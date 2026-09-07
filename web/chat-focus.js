'use strict';

(() => {
  const desktopQuery = window.matchMedia('(min-width: 981px)');
  const body = document.body;

  const chevron = direction => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', direction === 'left' ? 'm15 18-6-6 6-6' : 'm9 18 6-6-6-6');
    svg.append(path);
    return svg;
  };

  const makeButton = (id, cls, label, direction) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = id;
    button.className = cls;
    button.setAttribute('aria-label', label);
    button.title = label;
    button.append(chevron(direction));
    return button;
  };

  const sidebar = document.querySelector('.sidebar');
  const contextPanel = document.querySelector('.context-panel');
  if (!sidebar || !contextPanel) return;

  const collapseLeft = makeButton('collapse-left-panel', 'panel-toggle panel-toggle-left', 'Thu gọn thanh bên trái', 'left');
  const collapseRight = makeButton('collapse-right-panel', 'panel-toggle panel-toggle-right', 'Thu gọn bảng đơn hàng', 'right');
  const restoreLeft = makeButton('restore-left-panel', 'panel-restore panel-restore-left', 'Mở thanh bên trái', 'right');
  const restoreRight = makeButton('restore-right-panel', 'panel-restore panel-restore-right', 'Mở bảng đơn hàng', 'left');

  collapseLeft.setAttribute('aria-controls', 'left-navigation-panel');
  collapseRight.setAttribute('aria-controls', 'right-context-panel');
  restoreLeft.setAttribute('aria-controls', 'left-navigation-panel');
  restoreRight.setAttribute('aria-controls', 'right-context-panel');
  sidebar.id ||= 'left-navigation-panel';
  contextPanel.id ||= 'right-context-panel';

  sidebar.prepend(collapseLeft);
  contextPanel.prepend(collapseRight);
  body.append(restoreLeft, restoreRight);

  const readPreference = key => {
    try { return localStorage.getItem(key) === 'true'; }
    catch (_) { return false; }
  };

  const writePreference = (key, value) => {
    try { localStorage.setItem(key, String(value)); }
    catch (_) { /* Private browsing can deny storage; layout still works for this page. */ }
  };

  const setCollapsed = (side, collapsed, persist = true) => {
    const isLeft = side === 'left';
    const cls = isLeft ? 'sidebar-collapsed' : 'context-collapsed';
    const collapseButton = isLeft ? collapseLeft : collapseRight;
    const restoreButton = isLeft ? restoreLeft : restoreRight;
    body.classList.toggle(cls, collapsed && desktopQuery.matches);
    collapseButton.setAttribute('aria-expanded', String(!collapsed));
    restoreButton.setAttribute('aria-expanded', String(!collapsed));
    if (persist) writePreference('retailops.ui.' + side + 'Collapsed', collapsed);
  };

  collapseLeft.onclick = () => setCollapsed('left', true);
  collapseRight.onclick = () => setCollapsed('right', true);
  restoreLeft.onclick = () => setCollapsed('left', false);
  restoreRight.onclick = () => setCollapsed('right', false);

  const applyResponsiveState = () => {
    if (!desktopQuery.matches) {
      body.classList.remove('sidebar-collapsed', 'context-collapsed');
      return;
    }
    setCollapsed('left', readPreference('retailops.ui.leftCollapsed'), false);
    setCollapsed('right', readPreference('retailops.ui.rightCollapsed'), false);
  };

  desktopQuery.addEventListener?.('change', applyResponsiveState);
  applyResponsiveState();

  const compactStatus = () => {
    const status = document.querySelector('.model-status');
    if (!status) return;
    const strong = status.querySelector('strong');
    const detail = status.querySelector('div span');
    if (!strong || !detail) return;
    if (strong.textContent.trim() === 'Model vừa phản hồi') {
      strong.textContent = 'Đã phản hồi';
      const selected = document.querySelector('#model-provider option:checked');
      detail.textContent = selected?.textContent?.replace(' — Chưa cấu hình', '') || 'Model đã chọn';
    }
  };

  const compactTraceLabels = root => {
    root.querySelectorAll?.('.agent-trace summary').forEach(summary => {
      if (summary.dataset.compactLabel === 'true') return;
      const saved = /Kết quả đã lưu/i.test(summary.textContent);
      summary.textContent = 'Công cụ & thời gian' + (saved ? ' · Kết quả đã lưu' : '');
      summary.dataset.compactLabel = 'true';
    });
  };

  const status = document.querySelector('.model-status');
  if (status) new MutationObserver(compactStatus).observe(status, {subtree: true, childList: true, characterData: true});
  const messages = document.getElementById('messages');
  if (messages) {
    compactTraceLabels(messages);
    new MutationObserver(records => {
      for (const record of records) record.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) compactTraceLabels(node);
      });
    }).observe(messages, {childList: true, subtree: true});
  }
  compactStatus();
})();
