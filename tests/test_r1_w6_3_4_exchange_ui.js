'use strict';
// Execute both real forms in a DOM stub; no browser, library or network required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function harness(canTarget) {
  const nodes = new Map();
  const all = [];
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
      this.value = ''; this.textContent = ''; this.disabled = false;
      this.classList = {add() {}, remove() {}, toggle() {}, contains() { return false; }};
      all.push(this);
    }
    set id(v) { this._id = v; nodes.set(v, this); }
    get id() { return this._id; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
    setAttribute(k, v) { this[k] = v; }
    getAttribute(k) { return this[k]; }
    addEventListener() {}
    querySelector() { return new Element('button'); }
    querySelectorAll() { return []; }
    focus() {}
    remove() {}
    before() {}
    showModal() {}
    close() {}
    scrollIntoView() {}
    set innerHTML(v) { this.children = []; }
  }
  const get = id => nodes.get(id) || (() => { const e = new Element(); e.id = id; return e; })();
  const order = {id: 'O-test', status: 'delivered', version: 1, name: 'Áo',
    eligibility: {within_return_window: true, within_size_exchange_window: true, within_warranty: true}};
  const variants = [
    {id: 'black', label: 'Đen · Size L', is_current: true, can_target: canTarget, stock_status: 'in_stock'},
    {id: 'white', label: 'Trắng · Size L', is_current: canTarget, can_target: true, stock_status: 'in_stock'},
  ];
  const context = vm.createContext({
    document: {body: {dataset: {auth: 'cookie', dataMode: 'persistent-demo'}}, getElementById: get,
      createElement: tag => new Element(tag), createTextNode: text => ({textContent: text}),
      querySelector: get, querySelectorAll: () => [], addEventListener() {}},
    window: {addEventListener() {}, matchMedia: () => ({matches: false, addEventListener() {}})},
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    console, Intl, Date, URLSearchParams, AbortSignal,
    setTimeout: () => 1, clearTimeout() {}, requestAnimationFrame: fn => fn(),
    crypto: {randomUUID: () => 'synthetic-ui-test'},
    fetch: async url => {
      assert.ok(String(url).endsWith('/focus') || String(url).endsWith('/exchange-options'), String(url));
      return {ok: true, headers: {get: () => 'application/json'}, json: async () =>
        String(url).endsWith('/focus') ? {order, context: {}} : {variants}};
    },
  });
  vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
  context.fixtureOrder = order;
  vm.runInContext(`
    canCancel = true; conversationId = 'synthetic';
    reasonCatalog = {reasons: [{code: 'change_of_mind', label: 'Đổi ý', applies_to: ['exchange'], requires_text: false}]};
    loadReasonCatalog = async () => true; showContext = () => {}; refresh = async () => {};
    message = () => document.createElement('div');
    currentSessionRole = 'manager'; currentSessionPrincipalId = 'mgr-test';
    activeStaffTicket = {case_id: 'case-test', status: 'in_progress', holder: 'mgr-test'};
    staffCaseOrders = [fixtureOrder];
    staffCaseConsentTurns = [{turn_id: 1, text: 'Đồng ý đổi'}];
    resetStaffConsentDraft('case-test');
    staffConsentDraft.orderId = 'O-test'; staffConsentDraft.typeKey = 'exchange:other_variant';
    staffConsentDraft.targetVariantId = 'black';
  `, context);
  return {get, all, run: code => vm.runInContext(code, context)};
}

for (const canTarget of [true, false]) {
  test(`customer held target selectable=${canTarget}`, async () => {
    const customer = harness(canTarget);
    await customer.run("chooseReason('O-test', 'exchange', 'other_variant', 'black')");
    const select = customer.all.find(e => e.className === 'order-action-target-select');
    assert.ok(select, 'customer target selector renders');
    const black = select.children.find(e => e.value === 'black');
    assert.equal(black.disabled, !canTarget, 'customer held target eligibility');
    assert.ok(black.textContent.includes('(đang giữ)'));
    assert.equal(select.value, canTarget ? 'black' : '', 'customer preselection respects eligibility');
  });
  test(`staff held target selectable=${canTarget}`, async () => {
    const staff = harness(canTarget);
    staff.run('renderStaffCaseOrderActions()');
    // Rendering starts an asynchronous target load; explicitly await its change handler.
    await staff.get('staff-consent-type-select').onchange();
    const staffSelect = staff.get('staff-consent-target-select');
    const staffBlack = staffSelect.children.find(e => e.value === 'black');
    assert.ok(staffBlack, 'staff target selector renders');
    assert.equal(staffBlack.disabled, !canTarget, 'staff held target eligibility');
    assert.ok(staffBlack.textContent.includes('(đang giữ)'));
    assert.equal(staffSelect.value, canTarget ? 'black' : '', 'staff preselection respects eligibility');
  });
}
