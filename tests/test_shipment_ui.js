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
  const row = render({carrier:missing, tracking_code:missing, status:'unknown', carrier_status_raw:missing,
    status_text:'Chua co du lieu hanh trinh', current_area:missing, shipper_name:missing, shipper_phone_masked:missing,
    estimated_delivery_at:missing, delivery_attempts:0, fail_reason:missing, events:[]});
  const actual = text(row);
  assert.doesNotMatch(actual, /\b(null|undefined|None)\b/);
  assert.doesNotMatch(actual, /\u0110ang ph\u00e2n c\u00f4ng|\u0110ang giao/);
  assert.doesNotMatch(actual, /M\u00e3 v\u1eadn \u0111\u01a1n:/);
  assert.doesNotMatch(actual, /S\u1ed1 l\u1ea7n giao:/);
  assert.match(actual, /Chua co du lieu hanh trinh/);
}
const completeDb = {
  carrier:'GHN',
  tracking_code:'GHN-SIM-001',
  status:'delivery_failed',
  carrier_status_raw:'delivery_fail',
  status_text:'Giao h\u00e0ng th\u1ea5t b\u1ea1i',
  current_area:'B\u01b0u c\u1ee5c C\u1ea7u Gi\u1ea5y, H\u00e0 N\u1ed9i',
  shipper_name:'Nguy\u1ec5n V\u0103n Nam',
  shipper_phone_masked:'090****334',
  estimated_delivery_at:'2026-11-09T17:00:00+07:00',
  delivery_attempts:2,
  fail_reason:'Kh\u00f4ng li\u00ean l\u1ea1c \u0111\u01b0\u1ee3c ng\u01b0\u1eddi nh\u1eadn',
  events:[
    {
      occurred_at:'2026-11-08T08:00:00+07:00',
      hub_name:'Kho T\u1ed5ng HN',
      district:'Long Bi\u00ean',
      province:'H\u00e0 N\u1ed9i',
      location:'Kho T\u1ed5ng HN, Long Bi\u00ean, H\u00e0 N\u1ed9i',
      description:'Xu\u1ea5t kho trung chuy\u1ec3n'
    },
    {
      occurred_at:'2026-11-08T14:30:00+07:00',
      location:'B\u01b0u c\u1ee5c C\u1ea7u Gi\u1ea5y, H\u00e0 N\u1ed9i',
      description:'Giao l\u1ea7n 2 kh\u00f4ng g\u1eb7p kh\u00e1ch'
    }
  ]
};
const allDb = text(render(completeDb));
for (const value of [
  'GHN', 'GHN-SIM-001', 'delivery_fail', 'Giao h\u00e0ng th\u1ea5t b\u1ea1i',
  'B\u01b0u c\u1ee5c C\u1ea7u Gi\u1ea5y, H\u00e0 N\u1ed9i', 'Nguy\u1ec5n V\u0103n Nam (090****334)',
  'D\u1ef1 ki\u1ebfn nh\u1eadn', '17:00 09/11/2026', '08:00 08/11/2026', '14:30 08/11/2026',
  'S\u1ed1 l\u1ea7n giao: 2', 'Kh\u00f4ng li\u00ean l\u1ea1c \u0111\u01b0\u1ee3c ng\u01b0\u1eddi nh\u1eadn',
  'Xu\u1ea5t kho trung chuy\u1ec3n', 'Giao l\u1ea7n 2 kh\u00f4ng g\u1eb7p kh\u00e1ch'
]) {
  assert.ok(allDb.includes(value), 'Missing expected shipment text: ' + value);
}
assert.doesNotMatch(allDb, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
const partial = text(render({
  ...completeDb,
  shipper_name:null,
  shipper_phone_masked:null,
  estimated_delivery_at:null,
  delivery_attempts:0,
  fail_reason:null,
  events:[null, {}, {occurred_at:null, description:'Received at hub'}]
}));
assert.ok(partial.includes('Received at hub'));
assert.doesNotMatch(partial, /\b(null|undefined|None)\b|\u0110ang ph\u00e2n c\u00f4ng/);
assert.ok(text(render({...completeDb, carrier:'<script>fixture</script>'})).includes('<script>fixture</script>'));
for (const invalid of [null, undefined, [], 'shipment']) assert.equal(render(invalid).children.length, 0);
context.row = new Element();
context.trace = {model:'fixture', model_calls:1, latency_ms:null, tools:[{name:'get_order',status:'error',error_code:'order_not_found'}], turn_id:'fixture'};
vm.runInContext('showTrace(row, trace)', context);
assert.match(text(context.row), /kh\u00f4ng t\u00ecm th\u1ea5y trong t\u00e0i kho\u1ea3n/);
assert.doesNotMatch(text(context.row), /0\.00 gi\u00e2y/);
context.row = new Element();
context.trace = {model:'fixture', model_calls:1, latency_ms:80, tools:[{name:'get_order',status:'error',error_code:'ambiguous_order'}], turn_id:'fixture'};
vm.runInContext('showTrace(row, trace)', context);
assert.match(text(context.row), /kh\u1edbp nhi\u1ec1u \u0111\u01a1n/);
context.row = new Element(); context.trace.latency_ms=1234;
context.trace.tools = [{name:'search_knowledge',status:'error',error_code:'tool_not_allowed'}];
vm.runInContext('showTrace(row, trace)', context);
assert.ok(text(context.row).includes('1.23'));
assert.match(text(context.row), /ngo\u00e0i ph\u1ea1m vi/);
console.log('SHIPMENT_UI_OK (DB shipment events, unknown, partial, invalid data, safe text and trace semantics)');
