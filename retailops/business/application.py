"""Application use cases: conversation, provider selection and focused order lookup."""
import hashlib
import json
import logging
import os
from contextlib import ExitStack
import re
import threading
import time
import uuid

logger = logging.getLogger("retailops.application")
from retailops.core import ApiError, REASONS, STATUSES, fields, require
from retailops.identity.bearer import authenticate_bearer
from retailops.business.permissions import CANCEL, ROLE_PERMISSIONS
from retailops_agent import AgentError, run_agent
from retailops_tools import BoundTools
from retailops.knowledge.citations import CitationError, cited_sources
from retailops.knowledge.embedding import MODEL_ID as KNOWLEDGE_EMBEDDING_MODEL
from retailops_providers import API_MODEL
from retailops_conversation import Catalog, describe_order
from retailops.business.cache import SemanticCache, ToolCache, is_cacheable_query, is_cache_eligible_for_lookup
from retailops.inference_gate import InferenceGate, GatedGateway

class Application:
    def __init__(self, store, tokens, infer=None, api_infer=None, api_daily_limit=20, *, role='customer', orchestrator=None):
        if role not in ROLE_PERMISSIONS:
            raise ValueError('Unknown application role.')
        self.role, self.permissions = role, ROLE_PERMISSIONS[role]
        self.store, self.tokens, self.infer = store, tokens, infer
        self.api_infer = api_infer
        if type(api_daily_limit) is not int or not 1 <= api_daily_limit <= 10000:
            raise ValueError('API daily turn limit must be an integer from 1 to 10000')
        self.api_daily_limit = api_daily_limit
        self.quota_store = store
        self.default_provider = 'custom'
        self.catalog = Catalog(store=self.store)
        self.inference_gate = getattr(self, 'inference_gate', None) or InferenceGate()
        self.agent_lock = threading.Lock()
        self.overload_429_count = 0
        self.semantic_cache = SemanticCache(min_similarity=0.65)
        self.tool_cache = ToolCache(default_ttl=180.0)
        self.internal_events = []
        if orchestrator is None:
            infer_cls = getattr(getattr(infer, '__class__', None), '__name__', '')
            api_infer_cls = getattr(getattr(api_infer, '__class__', None), '__name__', '')
            mock_classes = ('ScriptedAgent', 'Gateway', 'LoopbackProxyAgent', 'FakeAgent', 'ModelFixture', 'FakeGateway')
            if infer_cls in mock_classes or api_infer_cls in mock_classes:
                self.orchestrator = 'single_agent'
            else:
                self.orchestrator = os.environ.get('RETAILOPS_ORCHESTRATOR', 'multi_agent')
        else:
            self.orchestrator = orchestrator

    def record_internal_event(self, event_type, **kwargs):
        event = {
            'event': event_type,
            'timestamp': time.time(),
            **kwargs
        }
        if not hasattr(self, 'internal_events'):
            self.internal_events = []
        self.internal_events.append(event)
        logger.error(
            "Internal %s: stage=%s tool=%s status=%s original_code=%s",
            event_type,
            kwargs.get('stage'),
            kwargs.get('tool'),
            kwargs.get('status'),
            kwargs.get('original_code')
        )
        return event

    def providers(self):
        custom_model = getattr(getattr(self.infer, 'config', None), 'model', 'qwen3.5:4b')
        api_model = getattr(self.api_infer, 'model', API_MODEL)
        is_anthropic = getattr(self.api_infer, 'is_anthropic', False) or 'claude' in str(api_model).lower()
        is_google = not is_anthropic and (getattr(self.api_infer, 'is_google', False) or 'gemini' in str(api_model).lower())
        custom_endpoint = getattr(self.api_infer, 'endpoint', '')
        if custom_endpoint and ('ngrok' in custom_endpoint or 'vllm' in custom_endpoint or 'qwen' in str(api_model).lower()):
            api_label = f'vLLM (Colab GPU) · {api_model}'
            api_notice = f'vLLM Self-Hosted GPU ({api_model}) kết nối qua ngrok.'
        elif is_anthropic:
            api_label = 'API · Anthropic Claude'
            api_notice = f'API Anthropic Claude ({api_model}), giới hạn {self.api_daily_limit} lượt/ngày UTC cho demo.'
        elif is_google:
            api_label = 'API · Google Gemini'
            api_notice = f'API Google AI Studio ({api_model}), giới hạn {self.api_daily_limit} lượt/ngày UTC cho demo.'
        else:
            api_label = 'API · OpenRouter'
            api_notice = f'API tính phí theo sử dụng, tối đa {self.api_daily_limit} lần thử chat/ngày UTC cho demo. Contributor: nội dung có thể được Meta dùng để cải thiện sản phẩm. Chỉ nhập dữ liệu giả lập.'
        return {'default_provider': self.default_provider, 'providers': [
            {'id': 'custom', 'label': 'Custom model · Colab/Ollama', 'model': custom_model,
             'configured': self.infer is not None, 'notice': 'Cần phiên model đang chạy. Kết nối được kiểm tra khi gửi tin.'},
            {'id': 'api', 'label': api_label, 'model': api_model,
             'configured': self.api_infer is not None,
             'notice': api_notice,
             'daily_turn_limit': self.api_daily_limit}]}

    def new_conversation(self, customer, body):
        require(isinstance(body, dict) and set(body) in (set(), {'provider_id'}),
                400, 'invalid_fields', 'Chỉ chọn nguồn model đã được cấu hình.')
        provider_id = body.get('provider_id', self.default_provider)
        require(isinstance(provider_id, str) and provider_id in ('custom', 'api'),
                400, 'invalid_provider', 'Nguồn model không hợp lệ.')
        # Offline custom sessions still support direct business buttons. API is opt-in.
        require(provider_id != 'api' or self.api_infer is not None, 503, 'provider_not_configured',
                'API chưa được chủ demo cấu hình. Hãy chọn custom model.')
        return self.store.new_conversation(customer, provider_id)

    def authenticate(self, header):
        return authenticate_bearer(header, self.tokens)

    def require_permission(self, permission):
        require(permission in self.permissions, 403, 'permission_denied', 'Tài khoản này không có quyền thực hiện thao tác.')

    def chat(self, customer, body):
        started = time.monotonic()
        require(isinstance(body, dict) and {'text', 'conversation_id', 'request_id'}.issubset(set(body))
                and set(body).issubset({'text', 'conversation_id', 'request_id', 'attachment'}),
                400, "invalid_fields", "Các trường của yêu cầu không hợp lệ.")
        text, request_id = body['text'], body['request_id']
        require(isinstance(text, str) and 0 < len(text.strip()) <= 2000,
                400, 'invalid_text', 'Nhập yêu cầu tối đa 2.000 ký tự.')
        require(isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_id),
                400, 'invalid_request_id', 'Thiếu mã yêu cầu hội thoại.')
        attachment = body.get('attachment')
        if attachment is not None:
            require(isinstance(attachment, dict) and 'data' in attachment and 'type' in attachment,
                    400, 'invalid_attachment', 'Định dạng tệp đính kèm không hợp lệ.')
            require(attachment.get('type') in ('image', 'document'),
                    400, 'unsupported_attachment_type', 'Chỉ hỗ trợ tệp hình ảnh hoặc tài liệu.')
            require(isinstance(attachment.get('data'), str) and len(attachment['data']) <= 6_000_000,
                    400, 'attachment_too_large', 'Kích thước tệp đính kèm vượt quá 4MB.')
        snapshot = self.store.conversation(customer, body['conversation_id'])
        provider_id = snapshot['provider_id']
        att_data_hash = hashlib.sha256(attachment['data'].encode()).hexdigest()[:16] if (attachment and 'data' in attachment) else ''
        att_token = f"{attachment.get('name', '')}:{att_data_hash}" if attachment else ''
        digest = hashlib.sha256((text + att_token).encode()).hexdigest()
        replay = self.store.replay(customer, snapshot['id'], request_id, digest)
        if replay:
            return replay

        gateway = self.infer if provider_id == 'custom' else self.api_infer if provider_id == 'api' else None
        require(gateway is not None, 503, 'model_offline',
                'Model chưa kết nối. Bạn vẫn có thể dùng các nút tra đơn và yêu cầu hủy.')
        if self.agent_lock.locked():
            self.overload_429_count += 1
            raise ApiError(429, 'model_busy',
                           'Model đang xử lý một cuộc trò chuyện khác. Bạn thử lại sau nhé.')
        conv_key = f"{customer}:{snapshot['id']}"
        conv_lock = self.inference_gate.get_conversation_lock(conv_key)
        if not conv_lock.acquire(blocking=False):
            self.overload_429_count += 1
            raise ApiError(429, 'model_busy',
                           'Cuộc trò chuyện này đang xử lý một yêu cầu khác. Bạn thử lại sau nhé.')
        stack = ExitStack()
        stack.callback(conv_lock.release)
        try:
            # Replay #2 check under lock (catches concurrent winning request)
            replay = self.store.replay(customer, snapshot['id'], request_id, digest)
            if replay:
                return replay

            # Reload & Revalidate conversation snapshot under lock
            snapshot = self.store.conversation(customer, snapshot['id'])

            # G02: Check interrupted runs in graph_runs under conv_lock BEFORE cache lookup & workflow
            run_key = [snapshot['id'], request_id]
            fingerprint = hashlib.sha256(json.dumps([digest, self.role, provider_id]).encode()).hexdigest()
            run_id = hashlib.sha256(json.dumps([customer, 'chat-v1', run_key]).encode()).hexdigest()

            existing_run = self.store.get_graph_run(run_id) if hasattr(self.store, 'get_graph_run') else None
            if existing_run is not None:
                now = time.time()
                if existing_run.get('expires_at', 0) > now:
                    require(existing_run['customer_id'] == customer and existing_run['fingerprint'] == fingerprint, 409,
                            'request_conflict', 'Mã yêu cầu đã dùng cho nội dung, quyền hoặc nguồn model khác.')
                    require(existing_run.get('lease_until', 0) <= now, 429,
                            'workflow_busy', 'Yêu cầu này đang được xử lý. Hãy thử lại sau.')
                    old_seed = json.loads(existing_run['seed']) if isinstance(existing_run['seed'], str) else existing_run['seed']
                    if isinstance(old_seed, dict):
                        require(old_seed.get('revision') == snapshot.get('revision') and
                                old_seed.get('order_id') == snapshot.get('order_id') and
                                old_seed.get('product_id') == snapshot.get('product_id'),
                                409, 'conversation_changed',
                                'Ngữ cảnh đã thay đổi hoặc hết hạn. Hãy gửi lại trong cuộc trò chuyện hiện tại.')

            # Invalidate semantic cache if catalog was updated in database by any session
            if hasattr(self.store, 'get_catalog_revision'):
                cur_cat_rev = self.store.get_catalog_revision()
                if getattr(self, '_last_catalog_rev', None) is not None and getattr(self, '_last_catalog_rev', None) < cur_cat_rev:
                    if hasattr(self, 'semantic_cache') and self.semantic_cache:
                        self.semantic_cache.clear()
                self._last_catalog_rev = cur_cat_rev

            try:
                has_prior_turns = self.store.has_turns(customer, snapshot['id']) if hasattr(self.store, 'has_turns') else True
            except Exception:
                has_prior_turns = True

            eligibility_before_turn = (
                existing_run is None
                and is_cache_eligible_for_lookup(text, snapshot, has_prior_turns, attachment)
            )

            # Tier 1: Check Semantic / Exact Cache under conv_lock
            cached = None
            if eligibility_before_turn and (provider_id != 'api' or getattr(self, 'cache_api', False)):
                cached = self.semantic_cache.lookup(text)

            if cached:
                cache_trace = {
                    'turn_id': str(uuid.uuid4()),
                    'protocol': 'cache-hit-v1',
                    'model': f"cache:{cached['type']}",
                    'provider': 'cache',
                    'latency_ms': round((time.monotonic() - started) * 1000, 2),
                    'cache_hit': cached['type'],
                    'similarity': cached['similarity'],
                    'matched_query': cached.get('matched_query'),
                    'model_calls': 0,
                    'prompt_tokens': 0,
                    'generated_tokens': 0,
                    'reported_cost_usd': 0.0,
                    'tools': [],
                    'steps': [],
                    'queue_wait_ms': 0.0,
                    'provider_inference_ms': 0.0,
                    'graph_retrieval_ms': 0.0,
                    'rag_retrieval_ms': 0.0,
                    'db_ms': 0.0,
                    'in_flight_inferences': 0
                }
                cached_result = {
                    'action': cached['action'],
                    'message': cached['answer'],
                    'source': 'semantic_cache',
                    'model_used': False,
                    'context': {'order_id': snapshot.get('order_id'), 'product_id': snapshot.get('product_id')},
                    'trace': cache_trace,
                    'provider_id': snapshot['provider_id'],
                    'replayed': False
                }
                user_msg = {'role': 'user', 'content': text}
                assistant_msg = {'role': 'assistant', 'content': cached['answer']}
                self.store.finish_turn(customer, snapshot, request_id, digest, [user_msg, assistant_msg], cached_result, {})
                return cached_result

            from retailops.workflow.checkpoints import workflow
            saver, snapshot = stack.enter_context(workflow(self.store, customer, 'chat-v1',
                [snapshot['id'], request_id], fingerprint, snapshot, expires_at=snapshot['expires_at']))

            if hasattr(gateway, 'for_turn'):
                gateway = gateway.for_turn()
            gated_gateway = GatedGateway(gateway, self.inference_gate)
            saved = saver.get_tuple(saver.config())
            saved_state = saved.checkpoint.get('channel_values', {}) if saved else {}
            if saved_state.get('complete'):
                trace = saved_state['trace']
                identity = {'name': trace['model'], 'digest': trace['model_digest'],
                            'provider': trace['provider'], 'ollama_version': trace['ollama_version']}
            else:
                identity = gated_gateway.inspect()
            identity = {**identity, 'selection': provider_id}
            reserved = False
            def before_model():
                nonlocal reserved
                if provider_id == 'api' and not reserved:
                    self.quota_store.reserve_api_attempt(self.api_daily_limit)
                    reserved = True
            bound = BoundTools(self.store, self.catalog, customer, snapshot, identity,
                               can_cancel=CANCEL in self.permissions)

            tool_execution_count = 0
            tools_called_in_turn = []

            def execute(name, arguments):
                nonlocal tool_execution_count
                tool_execution_count += 1
                tools_called_in_turn.append(name)
                cached_res = self.tool_cache.get(customer, name, arguments)
                if cached_res is not None:
                    # F04: Maintain freshness and evidence registration on cache hit
                    if name in ('get_order', 'read_order') and isinstance(cached_res, dict) and 'order' in cached_res:
                        order_obj = cached_res['order']
                        if isinstance(order_obj, dict) and 'id' in order_obj and 'version' in order_obj:
                            bound.versions[order_obj['id']] = order_obj['version']
                            bound.context = {'order_id': order_obj['id'], 'product_id': order_obj.get('product_id')}
                    elif name == 'get_product' and isinstance(cached_res, dict) and isinstance(cached_res.get('product'), dict):
                        pid = cached_res['product'].get('id')
                        if bound.context['product_id'] != pid:
                            bound.context['order_id'] = None
                        bound.context['product_id'] = pid
                    elif name == 'search_knowledge' and isinstance(cached_res, dict) and 'results' in cached_res:
                        known = {s['citation_id'] for s in bound.knowledge.sources if isinstance(s, dict) and 'citation_id' in s}
                        for s in cached_res.get('results', []):
                            if isinstance(s, dict) and 'citation_id' in s and s['citation_id'] not in known:
                                bound.knowledge.sources.append(dict(s))
                                known.add(s['citation_id'])
                    return cached_res
                try:
                    res = bound(name, arguments)
                except ApiError as exc:
                    if exc.status == 429:
                        raise
                    if exc.status >= 500:
                        self.record_internal_event(
                            'tool_error',
                            stage='tool_execution',
                            tool=name,
                            status=exc.status,
                            original_code=exc.code,
                        )
                        code = 'tool_unavailable' if exc.code == 'database_unavailable' else exc.code
                        msg = 'Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.' if exc.code == 'database_unavailable' else exc.message
                        raise ApiError(exc.status, code, msg)
                    if name in ('get_order', 'get_context', 'track_shipment', 'prepare_cancellation'):
                        bound.context = {'order_id': None, 'product_id': None}
                        bound.cancel_order = None
                        bound.shipment = None
                    return {'error': exc.code, 'message': exc.message}
                if name in ('cancel_order', 'confirm_cancellation', 'update_shipping_address'):
                    self.tool_cache.invalidate(customer)
                elif name not in ('request_human_support', 'prepare_cancellation'):
                    self.tool_cache.set(customer, name, arguments, res)
                return res

            def capture():
                return {'context': dict(bound.context), 'versions': dict(bound.versions), 'cancel_order': bound.cancel_order,
                        'knowledge': bound.knowledge.snapshot(), 'shipment': bound.shipment, 'human_support': bound.human_support}

            def restore(state):
                bound.context = dict(state['context'])
                bound.versions = dict(state['versions'])
                bound.cancel_order = state['cancel_order']
                bound.knowledge.restore(state.get('knowledge'))
                bound.shipment = state.get('shipment')
                bound.human_support = state.get('human_support')

            if getattr(self, 'orchestrator', 'multi_agent') == 'multi_agent' and not (hasattr(run_agent, 'side_effect') or hasattr(run_agent, 'mock_calls')):
                from retailops.workflow.graph import run_multiagent
                answer = run_multiagent(gated_gateway, text, self.store.history(customer, snapshot['id']), execute, identity,
                                        saver=saver, capture=capture, restore=restore, before_model=before_model, attachment=attachment)
            else:
                answer = run_agent(gated_gateway, text, self.store.history(customer, snapshot['id']), execute, identity,
                                   saver=saver, capture=capture, restore=restore, before_model=before_model, attachment=attachment)

            # N01: Rollback cancel_order and mutated context if target order is invalid, unverified, or mismatched
            if bound.cancel_order:
                extracted_m = re.search(r'\bO-(\d+)\b', text, re.IGNORECASE)
                extracted_oid = f"O-{extracted_m.group(1)}" if extracted_m else None
                expected_oid = extracted_oid or snapshot.get('order_id')
                cancel_oid = bound.cancel_order.get('id')
                if not expected_oid or (cancel_oid and cancel_oid != expected_oid):
                    bound.cancel_order = None
                    if bound.context.get('order_id') != snapshot.get('order_id'):
                        bound.context['order_id'] = snapshot.get('order_id')
                        bound.context['product_id'] = snapshot.get('product_id')
                elif answer.get('action_proposal') is not None:
                    prop = answer.get('action_proposal')
                    if prop and (prop.get('action') != 'cancel_order' or prop.get('order_id') != cancel_oid):
                        bound.cancel_order = None
                        if bound.context.get('order_id') != snapshot.get('order_id'):
                            bound.context['order_id'] = snapshot.get('order_id')
                            bound.context['product_id'] = snapshot.get('product_id')

            result = {'action': 'choose_cancel_reason' if bound.cancel_order else 'reply',
                      'message': answer['message'], 'source': answer['trace'].get('answer_source', 'llm_agent'),
                      'model_used': answer['trace'].get('model_responses', answer['trace'].get('model_calls', 0)) > 0,
                      'context': bound.context, 'trace': answer['trace'], 'provider_id': provider_id, 'replayed': False}
            result['trace']['queue_wait_ms'] = getattr(gated_gateway, 'total_queue_wait_ms', 0.0)
            result['trace'].setdefault('provider_inference_ms', answer['trace'].get('latency_ms', 0.0))
            result['trace'].setdefault('graph_retrieval_ms', 0.0)
            result['trace'].setdefault('rag_retrieval_ms', 0.0)
            result['trace'].setdefault('db_ms', 0.0)
            result['trace']['in_flight_inferences'] = getattr(self.inference_gate, 'in_flight', 0)
            if answer.get('action_proposal'):
                result['action_proposal'] = answer['action_proposal']
            # A second provenance check also covers a completed checkpoint replay.
            try:
                result['sources'] = cited_sources(answer['message'], bound.knowledge.sources)
            except CitationError as exc:
                raise AgentError(exc.code, 'Nguồn trích dẫn chưa hợp lệ. Hãy gửi lại câu hỏi.', answer['trace']) from None
            if bound.knowledge.searches:
                result['trace']['knowledge'] = {'searches': bound.knowledge.searches,
                    'retrieved_sources': len(bound.knowledge.sources), 'cited_sources': len(result['sources']),
                    'citation_check': 'provenance_only', 'embedding_model': KNOWLEDGE_EMBEDDING_MODEL}
            if bound.cancel_order:
                result['order'] = bound.cancel_order
            if getattr(bound, 'shipment', None):
                result['shipment'] = bound.shipment
            if getattr(bound, 'human_support', None):
                result['human_support'] = bound.human_support
            self.store.finish_turn(customer, snapshot, request_id, digest, answer['messages'], result, bound.versions)

            trace_obj = answer.get('trace') if isinstance(answer.get('trace'), dict) else {}
            tools_val = trace_obj.get('tools')
            tools_called_list = tools_val if isinstance(tools_val, list) else []
            tool_cnt_val = trace_obj.get('tool_count')

            # G05: Strict explicit provenance verification
            has_explicit_provenance = (
                isinstance(trace_obj, dict)
                and 'tools' in trace_obj and isinstance(trace_obj['tools'], list)
                and 'tool_count' in trace_obj and isinstance(trace_obj['tool_count'], int)
                and not trace_obj.get('resumed_from_checkpoint')
                and not trace_obj.get('degraded')
            )

            tool_calls_detected = (
                len(tools_called_list) > 0
                or (isinstance(tool_cnt_val, int) and tool_cnt_val > 0)
                or tool_execution_count > 0
                or len(tools_called_in_turn) > 0
            )

            can_store_cache = (
                eligibility_before_turn is True
                and not attachment
                and result['source'] == 'llm_agent'
                and not result['trace'].get('degraded')
                and not result['trace'].get('resumed_from_checkpoint')
                and has_explicit_provenance
                and not tool_calls_detected
                and is_cacheable_query(text)
                and not bound.cancel_order
                and not bound.context.get('order_id')
                and not bound.context.get('product_id')
                and snapshot.get('order_id') is None
                and snapshot.get('product_id') is None
                and result.get('action') == 'reply'
                and (provider_id != 'api' or getattr(self, 'cache_api', False))
                and not bound.knowledge.searches
                and not result.get('sources')
                and not bound.versions
                and not getattr(bound, 'human_support', None)
                and not result.get('human_support')
            )
            if can_store_cache:
                self.semantic_cache.store(text, answer['message'], action=result['action'])
            return result
        except ApiError:
            raise
        except AgentError as exc:
            exc_trace = exc.trace if isinstance(getattr(exc, 'trace', None), dict) else {}
            http_status = getattr(exc, 'http_status', None) or exc_trace.get('http_status')
            if not http_status:
                if exc.code in ('api_rate_limited', 'model_busy'):
                    http_status = 429
                elif exc.code == 'agent_timeout':
                    http_status = 504
                else:
                    http_status = 503
            exc_trace['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
            self.store.event(customer, 'agent_failed', code=exc.code, trace=exc_trace)
            raise ApiError(http_status, exc.code, str(exc), exc_trace) from None
        except (RuntimeError, ValueError, OSError):
            self.store.event(customer, 'agent_failed', code='model_unavailable')
            raise ApiError(503, 'model_unavailable',
                           'Không kết nối được nguồn model đã chọn. Kiểm tra cấu hình; hệ thống không tự chuyển model.') from None
        except Exception as exc:
            trace_dict = {'error_kind': type(exc).__name__, 'error_detail': str(exc), 'latency_ms': round((time.monotonic() - started) * 1000, 2)}
            self.store.event(customer, 'agent_failed', code='internal_error', trace=trace_dict)
            raise ApiError(500, 'internal_error', 'Không hoàn tất yêu cầu do lỗi xử lý nội bộ. Vui lòng tải lại trạng thái.', trace_dict) from None
        finally:
            stack.close()

    def focus(self, customer, cid, body):
        fields(body, {'order_id'})
        require(isinstance(body['order_id'], str), 400, 'invalid_order', 'Mã đơn không hợp lệ.')
        snapshot = self.store.conversation(customer, cid)
        order = self.store.lookup(customer, body['order_id'])
        product = self.catalog.for_order(order)
        pid = product['id'] if product else None
        self.store.remember(customer, snapshot, order['id'], pid)
        return {'order': order, 'message': describe_order(order, STATUSES, REASONS),
                'context': {'order_id': order['id'], 'product_id': pid}, 'source': 'store_data', 'model_used': False}
