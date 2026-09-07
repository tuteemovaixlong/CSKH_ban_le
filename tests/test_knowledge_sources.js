'use strict';
// Execute the real renderer without HTML interpretation or network I/O.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.textContent = ''; this.value = ''; this.classList = {toggle(){}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector() { return new Element('button'); }
  before() {}
  setAttribute(k,v) { if (k === 'href' || k.startsWith('on')) throw Error('unsafe attribute'); this[k] = v; }
  set innerHTML(_) { throw Error('HTML must not be interpreted'); }
  set href(_) { throw Error('Source URLs must not become links'); }
}
const nodes = new Map();
const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const context = vm.createContext({
  document: {body: {dataset:{}}, getElementById:get, createElement:t=>new Element(t),
    createTextNode:t=>({textContent:t}), querySelector:get, querySelectorAll:()=>[]},
  console, Intl, Date, AbortSignal, requestAnimationFrame:fn=>fn(), crypto:{randomUUID:()=> 'fixture'},
  fetch:()=> { throw Error('Renderer must not fetch source_uri'); },
});
vm.runInContext(fs.readFileSync('web/app.js','utf8'), context);
const render = (row, sources) => { context.row=row; context.sources=sources; vm.runInContext('showSources(row, sources)', context); };
const source = {citation_id:'KB:'+'a'.repeat(24),title:'<img src=x onerror=alert(1)>',
  source_key:'<script>untrusted</script>.md',excerpt:'**text** <script>alert(1)</script>',source_uri:'javascript:alert(1)',truncated:false};
const row = new Element(); render(row, [source]);
assert.equal(row.children.length,1);
const details = row.children[0];
assert.equal(details.className,'knowledge-sources');
assert.equal(details.tagName,'details');
assert.equal(details.open,undefined,'source disclosure starts closed');
assert.ok(!details.className.includes('agent-trace'),'source disclosure is independent of debug visibility');
assert.equal(details.children[2].children[0].textContent,source.title);
assert.equal(details.children[2].children[2].textContent,source.excerpt);
for (const data of [null, undefined, [], {}, [null], [{citation_id:'javascript:bad'}]]) {
  const empty = new Element(); render(empty,data); assert.equal(empty.children.length,0);
}
const bounded = new Element(); render(bounded, Array.from({length:20},()=>({...source,excerpt:'x'.repeat(10000),truncated:true})));
assert.equal(bounded.children[0].children.length,8); // heading + note + at most six sources
assert.equal(bounded.children[0].children[2].children[2].textContent.length,1100);
console.log('KNOWLEDGE_SOURCES_UI_OK (safe text, no URL fetch, bounded disclosure, independent trace toggle)');
