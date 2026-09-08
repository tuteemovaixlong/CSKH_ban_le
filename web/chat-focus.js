'use strict';

(() => {
  const desktop = window.matchMedia('(min-width: 981px)');
  const body = document.body;
  const sidebar = document.querySelector('.sidebar');
  const context = document.querySelector('.context-panel');
  const toolbar = document.querySelector('.topbar');
  const controls = document.getElementById('layout-controls') || toolbar;
  if (!sidebar || !context || !toolbar || !controls) return;

  sidebar.id ||= 'left-support-panel';
  context.id ||= 'right-context-panel';

  const icon = pathData => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathData);
    svg.append(path);
    return svg;
  };

  const toggleButton = (id, label, pathData, extraClass = '') => {
    const node = document.createElement('button');
    node.type = 'button';
    node.id = id;
    node.className = 'workspace-toggle ' + extraClass;
    node.dataset.layoutControl = 'true';
    node.append(icon(pathData));
    const text = document.createElement('span'); text.textContent = label; node.append(text);
    return node;
  };

  const panelButtons = {
    left: toggleButton('toggle-left-panel', 'Hỗ trợ', 'M4 5h16M4 12h10M4 19h16', 'panel-layout-toggle'),
    right: toggleButton('toggle-right-panel', 'Đơn hàng', 'M5 4h14v16H5zM9 4v16', 'panel-layout-toggle'),
  };
  const traceButton = toggleButton('toggle-process-trace', 'Quá trình xử lý', 'M8 7h8M6 12h12M9 17h6', 'trace-layout-toggle');
  panelButtons.left.setAttribute('aria-controls', sidebar.id);
  panelButtons.right.setAttribute('aria-controls', context.id);
  traceButton.setAttribute('aria-controls', 'messages');

  const storageKey = side => 'retailops.ui.' + side + 'Collapsed';
  const traceKey = 'retailops.ui.traceVisible';
  const read = key => {
    try { return localStorage.getItem(key); }
    catch (_) { return null; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, String(value)); }
    catch (_) { /* Keep in-memory layout when storage is blocked. */ }
  };
  const preference = {
    left: read(storageKey('left')) === 'true',
    right: read(storageKey('right')) === 'true',
    trace: read(traceKey) === 'true',
  };

  function renderPanels() {
    for (const [side, panel] of [['left', sidebar], ['right', context]]) {
      const collapsed = desktop.matches && preference[side];
      body.classList.toggle(side === 'left' ? 'sidebar-collapsed' : 'context-collapsed', collapsed);
      panel.hidden = collapsed;
      const button = panelButtons[side];
      button.hidden = !desktop.matches;
      button.classList.toggle('is-active', !collapsed);
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', (collapsed ? 'Mở ' : 'Ẩn ') + (side === 'left' ? 'cột hỗ trợ' : 'cột đơn hàng'));
      button.title = button.getAttribute ? button.getAttribute('aria-label') : '';
    }
  }

  function renderTrace() {
    body.classList.toggle('trace-visible', preference.trace);
    traceButton.classList.toggle('is-active', preference.trace);
    traceButton.setAttribute('aria-pressed', String(preference.trace));
    traceButton.setAttribute('aria-label', (preference.trace ? 'Ẩn' : 'Hiện') + ' quá trình xử lý của model');
  }

  function togglePanel(side) {
    if (!desktop.matches) return;
    preference[side] = !preference[side];
    write(storageKey(side), preference[side]);
    renderPanels();
    panelButtons[side].focus();
  }

  function toggleTrace() {
    preference.trace = !preference.trace;
    write(traceKey, preference.trace);
    renderTrace();
    traceButton.focus();
  }

  controls.append(panelButtons.left, traceButton, panelButtons.right);
  panelButtons.left.onclick = () => togglePanel('left');
  panelButtons.right.onclick = () => togglePanel('right');
  traceButton.onclick = toggleTrace;

  desktop.addEventListener('change', () => {
    const focused = document.activeElement;
    renderPanels();
    if (!desktop.matches && (focused === panelButtons.left || focused === panelButtons.right)) {
      const input = document.getElementById('message');
      if (input) input.focus();
    }
  });

  renderPanels();
  renderTrace();
})();

// Persistent-account usage is deliberately separate from the chat implementation.
// It reads aggregate metadata only; no prompt, answer, credential or customer id is exposed.
(() => {
  if (typeof document === 'undefined' || document.body?.dataset?.dataMode !== 'persistent-demo') return;
  const topbar = document.querySelector('.topbar-meta');
  const messages = document.getElementById('messages');
  if (!topbar || !messages) return;

  const number = value => new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 0}).format(value || 0);
  const money = value => typeof value === 'number' && Number.isFinite(value) ? '$' + value.toFixed(6) : 'Chưa xác định';
  const make = (tag, text, cls) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (cls) item.className = cls;
    return item;
  };

  const button = make('button', 'AI usage', 'workspace-toggle usage-account-toggle');
  button.type = 'button';
  button.id = 'account-usage-button';
  button.dataset.layoutControl = 'true';
  button.hidden = true;
  button.setAttribute('aria-haspopup', 'dialog');
  topbar.prepend(button);

  const dialog = document.createElement('dialog');
  dialog.id = 'account-usage-dialog';
  dialog.setAttribute('aria-labelledby', 'account-usage-title');
  const inner = make('div', undefined, 'dialog-inner');
  inner.append(make('span', 'AI USAGE · HÔM NAY UTC', 'small-tag'), make('h2', 'Hạn mức & sử dụng', ''));
  const summary = make('p', 'Đang tải số liệu tài khoản...', 'dialog-note');
  const details = make('div', undefined, 'account-usage-details');
  const scope = make('p', '', 'dialog-note');
  const close = make('button', 'Đóng', 'primary');
  close.type = 'button';
  close.onclick = () => dialog.close();
  inner.append(summary, details, scope, close);
  dialog.append(inner);
  document.body.append(dialog);

  const row = (label, value) => {
    const item = make('div', undefined, 'confirm-detail');
    item.append(make('span', label), make('strong', value));
    return item;
  };

  let latest = null;
  function render(data) {
    latest = data;
    const quota = data.api_quota;
    const totals = data.totals;
    button.hidden = false;
    button.textContent = data.api_configured ? 'AI usage · còn ' + quota.remaining + '/' + quota.limit : 'AI usage';
    summary.textContent = data.api_configured
      ? 'API quota được tính riêng cho tài khoản này. Lượt lỗi hoặc timeout sau khi đã reserve có thể vẫn tiêu quota.'
      : 'API hiện chưa được cấu hình; custom model vẫn ghi nhận token và latency khi trace có dữ liệu.';
    details.replaceChildren(
      row('Lượt API', quota.used + ' / ' + quota.limit + ' · còn ' + quota.remaining),
      row('Prompt tokens', number(totals.prompt_tokens)),
      row('Output tokens', number(totals.generated_tokens)),
      row('Model calls', number(totals.model_calls)),
      row('Latency trung bình', typeof totals.latency_ms.mean === 'number' ? (totals.latency_ms.mean / 1000).toFixed(2) + ' giây' : 'Chưa đo'),
      row('Chi phí API đã biết', money(totals.reported_cost_usd.known_sum)),
      row('Coverage chi phí', (totals.reported_cost_usd.coverage * 100).toFixed(1) + '%'),
      row('Reset quota', new Date(data.reset_at * 1000).toLocaleString('vi-VN') + ' (UTC day)')
    );
    const custom = data.providers.custom, api = data.providers.api;
    scope.textContent = 'Custom: ' + custom.turns + ' lượt · API: ' + api.turns + ' lượt. ' + data.measurement_scope;
  }

  async function refreshUsage() {
    try {
      const response = await fetch('/api/account/usage', {credentials: 'same-origin', cache: 'no-store'});
      if (response.status === 401 || response.status === 404) { button.hidden = true; return; }
      if (!response.ok) return;
      const data = await response.json();
      if (data?.schema === 'retailops-account-usage-v1') render(data);
    } catch (_) { /* Usage must never block customer support UI. */ }
  }

  button.onclick = async () => {
    await refreshUsage();
    if (latest && !dialog.open) dialog.showModal();
  };
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

  let timer = null;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(refreshUsage, 500);
  };
  new MutationObserver(schedule).observe(messages, {childList: true, subtree: true});
  document.addEventListener('visibilitychange', () => { if (!document.hidden) schedule(); });
  schedule();
})();
