'use strict';

(() => {
  const desktop = window.matchMedia('(min-width: 981px)');
  const body = document.body;
  const sidebar = document.querySelector('.sidebar');
  const context = document.querySelector('.context-panel');
  const toolbar = document.querySelector('.topbar');
  if (!sidebar || !context || !toolbar) return;

  sidebar.id ||= 'left-navigation-panel';
  context.id ||= 'right-context-panel';

  const button = (id, cls, label, direction, panel) => {
    const node = document.createElement('button');
    node.type = 'button';
    node.id = id;
    node.className = cls;
    node.dataset.layoutControl = 'true';
    node.setAttribute('aria-label', label);
    node.setAttribute('aria-controls', panel.id);
    node.title = label;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', direction === 'left' ? 'm15 18-6-6 6-6' : 'm9 18 6-6-6-6');
    svg.append(path);
    node.append(svg);
    return node;
  };
  const panels = {
    left: {
      panel: sidebar, cls: 'sidebar-collapsed',
      collapse: button('collapse-left-panel', 'panel-toggle panel-toggle-left', 'Thu gọn thanh bên trái', 'left', sidebar),
      restore: button('restore-left-panel', 'panel-restore panel-restore-left', 'Mở thanh bên trái', 'right', sidebar),
    },
    right: {
      panel: context, cls: 'context-collapsed',
      collapse: button('collapse-right-panel', 'panel-toggle panel-toggle-right', 'Thu gọn bảng đơn hàng', 'right', context),
      restore: button('restore-right-panel', 'panel-restore panel-restore-right', 'Mở bảng đơn hàng', 'left', context),
    },
  };
  const key = side => 'retailops.ui.' + side + 'Collapsed';
  const read = side => {
    try { return localStorage.getItem(key(side)) === 'true'; }
    catch (_) { return false; }
  };
  // Keep a memory preference too: denied storage must not break a resize.
  const preference = {left: read('left'), right: read('right')};

  function render() {
    for (const [side, item] of Object.entries(panels)) {
      const collapsed = desktop.matches && preference[side];
      body.classList.toggle(item.cls, collapsed);
      // hidden removes collapsed content from keyboard navigation and accessibility tree.
      item.panel.hidden = collapsed;
      item.restore.hidden = !collapsed;
      item.collapse.hidden = !desktop.matches;
      item.collapse.setAttribute('aria-expanded', String(!collapsed));
      item.restore.setAttribute('aria-expanded', String(!collapsed));
    }
  }

  function change(side, collapsed) {
    if (!desktop.matches) return;
    preference[side] = collapsed;
    try { localStorage.setItem(key(side), String(collapsed)); }
    catch (_) { /* Layout remains usable when browser storage is unavailable. */ }
    render();
    (collapsed ? panels[side].restore : panels[side].collapse).focus();
  }

  sidebar.prepend(panels.left.collapse);
  context.prepend(panels.right.collapse);
  // Controls stay inside main so the existing login lock also locks them.
  toolbar.prepend(panels.left.restore);
  toolbar.append(panels.right.restore);
  for (const [side, item] of Object.entries(panels)) {
    item.collapse.onclick = () => change(side, true);
    item.restore.onclick = () => change(side, false);
  }
  desktop.addEventListener('change', () => {
    const focused = document.activeElement;
    render();
    for (const item of Object.values(panels)) {
      if (item.panel.hidden && item.panel.contains(focused)) item.restore.focus();
      else if (!desktop.matches && (focused === item.restore || focused === item.collapse)) {
        const input = document.getElementById('message');
        if (input) input.focus();
      }
    }
  });
  render();
})();
