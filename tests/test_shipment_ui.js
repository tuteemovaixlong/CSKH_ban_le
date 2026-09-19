'use strict';
// Run actual application renderers; reject HTML interpretation and external I/O.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.textContent = ''; this.value = ''; this.classList = {toggle(){}, add(){}, remove(){}, contains(){ return false; }}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector() { return new Element('button'); }
  before() {}
  setAttribute(k, v) { this[k] = v; }
  set innerHTML(_) { throw Error('Untrusted data must stay text'); }
}
const nodes = new Map();
const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const context = vm.createContext({
  document: {body: {dataset:{}}, getElementById:get, createElement:t=>new Element(t),
    createTextNode:t=>({textContent:t}), querySelector:get, querySelectorAll:()=>[]},
  console, Intl, Date, AbortSignal, requestAnimationFrame:fn=>fn(), crypto:{randomUUID:()=> 'fixture'},
  fetch:()=> { throw Error('Shipment rendering cannot fetch'); },
});
vm.runInContext(fs.readFileSync('web/app.js', 'utf8'), context);
const text = node => [node.textContent || '', ...(node.children || []).map(text)].join(' ');
const render = shipment => { context.row = new Element(); context.shipment = shipment; vm.runInContext('showShipment(row, shipment)', context); return context.row; };
for (const missing of [null, undefined, '', 'null', 'undefined', 'None']) {
  const row = render({carrier:missing, tracking_code:missing, status:'unknown', status_text:'Chua co du lieu hanh trinh',
    current_location:missing, shipper:missing, estimated_delivery:missing, steps:[]});
  const actual = text(row);
  assert.doesNotMatch(actual, /\b(null|undefined|None)\b/);
  assert.doesNotMatch(actual, /\u0110ang ph\u00e2n c\u00f4ng|\u0110ang giao/);
  assert.doesNotMatch(actual, /M\u00e3 v\u1eadn \u0111\u01a1n:/);
  assert.match(actual, /Chua co du lieu hanh trinh/);
}
const complete = {carrier:'Fixture carrier', tracking_code:'TRACK-42', status:'in_transit', status_text:'In transit',
  current_location:'Fixture hub', shipper:'Fixture courier', estimated_delivery:'Fixture ETA',
  steps:[{time:'12:00', event:'Arrived'}]};
const all = text(render(complete));
for (const value of ['Fixture carrier', 'TRACK-42', 'Fixture hub', 'Fixture courier', 'Fixture ETA', 'Arrived']) assert.ok(all.includes(value));
const partial = text(render({...complete, shipper:null, estimated_delivery:null, steps:[null, {}, {time:null,event:'Received'}]}));
assert.ok(partial.includes('Received')); assert.doesNotMatch(partial, /null|undefined|\u0110ang ph\u00e2n c\u00f4ng/);
assert.ok(text(render({...complete, carrier:'<script>fixture</script>'})).includes('<script>fixture</script>'));
for (const invalid of [null, undefined, [], 'shipment']) assert.equal(render(invalid).children.length, 0);
context.row = new Element();
context.trace = {model:'fixture', model_calls:1, latency_ms:null, tools:[{name:'get_order',status:'error',error_code:'order_not_found'}], turn_id:'fixture'};
vm.runInContext('showTrace(row, trace)', context);
assert.match(text(context.row), /kh\u00f4ng t\u00ecm th\u1ea5y trong t\u00e0i kho\u1ea3n/);
assert.doesNotMatch(text(context.row), /0\.00 gi\u00e2y/);
context.row = new Element(); context.trace.latency_ms=1234;
context.trace.tools = [{name:'search_knowledge',status:'error',error_code:'tool_not_allowed'}];
vm.runInContext('showTrace(row, trace)', context);
assert.ok(text(context.row).includes('1.23'));
assert.match(text(context.row), /ngo\u00e0i ph\u1ea1m vi/);
console.log('SHIPMENT_UI_OK (unknown, partial, complete, invalid data, safe text and trace semantics)');
