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
let humanPollingTimer = null;
const renderedStaffTurnIds = new Set();
let currentAttachment = null;
let orderScope = 'customer', managerFilter = 'all';

function openLightbox(src, caption) {
  const dlg = byId('image-lightbox-dialog');
  if (!dlg || typeof dlg.showModal !== 'function') return;
  const img = byId('lightbox-img');
  const cap = byId('lightbox-caption');
  if (img) img.src = src;
  if (cap) cap.textContent = caption || '';
  dlg.showModal();
}

function stageAttachment(file) {
  if (!file) return;
  const isImg = file.type.startsWith('image/');
  const isPdf = file.type === 'application/pdf';
  if (!isImg && !isPdf) {
    message('Chỉ hỗ trợ file ảnh (JPG, PNG, WEBP, GIF) hoặc tài liệu PDF.', 'assistant', 'interface');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    message('Dung lượng tệp tối đa là 10MB.', 'assistant', 'interface');
    return;
  }
  const reader = new FileReader();
  reader.onload = function(e) {
    let dataUrl = e.target.result;
    if (isImg && file.type !== 'image/gif') {
      const img = new Image();
      img.onload = function() {
        const maxDim = 1920;
        let w = img.width, h = img.height;
        if (w > maxDim || h > maxDim) {
          if (w > h) { h = Math.round((h * maxDim) / w); w = maxDim; }
          else { w = Math.round((w * maxDim) / h); h = maxDim; }
          const canvas = document.createElement('canvas');
          canvas.width = w; canvas.height = h;
          const ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, w, h);
          dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        }
        currentAttachment = {
          type: 'image',
          name: file.name,
          mime_type: 'image/jpeg',
          data: dataUrl
        };
        renderAttachmentPreview();
      };
      img.src = dataUrl;
    } else {
      currentAttachment = {
        type: isImg ? 'image' : 'document',
        name: file.name,
        mime_type: file.type || (isPdf ? 'application/pdf' : 'image/jpeg'),
        data: dataUrl
      };
      renderAttachmentPreview();
    }
  };
  reader.readAsDataURL(file);
}

function clearAttachment() {
  currentAttachment = null;
  const input = byId('chat-file-input');
  if (input) input.value = '';
  renderAttachmentPreview();
}

function renderAttachmentPreview() {
  const container = byId('attachment-preview');
  if (!container) return;
  if (!currentAttachment) {
    if (container.style) container.style.display = 'none';
    container.hidden = true;
    container.replaceChildren();
    return;
  }
  if (container.style) container.style.display = 'flex';
  container.hidden = false;
  container.replaceChildren();
  if (currentAttachment.type === 'image') {
    const thumb = el('img', 'attachment-preview-thumb');
    thumb.src = currentAttachment.data;
    thumb.alt = currentAttachment.name;
    container.append(thumb);
  } else {
    container.append(el('div', 'attachment-preview-icon', '📄'));
  }
  const info = el('div', 'attachment-preview-info');
  info.append(
    el('div', 'attachment-preview-name', currentAttachment.name),
    el('div', 'attachment-preview-size', currentAttachment.type === 'image' ? 'Ảnh đính kèm · Sẵn sàng gửi' : 'Tài liệu PDF · Sẵn sàng gửi')
  );
  container.append(info);
  const removeBtn = el('button', 'attachment-preview-remove', '✕');
  removeBtn.type = 'button';
  removeBtn.title = 'Bỏ đính kèm';
  removeBtn.onclick = () => clearAttachment();
  container.append(removeBtn);
}
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
  renderedStaffTurnIds.clear();
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

function message(text, role = 'assistant', source = null, model = null, attachment = null) {
  const row = el('div', 'message ' + role), label = el('div', 'message-label');
  label.append(el('span', role === 'assistant' ? 'mini-r' : '', role === 'assistant' ? 'R' : ''));
  label.append(document.createTextNode(role === 'user' ? 'Bạn' : 'RetailOps' + (source ? ' · ' + sourceLabels[source] : '') + (model ? ' · ' + model : '')));
  const bubble = el('div', 'bubble');
  if (attachment) {
    const card = el('div', 'chat-attachment-card');
    if (attachment.type === 'image') {
      const img = el('img', 'chat-attachment-img');
      img.src = attachment.data.startsWith('data:') ? attachment.data : `data:${attachment.mime_type || 'image/jpeg'};base64,${attachment.data}`;
      img.alt = attachment.name || 'Ảnh đính kèm';
      img.onclick = (e) => { e.stopPropagation(); openLightbox(img.src, attachment.name); };
      card.append(img);
    } else {
      const doc = el('div', 'chat-attachment-doc');
      doc.append(document.createTextNode('📄 '), el('strong', '', attachment.name || 'Tài liệu'));
      card.append(doc);
    }
    card.append(el('div', 'chat-attachment-caption', attachment.name || 'Tệp đính kèm'));
    bubble.append(card);
  }
  if (text) {
    bubble.append(document.createTextNode(text));
  }
  row.append(label, bubble);
  byId('messages').append(row);
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

function startHumanModePolling() {
  if (humanPollingTimer) return;
  humanPollingTimer = setInterval(pollHumanChat, 2000);
}

function stopHumanModePolling() {
  if (humanPollingTimer) {
    clearInterval(humanPollingTimer);
    humanPollingTimer = null;
  }
}

async function pollHumanChat() {
  if (!isHumanMode || !conversationId) return;
  try {
    const data = await api('/api/staff/conversations/' + conversationId + '/messages');
    const turns = data.turns || [];
    for (const t of turns) {
      if (renderedStaffTurnIds.has(t.id)) continue;
      renderedStaffTurnIds.add(t.id);

      let resObj = {};
      try { resObj = JSON.parse(t.result); } catch (e) {}
      if (resObj.author === 'staff' && resObj.message) {
        humanMessage(resObj.message, resObj.staff_name || 'Nguyễn Mai Anh (Chuyên viên CSKH)');
        setModelStatus('Đã nhận phản hồi', 'Chuyên viên CSKH Mai Anh');
      }
    }

    const feedbacks = data.feedbacks || [];
    const isResolved = feedbacks.some(f => f.feedback_type === 'human_handoff' && f.reason_code === 'resolved' && f.sentiment_flag === 'resolved');
    if (isResolved && isHumanMode) {
      if (!pollHumanChat.resolvedNotified) {
        pollHumanChat.resolvedNotified = true;
        message('Chuyên viên CSKH đã xử lý xong yêu cầu và đóng ca hỗ trợ trực tiếp. Hệ thống chuyển lại Trợ lý AI.', 'assistant', 'interface');
        setHumanMode(false);
      }
    } else {
      pollHumanChat.resolvedNotified = false;
    }
  } catch (e) {
    // background polling silent
  }
}

function setHumanMode(active, repName = 'Chuyên viên CSKH (Mai Anh)') {
  isHumanMode = active;
  const avatar = byId('chat-agent-avatar');
  const title = byId('chat-title');
  const subtitle = byId('chat-subtitle');
  const btnMeet = byId('btn-meet-human');
  const badge = byId('session-badge');

  if (active) {
    startHumanModePolling();
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
    stopHumanModePolling();
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
    if (conversationId) {
      api('/api/feedback', {
        conversation_id: conversationId,
        feedback_type: 'human_handoff',
        reason_code: 'customer_requested_human',
        comment: 'Khách hàng yêu cầu kết nối chuyên viên tư vấn trực tiếp'
      }).catch(() => {});
    }
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

async function confirmEndSession() {
  const dlg = byId('end-session-dialog');
  if (dlg) dlg.close();

  const ratingVal = currentRating;
  const ratingText = ratingLabels[ratingVal] || (ratingVal + '/5 sao');

  if (conversationId) {
    try {
      await api('/api/feedback', {
        conversation_id: conversationId,
        feedback_type: 'session_csat',
        rating: ratingVal,
        comment: ratingText
      });
    } catch (e) {
      console.warn('Lưu CSAT lỗi:', e);
    }
  }

  const row = el('div', 'message system');
  const card = el('div', 'session-ended-card');
  card.innerHTML = `
    <h4>🏁 Phiên làm việc đã kết thúc thành công</h4>
    <p>⭐ <strong>Đánh giá dịch vụ:</strong> ${ratingText}</p>
    <p>⏰ <strong>Thời gian hoàn tất:</strong> ${new Date().toLocaleTimeString('vi-VN')} · ${new Date().toLocaleDateString('vi-VN')}</p>
    <p>Cảm ơn quý khách đã tin tưởng và sử dụng dịch vụ CSKH của RetailOps. Trân trọng cảm ơn!</p>
  `;
  row.append(card);
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });

  setHumanMode(false);
  setModelStatus('Phiên đã kết thúc', 'Đã lưu đánh giá ' + ratingVal + '/5 sao');
}

function showFeedbackBar(row, cid, turnId) {
  const bar = el('div', 'message-feedback-bar');
  const btnLike = el('button', 'feedback-btn', '👍 Hữu ích');
  const btnDislike = el('button', 'feedback-btn', '👎 Chưa hài lòng');
  const note = el('span', 'feedback-note');

  btnLike.onclick = async () => {
    btnLike.disabled = true;
    btnDislike.disabled = true;
    btnLike.classList?.add?.('active');
    btnLike.classList?.add?.('positive');
    note.textContent = '✓ Cảm ơn đánh giá!';
    bar.append(note);
    try {
      await api('/api/feedback', {
        conversation_id: cid,
        turn_id: turnId || null,
        feedback_type: 'turn_rating',
        sentiment_flag: 'positive'
      });
    } catch (e) {
      console.warn('Gửi like lỗi:', e);
    }
  };

  btnDislike.onclick = () => {
    let popover = row.querySelector('.feedback-reason-popover');
    if (popover) { popover.remove(); return; }
    popover = el('div', 'feedback-reason-popover');
    popover.append(el('span', '', 'Lý do chưa hài lòng:'));
    const chips = el('div', 'feedback-reason-chips');
    const reasons = [
      { code: 'wrong_info', label: 'Sai thông tin' },
      { code: 'misunderstood', label: 'Chưa hiểu ý' },
      { code: 'tone_issue', label: 'Cách trả lời chưa tốt' },
      { code: 'other', label: 'Khác' }
    ];
    for (const r of reasons) {
      const chip = el('button', 'reason-chip', r.label);
      chip.onclick = async () => {
        popover.remove();
        btnLike.disabled = true;
        btnDislike.disabled = true;
        btnDislike.classList?.add?.('active');
        btnDislike.classList?.add?.('negative');
        note.textContent = '✓ Đã ghi nhận phản hồi!';
        bar.append(note);
        try {
          await api('/api/feedback', {
            conversation_id: cid,
            turn_id: turnId || null,
            feedback_type: 'turn_rating',
            sentiment_flag: 'negative',
            reason_code: r.code,
            comment: r.label
          });
        } catch (e) {
          console.warn('Gửi dislike lỗi:', e);
        }
      };
      chips.append(chip);
    }
    popover.append(chips);
    bar.after(popover);
  };

  bar.append(btnLike, btnDislike);
  row.append(bar);
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
  const isManager = orderScope === 'store_all';
  const filteredOrders = (isManager && managerFilter !== 'all')
    ? orders.filter(o => o.status === managerFilter)
    : orders;
  const order = orders.find(o => o.id === selected) || filteredOrders[0], area = byId('order-details');
  area.replaceChildren();
  const tabs = byId('order-tabs'); tabs.replaceChildren();

  if (isManager) {
    const filterBar = el('div', 'manager-filter-bar');
    const filters = [
      {id: 'all', label: 'Tất cả (' + orders.length + ')'},
      {id: 'pending', label: 'Chờ (' + orders.filter(o => o.status === 'pending').length + ')'},
      {id: 'delivered', label: 'Giao (' + orders.filter(o => o.status === 'delivered').length + ')'},
      {id: 'cancelled', label: 'Hủy (' + orders.filter(o => o.status === 'cancelled').length + ')'}
    ];
    filters.forEach(f => {
      const btn = el('button', 'manager-filter-btn' + (managerFilter === f.id ? ' active' : ''), f.label);
      btn.type = 'button';
      btn.onclick = () => { managerFilter = f.id; renderOrder(); };
      filterBar.append(btn);
    });
    area.append(filterBar);
  }

  for (const item of filteredOrders) {
    const active = item.id === (order ? order.id : selected), button = el('button', active ? 'selected' : '', item.id);
    button.dataset.order = item.id; button.setAttribute('aria-pressed', String(active));
    button.onclick = () => act(() => lookupOrder(item.id)); tabs.append(button);
  }
  byId('order-count').textContent = isManager ? (orders.length + ' đơn toàn shop') : (orders.length + ' đơn mẫu');
  if (isManager) {
    const headerTitle = byId('order-panel-title');
    if (headerTitle) headerTitle.textContent = 'Toàn bộ đơn hàng Shop';
  }
  if (!order) { area.append(el('p', 'order-empty', 'Chưa có thông tin đơn. Hãy kết nối hoặc tải lại dữ liệu.')); return; }
  const top = el('div', 'order-line'); top.append(el('h3', '', order.id), el('span', 'badge ' + order.status, statuses[order.status]));
  const item = el('div', 'item'), copy = el('div'); copy.append(el('strong', '', order.name), el('p', '', order.variant)); item.append(copy);
  const total = el('div', 'detail-row total'); total.append(el('span', '', 'Tổng cộng'), el('strong', '', money(order.amount)));
  area.append(top, el('p', 'order-date', 'Đơn ' + (order.customer_id ? ('khách ' + order.customer_id + ' · ') : '') + 'Phiên bản ' + order.version), item, total);
  area.append(el('p', 'order-policy', order.status === 'pending' ? 'Có thể yêu cầu hủy. Cần chọn lý do và xác nhận.' : order.status === 'delivered' ? 'Đơn đã giao không đủ điều kiện hủy.' : 'Đơn đã hủy. Trạng thái được lưu trên máy chủ.'));
  const lookup = el('button', 'order-action', 'Tra cứu đơn này'); lookup.onclick = () => act(() => lookupOrder(order.id)); area.append(lookup);
  if (canCancel) {
    const cancel = el('button', 'order-action', 'Yêu cầu hủy đơn này'); cancel.onclick = () => act(() => chooseReason(order.id)); area.append(cancel);
  } else { area.append(el('p', 'order-policy', 'Tài khoản của bạn có quyền xem; không được tạo yêu cầu hủy.')); }
}

const eventLabels = {order_viewed: 'Tra cứu đơn', cancellation_proposed: 'Tạo đề xuất hủy', order_cancelled: 'Đã xác nhận hủy', proposal_dismissed: 'Bỏ đề xuất', model_extraction: 'Model phân tích yêu cầu', model_unavailable: 'Không kết nối được model', chat_replied: 'Trả lời hội thoại', agent_replied: 'Model trả lời', agent_failed: 'Lượt chat chưa hoàn tất'};
async function refresh() {
  const [data, history] = await Promise.all([api('/api/orders'), api('/api/events')]);
  orders = data.orders || [];
  orderScope = data.scope || 'customer';
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

async function send(text, requestId = crypto.randomUUID(), retry = false, attachment = null) {
  text = text ? text.trim() : '';
  if (!text && !attachment) return;
  if (!text && attachment) {
    text = 'Nhờ bot kiểm tra hình ảnh/tài liệu đính kèm này giúp tôi.';
  }

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
    message(text, 'user', null, null, attachment);
    byId('message').value = '';
    byId('messages').setAttribute('aria-busy', 'true');
    setModelStatus('Đang gửi tin…', 'Đã chuyển tin nhắn đến Chuyên viên CSKH');
    try {
      const payload = {
        conversation_id: conversationId,
        message: text
      };
      if (attachment) payload.attachment = attachment;
      const res = await api('/api/staff/customer-message', payload);
      if (res && res.turn_id) {
        renderedStaffTurnIds.add(res.turn_id);
      }
      setModelStatus('Đã gửi cho CSKH', 'Chuyên viên Mai Anh đang xem và xử lý');
      if (byId('staff-desk-dialog')?.open) {
        loadStaffQueue(true);
        if (activeStaffTicket && activeStaffTicket.conversation_id === conversationId) {
          refreshStaffTranscript(conversationId, true);
        }
      }
    } catch (err) {
      console.error('Lỗi gửi tin nhắn cho chuyên viên:', err);
      message('Không thể gửi tin nhắn đến chuyên viên: ' + (err.message || 'Lỗi mạng'), 'assistant', 'interface');
      setModelStatus('Lỗi gửi tin', 'Vui lòng thử lại');
    } finally {
      byId('messages').removeAttribute('aria-busy');
    }
    return;
  }

  if (!retry) message(text, 'user', null, null, attachment);
  byId('message').value = '';
  setModelStatus('Model đang xử lý…', 'Đang đọc hội thoại và gọi công cụ khi cần');
  byId('messages').setAttribute('aria-busy', 'true');
  let result;
  try {
    const payload = {text, conversation_id: conversationId, request_id: requestId};
    if (attachment) payload.attachment = attachment;
    result = await api('/api/chat', payload);
  } catch (error) {
    const row = message(error.message || 'Mất kết nối trong lúc chờ model.', 'assistant', 'interface');
    showTrace(row, error.trace);
    const retryButton = el('button', 'order-action', 'Thử lại tin nhắn này');
    const originalConversation = conversationId;
    retryButton.onclick = () => act(async () => {
      if (conversationId !== originalConversation) return;
      retryButton.remove(); await send(text, requestId, true, attachment);
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
    if (conversationId) {
      api('/api/feedback', {
        conversation_id: conversationId,
        turn_id: result.turn_id || null,
        feedback_type: 'human_handoff',
        reason_code: result.human_support.reason || 'user_requested'
      }).catch(e => console.warn('Ghi log handoff lỗi:', e));
    }
  }
  showSources(row, result.sources);
  showTrace(row, result.trace, result.replayed);
  if (conversationId && result.source !== 'interface') {
    showFeedbackBar(row, conversationId, result.turn_id);
  }
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
  document.body.dataset.role = session.role || 'customer';
  canCancel = Array.isArray(session.permissions) ? session.permissions.includes('orders:cancel') : true;
  byId('profile-name').textContent = session.name || 'Khách hàng';
  byId('profile-avatar').textContent = (session.name || 'KH').slice(0, 2).toUpperCase();
  const roleNames = {
    customer: 'Khách hàng',
    viewer: 'Chỉ xem dữ liệu mẫu',
    staff: 'Chuyên viên CSKH',
    manager: 'Quản lý cửa hàng',
    admin: 'Quản trị viên'
  };
  byId('profile-role').textContent = roleNames[session.role] || (canCancel ? 'Khách hàng giả lập' : 'Chỉ xem dữ liệu mẫu');
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
  if (session.role === 'staff') {
    openStaffDesk();
  }
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
function submitChat() {
  const input = byId('message');
  let text = input.value.trim();
  const att = currentAttachment;
  if (!text && !att) return;
  if (!text && att) {
    text = 'Nhờ bot kiểm tra hình ảnh/tài liệu đính kèm này giúp tôi.';
  }
  clearAttachment();
  act(() => send(text, crypto.randomUUID(), false, att));
}
byId('chat-form').onsubmit = event => { event.preventDefault(); submitChat(); };
byId('message').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submitChat(); } };
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

// In-Chat Layout Controls, Human Handoff & End Session Listeners
const btnToggleTopbar = byId('btn-toggle-topbar');
if (btnToggleTopbar) {
  const isCollapsed = () => document.body.classList?.contains?.('topbar-collapsed') || false;
  const updateExpandState = (collapsed) => {
    document.body.classList?.toggle?.('topbar-collapsed', collapsed);
    btnToggleTopbar.classList?.toggle?.('active', collapsed);
    btnToggleTopbar.textContent = collapsed ? '⤡ Thu nhỏ' : '⤢ Mở rộng';
    btnToggleTopbar.title = collapsed ? 'Hiện lại thanh tiêu đề' : 'Ẩn thanh menu trên cùng để mở rộng khung chat';
    try { localStorage.setItem('retailops.ui.topbarCollapsed', String(collapsed)); } catch (_) {}
  };
  try {
    if (localStorage.getItem('retailops.ui.topbarCollapsed') === 'true') {
      updateExpandState(true);
    }
  } catch (_) {}
  btnToggleTopbar.onclick = () => updateExpandState(!isCollapsed());
}

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

// Staff Live Chat Console (Human-in-the-loop Desk)
let activeStaffTicket = null;
let staffDeskTimer = null;

function openStaffDesk() {
  const dlg = byId('staff-desk-dialog');
  if (dlg) {
    dlg.showModal();
    loadStaffQueue();
    startStaffDeskPolling();
  }
}

function closeStaffDeskDialog() {
  const dlg = byId('staff-desk-dialog');
  if (dlg && dlg.open) dlg.close();
  stopStaffDeskPolling();
}

function startStaffDeskPolling() {
  if (staffDeskTimer) return;
  staffDeskTimer = setInterval(pollStaffDesk, 2500);
}

function stopStaffDeskPolling() {
  if (staffDeskTimer) {
    clearInterval(staffDeskTimer);
    staffDeskTimer = null;
  }
}

async function pollStaffDesk() {
  const dlg = byId('staff-desk-dialog');
  if (!dlg || !dlg.open) {
    stopStaffDeskPolling();
    return;
  }
  if (activeStaffTicket) {
    await refreshStaffTranscript(activeStaffTicket.conversation_id, false);
  }
  await loadStaffQueue(true);
}

async function loadStaffQueue(silent = false) {
  const listEl = byId('staff-queue-list');
  const countEl = byId('staff-queue-count');
  if (!listEl) return;
  if (!silent) {
    listEl.innerHTML = '<p class="staff-empty-hint" style="padding:15px 10px;text-align:center;color:#94a3b8;">Đang tải danh sách ca chờ...</p>';
  }
  try {
    const res = await api('/api/staff/escalations');
    const items = res.escalations || [];
    if (countEl) countEl.textContent = items.length;
    if (!items.length) {
      listEl.innerHTML = '<p class="staff-empty-hint" style="padding:20px 10px;text-align:center;color:#94a3b8;">Không có ca khiếu nại hoặc chuyển giao nào đang chờ.</p>';
      return;
    }
    listEl.innerHTML = '';
    items.forEach(item => {
      const isResolved = item.sentiment_flag === 'resolved';
      const card = el('div', 'ticket-card' + (activeStaffTicket && activeStaffTicket.id === item.id ? ' active' : ''));
      const header = el('div', 'ticket-header');
      header.append(
        el('span', 'ticket-user', (item.customer_name || item.customer_id) + (item.order_id ? ' (' + item.order_id + ')' : '')),
        el('span', 'ticket-badge ' + (isResolved ? 'resolved' : 'pending'), isResolved ? '✓ Đã xử lý' : '🔴 Chờ hỗ trợ')
      );
      const reason = el('p', 'ticket-reason', item.comment || item.reason_code || 'Yêu cầu hỗ trợ từ khách hàng');
      const timeStr = new Date((item.created_at || Date.now() / 1000) * 1000).toLocaleTimeString('vi-VN', {hour: '2-digit', minute:'2-digit'});
      const meta = el('div', 'ticket-meta');
      meta.append(el('span', '', 'Mã ca: #' + item.id), el('span', '', timeStr));
      card.append(header, reason, meta);
      card.onclick = () => selectStaffTicket(item);
      listEl.append(card);
    });
  } catch (err) {
    if (!silent) {
      listEl.innerHTML = '<p class="staff-empty-hint" style="color:#ef4444;padding:15px;">Lỗi tải hàng đợi: ' + err.message + '</p>';
    }
  }
}

async function refreshStaffTranscript(cid, forceScroll = false) {
  const transcriptEl = byId('staff-chat-transcript');
  if (!transcriptEl) return;
  try {
    const data = await api('/api/staff/conversations/' + cid + '/messages');
    const turns = data.turns || [];
    const currentCount = parseInt(transcriptEl.dataset.turnsCount || '-1', 10);
    if (currentCount === turns.length && !forceScroll) return;

    transcriptEl.dataset.turnsCount = turns.length.toString();
    transcriptEl.innerHTML = '';
    if (!turns.length) {
      transcriptEl.innerHTML = '<p class="transcript-placeholder">Chưa có tin nhắn trong phiên này.</p>';
      return;
    }
    turns.forEach(t => {
      let raw = [];
      try { raw = JSON.parse(t.messages); } catch(e) {}
      let res = {};
      try { res = JSON.parse(t.result); } catch(e) {}

      raw.forEach(m => {
        if (m.role === 'user') {
          const row = el('div', 'message user');
          const bubble = el('div', 'bubble bubble-user');
          if (m.attachment) {
            const card = el('div', 'chat-attachment-card');
            if (m.attachment.type === 'image') {
              const img = el('img', 'chat-attachment-img');
              img.src = m.attachment.data.startsWith('data:') ? m.attachment.data : `data:${m.attachment.mime_type || 'image/jpeg'};base64,${m.attachment.data}`;
              img.alt = m.attachment.name || 'Ảnh đính kèm';
              img.onclick = (e) => { e.stopPropagation(); openLightbox(img.src, m.attachment.name); };
              card.append(img);
            } else {
              const doc = el('div', 'chat-attachment-doc');
              doc.append(document.createTextNode('📄 '), el('strong', '', m.attachment.name || 'Tài liệu'));
              card.append(doc);
            }
            card.append(el('div', 'chat-attachment-caption', m.attachment.name || 'Tệp đính kèm'));
            bubble.append(card);
          }
          if (m.content) bubble.append(document.createTextNode(m.content));
          row.append(
            el('div', 'message-label', 'Khách hàng' + (activeStaffTicket?.customer_name ? ' (' + activeStaffTicket.customer_name + ')' : '')),
            bubble
          );
          transcriptEl.append(row);
        } else if (m.role === 'assistant') {
          const isStaff = m.author === 'staff' || res.author === 'staff';
          const row = el('div', 'message assistant' + (isStaff ? ' human-message' : ''));
          const label = el('div', 'message-label');
          label.append(el('span', isStaff ? 'human-badge-mini' : 'mini-r', isStaff ? 'NV' : 'R'));
          label.append(document.createTextNode(' ' + (isStaff ? (m.staff_name || res.staff_name || 'Chuyên viên CSKH') : 'Trợ lý AI')));
          row.append(label, el('div', 'bubble' + (isStaff ? ' bubble-staff' : ''), m.content));
          transcriptEl.append(row);
        }
      });
    });
    if (forceScroll || !transcriptEl.dataset.hasScrolled) {
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
      transcriptEl.dataset.hasScrolled = 'true';
    }
  } catch (err) {
    // ignore
  }
}

async function selectStaffTicket(ticket) {
  activeStaffTicket = ticket;
  document.querySelectorAll('.ticket-card').forEach(c => c.classList.remove('active'));

  byId('staff-active-customer').textContent = (ticket.customer_name || ticket.customer_id) + (ticket.order_id ? ' · Đơn hàng: ' + ticket.order_id : '');
  byId('staff-active-meta').textContent = 'Mã phiên: ' + ticket.conversation_id + ' · Lý do: ' + (ticket.comment || ticket.reason_code || 'Yêu cầu gặp nhân viên');
  byId('staff-chat-actions').style.display = 'block';
  byId('staff-chat-composer').style.display = 'flex';

  const transcriptEl = byId('staff-chat-transcript');
  transcriptEl.dataset.turnsCount = '-1';
  transcriptEl.dataset.hasScrolled = '';
  transcriptEl.innerHTML = '<p class="transcript-placeholder">Đang tải lịch sử hội thoại...</p>';

  await refreshStaffTranscript(ticket.conversation_id, true);
}

async function sendStaffReply() {
  if (!activeStaffTicket) return;
  const input = byId('staff-reply-input');
  const text = (input?.value || '').trim();
  if (!text) return;

  const btn = byId('btn-send-staff-reply');
  if (btn) btn.disabled = true;

  try {
    const replyRes = await api('/api/staff/reply', {
      conversation_id: activeStaffTicket.conversation_id,
      message: text,
      staff_name: 'Nguyễn Mai Anh (Chuyên viên CSKH)'
    });
    if (replyRes && replyRes.turn_id) {
      renderedStaffTurnIds.add(replyRes.turn_id);
    }
    input.value = '';

    // Append to staff transcript
    const transcriptEl = byId('staff-chat-transcript');
    const row = el('div', 'message assistant human-message');
    const label = el('div', 'message-label');
    label.append(el('span', 'human-badge-mini', 'NV'));
    label.append(document.createTextNode(' Nguyễn Mai Anh (Chuyên viên CSKH)'));
    row.append(label, el('div', 'bubble bubble-staff', text));
    transcriptEl.append(row);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    transcriptEl.dataset.turnsCount = (parseInt(transcriptEl.dataset.turnsCount || '0', 10) + 1).toString();

    // Instantly display on customer screen if this ticket matches current active conversation!
    if (conversationId && activeStaffTicket.conversation_id === conversationId) {
      humanMessage(text, 'Nguyễn Mai Anh (Chuyên viên CSKH)');
      setModelStatus('Đã nhận phản hồi', 'Chuyên viên CSKH Mai Anh');
    }

    loadStaffQueue(true);
  } catch (err) {
    alert('Lỗi gửi phản hồi: ' + err.message);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function resolveStaffTicket() {
  if (!activeStaffTicket) return;
  try {
    await api('/api/staff/resolve', {
      conversation_id: activeStaffTicket.conversation_id,
      staff_name: 'Nguyễn Mai Anh (Chuyên viên CSKH)'
    });
    if (conversationId && activeStaffTicket.conversation_id === conversationId) {
      message('Chuyên viên CSKH đã hỗ trợ xong và hoàn tất phiên này. Hệ thống chuyển lại Trợ lý AI.', 'assistant', 'interface');
      setHumanMode(false);
    }
    loadStaffQueue(true);
  } catch (err) {
    alert('Lỗi hoàn tất: ' + err.message);
  }
}

const toggleStaffDesk = byId('toggle-staff-desk');
if (toggleStaffDesk) toggleStaffDesk.onclick = () => openStaffDesk();

const closeStaffDesk = byId('close-staff-desk');
if (closeStaffDesk) closeStaffDesk.onclick = () => closeStaffDeskDialog();

const staffDeskDialog = byId('staff-desk-dialog');
if (staffDeskDialog) {
  if (typeof staffDeskDialog.addEventListener === 'function') {
    staffDeskDialog.addEventListener('close', () => stopStaffDeskPolling());
  }
  staffDeskDialog.onclose = () => stopStaffDeskPolling();
}

const refreshStaffQueue = byId('refresh-staff-queue');
if (refreshStaffQueue) refreshStaffQueue.onclick = () => loadStaffQueue();

const btnSendStaffReply = byId('btn-send-staff-reply');
if (btnSendStaffReply) btnSendStaffReply.onclick = () => sendStaffReply();

const staffReplyInput = byId('staff-reply-input');
if (staffReplyInput) {
  staffReplyInput.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendStaffReply();
    }
  };
}

const btnResolveTicket = byId('btn-resolve-ticket');
if (btnResolveTicket) btnResolveTicket.onclick = () => resolveStaffTicket();

// Multimodal Attachment Wiring & Drag-and-Drop & Lightbox
const closeLightbox = byId('close-lightbox');
if (closeLightbox) closeLightbox.onclick = () => byId('image-lightbox-dialog')?.close();
const lightboxDialog = byId('image-lightbox-dialog');
if (lightboxDialog) {
  lightboxDialog.onclick = (e) => {
    if (e.target === lightboxDialog) lightboxDialog.close();
  };
}

const btnAttach = byId('btn-attach');
const chatFileInput = byId('chat-file-input');
if (btnAttach && chatFileInput) {
  btnAttach.onclick = () => chatFileInput.click();
  chatFileInput.onchange = () => {
    if (chatFileInput.files && chatFileInput.files[0]) {
      stageAttachment(chatFileInput.files[0]);
    }
  };
}

if (typeof document.addEventListener === 'function') {
  document.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.indexOf('image') !== -1) {
        const blob = items[i].getAsFile();
        if (blob) {
          stageAttachment(new File([blob], 'screenshot_' + Date.now() + '.png', {type: blob.type}));
          e.preventDefault();
          break;
        }
      }
    }
  });
}

const chatPanelEl = document.querySelector('.chat-panel');
if (chatPanelEl && typeof chatPanelEl.addEventListener === 'function') {
  ['dragenter', 'dragover'].forEach(name => {
    chatPanelEl.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      chatPanelEl.classList?.add?.('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(name => {
    chatPanelEl.addEventListener(name, (e) => {
      e.preventDefault();
      e.stopPropagation();
      chatPanelEl.classList?.remove?.('drag-over');
    });
  });
  chatPanelEl.addEventListener('drop', (e) => {
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      stageAttachment(files[0]);
    }
  });
}



