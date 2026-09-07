"""Application use cases: conversation, provider selection and focused order lookup."""
import hashlib
import json
from contextlib import ExitStack
import re
import threading
from retailops.core import ApiError, REASONS, STATUSES, fields, require
from retailops.identity.bearer import authenticate_bearer
from retailops.business.permissions import CANCEL, ROLE_PERMISSIONS
from retailops_agent import AgentError, run_agent
from retailops_tools import BoundTools
from retailops_providers import API_MODEL
from retailops_conversation import Catalog, describe_order

class Application:
    def __init__(self, store, tokens, infer=None, api_infer=None, api_daily_limit=20, *, role='customer'):
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
        self.catalog = Catalog()
        self.knowledge = None
        self.agent_lock = threading.Lock()

    def providers(self):
        custom_model = getattr(getattr(self.infer, 'config', None), 'model', 'qwen3.5:4b')
        api_model = getattr(self.api_infer, 'model', API_MODEL)
        return {'default_provider': self.default_provider, 'providers': [
            {'id': 'custom', 'label': 'Custom model · Colab/Ollama', 'model': custom_model,
             'configured': self.infer is not None, 'notice': 'Cần phiên model đang chạy. Kết nối được kiểm tra khi gửi tin.'},
            {'id': 'api', 'label': 'API · OpenRouter', 'model': api_model,
             'configured': self.api_infer is not None,
             'notice': f'API tính phí theo sử dụng, tối đa {self.api_daily_limit} lần thử chat/ngày UTC cho demo. Contributor: nội dung có thể được Meta dùng để cải thiện sản phẩm. Chỉ nhập dữ liệu giả lập.',
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
        fields(body, {'text', 'conversation_id', 'request_id'})
        text, request_id = body['text'], body['request_id']
        require(isinstance(text, str) and 0 < len(text.strip()) <= 2000,
                400, 'invalid_text', 'Nhập yêu cầu tối đa 2.000 ký tự.')
        require(isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_id),
                400, 'invalid_request_id', 'Thiếu mã yêu cầu hội thoại.')
        snapshot = self.store.conversation(customer, body['conversation_id'])
        digest = hashlib.sha256(text.encode()).hexdigest()
        replay = self.store.replay(customer, snapshot['id'], request_id, digest)
        if replay:
            return replay
        provider_id = snapshot['provider_id']
        gateway = self.infer if provider_id == 'custom' else self.api_infer if provider_id == 'api' else None
        require(gateway is not None, 503, 'model_offline',
                'Model chưa kết nối. Bạn vẫn có thể dùng các nút tra đơn và yêu cầu hủy.')
        require(self.agent_lock.acquire(blocking=False), 429, 'model_busy',
                'Model đang xử lý một cuộc trò chuyện khác. Bạn thử lại sau nhé.')
        stack = ExitStack()
        try:
            from retailops.workflow.checkpoints import workflow
            fingerprint = hashlib.sha256(json.dumps([digest, self.role, provider_id, bool(self.knowledge)]).encode()).hexdigest()
            saver, snapshot = stack.enter_context(workflow(self.store, customer, 'chat-v1',
                [snapshot['id'], request_id], fingerprint, snapshot, expires_at=snapshot['expires_at']))
            # A concurrent completed retry must not spend GPU or duplicate history.
            replay = self.store.replay(customer, snapshot['id'], request_id, digest)
            if replay:
                return replay
            if hasattr(gateway, 'for_turn'):
                gateway = gateway.for_turn()
            saved = saver.get_tuple(saver.config())
            saved_state = saved.checkpoint.get('channel_values', {}) if saved else {}
            if saved_state.get('complete'):
                trace = saved_state['trace']
                identity = {'name': trace['model'], 'digest': trace['model_digest'],
                            'provider': trace['provider'], 'ollama_version': trace['ollama_version']}
            else:
                identity = gateway.inspect()
            identity = {**identity, 'selection': provider_id}
            if self.knowledge is not None and provider_id == 'custom' and not saved_state.get('complete'):
                require('knowledge-v1' in identity.get('capabilities', []), 503, 'proxy_upgrade_required',
                        'RAG cần notebook Colab mới có công cụ tra tài liệu. Hãy cập nhật proxy.')
            reserved = False
            def before_model():
                nonlocal reserved
                if provider_id == 'api' and not reserved:
                    self.quota_store.reserve_api_attempt(self.api_daily_limit)
                    reserved = True
            bound = BoundTools(self.store, self.catalog, customer, snapshot, identity,
                               can_cancel=CANCEL in self.permissions, knowledge=self.knowledge)

            def execute(name, arguments):
                try:
                    return bound(name, arguments)
                except ApiError as exc:
                    if name in ('get_order', 'prepare_cancellation'):
                        bound.context = {'order_id': None, 'product_id': None}
                        bound.cancel_order = None
                    return {'error': exc.code, 'message': exc.message}

            def capture():
                return {'context': dict(bound.context), 'versions': dict(bound.versions), 'cancel_order': bound.cancel_order, 'citations': list(bound.citations)}

            def restore(state):
                bound.context = dict(state['context'])
                bound.versions = dict(state['versions'])
                bound.cancel_order = state['cancel_order']
                bound.citations = list(state.get('citations', []))

            answer = run_agent(gateway, text, self.store.history(customer, snapshot['id']), execute, identity,
                               saver=saver, capture=capture, restore=restore, before_model=before_model)
            used = set(re.findall(r'\[K([0-9]+)\]', answer['message']))
            known = {c['ref'][1:] for c in bound.citations}
            require(used <= known and (not known or bool(used)), 503, 'invalid_citation',
                    'Model chưa trích dẫn đúng tài liệu. Hãy tạo câu trả lời mới hoặc nêu câu hỏi cụ thể hơn.')
            citations = [c for c in bound.citations if c['ref'][1:] in used]
            result = {'action': 'choose_cancel_reason' if bound.cancel_order else 'reply',
                      'message': answer['message'], 'source': 'llm_agent', 'model_used': True,
                      'context': bound.context, 'trace': answer['trace'], 'citations': citations, 'provider_id': provider_id, 'replayed': False}
            if bound.cancel_order:
                result['order'] = bound.cancel_order
            self.store.finish_turn(customer, snapshot, request_id, digest, answer['messages'], result, bound.versions)
            return result
        except AgentError as exc:
            self.store.event(customer, 'agent_failed', code=exc.code, trace=exc.trace)
            raise ApiError(503, exc.code, str(exc), exc.trace) from None
        except (RuntimeError, ValueError, OSError):
            self.store.event(customer, 'agent_failed', code='model_unavailable')
            raise ApiError(503, 'model_unavailable',
                           'Không kết nối được nguồn model đã chọn. Kiểm tra cấu hình; hệ thống không tự chuyển model.') from None
        finally:
            try:
                stack.close()
            finally:
                self.agent_lock.release()

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
