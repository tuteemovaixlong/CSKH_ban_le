'use strict';
// Execute the real full-screen workspace controller without a DOM library or network calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/chat-focus.js', 'utf8');

function fixture(saved = {}, blocked = false) {
  const byId = new Map();
  let document;
  class Element {
    constructor() {
      this.children = []; this.attrs = {}; this.dataset = {}; this.hidden = false;
      this.className = ''; this.textContent = ''; this.title = '';
      const values = new Set();
      this.classList = {
        toggle(key, enabled) { enabled ? values.add(key) : values.delete(key); },
        contains(key) { return values.has(key); },
      };
    }
    set id(value) { this._id = value; byId.set(value, this); }
    get id() { return this._id || ''; }
    setAttribute(key, value) { this.attrs[key] = value; }
    getAttribute(key) { return this.attrs[key]; }
    append(...items) { this.children.push(...items); }
    contains(item) { return this === item || this.children.some(child => child.contains && child.contains(item)); }
    focus() { document.activeElement = this; }
  }
  const body = new Element(), sidebar = new Element(), context = new Element(), toolbar = new Element();
  sidebar.id = 'left-support-panel'; context.id = 'right-context-panel';
  const controls = new Element(); controls.id = 'layout-controls';
  const input = new Element(); input.id = 'message';
  document = {
    body, activeElement: null,
    querySelector: name => ({'.sidebar': sidebar, '.context-panel': context, '.topbar': toolbar}[name]),
    createElement: () => new Element(), createElementNS: () => new Element(),
    getElementById: id => byId.get(id),
  };
  const media = {
    matches: true,
    addEventListener(type, callback) { assert.equal(type, 'change'); this.change = callback; },
    resize(wide) { this.matches = wide; this.change(); },
  };
  const storage = {...saved};
  vm.runInNewContext(source, {
    window: {matchMedia: () => media}, document,
    localStorage: {
      getItem(key) { if (blocked) throw Error('denied'); return storage[key] ?? null; },
      setItem(key, value) { if (blocked) throw Error('denied'); storage[key] = value; },
    },
  });
  return {document, body, sidebar, context, toolbar, controls, input, media, storage, get: id => byId.get(id)};
}

const basic = fixture();
for (const side of ['left', 'right']) {
  const panel = side === 'left' ? basic.sidebar : basic.context;
  const button = basic.get('toggle-' + side + '-panel');
  assert.ok(basic.controls.children.includes(button), 'panel toggle stays in the login-locked main toolbar');
  assert.equal(button.dataset.layoutControl, 'true');
  assert.equal(button.attrs['aria-controls'], panel.id);
  assert.equal(button.attrs['aria-expanded'], 'true');
  assert.equal(panel.hidden, false);
  button.onclick();
  assert.equal(panel.hidden, true);
  assert.equal(button.attrs['aria-expanded'], 'false');
  assert.equal(basic.document.activeElement, button);
  assert.equal(basic.storage['retailops.ui.' + side + 'Collapsed'], 'true');
  button.onclick();
  assert.equal(panel.hidden, false);
  assert.equal(button.attrs['aria-expanded'], 'true');
}

const trace = basic.get('toggle-process-trace');
assert.equal(trace.dataset.layoutControl, 'true');
assert.equal(trace.attrs['aria-pressed'], 'false', 'process trace is hidden by default');
assert.equal(basic.body.classList.contains('trace-visible'), false);
trace.onclick();
assert.equal(trace.attrs['aria-pressed'], 'true');
assert.equal(basic.body.classList.contains('trace-visible'), true);
assert.equal(basic.storage['retailops.ui.traceVisible'], 'true');

const saved = {
  'retailops.ui.leftCollapsed': 'true',
  'retailops.ui.rightCollapsed': 'true',
  'retailops.ui.traceVisible': 'true',
};
const restored = fixture(saved);
assert.ok(restored.sidebar.hidden && restored.context.hidden);
assert.equal(restored.get('toggle-process-trace').attrs['aria-pressed'], 'true');
restored.media.resize(false);
assert.ok(!restored.sidebar.hidden && !restored.context.hidden, 'mobile must always render both content panels');
assert.ok(restored.get('toggle-left-panel').hidden && restored.get('toggle-right-panel').hidden);
restored.media.resize(true);
assert.ok(restored.sidebar.hidden && restored.context.hidden, 'desktop restores the saved workspace preference');

const denied = fixture({}, true);
denied.get('toggle-left-panel').onclick();
denied.get('toggle-process-trace').onclick();
denied.media.resize(false); denied.media.resize(true);
assert.equal(denied.sidebar.hidden, true, 'memory preference survives when localStorage is denied');
assert.equal(denied.body.classList.contains('trace-visible'), true);

const focused = fixture();
const right = focused.get('toggle-right-panel');
right.focus(); focused.media.resize(false);
assert.equal(focused.document.activeElement, focused.input, 'hidden desktop panel controls hand focus to chat on mobile');

console.log('CHAT_FOCUS_WORKSPACE_OK (full-screen panel toggles, trace visibility, responsive state, storage)');
