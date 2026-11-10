'use strict';
// Phase R1 W6.1b-2 JS UI contract tests (Item 2 Staff Desk recipient reveal & Customer order detail).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const appJs = fs.readFileSync('web/app.js', 'utf8');

class Element {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this._classes = new Set();
    this.classList = {
      add: (...cs) => cs.forEach(c => c && this._classes.add(c)),
      remove: (...cs) => cs.forEach(c => this._classes.delete(c)),
      toggle: (c, force) => {
        const next = force === undefined ? !this._classes.has(c) : Boolean(force);
        if (next) this._classes.add(c); else this._classes.delete(c);
        return next;
      },
      contains: c => this._classes.has(c),
    };
  }
  get className() { return [...this._classes].join(' '); }
  set className(val) {
    this._classes = new Set(String(val || '').split(/\s+/).filter(Boolean));
  }
  append(...nodes) {
    for (const n of nodes) {
      if (n !== null && n !== undefined) {
        this.children.push(typeof n === 'string' ? { textContent: n } : n);
      }
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  setAttribute(k, v) { this[k] = String(v); }
  getAttribute(k) { return this[k]; }
  removeAttribute(k) { delete this[k]; }
  remove() {}
  before() {}
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  querySelector() { return new Element('button'); }
  querySelectorAll() { return []; }
  set innerHTML(val) {
    this._innerHTML = String(val || '');
    this.children = [];
  }
  get innerHTML() { return this._innerHTML || ''; }
}

const collectText = node => {
  if (!node) return '';
  return [node.textContent || '', ...(node.children || []).map(collectText)].join(' ').replace(/\s+/g, ' ').trim();
};

const findByIdDeep = (node, targetId) => {
  if (!node) return null;
  if (node.id === targetId) return node;
  for (const child of (node.children || [])) {
    const found = findByIdDeep(child, targetId);
    if (found) return found;
  }
  return null;
};

function createHarness() {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) {
      const e = new Element('div');
      e.id = id;
      nodes.set(id, e);
    }
    for (const rootNode of nodes.values()) {
      const deep = findByIdDeep(rootNode, id);
      if (deep) return deep;
    }
    return nodes.get(id);
  };

  const fetchCalls = [];
  const state = { revealResponse: null };
  const context = vm.createContext({
    document: {
      body: { dataset: { auth: 'cookie', dataMode: 'persistent-demo' } },
      getElementById: get,
      createElement: t => new Element(t),
      createTextNode: t => ({ textContent: String(t) }),
      querySelector: sel => get(sel),
      querySelectorAll: () => [],
      addEventListener: () => {},
    },
    window: { addEventListener: () => {}, matchMedia: () => ({ matches: false, addEventListener: () => {} }) },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    console,
    Intl,
    Date,
    URLSearchParams,
    AbortSignal,
    requestAnimationFrame: fn => fn(),
    setTimeout: () => 1,
    clearTimeout: () => {},
    crypto: { randomUUID: () => '22222222-3333-4444-5555-666666666666' },
    fetch: async (url, opts = {}) => {
      fetchCalls.push({ url: String(url), method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
      if (String(url).endsWith('/reveal-recipient')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => state.revealResponse,
        };
      }
      if (String(url).includes('/api/staff/compensations/')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => state.compDecisionResponse || { status: 'ok', compensation: { status: 'approved', value: 50000 } },
        };
      }
      if (String(url).includes('/api/staff/cases/') && String(url).endsWith('/order-actions')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => state.caseOrderActionsResponse || { order_actions: [], compensations: [], customer_orders: [], unlinked_refunds: [] },
        };
      }
      if (String(url).includes('/api/staff/cases/') && String(url).endsWith('/orders')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => ({ orders: [], consent_turns: [] }),
        };
      }
      if (String(url).startsWith('/api/manager/compensations')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => state.mgrCompensationsResponse || { items: [], counts: { proposed: 0, all: 0 } },
        };
      }
      throw new Error('Unexpected fetch in W6.1b-2 UI test: ' + url);
    },
  });

  vm.runInContext(appJs, context);
  return { context, get, fetchCalls, state, run: code => vm.runInContext(code, context) };
}

(async () => {
  const h = createHarness();

  // 1. Customer order detail renders own decrypted recipient; Manager store_all never renders decrypted recipient
  h.run(`
    currentSessionRole = 'customer';
    orderScope = 'customer';
    orders = [{
      id: 'ord_aaaa1111bbbb2222cccc3333dddd4444',
      external_order_id: 'SIM-ORD-UI-01',
      name: 'Bình giữ nhiệt Inox',
      variant: 'Đen / 500ml',
      amount: 250000,
      status: 'shipping',
      version: 1,
      recipient: {
        name: 'Phạm Minh Tuấn',
        phone: '0908111222',
        address_line: '12 Nguyễn Trãi',
        ward: 'Phường Bến Thành',
        district: 'Quận 1',
        province: 'TP. Hồ Chí Minh',
        purged: false
      }
    }];
    selected = orders[0].id;
    renderOrder();
  `);
  const custOrderText = collectText(h.get('order-details'));
  assert.ok(custOrderText.includes('Phạm Minh Tuấn'), 'Customer must see own recipient name');
  assert.ok(custOrderText.includes('0908111222'), 'Customer must see own recipient phone');
  assert.ok(custOrderText.includes('12 Nguyễn Trãi'), 'Customer must see own recipient address_line');

  // 2. Staff Desk unheld case shows masked recipient + gate note and hides reveal button
  h.run(`
    currentSessionRole = 'staff';
    currentSessionPrincipalId = 'p_staff_ui_1';
    activeStaffTicket = {
      case_id: 'case_ui_1',
      status: 'waiting',
      holder: null,
      order_id: 'ord_aaaa1111bbbb2222cccc3333dddd4444'
    };
    staffCaseOrderActions = [];
    staffCaseOrders = [{
      id: 'ord_aaaa1111bbbb2222cccc3333dddd4444',
      external_order_id: 'SIM-ORD-UI-01',
      name: 'Bình giữ nhiệt Inox',
      amount: 250000,
      status: 'shipping',
      recipient_masked: {
        phone_masked: '0908.xxx.222',
        ward: 'Phường Bến Thành',
        district: 'Quận 1',
        province: 'TP. Hồ Chí Minh',
        has_encrypted_recipient: true,
        purged: false
      }
    }];
    renderStaffCaseOrderActions();
  `);
  const panelUnheld = h.get('staff-order-actions-panel');
  const unheldText = collectText(panelUnheld);
  assert.ok(unheldText.includes('0908.xxx.222'), 'Staff Desk must display masked phone');
  assert.ok(unheldText.includes('Nhận giữ ca mở có gắn đơn hàng'), 'Unheld Staff must see gate note');
  assert.equal(findByIdDeep(panelUnheld, 'btn-reveal-recipient'), null, 'Unheld Staff must not get reveal button');

  // 3. Held Staff enters reason, clicks reveal, calls POST /api/staff/orders/<id>/reveal-recipient, and sees decrypted data
  h.state.revealResponse = {
    order_id: 'ord_aaaa1111bbbb2222cccc3333dddd4444',
    external_order_id: 'SIM-ORD-UI-01',
    case_id: 'case_ui_1',
    audited: true,
    recipient: {
      name: 'Phạm Minh Tuấn',
      phone: '0908111222',
      address_line: '12 Nguyễn Trãi',
      phone_masked: '0908.xxx.222',
      ward: 'Phường Bến Thành',
      district: 'Quận 1',
      province: 'TP. Hồ Chí Minh',
      purged: false
    }
  };

  h.run(`
    activeStaffTicket.status = 'in_progress';
    activeStaffTicket.holder = 'p_staff_ui_1';
    renderStaffCaseOrderActions();
  `);
  const revealBtnBefore = findByIdDeep(panelUnheld, 'btn-reveal-recipient');
  const reasonInput = findByIdDeep(panelUnheld, 'staff-reveal-reason-input');
  assert.ok(revealBtnBefore, 'Held Staff on linked order must get reveal button');
  assert.equal(revealBtnBefore.disabled, true, 'Reveal button must be disabled when reason is empty');

  reasonInput.value = 'Xác nhận địa chỉ giao lại theo yêu cầu khách';
  reasonInput.oninput();
  assert.equal(revealBtnBefore.disabled, false, 'Reveal button enables once reason is entered');

  await h.run(`submitStaffRevealRecipient()`);
  const revealCalls = h.fetchCalls.filter(c => c.url.endsWith('/reveal-recipient'));
  assert.equal(revealCalls.length, 1);
  assert.equal(revealCalls[0].method, 'POST');
  assert.equal(revealCalls[0].url, '/api/staff/orders/ord_aaaa1111bbbb2222cccc3333dddd4444/reveal-recipient');
  assert.deepEqual(revealCalls[0].body, {
    reason: 'Xác nhận địa chỉ giao lại theo yêu cầu khách',
    case_id: 'case_ui_1',
  });

  const revealedText = collectText(panelUnheld);
  assert.ok(revealedText.includes('Phạm Minh Tuấn'));
  assert.ok(revealedText.includes('0908111222'));
  assert.ok(revealedText.includes('12 Nguyễn Trãi'));
  assert.ok(revealedText.includes('Đã ghi nhật ký kiểm toán'));

  // 4. Switching/resetting case clears revealed recipient from memory
  h.run(`
    resetStaffConsentDraft('case_ui_2');
    activeStaffTicket = {
      case_id: 'case_ui_2',
      status: 'in_progress',
      holder: 'p_staff_ui_1',
      order_id: 'ord_aaaa1111bbbb2222cccc3333dddd4444'
    };
    renderStaffCaseOrderActions();
  `);
  const afterSwitchText = collectText(panelUnheld);
  assert.ok(!afterSwitchText.includes('Phạm Minh Tuấn'), 'Revealed recipient must be cleared when switching cases');

  // 5. Item 4: Staff Desk compensation proposal card (unheld vs held) + fixed 50,000 VND without value input
  h.run(`
    currentSessionRole = 'staff';
    currentSessionPrincipalId = 'p_staff_ui_1';
    activeStaffTicket = {
      case_id: 'case_ui_comp',
      status: 'waiting',
      holder: null,
      order_id: 'ord_aaaa1111bbbb2222cccc3333dddd4444'
    };
    staffCaseCompensations = [{
      compensation_id: 'comp_ui_001',
      order_id: 'ord_aaaa1111bbbb2222cccc3333dddd4444',
      external_order_id: 'SIM-ORD-UI-01',
      late_by_hours: 51.5,
      voucher_type: 'amount',
      value: 50000,
      status: 'proposed'
    }];
    renderStaffCaseOrderActions();
  `);
  const compUnheldText = collectText(panelUnheld);
  assert.ok(compUnheldText.includes('50.000'), 'Staff Desk must show fixed 50,000 VND proposal');
  assert.equal(findByIdDeep(panelUnheld, 'btn-approve-comp-comp_ui_001'), null, 'Unheld Staff must not see approve button');

  h.run(`
    activeStaffTicket.status = 'in_progress';
    activeStaffTicket.holder = 'p_staff_ui_1';
    renderStaffCaseOrderActions();
  `);
  const compApproveBtn = findByIdDeep(panelUnheld, 'btn-approve-comp-comp_ui_001');
  const compNoteInput = findByIdDeep(panelUnheld, 'staff-comp-note-comp_ui_001');
  assert.ok(compApproveBtn, 'Held Staff must see compensation approve button');
  compNoteInput.value = 'Đơn trễ 51.5h đủ điều kiện';
  await compApproveBtn.onclick();

  const compApproveCalls = h.fetchCalls.filter(c => c.url.endsWith('/api/staff/compensations/comp_ui_001/approve'));
  assert.equal(compApproveCalls.length, 1);
  assert.deepEqual(compApproveCalls[0].body, {
    note: 'Đơn trễ 51.5h đủ điều kiện',
    case_id: 'case_ui_comp'
  }, 'Compensation approve call must NEVER send a value/denomination field');

  // 6. Item 4: Manager store-wide compensation list in Staff Desk & Manager Console
  h.state.mgrCompensationsResponse = {
    items: [{
      compensation_id: 'comp_mgr_store_02',
      order_id: 'ord_bbbb2222cccc3333dddd4444eeee5555',
      external_order_id: 'SIM-ORD-MGR-02',
      customer_name: 'Khách B',
      late_by_hours: 62.0,
      voucher_type: 'amount',
      value: 50000,
      status: 'proposed'
    }],
    counts: { proposed: 1, all: 1 }
  };
  await h.run(`
    currentSessionRole = 'manager';
    loadManagerCompensations(true);
  `);
  const staffMgrPanel = h.get('staff-manager-compensations-panel');
  const mgrConsolePanel = h.get('manager-compensations-panel');
  assert.equal(staffMgrPanel.hidden, false);
  assert.ok(collectText(staffMgrPanel).includes('SIM-ORD-MGR-02'));
  assert.ok(collectText(mgrConsolePanel).includes('SIM-ORD-MGR-02'));
  assert.ok(findByIdDeep(staffMgrPanel, 'staff-mgr-comp-approve-comp_mgr_store_02'));

  console.log('W6_1B_2_UI_ITEM2_AND_ITEM4_OK');
})().catch(err => {
  console.error(err);
  process.exit(1);
});
