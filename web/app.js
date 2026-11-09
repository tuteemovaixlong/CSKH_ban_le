'use strict';

// Same-origin API; credentials and inference URLs are never stored in the page.
const byId = id => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const statuses = {pending: 'Chờ xử lý', shipping: 'Đang vận chuyển', delivered: 'Đã giao', cancelled: 'Đã hủy'};
const formatCustomerOrderId = order => (order && typeof order === 'object' ? (order.external_order_id || order.id || '—') : '—');
const formatDualOrderId = (internalId, externalId) => {
  const intId = typeof internalId === 'string' ? internalId.trim() : '';
  const extId = typeof externalId === 'string' ? externalId.trim() : '';
  if (extId && intId && extId !== intId) return `${extId} (${intId})`;
  return extId || intId || '—';
};
// W3.2-D2: request reasons come from the one shared catalog (GET /api/order-action-reasons); no list lives here.
let reasonCatalog = null;
const stockLabels = {in_stock: 'còn hàng', out_of_stock: 'hết hàng', unknown: 'chưa rõ tồn kho'};
const exchangeKindLabels = {other_variant: 'Đổi sang biến thể khác', same_variant: 'Đổi cùng biến thể'};
const money = value => new Intl.NumberFormat('vi-VN', {style: 'currency', currency: 'VND'}).format(value);
let token = '', orders = [], selected = null, pending = null, busy = false, conversationId = null;
let providerId = 'custom', providerOptions = [];
let canCancel = true;
let isHumanMode = false, currentRating = 5;
let humanPollingTimer = null;
let botTimerPollingTimer = null;
let currentCaseId = null, currentHandoffId = null, caseClosedNotifiedForId = null;
const renderedStaffTurnIds = new Set();
let currentAttachment = null;
let orderScope = 'customer', managerFilter = 'all', orderSearchQuery = '';
let focusedExternalOrderId = null;
let currentSessionRole = 'customer', currentSessionTenantId = null, currentSessionPrincipalId = null;
let currentSessionName = '';
const staffLabel = () => currentSessionName || 'Chuyên viên CSKH';
let adminAccounts = [], selectedAdminMembershipId = null, selectedAdminAccount = null;
let activeChatTurn = null;
const SEND_BTN_ICON_HTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 7-7 7 7M12 5v14"/></svg>';
let activeResumeCaseBtn = null;
let activeResumeCaseParent = null;

function clearResumeCaseButtons() {
  if (activeResumeCaseBtn) {
    activeResumeCaseBtn.hidden = true;
    if (typeof activeResumeCaseBtn.remove === 'function') {
      activeResumeCaseBtn.remove();
    }
    if (activeResumeCaseParent && Array.isArray(activeResumeCaseParent.children)) {
      activeResumeCaseParent.children = activeResumeCaseParent.children.filter(c => c !== activeResumeCaseBtn);
    }
    activeResumeCaseBtn = null;
    activeResumeCaseParent = null;
  }
}

function appendResumeCaseButton(row, targetCid = conversationId) {
  if (!row || !targetCid) return null;
  clearResumeCaseButtons();
  const btn = el('button', 'secondary btn-sm resume-case-btn', 'Tiếp tục');
  btn.type = 'button';
  btn.id = 'btn-resume-case';
  btn.onclick = async () => {
    if (btn.disabled || !targetCid) return;
    btn.disabled = true;
    try {
      const res = await api('/api/conversations/' + encodeURIComponent(targetCid) + '/resume', {});
      if (res?.case?.case_id) {
        currentCaseId = res.case.case_id;
      }
      caseClosedNotifiedForId = null;
      pollHumanChat.resolvedNotified = false;
      clearResumeCaseButtons();
      if (res?.case?.has_active_timer && !isHumanMode) {
        startBotTimerPolling();
      }
      setModelStatus('Đã mở lại ca hỗ trợ', selectedProvider()?.label || 'Sẵn sàng tiếp tục');
      message('Đã mở lại ca hỗ trợ. Bạn có thể tiếp tục gửi yêu cầu tại đây.', 'assistant', 'interface');
    } catch (err) {
      btn.disabled = false;
      const errRow = message('Không thể mở lại ca hỗ trợ: ' + (err.message || 'Lỗi máy chủ'), 'assistant', 'interface');
      if (err.debugInfo) showErrorDetails(errRow, err);
    }
  };
  row.append(btn);
  activeResumeCaseBtn = btn;
  activeResumeCaseParent = row;
  return btn;
}

function syncChatSendStopButton() {
  const btn = byId('chat-send-btn');
  if (!btn) return;
  if (activeChatTurn) {
    btn.type = 'button';
    btn.classList?.add?.('is-stop');
    btn.textContent = '■ Dừng';
    btn.setAttribute('aria-label', 'Dừng câu trả lời');
    btn.title = 'Dừng câu trả lời';
    delete btn.dataset.busyDisabled;
    btn.disabled = Boolean(activeChatTurn.stopping);
    btn.onclick = event => {
      event?.preventDefault?.();
      event?.stopPropagation?.();
      return cancelActiveChatTurn();
    };
  } else {
    btn.type = 'submit';
    btn.classList?.remove?.('is-stop');
    btn.textContent = '';
    btn.innerHTML = SEND_BTN_ICON_HTML;
    btn.setAttribute('aria-label', 'Gửi yêu cầu');
    btn.title = 'Gửi yêu cầu';
    btn.onclick = null;
    btn.disabled = false;
    delete btn.dataset.busyDisabled;
  }
}

async function cancelActiveChatTurn() {
  if (!activeChatTurn || activeChatTurn.stopping) return;
  const { conversationId: cid, requestId: reqId } = activeChatTurn;
  activeChatTurn.stopping = true;
  syncChatSendStopButton();
  setModelStatus('Đang dừng câu trả lời…', 'Sẽ dừng ở điểm kiểm tra an toàn tiếp theo');
  try {
    await api('/api/chat/cancel', { conversation_id: cid, request_id: reqId });
  } catch (err) {
    // Pending /api/chat response settles the turn state.
  }
}

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
  if (isPdf && file.size > 20 * 1024 * 1024) {
    message('Dung lượng tài liệu PDF tối đa là 20MB.', 'assistant', 'interface');
    return;
  }
  if (!isPdf && file.size > 10 * 1024 * 1024) {
    message('Dung lượng tệp tối đa là 10MB.', 'assistant', 'interface');
    return;
  }
  const reader = new FileReader();
  reader.onload = function(e) {
    let dataUrl = e.target.result;
    if (isImg && file.type !== 'image/gif') {
      const img = new Image();
      img.onload = function() {
        const maxDim = 2048;
        let w = img.width, h = img.height;
        if (w > maxDim || h > maxDim) {
          if (w > h) { h = Math.round((h * maxDim) / w); w = maxDim; }
          else { w = Math.round((w * maxDim) / h); h = maxDim; }
        }
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, 0, 0, w, h);
        dataUrl = canvas.toDataURL('image/jpeg', 0.85);
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
const persistentAccount = ['persistent-demo', 'production', 'live'].includes(document.body?.dataset.dataMode);
const sourceLabels = {tool_result: 'Kết quả công cụ đã xác minh', interface: 'Hướng dẫn giao diện', store_data: 'Dữ liệu đơn hàng', llm_agent: 'Hội thoại model', safety_rail: 'Rào an toàn', ui_simulation: 'Mô phỏng giao diện', case_timer: 'Nhắc tự động'};
function formatContextOrderLabel(orderId, externalOrderId = null) {
  if (!orderId) return '';
  const matched = Array.isArray(orders) ? orders.find(o => o && o.id === orderId) : null;
  const extId = (typeof externalOrderId === 'string' && externalOrderId.trim())
    ? externalOrderId.trim()
    : (matched && typeof matched.external_order_id === 'string' && matched.external_order_id.trim()
      ? matched.external_order_id.trim()
      : '');
  if (orderScope === 'store_all') {
    return formatDualOrderId(orderId, extId);
  }
  return extId || orderId;
}
function showContext(context) {
  selected = context?.order_id || null;
  focusedExternalOrderId = selected
    ? ((typeof context?.external_order_id === 'string' && context.external_order_id.trim())
      ? context.external_order_id.trim()
      : (orders.find(o => o && o.id === selected)?.external_order_id || null))
    : null;
  byId('conversation-context').textContent = selected
    ? 'Đang trao đổi: ' + formatContextOrderLabel(selected, focusedExternalOrderId)
    : context?.product_id ? 'Đang trao đổi: sản phẩm ' + context.product_id : 'Chưa chọn đơn hoặc sản phẩm';
  renderOrder();
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
  selected = null;
  const result = await api('/api/conversations', {provider_id: nextProvider});
  conversationId = result.conversation_id; providerId = result.provider_id;
  currentCaseId = result.case_id || result.case?.case_id || null;
  currentHandoffId = null;
  caseClosedNotifiedForId = null;
  clearResumeCaseButtons();
  stopBotTimerPolling();
  renderedStaffTurnIds.clear();
  setHumanMode(false);
  renderProvider(); showContext(result.context); byId('messages').replaceChildren();
  message('Phiên mới dùng ' + (selectedProvider()?.model || 'model đã chọn') +
    '. Gửi câu hỏi hoặc chọn đơn bên phải. Khi đổi nguồn, lịch sử bắt đầu lại; trạng thái đơn được giữ.', 'assistant', 'interface');
}
const lockPage = locked => {
  byId('login-shell').hidden = !locked;
  document.querySelectorAll('main, .sidebar').forEach(node => {
    node.hidden = locked;
    node.inert = locked;
  });
};
lockPage(true);

async function api(path, body, extra = {}) {
  const bodyStr = body === undefined ? undefined : JSON.stringify(body);
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {...(cookieAuth ? {} : {Authorization: 'Bearer ' + token}), ...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...extra},
    body: bodyStr,
    credentials: cookieAuth ? 'same-origin' : 'omit', cache: 'no-store', signal: AbortSignal.timeout(150000),
  });
  let result;
  let rawText = '';
  try {
    if (typeof response.json === 'function') {
      result = await response.json();
    }
  } catch (e) {
    if (typeof response.text === 'function') {
      rawText = await response.text().catch(() => '');
    }
  }
  if (!response.ok) {
    if (response.status === 401) lockPage(true);
    const bodySizeKb = bodyStr ? (bodyStr.length / 1024).toFixed(1) + ' KB' : '0 KB';
    const serverHeader = (response.headers && typeof response.headers.get === 'function')
      ? (response.headers.get('server') || 'unknown') : 'unknown';
    console.error('RetailOps API Error:', {
      status: response.status,
      statusText: response.statusText,
      server: serverHeader,
      path,
      payloadSize: bodySizeKb,
      responseBody: (result && result.message) || rawText || '(empty)'
    });
    let messageText;
    if (result && result.message) {
      messageText = result.message;
    } else if (response.status === 413) {
      messageText = `Dung lượng tệp hoặc tin nhắn vượt quá giới hạn máy chủ (HTTP 413: Payload ${bodySizeKb}).`;
    } else if (rawText && rawText.length < 300) {
      messageText = rawText.trim();
    } else {
      messageText = `Lỗi máy chủ HTTP ${response.status} (${response.statusText || 'Lỗi không xác định'}).`;
    }
    const error = new Error(messageText);
    error.status = response.status;
    error.trace = result ? result.trace : null;
    error.debugInfo = {
      status: response.status,
      statusText: response.statusText || '',
      server: serverHeader,
      path,
      payloadSize: bodySizeKb,
      snippet: rawText ? rawText.slice(0, 300) : (result ? JSON.stringify(result) : '(empty)')
    };
    throw error;
  }
  return result;
}

function showErrorDetails(row, error) {
  if (!error || !row) return;
  const details = el('details', 'agent-trace error-trace');
  if (details.style) {
    details.style.borderColor = 'rgba(239, 68, 68, 0.5)';
    details.style.marginTop = '8px';
    details.style.background = 'rgba(239, 68, 68, 0.06)';
    details.style.borderRadius = '8px';
    details.style.border = '1px solid rgba(239, 68, 68, 0.4)';
  }
  const summary = el('summary', '', '🛠️ Chi tiết lỗi kỹ thuật (Debug Info)');
  if (summary.style) {
    summary.style.color = '#ef4444';
    summary.style.cursor = 'pointer';
    summary.style.fontWeight = '600';
    summary.style.padding = '6px 10px';
  }
  details.append(summary);

  const box = el('pre', 'debug-error-box');
  if (box.style) {
    box.style.padding = '8px 12px';
    box.style.margin = '4px 0 0';
    box.style.fontSize = '12px';
    box.style.fontFamily = 'monospace';
    box.style.color = '#f87171';
    box.style.lineHeight = '1.6';
    box.style.whiteSpace = 'pre-wrap';
    box.style.wordBreak = 'break-word';
  }

  const lines = [];
  if (error.status) lines.push(`• HTTP Status: ${error.status} ${error.debugInfo?.statusText || ''}`);
  if (error.debugInfo?.server) lines.push(`• Máy chủ phản hồi (Server Header): ${error.debugInfo.server}`);
  if (error.debugInfo?.path) lines.push(`• Đường dẫn gọi: ${error.debugInfo.path}`);
  if (error.debugInfo?.payloadSize) lines.push(`• Kích thước payload gửi: ${error.debugInfo.payloadSize}`);
  if (error.debugInfo?.snippet && error.debugInfo.snippet !== '(empty)') {
    lines.push(`• Phản hồi thô từ server:\n  ${error.debugInfo.snippet}`);
  }
  box.textContent = lines.join('\n') || (error.message || 'Không có thêm thông tin.');
  details.append(box);
  row.append(details);
}

function resolveAttachmentUrl(attachment, cid = null) {
  if (!attachment || attachment.removed || attachment.purged) return null;
  if (typeof attachment.data === 'string' && attachment.data.length > 0) {
    return attachment.data.startsWith('data:')
      ? attachment.data
      : `data:${attachment.mime_type || 'image/jpeg'};base64,${attachment.data}`;
  }
  if (typeof attachment.download_url === 'string' && attachment.download_url.startsWith('/')) {
    return attachment.download_url;
  }
  const convId = cid || conversationId;
  if (convId && typeof attachment.evidence_id === 'string' && attachment.evidence_id.startsWith('ev_')) {
    return `/api/conversations/${encodeURIComponent(convId)}/evidence/${encodeURIComponent(attachment.evidence_id)}`;
  }
  return null;
}

function buildChatAttachmentCard(attachment, cid = null) {
  const card = el('div', 'chat-attachment-card');
  if (attachment.removed || attachment.purged) {
    const notice = el('div', 'chat-attachment-doc', '📎 Tệp đính kèm đã hết hạn hoặc đã gỡ');
    card.append(notice);
    card.append(el('div', 'chat-attachment-caption', attachment.name || 'Tệp đính kèm'));
    return card;
  }
  const srcUrl = resolveAttachmentUrl(attachment, cid);
  if (attachment.type === 'image' && srcUrl) {
    const img = el('img', 'chat-attachment-img');
    img.src = srcUrl;
    img.alt = attachment.name || 'Ảnh đính kèm';
    img.onclick = (e) => { e.stopPropagation(); openLightbox(img.src, attachment.name); };
    card.append(img);
  } else {
    const doc = el('div', 'chat-attachment-doc');
    doc.append(document.createTextNode(attachment.type === 'image' ? '🖼️ ' : '📄 '));
    if (srcUrl) {
      const link = el('a', 'chat-attachment-link', attachment.name || 'Tài liệu');
      link.href = srcUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      doc.append(link);
    } else {
      doc.append(el('strong', '', attachment.name || 'Tài liệu'));
    }
    card.append(doc);
  }
  card.append(el('div', 'chat-attachment-caption', attachment.name || 'Tệp đính kèm'));
  return card;
}

function message(text, role = 'assistant', source = null, model = null, attachment = null) {
  const row = el('div', 'message ' + role), label = el('div', 'message-label');
  label.append(el('span', role === 'assistant' ? 'mini-r' : '', role === 'assistant' ? 'R' : ''));
  label.append(document.createTextNode(role === 'user' ? 'Bạn' : 'RetailOps' + (source ? ' · ' + (sourceLabels[source] || source) : '') + (model ? ' · ' + model : '')));
  const bubble = el('div', 'bubble');
  if (attachment) {
    bubble.append(buildChatAttachmentCard(attachment, conversationId));
  }
  if (text) {
    bubble.append(document.createTextNode(text));
  }
  row.append(label, bubble);
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

function humanMessage(text, repName = 'Chuyên viên CSKH') {
  const row = el('div', 'message assistant human-message'), label = el('div', 'message-label');
  label.append(el('span', 'human-badge-mini', 'NV'));
  label.append(document.createTextNode(' ' + repName));
  row.append(label, el('div', 'bubble', text));
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

function caseSystemNoticeMessage(text, milestone = '') {
  if (!text) return null;
  const row = el('div', 'message system case-milestone-notice');
  if (milestone) row.dataset.milestone = milestone;
  row.append(el('div', 'system-milestone-pill', text));
  byId('messages').append(row);
  requestAnimationFrame(() => { byId('messages').scrollTop = byId('messages').scrollHeight; });
  return row;
}

function startHumanModePolling() {
  if (humanPollingTimer || typeof setInterval !== 'function') return;
  humanPollingTimer = setInterval(pollHumanChat, 2000);
}

function stopHumanModePolling() {
  if (humanPollingTimer) {
    if (typeof clearInterval === 'function') clearInterval(humanPollingTimer);
    humanPollingTimer = null;
  }
}

function startBotTimerPolling() {
  if (botTimerPollingTimer || isHumanMode || !conversationId || currentSessionRole !== 'customer') return;
  if (typeof setInterval !== 'function') return;
  botTimerPollingTimer = setInterval(pollBotCaseTimer, 5000);
}

function stopBotTimerPolling() {
  if (botTimerPollingTimer) {
    if (typeof clearInterval === 'function') clearInterval(botTimerPollingTimer);
    botTimerPollingTimer = null;
  }
}

async function pollBotCaseTimer() {
  if (!conversationId || isHumanMode) {
    stopBotTimerPolling();
    return;
  }
  try {
    const data = await api('/api/conversations/' + conversationId + '/messages');
    const turns = data.turns || [];
    for (const t of turns) {
      if (renderedStaffTurnIds.has(t.id)) continue;
      let resObj = {};
      try { resObj = typeof t.result === 'string' ? JSON.parse(t.result) : (t.result || {}); } catch (e) {}
      if (resObj.author === 'system_reminder' && resObj.message) {
        renderedStaffTurnIds.add(t.id);
        message(resObj.message, 'assistant', 'case_timer');
      } else if (resObj.author === 'system_order_action' && resObj.message) {
        renderedStaffTurnIds.add(t.id);
        message(resObj.message, 'assistant', 'store_data');
        refresh().catch(() => {});
      } else if (resObj.author === 'system_case_notice' && resObj.message) {
        renderedStaffTurnIds.add(t.id);
        caseSystemNoticeMessage(resObj.message, resObj.milestone || '');
      }
    }
    const c = data.case || null;
    if (c) {
      currentCaseId = c.case_id || currentCaseId;
      if (c.status === 'resolved') {
        stopBotTimerPolling();
        const notifyKey = (c.case_id || conversationId) + ':' + (c.version || 0);
        if (caseClosedNotifiedForId !== notifyKey) {
          caseClosedNotifiedForId = notifyKey;
          const closedNotice = c.resolved_reason === 'completed'
            ? 'Ca hỗ trợ đã hoàn tất và đóng tự động. Bạn vẫn có thể gửi tin nhắn mới bất kỳ lúc nào để tiếp tục.'
            : 'Ca hỗ trợ đã tạm đóng do chưa nhận thêm phản hồi. Bạn có thể gửi tin nhắn bất kỳ lúc nào để mở lại ca này.';
          const closedRow = message(closedNotice, 'assistant', 'interface');
          appendResumeCaseButton(closedRow, conversationId);
          setModelStatus('Ca hỗ trợ đã đóng', 'Bấm Tiếp tục hoặc nhắn tin mới để mở lại');
        }
      } else if (!c.has_active_timer) {
        stopBotTimerPolling();
      }
    }
  } catch (e) {
    stopBotTimerPolling();
  }
}

async function pollHumanChat() {
  if (!isHumanMode || !conversationId) return;
  try {
    const data = await api('/api/conversations/' + conversationId + '/messages');
    const turns = data.turns || [];
    let lastResolvedNoticeRow = null;
    for (const t of turns) {
      if (renderedStaffTurnIds.has(t.id)) continue;
      renderedStaffTurnIds.add(t.id);

      let resObj = {};
      try { resObj = typeof t.result === 'string' ? JSON.parse(t.result) : (t.result || {}); } catch (e) {}
      if (resObj.author === 'staff' && resObj.message) {
        humanMessage(resObj.message, resObj.staff_name || 'Chuyên viên CSKH');
        setModelStatus('Đã nhận phản hồi', resObj.staff_name || 'Chuyên viên CSKH');
      } else if (resObj.author === 'system_order_action' && resObj.message) {
        message(resObj.message, 'assistant', 'store_data');
        setModelStatus('Cập nhật yêu cầu đơn hàng', resObj.order_id || 'Đã cập nhật trạng thái');
        refresh().catch(() => {});
      } else if (resObj.author === 'system_case_notice' && resObj.message) {
        const noticeRow = caseSystemNoticeMessage(resObj.message, resObj.milestone || '');
        if (resObj.milestone === 'case_resolved') {
          lastResolvedNoticeRow = noticeRow;
        }
      }
    }

    const feedbacks = data.feedbacks || [];
    const isResolved = (data.case && data.case.status === 'resolved')
      || feedbacks.some(f => f.feedback_type === 'human_handoff' && f.reason_code === 'resolved');
    if (isResolved && isHumanMode) {
      if (!pollHumanChat.resolvedNotified) {
        pollHumanChat.resolvedNotified = true;
        currentHandoffId = null;
        setHumanMode(false);
        const targetRow = lastResolvedNoticeRow || caseSystemNoticeMessage('Ca hỗ trợ đã hoàn tất.', 'case_resolved');
        appendResumeCaseButton(targetRow, conversationId);
        setModelStatus('Ca hỗ trợ đã hoàn tất', 'Bấm Tiếp tục hoặc gửi tin mới để mở lại');
      }
    } else {
      pollHumanChat.resolvedNotified = false;
    }
  } catch (e) {
    // background polling silent
  }
}

function setHumanMode(active, repName = 'Chuyên viên CSKH') {
  isHumanMode = active;
  const avatar = byId('chat-agent-avatar');
  const title = byId('chat-title');
  const subtitle = byId('chat-subtitle');
  const btnMeet = byId('btn-meet-human');
  const badge = byId('session-badge');

  if (active) {
    stopBotTimerPolling();
    startHumanModePolling();
    if (avatar) { avatar.textContent = 'NV'; avatar.classList?.toggle?.('human', true); }
    if (title) title.textContent = repName;
    if (subtitle) subtitle.textContent = 'Đã yêu cầu hỗ trợ trực tiếp · Nhân viên sẽ phản hồi tại đây';
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

async function toggleHumanMode() {
  if (!isHumanMode) {
    if (!conversationId) {
      message('Chưa có phiên hội thoại đang mở để kết nối nhân viên. Hãy tạo cuộc trò chuyện mới.', 'assistant', 'interface');
      return;
    }
    try {
      const res = await api('/api/feedback', {
        conversation_id: conversationId,
        feedback_type: 'human_handoff',
        reason_code: 'customer_requested_human',
        comment: 'Khách hàng yêu cầu kết nối chuyên viên tư vấn trực tiếp'
      });
      currentCaseId = res?.case_id || currentCaseId;
      currentHandoffId = res?.handoff_id || null;
      setHumanMode(true);
      if (res?.notice_turn_id && res?.notice_message && !renderedStaffTurnIds.has(res.notice_turn_id)) {
        renderedStaffTurnIds.add(res.notice_turn_id);
        caseSystemNoticeMessage(res.notice_message, 'handoff_requested');
      }
    } catch (err) {
      setHumanMode(false);
      message('Không thể gửi yêu cầu gặp nhân viên: ' + (err.message || 'Lỗi máy chủ'), 'assistant', 'interface');
      setModelStatus('Chưa chuyển được nhân viên', 'Vui lòng thử lại');
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
  if (conversationId && !isHumanMode) {
    api('/api/conversations/' + conversationId + '/feedback-prompt', {})
      .then(r => { if (r?.case?.has_active_timer) startBotTimerPolling(); })
      .catch(() => {});
  }
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
  catch (error) {
    const row = message(error.message || 'Mất kết nối. Tải lại trạng thái trước khi thử tiếp.', 'assistant', 'interface');
    if (error.debugInfo) showErrorDetails(row, error);
  }
  finally {
    busy = false;
    document.querySelectorAll('[data-busy-disabled]').forEach(b => { b.disabled = false; delete b.dataset.busyDisabled; });
  }
}

function syncManagerButtonsVisibility() {
  const isManager = currentSessionRole === 'manager'
    || currentSessionRole === 'platform_admin'
    || (orderScope === 'store_all' && !['customer', 'staff', 'viewer'].includes(currentSessionRole));
  const btnHeaderMgr = byId('btn-open-manager-console');
  if (btnHeaderMgr) {
    btnHeaderMgr.hidden = !isManager;
    if (btnHeaderMgr.style) btnHeaderMgr.style.display = isManager ? 'inline-flex' : 'none';
  }
  const btnSidebarMgr = byId('btn-sidebar-manager-nav');
  if (btnSidebarMgr) {
    btnSidebarMgr.hidden = !isManager;
    if (btnSidebarMgr.style) btnSidebarMgr.style.display = isManager ? 'flex' : 'none';
  }
  const btnPanelMgr = byId('btn-panel-manager-banner');
  if (btnPanelMgr) {
    btnPanelMgr.hidden = !isManager;
    if (btnPanelMgr.style) btnPanelMgr.style.display = isManager ? 'flex' : 'none';
  }
  const isStrictManager = currentSessionRole === 'manager';
  const btnInspector = byId('toggle-inspector');
  if (btnInspector) {
    btnInspector.hidden = !isStrictManager;
    if (btnInspector.style) btnInspector.style.display = isStrictManager ? 'flex' : 'none';
  }
  if (!isStrictManager && byId('inspector-dialog')?.open) {
    byId('inspector-dialog').close();
  }
}

function renderOrder() {
  const isManager = orderScope === 'store_all';
  syncManagerButtonsVisibility();
  if (selected) {
    const matchedSelected = orders.find(o => o && o.id === selected);
    if (matchedSelected?.external_order_id) {
      focusedExternalOrderId = matchedSelected.external_order_id;
    }
    const ctxNode = byId('conversation-context');
    if (ctxNode) {
      ctxNode.textContent = 'Đang trao đổi: ' + formatContextOrderLabel(selected, focusedExternalOrderId);
    }
  }

  let filtered = orders;
  if (managerFilter !== 'all') {
    filtered = filtered.filter(o => o.status === managerFilter);
  }
  if (orderSearchQuery) {
    const q = orderSearchQuery.toLowerCase();
    filtered = filtered.filter(o =>
      o.id.toLowerCase().includes(q) ||
      (o.external_order_id && o.external_order_id.toLowerCase().includes(q)) ||
      ((o.display_name || o.name) && (o.display_name || o.name).toLowerCase().includes(q)) ||
      (o.customer_id && o.customer_id.toLowerCase().includes(q))
    );
  }

  const order = orders.find(o => o.id === selected) || filtered[0];
  const area = byId('order-details');
  area.replaceChildren();

  // Legacy tabs container (for test harness and accessibility)
  const tabs = byId('order-tabs');
  if (tabs) {
    tabs.replaceChildren();
    for (const item of orders) {
      const isSelected = Boolean(selected && item.id === selected);
      const tabLabel = isManager ? formatDualOrderId(item.id, item.external_order_id) : formatCustomerOrderId(item);
      const button = el('button', isSelected ? 'selected' : '', tabLabel);
      button.dataset.order = item.id;
      button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      button.onclick = () => act(() => lookupOrder(item.id));
      tabs.append(button);
    }
  }

  // Render vertical card list in #order-card-list
  const cardList = byId('order-card-list');
  if (cardList) {
    cardList.replaceChildren();
    if (!filtered.length) {
      cardList.append(el('p', 'order-empty', 'Không tìm thấy đơn hàng phù hợp.'));
    } else {
      for (const item of filtered) {
        const active = Boolean(selected && item.id === selected);
        const card = el('div', 'order-card-item' + (active ? ' selected' : ''));
        card.dataset.order = item.id;

        const header = el('div', 'order-card-header');
        const cardLabel = isManager ? formatDualOrderId(item.id, item.external_order_id) : formatCustomerOrderId(item);
        header.append(
          el('span', 'order-card-oid', cardLabel),
          el('span', 'order-card-badge ' + item.status, statuses[item.status] || item.status)
        );

        const title = el('div', 'order-card-title', item.display_name || item.name || 'Sản phẩm');

        const footer = el('div', 'order-card-footer');
        footer.append(el('span', 'order-card-price', money(item.amount)));
        if (isManager && item.customer_id) {
          footer.append(el('span', 'order-card-cust', 'Khách ' + item.customer_id));
        }

        card.append(header, title, footer);
        card.onclick = () => act(() => lookupOrder(item.id));
        cardList.append(card);
      }
    }
  }

  byId('order-count').textContent = isManager
    ? (orders.length + ' đơn toàn shop')
    : (orders.length + (persistentAccount ? ' đơn hàng' : ' đơn mẫu'));
  const headerTitle = byId('order-panel-title');
  if (headerTitle) headerTitle.textContent = isManager ? 'Toàn bộ đơn hàng Shop' : 'Đơn hàng của bạn';

  if (!order) {
    area.append(el('p', 'order-empty', 'Chưa có thông tin đơn. Hãy kết nối hoặc tải lại dữ liệu.'));
    return;
  }

  const top = el('div', 'order-line');
  const detailHeading = isManager ? formatDualOrderId(order.id, order.external_order_id) : formatCustomerOrderId(order);
  top.append(el('h3', '', detailHeading), el('span', 'badge ' + order.status, statuses[order.status] || order.status));
  const item = el('div', 'item'), copy = el('div');
  copy.append(el('strong', '', order.display_name || order.name), el('p', '', order.variant));
  item.append(copy);
  const total = el('div', 'detail-row total');
  total.append(el('span', '', 'Tổng cộng'), el('strong', '', money(order.amount)));
  area.append(top);
  if (isManager) {
    area.append(el('p', 'order-date', 'Đơn ' + (order.customer_id ? ('khách ' + order.customer_id + ' · ') : '') + 'Phiên bản ' + order.version));
  }
  area.append(item, total);
  if (!isManager && order.recipient && typeof order.recipient === 'object') {
    const recBox = el('div', 'order-recipient-box');
    recBox.dataset.role = 'customer-recipient';
    const areaParts = [order.recipient.ward, order.recipient.district, order.recipient.province].filter(Boolean);
    if (order.recipient.purged) {
      recBox.append(
        el('p', 'order-recipient-line', 'SĐT người nhận: ' + (order.recipient.phone_masked || '—')),
        el('p', 'order-recipient-line', 'Khu vực: ' + (areaParts.join(', ') || '—')),
        el('small', 'order-recipient-note', 'Thông tin người nhận chi tiết đã xóa theo thời hạn lưu trữ.')
      );
    } else {
      const fullAddr = [order.recipient.address_line, ...areaParts].filter(Boolean).join(', ');
      recBox.append(
        el('p', 'order-recipient-line', 'Người nhận: ' + (order.recipient.name || '—')),
        el('p', 'order-recipient-line', 'SĐT: ' + (order.recipient.phone || order.recipient.phone_masked || '—')),
        el('p', 'order-recipient-line', 'Địa chỉ: ' + (fullAddr || '—'))
      );
    }
    area.append(recBox);
  }
  area.append(el('p', 'order-policy', order.status === 'pending'
    ? 'Có thể yêu cầu hủy. Cần chọn lý do và xác nhận gửi cửa hàng duyệt.'
    : order.status === 'shipping'
      ? 'Đơn đang vận chuyển: không hỗ trợ hủy tự phục vụ; vui lòng nhắn CSKH nếu cần hỗ trợ.'
      : order.status === 'delivered'
        ? 'Đơn đã giao: có thể gửi yêu cầu trả hàng hoặc đổi hàng kèm ảnh bằng chứng.'
        : 'Đơn đã hủy. Trạng thái được lưu trên máy chủ.'));

  const lookup = el('button', 'order-action', 'Tra cứu đơn này');
  lookup.onclick = () => act(() => lookupOrder(order.id));
  area.append(lookup);

  if (canCancel) {
    if (order.status === 'pending') {
      const cancel = el('button', 'order-action', 'Yêu cầu hủy đơn này');
      cancel.onclick = () => act(() => chooseReason(order.id, 'cancel'));
      area.append(cancel);
    } else if (order.status === 'delivered') {
      const retEx = el('button', 'order-action', 'Yêu cầu trả / đổi hàng');
      retEx.onclick = () => act(() => chooseReason(order.id, 'return'));
      area.append(retEx);
    }
  } else {
    area.append(el('p', 'order-policy', 'Tài khoản của bạn có quyền xem; không được tạo yêu cầu hủy.'));
  }
}

const eventLabels = {
  order_viewed: 'Tra cứu đơn', cancellation_proposed: 'Tạo đề xuất hủy', order_cancelled: 'Đã xác nhận hủy',
  order_action_requested: 'Gửi yêu cầu đơn hàng', order_action_status_changed: 'Cập nhật yêu cầu đơn hàng',
  proposal_dismissed: 'Bỏ đề xuất', model_extraction: 'Model phân tích yêu cầu', model_unavailable: 'Không kết nối được model',
  chat_replied: 'Trả lời hội thoại', agent_replied: 'Phản hồi hội thoại', agent_failed: 'Lượt chat chưa hoàn tất',
  product_created: 'Thêm sản phẩm', product_updated: 'Sửa sản phẩm', product_deleted: 'Xóa sản phẩm',
  order_status_updated_by_manager: 'Đổi trạng thái đơn', case_transferred: 'Chuyển ca hỗ trợ'
};
async function refresh() {
  const [data, history] = await Promise.all([api('/api/orders'), api('/api/events')]);
  orders = data.orders || [];
  orderScope = data.scope || 'customer';
  if (selected && !orders.some(o => o.id === selected)) selected = null;
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

async function uploadOrderActionEvidence(requestId, file) {
  const response = await fetch('/api/order-actions/' + encodeURIComponent(requestId) + '/evidence', {
    method: 'POST',
    headers: {
      ...(cookieAuth ? {} : {Authorization: 'Bearer ' + token}),
      'Content-Type': (file && file.type) || 'application/octet-stream'
    },
    body: file,
    credentials: cookieAuth ? 'same-origin' : 'omit',
    cache: 'no-store',
    signal: AbortSignal.timeout(150000),
  });
  let result = null;
  try {
    if (typeof response.json === 'function') result = await response.json();
  } catch (_) {}
  if (!response.ok) {
    if (response.status === 401) lockPage(true);
    const err = new Error((result && result.message) || ('Không tải được ảnh bằng chứng (HTTP ' + response.status + ').'));
    err.status = response.status;
    throw err;
  }
  return result;
}

async function loadReasonCatalog(force = false) {
  if (reasonCatalog && !force) return reasonCatalog;
  try {
    const data = await api('/api/order-action-reasons');
    reasonCatalog = data && Array.isArray(data.reasons) ? data : null;
  } catch (error) {
    reasonCatalog = null;
  }
  return reasonCatalog;
}

function reasonEntry(code) {
  return (reasonCatalog?.reasons || []).find(entry => entry.code === code) || null;
}

function reasonLabel(code) {
  return reasonEntry(code)?.label || code || '—';
}

// Reasons a request type can use, in catalog order; staff-only reasons only when the caller is staff.
function reasonsForType(actionType, staff = false) {
  return (reasonCatalog?.reasons || []).filter(entry => Array.isArray(entry.applies_to)
    && entry.applies_to.includes(actionType) && (staff || !entry.staff_only));
}

function variantStockText(variant) {
  if (typeof variant.stock === 'number') return variant.stock > 0 ? 'còn ' + variant.stock : 'hết hàng';
  return stockLabels[variant.stock_status] || stockLabels.unknown;
}

async function chooseReason(id, requestedType = null, requestedExchangeKind = null, requestedTargetVariantId = null) {
  if (!canCancel) { message('Tài khoản của bạn có quyền xem; không được tạo yêu cầu hủy.', 'assistant', 'interface'); return; }
  if (!(await loadReasonCatalog())) {
    message('Chưa tải được danh mục lý do yêu cầu. Bạn thử lại sau một lát nhé.', 'assistant', 'interface');
    return;
  }
  const result = await api('/api/conversations/' + conversationId + '/focus', {order_id: id});
  const order = result.order; showContext(result.context); selected = order.id; await refresh();
  let actionType = 'cancel';
  let exchangeKind = null;
  if (order.status === 'pending') {
    actionType = 'cancel';
  } else if (order.status === 'delivered') {
    actionType = (requestedType === 'exchange' || requestedType === 'return') ? requestedType : 'return';
    exchangeKind = actionType === 'exchange' ? (requestedExchangeKind === 'same_variant' ? 'same_variant' : 'other_variant') : null;
  } else {
    message('Đơn ' + id + ' ' + (statuses[order.status] || order.status).toLowerCase() + ', không đủ điều kiện tạo yêu cầu.');
    return;
  }

  const introText = actionType === 'cancel'
    ? ('Bạn chọn lý do hủy ' + id + ', có thể đính kèm ảnh nếu cần, rồi bấm xác nhận để gửi yêu cầu nhé.')
    : ('Bạn chọn hình thức trả/đổi và lý do cho đơn ' + id + ', đính kèm ảnh bằng chứng nếu muốn, rồi bấm xác nhận nhé.');
  const row = message(introText, 'assistant', 'store_data');
  const card = el('div', 'proposal order-action-card');
  const group = 'reason-' + crypto.randomUUID();
  const textLimit = Number(reasonCatalog.text_max_length) || 500;
  let reason = null;
  let targetVariantId = null;
  let exchangeOptions = null;
  let selectedFiles = [];

  const titleHeading = el('h3', '');
  const updateHeading = () => {
    if (actionType === 'cancel') titleHeading.textContent = 'Yêu cầu hủy · ' + id;
    else if (actionType === 'return') titleHeading.textContent = 'Yêu cầu trả hàng · ' + id;
    else titleHeading.textContent = 'Yêu cầu đổi hàng (' + exchangeKindLabels[exchangeKind] + ') · ' + id;
  };
  updateHeading();
  card.append(titleHeading);

  const button = el('button', 'primary order-action-submit-btn', 'Xác nhận gửi yêu cầu');
  button.type = 'button';
  button.disabled = true;

  const noteInput = el('textarea', 'order-action-note');
  noteInput.rows = 2;
  noteInput.maxLength = textLimit;
  const needsText = () => Boolean(reason && reasonEntry(reason)?.requires_text);
  const needsTarget = () => actionType === 'exchange' && exchangeKind === 'other_variant';
  const syncSubmit = () => {
    const textMissing = needsText() && !(noteInput.value || '').trim();
    noteInput.required = needsText();
    noteInput.placeholder = needsText()
      ? 'Mô tả lý do (bắt buộc, tối đa ' + textLimit + ' ký tự)…'
      : 'Mô tả thêm tình trạng hoặc yêu cầu (tùy chọn, tối đa ' + textLimit + ' ký tự)…';
    button.disabled = busy || !reason || textMissing || (needsTarget() && !targetVariantId);
  };

  const cardError = el('p', 'proposal-error');
  cardError.setAttribute('role', 'alert');

  const reasonsBox = el('div', 'order-action-reasons');
  const renderReasons = () => {
    reasonsBox.replaceChildren();
    reason = null;
    for (const entry of reasonsForType(actionType)) {
      const line = el('label'), input = el('input');
      input.type = 'radio'; input.name = group; input.value = entry.code;
      input.onchange = () => { reason = entry.code; syncSubmit(); };
      line.append(input, document.createTextNode(entry.label));
      reasonsBox.append(line);
    }
    syncSubmit();
  };

  // An exchange to another variant names the variant: the real variants of the product with their stock.
  const targetBox = el('div', 'order-action-field order-action-target');
  targetBox.hidden = true;
  const targetSelect = el('select', 'order-action-target-select');
  const targetHint = el('small', 'order-action-target-hint', '');
  targetBox.append(el('span', 'order-action-field-label', 'Biến thể muốn đổi sang:'), targetSelect, targetHint);
  targetSelect.onchange = () => { targetVariantId = targetSelect.value || null; syncSubmit(); };
  const renderTarget = async () => {
    targetBox.hidden = !needsTarget();
    if (!needsTarget()) { targetVariantId = null; syncSubmit(); return; }
    if (!exchangeOptions) {
      try {
        exchangeOptions = await api('/api/orders/' + encodeURIComponent(id) + '/exchange-options');
      } catch (err) {
        cardError.textContent = err.message || 'Không tải được danh sách biến thể của sản phẩm.';
        exchangeOptions = {variants: []};
      }
    }
    if (!needsTarget()) return;  // the customer switched to another kind while the options were loading
    const variants = Array.isArray(exchangeOptions.variants) ? exchangeOptions.variants : [];
    targetSelect.replaceChildren();
    const placeholder = el('option', '', '— Chọn biến thể —');
    placeholder.value = '';
    targetSelect.append(placeholder);
    for (const variant of variants) {
      const option = el('option', '', variant.label + ' · ' + variantStockText(variant) + (variant.is_current ? ' (đang giữ)' : ''));
      option.value = variant.id;
      option.disabled = Boolean(variant.is_current);
      targetSelect.append(option);
    }
    const wanted = variants.some(v => v.id === requestedTargetVariantId && !v.is_current) ? requestedTargetVariantId : '';
    targetSelect.value = wanted;
    targetVariantId = wanted || null;
    targetHint.textContent = variants.length
      ? 'Tồn kho chỉ để tham khảo; cửa hàng quyết định khi duyệt yêu cầu.'
      : 'Đơn này chưa có danh sách biến thể để chọn. Hãy chọn "Đổi cùng biến thể" hoặc nhờ nhân viên hỗ trợ.';
    syncSubmit();
  };

  if (order.status === 'delivered') {
    const kindRow = el('div', 'order-action-field');
    const kindLabel = el('span', 'order-action-field-label', 'Hình thức yêu cầu:');
    const kindSelect = el('select', 'order-action-kind-select');
    for (const [val, lbl] of [
      ['return', 'Trả hàng'],
      ['exchange:other_variant', 'Đổi hàng · ' + exchangeKindLabels.other_variant + ' (màu, size, kiểu…)'],
      ['exchange:same_variant', 'Đổi hàng · ' + exchangeKindLabels.same_variant + ' (hàng lỗi)']
    ]) {
      const opt = el('option', '', lbl);
      opt.value = val;
      kindSelect.append(opt);
    }
    kindSelect.value = actionType === 'exchange' ? ('exchange:' + exchangeKind) : 'return';
    kindSelect.onchange = () => {
      const val = kindSelect.value;
      if (val.startsWith('exchange:')) {
        actionType = 'exchange';
        exchangeKind = val.split(':')[1] === 'same_variant' ? 'same_variant' : 'other_variant';
      } else {
        actionType = 'return';
        exchangeKind = null;
      }
      updateHeading();
      renderReasons();
      return renderTarget();
    };
    kindRow.append(kindLabel, kindSelect);
    card.append(kindRow);
  }

  renderReasons();
  card.append(reasonsBox);
  card.append(targetBox);

  noteInput.oninput = () => syncSubmit();
  card.append(noteInput);

  const evWrap = el('div', 'order-action-evidence-wrap');
  const evInput = el('input', 'order-action-evidence-input');
  evInput.type = 'file';
  evInput.accept = 'image/jpeg,image/png,image/webp,application/pdf';
  evInput.multiple = true;
  const evHint = el('small', 'order-action-evidence-hint', 'Đính kèm bằng chứng (tùy chọn, tối đa 5 tệp JPEG/PNG/WebP ≤ 10MB hoặc PDF ≤ 20MB).');

  evInput.onchange = () => {
    cardError.textContent = '';
    const files = Array.from(evInput.files || []);
    if (files.length > 5) {
      selectedFiles = [];
      evInput.value = '';
      cardError.textContent = 'Chỉ được đính kèm tối đa 5 tệp bằng chứng cho mỗi yêu cầu.';
      evHint.textContent = 'Chưa chọn tệp bằng chứng.';
      return;
    }
    for (const f of files) {
      if (f.type && !['image/jpeg', 'image/png', 'image/webp', 'application/pdf'].includes(f.type)) {
        selectedFiles = [];
        evInput.value = '';
        cardError.textContent = 'Chỉ chấp nhận tệp JPEG, PNG, WebP hoặc PDF.';
        evHint.textContent = 'Chưa chọn tệp bằng chứng.';
        return;
      }
      const isPdfFile = f.type === 'application/pdf';
      const maxBytes = isPdfFile ? 20971520 : 10485760;
      if (typeof f.size === 'number' && f.size > maxBytes) {
        selectedFiles = [];
        evInput.value = '';
        cardError.textContent = isPdfFile
          ? 'Mỗi tệp PDF bằng chứng không được vượt quá 20MB.'
          : 'Mỗi ảnh bằng chứng không được vượt quá 10MB.';
        evHint.textContent = 'Chưa chọn tệp bằng chứng.';
        return;
      }
    }
    selectedFiles = files;
    evHint.textContent = files.length
      ? ('Đã chọn ' + files.length + ' tệp bằng chứng: ' + files.map(f => f.name).join(', '))
      : 'Đính kèm bằng chứng (tùy chọn, tối đa 5 tệp JPEG/PNG/WebP ≤ 10MB hoặc PDF ≤ 20MB).';
  };
  evWrap.append(evInput, evHint);
  card.append(evWrap, cardError);

  button.onclick = () => act(async () => {
    if (!reason || (needsText() && !(noteInput.value || '').trim()) || (needsTarget() && !targetVariantId)) return;
    cardError.textContent = '';
    const payload = {
      order_id: id,
      type: actionType,
      expected_order_version: order.version,
      reason_code: reason,
    };
    if (conversationId) payload.conversation_id = conversationId;
    if (actionType === 'exchange') {
      payload.exchange_kind = exchangeKind;
      if (exchangeKind === 'other_variant') payload.target_variant_id = targetVariantId;
    }
    const cleanNote = (noteInput.value || '').trim();
    if (cleanNote) payload.reason_text = cleanNote.slice(0, textLimit);

    let created;
    try {
      created = await api('/api/order-actions', payload);
    } catch (err) {
      cardError.textContent = err.message || 'Không gửi được yêu cầu đơn hàng.';
      return;
    }
    const reqObj = created.request || {};
    card.querySelectorAll('button,input,select,textarea').forEach(n => { n.disabled = true; delete n.dataset.busyDisabled; });

    let uploadedCount = 0;
    let uploadErr = null;
    for (const f of selectedFiles) {
      try {
        await uploadOrderActionEvidence(reqObj.request_id, f);
        uploadedCount += 1;
      } catch (err) {
        uploadErr = err;
        break;
      }
    }
    if (reqObj.case_id) currentCaseId = reqObj.case_id;
    setHumanMode(true, 'Chuyên viên CSKH');
    let confirmMsg = created.message || ('Đã gửi yêu cầu cho đơn ' + id + ', chờ cửa hàng duyệt.');
    if (uploadedCount > 0) {
      confirmMsg += ' (Đã đính kèm ' + uploadedCount + ' ảnh bằng chứng.)';
    }
    if (uploadErr) {
      confirmMsg += ' Lưu ý tải ảnh: ' + uploadErr.message;
    }
    message(confirmMsg, 'assistant', 'store_data');
    await refresh();
  });

  card.append(button, el('small', '', 'Yêu cầu sẽ được chuyển tới nhân viên cửa hàng xét duyệt và thông báo trạng thái ngay trong hội thoại này.'));
  row.append(card);
  await renderTarget();
}

function openProposal(proposal) {
  // Proposal ID is a stable idempotency key, not an authentication credential.
  pending = {...proposal, key: proposal.proposal_id};
  byId('confirm-title').textContent = 'Gửi yêu cầu hủy đơn ' + proposal.order.id + '?';
  byId('confirm-description').textContent = (proposal.order.display_name || proposal.order.name) + ' · ' + money(proposal.order.amount)
    + '. Hết hạn: ' + new Date(proposal.expires_at * 1000).toLocaleTimeString('vi-VN') + '.';
  byId('confirm-reason').textContent = reasonLabel(proposal.reason);
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
    pending = null; byId('confirm-dialog').close(); message(result.message + (result.replayed ? ' Đây là kết quả của lần xác nhận trước, không gửi lặp yêu cầu.' : ''));
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

function shipmentText(value) {
  if (typeof value !== 'string') return '';
  const clean = value.trim();
  return /^(null|undefined|none)$/i.test(clean) ? '' : clean.slice(0, 400);
}

function formatShipmentTimeVn(value) {
  const clean = shipmentText(value);
  if (!clean) return '';
  if (!/^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(clean)) return clean;
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(clean);
  const isoNorm = (hasOffset ? clean.replace(' ', 'T') : clean.replace(' ', 'T') + '+07:00');
  const ms = Date.parse(isoNorm);
  if (!Number.isFinite(ms)) return clean;
  const vn = new Date(ms + 7 * 3600 * 1000);
  const pad2 = n => String(n).padStart(2, '0');
  return `${pad2(vn.getUTCHours())}:${pad2(vn.getUTCMinutes())} ${pad2(vn.getUTCDate())}/${pad2(vn.getUTCMonth() + 1)}/${vn.getUTCFullYear()}`;
}

function showShipment(row, shipment) {
  if (!shipment || typeof shipment !== 'object' || Array.isArray(shipment)) return;
  const card = el('div', 'shipment-card');
  const header = el('div', 'shipment-header');
  const status = typeof shipment.status === 'string' && /^[a-z_]{1,40}$/.test(shipment.status) ? shipment.status : 'unknown';
  const rawCode = shipmentText(shipment.carrier_status_raw);
  const statusBase = shipmentText(shipment.status_text) || 'Ch\u01b0a c\u00f3 d\u1eef li\u1ec7u h\u00e0nh tr\u00ecnh';
  const pillLabel = rawCode ? `${statusBase} (${rawCode})` : statusBase;
  header.append(
    el('strong', '', '\ud83d\ude9a ' + (shipmentText(shipment.carrier) || 'Th\u00f4ng tin v\u1eadn chuy\u1ec3n')),
    el('span', 'tracking-pill ' + status, pillLabel)
  );
  const body = el('div', 'shipment-body');
  const trackingCode = shipmentText(shipment.tracking_code);
  if (trackingCode) body.append(el('p', '', 'M\u00e3 v\u1eadn \u0111\u01a1n: ' + trackingCode));
  const area = shipmentText(shipment.current_area) || shipmentText(shipment.current_location);
  if (area) body.append(el('p', '', 'V\u1ecb tr\u00ed g\u1ea7n nh\u1ea5t: ' + area));
  const shipperName = shipmentText(shipment.shipper_name);
  const shipperPhone = shipmentText(shipment.shipper_phone_masked);
  const shipperCombined = (shipperName && shipperPhone)
    ? `${shipperName} (${shipperPhone})`
    : (shipperName || shipperPhone || shipmentText(shipment.shipper));
  if (shipperCombined) body.append(el('p', '', 'Shipper: ' + shipperCombined));
  const isDeliveredShipment = status === 'delivered' || Boolean(shipmentText(shipment.delivered_at));
  if (isDeliveredShipment) {
    const deliveredAt = formatShipmentTimeVn(shipment.delivered_at);
    if (deliveredAt) body.append(el('p', 'delivery-eta', '\u2705 \u0110\u00e3 giao l\u00fac: ' + deliveredAt));
  } else {
    const eta = formatShipmentTimeVn(shipment.estimated_delivery_at || shipment.estimated_delivery);
    if (eta) body.append(el('p', 'delivery-eta', '\u23f0 D\u1ef1 ki\u1ebfn nh\u1eadn: ' + eta));
  }
  if (typeof shipment.delivery_attempts === 'number' && Number.isFinite(shipment.delivery_attempts) && shipment.delivery_attempts > 0) {
    body.append(el('p', '', 'S\u1ed1 l\u1ea7n giao: ' + shipment.delivery_attempts));
  }
  const failReason = shipmentText(shipment.fail_reason);
  if (failReason) body.append(el('p', '', 'L\u00fd do giao th\u1ea5t b\u1ea1i: ' + failReason));

  const events = Array.isArray(shipment.events)
    ? shipment.events.filter(ev => ev && typeof ev === 'object' && (shipmentText(ev.description) || shipmentText(ev.status_text) || shipmentText(ev.location))).slice(0, 30)
    : [];
  const legacySteps = !events.length && Array.isArray(shipment.steps)
    ? shipment.steps.filter(step => step && shipmentText(step.event)).slice(0, 20)
    : [];
  if (events.length) {
    const timeline = el('div', 'shipment-timeline');
    for (const ev of events) {
      const item = el('div', 'timeline-item');
      const loc = shipmentText(ev.location)
        || [shipmentText(ev.hub_name), shipmentText(ev.district), shipmentText(ev.province)].filter(Boolean).join(', ');
      const desc = shipmentText(ev.description) || shipmentText(ev.status_text);
      const evtLabel = (loc && desc && !desc.includes(loc)) ? `${loc} \u2014 ${desc}` : (desc || loc);
      item.append(el('span', 'timeline-time', formatShipmentTimeVn(ev.occurred_at)), el('span', 'timeline-event', evtLabel));
      timeline.append(item);
    }
    body.append(timeline);
  } else if (legacySteps.length) {
    const timeline = el('div', 'shipment-timeline');
    for (const step of legacySteps) {
      const item = el('div', 'timeline-item');
      item.append(el('span', 'timeline-time', formatShipmentTimeVn(step.time)), el('span', 'timeline-event', shipmentText(step.event)));
      timeline.append(item);
    }
    body.append(timeline);
  }
  if (!body.children.length) {
    body.append(el('p', '', 'H\u1ec7 th\u1ed1ng ch\u01b0a c\u00f3 m\u00e3 v\u1eadn \u0111\u01a1n, v\u1ecb tr\u00ed ho\u1eb7c ng\u00e0y giao d\u1ef1 ki\u1ebfn cho \u0111\u01a1n n\u00e0y.'));
  }
  card.append(header, body);
  row.append(card);
}

function showHumanSupport(row, support) {
  if (!support) return;
  const card = el('div', 'human-support-card');
  card.append(
    el('div', 'human-header', '🙋 Chuyên viên CSKH'),
    el('p', '', support.message || 'Đã chuyển cuộc trò chuyện sang nhân viên hỗ trợ.'),
    el('span', 'badge-handoff', '🙋 Đã chuyển yêu cầu · Hàng đợi: ' + (support.queue || 'Ưu tiên VIP'))
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
  const toolErrors = {
    order_not_found: 'kh\u00f4ng t\u00ecm th\u1ea5y trong t\u00e0i kho\u1ea3n',
    ambiguous_order: 'm\u00e3 \u0111\u01a1n kh\u1edbp nhi\u1ec1u \u0111\u01a1n; c\u1ea7n h\u1ecfi r\u00f5',
    tool_not_allowed: 'ngo\u00e0i ph\u1ea1m vi worker; kh\u00f4ng th\u1ef1c thi',
    invalid_tool_arguments: 'tham s\u1ed1 kh\u00f4ng h\u1ee3p l\u1ec7',
    product_not_found: 'ch\u01b0a t\u00ecm th\u1ea5y trong danh m\u1ee5c',
    permission_denied: 'kh\u00f4ng \u0111\u1ee7 quy\u1ec1n',
    tool_unavailable: 'ngu\u1ed3n d\u1eef li\u1ec7u ch\u01b0a s\u1eb5n s\u00e0ng'
  };
  const names = (trace.tools || []).map(t => t.name + (t.status === 'error'
    ? ' (' + (toolErrors[t.error_code] || 'b\u1ecb t\u1eeb ch\u1ed1i / l\u1ed7i') + ')' : ''));
  details.append(el('p', '', (trace.model || 'model') + ' · ' + (trace.model_calls || 0) + ' lượt gọi model' +
    (typeof trace.latency_ms === 'number' && Number.isFinite(trace.latency_ms) && trace.latency_ms >= 0 ? ' · ' + (trace.latency_ms / 1000).toFixed(2) + ' giây' : '')),
    el('p', '', 'Công cụ: ' + (names.join(' → ') || 'Không dùng công cụ ở lượt này')),
    el('small', '', 'Mã lượt: ' + trace.turn_id + (trace.model_digest ? ' · Digest: ' + trace.model_digest : ' · API không cung cấp digest trọng số')));
  if (trace.provider) details.append(el('small', '', 'Nguồn: ' + trace.provider));
  if (trace.reported_cost_usd !== null && trace.reported_cost_usd !== undefined) {
    details.append(el('small', '', 'Chi phí lượt này do API báo: $' + trace.reported_cost_usd.toFixed(6)));
  }
  if (Array.isArray(trace.steps) && trace.steps.length > 0) {
    const stepsPanel = el('div', 'trace-steps-panel');
    stepsPanel.append(el('div', 'trace-steps-title', '🔄 Quá trình suy luận, gọi công cụ & Đánh giá (ReAct Chain):'));
    const timeline = el('div', 'trace-steps-timeline');
    trace.steps.forEach(st => {
      const card = el('div', 'trace-step-card' + (st.backtrack ? ' is-backtrack' : ''));
      const header = el('div', 'trace-step-header');
      header.append(el('span', 'trace-step-badge', 'Bước ' + st.step));
      if (st.worker) {
        header.append(el('span', 'trace-step-worker', '[' + st.worker + ']'));
      }
      if (st.backtrack) {
        header.append(el('span', 'trace-step-backtrack-tag', '🔄 Tự điều chỉnh / Quay lui'));
      }
      card.append(header);

      if (st.thought) {
        const thoughtDiv = el('div', 'trace-step-thought');
        thoughtDiv.append(el('strong', '', '💭 Suy luận: '), el('span', '', st.thought));
        card.append(thoughtDiv);
      }

      if (Array.isArray(st.tools) && st.tools.length > 0) {
        const toolsDiv = el('div', 'trace-step-tools');
        st.tools.forEach(t => {
          const tItem = el('div', 'trace-tool-item ' + (t.status === 'error' ? 'tool-error' : 'tool-ok'));
          const tHeader = el('span', 'trace-tool-title', '🛠️ ' + t.name);
          if (t.args && Object.keys(t.args).length > 0) {
            tHeader.append(el('span', 'trace-tool-args', ' ' + JSON.stringify(t.args)));
          }
          tItem.append(tHeader);
          if (t.summary) {
            tItem.append(el('div', 'trace-tool-summary', '➜ ' + t.summary));
          }
          toolsDiv.append(tItem);
        });
        card.append(toolsDiv);
      } else if (st.action === 'final_answer') {
        card.append(el('div', 'trace-step-final', '✅ ' + (st.summary || 'Tổng hợp dữ kiện và hoàn tất câu trả lời.')));
      } else if (st.action === 'cancelled') {
        card.append(el('div', 'trace-step-final', '⏹️ ' + (st.summary || 'Đã dừng câu trả lời theo yêu cầu.')));
      }

      if (st.evaluation) {
        const evalDiv = el('div', 'trace-step-eval');
        evalDiv.append(el('strong', '', '📋 Đánh giá: '), el('span', '', st.evaluation));
        card.append(evalDiv);
      }

      timeline.append(card);
    });
    stepsPanel.append(timeline);
    details.append(stepsPanel);
  }

  if (trace.reasoning && (!trace.steps || !trace.steps.some(s => s.thought))) {
    const rawBox = el('div', 'trace-raw-reasoning');
    rawBox.append(el('strong', '', '💭 Độc thoại suy luận (CoT):'));
    rawBox.append(el('pre', 'trace-reasoning-pre', trace.reasoning));
    details.append(rawBox);
  }
  row.append(details);
}

// W3.2-D10: while a turn runs, the page asks what the agent has done so far and shows it in the status line.
const toolProgressLabels = {
  get_order: 'đơn hàng', list_orders: 'danh sách đơn', get_context: 'đơn đang trao đổi', get_product: 'sản phẩm',
  search_products: 'danh mục sản phẩm', check_inventory: 'tồn kho', track_shipment: 'vận chuyển',
  search_knowledge: 'chính sách cửa hàng', prepare_order_action: 'điều kiện yêu cầu', request_human_support: 'chuyển nhân viên',
  get_current_time: 'thời gian', get_runtime_info: 'thông tin model',
  get_case_transcript: 'hội thoại ca', list_case_orders: 'đơn hàng trong ca',
  get_case_order: 'chi tiết đơn trong ca', list_case_order_actions: 'yêu cầu đơn hàng của ca'
};
let progressTimer = null, progressToken = 0;

function progressStatus(state) {
  if (!state || !state.active) return null;
  const done = [];
  for (const tool of Array.isArray(state.tools) ? state.tools : []) {
    const label = toolProgressLabels[tool.name] || tool.name;
    if (typeof label === 'string' && !done.includes(label)) done.push(label);
  }
  if (!done.length) return {title: 'Model đang xử lý…', detail: 'Đang đọc hội thoại và lập kế hoạch'};
  return {title: 'Đã kiểm tra ' + done[done.length - 1] + '…',
    detail: 'Đã kiểm tra: ' + done.join(' → ') + ' · đang tổng hợp (bước ' + Math.max(1, Number(state.model_calls) || 1) + ')'};
}

async function pollTurnProgress() {
  const token = progressToken;
  if (!conversationId || !token) return;
  try {
    const status = progressStatus(await api('/api/conversations/' + conversationId + '/progress'));
    if (status && token === progressToken) setModelStatus(status.title, status.detail);
  } catch (error) {
    // The progress line is a courtesy; the answer does not depend on it.
  }
}

function startProgressPolling() {
  stopProgressPolling();
  progressToken += 1;
  if (typeof setInterval === 'function') progressTimer = setInterval(pollTurnProgress, 3000);
}

function stopProgressPolling() {
  progressToken += 1;  // a poll that is still in flight must not overwrite the final status
  if (progressTimer && typeof clearInterval === 'function') clearInterval(progressTimer);
  progressTimer = null;
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
    await toggleHumanMode();
    return;
  }

  stopBotTimerPolling();
  caseClosedNotifiedForId = null;
  clearResumeCaseButtons();

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
      setModelStatus('Đã gửi cho CSKH', 'Nhân viên CSKH sẽ phản hồi tại đây');
      if (byId('staff-desk-dialog')?.open) {
        loadStaffQueue(true);
        if (activeStaffTicket && activeStaffTicket.conversation_id === conversationId) {
          refreshStaffTranscript(conversationId, true);
        }
      }
    } catch (err) {
      console.error('Lỗi gửi tin nhắn cho chuyên viên:', err);
      const row = message('Không thể gửi tin nhắn đến chuyên viên: ' + (err.message || 'Lỗi mạng'), 'assistant', 'interface');
      if (err.debugInfo) showErrorDetails(row, err);
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
  activeChatTurn = { conversationId, requestId, stopping: false };
  syncChatSendStopButton();
  startProgressPolling();
  let result;
  try {
    const payload = {text, conversation_id: conversationId, request_id: requestId};
    if (attachment) payload.attachment = attachment;
    result = await api('/api/chat', payload);
  } catch (error) {
    const row = message(error.message || 'Mất kết nối trong lúc chờ model.', 'assistant', 'interface');
    showTrace(row, error.trace);
    showErrorDetails(row, error);
    const retryButton = el('button', 'order-action', 'Thử lại tin nhắn này');
    const originalConversation = conversationId;
    retryButton.onclick = () => act(async () => {
      if (conversationId !== originalConversation) return;
      retryButton.remove(); await send(text, requestId, true, attachment);
    });
    row.append(retryButton);
    setModelStatus('Chat chưa hoàn tất', 'Có thể thử lại hoặc dùng các nút thao tác');
    return;
  } finally {
    stopProgressPolling();
    activeChatTurn = null;
    syncChatSendStopButton();
    byId('messages').removeAttribute('aria-busy');
  }
  const row = message(result.message, 'assistant', result.source, result.trace?.model);
  if (result.case?.case_id) currentCaseId = result.case.case_id;
  if (result.cancelled) {
    showTrace(row, result.trace, result.replayed);
    setModelStatus('Đã dừng câu trả lời', 'Tin nhắn của bạn đã được lưu');
    renderSidebarConversations().catch(() => {});
    return;
  }
  if (result.shipment) showShipment(row, result.shipment);
  if (result.human_support) {
    currentHandoffId = result.human_support.handoff_id || null;
    showHumanSupport(row, result.human_support);
    if (result.human_support.notice_turn_id && !renderedStaffTurnIds.has(result.human_support.notice_turn_id)) {
      renderedStaffTurnIds.add(result.human_support.notice_turn_id);
      if (result.human_support.notice_message) {
        caseSystemNoticeMessage(result.human_support.notice_message, 'handoff_requested');
      }
    }
    setHumanMode(true, 'Chuyên viên CSKH');
  } else if (result.case?.has_active_timer && !isHumanMode) {
    startBotTimerPolling();
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
  if (result.action === 'choose_cancel_reason' || result.action === 'choose_order_action_reason') {
    await chooseReason(
      result.order.id,
      result.order_action?.action_type || (result.action === 'choose_cancel_reason' ? 'cancel' : 'return'),
      result.order_action?.exchange_kind || null,
      result.order_action?.target_variant_id || null
    );
  } else await refresh();
  renderSidebarConversations().catch(() => {});
}

async function loadConversation(cid) {
  if (!cid) return;
  try {
    byId('messages').setAttribute('aria-busy', 'true');
    setModelStatus('Đang nạp lịch sử…', 'Đang tải lại hội thoại');
    const data = await api('/api/conversations/' + cid + '/messages');
    if (!data || !data.conversation) {
      await newConversation();
      return;
    }
    
    conversationId = cid;
    if (data.conversation.provider_id) {
      providerId = data.conversation.provider_id;
    }
    currentCaseId = data.case?.case_id || null;
    currentHandoffId = data.active_handoff?.handoff_id || null;
    caseClosedNotifiedForId = null;
    clearResumeCaseButtons();
    stopBotTimerPolling();
    renderedStaffTurnIds.clear();
    setHumanMode(false);
    renderProvider();
    showContext({
      order_id: data.conversation.order_id || null,
      external_order_id: data.conversation.external_order_id || null,
      product_id: data.conversation.product_id || null
    });
    byId('messages').replaceChildren();

    const turns = data.turns || [];
    let hasHumanSupport = false;
    let lastClosedNoticeRow = null;

    if (turns.length === 0) {
      message('Phiên mới dùng ' + (selectedProvider()?.model || 'model đã chọn') +
        '. Gửi câu hỏi hoặc chọn đơn bên phải. Khi đổi nguồn, lịch sử bắt đầu lại; trạng thái đơn được giữ.', 'assistant', 'interface');
      if (data.case?.status === 'resolved') {
        const closedRow = caseSystemNoticeMessage('Ca hỗ trợ này đã đóng. Bấm Tiếp tục hoặc gửi tin nhắn mới để mở lại.', 'case_resolved');
        appendResumeCaseButton(closedRow, cid);
      }
      setModelStatus('Đã sẵn sàng', selectedProvider()?.label || 'Model đã chọn');
      return;
    }

    for (const t of turns) {
      renderedStaffTurnIds.add(t.id);
      let msgs = [];
      try { msgs = typeof t.messages === 'string' ? JSON.parse(t.messages) : t.messages; } catch (e) {}
      let res = {};
      try { res = typeof t.result === 'string' ? JSON.parse(t.result) : t.result; } catch (e) {}

      if (res.author === 'staff') {
        humanMessage(res.message || '', res.staff_name || 'Chuyên viên CSKH');
        hasHumanSupport = true;
      } else if (res.author === 'customer') {
        const userText = msgs[0]?.content || '';
        message(userText, 'user');
        hasHumanSupport = true;
      } else if (res.author === 'system_reminder') {
        message(res.message || '', 'assistant', 'case_timer');
      } else if (res.author === 'system_order_action') {
        message(res.message || '', 'assistant', 'store_data');
      } else if (res.author === 'system_case_notice' || String(t.request_id || '').startsWith('sys-notice-')) {
        const noticeRow = caseSystemNoticeMessage(res.message || msgs[0]?.content || '', res.milestone || '');
        if (res.milestone === 'case_resolved') {
          lastClosedNoticeRow = noticeRow;
        } else if (res.milestone && String(res.milestone).startsWith('case_')) {
          hasHumanSupport = true;
        }
      } else {
        // Standard AI turn
        let userMsg = null;
        if (Array.isArray(msgs)) {
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'user') {
              userMsg = msgs[i];
              break;
            }
          }
        }
        if (userMsg && userMsg.content) {
          message(userMsg.content, 'user', null, null, userMsg.attachment || null);
        }

        const asstContent = res.message || '';
        const row = message(asstContent, 'assistant', res.source || null, res.trace?.model || null);
        if (res.shipment) showShipment(row, res.shipment);
        if (res.human_support) {
          showHumanSupport(row, res.human_support);
          hasHumanSupport = true;
        }
        if (res.sources) showSources(row, res.sources);
        if (res.trace) showTrace(row, res.trace, true);
        if (res.source !== 'interface' && !res.cancelled) {
          showFeedbackBar(row, cid, t.id);
        }
      }
    }

    const feedbacks = data.feedbacks || [];
    const activeHandoff = data.active_handoff || feedbacks.find(f => f.feedback_type === 'human_handoff' && f.reason_code !== 'resolved');
    if (activeHandoff && data.case?.status !== 'resolved') {
      setHumanMode(true, 'Chuyên viên CSKH');
      startHumanModePolling();
    } else if (data.case?.status === 'resolved') {
      const targetRow = lastClosedNoticeRow || caseSystemNoticeMessage('Ca hỗ trợ đã đóng. Bấm Tiếp tục hoặc gửi tin nhắn mới để mở lại.', 'case_resolved');
      appendResumeCaseButton(targetRow, cid);
    } else if (data.case?.has_active_timer && !isHumanMode) {
      startBotTimerPolling();
    }

    setModelStatus('Đã khôi phục hội thoại', `${turns.length} lượt tin nhắn · Sẵn sàng`);
    renderSidebarConversations().catch(() => {});
  } catch (err) {
    console.error('Lỗi khi nạp lịch sử cuộc trò chuyện:', err);
    message('Không thể nạp lại cuộc trò chuyện cũ: ' + (err.message || 'Lỗi mạng'), 'assistant', 'interface');
    await newConversation();
  } finally {
    byId('messages').removeAttribute('aria-busy');
  }
}

async function renderSidebarConversations(convs = null) {
  const container = byId('sidebar-conversation-history');
  if (!container) return;
  try {
    if (!convs) {
      const data = await api('/api/conversations');
      convs = data?.conversations || [];
    }
    container.replaceChildren();
    if (!convs || !convs.length) {
      container.innerHTML = '<div class="sidebar-history-empty">Chưa có hội thoại nào</div>';
      return;
    }
    for (const c of convs.slice(0, 10)) {
      const item = el('button', 'sidebar-history-item' + (c.id === conversationId ? ' active' : ''));
      item.type = 'button';
      item.title = c.snippet || ('Cuộc trò chuyện ' + c.id.slice(0, 8));

      const icon = el('span', 'sidebar-history-icon', '💬');
      const title = el('span', 'sidebar-history-title', c.snippet || ('Hội thoại ' + c.id.slice(0, 6)));
      const badge = el('span', 'sidebar-history-badge', (c.turns_count || 0) + ' lượt');

      item.append(icon, title, badge);
      item.onclick = () => {
        if (c.id !== conversationId) {
          act(async () => {
            await loadConversation(c.id);
            await renderSidebarConversations();
          });
        }
      };
      container.append(item);
    }
  } catch (err) {
    console.warn('Lỗi hiển thị lịch sử ở sidebar:', err);
  }
}

async function openConversationHistoryDialog() {
  const dialog = byId('conversation-history-dialog');
  if (!dialog) return;
  const listEl = byId('conversation-history-list');
  if (listEl) {
    listEl.innerHTML = '<div class="history-empty-state">Đang tải danh sách cuộc trò chuyện…</div>';
  }
  dialog.showModal();

  try {
    const data = await api('/api/conversations');
    const convs = data.conversations || [];
    if (!listEl) return;
    listEl.replaceChildren();

    if (convs.length === 0) {
      listEl.innerHTML = '<div class="history-empty-state">Chưa có cuộc trò chuyện nào trước đây.<br>Hãy bắt đầu nhắn tin với trợ lý!</div>';
      return;
    }

    for (const c of convs) {
      const item = el('div', 'history-item' + (c.id === conversationId ? ' active' : ''));
      item.onclick = async () => {
        dialog.close();
        if (c.id !== conversationId) {
          await act(() => loadConversation(c.id));
        }
      };

      const top = el('div', 'history-item-top');
      const title = el('div', 'history-item-title', c.snippet || ('Cuộc trò chuyện ' + c.id.slice(0, 8)));
      if (c.id === conversationId) {
        title.title = 'Cuộc trò chuyện đang mở';
      }
      top.append(title);

      const meta = el('div', 'history-item-meta');
      const turnsBadge = el('span', 'history-pill', `💬 ${c.turns_count || 0} lượt`);
      meta.append(turnsBadge);

      if (c.has_human_handoff) {
        const humanBadge = el('span', 'history-pill human', '🎧 Có chuyên viên');
        meta.append(humanBadge);
      }

      if (c.last_activity) {
        const d = new Date(c.last_activity * 1000);
        const timeStr = d.toLocaleTimeString('vi-VN', {hour: '2-digit', minute: '2-digit'});
        const dateStr = d.toLocaleDateString('vi-VN', {day: '2-digit', month: '2-digit'});
        const timeSpan = el('span', '', `${timeStr} ${dateStr}`);
        meta.append(timeSpan);
      }

      item.append(top, meta);
      listEl.append(item);
    }
  } catch (err) {
    console.error('Lỗi lấy danh sách cuộc trò chuyện:', err);
    if (listEl) {
      listEl.innerHTML = '<div class="history-empty-state">Không thể tải danh sách. Vui lòng thử lại.</div>';
    }
  }
}

async function openSession() {
  const session = await api('/api/session');
  currentSessionRole = session.role || 'customer';
  orderScope = 'customer';
  currentSessionTenantId = session.tenant_id || null;
  currentSessionPrincipalId = session.principal_id || null;
  currentSessionName = (session.name || '').trim();
  const staffRepName = byId('staff-rep-name');
  if (staffRepName) staffRepName.textContent = staffLabel();
  document.body.dataset.role = currentSessionRole;
  syncManagerButtonsVisibility();
  clearAttachment();
  canCancel = Array.isArray(session.permissions) ? session.permissions.includes('orders:cancel') : true;
  byId('profile-name').textContent = session.name || 'Khách hàng';
  byId('profile-avatar').textContent = (session.name || 'KH').slice(0, 2).toUpperCase();
  const roleNames = {
    customer: 'Khách hàng',
    viewer: 'Chỉ xem dữ liệu mẫu',
    staff: 'Chuyên viên CSKH',
    manager: 'Quản lý cửa hàng',
    platform_admin: 'Quản trị nền tảng',
    admin: 'Quản trị viên'
  };
  byId('profile-role').textContent = roleNames[session.role] || (canCancel ? 'Khách hàng giả lập' : 'Chỉ xem dữ liệu mẫu');
  byId('greeting').textContent = 'XIN CHÀO, ' + (session.name || 'BẠN').toUpperCase();
  document.querySelectorAll('[data-prompt]').forEach(button => { button.hidden = false; });
  byId('message').placeholder = persistentAccount ? 'Hỏi về đơn hàng hoặc sản phẩm của bạn…' : 'Ví dụ: Kiểm tra đơn hàng gần nhất của tôi…';
  syncAdminGovernanceVisibility();
  
  // Unlock UI immediately upon verified identity
  byId('demo-token').value = '';
  lockPage(false);
  if (byId('confirm-dialog').open) byId('confirm-dialog').close();
  byId('messages').replaceChildren();

  loadReasonCatalog(true);  // request reasons come from the shared catalog (of this role); warm it while the page settles
  try {
    const choices = await api('/api/providers');
    providerOptions = choices.providers;
    providerId = choices.default_provider;
    renderProvider();
  } catch (e) {
    console.warn('Lỗi tải providers:', e);
  }

  try {
    await refresh();
  } catch (e) {
    console.warn('Lỗi tải dữ liệu đơn hàng:', e);
  }

  pending = null;
  conversationId = null;
  
  let resumed = false;
  let cachedConvs = [];
  try {
    const listRes = await api('/api/conversations');
    cachedConvs = listRes?.conversations || [];
    if (
      cachedConvs.length > 0
      && (cachedConvs[0].turns_count > 0 || cachedConvs[0].has_human_handoff || cachedConvs[0].has_case_notices)
    ) {
      await loadConversation(cachedConvs[0].id);
      resumed = true;
    }
  } catch (e) {
    console.warn('Không thể tự động khôi phục hội thoại gần nhất:', e);
  }
  if (!resumed) {
    try {
      await newConversation();
    } catch (e) {
      console.warn('Lỗi tạo hội thoại ban đầu:', e);
    }
  }
  renderSidebarConversations(cachedConvs).catch(() => {});
  await restoreProposals().catch(() => {});
  if (session.role === 'staff') {
    openStaffDesk();
  } else if (session.role === 'manager' || session.role === 'platform_admin') {
    openManagerConsole();
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
byId('new-conversation').onclick = () => act(async () => {
  await newConversation();
  await renderSidebarConversations();
});

const btnHistoryHeader = byId('btn-chat-history');
if (btnHistoryHeader) btnHistoryHeader.onclick = () => openConversationHistoryDialog();

const btnHistorySidebar = byId('btn-conversation-history');
if (btnHistorySidebar) btnHistorySidebar.onclick = () => openConversationHistoryDialog();

const btnHeaderNewConv = byId('btn-header-new-conv');
if (btnHeaderNewConv) btnHeaderNewConv.onclick = () => act(async () => {
  await newConversation();
  await renderSidebarConversations();
});

const closeHistoryDialog = byId('close-history-dialog');
if (closeHistoryDialog) closeHistoryDialog.onclick = () => byId('conversation-history-dialog').close();

const btnModalNewConv = byId('btn-modal-new-conv');
if (btnModalNewConv) btnModalNewConv.onclick = () => {
  byId('conversation-history-dialog').close();
  act(async () => {
    await newConversation();
    await renderSidebarConversations();
  });
};
byId('model-provider').onchange = () => {
  const requested = byId('model-provider').value;
  if (busy) { byId('model-provider').value = providerId; return; }
  act(async () => {
    try { await newConversation(requested); }
    finally { byId('model-provider').value = providerId; }
  });
};
const aboutButton = byId('about');
const aboutDialog = byId('about-dialog');
const closeAboutButton = byId('close-about');
if (aboutButton && aboutDialog) aboutButton.onclick = () => aboutDialog.showModal();
if (closeAboutButton && aboutDialog) closeAboutButton.onclick = () => aboutDialog.close();
byId('approve-confirm').onclick = () => act(confirm); byId('dismiss-confirm').onclick = () => act(dismiss);
byId('confirm-dialog').oncancel = event => { event.preventDefault(); act(dismiss); };
const error = el('p', 'proposal-error'); error.id = 'confirm-error'; error.setAttribute('role', 'alert');
byId('confirm-dialog').querySelector('.dialog-actions').before(error);
if (byId('order-tabs')) byId('order-tabs').hidden = true;
renderAttachmentPreview();
renderOrder();
if (cookieAuth) {
  byId('login-description').textContent = persistentAccount
    ? 'Nhập mã truy cập cá nhân do quản trị viên cấp. Phiên có hiệu lực 8 giờ. Đăng nhập lại để tiếp tục xem dữ liệu của tài khoản.'
    : 'Nhập mã mời từ chủ dự án. Mỗi khách có bộ đơn mẫu riêng. Phiên có hiệu lực 8 giờ. Đóng phiên sẽ kết thúc quyền truy cập bộ dữ liệu này.';
  byId('session-note').textContent = persistentAccount
    ? 'Dữ liệu thuộc tài khoản của bạn. Hết phiên hoặc đăng xuất vẫn giữ đơn hàng và nhật ký; đăng nhập lại để tiếp tục.'
    : 'Dữ liệu thuộc phiên demo riêng của bạn, có hiệu lực 8 giờ. Tải lại trang giữ trạng thái; đóng phiên rồi đăng nhập tạo bộ đơn mới.';
  const loginButton = byId('login-form').querySelector('button'); loginButton.disabled = true;
  openSession().catch(error => { lockPage(true); if (error.message && !/mã mời|phiên demo/i.test(error.message)) byId('login-error').textContent = error.message; })
    .finally(() => { loginButton.disabled = false; });
}

const googleAuthConfigured = document.body?.dataset?.googleAuth === 'true';
const googleContainer = byId('google-login-container');
if (googleContainer) {
  googleContainer.hidden = !googleAuthConfigured;
  if (googleContainer.style) googleContainer.style.display = googleAuthConfigured ? '' : 'none';
}
if (googleAuthConfigured) {
  const desc = byId('login-description');
  if (desc) desc.textContent = 'Đăng nhập nhanh bằng tài khoản Google hoặc sử dụng mã truy cập cá nhân.';
}

// Interactive Tool Inspector Harness (W5-D4: Manager-only, read-only, case-bound)
const inspectorDialog = byId('inspector-dialog');
const toggleInspectorBtn = byId('toggle-inspector');
const closeInspectorBtn = byId('close-inspector');
const inspectorCaseSelect = byId('inspector-case-select');
const toolSelect = byId('inspector-tool-select');
const argsInput = byId('inspector-args-input');
const runInspectorBtn = byId('inspector-run-btn');
const inspectorOutput = byId('inspector-output');
const inspectorLatency = byId('inspector-latency-badge');

const INSPECTOR_TOOL_SPECS = [
  { value: 'get_order', label: 'get_order (Đọc trạng thái đơn hàng)' },
  { value: 'list_orders', label: 'list_orders (Danh sách đơn của khách)' },
  { value: 'track_shipment', label: 'track_shipment (Hành trình bưu cục GHTK/GHN)' },
  { value: 'check_inventory', label: 'check_inventory (Kiểm tra tồn kho theo size/màu)' },
  { value: 'search_knowledge', label: 'search_knowledge (Tìm kiếm kho chính sách)' },
  { value: 'get_context', label: 'get_context (Ngữ cảnh đơn/sản phẩm của hội thoại)' }
];
const inspectorCasesById = new Map();
const inspectorCaseSampleById = new Map();

function ensureInspectorToolOptions() {
  if (!toolSelect) return;
  const currentVal = toolSelect.value;
  toolSelect.replaceChildren();
  for (const spec of INSPECTOR_TOOL_SPECS) {
    const opt = el('option', '', spec.label);
    opt.value = spec.value;
    toolSelect.append(opt);
  }
  toolSelect.value = INSPECTOR_TOOL_SPECS.some(s => s.value === currentVal) ? currentVal : 'get_order';
}

function parseInspectorVariantSample(variantStr) {
  const raw = String(variantStr || '').trim();
  if (!raw) return { color: '', size: '' };
  let size = '';
  let color = '';
  const sizeMatch = raw.match(/(?:size\s*)?([XSML]{1,3}|\d{2})\b/i);
  if (sizeMatch) {
    size = sizeMatch[1].toUpperCase();
  }
  const parts = raw.split(/[·/,-]/).map(s => s.trim()).filter(Boolean);
  for (const part of parts) {
    if (!/^size\b/i.test(part) && part.toUpperCase() !== size) {
      color = part;
      break;
    }
  }
  return { color, size };
}

function buildInspectorSampleArgs(toolName, sample) {
  const s = sample || {};
  if (toolName === 'get_order' || toolName === 'track_shipment') {
    return s.orderId ? JSON.stringify({ order_id: s.orderId }, null, 2) : '{}';
  }
  if (toolName === 'check_inventory') {
    if (!s.productId) return '{}';
    const obj = {
      product_id: s.productId,
      size: s.size || 'Freesize',
      color: s.color || 'Mặc định'
    };
    return JSON.stringify(obj, null, 2);
  }
  if (toolName === 'search_knowledge') {
    return JSON.stringify({ query: 'Chính sách đổi trả hàng' }, null, 2);
  }
  return '{}';
}

function syncInspectorArgsForCurrentSelection() {
  if (!argsInput || !toolSelect) return;
  const caseId = (inspectorCaseSelect?.value || '').trim();
  const sample = caseId ? inspectorCaseSampleById.get(caseId) : null;
  argsInput.value = buildInspectorSampleArgs(toolSelect.value, sample);
  if (runInspectorBtn) {
    runInspectorBtn.disabled = !caseId || currentSessionRole !== 'manager';
  }
}

async function selectInspectorCase(caseId) {
  const cleanId = String(caseId || '').trim();
  if (inspectorCaseSelect && inspectorCaseSelect.value !== cleanId) {
    inspectorCaseSelect.value = cleanId;
  }
  if (!cleanId) {
    syncInspectorArgsForCurrentSelection();
    return;
  }
  const caseItem = inspectorCasesById.get(cleanId) || null;
  let sample = {
    orderId: caseItem?.order_id || '',
    productId: '',
    color: '',
    size: ''
  };
  try {
    const ordersRes = await api('/api/staff/cases/' + encodeURIComponent(cleanId) + '/orders');
    const caseOrders = Array.isArray(ordersRes?.orders) ? ordersRes.orders : [];
    const primaryOrder = (sample.orderId && caseOrders.find(o => o.id === sample.orderId)) || caseOrders[0] || null;
    if (primaryOrder) {
      const parsedVar = parseInspectorVariantSample(primaryOrder.variant);
      sample = {
        orderId: primaryOrder.external_order_id || primaryOrder.id || sample.orderId,
        productId: primaryOrder.product_id || '',
        color: parsedVar.color,
        size: parsedVar.size
      };
    }
  } catch (err) {
    // Keep case header fallback if orders endpoint fails.
  }
  inspectorCaseSampleById.set(cleanId, sample);
  syncInspectorArgsForCurrentSelection();
}

async function openToolInspector() {
  if (currentSessionRole !== 'manager' || !inspectorDialog) return;
  ensureInspectorToolOptions();
  inspectorCasesById.clear();
  if (inspectorCaseSelect) {
    inspectorCaseSelect.replaceChildren();
    const emptyOpt = el('option', '', '— Chọn một ca hỗ trợ —');
    emptyOpt.value = '';
    inspectorCaseSelect.append(emptyOpt);
  }
  if (runInspectorBtn) runInspectorBtn.disabled = true;
  inspectorDialog.showModal();
  try {
    const res = await api('/api/staff/cases');
    const allCases = [
      ...(res?.in_progress || []),
      ...(res?.waiting || []),
      ...(res?.resolved || [])
    ];
    for (const c of allCases) {
      if (!c || !c.case_id || inspectorCasesById.has(c.case_id)) continue;
      inspectorCasesById.set(c.case_id, c);
      if (inspectorCaseSelect) {
        const statusTag = c.status === 'resolved' ? 'Đã đóng' : (c.holder ? 'Đang xử lý' : 'Hàng chờ');
        const dualOid = c.order_id ? ' (' + formatDualOrderId(c.order_id, c.external_order_id) + ')' : '';
        const label = `${c.case_id} · ${c.customer_name || c.customer_id || 'Khách'}${dualOid} [${statusTag}]`;
        const opt = el('option', '', label);
        opt.value = c.case_id;
        inspectorCaseSelect.append(opt);
      }
    }
    const preferred = (activeStaffTicket?.case_id && inspectorCasesById.has(activeStaffTicket.case_id))
      ? activeStaffTicket.case_id
      : (allCases[0]?.case_id || '');
    await selectInspectorCase(preferred);
  } catch (err) {
    if (inspectorOutput) {
      inspectorOutput.textContent = 'Không thể tải danh sách ca hỗ trợ: ' + (err.message || 'Lỗi máy chủ');
    }
  }
}

ensureInspectorToolOptions();

if (toggleInspectorBtn && inspectorDialog) {
  toggleInspectorBtn.onclick = () => openToolInspector();
}
if (closeInspectorBtn && inspectorDialog) {
  closeInspectorBtn.onclick = () => inspectorDialog.close();
}
if (inspectorCaseSelect) {
  inspectorCaseSelect.onchange = () => selectInspectorCase(inspectorCaseSelect.value);
}
if (toolSelect && argsInput) {
  toolSelect.onchange = () => syncInspectorArgsForCurrentSelection();
}
if (runInspectorBtn && inspectorOutput) {
  runInspectorBtn.onclick = async () => {
    if (currentSessionRole !== 'manager') {
      inspectorOutput.textContent = 'Error: Chỉ Quản lý cửa hàng mới được phép chạy Tool Inspector.';
      return;
    }
    const selectedCaseId = (inspectorCaseSelect?.value || '').trim();
    if (!selectedCaseId) {
      inspectorOutput.textContent = 'Error: Vui lòng chọn một ca hỗ trợ trước khi chạy công cụ.';
      return;
    }
    try {
      const tool_name = toolSelect.value;
      const arguments_obj = JSON.parse(argsInput.value.trim() || '{}');
      const caseEntry = inspectorCasesById.get(selectedCaseId) || null;
      const execPayload = {
        case_id: selectedCaseId,
        tool_name,
        arguments: arguments_obj
      };
      if (caseEntry?.conversation_id) {
        execPayload.conversation_id = caseEntry.conversation_id;
      }
      inspectorOutput.textContent = 'Đang thực thi công cụ [' + tool_name + '] trong phạm vi ca ' + selectedCaseId + '...';
      inspectorLatency.textContent = '';
      const t0 = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
      const res = await api('/api/tools/execute', execPayload);
      const t1 = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
      const ms = (t1 - t0).toFixed(1);
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
if (btnMeetHuman) btnMeetHuman.onclick = () => act(() => toggleHumanMode());

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
const STAFF_CASE_OPS_COLLAPSED_KEY = 'retailops.staff.caseOpsCollapsed';
const STAFF_DESK_MAXIMIZED_KEY = 'retailops.staff.deskMaximized';
const STAFF_DESK_POLL_MS = 5000;
const STAFF_OA_STATUS_VI = {
  requested: 'Chờ tiếp nhận',
  under_review: 'Đang xem xét',
  approved: 'Đã duyệt',
  rejected: 'Đã từ chối',
  received: 'Đã nhận hàng',
  inspected: 'Đã kiểm tra',
  completed: 'Hoàn tất'
};
const STAFF_OA_OUTCOME_VI = {
  refund: 'Hoàn tiền',
  exchange: 'Đổi hàng',
  no_action: 'Không xử lý'
};
const STAFF_OA_ROLE_VI = {
  customer: 'Khách hàng',
  staff: 'Nhân viên',
  manager: 'Quản lý',
  system: 'Hệ thống'
};
const STAFF_OA_DECISION_VI = {
  submit: 'Gửi yêu cầu',
  start_review: 'Nhận ca xem xét',
  claim_review: 'Nhận ca xem xét',
  approve: 'Duyệt yêu cầu',
  reject: 'Từ chối yêu cầu',
  mark_received: 'Đã nhận hàng gửi về',
  mark_inspected: 'Đã kiểm tra hàng',
  complete: 'Hoàn tất xử lý',
  refund_request: 'Gửi yêu cầu hoàn tiền',
  refund_approve: 'Duyệt hoàn tiền',
  refund_reject: 'Từ chối hoàn tiền',
  refund_outcome: 'Ghi nhận kết quả hoàn tiền',
  refund_provider_update: 'Cổng thanh toán cập nhật hoàn tiền'
};

let activeStaffTicket = null;
let staffDeskTimer = null;
let staffReplySending = false;
let staffQueueBucket = 'waiting';
let staffDeskData = { waiting: [], in_progress: [], resolved: [], open_count: 0 };
let staffCaseOpsCollapsed = false;
let staffDeskMaximized = false;
let staffCaseOrderActions = [];
let staffCaseCompensations = [];
let staffCaseUnlinkedRefunds = [];
let staffCaseCustomerOrders = [];
let staffCaseOrders = [];
let staffCaseConsentTurns = [];
let staffCaseOrderReasonsMap = null;
let staffCaseOrderActionsReadOnly = false;
let staffCaseOpenRequestSig = '';
let staffOrderActionBusy = false;
let staffRevealedRecipients = {};
let managerCompensations = [];
let managerCompensationsCounts = {
  proposed: 0,
  approved: 0,
  requested: 0,
  issued: 0,
  rejected: 0,
  failed: 0,
  all: 0
};
const compensationStatusLabels = {
  proposed: 'Chờ duyệt',
  approved: 'Đã duyệt',
  requested: 'Đang chờ sàn phát mã',
  issued: 'Đã phát voucher',
  rejected: 'Đã từ chối',
  failed: 'Phát thất bại'
};
let staffConsentDraft = {
  caseId: null,
  orderId: '',
  typeKey: '',
  reasonCode: '',
  noteText: '',
  consentTurnId: '',
  turnManuallyChanged: false,
  otherOpsOpen: false,
  dfOrderId: '',
  dfAttempts: '1',
  dfNote: '',
  revealOrderId: '',
  revealReason: ''
};

function resetStaffConsentDraft(caseId = null) {
  staffRevealedRecipients = {};
  staffConsentDraft = {
    caseId: caseId || null,
    orderId: '',
    typeKey: '',
    reasonCode: '',
    noteText: '',
    consentTurnId: '',
    turnManuallyChanged: false,
    otherOpsOpen: false,
    targetVariantId: '',
    variantOptions: {},
    dfOrderId: '',
    dfAttempts: '1',
    dfNote: '',
    revealOrderId: '',
    revealReason: ''
  };
}

function getConsentTypeChoicesForOrder(ord) {
  if (!ord) return [];
  const allowed = Array.isArray(ord.allowed_action_types)
    ? ord.allowed_action_types
    : (ord.status === 'pending' ? ['cancel'] : (ord.status === 'delivered' ? ['return', 'exchange'] : []));
  const choices = [];
  if (allowed.includes('cancel')) choices.push({ value: 'cancel', label: 'Hủy đơn' });
  if (allowed.includes('return')) choices.push({ value: 'return', label: 'Trả hàng' });
  if (allowed.includes('exchange')) {
    choices.push({ value: 'exchange:other_variant', label: exchangeKindLabels.other_variant });
    choices.push({ value: 'exchange:same_variant', label: exchangeKindLabels.same_variant });
  }
  return choices;
}

function getConsentReasonsForTypeKey(typeKey) {
  const raw = String(typeKey || '');
  const baseType = raw.startsWith('exchange:') ? 'exchange' : raw;
  const fromCatalog = reasonsForType(baseType, true).map(entry => [entry.code, entry.label]);
  const src = fromCatalog.length ? fromCatalog : Object.entries((staffCaseOrderReasonsMap && staffCaseOrderReasonsMap[baseType]) || {});
  return src.filter(([code]) => code !== 'delivery_failed');
}

function formatConsentTurnOptionLabel(turn) {
  if (!turn) return '';
  const ts = Number(turn.created_at);
  const timeStr = (Number.isFinite(ts) && ts > 0)
    ? new Date(ts * 1000).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    : '--:--';
  const excerpt = String(turn.excerpt || '').trim();
  return `[${timeStr}] "${excerpt}"`;
}

function makeStaffIdempotencyKey(prefix = 'staff-oa-') {
  const rand = (typeof crypto !== 'undefined' && crypto && typeof crypto.randomUUID === 'function')
    ? crypto.randomUUID()
    : (Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12));
  return prefix + rand;
}

function readStaffCaseOpsSavedCollapsed() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage && typeof localStorage.getItem === 'function') {
      return localStorage.getItem(STAFF_CASE_OPS_COLLAPSED_KEY) === '1';
    }
  } catch (e) {}
  return false;
}

function writeStaffCaseOpsSavedCollapsed(collapsed) {
  try {
    if (typeof localStorage !== 'undefined' && localStorage && typeof localStorage.setItem === 'function') {
      localStorage.setItem(STAFF_CASE_OPS_COLLAPSED_KEY, collapsed ? '1' : '0');
    }
  } catch (e) {}
}

function applyStaffCaseOpsCollapseState(collapsed) {
  staffCaseOpsCollapsed = Boolean(collapsed);
  const modEl = byId('staff-case-ops-module');
  const bodyEl = byId('staff-case-ops-body');
  const toggleBtn = byId('btn-toggle-staff-case-ops');
  if (modEl) modEl.classList?.toggle?.('is-collapsed', staffCaseOpsCollapsed);
  if (bodyEl) {
    bodyEl.hidden = staffCaseOpsCollapsed;
    if (bodyEl.style) bodyEl.style.display = staffCaseOpsCollapsed ? 'none' : 'flex';
  }
  if (toggleBtn) {
    toggleBtn.setAttribute('aria-expanded', staffCaseOpsCollapsed ? 'false' : 'true');
    toggleBtn.textContent = staffCaseOpsCollapsed ? 'Mở rộng ▼' : 'Thu gọn ▲';
  }
}

function toggleStaffCaseOps() {
  const next = !staffCaseOpsCollapsed;
  writeStaffCaseOpsSavedCollapsed(next);
  applyStaffCaseOpsCollapseState(next);
}

function readStaffDeskSavedMaximized() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage && typeof localStorage.getItem === 'function') {
      return localStorage.getItem(STAFF_DESK_MAXIMIZED_KEY) === '1';
    }
  } catch (e) {}
  return false;
}

function writeStaffDeskSavedMaximized(maximized) {
  try {
    if (typeof localStorage !== 'undefined' && localStorage && typeof localStorage.setItem === 'function') {
      localStorage.setItem(STAFF_DESK_MAXIMIZED_KEY, maximized ? '1' : '0');
    }
  } catch (e) {}
}

function applyStaffDeskMaximizedState(maximized) {
  staffDeskMaximized = Boolean(maximized);
  const dlg = byId('staff-desk-dialog');
  const btn = byId('btn-maximize-staff-desk');
  if (dlg) dlg.classList?.toggle?.('is-maximized', staffDeskMaximized);
  if (btn) {
    btn.setAttribute('aria-pressed', staffDeskMaximized ? 'true' : 'false');
    btn.textContent = staffDeskMaximized ? '🗗 Thu nhỏ' : '⛶ Phóng to';
  }
}

function toggleStaffDeskMaximized() {
  const next = !staffDeskMaximized;
  writeStaffDeskSavedMaximized(next);
  applyStaffDeskMaximizedState(next);
}

function isOrderActionOpen(req) {
  if (!req) return false;
  if (req.refund_status === 'pending') return true;
  if (req.closed_at != null) return false;
  if (req.status === 'rejected' || req.status === 'completed') return false;
  if (req.type === 'cancel' && req.status === 'approved') return false;
  return true;
}

function setStaffDeskNotice(msg, kind = 'error') {
  const noticeEl = byId('staff-desk-notice');
  if (!noticeEl) {
    if (msg) console.warn(msg);
    return;
  }
  const text = (msg || '').trim();
  if (!text) {
    noticeEl.textContent = '';
    noticeEl.hidden = true;
    if (noticeEl.style) noticeEl.style.display = 'none';
    noticeEl.classList?.remove?.('is-error', 'is-success');
    return;
  }
  noticeEl.textContent = text;
  noticeEl.hidden = false;
  if (noticeEl.style) noticeEl.style.display = 'block';
  noticeEl.classList?.toggle?.('is-error', kind === 'error');
  noticeEl.classList?.toggle?.('is-success', kind === 'success');
}

function notifyStaffAlert(msg, kind = 'error') {
  setStaffDeskNotice(msg, kind);
}

function openStaffDesk() {
  const dlg = byId('staff-desk-dialog');
  loadReasonCatalog();  // staff see the same catalog as customers (plus the staff-only reasons)
  if (dlg) {
    setStaffDeskNotice('', '');
    applyStaffDeskMaximizedState(readStaffDeskSavedMaximized());
    applyStaffCaseOpsCollapseState(readStaffCaseOpsSavedCollapsed());
    if (!activeStaffTicket) {
      syncStaffTicketActions(null, true);
    }
    dlg.showModal();
    startStaffDeskPolling();
    return loadStaffQueue();
  }
  return Promise.resolve();
}

function closeStaffDeskDialog() {
  const dlg = byId('staff-desk-dialog');
  if (dlg && dlg.open) dlg.close();
  stopStaffDeskPolling();
}

function startStaffDeskPolling() {
  if (staffDeskTimer || typeof setInterval !== 'function') return;
  staffDeskTimer = setInterval(pollStaffDesk, STAFF_DESK_POLL_MS);
}

function stopStaffDeskPolling() {
  if (staffDeskTimer) {
    if (typeof clearInterval === 'function') clearInterval(staffDeskTimer);
    staffDeskTimer = null;
  }
  stopStaffCaseAssistProgressPolling();
}

async function pollStaffDesk() {
  const dlg = byId('staff-desk-dialog');
  if (!dlg || !dlg.open) {
    stopStaffDeskPolling();
    return;
  }
  if (activeStaffTicket && activeStaffTicket.status !== 'resolved') {
    await refreshStaffTranscript(activeStaffTicket.conversation_id, false, activeStaffTicket.case_id);
    if (activeStaffTicket.case_id) {
      await loadStaffCaseOrderActions(activeStaffTicket.case_id, false);
    }
  }
  await loadStaffQueue(true);
}

function setStaffQueueBucket(bucket) {
  if (!['waiting', 'in_progress', 'resolved'].includes(bucket)) return;
  staffQueueBucket = bucket;
  renderStaffBucketList();
}

function formatCustomerSilentLabel(caseOrItem) {
  if (!caseOrItem || caseOrItem.status !== 'in_progress' || !caseOrItem.holder) return '';
  const secs = caseOrItem.customer_silent_seconds;
  if (typeof secs !== 'number' || !Number.isFinite(secs) || secs <= 0) return '';
  const mins = Math.max(1, Math.floor(secs / 60));
  return `Khách không phản hồi · ${mins} phút`;
}

function syncStaffHeaderSilentBadge(caseObj, isClosed = false) {
  const silentEl = byId('staff-active-silent-badge');
  if (!silentEl) return;
  const label = (!isClosed && caseObj) ? formatCustomerSilentLabel(caseObj) : '';
  silentEl.hidden = !label;
  silentEl.textContent = label;
}

function renderStaffBucketList() {
  const listEl = byId('staff-queue-list');
  const countEl = byId('staff-queue-count');
  if (countEl) countEl.textContent = String(staffDeskData.open_count ?? 0);

  const btnW = byId('staff-bucket-waiting');
  const btnP = byId('staff-bucket-in-progress');
  const btnR = byId('staff-bucket-resolved');
  if (btnW) {
    btnW.textContent = `Hàng chờ (${(staffDeskData.waiting || []).length})`;
    btnW.classList?.toggle?.('active', staffQueueBucket === 'waiting');
  }
  if (btnP) {
    btnP.textContent = `Đang xử lý (${(staffDeskData.in_progress || []).length})`;
    btnP.classList?.toggle?.('active', staffQueueBucket === 'in_progress');
  }
  if (btnR) {
    btnR.textContent = `Đã xử lý (${(staffDeskData.resolved || []).length})`;
    btnR.classList?.toggle?.('active', staffQueueBucket === 'resolved');
  }

  if (!listEl) return;
  const items = staffDeskData[staffQueueBucket] || [];
  if (!items.length) {
    const emptyMsg = staffQueueBucket === 'waiting'
      ? 'Không có ca nào trong hàng chờ.'
      : (staffQueueBucket === 'in_progress'
        ? 'Không có ca nào đang được giữ xử lý.'
        : 'Chưa có ca đã xử lý trong thời hạn lưu.');
    listEl.replaceChildren(el('p', 'staff-empty-hint', emptyMsg));
    return;
  }

  listEl.replaceChildren();
  items.forEach(item => {
    const itemKey = item.case_id || item.id;
    const activeKey = activeStaffTicket ? (activeStaffTicket.case_id || activeStaffTicket.id) : null;
    const isResolved = item.status === 'resolved' || item.reason_code === 'resolved';
    const isInProgress = item.status === 'in_progress' || Boolean(item.holder);
    const badgeLabel = isResolved
      ? '✓ Đã xử lý'
      : (isInProgress ? ('🟡 Đang giữ' + (item.holder_name ? ': ' + item.holder_name : '')) : '🔴 Hàng chờ');
    const card = el('div', 'ticket-card' + (activeKey && activeKey === itemKey ? ' active' : ''));
    const header = el('div', 'ticket-header');
    const ticketOrderLabel = item.order_id ? (' (' + formatDualOrderId(item.order_id, item.external_order_id) + ')') : '';
    header.append(
      el('span', 'ticket-user', (item.customer_name || item.customer_id) + ticketOrderLabel),
      el('span', 'ticket-badge ' + (isResolved ? 'resolved' : 'pending'), badgeLabel)
    );
    const silentLabel = formatCustomerSilentLabel(item);
    const reason = el('p', 'ticket-reason', item.comment || item.reason_code || (isResolved ? ('Lý do đóng: ' + (item.resolved_reason || 'resolved')) : 'Yêu cầu hỗ trợ từ khách hàng'));
    const ts = item.updated_at || item.created_at || (Date.now() / 1000);
    const timeStr = new Date(ts * 1000).toLocaleTimeString('vi-VN', {hour: '2-digit', minute:'2-digit'});
    const meta = el('div', 'ticket-meta');
    meta.append(el('span', '', 'Mã ca: ' + (item.case_id || ('#' + item.id))), el('span', '', timeStr));
    card.append(header);
    if (silentLabel) {
      card.append(el('div', 'ticket-silent-badge', silentLabel));
    }
    card.append(reason, meta);
    card.onclick = () => selectStaffTicket(item);
    listEl.append(card);
  });
}

async function loadStaffQueue(silent = false) {
  const listEl = byId('staff-queue-list');
  if (!listEl) return;
  if (!silent) {
    listEl.innerHTML = '<p class="staff-empty-hint">Đang tải danh sách ca chờ...</p>';
  }
  try {
    const res = await api('/api/staff/cases');
    staffDeskData = {
      waiting: res.waiting || [],
      in_progress: res.in_progress || [],
      resolved: res.resolved || [],
      open_count: typeof res.open_count === 'number'
        ? res.open_count
        : ((res.waiting || []).length + (res.in_progress || []).length)
    };
    if (activeStaffTicket?.case_id) {
      const allItems = [
        ...(staffDeskData.waiting || []),
        ...(staffDeskData.in_progress || []),
        ...(staffDeskData.resolved || [])
      ];
      const matched = allItems.find(it => it.case_id === activeStaffTicket.case_id);
      if (matched) {
        activeStaffTicket.customer_silent_seconds = matched.customer_silent_seconds ?? null;
        syncStaffHeaderSilentBadge(activeStaffTicket, matched.status === 'resolved');
      }
    }
    renderStaffBucketList();
    if (currentSessionRole === 'manager') {
      loadManagerCompensations(true).catch(() => {});
    } else {
      const mgrPanel = byId('staff-manager-compensations-panel');
      if (mgrPanel) {
        mgrPanel.hidden = true;
        mgrPanel.replaceChildren();
      }
    }
  } catch (err) {
    if (!silent) {
      listEl.innerHTML = '<p class="staff-empty-hint is-error">Lỗi tải hàng đợi: ' + err.message + '</p>';
    }
  }
}

function formatStaffOrderActionType(req) {
  const isDeliveryFailure = Boolean(
    req.delivery_failure_attempts != null
    || req.reason_code === 'delivery_failed'
    || ['staff', 'manager'].includes(req.raised_by_role)
  );
  if (req.type === 'cancel') {
    return isDeliveryFailure
      ? ('Hủy đơn · Giao thất bại' + (req.delivery_failure_attempts ? ` (${req.delivery_failure_attempts} lần)` : ''))
      : 'Hủy đơn';
  }
  if (req.type === 'return') return 'Trả hàng';
  if (req.type === 'exchange') {
    if (exchangeKindLabels[req.exchange_kind]) return 'Đổi hàng (' + exchangeKindLabels[req.exchange_kind] + ')';
    return 'Đổi hàng';
  }
  return req.type || 'Yêu cầu đơn hàng';
}

function formatStaffRefundStatus(req) {
  if (!req) return '';
  if (req.refund_status === 'pending' && !req.refund_decision) return 'Hoàn tiền: Chờ Quản lý duyệt';
  if (req.refund_status === 'pending' && req.refund_decision === 'approved') {
    return req.refund_managed_by_provider
      ? 'Hoàn tiền: Đã duyệt · Chờ cổng thanh toán'
      : 'Hoàn tiền: Đã duyệt · Chờ ghi kết quả';
  }
  if (req.refund_status === 'refunded') return 'Hoàn tiền: Đã hoàn tiền';
  if (req.refund_status === 'failed') return 'Hoàn tiền: Hoàn tiền thất bại';
  if (req.refund_status === 'not_applicable' && req.refund_decision === 'rejected') return 'Hoàn tiền: Đã từ chối';
  return '';
}

function renderStaffCaseOrderActions() {
  const panelEl = byId('staff-order-actions-panel');
  const summaryEl = byId('staff-case-ops-summary');
  const openCount = staffCaseOrderActions.filter(isOrderActionOpen).length;
  if (summaryEl) {
    if (!activeStaffTicket) {
      summaryEl.textContent = 'Chưa chọn ca hỗ trợ';
    } else if (!staffCaseOrderActions.length) {
      summaryEl.textContent = staffCaseUnlinkedRefunds.length
        ? `Cảnh báo ${staffCaseUnlinkedRefunds.length} hoàn tiền chưa nối yêu cầu`
        : 'Chưa có yêu cầu đơn hàng';
    } else if (openCount > 0) {
      summaryEl.textContent = `${openCount} yêu cầu đang mở / tổng ${staffCaseOrderActions.length}`;
    } else {
      summaryEl.textContent = `${staffCaseOrderActions.length} yêu cầu (đã đóng)`;
    }
  }
  if (!panelEl) return;
  panelEl.replaceChildren();
  if (!activeStaffTicket) return;

  const caseObj = activeStaffTicket;
  const isClosed = Boolean(staffCaseOrderActionsReadOnly || caseObj.status === 'resolved');
  const isManager = currentSessionRole === 'manager';
  const isHolder = Boolean(
    !isClosed
    && caseObj.status === 'in_progress'
    && caseObj.holder
    && currentSessionPrincipalId
    && caseObj.holder === currentSessionPrincipalId
  );
  const canReview = Boolean(!isClosed && (isManager || isHolder));

  if (staffCaseUnlinkedRefunds.length > 0) {
    const warnBox = el('div', 'case-ops-unlinked-refund-warning');
    warnBox.dataset.role = 'unlinked-refund-warning';
    warnBox.append(el('strong', '', `⚠ Cảnh báo hoàn tiền chưa nối yêu cầu (${staffCaseUnlinkedRefunds.length}):`));
    staffCaseUnlinkedRefunds.forEach(item => {
      const lbl = item.warning
        || `Đơn ${formatDualOrderId(item.order_id, item.external_order_id)} · ${item.provider_refund_ref || ''} · ${money(item.amount || 0)} (${item.status || ''})`;
      warnBox.append(el('div', 'case-ops-unlinked-refund-item', lbl));
    });
    panelEl.append(warnBox);
  }

  if (!staffCaseOrderActions.length) {
    panelEl.append(
      el('p', 'case-ops-empty-hint', 'Ca hỗ trợ này chưa có yêu cầu hủy/trả/đổi đơn hàng.')
    );
  }

  staffCaseOrderActions.forEach(req => {
    const card = el('div', 'case-ops-request-card');
    card.dataset.requestId = req.request_id || '';
    card.dataset.status = req.status || '';

    const topRow = el('div', 'case-ops-req-top');
    const ord = req.order || {};
    const ordName = ord.display_name || ord.name || '';
    const ordLabel = formatDualOrderId(req.order_id || ord.id, req.external_order_id || ord.external_order_id);
    const ordParts = [`Đơn ${ordLabel}`];
    if (ordName) ordParts.push(ordName + (ord.variant ? ` (${ord.variant})` : ''));
    if (ord.amount != null) ordParts.push(money(ord.amount));
    if (ord.status) ordParts.push(`[${statuses[ord.status] || ord.status}]`);
    topRow.append(el('strong', '', ordParts.join(' · ')));

    const badges = el('div', 'case-ops-req-badges');
    badges.append(el('span', 'case-ops-pill', formatStaffOrderActionType(req)));
    const statusCls = req.status === 'rejected'
      ? ' is-rejected'
      : (['approved', 'completed'].includes(req.status) ? ' is-approved' : ' is-open');
    const statusText = (STAFF_OA_STATUS_VI[req.status] || req.status)
      + (req.inspection_outcome ? ` · KQ: ${STAFF_OA_OUTCOME_VI[req.inspection_outcome] || req.inspection_outcome}` : '');
    badges.append(el('span', 'case-ops-pill' + statusCls, statusText));
    const refundLabel = formatStaffRefundStatus(req);
    if (refundLabel) {
      badges.append(el('span', 'case-ops-pill is-refund', refundLabel));
    }
    topRow.append(badges);
    card.append(topRow);

    const metaRow = el('div', 'case-ops-meta-row');
    const reasonText = req.reason_label || reasonLabel(req.reason_code);
    const extraReason = (req.reason_text && req.reason_text !== reasonText) ? ` — "${req.reason_text}"` : '';
    metaRow.append(el('span', '', `Lý do: ${reasonText}${extraReason}`));
    if (req.type === 'exchange') {
      // Current variant -> wanted variant with its stock, for the person who approves (stock informs, never blocks).
      const variantLine = req.exchange_kind === 'other_variant'
        ? `Biến thể: ${req.current_variant_label || '—'} → ${req.target_variant_label || '(chưa chọn biến thể đích)'}`
          + ` · Tồn kho đích: ${variantStockText({stock: req.target_stock, stock_status: req.target_stock_status})}`
        : `Biến thể: ${req.current_variant_label || '—'} (đổi cùng biến thể)`;
      metaRow.append(el('span', 'case-ops-variant-line', variantLine));
    }
    const ageLabel = req.delivery_age_label
      || (req.days_since_delivery != null
        ? `${req.days_since_delivery} ngày kể từ khi giao`
        : (req.delivered_at != null
          ? `${Math.max(0, Math.floor((Date.now() / 1000 - Number(req.delivered_at)) / 86400))} ngày kể từ khi giao`
          : 'chưa có ngày giao'));
    metaRow.append(el('span', '', `Giao hàng: ${ageLabel}`));
    metaRow.append(el('span', '', `Người tạo: ${STAFF_OA_ROLE_VI[req.raised_by_role] || req.raised_by_role || 'Khách hàng'} · v${req.version}`));
    card.append(metaRow);

    const evList = Array.isArray(req.evidence) ? req.evidence : [];
    const evRow = el('div', 'case-ops-evidence-row');
    evRow.append(el('span', '', `Ảnh bằng chứng (${evList.length}/5):`));
    if (!evList.length) {
      evRow.append(el('span', 'case-ops-empty-hint', 'Chưa có ảnh đính kèm'));
    } else {
      evList.forEach(ev => {
        if (ev.purged || ev.file_purged_at != null) {
          const shaShort = String(ev.sha256 || '').slice(0, 12);
          evRow.append(el('span', 'case-ops-pill', `Đã xóa tệp sau 90 ngày · SHA-256 ${shaShort}…`));
        } else if (ev.mime_type === 'application/pdf') {
          const pdfLink = el('a', 'case-ops-pill', `📄 PDF (${ev.filename || ev.evidence_id})`);
          pdfLink.href = ev.download_url || `/api/order-actions/${encodeURIComponent(req.request_id)}/evidence/${encodeURIComponent(ev.evidence_id)}`;
          pdfLink.target = '_blank';
          pdfLink.rel = 'noopener noreferrer';
          evRow.append(pdfLink);
        } else {
          const img = el('img', 'case-ops-evidence-thumb');
          img.src = ev.download_url || `/api/order-actions/${encodeURIComponent(req.request_id)}/evidence/${encodeURIComponent(ev.evidence_id)}`;
          img.alt = `Ảnh bằng chứng ${ev.evidence_id}`;
          img.onclick = () => openLightbox(img.src, `Bằng chứng đơn ${req.order_id} (${ev.evidence_id})`);
          evRow.append(img);
        }
      });
    }
    card.append(evRow);

    const decs = Array.isArray(req.decisions) ? req.decisions : [];
    const decBox = el('div', 'case-ops-decisions');
    decBox.append(el('strong', '', `Lịch sử quyết định (${decs.length}):`));
    if (!decs.length) {
      decBox.append(el('span', 'case-ops-empty-hint', 'Chưa có lịch sử quyết định.'));
    } else {
      decs.forEach(d => {
        const isRefundStep = typeof d.action === 'string' && d.action.startsWith('refund_');
        const trans = isRefundStep
          ? `${d.from_refund_status || '—'} → ${d.to_refund_status || '—'}${d.refund_decision ? ` (${d.refund_decision})` : ''}`
          : `${d.from_status ? `${d.from_status} → ` : ''}${d.to_status || ''}`;
        const lineText = `• ${STAFF_OA_DECISION_VI[d.action] || d.action} [${STAFF_OA_ROLE_VI[d.actor_role] || d.actor_role || '—'}] ${trans}`
          + (d.inspection_outcome ? ` · KQ: ${STAFF_OA_OUTCOME_VI[d.inspection_outcome] || d.inspection_outcome}` : '')
          + (d.note ? ` — ${d.note}` : '');
        decBox.append(el('div', '', lineText));
      });
    }
    card.append(decBox);

    if (!isClosed) {
      const ctrlRow = el('div', 'case-ops-controls-row');
      const noteInput = el('input', 'case-ops-input');
      noteInput.type = 'text';
      noteInput.placeholder = 'Ghi chú quyết định (tùy chọn)...';
      noteInput.dataset.role = 'decision-note';

      const actionNodes = [];
      const gateNotes = [];
      const isDeliveryFailure = Boolean(
        req.delivery_failure_attempts != null
        || req.reason_code === 'delivery_failed'
        || ['staff', 'manager'].includes(req.raised_by_role)
      );

      const mkActionBtn = (cls, label, actName, onClick) => {
        const b = el('button', cls, label);
        b.type = 'button';
        b.dataset.action = actName;
        b.disabled = staffOrderActionBusy;
        b.onclick = onClick;
        actionNodes.push(b);
      };

      if (req.status === 'requested' || req.status === 'under_review') {
        if (isDeliveryFailure) {
          if (isManager) {
            mkActionBtn('primary', '✓ Duyệt hủy', 'approve', () => submitStaffOrderActionStep(req, 'approve', { note: noteInput.value }));
            mkActionBtn('secondary', '✕ Từ chối', 'reject', () => submitStaffOrderActionStep(req, 'reject', { note: noteInput.value }));
          } else {
            gateNotes.push('Chờ Quản lý duyệt (yêu cầu hủy do giao thất bại)');
          }
        } else if (canReview) {
          mkActionBtn('primary', '✓ Duyệt', 'approve', () => submitStaffOrderActionStep(req, 'approve', { note: noteInput.value }));
          mkActionBtn('secondary', '✕ Từ chối', 'reject', () => submitStaffOrderActionStep(req, 'reject', { note: noteInput.value }));
        } else if (!caseObj.holder) {
          gateNotes.push('Nhận ca để duyệt hoặc từ chối yêu cầu');
        } else {
          gateNotes.push('Ca đang do nhân viên khác giữ');
        }
      } else if ((req.type === 'return' || req.type === 'exchange') && req.status === 'approved') {
        if (canReview) {
          mkActionBtn('primary', '📦 Đã nhận hàng', 'mark-received', () => submitStaffOrderActionStep(req, 'mark-received', { note: noteInput.value }));
        } else if (!caseObj.holder) {
          gateNotes.push('Nhận ca để xác nhận đã nhận hàng');
        } else {
          gateNotes.push('Ca đang do nhân viên khác giữ');
        }
      } else if ((req.type === 'return' || req.type === 'exchange') && req.status === 'received') {
        if (canReview) {
          const outcomeSelect = el('select', 'case-ops-select');
          outcomeSelect.dataset.role = 'inspection-outcome';
          [
            ['refund', 'KQ kiểm tra: Hoàn tiền'],
            ['exchange', 'KQ kiểm tra: Đổi hàng'],
            ['no_action', 'KQ kiểm tra: Không xử lý']
          ].forEach(([val, lbl]) => {
            const opt = el('option', '', lbl);
            opt.value = val;
            outcomeSelect.append(opt);
          });
          outcomeSelect.value = req.type === 'exchange' ? 'exchange' : 'refund';
          actionNodes.push(outcomeSelect);
          mkActionBtn(
            'primary',
            '🔍 Đã kiểm tra',
            'mark-inspected',
            () => submitStaffOrderActionStep(req, 'mark-inspected', { inspection_outcome: outcomeSelect.value, note: noteInput.value })
          );
        } else if (!caseObj.holder) {
          gateNotes.push('Nhận ca để ghi kết quả kiểm tra');
        } else {
          gateNotes.push('Ca đang do nhân viên khác giữ');
        }
      } else if ((req.type === 'return' || req.type === 'exchange') && req.status === 'inspected') {
        if (canReview) {
          mkActionBtn('primary', '✓ Hoàn tất', 'complete', () => submitStaffOrderActionStep(req, 'complete', { note: noteInput.value }));
        } else if (!caseObj.holder) {
          gateNotes.push('Nhận ca để hoàn tất yêu cầu');
        } else {
          gateNotes.push('Ca đang do nhân viên khác giữ');
        }
      }

      if (['approved', 'received', 'inspected', 'completed'].includes(req.status) && req.refund_status === 'not_applicable') {
        if (canReview) {
          mkActionBtn('secondary', '💸 Gửi yêu cầu hoàn tiền', 'refund-request', () => submitStaffOrderActionStep(req, 'refund-request', { note: noteInput.value }));
        }
      } else if (req.refund_status === 'pending' && !req.refund_decision) {
        if (isManager) {
          mkActionBtn('primary', '✓ Duyệt hoàn tiền', 'refund-approve', () => submitStaffOrderActionStep(req, 'refund-decision', { decision: 'approved', note: noteInput.value }));
          mkActionBtn('secondary', '✕ Từ chối hoàn tiền', 'refund-reject', () => submitStaffOrderActionStep(req, 'refund-decision', { decision: 'rejected', note: noteInput.value }));
        } else {
          gateNotes.push('Chờ Quản lý duyệt hoàn tiền');
        }
      } else if (req.refund_status === 'pending' && req.refund_decision === 'approved') {
        if (req.refund_managed_by_provider) {
          gateNotes.push('Hoàn tiền do cổng thanh toán cập nhật tự động (connector)');
        } else if (isManager) {
          mkActionBtn('primary', '💰 Ghi nhận Đã hoàn tiền', 'refund-outcome-refunded', () => submitStaffOrderActionStep(req, 'refund-outcome', { outcome: 'refunded', note: noteInput.value }));
          mkActionBtn('secondary', '⚠ Ghi nhận Hoàn thất bại', 'refund-outcome-failed', () => submitStaffOrderActionStep(req, 'refund-outcome', { outcome: 'failed', note: noteInput.value }));
        } else {
          gateNotes.push('Chờ Quản lý ghi kết quả hoàn tiền');
        }
      }

      if (actionNodes.length > 0) {
        ctrlRow.append(noteInput, ...actionNodes);
      }
      gateNotes.forEach(txt => {
        ctrlRow.append(el('span', 'case-ops-role-gate-note', txt));
      });
      if (actionNodes.length > 0 || gateNotes.length > 0) {
        card.append(ctrlRow);
      }
    }

    panelEl.append(card);
  });

  const allCaseOrdersForRecipient = staffCaseOrders.length > 0 ? staffCaseOrders : staffCaseCustomerOrders;
  const linkedCaseOrderIds = new Set(
    [caseObj.order_id, ...staffCaseOrderActions.map(r => r && r.order_id)].filter(Boolean)
  );
  const maskedRecipientOrders = allCaseOrdersForRecipient.filter(o => o && o.recipient_masked);
  const revealableOrders = (isManager
    ? maskedRecipientOrders
    : (!isClosed && isHolder ? maskedRecipientOrders.filter(o => linkedCaseOrderIds.has(o.id)) : [])
  ).filter(o => o.recipient_masked && o.recipient_masked.has_encrypted_recipient !== false);

  if (maskedRecipientOrders.length > 0) {
    const rcpCard = el('div', 'case-ops-consented-card');
    rcpCard.id = 'staff-recipient-reveal-card';
    rcpCard.dataset.role = 'staff-recipient-card';
    rcpCard.append(el('strong', '', '🔐 Thông tin người nhận (kiểm toán)'));

    maskedRecipientOrders.forEach(o => {
      const rm = o.recipient_masked || {};
      const areaTxt = [rm.ward, rm.district, rm.province].filter(Boolean).join(', ') || '—';
      const lineTxt = `${formatDualOrderId(o.id, o.external_order_id)} · SĐT: ${rm.phone_masked || '—'} · Khu vực: ${areaTxt}`;
      rcpCard.append(el('div', 'case-ops-meta-row', lineTxt));
    });

    if (revealableOrders.length > 0) {
      const rcpRow = el('div', 'case-ops-controls-row');
      const rcpOrdSel = el('select', 'case-ops-select');
      rcpOrdSel.id = 'staff-reveal-order-select';
      revealableOrders.forEach(o => {
        const opt = el('option', '', formatDualOrderId(o.id, o.external_order_id));
        opt.value = o.id;
        rcpOrdSel.append(opt);
      });
      const selRcpOid = revealableOrders.some(o => o.id === staffConsentDraft.revealOrderId)
        ? staffConsentDraft.revealOrderId
        : revealableOrders[0].id;
      rcpOrdSel.value = selRcpOid;
      staffConsentDraft.revealOrderId = selRcpOid;

      const rcpReasonInput = el('input', 'case-ops-input');
      rcpReasonInput.type = 'text';
      rcpReasonInput.id = 'staff-reveal-reason-input';
      rcpReasonInput.maxLength = 500;
      rcpReasonInput.placeholder = 'Lý do xem người nhận đầy đủ (bắt buộc)...';
      rcpReasonInput.value = staffConsentDraft.revealReason || '';

      const rcpBtn = el('button', 'secondary', '👁 Xem người nhận đầy đủ');
      rcpBtn.type = 'button';
      rcpBtn.id = 'btn-reveal-recipient';
      rcpBtn.dataset.action = 'reveal-recipient';
      const syncRevealBtn = () => {
        rcpBtn.disabled = Boolean(staffOrderActionBusy || !(rcpReasonInput.value || '').trim());
      };
      rcpOrdSel.onchange = () => {
        staffConsentDraft.revealOrderId = rcpOrdSel.value;
        renderStaffCaseOrderActions();
      };
      rcpReasonInput.oninput = () => {
        staffConsentDraft.revealReason = rcpReasonInput.value;
        syncRevealBtn();
      };
      rcpBtn.onclick = () => submitStaffRevealRecipient();
      syncRevealBtn();

      rcpRow.append(rcpOrdSel, rcpReasonInput, rcpBtn);
      rcpCard.append(rcpRow);

      const revealed = staffRevealedRecipients[selRcpOid];
      if (revealed && revealed.recipient) {
        const revBox = el('div', 'case-ops-decisions');
        revBox.dataset.role = 'revealed-recipient-details';
        const r = revealed.recipient;
        const fullAddr = [r.address_line, r.ward, r.district, r.province].filter(Boolean).join(', ');
        revBox.append(
          el('strong', '', `Đã mở khóa người nhận (${formatDualOrderId(revealed.order_id, revealed.external_order_id)}) · Đã ghi nhật ký kiểm toán`),
          el('div', '', `Họ tên: ${r.name || '—'} · SĐT: ${r.phone || r.phone_masked || '—'}`),
          el('div', '', `Địa chỉ: ${fullAddr || '—'}`)
        );
        rcpCard.append(revBox);
      }
    } else {
      const gateMsg = el(
        'span',
        'case-ops-role-gate-note',
        'Nhận giữ ca mở có gắn đơn hàng hoặc đăng nhập Quản lý để xem thông tin người nhận đầy đủ.'
      );
      gateMsg.dataset.role = 'recipient-gate-note';
      rcpCard.append(gateMsg);
    }
    panelEl.append(rcpCard);
  }

  if (staffCaseCompensations.length > 0) {
    const compCard = el('div', 'case-ops-consented-card');
    compCard.id = 'staff-case-compensations-card';
    compCard.dataset.role = 'staff-case-compensations-card';
    compCard.append(el('strong', '', '🎁 Đề xuất bồi thường giao trễ (mệnh giá cố định 50.000 ₫)'));

    staffCaseCompensations.forEach(comp => {
      const compItem = el('div', 'case-ops-item');
      compItem.dataset.compensationId = comp.compensation_id;
      const stLabel = compensationStatusLabels[comp.status] || comp.status || '—';
      const ordLbl = formatDualOrderId(comp.order_id, comp.external_order_id);
      const valLbl = money(comp.value || 50000);
      const headerTxt = `${ordLbl} · Trễ ${comp.late_by_hours ?? '—'}h · Voucher giảm giá ${valLbl} · [${stLabel}]`;
      compItem.append(el('div', 'case-ops-meta-row', headerTxt));
      if (comp.voucher_code) {
        compItem.append(el('div', 'case-ops-meta-row', `Mã voucher đã phát: ${comp.voucher_code}`));
      }
      if (comp.status === 'proposed') {
        const compCtrl = el('div', 'case-ops-controls-row');
        if (isManager || (!isClosed && isHolder)) {
          const compNote = el('input', 'case-ops-input');
          compNote.type = 'text';
          compNote.id = `staff-comp-note-${comp.compensation_id}`;
          compNote.maxLength = 500;
          compNote.placeholder = 'Ghi chú duyệt/từ chối (tùy chọn)...';

          const btnApprove = el('button', 'primary btn-sm', `✓ Duyệt ${valLbl}`);
          btnApprove.type = 'button';
          btnApprove.id = `btn-approve-comp-${comp.compensation_id}`;
          btnApprove.dataset.action = 'approve-compensation';
          btnApprove.disabled = staffOrderActionBusy;
          btnApprove.onclick = () => submitCompensationDecision(comp.compensation_id, 'approve', {
            note: compNote.value,
            caseId: caseObj.case_id
          });

          const btnReject = el('button', 'secondary btn-sm', '✕ Từ chối');
          btnReject.type = 'button';
          btnReject.id = `btn-reject-comp-${comp.compensation_id}`;
          btnReject.dataset.action = 'reject-compensation';
          btnReject.disabled = staffOrderActionBusy;
          btnReject.onclick = () => submitCompensationDecision(comp.compensation_id, 'reject', {
            note: compNote.value,
            caseId: caseObj.case_id
          });

          compCtrl.append(compNote, btnApprove, btnReject);
        } else {
          compCtrl.append(
            el(
              'span',
              'case-ops-role-gate-note',
              'Nhận giữ ca mở có gắn đơn hàng hoặc đăng nhập Quản lý để duyệt đề xuất bồi thường.'
            )
          );
        }
        compItem.append(compCtrl);
      }
      compCard.append(compItem);
    });

    panelEl.append(compCard);
  }

  if (!isClosed) {
    if (staffConsentDraft.caseId !== caseObj.case_id) {
      resetStaffConsentDraft(caseObj.case_id);
    }
    const openOrderIds = new Set(
      staffCaseOrderActions
        .filter(r => r && r.closed_at == null && !['rejected', 'completed'].includes(r.status) && !(r.type === 'cancel' && r.status === 'approved'))
        .map(r => r.order_id)
    );
    const effectiveOrders = staffCaseOrders.length > 0 ? staffCaseOrders : staffCaseCustomerOrders;
    const isOrderEligibleForConsent = o => Boolean(
      o
      && !openOrderIds.has(o.id)
      && !o.open_order_action
      && getConsentTypeChoicesForOrder(o).length > 0
    );

    if (canReview) {
      const consentCard = el('div', 'case-ops-consented-card');
      consentCard.id = 'staff-consented-oa-card';
      consentCard.append(el('strong', '', '✍️ Tạo yêu cầu theo đồng ý của khách'));

      const formGrid = el('div', 'case-ops-form-grid');

      const ordField = el('div', 'case-ops-field case-ops-field-wide');
      ordField.append(el('label', 'case-ops-label', 'Đơn hàng của khách'));
      const cOrdSel = el('select', 'case-ops-select');
      cOrdSel.id = 'staff-consent-order-select';
      cOrdSel.setAttribute('aria-label', 'Đơn hàng của khách');
      const eligibleConsentOrders = effectiveOrders.filter(isOrderEligibleForConsent);
      if (!effectiveOrders.length) {
        const emptyOpt = el('option', '', '— Khách chưa có đơn hàng —');
        emptyOpt.value = '';
        cOrdSel.append(emptyOpt);
        cOrdSel.value = '';
        cOrdSel.disabled = true;
      } else {
        if (!eligibleConsentOrders.length) {
          const noneOpt = el('option', '', '— Không còn đơn đủ điều kiện tạo yêu cầu —');
          noneOpt.value = '';
          cOrdSel.append(noneOpt);
        }
        effectiveOrders.forEach(o => {
          const hasOpen = openOrderIds.has(o.id) || Boolean(o.open_order_action);
          const choices = getConsentTypeChoicesForOrder(o);
          const statusVi = statuses[o.status] || o.status || '—';
          const allowedNote = hasOpen
            ? 'đang có yêu cầu mở'
            : (choices.length ? ('cho phép: ' + choices.map(c => c.label).join(', ')) : 'không đủ điều kiện');
          const opt = el('option', '', `${formatDualOrderId(o.id, o.external_order_id)} · ${o.display_name || o.name || 'Đơn hàng'} [${statusVi} · ${allowedNote}]`);
          opt.value = o.id;
          opt.disabled = hasOpen || choices.length === 0;
          cOrdSel.append(opt);
        });
        if (eligibleConsentOrders.length > 0) {
          const pickedId = eligibleConsentOrders.some(o => o.id === staffConsentDraft.orderId)
            ? staffConsentDraft.orderId
            : eligibleConsentOrders[0].id;
          cOrdSel.value = pickedId;
          staffConsentDraft.orderId = pickedId;
          cOrdSel.disabled = staffOrderActionBusy;
        } else {
          cOrdSel.value = '';
          staffConsentDraft.orderId = '';
          cOrdSel.disabled = true;
        }
      }
      ordField.append(cOrdSel);

      const typeField = el('div', 'case-ops-field');
      typeField.append(el('label', 'case-ops-label', 'Loại yêu cầu'));
      const cTypeSel = el('select', 'case-ops-select');
      cTypeSel.id = 'staff-consent-type-select';
      cTypeSel.setAttribute('aria-label', 'Loại yêu cầu');
      typeField.append(cTypeSel);

      const reasonField = el('div', 'case-ops-field');
      reasonField.append(el('label', 'case-ops-label', 'Lý do'));
      const cReasonSel = el('select', 'case-ops-select');
      cReasonSel.id = 'staff-consent-reason-select';
      cReasonSel.setAttribute('aria-label', 'Lý do');
      reasonField.append(cReasonSel);

      const targetField = el('div', 'case-ops-field case-ops-field-wide');
      targetField.id = 'staff-consent-target-field';
      targetField.hidden = true;
      targetField.append(el('label', 'case-ops-label', 'Biến thể khách muốn đổi sang (tồn kho chỉ để tham khảo)'));
      const cTargetSel = el('select', 'case-ops-select');
      cTargetSel.id = 'staff-consent-target-select';
      cTargetSel.setAttribute('aria-label', 'Biến thể đích');
      targetField.append(cTargetSel);

      const turnField = el('div', 'case-ops-field case-ops-field-wide');
      turnField.append(el('label', 'case-ops-label', 'Tin nhắn đồng ý của khách (30 phút gần nhất)'));
      const cTurnSel = el('select', 'case-ops-select');
      cTurnSel.id = 'staff-consent-turn-select';
      cTurnSel.setAttribute('aria-label', 'Tin nhắn đồng ý của khách');
      const placeholderTurnOpt = el('option', '', '— Chọn tin nhắn đồng ý của khách —');
      placeholderTurnOpt.value = '';
      cTurnSel.append(placeholderTurnOpt);
      const sortedConsentTurns = [...staffCaseConsentTurns].sort((a, b) => Number(b.turn_id) - Number(a.turn_id));
      sortedConsentTurns.forEach(t => {
        const tOpt = el('option', '', formatConsentTurnOptionLabel(t));
        tOpt.value = String(t.turn_id);
        cTurnSel.append(tOpt);
      });
      if (!staffConsentDraft.turnManuallyChanged) {
        cTurnSel.value = sortedConsentTurns.length > 0 ? String(sortedConsentTurns[0].turn_id) : '';
        staffConsentDraft.consentTurnId = cTurnSel.value;
      } else {
        const stillValid = sortedConsentTurns.some(t => String(t.turn_id) === String(staffConsentDraft.consentTurnId));
        cTurnSel.value = stillValid ? String(staffConsentDraft.consentTurnId) : '';
      }
      cTurnSel.disabled = staffOrderActionBusy;
      turnField.append(cTurnSel);

      const actionRow = el('div', 'case-ops-controls-row');
      const cNoteInput = el('input', 'case-ops-input');
      cNoteInput.type = 'text';
      cNoteInput.id = 'staff-consent-note-input';
      cNoteInput.placeholder = 'Ghi chú bổ sung (tùy chọn)...';
      cNoteInput.value = staffConsentDraft.noteText || '';
      cNoteInput.disabled = staffOrderActionBusy;

      const cSubmitBtn = el('button', 'primary', 'Tạo yêu cầu theo đồng ý khách');
      cSubmitBtn.type = 'button';
      cSubmitBtn.id = 'btn-create-consented-order-action';
      cSubmitBtn.dataset.action = 'create-consented-order-action';

      const populateConsentReasons = (preferredReason = '') => {
        const entries = getConsentReasonsForTypeKey(cTypeSel.value);
        cReasonSel.replaceChildren();
        if (!entries.length) {
          const emptyR = el('option', '', '— Chưa có lý do —');
          emptyR.value = '';
          cReasonSel.append(emptyR);
          cReasonSel.value = '';
          cReasonSel.disabled = true;
          staffConsentDraft.reasonCode = '';
          return;
        }
        entries.forEach(([code, label]) => {
          const rOpt = el('option', '', label);
          rOpt.value = code;
          cReasonSel.append(rOpt);
        });
        const nextReason = entries.some(([code]) => code === preferredReason) ? preferredReason : entries[0][0];
        cReasonSel.value = nextReason;
        cReasonSel.disabled = staffOrderActionBusy;
        staffConsentDraft.reasonCode = nextReason;
      };

      const populateConsentTypes = (preferredType = '') => {
        const selOrd = effectiveOrders.find(o => o.id === cOrdSel.value);
        const choices = isOrderEligibleForConsent(selOrd) ? getConsentTypeChoicesForOrder(selOrd) : [];
        cTypeSel.replaceChildren();
        if (!choices.length) {
          const emptyT = el('option', '', '— Chọn loại —');
          emptyT.value = '';
          cTypeSel.append(emptyT);
          cTypeSel.value = '';
          cTypeSel.disabled = true;
          staffConsentDraft.typeKey = '';
          populateConsentReasons('');
          return;
        }
        choices.forEach(ch => {
          const tOpt = el('option', '', ch.label);
          tOpt.value = ch.value;
          cTypeSel.append(tOpt);
        });
        const nextType = choices.some(ch => ch.value === preferredType) ? preferredType : choices[0].value;
        cTypeSel.value = nextType;
        cTypeSel.disabled = staffOrderActionBusy;
        staffConsentDraft.typeKey = nextType;
        populateConsentReasons(staffConsentDraft.reasonCode);
      };

      // An exchange to another variant names the variant (real variants of the order's product, with stock).
      const populateConsentTargets = async () => {
        const wantsTarget = cTypeSel.value === 'exchange:other_variant' && Boolean(cOrdSel.value);
        targetField.hidden = !wantsTarget;
        cTargetSel.replaceChildren();
        if (!wantsTarget) {
          staffConsentDraft.targetVariantId = '';
          return;
        }
        const orderId = cOrdSel.value;
        let options = staffConsentDraft.variantOptions[orderId];
        if (!options) {
          try {
            options = await api(`/api/staff/cases/${encodeURIComponent(caseObj.case_id)}/orders/${encodeURIComponent(orderId)}/exchange-options`);
          } catch (err) {
            options = { variants: [] };
          }
          staffConsentDraft.variantOptions[orderId] = options;
        }
        if (cOrdSel.value !== orderId || cTypeSel.value !== 'exchange:other_variant') return;  // the choice moved on meanwhile
        const variants = Array.isArray(options.variants) ? options.variants : [];
        const placeholder = el('option', '', variants.length ? '— Chọn biến thể —' : '— Đơn này chưa có danh sách biến thể —');
        placeholder.value = '';
        cTargetSel.append(placeholder);
        variants.forEach(v => {
          const opt = el('option', '', `${v.label} · ${variantStockText(v)}${v.is_current ? ' (đang giữ)' : ''}`);
          opt.value = v.id;
          opt.disabled = Boolean(v.is_current);
          cTargetSel.append(opt);
        });
        const keep = variants.some(v => v.id === staffConsentDraft.targetVariantId && !v.is_current) ? staffConsentDraft.targetVariantId : '';
        cTargetSel.value = keep;
        cTargetSel.disabled = staffOrderActionBusy;
        staffConsentDraft.targetVariantId = keep;
        syncConsentSubmitState();
      };

      const syncConsentSubmitState = () => {
        const selOrd = effectiveOrders.find(o => o.id === cOrdSel.value);
        const validTurn = /^[1-9]\d*$/.test(String(cTurnSel.value || '').trim());
        const needsTarget = cTypeSel.value === 'exchange:other_variant';
        const needsText = Boolean(reasonEntry(cReasonSel.value)?.requires_text);
        cNoteInput.required = needsText;
        cNoteInput.placeholder = needsText ? 'Mô tả lý do (bắt buộc)...' : 'Ghi chú bổ sung (tùy chọn)...';
        cSubmitBtn.disabled = Boolean(
          staffOrderActionBusy
          || !isOrderEligibleForConsent(selOrd)
          || !cTypeSel.value
          || !cReasonSel.value
          || !validTurn
          || (needsTarget && !cTargetSel.value)
          || (needsText && !(cNoteInput.value || '').trim())
        );
      };

      cOrdSel.onchange = () => {
        staffConsentDraft.orderId = cOrdSel.value;
        staffConsentDraft.targetVariantId = '';
        populateConsentTypes('');
        syncConsentSubmitState();
        return populateConsentTargets();
      };
      cTypeSel.onchange = () => {
        staffConsentDraft.typeKey = cTypeSel.value;
        populateConsentReasons('');
        syncConsentSubmitState();
        return populateConsentTargets();
      };
      cTargetSel.onchange = () => {
        staffConsentDraft.targetVariantId = cTargetSel.value;
        syncConsentSubmitState();
      };
      cReasonSel.onchange = () => {
        staffConsentDraft.reasonCode = cReasonSel.value;
        syncConsentSubmitState();
      };
      cTurnSel.onchange = () => {
        staffConsentDraft.turnManuallyChanged = true;
        staffConsentDraft.consentTurnId = cTurnSel.value;
        syncConsentSubmitState();
      };
      cNoteInput.oninput = () => {
        staffConsentDraft.noteText = cNoteInput.value;
        syncConsentSubmitState();
      };
      cSubmitBtn.onclick = () => submitStaffConsentedOrderAction();

      populateConsentTypes(staffConsentDraft.typeKey);
      syncConsentSubmitState();
      populateConsentTargets();

      formGrid.append(ordField, typeField, reasonField, targetField, turnField);
      actionRow.append(cNoteInput, cSubmitBtn);
      consentCard.append(formGrid, actionRow);
      if (!sortedConsentTurns.length) {
        consentCard.append(
          el('span', 'case-ops-empty-hint', 'Chưa có tin nhắn đồng ý của khách trong ca hiện tại (30 phút gần nhất).')
        );
      }
      panelEl.append(consentCard);
    }

    if (isHolder) {
      const eligiblePendingOrders = effectiveOrders.filter(o => o && o.status === 'pending' && !openOrderIds.has(o.id) && !o.open_order_action);
      if (eligiblePendingOrders.length > 0) {
        const otherDetails = el('details', 'case-ops-other-details');
        otherDetails.id = 'staff-other-ops';
        otherDetails.open = Boolean(staffConsentDraft.otherOpsOpen);
        otherDetails.ontoggle = () => {
          staffConsentDraft.otherOpsOpen = Boolean(otherDetails.open);
        };
        otherDetails.append(el('summary', 'case-ops-other-summary', 'Thao tác khác'));

        const dfCard = el('div', 'case-ops-delivery-fail-card');
        dfCard.append(el('strong', '', '🚚 Tạo yêu cầu hủy do giao thất bại (chờ Quản lý duyệt)'));
        const dfRow = el('div', 'case-ops-controls-row');
        const ordSel = el('select', 'case-ops-select');
        ordSel.id = 'staff-df-order-select';
        eligiblePendingOrders.forEach(o => {
          const opt = el('option', '', `${formatDualOrderId(o.id, o.external_order_id)} · ${o.display_name || o.name || 'Đơn hàng'} (${money(o.amount || 0)})`);
          opt.value = o.id;
          ordSel.append(opt);
        });
        if (staffConsentDraft.dfOrderId && eligiblePendingOrders.some(o => o.id === staffConsentDraft.dfOrderId)) {
          ordSel.value = staffConsentDraft.dfOrderId;
        } else {
          ordSel.value = eligiblePendingOrders[0].id;
        }
        ordSel.onchange = () => {
          staffConsentDraft.dfOrderId = ordSel.value;
        };

        const attemptsInput = el('input', 'case-ops-select');
        attemptsInput.type = 'number';
        attemptsInput.id = 'staff-df-attempts-input';
        attemptsInput.min = '1';
        attemptsInput.step = '1';
        attemptsInput.value = staffConsentDraft.dfAttempts || '1';
        attemptsInput.setAttribute('aria-label', 'Số lần giao thất bại');
        attemptsInput.oninput = () => {
          staffConsentDraft.dfAttempts = attemptsInput.value;
        };

        const dfNoteInput = el('input', 'case-ops-input');
        dfNoteInput.type = 'text';
        dfNoteInput.id = 'staff-df-note-input';
        dfNoteInput.placeholder = 'Ghi chú giao thất bại (bắt buộc)...';
        dfNoteInput.value = staffConsentDraft.dfNote || '';
        dfNoteInput.oninput = () => {
          staffConsentDraft.dfNote = dfNoteInput.value;
        };

        const dfBtn = el('button', 'secondary', 'Tạo yêu cầu hủy do giao thất bại');
        dfBtn.type = 'button';
        dfBtn.id = 'btn-create-delivery-failure';
        dfBtn.dataset.action = 'create-delivery-failure';
        dfBtn.disabled = staffOrderActionBusy;
        dfBtn.onclick = () => submitStaffDeliveryFailureCancel();

        dfRow.append(ordSel, attemptsInput, dfNoteInput, dfBtn);
        dfCard.append(dfRow);
        otherDetails.append(dfCard);
        panelEl.append(otherDetails);
      }
    }
  }
}

async function loadStaffCaseOrderActions(caseId, isCaseSelection = false) {
  if (!caseId) {
    staffCaseOrderActions = [];
    staffCaseCompensations = [];
    staffCaseUnlinkedRefunds = [];
    staffCaseCustomerOrders = [];
    staffCaseOrders = [];
    staffCaseConsentTurns = [];
    staffCaseOrderReasonsMap = null;
    staffCaseOrderActionsReadOnly = false;
    staffCaseOpenRequestSig = '';
    resetStaffConsentDraft(null);
    renderStaffCaseOrderActions();
    return;
  }
  if (isCaseSelection && staffConsentDraft.caseId !== caseId) {
    resetStaffConsentDraft(caseId);
  }
  try {
    const [res, ordersRes] = await Promise.all([
      api(`/api/staff/cases/${encodeURIComponent(caseId)}/order-actions`),
      api(`/api/staff/cases/${encodeURIComponent(caseId)}/orders`).catch(() => null)
    ]);
    if (!activeStaffTicket || activeStaffTicket.case_id !== caseId) return;
    staffCaseOrderActions = Array.isArray(res?.order_actions) ? res.order_actions : [];
    staffCaseCompensations = Array.isArray(res?.compensations) ? res.compensations : [];
    staffCaseUnlinkedRefunds = Array.isArray(res?.unlinked_refunds) ? res.unlinked_refunds : [];
    staffCaseCustomerOrders = Array.isArray(res?.customer_orders) ? res.customer_orders : [];
    const openByOid = new Map();
    staffCaseOrderActions.filter(isOrderActionOpen).forEach(r => {
      if (r && r.order_id && !openByOid.has(r.order_id)) {
        openByOid.set(r.order_id, r);
      }
    });
    if (ordersRes && Array.isArray(ordersRes.orders)) {
      staffCaseOrders = ordersRes.orders;
      staffCaseConsentTurns = Array.isArray(ordersRes.consent_turns) ? ordersRes.consent_turns : [];
      staffCaseOrderReasonsMap = ordersRes.order_action_reasons || null;
      if (!staffCaseCustomerOrders.length && staffCaseOrders.length) {
        staffCaseCustomerOrders = staffCaseOrders;
      }
    } else {
      staffCaseOrders = staffCaseCustomerOrders.map(o => ({
        ...o,
        allowed_action_types: o.status === 'pending'
          ? ['cancel']
          : (o.status === 'delivered' ? ['return', 'exchange'] : []),
        open_order_action: openByOid.get(o.id) || null
      }));
      staffCaseConsentTurns = [];
      staffCaseOrderReasonsMap = null;
    }
    staffCaseOrderActionsReadOnly = Boolean(res?.read_only || ordersRes?.read_only);
    const openReqs = staffCaseOrderActions.filter(isOrderActionOpen);
    const nextSig = caseId + ':' + openReqs.map(r => r.request_id).sort().join(',');
    if (openReqs.length > 0 && (isCaseSelection || nextSig !== staffCaseOpenRequestSig)) {
      applyStaffCaseOpsCollapseState(false);
    } else if (isCaseSelection && openReqs.length === 0) {
      applyStaffCaseOpsCollapseState(readStaffCaseOpsSavedCollapsed());
    }
    staffCaseOpenRequestSig = nextSig;
    renderStaffCaseOrderActions();
  } catch (err) {
    if (!activeStaffTicket || activeStaffTicket.case_id !== caseId) return;
    staffCaseOrderActions = [];
    staffCaseCompensations = [];
    staffCaseUnlinkedRefunds = [];
    staffCaseCustomerOrders = [];
    staffCaseOrders = [];
    staffCaseConsentTurns = [];
    staffCaseOrderReasonsMap = null;
    renderStaffCaseOrderActions();
  }
}

async function submitCompensationDecision(compensationId, decision, opts = {}) {
  if (!compensationId || !['approve', 'reject'].includes(decision) || staffOrderActionBusy) return;
  const payload = {};
  const cleanNote = String(opts.note || '').trim();
  if (cleanNote) payload.note = cleanNote;
  if (opts.caseId) payload.case_id = opts.caseId;
  staffOrderActionBusy = true;
  renderStaffCaseOrderActions();
  renderManagerCompensationsPanels();
  try {
    await api(`/api/staff/compensations/${encodeURIComponent(compensationId)}/${decision}`, payload);
    setStaffDeskNotice(
      decision === 'approve'
        ? 'Đã duyệt đề xuất bồi thường giao trễ (50.000 ₫).'
        : 'Đã từ chối đề xuất bồi thường giao trễ.',
      'success'
    );
    if (activeStaffTicket?.case_id) {
      await loadStaffCaseOrderActions(activeStaffTicket.case_id, false);
    }
    if (currentSessionRole === 'manager') {
      await loadManagerCompensations(true);
    }
  } catch (err) {
    setStaffDeskNotice(err.message || 'Không thể xử lý đề xuất bồi thường.', 'error');
  } finally {
    staffOrderActionBusy = false;
    renderStaffCaseOrderActions();
    renderManagerCompensationsPanels();
  }
}

function renderManagerCompensationsInto(container, idPrefix) {
  if (!container) return;
  if (currentSessionRole !== 'manager') {
    container.hidden = true;
    container.replaceChildren();
    return;
  }
  container.hidden = false;
  container.replaceChildren();
  const proposedCnt = Number(managerCompensationsCounts.proposed || 0);
  container.append(
    el(
      'strong',
      '',
      `🎁 Đề xuất bồi thường giao trễ toàn cửa hàng (${proposedCnt} chờ duyệt / tổng ${managerCompensations.length})`
    )
  );
  if (!managerCompensations.length) {
    container.append(el('div', 'case-ops-empty-hint', 'Chưa có đề xuất bồi thường giao trễ nào.'));
    return;
  }
  managerCompensations.forEach(comp => {
    const row = el('div', 'case-ops-item');
    row.dataset.compensationId = comp.compensation_id;
    const stLabel = compensationStatusLabels[comp.status] || comp.status || '—';
    const ordLbl = formatDualOrderId(comp.order_id, comp.external_order_id);
    const valLbl = money(comp.value || 50000);
    const custLbl = comp.customer_name || 'Khách hàng';
    const metaTxt = `${ordLbl} · ${custLbl} · Trễ ${comp.late_by_hours ?? '—'}h · ${valLbl} · [${stLabel}]`
      + (comp.voucher_code ? ` · Mã: ${comp.voucher_code}` : '');
    row.append(el('div', 'case-ops-meta-row', metaTxt));
    if (comp.status === 'proposed') {
      const actRow = el('div', 'case-ops-controls-row');
      const btnApp = el('button', 'primary btn-sm', `✓ Duyệt ${valLbl}`);
      btnApp.type = 'button';
      btnApp.id = `${idPrefix}-approve-${comp.compensation_id}`;
      btnApp.disabled = staffOrderActionBusy;
      btnApp.onclick = () => submitCompensationDecision(comp.compensation_id, 'approve', {});

      const btnRej = el('button', 'secondary btn-sm', '✕ Từ chối');
      btnRej.type = 'button';
      btnRej.id = `${idPrefix}-reject-${comp.compensation_id}`;
      btnRej.disabled = staffOrderActionBusy;
      btnRej.onclick = () => submitCompensationDecision(comp.compensation_id, 'reject', {});

      actRow.append(btnApp, btnRej);
      row.append(actRow);
    }
    container.append(row);
  });
}

function renderManagerCompensationsPanels() {
  renderManagerCompensationsInto(byId('staff-manager-compensations-panel'), 'staff-mgr-comp');
  renderManagerCompensationsInto(byId('manager-compensations-panel'), 'mgr-console-comp');
}

async function loadManagerCompensations(silent = false) {
  if (currentSessionRole !== 'manager') return;
  try {
    const res = await api('/api/manager/compensations?status=all&limit=50&offset=0');
    managerCompensations = Array.isArray(res?.items) ? res.items : [];
    if (res?.counts && typeof res.counts === 'object') {
      managerCompensationsCounts = {
        proposed: Number(res.counts.proposed || 0),
        approved: Number(res.counts.approved || 0),
        requested: Number(res.counts.requested || 0),
        issued: Number(res.counts.issued || 0),
        rejected: Number(res.counts.rejected || 0),
        failed: Number(res.counts.failed || 0),
        all: Number(res.counts.all || 0)
      };
    }
    renderManagerCompensationsPanels();
  } catch (err) {
    if (!silent) {
      console.warn('Lỗi tải danh sách đề xuất bồi thường:', err);
    }
  }
}

async function submitStaffRevealRecipient() {
  if (!activeStaffTicket?.case_id || staffOrderActionBusy) return;
  const ordSel = byId('staff-reveal-order-select');
  const reasonEl = byId('staff-reveal-reason-input');
  const orderId = (ordSel?.value || staffConsentDraft.revealOrderId || '').trim();
  const reason = (reasonEl?.value || staffConsentDraft.revealReason || '').trim();
  if (!orderId) {
    setStaffDeskNotice('Vui lòng chọn đơn hàng cần xem người nhận.', 'error');
    return;
  }
  if (!reason) {
    setStaffDeskNotice('Vui lòng nhập lý do trước khi xem thông tin người nhận.', 'error');
    return;
  }
  staffOrderActionBusy = true;
  renderStaffCaseOrderActions();
  try {
    const res = await api(`/api/staff/orders/${encodeURIComponent(orderId)}/reveal-recipient`, {
      reason,
      case_id: activeStaffTicket.case_id
    });
    staffRevealedRecipients[orderId] = res;
    staffConsentDraft.revealReason = '';
    setStaffDeskNotice('Đã giải mã thông tin người nhận và ghi nhật ký kiểm toán.', 'success');
  } catch (err) {
    setStaffDeskNotice(err.message || 'Không thể xem thông tin người nhận.', 'error');
  } finally {
    staffOrderActionBusy = false;
    renderStaffCaseOrderActions();
  }
}

async function submitStaffConsentedOrderAction() {
  if (!activeStaffTicket?.case_id || staffOrderActionBusy) return;
  const orderSel = byId('staff-consent-order-select');
  const typeSel = byId('staff-consent-type-select');
  const reasonSel = byId('staff-consent-reason-select');
  const turnSel = byId('staff-consent-turn-select');
  const noteEl = byId('staff-consent-note-input');

  const orderId = (orderSel?.value || '').trim();
  const typeKey = (typeSel?.value || '').trim();
  const reasonCode = (reasonSel?.value || '').trim();
  const turnRaw = (turnSel?.value || '').trim();
  const reasonText = (noteEl?.value || '').trim();
  const consentTurnId = /^[1-9]\d*$/.test(turnRaw) ? parseInt(turnRaw, 10) : NaN;

  if (!orderId) {
    setStaffDeskNotice('Vui lòng chọn đơn hàng đủ điều kiện trước khi tạo yêu cầu.', 'error');
    return;
  }
  if (!typeKey || !reasonCode) {
    setStaffDeskNotice('Vui lòng chọn loại yêu cầu và lý do hợp lệ.', 'error');
    return;
  }
  if (!Number.isInteger(consentTurnId) || consentTurnId < 1) {
    setStaffDeskNotice('Vui lòng chọn tin nhắn đồng ý của khách hàng trước khi tạo yêu cầu.', 'error');
    return;
  }

  let actionType = typeKey;
  let exchangeKind = null;
  if (typeKey.startsWith('exchange:')) {
    actionType = 'exchange';
    exchangeKind = typeKey.split(':')[1] === 'same_variant' ? 'same_variant' : 'other_variant';
  }
  const targetVariantId = (byId('staff-consent-target-select')?.value || '').trim();
  if (exchangeKind === 'other_variant' && !targetVariantId) {
    setStaffDeskNotice('Vui lòng chọn biến thể khách muốn đổi sang.', 'error');
    return;
  }
  if (reasonEntry(reasonCode)?.requires_text && !reasonText) {
    setStaffDeskNotice('Lý do này bắt buộc nhập mô tả.', 'error');
    return;
  }

  const effectiveOrders = staffCaseOrders.length > 0 ? staffCaseOrders : staffCaseCustomerOrders;
  const ordObj = effectiveOrders.find(o => o.id === orderId);
  const payload = {
    order_id: orderId,
    expected_order_version: (ordObj && Number.isInteger(ordObj.version)) ? ordObj.version : 1,
    type: actionType,
    reason_code: reasonCode,
    consent_turn_id: consentTurnId
  };
  if (exchangeKind) {
    payload.exchange_kind = exchangeKind;
  }
  if (exchangeKind === 'other_variant') {
    payload.target_variant_id = targetVariantId;
  }
  if (reasonText) {
    payload.reason_text = reasonText;
  }

  staffOrderActionBusy = true;
  renderStaffCaseOrderActions();
  try {
    const res = await api(
      `/api/staff/cases/${encodeURIComponent(activeStaffTicket.case_id)}/order-actions`,
      payload,
      { 'Idempotency-Key': makeStaffIdempotencyKey('staff-coa-') }
    );
    staffConsentDraft.noteText = '';
    staffConsentDraft.orderId = '';
    staffConsentDraft.targetVariantId = '';
    staffConsentDraft.variantOptions = {};
    setStaffDeskNotice(res.message || 'Đã tạo yêu cầu theo đồng ý của khách hàng.', 'success');
    await loadStaffCaseOrderActions(activeStaffTicket.case_id, true);
    await refreshStaffTranscript(activeStaffTicket.conversation_id, true, activeStaffTicket.case_id);
    await loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Không thể tạo yêu cầu theo đồng ý của khách: ' + err.message, 'error');
  } finally {
    staffOrderActionBusy = false;
    renderStaffCaseOrderActions();
  }
}

async function submitStaffOrderActionStep(req, slug, extra = {}) {
  if (!req || !req.request_id || staffOrderActionBusy) return;
  staffOrderActionBusy = true;
  renderStaffCaseOrderActions();
  try {
    const payload = { version: Number(req.version) };
    if (extra.inspection_outcome) payload.inspection_outcome = extra.inspection_outcome;
    if (extra.decision) payload.decision = extra.decision;
    if (extra.outcome) payload.outcome = extra.outcome;
    const cleanNote = (extra.note || '').trim();
    if (cleanNote) payload.note = cleanNote;
    const res = await api(
      `/api/order-actions/${encodeURIComponent(req.request_id)}/${slug}`,
      payload,
      { 'Idempotency-Key': makeStaffIdempotencyKey('staff-oa-') }
    );
    setStaffDeskNotice(
      res.customer_notice || res.message || `Đã cập nhật yêu cầu đơn ${req.order_id}.`,
      'success'
    );
    if (activeStaffTicket?.case_id) {
      await loadStaffCaseOrderActions(activeStaffTicket.case_id, false);
      await refreshStaffTranscript(activeStaffTicket.conversation_id, true, activeStaffTicket.case_id);
    }
    await loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Không thể cập nhật yêu cầu đơn hàng: ' + err.message, 'error');
    if (activeStaffTicket?.case_id) {
      await loadStaffCaseOrderActions(activeStaffTicket.case_id, false);
    }
  } finally {
    staffOrderActionBusy = false;
    renderStaffCaseOrderActions();
  }
}

async function submitStaffDeliveryFailureCancel() {
  if (!activeStaffTicket?.case_id || staffOrderActionBusy) return;
  const orderSel = byId('staff-df-order-select');
  const attemptsEl = byId('staff-df-attempts-input');
  const noteEl = byId('staff-df-note-input');
  const orderId = (orderSel?.value || '').trim();
  const attempts = parseInt(String(attemptsEl?.value || ''), 10);
  const note = (noteEl?.value || '').trim();
  if (!orderId) {
    setStaffDeskNotice('Vui lòng chọn đơn hàng pending cần báo giao thất bại.', 'error');
    return;
  }
  if (!Number.isInteger(attempts) || attempts < 1) {
    setStaffDeskNotice('Số lần giao thất bại phải là số nguyên từ 1 trở lên.', 'error');
    return;
  }
  if (!note) {
    setStaffDeskNotice('Vui lòng nhập ghi chú giao thất bại trước khi gửi.', 'error');
    return;
  }
  const effectiveOrders = staffCaseOrders.length > 0 ? staffCaseOrders : staffCaseCustomerOrders;
  const ordObj = effectiveOrders.find(o => o.id === orderId);
  const payload = {
    order_id: orderId,
    delivery_failure_attempts: attempts,
    note
  };
  if (ordObj && Number.isInteger(ordObj.version)) {
    payload.expected_order_version = ordObj.version;
  }
  staffOrderActionBusy = true;
  renderStaffCaseOrderActions();
  try {
    const res = await api(
      `/api/staff/cases/${encodeURIComponent(activeStaffTicket.case_id)}/order-actions`,
      payload,
      { 'Idempotency-Key': makeStaffIdempotencyKey('staff-df-') }
    );
    staffConsentDraft.dfNote = '';
    staffConsentDraft.dfAttempts = '1';
    setStaffDeskNotice(res.message || 'Đã tạo yêu cầu hủy do giao thất bại, chờ Quản lý duyệt.', 'success');
    await loadStaffCaseOrderActions(activeStaffTicket.case_id, true);
    await refreshStaffTranscript(activeStaffTicket.conversation_id, true, activeStaffTicket.case_id);
    await loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Không thể tạo yêu cầu hủy do giao thất bại: ' + err.message, 'error');
  } finally {
    staffOrderActionBusy = false;
    renderStaffCaseOrderActions();
  }
}

let staffCaseAssistTurns = [];
let staffCaseAssistCanAssist = null;
let staffCaseAssistBusy = false;
let activeCaseAssistTurn = null;
let staffCaseAssistLatestText = '';
let staffCaseAssistProgressTimer = null;
let staffCaseAssistProgressToken = 0;
let staffTransferMembers = [];
let staffTransferBusy = false;

const STAFF_CASE_ASSIST_MODE_VI = {
  summary: '📋 Tóm tắt ca',
  draft: '✍️ Soạn nháp',
  ask: '💬 Hỏi đáp'
};

function setStaffCaseAssistProgress(text) {
  const progEl = byId('staff-case-assist-progress');
  const rowEl = byId('staff-case-assist-progress-row');
  const clean = (text || '').trim();
  if (progEl) {
    progEl.hidden = !clean;
    progEl.textContent = clean;
  }
  if (rowEl) {
    rowEl.hidden = !clean && !activeCaseAssistTurn;
  }
}

async function pollStaffCaseAssistProgress() {
  const token = staffCaseAssistProgressToken;
  const caseId = activeStaffTicket?.case_id;
  if (!caseId || !token || !staffCaseAssistBusy) return;
  try {
    const state = await api('/api/staff/cases/' + encodeURIComponent(caseId) + '/assist/progress');
    const status = progressStatus(state);
    if (status && token === staffCaseAssistProgressToken && staffCaseAssistBusy) {
      setStaffCaseAssistProgress(status.title + ' · ' + status.detail);
    }
  } catch (err) {
    // Progress polling is informational only.
  }
}

function startStaffCaseAssistProgressPolling() {
  stopStaffCaseAssistProgressPolling();
  staffCaseAssistProgressToken += 1;
  setStaffCaseAssistProgress('Model đang xử lý… · Đang đọc hội thoại và lập kế hoạch');
  if (typeof setInterval === 'function') {
    staffCaseAssistProgressTimer = setInterval(pollStaffCaseAssistProgress, 2000);
  }
}

function stopStaffCaseAssistProgressPolling() {
  staffCaseAssistProgressToken += 1;
  if (staffCaseAssistProgressTimer && typeof clearInterval === 'function') {
    clearInterval(staffCaseAssistProgressTimer);
  }
  staffCaseAssistProgressTimer = null;
  setStaffCaseAssistProgress('');
}

function canCallerUseCaseAssist(caseObj = activeStaffTicket) {
  if (!caseObj || !caseObj.case_id) return false;
  if (typeof staffCaseAssistCanAssist === 'boolean') return staffCaseAssistCanAssist;
  if (currentSessionRole === 'manager') return true;
  return Boolean(
    caseObj.status === 'in_progress'
    && caseObj.holder
    && currentSessionPrincipalId
    && caseObj.holder === currentSessionPrincipalId
  );
}

function syncStaffCaseAssistControls(caseObj = activeStaffTicket) {
  const btnSummary = byId('btn-case-assist-summary');
  const btnDraft = byId('btn-case-assist-draft');
  const btnAsk = byId('btn-case-assist-ask');
  const inputEl = byId('staff-case-assist-input');
  const btnStop = byId('btn-case-assist-stop');
  const progRow = byId('staff-case-assist-progress-row');
  const progEl = byId('staff-case-assist-progress');
  const btnInsert = byId('btn-case-assist-insert');
  const insertBar = byId('staff-case-assist-insert-bar');
  const hintEl = byId('staff-case-assist-hint');
  const replyInput = byId('staff-reply-input');

  const canAssist = canCallerUseCaseAssist(caseObj);
  const disabled = Boolean(!canAssist || staffCaseAssistBusy);
  let lockTitle = '';
  if (!caseObj || !caseObj.case_id) {
    lockTitle = 'Chọn một ca hỗ trợ ở cột bên trái trước khi dùng Trợ lý ca';
  } else if (staffCaseAssistBusy) {
    lockTitle = 'Trợ lý ca đang xử lý yêu cầu hiện tại';
  } else if (!canAssist) {
    if (caseObj.status === 'resolved') {
      lockTitle = 'Ca hỗ trợ đã đóng; nhân viên không thể gọi thêm Trợ lý ca';
    } else if (!caseObj.holder) {
      lockTitle = 'Bấm “Nhận ca” trước để dùng Trợ lý ca';
    } else {
      lockTitle = 'Ca đang do ' + (caseObj.holder_name || 'nhân viên khác') + ' phụ trách; chỉ người giữ ca hoặc Quản lý mới dùng được Trợ lý ca';
    }
  }
  for (const ctrl of [btnSummary, btnDraft, btnAsk, inputEl]) {
    if (ctrl) {
      ctrl.disabled = disabled;
      ctrl.title = disabled ? lockTitle : '';
    }
  }

  const showStop = Boolean(activeCaseAssistTurn && staffCaseAssistBusy);
  if (btnStop) {
    btnStop.hidden = !showStop;
    btnStop.disabled = !showStop || Boolean(activeCaseAssistTurn?.stopping);
  }
  if (progRow) {
    progRow.hidden = Boolean((!progEl || progEl.hidden) && !showStop);
  }

  if (hintEl) {
    hintEl.classList?.toggle?.('is-locked', !canAssist);
    if (!caseObj || !caseObj.case_id) {
      hintEl.textContent = '⚠️ Chọn một ca hỗ trợ để dùng Trợ lý ca';
    } else if (canAssist) {
      hintEl.textContent = 'Chỉ đọc trong phạm vi ca · lịch sử riêng từng người';
    } else if (caseObj.status === 'resolved') {
      hintEl.textContent = '🔒 Ca đã đóng · chỉ Quản lý mới gọi thêm Trợ lý ca';
    } else if (!caseObj.holder) {
      hintEl.textContent = '🔒 Bấm “Nhận ca” trước để dùng Trợ lý ca (Quản lý dùng được ngay)';
    } else {
      hintEl.textContent = '🔒 Ca đang do ' + (caseObj.holder_name || 'nhân viên khác') + ' giữ · chỉ người giữ ca hoặc Quản lý mới dùng được';
    }
  }

  const hasInsertText = Boolean(staffCaseAssistLatestText);
  if (insertBar) insertBar.hidden = !hasInsertText;
  if (btnInsert) {
    const canWriteReply = Boolean(
      hasInsertText
      && caseObj
      && caseObj.status !== 'resolved'
      && !(replyInput && replyInput.disabled)
    );
    btnInsert.disabled = !canWriteReply || staffCaseAssistBusy;
  }
}

function renderStaffCaseAssist() {
  const outEl = byId('staff-case-assist-output');
  if (!outEl) return;
  outEl.replaceChildren();
  staffCaseAssistLatestText = '';

  if (!activeStaffTicket || !activeStaffTicket.case_id) {
    syncStaffCaseAssistControls(null);
    return;
  }

  if (!Array.isArray(staffCaseAssistTurns) || !staffCaseAssistTurns.length) {
    outEl.append(
      el('p', 'case-ops-empty-hint', 'Chưa có lượt Trợ lý ca nào của bạn trên ca này.')
    );
    syncStaffCaseAssistControls(activeStaffTicket);
    return;
  }

  staffCaseAssistTurns.forEach(turn => {
    if (!turn || typeof turn !== 'object') return;
    const card = el('div', 'staff-case-assist-turn');
    if (turn.mode) card.dataset.mode = turn.mode;

    const head = el('div', 'staff-case-assist-turn-head');
    head.append(el('span', 'case-ops-pill', STAFF_CASE_ASSIST_MODE_VI[turn.mode] || '🤖 Trợ lý ca'));
    const qText = String(turn.question || '').trim();
    if (qText) {
      head.append(el('span', '', qText));
    }
    card.append(head);

    const ansText = String(turn.answer || '').trim();
    if (ansText) {
      card.append(el('p', 'staff-case-assist-answer', ansText));
    }

    const isCancelledTurn = Boolean(turn.cancelled || ansText === 'Bạn đã dừng câu trả lời.');
    const draftText = String(turn.draft_reply || '').trim();
    if (draftText && !isCancelledTurn) {
      const dBox = el('div', 'staff-case-assist-draft-box');
      dBox.append(
        el('strong', '', 'Bản nháp gợi ý gửi khách:'),
        el('p', 'staff-case-assist-draft-text', draftText)
      );
      card.append(dBox);
      staffCaseAssistLatestText = draftText;
    } else if (ansText && !isCancelledTurn) {
      staffCaseAssistLatestText = ansText;
    }

    if (Array.isArray(turn.sources) && turn.sources.length) {
      showSources(card, turn.sources);
    }
    outEl.append(card);
  });

  syncStaffCaseAssistControls(activeStaffTicket);
}

async function loadStaffCaseAssistHistory(caseId) {
  if (!caseId) {
    staffCaseAssistTurns = [];
    staffCaseAssistCanAssist = null;
    renderStaffCaseAssist();
    return;
  }
  try {
    const res = await api('/api/staff/cases/' + encodeURIComponent(caseId) + '/assist');
    if (!activeStaffTicket || activeStaffTicket.case_id !== caseId) return;
    staffCaseAssistTurns = Array.isArray(res?.turns) ? res.turns : [];
    staffCaseAssistCanAssist = typeof res?.can_assist === 'boolean' ? res.can_assist : null;
  } catch (err) {
    if (!activeStaffTicket || activeStaffTicket.case_id !== caseId) return;
    staffCaseAssistTurns = [];
    staffCaseAssistCanAssist = null;
  }
  renderStaffCaseAssist();
}

async function cancelActiveStaffCaseAssist() {
  if (!activeCaseAssistTurn || activeCaseAssistTurn.stopping) return;
  const { caseId, requestId } = activeCaseAssistTurn;
  activeCaseAssistTurn.stopping = true;
  syncStaffCaseAssistControls(activeStaffTicket);
  setStaffCaseAssistProgress('Đang dừng Trợ lý ca…');
  try {
    await api('/api/staff/cases/' + encodeURIComponent(caseId) + '/assist/cancel', { request_id: requestId });
  } catch (err) {
    // Pending /assist request settles the turn state.
  }
}

async function runStaffCaseAssist(mode = 'ask') {
  if (!activeStaffTicket || !activeStaffTicket.case_id || staffCaseAssistBusy) return;
  const caseId = activeStaffTicket.case_id;
  const normMode = ['summary', 'draft', 'ask'].includes(mode) ? mode : 'ask';
  const inputEl = byId('staff-case-assist-input');
  const rawQuestion = (inputEl?.value || '').trim();
  if (normMode === 'ask' && !rawQuestion) {
    setStaffDeskNotice('Vui lòng nhập câu hỏi cho Trợ lý ca trước khi bấm Hỏi.', 'error');
    inputEl?.focus?.();
    return;
  }

  const payload = {
    mode: normMode,
    request_id: makeStaffIdempotencyKey('case-assist-')
  };
  if (rawQuestion) {
    payload.question = rawQuestion;
  }

  staffCaseAssistBusy = true;
  activeCaseAssistTurn = { caseId, requestId: payload.request_id, stopping: false };
  syncStaffCaseAssistControls(activeStaffTicket);
  startStaffCaseAssistProgressPolling();
  try {
    const res = await api('/api/staff/cases/' + encodeURIComponent(caseId) + '/assist', payload);
    if (normMode === 'ask' && inputEl) {
      inputEl.value = '';
    }
    if (activeStaffTicket && activeStaffTicket.case_id === caseId && res) {
      const turnEntry = {
        turn_id: res.turn_id || null,
        request_id: res.request_id || payload.request_id,
        mode: res.mode || normMode,
        question: rawQuestion,
        answer: res.answer || res.message || '',
        draft_reply: res.draft_reply || null,
        cancelled: Boolean(res.cancelled),
        sources: Array.isArray(res.sources) ? res.sources : [],
        created_at: Date.now() / 1000
      };
      if (!res.replayed) {
        staffCaseAssistTurns = [...staffCaseAssistTurns, turnEntry];
      } else if (!staffCaseAssistTurns.some(t => t && t.request_id === turnEntry.request_id)) {
        staffCaseAssistTurns = [...staffCaseAssistTurns, turnEntry];
      }
      renderStaffCaseAssist();
    }
  } catch (err) {
    setStaffDeskNotice('Trợ lý ca chưa phản hồi được: ' + (err.message || 'Lỗi máy chủ'), 'error');
  } finally {
    activeCaseAssistTurn = null;
    stopStaffCaseAssistProgressPolling();
    staffCaseAssistBusy = false;
    syncStaffCaseAssistControls(activeStaffTicket);
  }
}

function insertCaseAssistIntoReply() {
  const text = (staffCaseAssistLatestText || '').trim();
  if (!text) return;
  const replyInput = byId('staff-reply-input');
  if (!replyInput || replyInput.disabled) return;
  // W4-D1: ONLY populate the reply input box for human review — NEVER send automatically.
  replyInput.value = text;
  replyInput.focus?.();
}

function canCallerTransferCase(caseObj = activeStaffTicket) {
  if (!caseObj || !caseObj.case_id) return false;
  if (caseObj.status !== 'in_progress' || !caseObj.holder) return false;
  if (currentSessionRole === 'manager') return true;
  return Boolean(currentSessionPrincipalId && caseObj.holder === currentSessionPrincipalId);
}

function closeStaffCaseTransferBox() {
  const box = byId('staff-case-transfer-box');
  if (box) {
    box.hidden = true;
    if (box.style) box.style.display = 'none';
  }
}

async function openStaffCaseTransferBox() {
  if (!canCallerTransferCase(activeStaffTicket) || staffTransferBusy) return;
  const box = byId('staff-case-transfer-box');
  const sel = byId('staff-transfer-target-select');
  const confirmBtn = byId('btn-confirm-transfer-case');
  if (!box || !sel) return;
  staffTransferBusy = true;
  syncStaffTicketActions(activeStaffTicket, false);
  try {
    const res = await api('/api/staff/members');
    const currentHolder = activeStaffTicket?.holder || '';
    staffTransferMembers = (Array.isArray(res?.members) ? res.members : []).filter(
      m => m && m.principal_id && m.principal_id !== currentHolder
    );
    sel.replaceChildren();
    if (!staffTransferMembers.length) {
      closeStaffCaseTransferBox();
      setStaffDeskNotice('Không có thành viên đang hoạt động nào khác trong cửa hàng để nhận chuyển ca.', 'error');
      return;
    }
    staffTransferMembers.forEach(m => {
      const roleLabel = m.role === 'manager' ? 'Quản lý' : 'Nhân viên';
      const opt = el('option', '', `${m.display_name || m.principal_id} (${roleLabel})`);
      opt.value = m.principal_id;
      sel.append(opt);
    });
    sel.value = staffTransferMembers[0].principal_id;
    if (confirmBtn) confirmBtn.disabled = false;
    box.hidden = false;
    if (box.style) box.style.display = 'flex';
  } catch (err) {
    closeStaffCaseTransferBox();
    setStaffDeskNotice('Không thể tải danh sách nhân viên nhận ca: ' + (err.message || 'Lỗi máy chủ'), 'error');
  } finally {
    staffTransferBusy = false;
    syncStaffTicketActions(activeStaffTicket, activeStaffTicket?.status === 'resolved');
  }
}

async function confirmStaffCaseTransfer() {
  if (!canCallerTransferCase(activeStaffTicket) || staffTransferBusy) return;
  const sel = byId('staff-transfer-target-select');
  const toPrincipalId = (sel?.value || '').trim();
  if (!toPrincipalId) {
    setStaffDeskNotice('Vui lòng chọn thành viên nhận ca trước khi xác nhận.', 'error');
    return;
  }
  const caseId = activeStaffTicket.case_id;
  const expectedVersion = Number(activeStaffTicket.version) || 1;
  staffTransferBusy = true;
  const confirmBtn = byId('btn-confirm-transfer-case');
  if (confirmBtn) confirmBtn.disabled = true;
  try {
    const res = await api(`/api/staff/cases/${encodeURIComponent(caseId)}/transfer`, {
      to_principal_id: toPrincipalId,
      version: expectedVersion
    });
    closeStaffCaseTransferBox();
    if (res && res.case) {
      activeStaffTicket = {
        ...activeStaffTicket,
        status: res.case.status,
        holder: res.case.holder,
        holder_name: res.case.holder_name,
        version: res.case.version,
        customer_silent_seconds: res.case.customer_silent_seconds ?? null
      };
      staffCaseAssistCanAssist = null;
      syncStaffTicketActions(res.case, false);
    }
    setStaffDeskNotice('Đã chuyển ca hỗ trợ cho ' + (res?.case?.holder_name || toPrincipalId) + '.', 'success');
    if (
      conversationId
      && activeStaffTicket?.conversation_id === conversationId
      && res?.notice_turn_id
      && res?.notice_message
      && !renderedStaffTurnIds.has(res.notice_turn_id)
    ) {
      renderedStaffTurnIds.add(res.notice_turn_id);
      caseSystemNoticeMessage(res.notice_message, 'case_transferred');
    }
    await Promise.all([
      loadStaffCaseOrderActions(caseId, false),
      loadStaffCaseAssistHistory(caseId)
    ]);
    if (activeStaffTicket?.conversation_id) {
      await refreshStaffTranscript(activeStaffTicket.conversation_id, true, caseId);
    }
    await loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Không thể chuyển ca: ' + (err.message || 'Lỗi máy chủ'), 'error');
    await loadStaffQueue(true);
  } finally {
    staffTransferBusy = false;
    if (confirmBtn) confirmBtn.disabled = false;
    syncStaffTicketActions(activeStaffTicket, activeStaffTicket?.status === 'resolved');
  }
}

function syncStaffTicketActions(caseObj, readOnly = false) {
  const modEl = byId('staff-case-ops-module');
  const chatActions = byId('staff-chat-actions');
  const chatComposer = byId('staff-chat-composer');
  const statusPill = byId('staff-active-status-pill');
  const btnClaim = byId('btn-claim-ticket');
  const btnOpenTransfer = byId('btn-open-transfer-case');
  const btnResolve = byId('btn-resolve-ticket');
  const btnSend = byId('btn-send-staff-reply');
  const replyInput = byId('staff-reply-input');

  if (!caseObj) {
    syncStaffHeaderSilentBadge(null, true);
    closeStaffCaseTransferBox();
    if (btnOpenTransfer) btnOpenTransfer.hidden = true;
    if (modEl) {
      modEl.hidden = true;
      if (modEl.style) modEl.style.display = 'none';
    }
    if (statusPill) {
      statusPill.hidden = true;
      statusPill.textContent = '';
    }
    if (chatActions) {
      chatActions.hidden = true;
      if (chatActions.style) chatActions.style.display = 'none';
    }
    if (chatComposer) {
      chatComposer.hidden = true;
      if (chatComposer.style) chatComposer.style.display = 'none';
    }
    syncStaffCaseAssistControls(null);
    return;
  }

  if (modEl) {
    modEl.hidden = false;
    if (modEl.style) modEl.style.display = 'flex';
  }

  const isClosed = Boolean(readOnly || caseObj.status === 'resolved');
  syncStaffHeaderSilentBadge(caseObj, isClosed);
  if (statusPill) {
    statusPill.hidden = false;
    statusPill.textContent = isClosed
      ? '✓ Đã đóng (chỉ đọc)'
      : (caseObj.holder
        ? ('🟡 Đang xử lý' + (caseObj.holder_name ? ': ' + caseObj.holder_name : ''))
        : '🔴 Hàng chờ');
  }

  if (isClosed) {
    closeStaffCaseTransferBox();
    if (btnOpenTransfer) btnOpenTransfer.hidden = true;
    if (chatActions) {
      chatActions.hidden = true;
      if (chatActions.style) chatActions.style.display = 'none';
    }
    if (chatComposer) {
      chatComposer.hidden = true;
      if (chatComposer.style) chatComposer.style.display = 'none';
    }
    syncStaffCaseAssistControls(caseObj);
    renderStaffCaseOrderActions();
    return;
  }

  if (chatActions) {
    chatActions.hidden = false;
    if (chatActions.style) chatActions.style.display = 'flex';
  }
  const holder = caseObj ? caseObj.holder : (activeStaffTicket ? activeStaffTicket.holder : null);
  const heldByOther = Boolean(
    holder
    && currentSessionPrincipalId
    && holder !== currentSessionPrincipalId
    && currentSessionRole !== 'manager'
  );
  const canTransfer = canCallerTransferCase(caseObj);
  if (btnOpenTransfer) {
    btnOpenTransfer.hidden = !canTransfer;
    btnOpenTransfer.disabled = !canTransfer || staffTransferBusy;
  }
  if (!canTransfer) {
    closeStaffCaseTransferBox();
  }

  if (btnClaim) {
    if (!holder) {
      btnClaim.textContent = '✋ Nhận ca';
      btnClaim.disabled = false;
    } else if (heldByOther) {
      btnClaim.textContent = '🔒 Đang giữ: ' + (caseObj?.holder_name || holder);
      btnClaim.disabled = true;
    } else {
      btnClaim.textContent = '↩ Trả ca';
      btnClaim.disabled = false;
    }
  }
  if (btnResolve) btnResolve.disabled = heldByOther;
  if (chatComposer) {
    chatComposer.hidden = false;
    if (chatComposer.style) chatComposer.style.display = 'flex';
  }
  if (btnSend) btnSend.disabled = heldByOther || staffReplySending;
  if (replyInput) replyInput.disabled = heldByOther;
  syncStaffCaseAssistControls(caseObj);
  renderStaffCaseOrderActions();
}

function formatStaffActiveCustomerLabel(ticket) {
  if (!ticket) return '—';
  const customerLabel = ticket.customer_name || ticket.customer_id || 'Khách hàng';
  if (!ticket.order_id) return customerLabel;
  return customerLabel + ' · Đơn hàng: ' + formatDualOrderId(ticket.order_id, ticket.external_order_id);
}

async function refreshStaffTranscript(cid, forceScroll = false, caseId = null) {
  const transcriptEl = byId('staff-chat-transcript');
  if (!transcriptEl) return;
  try {
    const endpoint = caseId
      ? ('/api/staff/cases/' + caseId + '/messages')
      : ('/api/staff/conversations/' + cid + '/messages');
    const data = await api(endpoint);
    if (activeStaffTicket && data.case) {
      activeStaffTicket = {
        ...activeStaffTicket,
        case_id: data.case.case_id,
        status: data.case.status,
        holder: data.case.holder,
        holder_name: data.case.holder_name,
        version: data.case.version,
        customer_name: data.conversation?.customer_name || activeStaffTicket.customer_name,
        order_id: data.conversation?.order_id || activeStaffTicket.order_id || null,
        external_order_id: data.conversation?.external_order_id || activeStaffTicket.external_order_id || null,
        customer_silent_seconds: data.case.customer_silent_seconds ?? null,
        handoff_id: data.active_handoff?.handoff_id || activeStaffTicket.handoff_id || null
      };
      const activeCustEl = byId('staff-active-customer');
      if (activeCustEl) {
        activeCustEl.textContent = formatStaffActiveCustomerLabel(activeStaffTicket);
      }
      syncStaffTicketActions(data.case, Boolean(data.read_only));
      const metaEl = byId('staff-active-meta');
      if (metaEl && (data.read_only || data.case.status === 'resolved') && !metaEl.textContent.includes('[Chỉ đọc')) {
        metaEl.textContent = metaEl.textContent + ' · [Chỉ đọc · Ca đã đóng]';
      }
    }
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
      try { raw = typeof t.messages === 'string' ? JSON.parse(t.messages) : (t.messages || []); } catch(e) {}
      let res = {};
      try { res = typeof t.result === 'string' ? JSON.parse(t.result) : (t.result || {}); } catch(e) {}

      if (res.author === 'system_case_notice' || String(t.request_id || '').startsWith('sys-notice-')) {
        const sysText = res.message || (raw[0] && raw[0].content) || '';
        if (sysText) {
          const row = el('div', 'message system case-milestone-notice');
          if (res.milestone) row.dataset.milestone = res.milestone;
          row.append(el('div', 'system-milestone-pill', sysText));
          transcriptEl.append(row);
        }
        return;
      }

      raw.forEach(m => {
        if (m.role === 'user') {
          const row = el('div', 'message user');
          const bubble = el('div', 'bubble bubble-user');
          if (m.attachment) {
            bubble.append(buildChatAttachmentCard(m.attachment, cid));
          }
          if (m.content) bubble.append(document.createTextNode(m.content));
          row.append(
            el('div', 'message-label', 'Khách hàng' + (activeStaffTicket?.customer_name ? ' (' + activeStaffTicket.customer_name + ')' : '')),
            bubble
          );
          transcriptEl.append(row);
        } else if (m.role === 'assistant') {
          const isStaff = m.author === 'staff' || res.author === 'staff';
          const isReminder = res.author === 'system_reminder';
          const isOrderNotice = res.author === 'system_order_action';
          const row = el('div', 'message assistant' + (isStaff ? ' human-message' : ''));
          const label = el('div', 'message-label');
          label.append(el('span', isStaff ? 'human-badge-mini' : 'mini-r', isStaff ? 'NV' : 'R'));
          const senderName = isStaff
            ? (m.staff_name || res.staff_name || 'Chuyên viên CSKH')
            : (isOrderNotice
              ? 'Hệ thống · Yêu cầu đơn hàng'
              : (isReminder ? 'Trợ lý AI · Nhắc tự động' : 'Trợ lý AI'));
          label.append(document.createTextNode(' ' + senderName));
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
  staffCaseOrderActions = [];
  staffCaseCustomerOrders = [];
  staffCaseOrderActionsReadOnly = false;
  staffCaseOpenRequestSig = '';
  staffCaseAssistTurns = [];
  staffCaseAssistCanAssist = null;
  activeCaseAssistTurn = null;
  closeStaffCaseTransferBox();
  stopStaffCaseAssistProgressPolling();
  setStaffDeskNotice('', '');
  document.querySelectorAll('.ticket-card').forEach(c => c.classList.remove('active'));

  const isClosed = ticket.status === 'resolved' || ticket.reason_code === 'resolved';
  byId('staff-active-customer').textContent = formatStaffActiveCustomerLabel(ticket);
  byId('staff-active-meta').textContent = 'Mã ca: ' + (ticket.case_id || ticket.conversation_id)
    + ' · Lý do: ' + (ticket.comment || ticket.reason_code || (isClosed ? (ticket.resolved_reason || 'Đã đóng') : 'Yêu cầu gặp nhân viên'))
    + (isClosed ? ' · [Chỉ đọc · Ca đã đóng]' : '');
  applyStaffCaseOpsCollapseState(readStaffCaseOpsSavedCollapsed());
  renderStaffCaseAssist();
  syncStaffTicketActions(ticket, isClosed);

  const transcriptEl = byId('staff-chat-transcript');
  transcriptEl.dataset.turnsCount = '-1';
  transcriptEl.dataset.hasScrolled = '';
  transcriptEl.innerHTML = '<p class="transcript-placeholder">Đang tải lịch sử hội thoại...</p>';

  await refreshStaffTranscript(ticket.conversation_id, true, ticket.case_id || null);
  if (ticket.case_id) {
    await Promise.all([
      loadStaffCaseOrderActions(ticket.case_id, true),
      loadStaffCaseAssistHistory(ticket.case_id)
    ]);
  }
}

async function claimOrReleaseStaffTicket() {
  if (!activeStaffTicket || !activeStaffTicket.case_id) return;
  const caseId = activeStaffTicket.case_id;
  const action = activeStaffTicket.holder ? 'release' : 'claim';
  try {
    const res = await api(`/api/staff/cases/${caseId}/${action}`, {});
    if (res && res.case) {
      activeStaffTicket = {
        ...activeStaffTicket,
        status: res.case.status,
        holder: res.case.holder,
        holder_name: res.case.holder_name,
        version: res.case.version,
        customer_silent_seconds: res.case.customer_silent_seconds ?? null,
        handoff_id: res.handoff_id || activeStaffTicket.handoff_id || null
      };
      staffCaseAssistCanAssist = null;
      syncStaffTicketActions(res.case, false);
    }
    setStaffDeskNotice(action === 'claim' ? 'Đã nhận ca hỗ trợ.' : 'Đã trả ca hỗ trợ về hàng chờ.', 'success');
    if (conversationId && activeStaffTicket?.conversation_id === conversationId && res?.notice_turn_id && res?.notice_message && !renderedStaffTurnIds.has(res.notice_turn_id)) {
      renderedStaffTurnIds.add(res.notice_turn_id);
      caseSystemNoticeMessage(res.notice_message, action === 'claim' ? 'case_claimed' : 'case_released');
    }
    await Promise.all([
      loadStaffCaseOrderActions(caseId, false),
      loadStaffCaseAssistHistory(caseId)
    ]);
    if (activeStaffTicket?.conversation_id) {
      await refreshStaffTranscript(activeStaffTicket.conversation_id, false, caseId);
    }
    await loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Không thể cập nhật trạng thái nhận ca: ' + err.message, 'error');
    await loadStaffQueue(true);
  }
}

async function sendStaffReply() {
  if (staffReplySending) return;
  if (!activeStaffTicket) {
    setStaffDeskNotice('Vui lòng chọn một ca hỗ trợ ở cột bên trái trước khi gửi phản hồi.', 'error');
    return;
  }
  if (activeStaffTicket.status === 'resolved') {
    setStaffDeskNotice('Ca hỗ trợ đã đóng, không thể gửi thêm phản hồi.', 'error');
    return;
  }
  const input = byId('staff-reply-input');
  const text = (input?.value || '').trim();
  if (!text) {
    setStaffDeskNotice('Vui lòng nhập nội dung phản hồi trước khi bấm gửi.', 'error');
    input?.focus?.();
    return;
  }

  staffReplySending = true;
  const btn = byId('btn-send-staff-reply');
  if (btn) btn.disabled = true;

  try {
    const payload = {
      conversation_id: activeStaffTicket.conversation_id,
      message: text
    };
    if (activeStaffTicket.case_id) payload.case_id = activeStaffTicket.case_id;
    const replyRes = await api('/api/staff/reply', payload);
    if (replyRes && replyRes.turn_id) {
      renderedStaffTurnIds.add(replyRes.turn_id);
    }
    input.value = '';
    activeStaffTicket.customer_silent_seconds = null;
    syncStaffHeaderSilentBadge(activeStaffTicket, false);
    setStaffDeskNotice('Đã gửi phản hồi trực tiếp cho khách hàng.', 'success');

    // Append to staff transcript
    const transcriptEl = byId('staff-chat-transcript');
    transcriptEl.querySelectorAll?.('.transcript-placeholder').forEach(p => p.remove());
    const row = el('div', 'message assistant human-message');
    const label = el('div', 'message-label');
    label.append(el('span', 'human-badge-mini', 'NV'));
    label.append(document.createTextNode(' ' + staffLabel()));
    row.append(label, el('div', 'bubble bubble-staff', text));
    transcriptEl.append(row);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    const prevCount = parseInt(transcriptEl.dataset.turnsCount || '0', 10);
    transcriptEl.dataset.turnsCount = ((prevCount >= 0 ? prevCount : 0) + 1).toString();

    // Instantly display on customer screen if this ticket matches current active conversation!
    if (conversationId && activeStaffTicket.conversation_id === conversationId) {
      humanMessage(text, staffLabel());
      setModelStatus('Đã nhận phản hồi', staffLabel());
    }

    loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Lỗi gửi phản hồi: ' + err.message, 'error');
  } finally {
    staffReplySending = false;
    syncStaffTicketActions(activeStaffTicket, activeStaffTicket?.status === 'resolved');
  }
}

async function resolveStaffTicket() {
  if (!activeStaffTicket || activeStaffTicket.status === 'resolved') return;
  try {
    const payload = {
      conversation_id: activeStaffTicket.conversation_id
    };
    if (activeStaffTicket.case_id) payload.case_id = activeStaffTicket.case_id;
    if (activeStaffTicket.handoff_id) payload.handoff_id = activeStaffTicket.handoff_id;
    const res = await api('/api/staff/resolve', payload);
    if (res && res.case) {
      activeStaffTicket = { ...activeStaffTicket, status: 'resolved', holder: null, holder_name: null };
      staffCaseAssistCanAssist = null;
      syncStaffTicketActions(res.case, true);
    }
    setStaffDeskNotice(
      res?.already_resolved ? 'Ca hỗ trợ đã được đóng trước đó.' : 'Đã hoàn tất và đóng ca hỗ trợ.',
      'success'
    );
    if (activeStaffTicket?.conversation_id) {
      await refreshStaffTranscript(activeStaffTicket.conversation_id, true, activeStaffTicket.case_id || null);
    }
    if (conversationId && activeStaffTicket.conversation_id === conversationId) {
      let resolvedNoticeRow = null;
      if (res?.notice_turn_id && res?.notice_message && !renderedStaffTurnIds.has(res.notice_turn_id)) {
        renderedStaffTurnIds.add(res.notice_turn_id);
        resolvedNoticeRow = caseSystemNoticeMessage(res.notice_message, 'case_resolved');
      }
      setHumanMode(false);
      if (resolvedNoticeRow) {
        appendResumeCaseButton(resolvedNoticeRow, conversationId);
      }
    }
    loadStaffQueue(true);
  } catch (err) {
    setStaffDeskNotice('Lỗi hoàn tất: ' + err.message, 'error');
  }
}

const btnToggleStaffCaseOps = byId('btn-toggle-staff-case-ops');
if (btnToggleStaffCaseOps) btnToggleStaffCaseOps.onclick = () => toggleStaffCaseOps();
applyStaffCaseOpsCollapseState(readStaffCaseOpsSavedCollapsed());

const btnBucketWaiting = byId('staff-bucket-waiting');
if (btnBucketWaiting) btnBucketWaiting.onclick = () => setStaffQueueBucket('waiting');
const btnBucketInProgress = byId('staff-bucket-in-progress');
if (btnBucketInProgress) btnBucketInProgress.onclick = () => setStaffQueueBucket('in_progress');
const btnBucketResolved = byId('staff-bucket-resolved');
if (btnBucketResolved) btnBucketResolved.onclick = () => setStaffQueueBucket('resolved');

const btnClaimTicket = byId('btn-claim-ticket');
if (btnClaimTicket) btnClaimTicket.onclick = () => claimOrReleaseStaffTicket();

const btnOpenTransferCase = byId('btn-open-transfer-case');
if (btnOpenTransferCase) btnOpenTransferCase.onclick = () => openStaffCaseTransferBox();

const btnConfirmTransferCase = byId('btn-confirm-transfer-case');
if (btnConfirmTransferCase) btnConfirmTransferCase.onclick = () => confirmStaffCaseTransfer();

const btnCancelTransferCase = byId('btn-cancel-transfer-case');
if (btnCancelTransferCase) btnCancelTransferCase.onclick = () => closeStaffCaseTransferBox();

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

const btnMaximizeStaffDesk = byId('btn-maximize-staff-desk');
if (btnMaximizeStaffDesk) btnMaximizeStaffDesk.onclick = () => toggleStaffDeskMaximized();
applyStaffDeskMaximizedState(readStaffDeskSavedMaximized());

const btnSendStaffReply = byId('btn-send-staff-reply');
if (btnSendStaffReply) btnSendStaffReply.onclick = () => sendStaffReply();

const staffReplyInput = byId('staff-reply-input');
if (staffReplyInput) {
  staffReplyInput.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      sendStaffReply();
    }
  };
}

const btnResolveTicket = byId('btn-resolve-ticket');
if (btnResolveTicket) btnResolveTicket.onclick = () => resolveStaffTicket();

const btnCaseAssistSummary = byId('btn-case-assist-summary');
if (btnCaseAssistSummary) btnCaseAssistSummary.onclick = () => runStaffCaseAssist('summary');

const btnCaseAssistDraft = byId('btn-case-assist-draft');
if (btnCaseAssistDraft) btnCaseAssistDraft.onclick = () => runStaffCaseAssist('draft');

const btnCaseAssistAsk = byId('btn-case-assist-ask');
if (btnCaseAssistAsk) btnCaseAssistAsk.onclick = () => runStaffCaseAssist('ask');

const btnCaseAssistStop = byId('btn-case-assist-stop');
if (btnCaseAssistStop) btnCaseAssistStop.onclick = () => cancelActiveStaffCaseAssist();

const btnCaseAssistInsert = byId('btn-case-assist-insert');
if (btnCaseAssistInsert) btnCaseAssistInsert.onclick = () => insertCaseAssistIntoReply();

const staffCaseAssistInput = byId('staff-case-assist-input');
if (staffCaseAssistInput) {
  staffCaseAssistInput.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      runStaffCaseAssist('ask');
    }
  };
}

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
if (chatFileInput) chatFileInput.hidden = true;
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

// ==========================================================================
// Store Manager Console Controller & CRUD Logic (RetailOps 2026)
// ==========================================================================
let managerProducts = [];
let editingProductId = null;
let currentManagerTab = 'kpis';
let managerOaGroup = 'all';
let managerOaLimit = 50;
let managerOaOffset = 0;
let managerOaTotal = 0;
let managerOaItems = [];
let managerOaCounts = { needs_manager: 0, in_progress: 0, completed: 0, all: 0 };
const MANAGER_TAB_KEYS = ['kpis', 'products', 'sops', 'orders', 'order-actions', 'audit', 'accounts'];
const MANAGER_BACK_KPI_BTN_IDS = [
  'btn-manager-back-to-kpis',
  'btn-products-back-to-kpis',
  'btn-sops-back-to-kpis',
  'btn-orders-back-to-kpis',
  'btn-order-actions-back-to-kpis',
  'btn-audit-back-to-kpis',
  'btn-accounts-back-to-kpis'
];

const mgrDialog = byId('manager-console-dialog');
const btnOpenMgrHeader = byId('btn-open-manager-console');
const btnOpenMgrSidebar = byId('btn-sidebar-manager-nav');
const btnOpenMgrBanner = byId('btn-panel-manager-banner');
const btnCloseMgr = byId('close-manager-console');
const btnRefreshMgr = byId('refresh-manager-data');

function switchManagerTab(target = 'kpis', options = {}) {
  const normalized = MANAGER_TAB_KEYS.includes(target) ? target : 'kpis';
  if (normalized === 'order-actions' && currentSessionRole !== 'manager') {
    return false;
  }
  if (normalized === 'accounts' && currentSessionRole !== 'manager' && currentSessionRole !== 'platform_admin') {
    setAdminGovernanceMessage('Tài khoản này không có quyền truy cập Quản trị Tài khoản & Quota.', '');
    return false;
  }

  document.querySelectorAll('.manager-nav-tab').forEach(t => {
    const isMatch = t.dataset && t.dataset.tab === normalized;
    t.classList.toggle('active', isMatch);
    t.setAttribute('aria-selected', isMatch ? 'true' : 'false');
    t.tabIndex = isMatch ? 0 : -1;
  });
  document.querySelectorAll('.manager-tab-content').forEach(c => {
    const isMatch = c.id === ('tab-content-' + normalized);
    c.classList.toggle('active', isMatch);
    c.hidden = !isMatch;
  });

  for (const key of MANAGER_TAB_KEYS) {
    const isMatch = key === normalized;
    const btn = byId('tab-btn-' + key);
    if (btn) {
      if (!btn.dataset) btn.dataset = {};
      btn.dataset.tab = key;
      btn.classList.remove('active');
      if (isMatch) btn.classList.add('active');
      btn.setAttribute('aria-selected', isMatch ? 'true' : 'false');
      btn.tabIndex = isMatch ? 0 : -1;
      if (isMatch && options.focusTab && typeof btn.focus === 'function') {
        btn.focus();
      }
    }
    const panel = byId('tab-content-' + key);
    if (panel) {
      panel.classList.remove('active');
      if (isMatch) panel.classList.add('active');
      panel.hidden = !isMatch;
    }
  }

  currentManagerTab = normalized;
  const headerBackBtn = byId('btn-manager-back-to-kpis');
  if (headerBackBtn) {
    headerBackBtn.hidden = (normalized === 'kpis');
  }
  const tabBar = byId('manager-nav-tabs');
  if (tabBar) {
    tabBar.hidden = false;
  }
  if (normalized === 'order-actions' && currentSessionRole === 'manager') {
    loadManagerOrderActions().catch(() => {});
  }
  if (normalized === 'accounts') {
    loadAdminAccounts().catch(() => {});
    loadAdminAuditLog().catch(() => {});
  }
  return true;
}

function handleManagerTabKeydown(e, currentKey) {
  if (!e || !['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
  const visibleKeys = MANAGER_TAB_KEYS.filter(k => {
    const btn = byId('tab-btn-' + k);
    return !btn || !btn.hidden;
  });
  if (!visibleKeys.length) return;
  const idx = Math.max(0, visibleKeys.indexOf(currentKey));
  let nextIdx = idx;
  if (e.key === 'ArrowRight') nextIdx = (idx + 1) % visibleKeys.length;
  else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + visibleKeys.length) % visibleKeys.length;
  else if (e.key === 'Home') nextIdx = 0;
  else if (e.key === 'End') nextIdx = visibleKeys.length - 1;
  if (typeof e.preventDefault === 'function') e.preventDefault();
  switchManagerTab(visibleKeys[nextIdx], { focusTab: true });
}

function openManagerConsole() {
  if (currentSessionRole !== 'manager' && currentSessionRole !== 'platform_admin') {
    setAdminGovernanceMessage('Tài khoản hiện tại không có quyền mở Bảng Quản Trị.', '');
    return;
  }
  if (!mgrDialog || typeof mgrDialog.showModal !== 'function') return;
  syncAdminGovernanceVisibility();
  switchManagerTab('kpis');
  mgrDialog.scrollTop = 0;
  mgrDialog.showModal();
  loadManagerData();
}

if (btnOpenMgrHeader) btnOpenMgrHeader.onclick = openManagerConsole;
if (btnOpenMgrSidebar) btnOpenMgrSidebar.onclick = openManagerConsole;
if (btnOpenMgrBanner) btnOpenMgrBanner.onclick = openManagerConsole;
if (btnCloseMgr && mgrDialog) btnCloseMgr.onclick = () => mgrDialog.close();
if (btnRefreshMgr) btnRefreshMgr.onclick = () => loadManagerData();

// Tabs switcher & persistent return-to-overview actions
for (const key of MANAGER_TAB_KEYS) {
  const btn = byId('tab-btn-' + key);
  if (btn) {
    if (!btn.dataset) btn.dataset = {};
    btn.dataset.tab = key;
    btn.onclick = () => switchManagerTab(key);
    btn.onkeydown = (e) => handleManagerTabKeydown(e, key);
  }
}
document.querySelectorAll('.manager-nav-tab').forEach(tab => {
  const key = tab.dataset?.tab;
  if (key) {
    tab.onclick = () => switchManagerTab(key);
    tab.onkeydown = (e) => handleManagerTabKeydown(e, key);
  }
});
for (const backId of MANAGER_BACK_KPI_BTN_IDS) {
  const backBtn = byId(backId);
  if (backBtn) {
    backBtn.onclick = () => switchManagerTab('kpis', { focusTab: true });
  }
}
switchManagerTab('kpis');

async function openStaffDeskForCase(caseId, fallbackConversationId = '') {
  const targetCaseId = String(caseId || '').trim();
  if (!targetCaseId) return;
  mgrDialog?.close?.();
  await openStaffDesk();
  const buckets = ['in_progress', 'waiting', 'resolved'];
  let matchedBucket = null;
  let matchedTicket = null;
  for (const b of buckets) {
    const found = (staffDeskData[b] || []).find(item => item && item.case_id === targetCaseId);
    if (found) {
      matchedBucket = b;
      matchedTicket = found;
      break;
    }
  }
  if (matchedBucket) {
    staffQueueBucket = matchedBucket;
    renderStaffBucketList();
  }
  if (matchedTicket) {
    await selectStaffTicket(matchedTicket);
  } else {
    await selectStaffTicket({
      case_id: targetCaseId,
      conversation_id: fallbackConversationId || '',
      customer_name: 'Khách hàng',
      status: 'waiting'
    });
  }
}

function syncManagerOrderActionControls() {
  const needsCount = Number(managerOaCounts.needs_manager || 0);
  const badge = byId('manager-oa-needs-badge');
  if (badge) {
    badge.hidden = needsCount <= 0;
    badge.textContent = String(needsCount);
  }
  const filterSpecs = [
    ['btn-manager-oa-filter-needs-manager', 'needs_manager', 'Cần Manager quyết'],
    ['btn-manager-oa-filter-in-progress', 'in_progress', 'Đang xử lý'],
    ['btn-manager-oa-filter-completed', 'completed', 'Đã xong'],
    ['btn-manager-oa-filter-all', 'all', 'Tất cả']
  ];
  for (const [btnId, groupKey, baseLabel] of filterSpecs) {
    const btn = byId(btnId);
    if (btn) {
      const cnt = Number(managerOaCounts[groupKey] || 0);
      btn.textContent = `${baseLabel} (${cnt})`;
      btn.classList?.toggle?.('active', managerOaGroup === groupKey);
    }
  }
  const prevBtn = byId('btn-manager-oa-prev');
  const nextBtn = byId('btn-manager-oa-next');
  const pageInfo = byId('manager-oa-page-info');
  const pageNum = Math.floor(managerOaOffset / Math.max(1, managerOaLimit)) + 1;
  const totalPages = Math.max(1, Math.ceil(managerOaTotal / Math.max(1, managerOaLimit)));
  if (prevBtn) prevBtn.disabled = managerOaOffset <= 0;
  if (nextBtn) nextBtn.disabled = (managerOaOffset + managerOaLimit) >= managerOaTotal;
  if (pageInfo) pageInfo.textContent = `Trang ${pageNum}/${totalPages} (${managerOaTotal} yêu cầu)`;
}

function renderManagerOrderActionsTable() {
  const tbody = byId('manager-order-actions-tbody');
  if (!tbody) return;
  tbody.replaceChildren();
  syncManagerOrderActionControls();

  if (!managerOaItems.length) {
    const tr = el('tr');
    tr.innerHTML = '<td colspan="8" class="manager-table-empty">Chưa có yêu cầu đơn hàng nào trong nhóm lọc này.</td>';
    tbody.append(tr);
    return;
  }

  for (const item of managerOaItems) {
    const tr = el('tr', 'manager-oa-row' + (item.needs_manager ? ' is-needs-manager' : ''));
    tr.dataset.requestId = item.request_id || '';
    tr.dataset.caseId = item.case_id || '';
    tr.title = item.case_id ? `Bấm để mở ca ${item.case_id} trong Bàn làm việc CSKH` : '';
    if (item.case_id) {
      tr.onclick = () => openStaffDeskForCase(item.case_id, item.conversation_id || '');
    }

    const tdReq = el('td');
    const reqCode = el('strong', '', item.request_id || '—');
    tdReq.append(reqCode);

    const tdType = el('td', '', formatStaffOrderActionType(item));
    const tdOrder = el('td', '', formatDualOrderId(item.order_id, item.external_order_id));
    const tdCustomer = el('td', '', item.customer_display_name || 'Khách hàng');
    const tdStatus = el('td', '', STAFF_OA_STATUS_VI[item.status] || item.status || '—');

    const tdRefund = el('td');
    if (item.needs_manager) {
      tdRefund.append(el('span', 'manager-oa-needs-pill', '⚠ Chờ Manager quyết hoàn tiền'));
    } else {
      tdRefund.textContent = formatStaffRefundStatus(item) || '—';
    }

    const tdCase = el('td', '', item.case_id || '—');
    const ts = item.updated_at || item.created_at || 0;
    const tdTime = el('td', '', ts ? new Date(ts * 1000).toLocaleString('vi-VN') : '—');

    tr.append(tdReq, tdType, tdOrder, tdCustomer, tdStatus, tdRefund, tdCase, tdTime);
    tbody.append(tr);
  }
}

async function loadManagerOrderActions() {
  if (currentSessionRole !== 'manager') return;
  const tbody = byId('manager-order-actions-tbody');
  try {
    const qs = `?status_group=${encodeURIComponent(managerOaGroup)}&limit=${managerOaLimit}&offset=${managerOaOffset}`;
    const res = await api('/api/manager/order-actions' + qs);
    managerOaItems = Array.isArray(res?.items) ? res.items : [];
    managerOaTotal = Number(res?.total || 0);
    if (res?.counts && typeof res.counts === 'object') {
      managerOaCounts = {
        needs_manager: Number(res.counts.needs_manager || 0),
        in_progress: Number(res.counts.in_progress || 0),
        completed: Number(res.counts.completed || 0),
        all: Number(res.counts.all || 0)
      };
    }
    renderManagerOrderActionsTable();
  } catch (err) {
    if (tbody) {
      tbody.replaceChildren();
      const tr = el('tr');
      tr.innerHTML = '<td colspan="8" class="manager-table-error">Không thể tải hàng đợi yêu cầu đơn hàng.</td>';
      tbody.append(tr);
    }
  }
}

function setManagerOrderActionsFilter(groupKey) {
  if (!['needs_manager', 'in_progress', 'completed', 'all'].includes(groupKey)) return Promise.resolve();
  managerOaGroup = groupKey;
  managerOaOffset = 0;
  return loadManagerOrderActions();
}

for (const [btnId, groupKey] of [
  ['btn-manager-oa-filter-needs-manager', 'needs_manager'],
  ['btn-manager-oa-filter-in-progress', 'in_progress'],
  ['btn-manager-oa-filter-completed', 'completed'],
  ['btn-manager-oa-filter-all', 'all']
]) {
  const fBtn = byId(btnId);
  if (fBtn) fBtn.onclick = () => setManagerOrderActionsFilter(groupKey);
}
const btnRefreshManagerOa = byId('btn-refresh-manager-order-actions');
if (btnRefreshManagerOa) btnRefreshManagerOa.onclick = () => loadManagerOrderActions();
const btnManagerOaPrev = byId('btn-manager-oa-prev');
if (btnManagerOaPrev) {
  btnManagerOaPrev.onclick = () => {
    if (managerOaOffset <= 0) return;
    managerOaOffset = Math.max(0, managerOaOffset - managerOaLimit);
    loadManagerOrderActions();
  };
}
const btnManagerOaNext = byId('btn-manager-oa-next');
if (btnManagerOaNext) {
  btnManagerOaNext.onclick = () => {
    if ((managerOaOffset + managerOaLimit) >= managerOaTotal) return;
    managerOaOffset += managerOaLimit;
    loadManagerOrderActions();
  };
}

async function loadManagerData() {
  const tasks = [
    loadManagerKPIs(),
    loadManagerProducts(),
    loadManagerOrdersTable(),
    loadManagerAuditTrail()
  ];
  if (currentSessionRole === 'manager') {
    tasks.push(
      loadManagerOrderActions().catch(() => {}),
      loadManagerCompensations(true).catch(() => {})
    );
  }
  if (persistentAccount && (currentSessionRole === 'manager' || currentSessionRole === 'platform_admin')) {
    tasks.push(loadAdminAccounts().catch(() => {}), loadAdminAuditLog().catch(() => {}));
  }
  await Promise.all(tasks);
}

async function loadManagerKPIs() {
  try {
    const kpis = await api('/api/manager/kpis');
    if (byId('kpi-ai-res')) byId('kpi-ai-res').textContent = (kpis.ai_resolution_rate !== null && kpis.ai_resolution_rate !== undefined) ? (kpis.ai_resolution_rate + '%') : '—';
    if (byId('kpi-human-esc')) byId('kpi-human-esc').textContent = (kpis.escalation_rate !== null && kpis.escalation_rate !== undefined) ? (kpis.escalation_rate + '%') : '—';
    if (byId('kpi-csat')) {
      if (kpis.avg_csat !== null && kpis.avg_csat !== undefined) {
        byId('kpi-csat').textContent = kpis.avg_csat + ' / 5.0';
        if (byId('kpi-csat-sub')) byId('kpi-csat-sub').textContent = `${kpis.csat_sample_size || 0} lượt đánh giá thực tế`;
      } else {
        byId('kpi-csat').textContent = 'Chưa có';
        if (byId('kpi-csat-sub')) byId('kpi-csat-sub').textContent = 'Chưa có lượt đánh giá (0 lượt)';
      }
    }
    if (byId('kpi-revenue')) {
      byId('kpi-revenue').textContent = (kpis.total_revenue !== null && kpis.total_revenue !== undefined) ? money(kpis.total_revenue) : '—';
    }
    if (byId('kpi-orders-count')) {
      byId('kpi-orders-count').textContent = (kpis.total_orders !== null && kpis.total_orders !== undefined) ? ((kpis.total_orders || 0) + ' đơn hàng ghi nhận') : '—';
    }

    if (byId('stat-pending-val')) byId('stat-pending-val').textContent = kpis.pending_orders ?? '—';
    if (byId('stat-delivered-val')) byId('stat-delivered-val').textContent = kpis.delivered_orders ?? '—';
    if (byId('stat-cancelled-val')) byId('stat-cancelled-val').textContent = kpis.cancelled_orders ?? '—';
    if (byId('stat-products-val')) byId('stat-products-val').textContent = kpis.active_products ?? '—';
  } catch (e) {
    console.warn('Lỗi tải KPIs:', e);
    if (byId('kpi-ai-res')) byId('kpi-ai-res').textContent = 'Lỗi';
    if (byId('kpi-human-esc')) byId('kpi-human-esc').textContent = 'Lỗi';
    if (byId('kpi-csat')) byId('kpi-csat').textContent = 'Lỗi';
    if (byId('kpi-revenue')) byId('kpi-revenue').textContent = '—';
    if (byId('kpi-orders-count')) byId('kpi-orders-count').textContent = 'Lỗi tải dữ liệu';
    if (byId('stat-pending-val')) byId('stat-pending-val').textContent = '—';
    if (byId('stat-delivered-val')) byId('stat-delivered-val').textContent = '—';
    if (byId('stat-cancelled-val')) byId('stat-cancelled-val').textContent = '—';
    if (byId('stat-products-val')) byId('stat-products-val').textContent = '—';
  }
}

async function loadManagerProducts() {
  try {
    const res = await api('/api/manager/products');
    managerProducts = res.products || [];
    renderManagerProductsTable();
  } catch (e) {
    console.warn('Lỗi tải danh mục sản phẩm:', e);
  }
}

function renderManagerProductsTable() {
  const tbody = byId('manager-products-tbody');
  if (!tbody) return;
  tbody.replaceChildren();

  const searchQ = (byId('product-search-input')?.value || '').toLowerCase().trim();
  const filtered = managerProducts.filter(p =>
    p.id.toLowerCase().includes(searchQ) ||
    p.name.toLowerCase().includes(searchQ) ||
    (p.category && p.category.toLowerCase().includes(searchQ))
  );

  if (!filtered.length) {
    const tr = el('tr');
    tr.innerHTML = '<td colspan="8" class="manager-table-empty">Không tìm thấy sản phẩm nào.</td>';
    tbody.append(tr);
    return;
  }

  for (const p of filtered) {
    const tr = el('tr');
    const isImmutable = ['P-101', 'P-102', 'P-202'].includes(p.id);

    const tdId = el('td');
    tdId.innerHTML = `<strong>${p.id}</strong>` + (isImmutable ? '<br><small class="product-base-tag">[Cơ sở]</small>' : '');

    const tdName = el('td');
    tdName.innerHTML = `<strong>${p.name}</strong><br><small class="product-desc-sub">${p.description ? p.description.slice(0, 45) + '...' : ''}</small>`;

    const tdCat = el('td', '', p.category || 'Chưa phân loại');
    const tdPrice = el('td', '', (p.price !== null && p.price !== undefined) ? money(p.price) : 'Chưa có giá');
    const tdVar = el('td', '', (p.variants && p.variants.length) ? p.variants.join(', ') : 'Chưa phân loại');
    const tdStock = el('td', '', (p.stock !== null && p.stock !== undefined) ? String(p.stock) : 'Chưa kiểm kho');
    const tdWarranty = el('td', '', p.warranty_days ? (p.warranty_days + ' ngày') : 'Chưa cập nhật');

    const tdActions = el('td');
    const btnEdit = el('button', 'btn-action-sm', '✏ Sửa');
    btnEdit.onclick = () => openEditProductModal(p);

    const btnDelete = el('button', 'btn-action-sm danger', '🗑 Xóa');
    btnDelete.onclick = () => deleteProduct(p.id);

    tdActions.append(btnEdit, btnDelete);
    tr.append(tdId, tdName, tdCat, tdPrice, tdVar, tdStock, tdWarranty, tdActions);
    tbody.append(tr);
  }
}

const prodSearchInput = byId('product-search-input');
if (prodSearchInput) {
  prodSearchInput.oninput = () => renderManagerProductsTable();
}

// Product Form Modal (Add / Edit)
const prodModal = byId('product-modal');
const btnOpenAddProd = byId('btn-open-add-product');
const btnCancelProdModal = byId('btn-cancel-product-modal');
const prodForm = byId('product-form');

if (btnOpenAddProd) {
  btnOpenAddProd.onclick = () => {
    editingProductId = null;
    byId('product-modal-title').textContent = '➕ Thêm Sản Phẩm Mới';
    byId('prod-id').value = '';
    byId('prod-id').readOnly = false;
    byId('prod-name').value = '';
    byId('prod-category').value = '';
    byId('prod-price').value = '';
    byId('prod-stock').value = '';
    byId('prod-warranty').value = '';
    byId('prod-variants').value = '';
    byId('prod-desc').value = '';
    if (prodModal && typeof prodModal.showModal === 'function') prodModal.showModal();
  };
}

function openEditProductModal(p) {
  editingProductId = p.id;
  byId('product-modal-title').textContent = '✏ Chỉnh Sửa Sản Phẩm ' + p.id;
  byId('prod-id').value = p.id;
  byId('prod-id').readOnly = true;
  byId('prod-name').value = p.name || '';
  byId('prod-category').value = p.category || '';
  byId('prod-price').value = (p.price !== null && p.price !== undefined) ? p.price : '';
  byId('prod-stock').value = (p.stock !== null && p.stock !== undefined) ? p.stock : '';
  byId('prod-warranty').value = (p.warranty_days !== null && p.warranty_days !== undefined) ? p.warranty_days : '';
  byId('prod-variants').value = (p.variants || []).join(', ');
  byId('prod-desc').value = p.description || '';
  if (prodModal && typeof prodModal.showModal === 'function') prodModal.showModal();
}

if (btnCancelProdModal && prodModal) {
  btnCancelProdModal.onclick = () => prodModal.close();
}

if (prodForm) {
  prodForm.onsubmit = async (e) => {
    e.preventDefault();
    const pid = byId('prod-id').value.trim();
    const priceRaw = parseInt(byId('prod-price').value, 10);
    if (isNaN(priceRaw) || priceRaw < 0) {
      alert('Vui lòng nhập giá niêm yết hợp lệ (số không âm).');
      return;
    }
    const stockStr = byId('prod-stock').value.trim();
    const warrantyStr = byId('prod-warranty').value.trim();
    const catStr = byId('prod-category').value.trim();
    const descStr = byId('prod-desc').value.trim();
    const payload = {
      id: pid,
      name: byId('prod-name').value.trim(),
      price: priceRaw,
      category: catStr || null,
      stock: stockStr ? parseInt(stockStr, 10) : null,
      warranty_days: warrantyStr ? parseInt(warrantyStr, 10) : null,
      variants: byId('prod-variants').value.split(',').map(s => s.trim()).filter(Boolean),
      description: descStr || null
    };

    try {
      if (editingProductId) {
        await api('/api/manager/products/update', payload);
      } else {
        await api('/api/manager/products', payload);
      }
      if (prodModal) prodModal.close();
      await loadManagerProducts();
      await loadManagerKPIs();
      message(`Đã ${editingProductId ? 'cập nhật' : 'thêm'} thành công sản phẩm ${payload.name} (${pid}).`, 'assistant', 'store_data');
    } catch (err) {
      alert('Lỗi lưu sản phẩm: ' + (err.message || 'Không thể lưu.'));
    }
  };
}

async function deleteProduct(pid) {
  if (['P-101', 'P-102', 'P-202'].includes(pid)) {
    alert(`⚠️ Sản phẩm ${pid} là sản phẩm cơ sở của hệ thống phục vụ kiểm thử hồi quy (Regression Test). Bạn không được xóa, chỉ có thể sửa giá hoặc tồn kho!`);
    return;
  }
  if (!confirm(`Bạn có chắc chắn muốn xóa sản phẩm ${pid} khỏi danh mục cửa hàng?`)) return;

  try {
    await api('/api/manager/products/delete', { id: pid });
    await loadManagerProducts();
    await loadManagerKPIs();
    message(`Đã xóa sản phẩm ${pid} khỏi danh mục hàng hóa.`, 'assistant', 'store_data');
  } catch (err) {
    alert('Lỗi xóa sản phẩm: ' + (err.message || 'Không thể xóa.'));
  }
}

// Tab 3: SOP Actions
document.querySelectorAll('.sop-action-btn').forEach(btn => {
  btn.onclick = async () => {
    const sop = btn.dataset.sop;
    const oid = (btn.dataset.order || selected || '').trim();
    if (sop === '1' || sop === '2' || sop === '3' || sop === '4') {
      if (!oid) {
        mgrDialog?.close?.();
        message('Vui lòng chọn một đơn hàng trong danh sách trước khi chạy mô phỏng SOP này.', 'assistant', 'ui_simulation');
        return;
      }
      await lookupOrder(oid);
      const matchedOrder = Array.isArray(orders) ? orders.find(o => o.id === oid || o.external_order_id === oid) : null;
      const displayOid = (matchedOrder && matchedOrder.external_order_id) || oid;
      mgrDialog?.close?.();
      if (sop === '1') {
        message(`[Mô phỏng] SOP 1: Mô phỏng gửi lệnh khiếu nại bưu cục yêu cầu bưu tá giao lại ngay trong ca trước 18:00 cho đơn ${displayOid}. (Chế độ demo giao diện - chưa kết nối backend mutation)`, 'assistant', 'ui_simulation');
      } else if (sop === '2') {
        message(`[Mô phỏng] SOP 2: Mô phỏng duyệt lệnh Đổi mới 1-1 tận nhà cho đơn ${displayOid}. Shipper GHTK sẽ mang sản phẩm mới tới đổi. (Chế độ demo giao diện - chưa kết nối backend mutation)`, 'assistant', 'ui_simulation');
      } else if (sop === '3') {
        message(`[Mô phỏng] SOP 3: Mô phỏng duyệt Đổi size L 2 chiều tận nơi freeship cho đơn ${displayOid}. (Chế độ demo giao diện - chưa kết nối backend mutation)`, 'assistant', 'ui_simulation');
      } else if (sop === '4') {
        message(`[Mô phỏng] SOP 4: Mô phỏng tạo đề xuất bồi thường giao trễ 50.000đ cho đơn hàng ${displayOid}. (Chế độ demo giao diện - chưa kết nối backend mutation)`, 'assistant', 'ui_simulation');
      }
    } else if (sop === '5') {
      mgrDialog?.close?.();
      message(`[Mô phỏng] SOP 5: Mô phỏng tiếp nhận khẩn cấp & kích hoạt Strict Mode. Chuyên viên quản lý ca sẽ liên hệ khách hàng. (Chế độ demo giao diện - chưa kết nối backend mutation)`, 'assistant', 'ui_simulation');
    } else if (sop === '6') {
      mgrDialog?.close?.();
      openStaffDesk();
    }
  };
});

const btnMgrOpenStaffDesk = byId('btn-manager-open-staff-desk');
if (btnMgrOpenStaffDesk) {
  btnMgrOpenStaffDesk.onclick = () => {
    mgrDialog?.close?.();
    openStaffDesk();
  };
}

// Tab 4: Master Orders Table
async function loadManagerOrdersTable() {
  const tbody = byId('manager-orders-tbody');
  if (!tbody) return;
  tbody.replaceChildren();

  const searchQ = (byId('manager-order-search-input')?.value || '').toLowerCase().trim();
  const statusFilter = byId('manager-order-status-filter')?.value || 'all';

  let filtered = orders;
  if (statusFilter !== 'all') {
    filtered = filtered.filter(o => o.status === statusFilter);
  }
  if (searchQ) {
    filtered = filtered.filter(o =>
      o.id.toLowerCase().includes(searchQ) ||
      (o.external_order_id && o.external_order_id.toLowerCase().includes(searchQ)) ||
      ((o.display_name || o.name) && (o.display_name || o.name).toLowerCase().includes(searchQ)) ||
      (o.customer_id && o.customer_id.toLowerCase().includes(searchQ))
    );
  }

  if (!filtered.length) {
    const tr = el('tr');
    const tdEmpty = el('td', 'manager-table-empty', 'Không tìm thấy đơn hàng nào.');
    tdEmpty.colSpan = 8;
    tr.append(tdEmpty);
    tbody.append(tr);
    return;
  }

  for (const o of filtered) {
    const tr = el('tr');
    const tdId = el('td'); tdId.append(el('strong', '', formatDualOrderId(o.id, o.external_order_id)));
    const tdCust = el('td', '', o.customer_id || 'Khách');
    const tdName = el('td', '', o.display_name || o.name);
    const tdVar = el('td', '', o.variant);
    const tdAmount = el('td', '', money(o.amount));
    const tdStatus = el('td');
    tdStatus.append(el('span', 'order-card-badge ' + o.status, statuses[o.status] || o.status));
    const tdVer = el('td', '', 'v' + o.version);

    const tdAction = el('td');
    if (o.status === 'pending') {
      const btnDeliver = el('button', 'btn-action-sm', '✓ Đã giao');
      btnDeliver.onclick = () => updateOrderStatus(o.id, 'delivered');
      const btnCancel = el('button', 'btn-action-sm danger', '✕ Hủy');
      btnCancel.onclick = () => updateOrderStatus(o.id, 'cancelled');
      tdAction.append(btnDeliver, btnCancel);
    } else {
      const btnView = el('button', 'btn-action-sm', '👁 Xem');
      btnView.onclick = () => { mgrDialog?.close?.(); lookupOrder(o.id); };
      tdAction.append(btnView);
    }

    tr.append(tdId, tdCust, tdName, tdVar, tdAmount, tdStatus, tdVer, tdAction);
    tbody.append(tr);
  }
}

const mgrOrderSearch = byId('manager-order-search-input');
const mgrOrderStatus = byId('manager-order-status-filter');
if (mgrOrderSearch) mgrOrderSearch.oninput = () => loadManagerOrdersTable();
if (mgrOrderStatus) mgrOrderStatus.onchange = () => loadManagerOrdersTable();

async function updateOrderStatus(oid, newStatus) {
  if (!confirm(`Xác nhận cập nhật đơn ${oid} sang trạng thái "${statuses[newStatus]}"?`)) return;
  try {
    await api('/api/manager/orders/update-status', { order_id: oid, status: newStatus });
    await refresh();
    await loadManagerOrdersTable();
    await loadManagerKPIs();
    message(`Quản lý đã cập nhật đơn ${oid} sang "${statuses[newStatus]}".`, 'assistant', 'store_data');
  } catch (err) {
    alert('Lỗi cập nhật trạng thái đơn: ' + (err.message || 'Thất bại.'));
  }
}

// Tab 5: Audit Trail
async function loadManagerAuditTrail() {
  const tbody = byId('manager-audit-tbody');
  if (!tbody) return;
  tbody.replaceChildren();

  try {
    const hist = await api('/api/manager/events');
    const events = hist.events || [];
    if (!events.length) {
      const tr = el('tr');
      tr.innerHTML = '<td colspan="5" class="manager-table-empty">Chưa có sự kiện nào.</td>';
      tbody.append(tr);
      return;
    }

    for (const ev of events) {
      const tr = el('tr');
      const tdTime = el('td', '', new Date(ev.created_at * 1000).toLocaleString('vi-VN'));
      const tdCust = el('td', '', ev.customer_id || 'Hệ thống');
      const tdKind = el('td');
      tdKind.innerHTML = `<strong>${eventLabels[ev.kind] || ev.kind}</strong>`;
      const tdOrder = el('td', '', ev.order_id || '—');
      const tdPayload = el('td', '', JSON.stringify(ev.payload || {}).slice(0, 60));

      tr.append(tdTime, tdCust, tdKind, tdOrder, tdPayload);
      tbody.append(tr);
    }
  } catch (e) {
    console.warn('Lỗi tải Audit Trail:', e);
    const tr = el('tr');
    tr.innerHTML = '<td colspan="5" class="manager-table-error">Không thể tải nhật ký quản lý toàn shop. Vui lòng kiểm tra quyền hạn hoặc bấm thử lại.</td>';
    tbody.append(tr);
  }
}

// Search and filter chips in right sidebar
const sideSearchInput = byId('order-search-input');
const sideClearSearchBtn = byId('btn-clear-order-search');
if (sideClearSearchBtn) sideClearSearchBtn.hidden = true;
if (sideSearchInput) {
  sideSearchInput.oninput = () => {
    orderSearchQuery = sideSearchInput.value.trim();
    if (sideClearSearchBtn) {
      sideClearSearchBtn.hidden = !orderSearchQuery;
      if (sideClearSearchBtn.style) sideClearSearchBtn.style.display = orderSearchQuery ? 'inline' : 'none';
    }
    renderOrder();
  };
}
if (sideClearSearchBtn) {
  sideClearSearchBtn.onclick = () => {
    sideSearchInput.value = '';
    orderSearchQuery = '';
    sideClearSearchBtn.hidden = true;
    if (sideClearSearchBtn.style) sideClearSearchBtn.style.display = 'none';
    renderOrder();
  };
}

document.querySelectorAll('.filter-chip').forEach(chip => {
  chip.onclick = () => {
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    managerFilter = chip.dataset.filter;
    renderOrder();
  };
});

// ==========================================================================
// Tab 6: Account & Quota Governance (P5-E ADM1–ADM6)
// ==========================================================================
function setAdminGovernanceMessage(errorText, statusText) {
  const errEl = byId('admin-governance-error');
  if (errEl) {
    errEl.textContent = errorText || '';
    errEl.hidden = !errorText;
  }
  const stEl = byId('admin-governance-status');
  if (stEl) {
    stEl.textContent = statusText || '';
    stEl.hidden = !statusText;
  }
}

function syncAdminGovernanceVisibility() {
  const isStrictMgr = currentSessionRole === 'manager';
  const oaTabBtn = byId('tab-btn-order-actions');
  const oaTabContent = byId('tab-content-order-actions');
  if (oaTabBtn) {
    oaTabBtn.hidden = !isStrictMgr;
    if (oaTabBtn.style) oaTabBtn.style.display = isStrictMgr ? '' : 'none';
  }
  if (oaTabContent) {
    oaTabContent.hidden = !isStrictMgr || currentManagerTab !== 'order-actions';
    if (!isStrictMgr) oaTabContent.classList?.remove?.('active');
  }
  const isAdminOrMgr = currentSessionRole === 'manager' || currentSessionRole === 'platform_admin';
  const tabBtn = byId('tab-btn-accounts');
  const tabContent = byId('tab-content-accounts');
  const detailPanel = byId('admin-account-detail-panel');
  if (tabBtn) {
    tabBtn.hidden = !isAdminOrMgr;
    if (tabBtn.style) tabBtn.style.display = isAdminOrMgr ? '' : 'none';
  }
  if (tabContent) {
    tabContent.hidden = !isAdminOrMgr || currentManagerTab !== 'accounts';
    if (!isAdminOrMgr) tabContent.classList?.remove?.('active');
  }
  if (!isAdminOrMgr && detailPanel) {
    detailPanel.hidden = true;
  }
  const tenantInput = byId('admin-tenant-id-input');
  const scopeBadge = byId('admin-governance-scope-badge');
  if (tenantInput) {
    if (currentSessionRole === 'platform_admin') {
      tenantInput.readOnly = false;
      tenantInput.disabled = false;
      if (!tenantInput.value && currentSessionTenantId) {
        tenantInput.value = currentSessionTenantId;
      }
    } else {
      tenantInput.value = currentSessionTenantId || '';
      tenantInput.readOnly = true;
    }
  }
  if (scopeBadge) {
    scopeBadge.textContent = currentSessionRole === 'platform_admin'
      ? 'SCOPE: PLATFORM_ADMIN (CROSS-TENANT)'
      : `SCOPE: MANAGER (${currentSessionTenantId || 'TENANT'})`;
  }
}

function clearAdminSelectedAccount() {
  selectedAdminMembershipId = null;
  selectedAdminAccount = null;
  const panel = byId('admin-account-detail-panel');
  if (panel) panel.hidden = true;
  const confirmCb = byId('admin-action-confirm');
  if (confirmCb) confirmCb.checked = false;
}

function buildAdminQueryString(extra = {}) {
  const params = new URLSearchParams();
  const tenantVal = (byId('admin-tenant-id-input')?.value || '').trim();
  if (tenantVal) params.set('tenant_id', tenantVal);
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined && v !== null && String(v).trim() !== '') {
      params.set(k, String(v).trim());
    }
  }
  const qs = params.toString();
  return qs ? ('?' + qs) : '';
}

async function loadAdminAccounts() {
  const tbody = byId('admin-accounts-tbody');
  if (!tbody) return;
  if (currentSessionRole !== 'manager' && currentSessionRole !== 'platform_admin') {
    setAdminGovernanceMessage('Tài khoản hiện tại không có quyền quản trị tài khoản.', '');
    return;
  }
  const searchQ = (byId('admin-account-search-input')?.value || '').trim();
  const requestedTenant = (byId('admin-tenant-id-input')?.value || '').trim();
  if (selectedAdminAccount && requestedTenant && selectedAdminAccount.tenant_id !== requestedTenant) {
    clearAdminSelectedAccount();
  }
  try {
    setAdminGovernanceMessage('', '');
    const res = await api('/api/admin/accounts' + buildAdminQueryString({ q: searchQ }));
    adminAccounts = res.accounts || [];
    if (selectedAdminAccount && res.tenant_id && selectedAdminAccount.tenant_id !== res.tenant_id) {
      clearAdminSelectedAccount();
    }
    tbody.replaceChildren();
    if (!adminAccounts.length) {
      const tr = el('tr');
      tr.innerHTML = '<td colspan="8" class="manager-table-empty compact">Không có tài khoản nào trong phạm vi truy vấn.</td>';
      tbody.append(tr);
      return;
    }
    for (const acct of adminAccounts) {
      const tr = el('tr');
      tr.dataset.membershipId = acct.membership_id;
      const q = acct.quota || {};
      const usedVal = q.used ?? q.attempts_used ?? 0;
      const limitVal = q.limit ?? q.effective_daily_limit ?? q.default_limit ?? q.default_daily_limit ?? '—';
      const hasOv = Boolean(q.override || q.has_override);
      const resetUtc = q.next_reset_utc || '00:00 UTC';
      const statusStr = acct.status || (acct.active === false ? 'suspended' : 'active');
      const sessCount = acct.active_session_count ?? acct.active_sessions ?? 0;
      const quotaText = `${usedVal}/${limitVal}` + (hasOv ? ' (override)' : '') + ` · reset: ${resetUtc}`;
      const tdMid = el('td', '', acct.membership_id);
      const tdName = el('td', '', `${acct.display_name || acct.customer_id || acct.principal_id || '—'} (${acct.customer_id || '—'})`);
      const tdRole = el('td', '', acct.role || 'customer');
      const tdTenant = el('td', '', acct.tenant_id || '—');
      const tdStatus = el('td', '', statusStr);
      const tdSessions = el('td', '', String(sessCount));
      const tdQuota = el('td', '', quotaText);
      const tdAct = el('td');
      const btnInspect = el('button', 'btn-action-sm admin-inspect-btn', '⚙ Quản lý');
      btnInspect.type = 'button';
      btnInspect.dataset.membershipId = acct.membership_id;
      btnInspect.onclick = () => inspectAdminAccount(acct.membership_id);
      tdAct.append(btnInspect);
      tr.append(tdMid, tdName, tdRole, tdTenant, tdStatus, tdSessions, tdQuota, tdAct);
      tbody.append(tr);
    }
  } catch (err) {
    setAdminGovernanceMessage(err.message || 'Không thể tải danh sách tài khoản.', '');
    tbody.replaceChildren();
    const tr = el('tr');
    tr.innerHTML = `<td colspan="8" class="manager-table-error compact">${err.message || 'Lỗi tải danh sách tài khoản.'}</td>`;
    tbody.append(tr);
  }
}

async function inspectAdminAccount(membershipId) {
  if (!membershipId) return;
  try {
    setAdminGovernanceMessage('', '');
    const res = await api('/api/admin/accounts/' + encodeURIComponent(membershipId) + buildAdminQueryString());
    const acct = res.account;
    if (!acct) return;
    selectedAdminMembershipId = acct.membership_id;
    selectedAdminAccount = acct;
    const statusStr = acct.status || (acct.active === false ? 'suspended' : 'active');
    const sessCount = acct.active_session_count ?? acct.active_sessions ?? 0;
    const q = acct.quota || {};
    const usedVal = q.used ?? q.attempts_used ?? 0;
    const limitVal = q.limit ?? q.effective_daily_limit ?? q.default_limit ?? q.default_daily_limit ?? '—';
    const hasOv = Boolean(q.override || q.has_override);
    const resetUtc = q.next_reset_utc || '00:00 UTC';
    const ovLimit = q.override?.daily_limit ?? q.override_daily_limit ?? null;
    const ovExpires = q.override?.expires_at ?? q.override_expires_at ?? null;
    const panel = byId('admin-account-detail-panel');
    if (panel) panel.hidden = false;
    if (byId('admin-selected-account-title')) {
      byId('admin-selected-account-title').textContent = `${acct.display_name || acct.customer_id || acct.membership_id} (${acct.membership_id})`;
    }
    if (byId('admin-selected-account-status')) {
      byId('admin-selected-account-status').textContent = statusStr;
    }
    if (byId('admin-selected-account-meta')) {
      byId('admin-selected-account-meta').textContent =
        `Tenant: ${acct.tenant_id} · Vai trò: ${acct.role} · Mã KH: ${acct.customer_id || '—'} · Phiên hoạt động: ${sessCount} · Quota hôm nay: ${usedVal}/${limitVal}${hasOv ? ' (override)' : ''} · Reset UTC: ${resetUtc}`;
    }
    const qLimitInput = byId('admin-quota-limit');
    if (qLimitInput) {
      qLimitInput.value = (ovLimit !== null && ovLimit !== undefined) ? String(ovLimit) : '';
    }
    const qExpInput = byId('admin-quota-expires');
    if (qExpInput) {
      qExpInput.value = ovExpires ? String(Math.floor(ovExpires)) : '';
    }
  } catch (err) {
    setAdminGovernanceMessage(err.message || 'Không thể tải chi tiết tài khoản.', '');
  }
}

async function loadAdminAuditLog(targetMembershipId = null) {
  const tbody = byId('admin-audit-log-tbody');
  if (!tbody) return;
  if (currentSessionRole !== 'manager' && currentSessionRole !== 'platform_admin') {
    return;
  }
  try {
    const res = await api('/api/admin/audit-log' + buildAdminQueryString(
      targetMembershipId ? { membership_id: targetMembershipId } : {}
    ));
    const logs = res.audit_logs || [];
    tbody.replaceChildren();
    if (!logs.length) {
      const tr = el('tr');
      tr.innerHTML = '<td colspan="6" class="manager-table-empty compact">Chưa có bản ghi audit quản trị.</td>';
      tbody.append(tr);
      return;
    }
    for (const item of logs) {
      const tr = el('tr');
      const tdTime = el('td', '', item.created_at ? new Date(item.created_at * 1000).toLocaleString('vi-VN') : '—');
      const tdActor = el('td', '', `${item.actor_principal_id || '—'} (${item.actor_role || '—'})`);
      const tdAction = el('td', '', item.action || '—');
      const tdTarget = el('td', '', item.target_membership_id || '—');
      const tdOutcome = el('td', '', item.outcome || '—');
      const afterObj = item.after || item.after_state;
      const tdReason = el('td', '', `${item.reason || ''} ${afterObj ? JSON.stringify(afterObj) : ''}`.trim());
      tr.append(tdTime, tdActor, tdAction, tdTarget, tdOutcome, tdReason);
      tbody.append(tr);
    }
  } catch (err) {
    setAdminGovernanceMessage(err.message || 'Không thể tải nhật ký audit quản trị.', '');
  }
}

async function submitAdminAccountAction(actionKind) {
  if (currentSessionRole !== 'manager' && currentSessionRole !== 'platform_admin') {
    setAdminGovernanceMessage('Tài khoản hiện tại không có quyền thực hiện thao tác quản trị.', '');
    return;
  }
  if (!selectedAdminMembershipId) {
    setAdminGovernanceMessage('Vui lòng chọn một tài khoản trước khi thực hiện thao tác.', '');
    return;
  }
  const activeTenantInput = (byId('admin-tenant-id-input')?.value || '').trim();
  const expectedTenantId = activeTenantInput || currentSessionTenantId || '';
  if (selectedAdminAccount && selectedAdminAccount.tenant_id && expectedTenantId && selectedAdminAccount.tenant_id !== expectedTenantId) {
    clearAdminSelectedAccount();
    setAdminGovernanceMessage('Tài khoản đang chọn không thuộc cửa hàng (tenant_id) hiện tại. Vui lòng tải lại danh sách và chọn lại tài khoản.', '');
    return;
  }
  const confirmed = Boolean(byId('admin-action-confirm')?.checked);
  if (!confirmed) {
    setAdminGovernanceMessage('Cần tích xác nhận trước khi thực thi thao tác quản trị.', '');
    return;
  }
  const reason = (byId('admin-action-reason')?.value || '').trim();
  if (!reason) {
    setAdminGovernanceMessage('Vui lòng nhập lý do thao tác quản trị.', '');
    return;
  }
  const mid = encodeURIComponent(selectedAdminMembershipId);
  let endpoint = `/api/admin/accounts/${mid}/${actionKind}`;
  let payload = { reason };
  if (actionKind === 'quota') {
    const limitRaw = (byId('admin-quota-limit')?.value ?? '').trim();
    const expiresRaw = (byId('admin-quota-expires')?.value ?? '').trim();
    payload = {
      reason,
      daily_limit: limitRaw === '' ? null : parseInt(limitRaw, 10)
    };
    if (expiresRaw !== '') {
      payload.expires_at = Number(expiresRaw);
    }
  }
  if (expectedTenantId) {
    payload.tenant_id = expectedTenantId;
  } else if (selectedAdminAccount?.tenant_id) {
    payload.tenant_id = selectedAdminAccount.tenant_id;
  }
  try {
    setAdminGovernanceMessage('', '');
    await api(endpoint, payload);
    const confirmCb = byId('admin-action-confirm');
    if (confirmCb) confirmCb.checked = false;
    setAdminGovernanceMessage('', `Đã thực hiện ${actionKind} cho tài khoản ${selectedAdminMembershipId}.`);
    await Promise.all([
      inspectAdminAccount(selectedAdminMembershipId),
      loadAdminAccounts(),
      loadAdminAuditLog(selectedAdminMembershipId)
    ]);
  } catch (err) {
    setAdminGovernanceMessage(err.message || 'Thao tác quản trị thất bại.', '');
    await loadAdminAuditLog(selectedAdminMembershipId).catch(() => {});
  }
}

const adminTenantInputEl = byId('admin-tenant-id-input');
if (adminTenantInputEl) {
  adminTenantInputEl.oninput = () => clearAdminSelectedAccount();
  adminTenantInputEl.onchange = () => clearAdminSelectedAccount();
}
const btnLoadAdminAccounts = byId('btn-load-admin-accounts');
if (btnLoadAdminAccounts) btnLoadAdminAccounts.onclick = () => loadAdminAccounts();
const btnLoadAdminAudit = byId('btn-load-admin-audit-log');
if (btnLoadAdminAudit) btnLoadAdminAudit.onclick = () => loadAdminAuditLog();
const btnAdminSuspend = byId('btn-admin-suspend');
if (btnAdminSuspend) btnAdminSuspend.onclick = () => submitAdminAccountAction('suspend');
const btnAdminReactivate = byId('btn-admin-reactivate');
if (btnAdminReactivate) btnAdminReactivate.onclick = () => submitAdminAccountAction('reactivate');
const btnAdminRevoke = byId('btn-admin-revoke-sessions');
if (btnAdminRevoke) btnAdminRevoke.onclick = () => submitAdminAccountAction('revoke-sessions');
const btnAdminSetQuota = byId('btn-admin-set-quota');
if (btnAdminSetQuota) btnAdminSetQuota.onclick = () => submitAdminAccountAction('quota');
syncAdminGovernanceVisibility();
