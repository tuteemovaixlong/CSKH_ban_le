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
let isHumanMode = false, currentRating = 5;
const ratingLabels = {
  1: 'Rất không hài lòng (1/5 sao)',
  2: 'Không hài lòng (2/5 sao)',
  3: 'Bình thường (3/5 sao)',
  4: 'Hài lòng (4/5 sao)',
  5: 'Rất hài lòng (5/5 sao)'
};
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
function setModelStatus(title, detail) {
  const titleNode = byId('model-status-title'), detailNode = byId('model-status-detail');
  titleNode.textContent = title; titleNode.title = title;
  detailNode.textContent = detail; detailNode.title = detail;
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
  setModelStatus(provider?.configured ? 'Đã chọn nguồn model' : 'Model chưa sẵn sàng',
    provider?.label || 'Có thể dùng các nút tra đơn');
}
async function newConversation(nextProvider = providerId) {
  if (pending) {
    byId('model-provider').value = providerId;
    message('Bạn xử lý đề xuất đang chờ xác nhận trước khi đổi nguồn hoặc mở cuộc trò chuyện mới nhé.', 'assistant', 'interface');
    return;
  }
  const result = await api('/api/conversations', {provider_id: nextProvider});
  conversationId = result.conversation_id; providerId = result.provider_id;
  setHumanMode(false);
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

function humanMessage(text, repName = 'Mai Anh (Chuyên viên CSKH)') {
  const row = el('div', 'message assistant human-message'), label = el('div', 'message-label');
  label.append(el('span', 'human-badge-mini', 'NV'));
  label.append(document.createTextNode(' ' + repName + ' · Trực tuyến'));
  row.append(label, el('div', 'bubble', text));
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

function setHumanMode(active, repName = 'Chuyên viên CSKH (Mai Anh)') {
  isHumanMode = active;
  const avatar = byId('chat-agent-avatar');
  const title = byId('chat-title');
  const subtitle = byId('chat-subtitle');
  const btnMeet = byId('btn-meet-human');
  const badge = byId('session-badge');

  if (active) {
    if (avatar) { avatar.textContent = 'NV'; avatar.classList?.toggle?.('human', true); }
    if (title) title.textContent = repName;
    if (subtitle) subtitle.textContent = '🟢 Đang trực tuyến · Tư vấn trực tiếp';
    if (badge) { badge.textContent = 'Nhân viên'; badge.classList?.toggle?.('human', true); }
    if (btnMeet) {
      btnMeet.classList?.toggle?.('active', true);
      btnMeet.innerHTML = '🤖 Chuyển lại Bot AI';
      btnMeet.title = 'Chuyển về trợ lý AI tự động';
    }
  } else {
    if (avatar) { avatar.textContent = 'R'; avatar.classList?.toggle?.('human', false); }
    if (title) title.textContent = 'Trợ lý RetailOps';
    if (subtitle) subtitle.textContent = 'Tra đơn · Thông tin sản phẩm · Yêu cầu hủy';
    if (badge) { badge.textContent = 'Phiên AI'; badge.classList?.toggle?.('human', false); }
    if (btnMeet) {
      btnMeet.classList?.toggle?.('active', false);
      btnMeet.innerHTML = '🙋 Gặp nhân viên';
      btnMeet.title = 'Yêu cầu gặp nhân viên tư vấn';
    }
  }
}

function toggleHumanMode() {
  if (!isHumanMode) {
    setHumanMode(true);
    message('Hệ thống đã kết nối bạn trực tiếp với Chuyên viên CSKH RetailOps.', 'assistant', 'interface');
    humanMessage('Xin chào anh/chị! Em là Mai Anh - Chuyên viên hỗ trợ khách hàng RetailOps. Em đã tiếp nhận phiên trao đổi này. Em có thể hỗ trợ trực tiếp gì cho mình về đơn hàng hoặc sản phẩm ạ?');
  } else {
    setHumanMode(false);
    message('Đã chuyển lại quyền hỗ trợ cho Trợ lý ảo AI RetailOps. Quý khách có thể tiếp tục tra cứu đơn hàng hoặc hỏi đáp chính sách.', 'assistant', 'interface');
  }
}

function renderCsatStars(rating) {
  currentRating = rating;
  const starsContainer = byId('csat-stars');
  if (!starsContainer) return;
  const stars = starsContainer.querySelectorAll ? starsContainer.querySelectorAll('.star') : [];
  stars.forEach(s => {
    const val = parseInt(s.dataset?.star || '0', 10);
    s.classList?.toggle?.('selected', val <= rating);
  });
  const label = byId('csat-feedback-label');
  if (label) label.textContent = ratingLabels[rating] || (rating + '/5 sao');
}

function openEndSessionDialog() {
  renderCsatStars(5);
  const dlg = byId('end-session-dialog');
  if (dlg) dlg.showModal();
}

function confirmEndSession() {
  const dlg = byId('end-session-dialog');
  if (dlg) dlg.close();
  
  const row = el('div', 'message system');
  const card = el('div', 'session-ended-card');
  card.innerHTML = `
    <h4>🏁 Phiên làm việc đã kết thúc thành công</h4>
    <p>⭐ <strong>Đánh giá dịch vụ:</strong> ${ratingLabels[currentRating] || currentRating + '/5 sao'}</p>
    <p>⏰ <strong>Thời gian hoàn tất:</strong> ${new Date().toLocaleTimeString('vi-VN')} · ${new Date().toLocaleDateString('vi-VN')}</p>
    <p>Cảm ơn quý khách đã tin tưởng và sử dụng dịch vụ CSKH của RetailOps. Trân trọng cảm ơn!</p>
  `;
  row.append(card);
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });

  setHumanMode(false);
  setModelStatus('Phiên đã kết thúc', 'Đã lưu đánh giá ' + currentRating + '/5 sao');
}

async function act(callback) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button, #model-provider').forEach(b => { if (!b.disabled && !b.dataset.layoutControl) { b.dataset.busyDisabled = 'true'; b.disabled = true; } });
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
    card.querySelectorAll('button,input').forEach(n => { n.disabled = true; delete n.dataset.busyDisabled; });
    openProposal(proposal); await refresh();
  });
  card.append(button, el('small', '', 'Chọn lý do rồi kiểm tra đơn trước khi xác nhận.')); row.append(card);
}

function openProposal(proposal) {
  // Proposal ID is a stable idempotency key, not an authentication credential.
  pending = {...proposal, key: proposal.proposal_id};
  byId('confirm-title').textContent = 'Hủy đơn ' + proposal.order.id + '?';
  byId('confirm-description').textContent = proposal.order.name + ' · ' + money(proposal.order.amount)
    + '. Hết hạn: ' + new Date(proposal.expires_at * 1000).toLocaleTimeString('vi-VN') + '.';
  byId('confirm-reason').textContent = reasons[proposal.reason];
  byId('confirm-error').textContent = ''; byId('confirm-dialog').showModal();
}

async function restoreProposals() {
  if (!canCancel) return;
  const result = await api('/api/cancellation-proposals');
  for (const proposal of result.proposals || []) {
    const row = message('Bạn còn đề xuất hủy ' + proposal.order.id + ' đang chờ xác nhận.', 'assistant', 'store_data');
    const button = el('button', 'secondary', 'Xem lại đề xuất');
    button.onclick = () => act(async () => { openProposal(proposal); });
    row.append(button);
  }
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

function showShipment(row, shipment) {
  if (!shipment) return;
  const card = el('div', 'shipment-card');
  const header = el('div', 'shipment-header');
  header.append(
    el('strong', '', '🚚 ' + (shipment.carrier || 'Đơn vị vận chuyển')),
    el('span', 'tracking-pill ' + (shipment.status || ''), shipment.status_text || 'Đang giao')
  );
  const body = el('div', 'shipment-body');
  body.append(
    el('p', '', 'Mã vận đơn: ' + shipment.tracking_code),
    el('p', '', 'Vị trí hiện tại: ' + shipment.current_location),
    el('p', '', 'Shipper: ' + (shipment.shipper || 'Đang phân công')),
    el('p', 'delivery-eta', '⏰ Dự kiến nhận: ' + shipment.estimated_delivery)
  );
  if (Array.isArray(shipment.steps) && shipment.steps.length) {
    const timeline = el('div', 'shipment-timeline');
    for (const step of shipment.steps) {
      const item = el('div', 'timeline-item');
      item.append(el('span', 'timeline-time', step.time), el('span', 'timeline-event', step.event));
      timeline.append(item);
    }
    body.append(timeline);
  }
  card.append(header, body);
  row.append(card);
}

function showHumanSupport(row, support) {
  if (!support) return;
  const card = el('div', 'human-support-card');
  card.append(
    el('div', 'human-header', '🙋 ' + (support.support_rep || 'Chuyên viên CSKH')),
    el('p', '', support.message || 'Đã chuyển cuộc trò chuyện sang nhân viên hỗ trợ.'),
    el('span', 'badge-handoff', '🟢 Trực tuyến · Hàng đợi: ' + (support.queue || 'Ưu tiên VIP'))
  );
  row.append(card);
}

function showSources(row, sources) {
  if (!Array.isArray(sources) || !sources.length) return;
  const checked = sources.filter(s => s && /^KB:[a-f0-9]{24}$/.test(s.citation_id) &&
    typeof s.title === 'string' && typeof s.source_key === 'string' && typeof s.excerpt === 'string').slice(0, 6);
  if (!checked.length) return;
  const details = el('details', 'knowledge-sources');
  details.append(el('summary', '', 'Ngu\u1ed3n tham kh\u1ea3o (' + checked.length + ')'));
  details.append(el('small', '', 'Tr\u00edch \u0111o\u1ea1n \u0111\u00e3 truy xu\u1ea5t cho l\u01b0\u1ee3t n\u00e0y; kh\u00f4ng thay th\u1ebf tr\u1ea1ng th\u00e1i \u0111\u01a1n hi\u1ec7n t\u1ea1i.'));
  for (const source of checked.slice(0, 6)) {
    const item = el('section', 'knowledge-source');
    // Never use innerHTML, arbitrary hrefs or model-provided URLs.
    item.append(el('strong', '', source.title.slice(0, 160)),
      el('small', '', '[' + source.citation_id + '] ' + source.source_key.slice(0, 240)),
      el('p', '', source.excerpt.slice(0, 1100)));
    if (source.truncated) item.append(el('small', '', 'Tr\u00edch \u0111o\u1ea1n \u0111\u00e3 \u0111\u01b0\u1ee3c r\u00fat g\u1ecdn.'));
    details.append(item);
  }
  row.append(details);
}

function showTrace(row, trace, replayed = false) {
  if (!trace) return;
  const details = el('details', 'agent-trace');
  let summaryTitle = 'Công cụ & thời gian' + (replayed ? ' · Kết quả đã lưu' : '');
  if (trace.cache_hit) {
    summaryTitle = '⚡ Cache Hit (0ms / $0) · ' + summaryTitle;
  }
  details.append(el('summary', '', summaryTitle));
  if (trace.cache_hit) {
    const hitLabel = trace.cache_hit === 'exact' ? 'Exact Match (Khớp 100%)' : `Semantic Match (Tương đồng ${(trace.similarity * 100).toFixed(1)}%)`;
    details.append(el('p', '', `⚡ Bộ nhớ đệm (Cache Hit): ${hitLabel} · Tiết kiệm $0.00 · Phản hồi tức thì`));
    if (trace.matched_query) {
      details.append(el('small', '', `Khớp với câu hỏi gốc: "${trace.matched_query}"`));
    }
  }
  const names = (trace.tools || []).map(t => t.name + (t.status === 'error' ? ' (bị từ chối / lỗi)' : ''));
  details.append(el('p', '', (trace.model || 'model') + ' · ' + (trace.model_calls || 0) + ' lượt gọi model' +
    (trace.latency_ms !== undefined ? ' · ' + (trace.latency_ms / 1000).toFixed(2) + ' giây' : '')),
    el('p', '', 'Công cụ: ' + (names.join(' → ') || 'Không dùng công cụ ở lượt này')),
    el('small', '', 'Mã lượt: ' + trace.turn_id + (trace.model_digest ? ' · Digest: ' + trace.model_digest : ' · API không cung cấp digest trọng số')));
  if (trace.provider) details.append(el('small', '', 'Nguồn: ' + trace.provider));
  if (trace.reported_cost_usd !== null && trace.reported_cost_usd !== undefined) {
    details.append(el('small', '', 'Chi phí lượt này do API báo: $' + trace.reported_cost_usd.toFixed(6)));
  }
  if (trace.reasoning) {
    details.append(el('p', '', '💭 Suy luận (Reasoning): ' + trace.reasoning));
  }
  row.append(details);
}

async function send(text, requestId = crypto.randomUUID(), retry = false) {
  text = text.trim(); if (!text) return;

  const endKeywords = ['kết thúc phiên', 'kết thúc hỗ trợ', 'dừng hỗ trợ', 'kết thúc làm việc', 'đóng phiên'];
  if (endKeywords.some(kw => text.toLowerCase().includes(kw))) {
    byId('message').value = '';
    openEndSessionDialog();
    return;
  }

  const meetKeywords = ['gặp nhân viên', 'nói chuyện với nhân viên', 'cần gặp người thật', 'gặp tư vấn viên', 'chuyển nhân viên'];
  if (meetKeywords.some(kw => text.toLowerCase().includes(kw)) && !isHumanMode) {
    byId('message').value = '';
    toggleHumanMode();
    return;
  }

  if (isHumanMode) {
    message(text, 'user');
    byId('message').value = '';
    byId('messages').setAttribute('aria-busy', 'true');
    setModelStatus('Chuyên viên đang phản hồi…', 'Đang kết nối Mai Anh');
    setTimeout(() => {
      byId('messages').removeAttribute('aria-busy');
      setModelStatus('Đang kết nối', 'Chuyên viên CSKH Mai Anh');
      let reply = 'Dạ em chào anh/chị, em là Mai Anh. Em đã nhận được thông tin: "' + text + '". Em đang xử lý trực tiếp trên hệ thống kho cho mình đây ạ!';
      const lower = text.toLowerCase();
      if (lower.includes('hủy') || lower.includes('đơn')) {
        reply = 'Dạ về đơn hàng, anh/chị có thể bấm trực tiếp "Yêu cầu hủy đơn" ở cột bên phải, hoặc chọn lý do hủy để em hỗ trợ xác nhận trên hệ thống cho mình ngay nhé ạ!';
      } else if (lower.includes('size') || lower.includes('màu') || lower.includes('áo') || lower.includes('quần') || lower.includes('kho')) {
        reply = 'Dạ sản phẩm này bên em đang có sẵn đủ kích cỡ và màu sắc tại kho hàng. Em có thể ghi chú giữ hàng sẵn trong giỏ cho anh/chị ngay nhé!';
      } else if (lower.includes('ship') || lower.includes('giao') || lower.includes('vận chuyển') || lower.includes('đâu')) {
        reply = 'Dạ đơn hàng đang được bên vận chuyển phân tuyến giao hàng. Bưu tá sẽ liên hệ với số điện thoại của anh/chị trước khi giao từ 15-30 phút ạ!';
      } else if (lower.includes('cảm ơn') || lower.includes('thanks') || lower.includes('xong') || lower.includes('ok')) {
        reply = 'Dạ rất hân hạnh được hỗ trợ anh/chị! Nếu cần kết thúc phiên làm việc, anh/chị có thể bấm nút "🛑 Kết thúc phiên" ở góc trên bên phải để hoàn tất và chấm điểm hỗ trợ giúp em nhé ạ!';
      }
      humanMessage(reply, 'Mai Anh (Chuyên viên CSKH)');
    }, 500);
    return;
  }

  if (!retry) message(text, 'user');
  byId('message').value = '';
  setModelStatus('Model đang xử lý…', 'Đang đọc hội thoại và gọi công cụ khi cần');
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
    setModelStatus('Chat chưa hoàn tất', 'Có thể thử lại hoặc dùng các nút thao tác');
    return;
  } finally { byId('messages').removeAttribute('aria-busy'); }
  const row = message(result.message, 'assistant', result.source, result.trace?.model);
  if (result.shipment) showShipment(row, result.shipment);
  if (result.human_support) {
    showHumanSupport(row, result.human_support);
    setHumanMode(true, result.human_support.support_rep || 'Chuyên viên CSKH');
  }
  showSources(row, result.sources);
  showTrace(row, result.trace, result.replayed);
  if (result.replayed) {
    row.append(el('small', 'replay-note', 'Đây là câu trả lời đã lưu của lần gửi trước. Bảng đơn bên phải hiển thị trạng thái hiện tại.'));
  } else { showContext(result.context); }
  setModelStatus(result.replayed ? 'Kết quả đã lưu' : 'Đã phản hồi',
    selectedProvider()?.label || 'Model đã chọn');
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
  await restoreProposals();
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

// Interactive Tool Inspector Harness
const inspectorDialog = byId('inspector-dialog');
const toggleInspectorBtn = byId('toggle-inspector');
const closeInspectorBtn = byId('close-inspector');
const toolSelect = byId('inspector-tool-select');
const argsInput = byId('inspector-args-input');
const runInspectorBtn = byId('inspector-run-btn');
const inspectorOutput = byId('inspector-output');
const inspectorLatency = byId('inspector-latency-badge');

const TOOL_DEFAULTS = {
  'track_shipment': '{\n  "order_id": "O-101"\n}',
  'check_inventory': '{\n  "product_id": "P-101",\n  "size": "M",\n  "color": "trang"\n}',
  'request_human_support': '{\n  "reason": "Cần nhân viên tư vấn đổi size áo"\n}',
  'search_knowledge': '{\n  "query": "Chính sách đổi trả hàng"\n}',
  'get_order': '{\n  "order_id": "O-101"\n}',
  'list_orders': '{}'
};

if (toggleInspectorBtn && inspectorDialog) {
  toggleInspectorBtn.onclick = () => inspectorDialog.showModal();
}
if (closeInspectorBtn && inspectorDialog) {
  closeInspectorBtn.onclick = () => inspectorDialog.close();
}
if (toolSelect && argsInput) {
  toolSelect.onchange = () => {
    argsInput.value = TOOL_DEFAULTS[toolSelect.value] || '{}';
  };
}
if (runInspectorBtn && inspectorOutput) {
  runInspectorBtn.onclick = async () => {
    try {
      const tool_name = toolSelect.value;
      const arguments_obj = JSON.parse(argsInput.value.trim() || '{}');
      inspectorOutput.textContent = 'Đang thực thi công cụ [' + tool_name + '] tại backend...';
      inspectorLatency.textContent = '';
      const t0 = performance.now();
      const res = await api('/api/tools/execute', { tool_name, arguments: arguments_obj });
      const ms = (performance.now() - t0).toFixed(1);
      inspectorLatency.textContent = `⚡ Phản hồi: ${ms}ms`;
      inspectorOutput.textContent = JSON.stringify(res.result, null, 2);
    } catch (err) {
      inspectorLatency.textContent = '❌ Lỗi';
      inspectorOutput.textContent = 'Error: ' + err.message;
    }
  };
}

// In-Chat Human Handoff & End Session Listeners
const btnMeetHuman = byId('btn-meet-human');
if (btnMeetHuman) btnMeetHuman.onclick = () => act(async () => { toggleHumanMode(); });

const btnEndSession = byId('btn-end-session');
if (btnEndSession) btnEndSession.onclick = () => openEndSessionDialog();

const cancelEndSession = byId('cancel-end-session');
if (cancelEndSession) cancelEndSession.onclick = () => byId('end-session-dialog').close();

const confirmEndSessionBtn = byId('confirm-end-session');
if (confirmEndSessionBtn) confirmEndSessionBtn.onclick = () => confirmEndSession();

document.querySelectorAll('#csat-stars .star').forEach(star => {
  star.onclick = () => {
    const val = parseInt(star.dataset.star, 10);
    renderCsatStars(val);
  };
  star.onmouseenter = () => {
    const val = parseInt(star.dataset.star, 10);
    const label = byId('csat-feedback-label');
    if (label) label.textContent = ratingLabels[val] || (val + '/5 sao');
  };
  star.onmouseleave = () => {
    const label = byId('csat-feedback-label');
    if (label) label.textContent = ratingLabels[currentRating] || (currentRating + '/5 sao');
  };
});
