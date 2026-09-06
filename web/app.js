'use strict';

// Same-origin API; credentials and inference URLs are never stored in the page.
const byId = id => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const statuses = {pending: 'Chờ xử lý', delivered: 'Đã giao', cancelled: 'Đã hủy'};
const reasons = {ordered_by_mistake: 'Tôi đặt nhầm', no_longer_needed: 'Tôi không còn cần'};
const money = value => new Intl.NumberFormat('vi-VN', {style: 'currency', currency: 'VND'}).format(value);
let token = '', orders = [], selected = 'O-101', pending = null, busy = false, conversationId = null;
const sourceLabels = {assistant_rules: 'Hướng dẫn hỗ trợ', store_data: 'Dữ liệu đơn hàng', catalog: 'Danh mục sản phẩm mẫu', model_and_store: 'Model nhận diện · Backend trả lời'};
function showContext(context) {
  byId('conversation-context').textContent = context?.order_id ? 'Đang trao đổi: ' + context.order_id
    : context?.product_id ? 'Đang trao đổi: sản phẩm ' + context.product_id : 'Chưa chọn đơn hoặc sản phẩm';
}
async function newConversation() {
  if (pending) { message('Bạn xử lý đề xuất đang chờ xác nhận trước khi mở cuộc trò chuyện mới nhé.'); return; }
  const result = await api('/api/conversations', {}); conversationId = result.conversation_id;
  showContext(result.context); byId('messages').replaceChildren();
  message('Chào bạn! Mình có thể tra đầy đủ thông tin đơn, giải thích sản phẩm trong danh mục và hỗ trợ yêu cầu hủy. Bạn muốn xem mục nào?', 'assistant', 'assistant_rules');
}
const lockPage = locked => {
  byId('login-shell').hidden = !locked;
  document.querySelectorAll('main, .sidebar').forEach(node => { node.inert = locked; });
};
lockPage(true);

async function api(path, body, extra = {}) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {Authorization: 'Bearer ' + token, ...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...extra},
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'omit', cache: 'no-store', signal: AbortSignal.timeout(90000),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) lockPage(true);
    throw new Error(result.message || 'Không hoàn tất yêu cầu.');
  }
  return result;
}

function message(text, role = 'assistant', source = null) {
  const row = el('div', 'message ' + role), label = el('div', 'message-label');
  label.append(el('span', role === 'assistant' ? 'mini-r' : '', role === 'assistant' ? 'R' : ''));
  label.append(document.createTextNode(role === 'user' ? 'Bạn' : 'RetailOps' + (source ? ' · ' + sourceLabels[source] : '')));
  row.append(label, el('div', 'bubble', text)); byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

async function act(callback) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(b => { if (!b.disabled) { b.dataset.busyDisabled = 'true'; b.disabled = true; } });
  try { await callback(); }
  catch (error) { message(error.message || 'Mất kết nối. Tải lại trạng thái trước khi thử tiếp.'); }
  finally {
    busy = false;
    document.querySelectorAll('[data-busy-disabled]').forEach(b => { b.disabled = false; delete b.dataset.busyDisabled; });
  }
}

function renderOrder() {
  const order = orders.find(o => o.id === selected), area = byId('order-details'); area.replaceChildren();
  document.querySelectorAll('[data-order]').forEach(b => {
    const active = b.dataset.order === selected; b.classList.toggle('selected', active); b.setAttribute('aria-pressed', String(active));
  });
  if (!order) { area.append(el('p', 'order-empty', 'Chưa có thông tin đơn. Hãy kết nối hoặc tải lại dữ liệu.')); return; }
  const top = el('div', 'order-line'); top.append(el('h3', '', order.id), el('span', 'badge ' + order.status, statuses[order.status]));
  const item = el('div', 'item'), copy = el('div'); copy.append(el('strong', '', order.name), el('p', '', order.variant)); item.append(copy);
  const total = el('div', 'detail-row total'); total.append(el('span', '', 'Tổng cộng'), el('strong', '', money(order.amount)));
  area.append(top, el('p', 'order-date', 'Đơn giả lập · Phiên bản ' + order.version), item, total);
  area.append(el('p', 'order-policy', order.status === 'pending' ? 'Có thể yêu cầu hủy. Cần chọn lý do và xác nhận.' : order.status === 'delivered' ? 'Đơn đã giao không đủ điều kiện hủy.' : 'Đơn đã hủy. Trạng thái được lưu trên máy chủ.'));
  const lookup = el('button', 'order-action', 'Tra cứu đơn này'); lookup.onclick = () => act(() => lookupOrder(order.id)); area.append(lookup);
  const cancel = el('button', 'order-action', 'Yêu cầu hủy đơn này'); cancel.onclick = () => act(() => chooseReason(order.id)); area.append(cancel);
}

const eventLabels = {order_viewed: 'Tra cứu đơn', cancellation_proposed: 'Tạo đề xuất hủy', order_cancelled: 'Đã xác nhận hủy', proposal_dismissed: 'Bỏ đề xuất', model_extraction: 'Model phân tích yêu cầu', model_unavailable: 'Không kết nối được model', chat_replied: 'Trả lời hội thoại'};
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

async function send(text) {
  text = text.trim(); if (!text) return;
  message(text, 'user'); byId('message').value = '';
  const status = document.querySelector('.model-status');
  try {
    const result = await api('/api/chat', {text, conversation_id: conversationId}); message(result.message, 'assistant', result.source);
    showContext(result.context);
    if (result.model_used) {
      status.querySelector('strong').textContent = 'Model vừa phản hồi'; status.querySelector('div span').textContent = 'Qwen nhận diện · Backend kiểm tra';
    }
    if (result.order) selected = result.order.id;
    if (result.action === 'choose_cancel_reason') await chooseReason(result.order.id);
    else await refresh();
  } catch (error) {
    showContext(null);
    status.querySelector('strong').textContent = 'Chat chưa hoàn tất'; status.querySelector('div span').textContent = 'Có thể dùng các nút tra / hủy đơn'; throw error;
  }
}

byId('login-form').onsubmit = async event => {
  event.preventDefault(); token = byId('demo-token').value.trim(); byId('login-error').textContent = '';
  const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try {
    const session = await api('/api/session'); await refresh();
    byId('demo-token').value = ''; lockPage(false); byId('messages').replaceChildren();
    document.querySelector('.model-status strong').textContent = session.model_configured ? 'Đã cấu hình model' : 'Model chưa kết nối';
    document.querySelector('.model-status div span').textContent = session.model_configured ? 'Gửi câu chat để kiểm tra kết nối' : 'Tra đơn bằng nút vẫn hoạt động';
    await newConversation();
  } catch (error) { token = ''; byId('login-error').textContent = error.message; }
  finally { button.disabled = false; }
};
byId('logout').onclick = () => { token = ''; location.reload(); };
byId('chat-form').onsubmit = event => { event.preventDefault(); act(() => send(byId('message').value)); };
byId('message').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); act(() => send(event.target.value)); } };
document.querySelectorAll('[data-prompt]').forEach(b => { b.onclick = () => act(() => send(b.dataset.prompt)); });
document.querySelectorAll('[data-order]').forEach(b => { b.onclick = () => act(() => lookupOrder(b.dataset.order)); });
byId('reset').onclick = () => act(async () => { await refresh(); message('Đã tải lại dữ liệu từ máy chủ.'); });
byId('new-conversation').onclick = () => act(newConversation);
byId('about').onclick = () => byId('about-dialog').showModal(); byId('close-about').onclick = () => byId('about-dialog').close();
byId('approve-confirm').onclick = () => act(confirm); byId('dismiss-confirm').onclick = () => act(dismiss);
byId('confirm-dialog').oncancel = event => { event.preventDefault(); act(dismiss); };
const error = el('p', 'proposal-error'); error.id = 'confirm-error'; error.setAttribute('role', 'alert');
byId('confirm-dialog').querySelector('.dialog-actions').before(error);
renderOrder();
