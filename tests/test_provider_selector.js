// Exercise the actual browser script with a small DOM stub; no browser/network or paid calls.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.value = ''; this.disabled = false; this.textContent = ''; this.classList = {toggle() {}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector() { return new Element(); }
  before() {}
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  remove() {}
}
const nodes = new Map();
const get = id => { if (!nodes.has(id)) nodes.set(id, new Element(id)); return nodes.get(id); };
const document = {
  getElementById: get,
  createElement: tag => new Element(tag),
  createTextNode: text => ({textContent: text}),
  querySelector: selector => get(selector),
  querySelectorAll: selector => selector === 'button, #model-provider' ? [get('model-provider'), get('new-conversation')]
    : selector === '[data-busy-disabled]' ? [...nodes.values()].filter(n => n.dataset.busyDisabled)
    : [],
};
const requests = [];
let rejectNext = false;
const context = vm.createContext({document, console, Intl, Date, AbortSignal,
  crypto: {randomUUID: () => 'fixture-request'}, requestAnimationFrame: fn => fn(),
  fetch: async (url, options) => {
    requests.push({url, options});
    if (rejectNext) { rejectNext = false; return {ok: false, status: 503, json: async () => ({message: 'Not configured'})}; }
    return {ok: true, json: async () => ({conversation_id: 'conversation-'+requests.length,
      provider_id: JSON.parse(options.body).provider_id, context: {order_id: null, product_id: null}})};
  }});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
const run = code => vm.runInContext(code, context);

(async () => {
  run(`providerOptions = [{id:'custom', label:'Custom', model:'qwen3.5:4b', configured:true, notice:'Fixture'},
    {id:'api', label:'API', model:'meta/muse-spark-1.3-contributor', configured:false, notice:'Fixture'}]; renderProvider();`);
  assert.equal(get('model-provider').children[1].disabled, true);
  assert.equal(requests.length, 0);
  await run('newConversation()');
  const original = run('conversationId');
  run('pending = {proposal_id:"pending"}');
  await run('act(() => newConversation("api"))');
  assert.equal(requests.length, 1); assert.equal(run('conversationId'), original);
  assert.equal(get('model-provider').value, 'custom');
  run('pending=null; providerOptions[1].configured=true; renderProvider()');
  await run('act(() => newConversation("api"))');
  assert.equal(run('providerId'), 'api'); assert.notEqual(run('conversationId'), original);
  assert.equal(get('model-provider').disabled, false);
  assert.ok(requests.every(r => r.url === '/api/conversations'));
  assert.deepEqual(JSON.parse(requests.at(-1).options.body), {provider_id:'api'});
  const kept = run('conversationId');
  rejectNext = true;
  await assert.rejects(run('newConversation("custom")'));
  assert.equal(run('conversationId'), kept); assert.equal(run('providerId'), 'api');
  run('busy=true'); get('model-provider').value = 'custom'; get('model-provider').onchange();
  assert.equal(get('model-provider').value, 'api');
  console.log('PROVIDER_SELECTOR_UI_FLOW_OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
