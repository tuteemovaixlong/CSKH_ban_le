// Exercise cookie login, reload and logout using the actual UI script; no external requests.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor() { this.children=[]; this.dataset={}; this.value=''; this.disabled=false; this.textContent=''; this.classList={toggle(){}}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  querySelector() { return this.button ||= new Element(); }
  before() {}
  setAttribute(k,v) { this[k]=v; }
  removeAttribute(k) { delete this[k]; }
  remove() {}
}
const nodes=new Map(), get=id=>{if(!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id);};
const document={body:{dataset:{auth:'cookie'}},getElementById:get,createElement:()=>new Element(),
  createTextNode:text=>({textContent:text}),querySelector:get,querySelectorAll:()=>[]};
const requests=[];
let authenticated=false, reloaded=false;
const persistent = process.env.RETAILOPS_UI_TEST_MODE === 'persistent';
if (persistent) document.body.dataset.dataMode = 'persistent-demo';
const context=vm.createContext({document,console,Intl,Date,AbortSignal,crypto:{randomUUID:()=> 'fixture-id'},
  requestAnimationFrame:fn=>fn(),location:{reload(){reloaded=true;}},
  fetch:async(url,options)=>{
    requests.push({url,options});
    let body={}, status=200;
    if(url==='/api/login') { authenticated=JSON.parse(options.body).token==='invite_fixture'; }
    else if(url==='/api/logout') {authenticated=false;}
    else if(!authenticated) {status=401;body={message:'Nhập mã mời để mở phiên demo.'};}
    else if(url==='/api/providers') body={default_provider:'api',providers:[{id:'api',model:'fixture-model',label:'API',configured:true}]};
    else if(url==='/api/session') body={name: 'Khách B', permissions: persistent ? ['orders:read'] : ['orders:read','orders:cancel']};
    else if(url==='/api/orders') body={orders:persistent ? [{id:'O-202',name:'Áo polo',variant:'M',amount:399000,status:'pending',version:1}] : []};
    else if(url==='/api/events') body={events:[]};
    else if(url==='/api/conversations') body={conversation_id:'fixture-conversation',provider_id:'api',context:{}};
    return {status,ok:status===200,json:async()=>body};
  }});
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const run=code=>vm.runInContext(code,context);
(async()=>{
  vm.runInContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(get('login-shell').hidden,false);
  get('demo-token').value='invite_fixture';
  await get('login-form').onsubmit({preventDefault(){},currentTarget:get('login-form')});
  assert.equal(get('login-shell').hidden,true);
  assert.equal(run('token'),''); assert.equal(get('demo-token').value,'');
  assert.equal(run('providerId'),'api');
  if (persistent) {
    assert.equal(get('profile-name').textContent, 'Khách B');
    assert.equal(get('order-tabs').children.length, 1);
    assert.equal(get('order-tabs').children[0].textContent, 'O-202');
    assert.equal(get('order-count').textContent, '1 đơn mẫu');
    assert.equal(run('canCancel'), false);
    assert.ok(!get('order-details').children.some(n => n.textContent === 'Yêu cầu hủy đơn này'));
    assert.ok(get('session-note').textContent.includes('đăng xuất vẫn giữ đơn hàng'));
    const beforeCancel = requests.length;
    await run('chooseReason("O-202")');
    assert.equal(requests.length, beforeCancel);
  }
  assert.ok(requests.every(r=>r.options.credentials==='same-origin'));
  assert.ok(requests.every(r=>!('Authorization' in r.options.headers)));
  const loginIndex=requests.findIndex(r=>r.url==='/api/login');
  assert.ok(requests.slice(loginIndex+1).every(r=>!JSON.stringify(r.options).includes('invite_fixture')));
  // Cookie-backed reopening uses the existing guest session, without resending an invite.
  const before=requests.filter(r=>r.url==='/api/login').length;
  await run('openSession()');
  assert.equal(requests.filter(r=>r.url==='/api/login').length,before);
  await get('logout').onclick();
  assert.equal(authenticated,false);assert.equal(reloaded,true);
  assert.equal(requests.at(-1).url,'/api/logout');
  console.log(persistent ? 'PERSISTENT_ACCOUNT_UI_FLOW_OK' : 'PUBLIC_COOKIE_UI_FLOW_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
