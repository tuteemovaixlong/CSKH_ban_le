'use strict';
// Exercise app.js status transitions. The old selector wrote into the indicator.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
class Element {
  constructor() {
    this.children = []; this.dataset = {}; this.value = ''; this.disabled = false;
    this.textContent = ''; this.attrs = {}; this.classList = {toggle() {}};
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return this.button ||= new Element(); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  before() {}
  remove() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}
const get = id => {
  if (!nodes.has(id)) nodes.set(id, new Element());
  return nodes.get(id);
};
const indicator = new Element(), status = new Element();
status.querySelector = selector => selector === 'strong' ? get('model-status-title') : indicator;
const layout = new Element(); layout.dataset.layoutControl = 'true';
const submit = new Element();
const requests = [];
let chatReply, chatError = false, unblock;
const document = {
  body: {dataset: {}}, getElementById: get, createElement: () => new Element(),
  createTextNode: text => ({textContent: text}),
  querySelector: selector => ({
    '.model-status': status,
    '.model-status strong': get('model-status-title'),
    '.model-status div span': get('model-status-detail'),
  }[selector] || get(selector)),
  querySelectorAll: selector => selector === 'button, #model-provider' ? [layout, submit]
    : selector === '[data-busy-disabled]' ? [layout, submit].filter(n => n.dataset.busyDisabled) : [],
};
const context = vm.createContext({
  document, console, Intl, Date, AbortSignal, crypto: {randomUUID: () => 'fixture-request-id'},
  requestAnimationFrame: fn => fn(), location: {reload() {}},
  fetch: async (url, options) => {
    requests.push({url, options});
    if (url === '/api/chat') {
      await new Promise(resolve => { unblock = resolve; });
      return {ok: !chatError, status: chatError ? 503 : 200,
        json: async () => chatError ? {message: 'Provider offline'} : chatReply};
    }
    return {ok: true, status: 200, json: async () => url === '/api/orders' ? {orders: []} : {events: []}};
  },
});
const run = code => vm.runInContext(code, context);
vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
const trace = {model: 'fixture-model', model_calls: 1, latency_ms: 250,
  tools: [{name: 'lookup_order', status: 'ok'}], turn_id: 'fixture-turn', reported_cost_usd: null};
(async () => {
  run("providerOptions = [{id:'custom',label:'Custom model · Colab/Ollama',model:'fixture-model',configured:true}]; renderProvider()");
  assert.equal(get('model-status-title').textContent, 'Đã chọn nguồn model');
  assert.equal(get('model-status-detail').textContent, 'Custom model · Colab/Ollama');
  chatReply = {message: 'Đơn đang chờ xử lý.', source: 'llm_agent', trace,
    action: 'reply', context: {order_id: 'O-101'}, replayed: false};
  for (const replayed of [false, true]) {
    chatReply.replayed = replayed;
    const work = run("act(() => send('Kiểm tra đơn'))");
    assert.equal(get('model-status-title').textContent, 'Model đang xử lý…');
    assert.equal(layout.disabled, false, 'layout controls must work during inference');
    assert.equal(submit.disabled, true);
    assert.equal(indicator.textContent, '');
    unblock(); await work;
    assert.equal(get('model-status-title').textContent, replayed ? 'Kết quả đã lưu' : 'Đã phản hồi');
    assert.equal(get('model-status-detail').textContent, 'Custom model · Colab/Ollama');
    assert.equal(indicator.textContent, '');
    assert.equal(submit.disabled, false);
  }
  const traces = get('messages').children.flatMap(row => row.children)
    .filter(item => item.className === 'agent-trace');
  assert.equal(traces.length, 2);
  assert.ok(traces[0].children[0].textContent.startsWith('Công cụ & thời gian'));
  assert.ok(traces[1].children[0].textContent.includes('Kết quả đã lưu'));
  chatError = true;
  const failed = run("act(() => send('Lỗi provider'))");
  unblock(); await failed;
  assert.equal(get('model-status-title').textContent, 'Chat chưa hoàn tất');
  assert.equal(indicator.textContent, '');
  assert.equal(layout.disabled, false);
  assert.equal(submit.disabled, false);
  assert.equal(requests.filter(r => r.url === '/api/chat').length, 3);
  console.log('MODEL_STATUS_UI_OK (configured, loading, success, replay, failure, busy controls)');
})().catch(error => { console.error(error); process.exitCode = 1; });
