'use strict';

// Same-origin API; credentials and inference URLs are never stored in the page.
const byId = id => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const statuses = {pending: 'Chờ xử lý', delivered: 'Đã giao', cancelled: 'Đã hủy'};
const reasons = {ordered_by_mistake: 'Tôi đặt nhầm', no_longer_needed: 'Tôi không còn cần'};
const money = value => new Intl.NumberFormat('vi-VN', {style: 'currency', currency: 'VND'}).format(value);
let token = '', orders = [], selected = 'O-101', pending = null, busy = false, conversationId = null;
let providerId = 'custom', providerOptions = [];
let canCancel = true;
const cookieAuth = document.body?.dataset.auth === 'cookie';
const persistentAccount = document.body?.dataset.dataMode === 'persistent-demo';
const sourceLabels = {interface: 'Hướng dẫn giao diện', store_data: 'Dữ liệu đơn hàng', llm_agent: 'Hội thoại model'};
function showContext(context) {
  byId('conversation-context').textContent = context?.order_id ? 'Đang trao đổi: ' + context.order_id
    : context?.product_id ? 'Đang trao đổi: sản phẩm ' + context.product_id : 'Chưa chọn đơn hoặc sản phẩm';
}
function selectedProvider() {
  return providerOptions.find(p => p.id === providerId);
}
function renderProvider() {
  const select = byId('model-provider'); select.replaceChildren();
  for (const provider of providerOptions) {
    const option = el('option', '', provider.label + (provider.configured ? '' : ' — Chưa cấu hình'));
    option.value = provider.id; option.disabled = !provider.configured;
    select.append(option);
  }
  select.value = providerId;
  const provider = selectedProvider();
  byId('provider-detail').textContent = provider ? provider.model + ' · ' +
    (provider.configured ? 'Đã cấu hình; gửi tin để kiểm tra kết nối.' : 'Nguồn model chưa được bật.') : '';
  byId('provider-notice').textContent = provider?.notice || '';
  document.querySelector('.model-status strong').textContent = provider?.configured ? 'Đã chọn nguồn model' : 'Model chưa sẵn sàng';
  document.querySelector('.model-status div span').textContent = provider?.label || 'Có thể dùng các nút tra đơn';
}
async function newConversation(nextProvider = providerId) {
  if (pending) {
    byId('model-provider').value = providerId;
    message('Bạn xử lý đề xuất đang chờ xác nhận trước khi đổi nguồn hoặc mở cuộc trò chuyện mới nhé.', 'assistant', 'interface');
    return;
  }
  const result = await api('/api/conversations', {provider_id: nextProvider});
  conversationId = result.conversation_id; providerId = result.provider_id;
  renderProvider(); showContext(result.context); byId('messages').replaceChildren();
  message('Phiên mới dùng ' + (selectedProvider()?.model || 'model đã chọn') +
    '. Gửi câu hỏi hoặc chọn đơn bên phải. Khi đổi nguồn, lịch sử bắt đầu lại; trạng thái đơn được giữ.', 'assistant', 'interface');
}
const lockPage = locked => {
  byId('login-shell').hidden = !locked;
  document.querySelectorAll('main, .sidebar').forEach(node => { node.inert = locked; });
};
lockPage(true);

async function api(path, body, extra = {}) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {...(cookieAuth ? {} : {Authorization: 'Bearer ' + token}), ...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...extra},
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: cookieAuth ? 'same-origin' : 'omit', cache: 'no-store', signal: AbortSignal.timeout(150000),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) lockPage(true);
    const error = new Error(result.message || 'Không hoàn tất yêu cầu.');
    error.trace = result.trace; throw error;
  }
  return result;
}

function message(text, role = 'assistant', source = null, model = null) {
  const row = el('div', 'message ' + role), label = el('div', 'message-label');
  label.append(el('span', role === 'assistant' ? 'mini-r' : '', role === 'assistant' ? 'R' : ''));
  label.append(document.createTextNode(role === 'user' ? 'Bạn' : 'RetailOps' + (source ? ' · ' + sourceLabels[source] : '') + (model ? ' · ' + model : '')));
  row.append(label, el('div', 'bubble', text)); byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

async function act(callback) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button, #model-provider').forEach(b => { if (!b.disabled) { b.dataset.busyDisabled = 'true'; b.disabled = true; } });
  try { await callback(); }
  catch (error) { message(error.message || 'Mất kết nối. Tải lại trạng thái trước khi thử tiếp.'); }
  finally {
    busy = false;
    document.querySelectorAll('[data-busy-disabled]').forEach(b => { b.disabled = false; delete b.dataset.busyDisabled; });
  }
}

function renderOrder() {
  const order = orders.find(o => o.id === selected), area = byId('order-details'); area.replaceChildren();
  const tabs = byId('order-tabs'); tabs.replaceChildren();
  for (const item of orders) {
    const active = item.id === selected, button = el('button', active ? 'selected' : '', item.id);
    button.dataset.order = item.id; button.setAttribute('aria-pressed', String(active));
    button.onclick = () => act(() => lookupOrder(item.id)); tabs.append(button);
  }
  byId('order-count').textContent = orders.length + ' đơn mẫu';
  if (!order) { area.append(el('p', 'order-empty', 'Chưa có thông tin đơn. Hãy kết nối hoặc tải lại dữ liệu.')); return; }
  const top = el('div', 'order-line'); top.append(el('h3', '', order.id), el('span', 'badge ' + order.status, statuses[order.status]));
  const item = el('div', 'item'), copy = el('div'); copy.append(el('strong', '', order.name), el('p', '', order.variant)); item.append(copy);
  const total = el('div', 'detail-row total'); total.append(el('span', '', 'Tổng cộng'), el('strong', '', money(order.amount)));
  area.append(top, el('p', 'order-date', 'Đơn giả lập · Phiên bản ' + order.version), item, total);
  area.append(el('p', 'order-policy', order.status === 'pending' ? 'Có thể yêu cầu hủy. Cần chọn lý do và xác nhận.' : order.status === 'delivered' ? 'Đơn đã giao không đủ điều kiện hủy.' : 'Đơn đã hủy. Trạng thái được lưu trên máy chủ.'));
  const lookup = el('button', 'order-action', 'Tra cứu đơn này'); lookup.onclick = () => act(() => lookupOrder(order.id)); area.append(lookup);
  if (canCancel) {
    const cancel = el('button', 'order-action', 'Yêu cầu hủy đơn này'); cancel.onclick = () => act(() => chooseReason(order.id)); area.append(cancel);
  } else { area.append(el('p', 'order-policy', 'Tài khoản của bạn có quyền xem; không được tạo yêu cầu hủy.')); }
}

const eventLabels = {order_viewed: 'Tra cứu đơn', cancellation_proposed: 'Tạo đề xuất hủy', order_cancelled: 'Đã xác nhận hủy', proposal_dismissed: 'Bỏ đề xuất', model_extraction: 'Model phân tích yêu cầu', model_unavailable: 'Không kết nối được model', chat_replied: 'Trả lời hội thoại', agent_replied: 'Model trả lời', agent_failed: 'Lượt chat chưa hoàn tất'};
async function refresh() {
  const [data, history] = await Promise.all([api('/api/orders'), api('/api/events')]); orders = data.orders;
  if (!orders.some(o => o.id === selected)) selected = orders[0]?.id;
  renderOrder(); const area = byId('activity'); area.replaceChildren();
  for (const event of history.events.slice(0, 8)) {
    const row = el('div', 'activity-item'), copy = el('div');
    copy.append(el('p', '', (eventLabels[event.kind] || event.kind) + (event.order_id ? ' · ' + event.order_id : '')),
      el('small', '', new Date(event.created_at * 1000).toLocaleString('vi-VN')));
    row.append(copy); area.append(row);
  }
  if (!history.events.length) area.append(el('p', 'activity-empty', 'Chưa có thao tác được ghi lại.'));
  byId('event-count').textContent = history.events.length + ' sự kiện gần nhất';
}

async function lookupOrder(id) {
  const result = await api('/api/conversations/' + conversationId + '/focus', {order_id: id}); selected = result.order.id;
  showContext(result.context); message(result.message, 'assistant', result.source); await refresh();
}

async function chooseReason(id) {
  if (!canCancel) { message('Tài khoản của bạn có quyền xem; không được tạo yêu cầu hủy.', 'assistant', 'interface'); return; }
  const result = await api('/api/conversations/' + conversationId + '/focus', {order_id: id});
  const order = result.order; showContext(result.context); selected = order.id; await refresh();
  if (order.status !== 'pending') { message('Đơn ' + id + ' ' + statuses[order.status].toLowerCase() + ', không đủ điều kiện hủy.'); return; }
  const row = message('Bạn chọn lý do hủy ' + id + ', rồi xem lại trước khi xác nhận nhé.', 'assistant', 'store_data');
  const card = el('div', 'proposal'), group = 'reason-' + crypto.randomUUID(); let reason = null;
  card.append(el('h3', '', 'Yêu cầu hủy · ' + id));
  const button = el('button', 'primary', 'Xem lại và xác nhận'); button.disabled = true;
  for (const [value, label] of Object.entries(reasons)) {
    const line = el('label'), input = el('input'); input.type = 'radio'; input.name = group; input.value = value;
    input.onchange = () => { reason = value; button.disabled = busy; };
    line.append(input, document.createTextNode(label)); card.append(line);
  }
  button.onclick = () => act(async () => {
    const proposal = await api('/api/cancellation-proposals', {order_id: id, order_version: order.version, cancel_reason: reason});
    pending = {...proposal, key: crypto.randomUUID()};
    card.querySelectorAll('button,input').forEach(n => { n.disabled = true; delete n.dataset.busyDisabled; });
    byId('confirm-title').textContent = 'Hủy đơn ' + proposal.order.id + '?';
    byId('confirm-description').textContent = proposal.order.name + ' · ' + money(proposal.order.amount) + '. Đề xuất có hiệu lực 10 phút.';
    byId('confirm-reason').textContent = reasons[proposal.reason];
    byId('confirm-error').textContent = ''; byId('confirm-dialog').showModal(); await refresh();
  });
  card.append(button, el('small', '', 'Chọn lý do rồi kiểm tra đơn trước khi xác nhận.')); row.append(card);
}

async function confirm() {
  if (!pending) return;
  try {
    const result = await api('/api/cancellation-proposals/' + pending.proposal_id + '/confirm', {confirmed: true}, {'Idempotency-Key': pending.key});
    pending = null; byId('confirm-dialog').close(); message(result.message + (result.replayed ? ' Đây là kết quả của lần xác nhận trước, không hủy lần thứ hai.' : ''));
    await refresh();
  } catch (error) {
    byId('confirm-error').textContent = error.message + ' Nếu mất mạng, bấm xác nhận lại sẽ dùng cùng mã yêu cầu để tránh thực hiện lặp.';
  }
}

async function dismiss() {
  if (!pending) { byId('confirm-dialog').close(); return; }
  try {
    const result = await api('/api/cancellation-proposals/' + pending.proposal_id + '/dismiss', {});
    pending = null; byId('confirm-dialog').close(); message(result.message); await refresh();
  } catch (error) { byId('confirm-error').textContent = error.message; }
}

function showTrace(row, trace, replayed = false) {
  if (!trace) return;
  const details = el('details', 'agent-trace');
  details.append(el('summary', '', 'Chi tiết lượt trả lời' + (replayed ? ' · Kết quả đã lưu' : '')));
  const names = trace.tools.map(t => t.name + (t.status === 'error' ? ' (bị từ chối / lỗi)' : ''));
  details.append(el('p', '', trace.model + ' · ' + trace.model_calls + ' lượt gọi model' +
    (trace.latency_ms !== undefined ? ' · ' + (trace.latency_ms / 1000).toFixed(2) + ' giây' : '')),
    el('p', '', 'Công cụ: ' + (names.join(' → ') || 'Không dùng công cụ ở lượt này')),
    el('small', '', 'Mã lượt: ' + trace.turn_id + (trace.model_digest ? ' · Digest: ' + trace.model_digest : ' · API không cung cấp digest trọng số')));
  if (trace.provider) details.append(el('small', '', 'Nguồn: ' + trace.provider));
  if (trace.reported_cost_usd !== null && trace.reported_cost_usd !== undefined) {
    details.append(el('small', '', 'Chi phí lượt này do API báo: $' + trace.reported_cost_usd.toFixed(6)));
  }
  row.append(details);
}

async function send(text, requestId = crypto.randomUUID(), retry = false) {
  text = text.trim(); if (!text) return;
  if (!retry) message(text, 'user');
  byId('message').value = '';
  const status = document.querySelector('.model-status');
  status.querySelector('strong').textContent = 'Model đang xử lý…';
  status.querySelector('div span').textContent = 'Đang đọc hội thoại và gọi công cụ khi cần';
  byId('messages').setAttribute('aria-busy', 'true');
  let result;
  try {
    result = await api('/api/chat', {text, conversation_id: conversationId, request_id: requestId});
  } catch (error) {
    const row = message(error.message || 'Mất kết nối trong lúc chờ model.', 'assistant', 'interface');
    showTrace(row, error.trace);
    const retryButton = el('button', 'order-action', 'Thử lại tin nhắn này');
    const originalConversation = conversationId;
    retryButton.onclick = () => act(async () => {
      if (conversationId !== originalConversation) return;
      retryButton.remove(); await send(text, requestId, true);
    });
    row.append(retryButton);
    status.querySelector('strong').textContent = 'Chat chưa hoàn tất';
    status.querySelector('div span').textContent = 'Có thể thử lại hoặc dùng các nút thao tác';
    return;
  } finally { byId('messages').removeAttribute('aria-busy'); }
  const row = message(result.message, 'assistant', result.source, result.trace?.model);
  showTrace(row, result.trace, result.replayed);
  if (result.replayed) {
    row.append(el('small', 'replay-note', 'Đây là câu trả lời đã lưu của lần gửi trước. Bảng đơn bên phải hiển thị trạng thái hiện tại.'));
  } else { showContext(result.context); }
  status.querySelector('strong').textContent = 'Model vừa phản hồi';
  status.querySelector('div span').textContent = 'Xem công cụ và thời gian bên dưới câu trả lời';
  if (result.action === 'choose_cancel_reason') await chooseReason(result.order.id);
  else await refresh();
}

async function openSession() {
  const session = await api('/api/session');
  canCancel = Array.isArray(session.permissions) ? session.permissions.includes('orders:cancel') : true;
  byId('profile-name').textContent = session.name || 'Khách hàng';
  byId('profile-avatar').textContent = (session.name || 'KH').slice(0, 2).toUpperCase();
  byId('profile-role').textContent = canCancel ? 'Khách hàng giả lập' : 'Chỉ xem dữ liệu mẫu';
  byId('greeting').textContent = 'XIN CHÀO, ' + (session.name || 'BẠN').toUpperCase();
  document.querySelectorAll('[data-prompt]').forEach(button => { button.hidden = persistentAccount; });
  byId('message').placeholder = persistentAccount ? 'Hỏi về đơn hàng hoặc sản phẩm của bạn…' : 'Ví dụ: Tôi muốn hủy đơn O-101…';
  const choices = await api('/api/providers'); providerOptions = choices.providers; providerId = choices.default_provider;
  await refresh();
  pending = null; conversationId = null;
  if (byId('confirm-dialog').open) byId('confirm-dialog').close();
  byId('demo-token').value = ''; lockPage(false); byId('messages').replaceChildren();
  await newConversation();
}
byId('login-form').onsubmit = async event => {
  event.preventDefault(); token = byId('demo-token').value.trim(); byId('login-error').textContent = '';
  const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try {
    if (cookieAuth) { await api('/api/login', {token}); token = ''; }
    await openSession();
  } catch (error) { token = ''; byId('login-error').textContent = error.message; }
  finally { button.disabled = false; }
};
byId('logout').onclick = () => act(async () => {
  if (cookieAuth) await api('/api/logout', {});
  token = ''; location.reload();
});
byId('chat-form').onsubmit = event => { event.preventDefault(); act(() => send(byId('message').value)); };
byId('message').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); act(() => send(event.target.value)); } };
document.querySelectorAll('[data-prompt]').forEach(b => { b.onclick = () => act(() => send(b.dataset.prompt)); });
byId('reset').onclick = () => act(async () => { await refresh(); message('Đã tải lại dữ liệu từ máy chủ.'); });
byId('new-conversation').onclick = () => act(() => newConversation());
byId('model-provider').onchange = () => {
  const requested = byId('model-provider').value;
  if (busy) { byId('model-provider').value = providerId; return; }
  act(async () => {
    try { await newConversation(requested); }
    finally { byId('model-provider').value = providerId; }
  });
};
byId('about').onclick = () => byId('about-dialog').showModal(); byId('close-about').onclick = () => byId('about-dialog').close();
byId('approve-confirm').onclick = () => act(confirm); byId('dismiss-confirm').onclick = () => act(dismiss);
byId('confirm-dialog').oncancel = event => { event.preventDefault(); act(dismiss); };
const error = el('p', 'proposal-error'); error.id = 'confirm-error'; error.setAttribute('role', 'alert');
byId('confirm-dialog').querySelector('.dialog-actions').before(error);
renderOrder();
if (cookieAuth) {
  byId('login-description').textContent = persistentAccount
    ? 'Nhập mã truy cập cá nhân do quản trị viên cấp. Phiên có hiệu lực 8 giờ. Đăng nhập lại để tiếp tục xem dữ liệu của tài khoản.'
    : 'Nhập mã mời từ chủ dự án. Mỗi khách có bộ đơn mẫu riêng. Phiên có hiệu lực 8 giờ. Đóng phiên sẽ kết thúc quyền truy cập bộ dữ liệu này.';
  byId('session-note').textContent = persistentAccount
    ? 'Dữ liệu mẫu thuộc tài khoản của bạn. Hết phiên hoặc đăng xuất vẫn giữ đơn hàng và nhật ký; đăng nhập lại để tiếp tục.'
    : 'Dữ liệu thuộc phiên demo riêng của bạn, có hiệu lực 8 giờ. Tải lại trang giữ trạng thái; đóng phiên rồi đăng nhập tạo bộ đơn mới.';
  const loginButton = byId('login-form').querySelector('button'); loginButton.disabled = true;
  openSession().catch(error => { lockPage(true); if (error.message && !/mã mời|phiên demo/i.test(error.message)) byId('login-error').textContent = error.message; })
    .finally(() => { loginButton.disabled = false; });
}
