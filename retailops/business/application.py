"""Application use cases: conversation, provider selection and focused order lookup."""
import hashlib
import re
import threading
from retailops.core import ApiError, REASONS, STATUSES, fields, require
from retailops.identity.bearer import authenticate_bearer
from retailops_agent import AgentError, run_agent
from retailops_tools import BoundTools
from retailops_providers import API_MODEL
from retailops_conversation import Catalog, describe_order

class Application:
    def __init__(self, store, tokens, infer=None, api_infer=None, api_daily_limit=20):
        self.store, self.tokens, self.infer = store, tokens, infer
        self.api_infer = api_infer
        if type(api_daily_limit) is not int or not 1 <= api_daily_limit <= 10000:
            raise ValueError('API daily turn limit must be an integer from 1 to 10000')
        self.api_daily_limit = api_daily_limit
        self.quota_store = store
        self.default_provider = 'custom'
        self.catalog = Catalog()
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
        try:
            # A concurrent completed retry must not spend GPU or duplicate history.
            replay = self.store.replay(customer, snapshot['id'], request_id, digest)
            if replay:
                return replay
            if hasattr(gateway, 'for_turn'):
                gateway = gateway.for_turn()
            identity = {**gateway.inspect(), 'selection': provider_id}
            if provider_id == 'api':
                self.quota_store.reserve_api_attempt(self.api_daily_limit)
            bound = BoundTools(self.store, self.catalog, customer, snapshot, identity)

            def execute(name, arguments):
                try:
                    return bound(name, arguments)
                except ApiError as exc:
                    if name in ('get_order', 'prepare_cancellation'):
                        bound.context = {'order_id': None, 'product_id': None}
                        bound.cancel_order = None
                    return {'error': exc.code, 'message': exc.message}

            answer = run_agent(gateway, text, self.store.history(customer, snapshot['id']), execute, identity)
            result = {'action': 'choose_cancel_reason' if bound.cancel_order else 'reply',
                      'message': answer['message'], 'source': 'llm_agent', 'model_used': True,
                      'context': bound.context, 'trace': answer['trace'], 'provider_id': provider_id, 'replayed': False}
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
