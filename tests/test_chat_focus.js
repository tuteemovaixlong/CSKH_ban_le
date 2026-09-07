'use strict';
// Execute the real panel controller without a DOM library or network calls.
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
      const values = new Set();
      this.classList = {
        toggle(key, enabled) { enabled ? values.add(key) : values.delete(key); },
        contains(key) { return values.has(key); },
      };
    }
    set id(value) { this._id = value; byId.set(value, this); }
    get id() { return this._id || ''; }
    setAttribute(key, value) { this.attrs[key] = value; }
    append(...items) { this.children.push(...items); }
    prepend(...items) { this.children.unshift(...items); }
    contains(item) { return this === item || this.children.some(child => child.contains(item)); }
    focus() { document.activeElement = this; }
  }
  const body = new Element(), sidebar = new Element(), context = new Element(), toolbar = new Element();
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
  return {document, body, sidebar, context, toolbar, input, media, storage, get: id => byId.get(id)};
}

for (const side of ['left', 'right']) {
  const f = fixture(), panel = side === 'left' ? f.sidebar : f.context;
  const collapse = f.get('collapse-' + side + '-panel');
  const restore = f.get('restore-' + side + '-panel');
  assert.equal(restore.hidden, true);
  assert.equal(collapse.attrs['aria-controls'], panel.id);
  assert.equal(collapse.dataset.layoutControl, 'true');
  assert.ok(f.toolbar.children.includes(restore), 'restore stays inside login-locked main');
  collapse.onclick();
  assert.equal(panel.hidden, true);
  assert.equal(restore.hidden, false);
  assert.equal(restore.attrs['aria-expanded'], 'false');
  assert.equal(f.document.activeElement, restore);
  assert.equal(f.storage['retailops.ui.' + side + 'Collapsed'], 'true');
  restore.onclick();
  assert.equal(panel.hidden, false);
  assert.equal(restore.hidden, true);
  assert.equal(collapse.attrs['aria-expanded'], 'true');
  assert.equal(f.document.activeElement, collapse);
}
const saved = {'retailops.ui.leftCollapsed': 'true', 'retailops.ui.rightCollapsed': 'true'};
const restored = fixture(saved);
assert.ok(restored.sidebar.hidden && restored.context.hidden);
restored.media.resize(false);
assert.ok(!restored.sidebar.hidden && !restored.context.hidden, 'mobile must not inherit hidden panels');
assert.equal(restored.get('restore-right-panel').attrs['aria-expanded'], 'true');
restored.media.resize(true);
assert.ok(restored.sidebar.hidden && restored.context.hidden);
const denied = fixture({}, true);
denied.get('collapse-left-panel').onclick();
denied.media.resize(false);
denied.media.resize(true);
assert.equal(denied.sidebar.hidden, true);
const focused = fixture();
focused.get('collapse-right-panel').onclick();
focused.media.resize(false);
assert.equal(focused.document.activeElement, focused.input);
console.log('CHAT_FOCUS_PANELS_OK (collapse, restore, focus, responsive state, storage)');
