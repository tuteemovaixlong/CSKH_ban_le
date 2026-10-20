// Exercise cookie login, reload and logout using the actual UI script; no external requests.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor() {
    this.children=[]; this.dataset={}; this.value=''; this.disabled=false; this.textContent='';
    this._classes=new Set();
    this.classList={
      toggle:(cls, force)=>{
        const shouldAdd = force === undefined ? !this._classes.has(cls) : Boolean(force);
        if (shouldAdd) this._classes.add(cls); else this._classes.delete(cls);
        return shouldAdd;
      },
      add:(...cls)=>cls.forEach(c=>this._classes.add(c)),
      remove:(...cls)=>cls.forEach(c=>this._classes.delete(c)),
      contains:(cls)=>this._classes.has(cls)
    };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  querySelector() { return this.button ||= new Element(); }
  before() {}
  showModal() {this.open=true;}
  close() {this.open=false;}
  focus() {this.focused=true;}
  setAttribute(k,v) { this[k]=v; }
  removeAttribute(k) { delete this[k]; }
  remove() {}
  addEventListener() {}
}
const absentIds=new Set(['about-dialog','close-about']);
const nodes=new Map(), get=id=>{
  if(absentIds.has(id)) return null;
  if(!nodes.has(id)) nodes.set(id,new Element());
  return nodes.get(id);
};
const document={body:{dataset:{auth:'cookie'}},getElementById:get,createElement:()=>new Element(),
  createTextNode:text=>({textContent:text}),querySelector:get,querySelectorAll:()=>[]};
const requests=[];
let authenticated=false, reloaded=false;
let mockSessionRole = null;
let mockSessionTenant = 'tenant_a';
let mockOrders = null;
let mockAdminAccounts = [
  {
    membership_id: 'm_cust_1',
    principal_id: 'p_cust_1',
    customer_id: 'C-701',
    display_name: 'Khách Demo A',
    role: 'customer',
    tenant_id: 'tenant_a',
    active: true,
    active_session_count: 2,
    quota: { day_utc: '2026-10-18', used: 3, default_limit: 20, limit: 20, remaining: 17, exhausted: false, override: null, next_reset_utc: '2026-10-19T00:00:00Z' }
  }
];
let mockAdminAuditLogs = [];
let forceAdminError = null;
const persistent = process.env.RETAILOPS_UI_TEST_MODE === 'persistent';
if (persistent) document.body.dataset.dataMode = 'persistent-demo';
const context=vm.createContext({document,console,Intl,Date,URLSearchParams,AbortSignal,crypto:{randomUUID:()=> 'fixture-id'},
  requestAnimationFrame:fn=>fn(),location:{reload(){reloaded=true;}},
  fetch:async(url,options)=>{
    requests.push({url,options});
    let body={}, status=200;
    if(url==='/api/login') { authenticated=JSON.parse(options.body).token==='invite_fixture'; }
    else if(url==='/api/logout') {authenticated=false;}
    else if(!authenticated) {status=401;body={message:'Nhập mã mời để mở phiên demo.'};}
    else if(url==='/api/providers') body={default_provider:'api',providers:[{id:'api',model:'fixture-model',label:'API',configured:true}]};
    else if(url==='/api/session') body={
      name: 'Khách B',
      role: mockSessionRole || 'customer',
      tenant_id: mockSessionTenant,
      permissions: (mockSessionRole === 'manager' || mockSessionRole === 'platform_admin')
        ? ['orders:read','orders:cancel','staff:access','manager:access']
        : (persistent ? ['orders:read'] : ['orders:read','orders:cancel'])
    };
    else if(url==='/api/orders') {
      if (mockOrders !== null) {
        body = { orders: mockOrders, scope: (mockSessionRole === 'manager' || mockSessionRole === 'platform_admin') ? 'store_all' : 'customer' };
      } else {
        body={orders:persistent ? [{id:'O-202',name:'Áo polo',variant:'M',amount:399000,status:'pending',version:1}] : []};
      }
    }
    else if(url==='/api/cancellation-proposals') body={proposals:[{proposal_id:'saved-proposal-id',reason:'ordered_by_mistake',expires_at:Date.now()/1000+600,order:{id:'O-101',name:'Áo thun',amount:299000}}]};
    else if(url==='/api/events') body={events:[]};
    else if(url==='/api/conversations') body={conversation_id:'fixture-conversation',provider_id:'api',context:{}};
    else if(url==='/api/manager/kpis') body={total_orders:2,pending_orders:1,delivered_orders:1,cancelled_orders:0,total_revenue:919000,active_products:3};
    else if(url==='/api/manager/products') body={products:[],count:0};
    else if(url==='/api/manager/events') body={events:[]};
    else if(url.startsWith('/api/admin/accounts')) {
      if (forceAdminError) {
        status = forceAdminError.status;
        body = { error: forceAdminError.error, message: forceAdminError.message };
      } else if (options.method === 'POST') {
        const payload = JSON.parse(options.body || '{}');
        const acct = mockAdminAccounts[0];
        if (url.endsWith('/suspend')) {
          acct.active = false;
          acct.active_session_count = 0;
          mockAdminAuditLogs.unshift({ created_at: 1760000000, actor_principal_id: 'p_mgr', actor_role: mockSessionRole, action: 'suspend_account', target_membership_id: acct.membership_id, outcome: 'allowed', reason: payload.reason, after: { active: false } });
        } else if (url.endsWith('/reactivate')) {
          acct.active = true;
          mockAdminAuditLogs.unshift({ created_at: 1760000001, actor_principal_id: 'p_mgr', actor_role: mockSessionRole, action: 'reactivate_account', target_membership_id: acct.membership_id, outcome: 'allowed', reason: payload.reason, after: { active: true } });
        } else if (url.endsWith('/revoke-sessions')) {
          acct.active_session_count = 0;
          mockAdminAuditLogs.unshift({ created_at: 1760000002, actor_principal_id: 'p_mgr', actor_role: mockSessionRole, action: 'revoke_sessions', target_membership_id: acct.membership_id, outcome: 'allowed', reason: payload.reason, after: { active_sessions: 0 } });
        } else if (url.endsWith('/quota')) {
          acct.quota.override = payload.daily_limit ? { daily_limit: payload.daily_limit, reason: payload.reason } : null;
          acct.quota.limit = payload.daily_limit ?? acct.quota.default_limit;
          mockAdminAuditLogs.unshift({ created_at: 1760000003, actor_principal_id: 'p_mgr', actor_role: mockSessionRole, action: 'set_quota_override', target_membership_id: acct.membership_id, outcome: 'allowed', reason: payload.reason, after: { override: { daily_limit: payload.daily_limit } } });
        }
        body = { account: acct };
      } else if (/^\/api\/admin\/accounts\/[^?]+/.test(url)) {
        body = { account: mockAdminAccounts[0] };
      } else {
        body = { accounts: mockAdminAccounts };
      }
    }
    else if(url.startsWith('/api/admin/audit-log')) {
      body = { audit_logs: mockAdminAuditLogs };
    }
    return {status,ok:status===200,json:async()=>body};
  }});
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const run=code=>vm.runInContext(code,context);
function collectText(node) {
  if (!node) return '';
  let out = (node.textContent || '') + ' ' + (node.innerHTML || '');
  if (Array.isArray(node.children)) {
    for (const ch of node.children) out += ' ' + collectText(ch);
  }
  return out;
}
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
  if (!persistent) {
    assert.ok(requests.some(r=>r.url==='/api/cancellation-proposals'));
    assert.equal(get('confirm-dialog').open,undefined);
    const rows=get('messages').children;
    const button=rows.flatMap(r=>r.children).find(n=>n.textContent==='Xem lại đề xuất');
    assert.ok(button); await button.onclick();
    assert.equal(run('pending.key'),'saved-proposal-id');
    assert.equal(get('confirm-dialog').open,true);
    assert.ok(!requests.some(r=>r.url.endsWith('/confirm')));
  }

  // P5-E-DATA1: Positive demo fixture display_name vs Negative non-demo canonical name in UI
  mockOrders = [
    { id: 'O-700102', customer_id: 'C-701', name: 'Quần tây ống đứng tôn dáng', display_name: 'Bộ xếp hình gỗ cho bé', variant: 'Đen / L', amount: 520000, status: 'delivered', version: 1, product_id: 'P-602' },
    { id: 'O-123456', customer_id: 'non_demo_customer', name: 'Quần tây ống đứng tôn dáng', variant: 'Đen / L', amount: 520000, status: 'delivered', version: 1, product_id: 'P-602' }
  ];
  await run('refresh()');
  const cards = get('order-card-list').children;
  assert.equal(cards.length, 2);
  assert.ok(collectText(cards[0]).includes('Bộ xếp hình gỗ cho bé'));
  assert.ok(collectText(cards[1]).includes('Quần tây ống đứng tôn dáng'));
  assert.ok(!collectText(cards[1]).includes('Bộ xếp hình gỗ cho bé'));

  // P5-E-R4 (ADM1–ADM6): Customer/staff denied vs Manager/Platform-Admin Account & Quota Governance UI
  assert.equal(get('tab-btn-accounts').hidden, true);
  assert.equal(get('tab-content-accounts').hidden, true);
  await run('openManagerConsole()');
  assert.equal(get('manager-console-dialog').open, undefined);
  assert.ok(get('admin-governance-error').textContent.includes('không có quyền'));

  // Elevate to manager (tenant_a) and verify Store Manager Navigation (FIXA-UI1..UI4) + Account & Quota Governance UI flow
  mockSessionRole = 'manager';
  await run('openSession()');
  assert.equal(get('tab-btn-accounts').hidden, false);
  assert.equal(get('admin-tenant-id-input').value, 'tenant_a');
  assert.equal(get('admin-tenant-id-input').readOnly, true);

  // FIXA-UI1..UI4: open Store Manager -> defaults to Tổng quan & KPIs -> switch to Hàng hóa & Kho -> return to KPIs -> close & reopen
  await run('openManagerConsole()');
  assert.equal(get('manager-console-dialog').open, true);
  assert.equal(run('currentManagerTab'), 'kpis');
  assert.equal(get('tab-btn-kpis').classList.contains('active'), true);
  assert.equal(get('tab-btn-kpis')['aria-selected'], 'true');
  assert.equal(get('tab-content-kpis').hidden, false);
  assert.equal(get('tab-content-products').hidden, true);
  assert.equal(get('btn-manager-back-to-kpis').hidden, true);

  // Navigate to Hàng hóa & Kho (products)
  get('tab-btn-products').onclick();
  assert.equal(run('currentManagerTab'), 'products');
  assert.equal(get('tab-btn-products').classList.contains('active'), true);
  assert.equal(get('tab-btn-products')['aria-selected'], 'true');
  assert.equal(get('tab-btn-kpis').classList.contains('active'), false);
  assert.equal(get('tab-btn-kpis')['aria-selected'], 'false');
  assert.equal(get('tab-content-products').hidden, false);
  assert.equal(get('tab-content-kpis').hidden, true);
  assert.equal(get('btn-manager-back-to-kpis').hidden, false);

  // Return to Tổng quan & KPIs from inside Products toolbar button (FIXA-UI2)
  get('btn-products-back-to-kpis').onclick();
  assert.equal(run('currentManagerTab'), 'kpis');
  assert.equal(get('tab-btn-kpis').classList.contains('active'), true);
  assert.equal(get('tab-content-kpis').hidden, false);
  assert.equal(get('tab-content-products').hidden, true);
  assert.equal(get('btn-manager-back-to-kpis').hidden, true);

  // Navigate to products again, then return via sticky header back button (FIXA-UI2)
  get('tab-btn-products').onclick();
  assert.equal(run('currentManagerTab'), 'products');
  get('btn-manager-back-to-kpis').onclick();
  assert.equal(run('currentManagerTab'), 'kpis');
  assert.equal(get('tab-content-kpis').hidden, false);

  // Keyboard navigation across tabs (FIXA-UI3)
  get('tab-btn-kpis').onkeydown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(run('currentManagerTab'), 'products');
  get('tab-btn-products').onkeydown({ key: 'ArrowLeft', preventDefault() {} });
  assert.equal(run('currentManagerTab'), 'kpis');

  // Switch to products, close dialog, reopen -> must reset to Tổng quan & KPIs (FIXA-UI1, FIXA-UI4)
  get('tab-btn-products').onclick();
  assert.equal(run('currentManagerTab'), 'products');
  get('close-manager-console').onclick();
  assert.equal(get('manager-console-dialog').open, false);
  await run('openManagerConsole()');
  assert.equal(get('manager-console-dialog').open, true);
  assert.equal(run('currentManagerTab'), 'kpis');
  assert.equal(get('tab-btn-kpis').classList.contains('active'), true);
  assert.equal(get('tab-content-kpis').hidden, false);
  assert.equal(get('tab-content-products').hidden, true);

  await run('loadAdminAccounts()');
  assert.equal(get('admin-accounts-tbody').children.length, 1);
  assert.ok(collectText(get('admin-accounts-tbody').children[0]).includes('m_cust_1'));
  assert.ok(collectText(get('admin-accounts-tbody').children[0]).includes('2026-10-19T00:00:00Z'));

  await run('inspectAdminAccount("m_cust_1")');
  assert.equal(get('admin-account-detail-panel').hidden, false);
  assert.ok(get('admin-selected-account-title').textContent.includes('m_cust_1'));
  assert.equal(get('admin-selected-account-status').textContent, 'active');
  assert.ok(get('admin-selected-account-meta').textContent.includes('2026-10-19T00:00:00Z'));

  // Unconfirmed action fails closed in UI without sending POST
  get('admin-action-confirm').checked = false;
  get('admin-action-reason').value = 'Kiểm thử đình chỉ';
  const reqBeforeUnconfirmed = requests.length;
  await run('submitAdminAccountAction("suspend")');
  assert.equal(requests.length, reqBeforeUnconfirmed);
  assert.equal(get('admin-governance-error').hidden, false);

  // Confirmed suspend -> reactivate -> revoke-sessions -> quota override -> clear quota override -> audit log refresh
  get('admin-action-confirm').checked = true;
  await run('submitAdminAccountAction("suspend")');
  assert.equal(get('admin-action-confirm').checked, false);
  assert.equal(get('admin-selected-account-status').textContent, 'suspended');
  assert.ok(collectText(get('admin-audit-log-tbody')).includes('suspend_account'));

  get('admin-action-confirm').checked = true;
  get('admin-action-reason').value = 'Kích hoạt lại tài khoản';
  await run('submitAdminAccountAction("reactivate")');
  assert.equal(get('admin-selected-account-status').textContent, 'active');

  get('admin-action-confirm').checked = true;
  get('admin-action-reason').value = 'Thu hồi phiên đăng nhập';
  await run('submitAdminAccountAction("revoke-sessions")');
  assert.ok(collectText(get('admin-audit-log-tbody')).includes('revoke_sessions'));

  get('admin-action-confirm').checked = true;
  get('admin-action-reason').value = 'Tăng hạn mức API';
  get('admin-quota-limit').value = '50';
  await run('submitAdminAccountAction("quota")');
  assert.ok(collectText(get('admin-selected-account-meta')).includes('3/50 (override)'));
  assert.ok(collectText(get('admin-audit-log-tbody')).includes('set_quota_override'));

  // Clear quota override by leaving #admin-quota-limit empty (R4.4)
  get('admin-action-confirm').checked = true;
  get('admin-action-reason').value = 'Xóa ghi đè hạn mức về mặc định';
  get('admin-quota-limit').value = '';
  await run('submitAdminAccountAction("quota")');
  assert.ok(collectText(get('admin-selected-account-meta')).includes('3/20'));
  assert.ok(!collectText(get('admin-selected-account-meta')).includes('(override)'));

  // Error handling (403/400/404) surfaces cleanly in #admin-governance-error
  forceAdminError = { status: 403, error: 'tenant_scope_denied', message: 'Quản lý cửa hàng chỉ được phép thao tác trên tài khoản thuộc cửa hàng của mình.' };
  get('admin-action-confirm').checked = true;
  await run('submitAdminAccountAction("suspend")');
  assert.equal(get('admin-governance-error').hidden, false);
  assert.ok(get('admin-governance-error').textContent.includes('cửa hàng của mình'));
  forceAdminError = null;

  // Platform admin has cross-tenant selector unlocked; changing tenant clears selected account and blocks stale mutation (R4.2)
  mockSessionRole = 'platform_admin';
  await run('openSession()');
  assert.equal(get('admin-tenant-id-input').readOnly, false);
  assert.ok(get('admin-governance-scope-badge').textContent.includes('PLATFORM_ADMIN'));
  await run('inspectAdminAccount("m_cust_1")');
  assert.equal(run('selectedAdminMembershipId'), 'm_cust_1');
  get('admin-tenant-id-input').value = 'tenant_b';
  get('admin-tenant-id-input').oninput();
  assert.equal(run('selectedAdminMembershipId'), null);
  assert.equal(get('admin-account-detail-panel').hidden, true);

  await get('logout').onclick();
  assert.equal(authenticated,false);assert.equal(reloaded,true);
  assert.equal(requests.at(-1).url,'/api/logout');
  console.log(persistent ? 'PERSISTENT_ACCOUNT_UI_FLOW_OK' : 'PUBLIC_COOKIE_UI_FLOW_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
