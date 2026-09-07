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
