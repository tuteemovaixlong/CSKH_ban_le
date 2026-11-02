// Exercise cookie login, reload and logout using the actual UI script; no external requests.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(tag='') {
    this.tagName=String(tag).toUpperCase();
    this._id='';
    this.children=[]; this.dataset={}; this.value=''; this.disabled=false; this.textContent='';
    this.style={};
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
  get id() { return this._id; }
  set id(v) { this._id=String(v||''); if (this._id) nodes.set(this._id, this); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  querySelector() { return this.button ||= new Element('button'); }
  querySelectorAll(sel='') {
    const tags = sel.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean);
    const out = [];
    const walk = n => {
      if (!n || typeof n !== 'object') return;
      for (const ch of (n.children || [])) {
        if (ch && typeof ch === 'object') {
          if (!tags.length || tags.includes(ch.tagName)) out.push(ch);
          walk(ch);
        }
      }
    };
    walk(this);
    return out;
  }
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
const document={body:{dataset:{auth:'cookie'}},getElementById:get,createElement:tag=>new Element(tag),
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
let forceFeedbackError = null;
let forceStaffReplyError = null;
let mockTranscriptResponse = null;
let mockStaffCases = null;
let mockStaffCaseOrderActions = null;
let mockStaffCaseTranscriptMap = null;
let alertCalls = [];
const storageMap = new Map();
const localStorage = {
  getItem: k => (storageMap.has(k) ? storageMap.get(k) : null),
  setItem: (k, v) => { storageMap.set(k, String(v)); },
  removeItem: k => { storageMap.delete(k); }
};
const persistent = process.env.RETAILOPS_UI_TEST_MODE === 'persistent';
if (persistent) document.body.dataset.dataMode = 'persistent-demo';
const context=vm.createContext({document,console,Intl,Date,URLSearchParams,AbortSignal,localStorage,crypto:{randomUUID:()=> 'fixture-id'},
  alert:msg=>{ alertCalls.push(String(msg)); },
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
      principal_id: (mockSessionRole === 'staff') ? 'p_staff_1' : 'p_cust_1',
      role: mockSessionRole || 'customer',
      tenant_id: mockSessionTenant,
      permissions: (mockSessionRole === 'manager' || mockSessionRole === 'platform_admin')
        ? ['orders:read','orders:cancel','staff:access','manager:access']
        : (mockSessionRole === 'staff'
          ? ['orders:read','staff:access']
          : (persistent ? ['orders:read'] : ['orders:read','orders:cancel']))
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
    else if(url==='/api/conversations') body={conversation_id:'fixture-conversation',case_id:'case_ui_1',provider_id:'api',context:{}};
    else if(/^\/api\/conversations\/[^/]+\/focus$/.test(url)) {
      const payload = JSON.parse(options.body || '{}');
      const ordList = mockOrders || [{id:'O-202',name:'Áo polo',variant:'M',amount:399000,status:'pending',version:1}];
      const found = ordList.find(o => o.id === payload.order_id) || ordList[0];
      body = { order: found, context: { order_id: found.id, product_id: found.product_id || 'P-101' }, message: 'Đã chọn đơn ' + found.id, source: 'store_data' };
    }
    else if(url==='/api/order-actions' && options.method==='POST') {
      const payload = JSON.parse(options.body || '{}');
      body = {
        status: 'ok',
        message: 'Đã gửi yêu cầu ' + payload.type + ' cho đơn ' + payload.order_id + ', chờ cửa hàng duyệt.',
        request: {
          request_id: 'oar_ui_fixture_1',
          order_id: payload.order_id,
          case_id: 'case_ui_1',
          conversation_id: payload.conversation_id || 'fixture-conversation',
          type: payload.type,
          exchange_kind: payload.exchange_kind || null,
          status: 'requested',
          reason_code: payload.reason_code,
          reason_text: payload.reason_text || null,
          version: 1
        }
      };
    }
    else if(/^\/api\/order-actions\/[^/]+\/evidence$/.test(url) && options.method==='POST') {
      body = {
        status: 'ok',
        evidence: {
          evidence_id: 'ev_ui_fixture_1',
          request_id: url.split('/')[3],
          mime_type: (options.headers && options.headers['Content-Type']) || 'image/jpeg',
          byte_size: 2048,
          sha256: 'a'.repeat(64)
        }
      };
    }
    else if(url==='/api/feedback') {
      if (forceFeedbackError) {
        status = forceFeedbackError.status;
        body = { error: 'handoff_persist_failed', message: forceFeedbackError.message };
      } else {
        const fbBody = JSON.parse(options.body || '{}');
        if (fbBody.feedback_type === 'human_handoff') {
          body = {
            status: 'ok',
            case_id: 'case_ui_1',
            handoff_id: 'hof_ui_1',
            notice_turn_id: 951,
            notice_message: 'Đã gửi yêu cầu gặp nhân viên. Nhân viên CSKH sẽ phản hồi trong cuộc trò chuyện này.'
          };
        } else {
          body = { status: 'ok', case_id: 'case_ui_1', handoff_id: 'hof_ui_1' };
        }
      }
    }
    else if(/^\/api\/conversations\/[^/]+\/messages$/.test(url)) {
      body = mockTranscriptResponse || { conversation: { id: 'fixture-conversation' }, case: { case_id: 'case_ui_1', status: 'waiting', version: 1, has_active_timer: false }, turns: [], feedbacks: [] };
    }
    else if(url==='/api/staff/cases') {
      body = mockStaffCases || { waiting: [], in_progress: [], resolved: [], open_count: 0 };
    }
    else if(/^\/api\/staff\/cases\/[^/]+\/claim$/.test(url)) {
      if (mockStaffCases && mockStaffCases.waiting.length) {
        const claimed = { ...mockStaffCases.waiting.shift(), status: 'in_progress', holder: 'p_staff_1', holder_name: 'Khách B', version: 2 };
        mockStaffCases.in_progress.unshift(claimed);
        body = {
          status: 'ok',
          claimed: true,
          case_id: claimed.case_id,
          handoff_id: 'hof_ui_1',
          case: claimed,
          notice_turn_id: 952,
          notice_message: 'Nhân viên Khách B đã nhận ca hỗ trợ.'
        };
      } else {
        status = 409;
        body = { error: 'case_claim_conflict', message: 'Ca hỗ trợ đã được nhân viên khác nhận xử lý.' };
      }
    }
    else if(/^\/api\/staff\/cases\/[^/]+\/messages$/.test(url)) {
      const cidMatch = url.split('/')[4];
      if (mockStaffCaseTranscriptMap && mockStaffCaseTranscriptMap[cidMatch]) {
        body = mockStaffCaseTranscriptMap[cidMatch];
      } else {
        const allMockCases = mockStaffCases
          ? [...(mockStaffCases.waiting || []), ...(mockStaffCases.in_progress || []), ...(mockStaffCases.resolved || [])]
          : [];
        const matchedCase = allMockCases.find(c => c.case_id === cidMatch);
        const isClosedCase = matchedCase ? matchedCase.status === 'resolved' : cidMatch === 'case_r1';
        body = {
          conversation: { id: 'fixture-conversation' },
          case: matchedCase || { case_id: cidMatch, status: isClosedCase ? 'resolved' : 'waiting', holder: null, version: 1 },
          read_only: isClosedCase,
          turns: [],
          feedbacks: []
        };
      }
    }
    else if(/^\/api\/staff\/cases\/[^/]+\/order-actions$/.test(url)) {
      const cidMatch = url.split('/')[4];
      if (options.method === 'POST') {
        const payload = JSON.parse(options.body || '{}');
        const created = {
          request_id: 'oar_df_1',
          order_id: payload.order_id,
          case_id: cidMatch,
          conversation_id: 'fixture-conversation',
          type: 'cancel',
          exchange_kind: null,
          status: 'under_review',
          inspection_outcome: null,
          refund_status: 'not_applicable',
          refund_decision: null,
          reason_code: 'delivery_failed',
          reason_label: 'Giao hàng thất bại',
          reason_text: payload.note,
          raised_by_role: mockSessionRole || 'staff',
          delivery_failure_attempts: payload.delivery_failure_attempts,
          expected_order_version: payload.expected_order_version || 1,
          version: 1,
          closed_at: null,
          order: { id: payload.order_id, name: 'Áo thun Essential', amount: 299000, status: 'pending', version: 1 },
          delivery_age_label: 'chưa có ngày giao',
          evidence: [],
          decisions: [{ decision_id: 'oad_df_1', action: 'submit', from_status: null, to_status: 'under_review', actor_role: mockSessionRole || 'staff', note: payload.note }]
        };
        if (mockStaffCaseOrderActions && mockStaffCaseOrderActions[cidMatch]) {
          mockStaffCaseOrderActions[cidMatch].order_actions.unshift(created);
        }
        status = 201;
        body = { status: 'under_review', order_action_request_id: created.request_id, order_action: created, message: 'Đã tạo yêu cầu hủy do giao thất bại, chờ Quản lý duyệt' };
      } else {
        body = (mockStaffCaseOrderActions && mockStaffCaseOrderActions[cidMatch]) || {
          case_id: cidMatch,
          read_only: cidMatch === 'case_r1',
          order_actions: [],
          customer_orders: []
        };
      }
    }
    else if(/^\/api\/order-actions\/[^/]+\/(approve|reject|mark-received|mark-inspected|complete|refund-request|refund-decision|refund-outcome)$/.test(url) && options.method === 'POST') {
      const parts = url.split('/');
      const reqId = parts[3];
      const stepSlug = parts[4];
      const payload = JSON.parse(options.body || '{}');
      let targetReq = null;
      if (mockStaffCaseOrderActions) {
        for (const entry of Object.values(mockStaffCaseOrderActions)) {
          const found = (entry.order_actions || []).find(r => r.request_id === reqId);
          if (found) { targetReq = found; break; }
        }
      }
      if (!targetReq) {
        status = 404;
        body = { error: 'order_action_not_found', message: 'Không tìm thấy yêu cầu.' };
      } else {
        const prevStatus = targetReq.status;
        const prevRefund = targetReq.refund_status;
        targetReq.version += 1;
        if (stepSlug === 'approve') {
          targetReq.status = 'approved';
          if (targetReq.type === 'cancel') {
            targetReq.closed_at = 1760000100;
            if (targetReq.order) targetReq.order.status = 'cancelled';
          }
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'approve', from_status: prevStatus, to_status: 'approved', actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'reject') {
          targetReq.status = 'rejected';
          targetReq.closed_at = 1760000100;
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'reject', from_status: prevStatus, to_status: 'rejected', actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'mark-received') {
          targetReq.status = 'received';
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'mark_received', from_status: prevStatus, to_status: 'received', actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'mark-inspected') {
          targetReq.status = 'inspected';
          targetReq.inspection_outcome = payload.inspection_outcome;
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'mark_inspected', from_status: prevStatus, to_status: 'inspected', inspection_outcome: payload.inspection_outcome, actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'complete') {
          targetReq.status = 'completed';
          targetReq.closed_at = 1760000200;
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'complete', from_status: prevStatus, to_status: 'completed', actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'refund-request') {
          targetReq.refund_status = 'pending';
          targetReq.refund_decision = null;
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'refund_request', from_refund_status: prevRefund, to_refund_status: 'pending', actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'refund-decision') {
          targetReq.refund_decision = payload.decision;
          targetReq.refund_status = payload.decision === 'approved' ? 'pending' : 'not_applicable';
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: payload.decision === 'approved' ? 'refund_approve' : 'refund_reject', from_refund_status: 'pending', to_refund_status: targetReq.refund_status, refund_decision: payload.decision, actor_role: mockSessionRole, note: payload.note || null });
        } else if (stepSlug === 'refund-outcome') {
          targetReq.refund_status = payload.outcome;
          targetReq.decisions.push({ decision_id: 'oad_' + targetReq.version, action: 'refund_outcome', from_refund_status: 'pending', to_refund_status: payload.outcome, refund_decision: 'approved', actor_role: mockSessionRole, note: payload.note || null });
        }
        body = { status: targetReq.status, order_action: targetReq, customer_notice: 'Đã cập nhật ' + stepSlug };
      }
    }
    else if(url==='/api/staff/reply') {
      if (forceStaffReplyError) {
        status = forceStaffReplyError.status;
        body = { error: forceStaffReplyError.error || 'staff_reply_failed', message: forceStaffReplyError.message };
      } else {
        const payload = JSON.parse(options.body || '{}');
        body = { status: 'ok', turn_id: 501, case_id: payload.case_id || 'case_w1', message: payload.message };
      }
    }
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
    return {status,ok:status>=200&&status<300,json:async()=>body};
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
    assert.equal(get('order-count').textContent, '1 đơn hàng');
    assert.equal(run('canCancel'), false);
    assert.ok(!get('order-details').children.some(n => n.textContent === 'Yêu cầu hủy đơn này'));
    assert.ok(get('session-note').textContent.includes('đăng xuất vẫn giữ đơn hàng'));
    assert.ok(!get('session-note').textContent.includes('Dữ liệu mẫu'));
    const beforeCancel = requests.length;
    await run('chooseReason("O-202")');
    assert.equal(requests.length, beforeCancel);
    mockOrders = [];
    await run('refresh()');
    assert.equal(get('order-count').textContent, '0 đơn hàng');
    mockOrders = null;
    await run('refresh()');
  } else {
    assert.equal(get('order-count').textContent, '0 đơn mẫu');
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

  // R1-W2 UI checks:
  // 1) Meet Human button waits for durable API persistence before switching UI mode; fails closed on API error
  mockSessionRole = 'customer';
  await run('openSession()');
  assert.equal(run('isHumanMode'), false);
  forceFeedbackError = { status: 503, message: 'Không thể lưu yêu cầu gặp nhân viên.' };
  await run('toggleHumanMode()');
  assert.equal(run('isHumanMode'), false);
  assert.ok(collectText(get('messages')).includes('Không thể gửi yêu cầu gặp nhân viên'));
  forceFeedbackError = null;
  await run('toggleHumanMode()');
  assert.equal(run('isHumanMode'), true);
  assert.equal(run('currentCaseId'), 'case_ui_1');
  assert.equal(run('currentHandoffId'), 'hof_ui_1');
  await run('toggleHumanMode()');
  assert.equal(run('isHumanMode'), false);

  // 2) Customer bot-timer polling renders fixed reminder turn once and surfaces resolved status
  mockTranscriptResponse = {
    conversation: { id: 'fixture-conversation' },
    case: { case_id: 'case_ui_1', status: 'waiting', version: 2, has_active_timer: true },
    turns: [{
      id: 901,
      messages: JSON.stringify([{ role: 'assistant', content: 'Tin nhắc tự động 5 phút' }]),
      result: JSON.stringify({ author: 'system_reminder', message: 'Tin nhắc tự động 5 phút' })
    }],
    feedbacks: []
  };
  await run('pollBotCaseTimer()');
  await run('pollBotCaseTimer()');
  const reminderMatches = collectText(get('messages')).split('Tin nhắc tự động 5 phút').length - 1;
  assert.equal(reminderMatches, 1);
  mockTranscriptResponse = {
    ...mockTranscriptResponse,
    case: { case_id: 'case_ui_1', status: 'resolved', resolved_reason: 'inactivity', version: 3, has_active_timer: false }
  };
  await run('pollBotCaseTimer()');
  assert.equal(get('model-status-title').textContent, 'Ca hỗ trợ đã đóng');
  assert.ok(collectText(get('messages')).includes('Ca hỗ trợ đã tạm đóng'));
  mockTranscriptResponse = null;

  // 3) Staff Desk 3-bucket queue count (open_count only), claim button, and read-only resolved view
  mockStaffCases = {
    waiting: [{ case_id: 'case_w1', conversation_id: 'fixture-conversation', customer_id: 'C-701', customer_name: 'Khách A', status: 'waiting', holder: null, comment: 'Cần hỗ trợ' }],
    in_progress: [{ case_id: 'case_p1', conversation_id: 'fixture-conversation', customer_id: 'C-702', status: 'in_progress', holder: 'p_staff_2', holder_name: 'NV 2' }],
    resolved: [{ case_id: 'case_r1', conversation_id: 'fixture-conversation', customer_id: 'C-703', status: 'resolved', resolved_reason: 'staff_resolved' }],
    open_count: 2
  };
  mockSessionRole = 'staff';
  await run('openSession()');
  await run('loadStaffQueue()');
  assert.equal(get('staff-queue-count').textContent, '2');
  assert.equal(get('staff-bucket-waiting').textContent, 'Hàng chờ (1)');
  assert.equal(get('staff-bucket-in-progress').textContent, 'Đang xử lý (1)');
  assert.equal(get('staff-bucket-resolved').textContent, 'Đã xử lý (1)');
  await run('selectStaffTicket(staffDeskData.waiting[0])');
  assert.equal(get('staff-chat-composer').style.display, 'flex');
  assert.equal(get('btn-claim-ticket').textContent, '✋ Nhận ca');
  await run('claimOrReleaseStaffTicket()');
  assert.equal(get('btn-claim-ticket').textContent, '↩ Trả ca');
  await run('setStaffQueueBucket("resolved")');
  await run('selectStaffTicket(staffDeskData.resolved[0])');
  assert.equal(get('staff-chat-composer').style.display, 'none');
  assert.equal(get('staff-chat-composer').hidden, true);
  assert.equal(get('staff-chat-actions').style.display, 'none');

  // R1-W3 Item 0: Direct reply button (#btn-send-staff-reply), Enter key, CSP-safe hidden state, and in-dialog notice banner (no alert())
  const indexHtml = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
  const stylesCss = fs.readFileSync(path.join(__dirname, '../web/styles.css'), 'utf8');
  assert.ok(indexHtml.includes('id="staff-desk-notice"'), 'Staff Desk dialog must contain #staff-desk-notice banner');
  const composerCssBlock = (stylesCss.match(/\.staff-chat-composer\s*\{[^}]*\}/) || [''])[0];
  assert.ok(!/display\s*:\s*flex\s*!important/i.test(composerCssBlock), '.staff-chat-composer must not force display:flex !important over hidden state');

  // Re-select active case and test empty click -> shows inline notice instead of silent no-op
  await run('setStaffQueueBucket("waiting")');
  await run('selectStaffTicket(staffDeskData.in_progress[0])');
  assert.equal(get('staff-chat-composer').hidden, false);
  alertCalls = [];
  get('staff-reply-input').value = '   ';
  const replyCountBeforeEmpty = requests.filter(r => r.url === '/api/staff/reply').length;
  await get('btn-send-staff-reply').onclick();
  assert.equal(requests.filter(r => r.url === '/api/staff/reply').length, replyCountBeforeEmpty);
  assert.equal(get('staff-desk-notice').hidden, false);
  assert.equal(alertCalls.length, 0);

  // Button click with text -> exactly 1 POST /api/staff/reply with case_id, clears input, appends to transcript, shows inline notice
  get('staff-reply-input').value = 'Shop xin chào anh/chị ạ';
  const replyCountBeforeClick = requests.filter(r => r.url === '/api/staff/reply').length;
  await get('btn-send-staff-reply').onclick();
  const clickCalls = requests.filter(r => r.url === '/api/staff/reply').slice(replyCountBeforeClick);
  assert.equal(clickCalls.length, 1);
  const clickPayload = JSON.parse(clickCalls[0].options.body);
  assert.equal(clickPayload.case_id, 'case_w1');
  assert.equal(clickPayload.message, 'Shop xin chào anh/chị ạ');
  assert.equal(get('staff-reply-input').value, '');
  assert.ok(collectText(get('staff-chat-transcript')).includes('Shop xin chào anh/chị ạ'));
  assert.equal(get('staff-desk-notice').hidden, false);
  assert.equal(alertCalls.length, 0);

  // Enter key in #staff-reply-input -> exactly 1 POST /api/staff/reply with case_id, clears input, appends to transcript
  get('staff-reply-input').value = 'Phản hồi gửi bằng phím Enter';
  const replyCountBeforeEnter = requests.filter(r => r.url === '/api/staff/reply').length;
  let enterPrevented = false;
  get('staff-reply-input').onkeydown({ key: 'Enter', shiftKey: false, isComposing: false, preventDefault() { enterPrevented = true; } });
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(enterPrevented, true);
  const enterCalls = requests.filter(r => r.url === '/api/staff/reply').slice(replyCountBeforeEnter);
  assert.equal(enterCalls.length, 1);
  const enterPayload = JSON.parse(enterCalls[0].options.body);
  assert.equal(enterPayload.case_id, 'case_w1');
  assert.equal(enterPayload.message, 'Phản hồi gửi bằng phím Enter');
  assert.equal(get('staff-reply-input').value, '');
  assert.ok(collectText(get('staff-chat-transcript')).includes('Phản hồi gửi bằng phím Enter'));

  // API error on POST /api/staff/reply -> error shown inside #staff-desk-notice (not alert()), draft preserved
  forceStaffReplyError = { status: 409, error: 'case_held_by_other', message: 'Ca hỗ trợ đang do nhân viên khác phụ trách.' };
  get('staff-reply-input').value = 'Tin nhắn khi API lỗi';
  await get('btn-send-staff-reply').onclick();
  assert.equal(alertCalls.length, 0, 'Staff Desk must never use window.alert()');
  assert.equal(get('staff-desk-notice').hidden, false);
  assert.ok(get('staff-desk-notice').textContent.includes('Ca hỗ trợ đang do nhân viên khác phụ trách.'));
  assert.equal(get('staff-reply-input').value, 'Tin nhắn khi API lỗi');
  forceStaffReplyError = null;
  closeStaffDeskDialogFn: await run('closeStaffDeskDialog()');

  // R1-W3 Item 11: Customer UI order-action reason + optional image evidence -> single POST /api/order-actions + status notice in chat
  mockSessionRole = 'customer';
  mockOrders = [
    { id: 'O-101', customer_id: 'C-001', name: 'Áo thun Essential', variant: 'Trắng / M', amount: 299000, status: 'pending', version: 1, product_id: 'P-101' },
    { id: 'O-102', customer_id: 'C-001', name: 'Áo khoác Everyday', variant: 'Đen / L', amount: 520000, status: 'delivered', version: 2, product_id: 'P-102' }
  ];
  await run('canCancel = true; currentSessionRole = "customer"; conversationId = "fixture-conversation"; selected = "O-102"; refresh()');
  assert.ok(get('order-details').children.some(n => n.textContent === 'Yêu cầu trả / đổi hàng'));
  assert.ok(!get('order-details').children.some(n => n.textContent === 'Yêu cầu hủy đơn này'));

  const oaBeforePrepare = requests.filter(r => r.url === '/api/order-actions').length;
  await run('chooseReason("O-102", "exchange", "size")');
  // Opening reason UI creates ZERO requests!
  assert.equal(requests.filter(r => r.url === '/api/order-actions').length, oaBeforePrepare);

  const lastMsgRow = get('messages').children.at(-1);
  const oaCard = lastMsgRow.children.find(c => c && c.className && c.className.includes('order-action-card'));
  assert.ok(oaCard, 'Order action reason card must be rendered in chat');
  const radios = oaCard.querySelectorAll('input').filter(i => i.type === 'radio');
  assert.ok(radios.length >= 2);
  radios[0].onchange(); // Select 'wrong_size'
  const fileInput = oaCard.querySelectorAll('input').find(i => i.type === 'file');
  fileInput.files = [{ name: 'anh_size.jpg', type: 'image/jpeg', size: 2048 }];
  fileInput.onchange();
  const noteArea = oaCard.querySelectorAll('textarea')[0];
  noteArea.value = 'Áo hơi chật vai, muốn đổi lên XL';
  const submitBtn = oaCard.querySelectorAll('button').find(b => b.textContent === 'Xác nhận gửi yêu cầu');
  assert.equal(submitBtn.disabled, false);
  await submitBtn.onclick();

  const oaCalls = requests.filter(r => r.url === '/api/order-actions').slice(oaBeforePrepare);
  assert.equal(oaCalls.length, 1, 'Confirming must send exactly one POST /api/order-actions');
  const oaPayload = JSON.parse(oaCalls[0].options.body);
  assert.equal(oaPayload.order_id, 'O-102');
  assert.equal(oaPayload.type, 'exchange');
  assert.equal(oaPayload.exchange_kind, 'size');
  assert.equal(oaPayload.expected_order_version, 2);
  assert.equal(oaPayload.reason_code, 'wrong_size');
  assert.equal(oaPayload.reason_text, 'Áo hơi chật vai, muốn đổi lên XL');
  assert.equal(submitBtn.disabled, true);
  assert.equal(requests.filter(r => r.url === '/api/order-actions/oar_ui_fixture_1/evidence').length, 1);

  // Customer receives system_order_action status notice in chat!
  mockTranscriptResponse = {
    conversation: { id: 'fixture-conversation' },
    case: { case_id: 'case_ui_1', status: 'in_progress', version: 2, has_active_timer: false },
    turns: [
      {
        id: 901,
        messages: JSON.stringify([{ role: 'assistant', content: 'Yêu cầu đổi hàng (đổi size) của đơn O-102 đã được duyệt.' }]),
        result: JSON.stringify({ author: 'system_order_action', order_id: 'O-102', message: 'Yêu cầu đổi hàng (đổi size) của đơn O-102 đã được duyệt.' })
      }
    ],
    feedbacks: []
  };
  await run('pollHumanChat()');
  assert.ok(collectText(get('messages')).includes('Yêu cầu đổi hàng (đổi size) của đơn O-102 đã được duyệt.'));
  mockTranscriptResponse = null;

  // R1-W3 Item 12: Staff Desk "Thao tác ca" collapsible module (W3-D10), canned buttons removed, CSS/header layout, and role/state button matrix
  assert.ok(!indexHtml.includes('btn-approve-exchange-1to1') && !indexHtml.includes('btn-approve-exchange-size'), 'Canned exchange buttons must be removed from web/index.html');
  assert.ok(!indexHtml.includes('id="staff-action-bar"'), 'Old #staff-action-bar must be removed from web/index.html');
  assert.ok(!source.includes('approveExchange1to1') && !source.includes('approveExchangeSize'), 'Canned exchange handlers must be removed from web/app.js');
  const posHeader = indexHtml.indexOf('id="staff-chat-header"');
  const posModule = indexHtml.indexOf('id="staff-case-ops-module"');
  const posTranscript = indexHtml.indexOf('id="staff-chat-transcript"');
  assert.ok(posHeader > 0 && posModule > posHeader && posTranscript > posModule, '#staff-case-ops-module must sit between header and transcript');
  assert.ok(stylesCss.includes('#staff-case-ops-module .primary'), 'CSS must scope .primary inside #staff-case-ops-module');
  const staffHeaderCss = (stylesCss.match(/\.staff-chat-header\s*\{[^}]*\}/) || [''])[0];
  assert.ok(/flex-wrap\s*:\s*nowrap/i.test(staffHeaderCss), '.staff-chat-header must enforce single-row nowrap layout');

  mockStaffCaseTranscriptMap = {
    case_empty_oa: {
      conversation: { id: 'fixture-conversation' },
      case: { case_id: 'case_empty_oa', status: 'in_progress', holder: 'p_staff_1', holder_name: 'Khách B', version: 2 },
      read_only: false,
      turns: [],
      feedbacks: []
    },
    case_open_oa: {
      conversation: { id: 'fixture-conversation' },
      case: { case_id: 'case_open_oa', status: 'waiting', holder: null, holder_name: null, version: 1 },
      read_only: false,
      turns: [],
      feedbacks: []
    }
  };
  mockStaffCaseOrderActions = {
    case_empty_oa: {
      case_id: 'case_empty_oa',
      read_only: false,
      order_actions: [],
      customer_orders: []
    },
    case_open_oa: {
      case_id: 'case_open_oa',
      read_only: false,
      order_actions: [
        {
          request_id: 'oar_staff_1',
          order_id: 'O-102',
          case_id: 'case_open_oa',
          conversation_id: 'fixture-conversation',
          type: 'exchange',
          exchange_kind: 'size',
          status: 'requested',
          inspection_outcome: null,
          refund_status: 'not_applicable',
          refund_decision: null,
          reason_code: 'wrong_size',
          reason_label: 'Không vừa size / muốn đổi size',
          reason_text: 'Chật vai, xin đổi sang XL',
          raised_by_role: 'customer',
          delivery_failure_attempts: null,
          expected_order_version: 2,
          version: 1,
          closed_at: null,
          order: { id: 'O-102', name: 'Áo khoác Everyday', variant: 'Đen / L', amount: 520000, status: 'delivered', version: 2 },
          days_since_delivery: 4,
          delivery_age_label: '4 ngày kể từ khi giao',
          evidence: [{ evidence_id: 'ev_11111111111111111111111111111111', mime_type: 'image/jpeg', sha256: 'b'.repeat(64), purged: false, download_url: '/api/order-actions/oar_staff_1/evidence/ev_11111111111111111111111111111111' }],
          decisions: [{ decision_id: 'oad_1', action: 'submit', from_status: null, to_status: 'requested', actor_role: 'customer', note: 'Chật vai, xin đổi sang XL' }]
        }
      ],
      customer_orders: [
        { id: 'O-101', name: 'Áo thun Essential', variant: 'Trắng / M', amount: 299000, status: 'pending', version: 1 },
        { id: 'O-102', name: 'Áo khoác Everyday', variant: 'Đen / L', amount: 520000, status: 'delivered', version: 2 }
      ]
    }
  };

  mockSessionRole = 'staff';
  await run('openSession()');
  await run('openStaffDesk()');
  assert.equal(get('staff-case-ops-body').hidden, false);

  // Collapse module and verify localStorage persistence across cases without open requests
  get('btn-toggle-staff-case-ops').onclick();
  assert.equal(get('staff-case-ops-body').hidden, true);
  assert.equal(get('btn-toggle-staff-case-ops')['aria-expanded'], 'false');
  assert.equal(localStorage.getItem('retailops.staff.caseOpsCollapsed'), '1');

  await run('selectStaffTicket({ case_id: "case_empty_oa", conversation_id: "fixture-conversation", customer_id: "C-001", status: "in_progress", holder: "p_staff_1" })');
  assert.equal(get('staff-case-ops-body').hidden, true, 'Saved collapsed state must apply when case has no open request');

  // Selecting a case WITH an open order-action request auto-expands the module while preserving saved preference
  await run('selectStaffTicket({ case_id: "case_open_oa", conversation_id: "fixture-conversation", customer_id: "C-001", status: "waiting", holder: null })');
  assert.equal(get('staff-case-ops-body').hidden, false, 'Module must auto-expand when case has open order-action request');
  assert.equal(get('btn-toggle-staff-case-ops')['aria-expanded'], 'true');
  assert.equal(localStorage.getItem('retailops.staff.caseOpsCollapsed'), '1');

  const panelEl = get('staff-order-actions-panel');
  const panelTxtUnclaimed = collectText(panelEl);
  assert.ok(panelTxtUnclaimed.includes('Đơn O-102'));
  assert.ok(panelTxtUnclaimed.includes('Đổi hàng (Đổi size)'));
  assert.ok(panelTxtUnclaimed.includes('4 ngày kể từ khi giao'));
  assert.ok(panelTxtUnclaimed.includes('Lịch sử quyết định (1)'));
  assert.equal(panelEl.querySelectorAll('img').length, 1);
  // Unclaimed case: Staff cannot approve/reject before claiming!
  assert.equal(panelEl.querySelectorAll('button').filter(b => b.dataset.action === 'approve').length, 0);
  assert.ok(panelTxtUnclaimed.includes('Nhận ca để duyệt hoặc từ chối yêu cầu'));

  // Claim case -> Staff holds case -> can review customer exchange lifecycle + request refund + raise delivery-failure cancel
  mockStaffCaseTranscriptMap.case_open_oa.case = { case_id: 'case_open_oa', status: 'in_progress', holder: 'p_staff_1', holder_name: 'Khách B', version: 2 };
  mockStaffCaseOrderActions.case_open_oa.order_actions[0].status = 'under_review';
  await run('selectStaffTicket({ case_id: "case_open_oa", conversation_id: "fixture-conversation", customer_id: "C-001", status: "in_progress", holder: "p_staff_1" })');

  let approveBtn = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'approve');
  let rejectBtn = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'reject');
  assert.ok(approveBtn && rejectBtn, 'Holding staff must see Approve and Reject on customer request');
  await approveBtn.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].status, 'approved');

  // After approve on exchange -> mark-received & refund-request appear
  const markReceivedBtn = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'mark-received');
  const refundReqBtn = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'refund-request');
  assert.ok(markReceivedBtn && refundReqBtn, 'Approved exchange must show mark-received and refund-request');
  await markReceivedBtn.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].status, 'received');

  // After received -> inspection outcome select + mark-inspected appear
  const outcomeSel = panelEl.querySelectorAll('select').find(s => s.dataset.role === 'inspection-outcome');
  const markInspectedBtn = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'mark-inspected');
  assert.ok(outcomeSel && markInspectedBtn);
  outcomeSel.value = 'refund';
  await markInspectedBtn.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].status, 'inspected');
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].inspection_outcome, 'refund');

  // Staff submits manual refund request -> Staff must NOT see Manager-only refund-approve/reject buttons
  const refundReqBtn2 = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'refund-request');
  await refundReqBtn2.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].refund_status, 'pending');
  assert.equal(panelEl.querySelectorAll('button').filter(b => b.dataset.action === 'refund-approve').length, 0);
  assert.ok(collectText(panelEl).includes('Chờ Quản lý duyệt hoàn tiền'));

  // Staff creates delivery-failure cancel on pending order O-101 -> Staff must NOT see approve/reject on delivery-failure cancel (W3-D8)
  get('staff-df-order-select').value = 'O-101';
  get('staff-df-attempts-input').value = '2';
  get('staff-df-note-input').value = 'Bưu tá gọi 2 lần thuê bao không liên lạc được';
  await get('btn-create-delivery-failure').onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].request_id, 'oar_df_1');
  assert.ok(collectText(panelEl).includes('chưa có ngày giao'));
  assert.ok(collectText(panelEl).includes('Chờ Quản lý duyệt (yêu cầu hủy do giao thất bại)'));
  assert.equal(panelEl.querySelectorAll('button').filter(b => b.dataset.action === 'approve').length, 0);

  // Switch to Manager -> Manager sees approve/reject on delivery-failure cancel AND refund-decision / refund-outcome!
  mockSessionRole = 'manager';
  await run('openSession()');
  await run('selectStaffTicket({ case_id: "case_open_oa", conversation_id: "fixture-conversation", customer_id: "C-001", status: "in_progress", holder: "p_staff_1" })');
  const mgrApproveDf = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'approve');
  const mgrRefundApprove = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'refund-approve');
  assert.ok(mgrApproveDf, 'Manager must see approve button on delivery-failure cancel');
  assert.ok(mgrRefundApprove, 'Manager must see refund-approve button');
  await mgrApproveDf.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[0].status, 'approved');
  await panelEl.querySelectorAll('button').find(b => b.dataset.action === 'refund-approve').onclick();
  const mgrRefundOutcome = panelEl.querySelectorAll('button').find(b => b.dataset.action === 'refund-outcome-refunded');
  assert.ok(mgrRefundOutcome, 'Manager must see refund-outcome button after approving refund');
  await mgrRefundOutcome.onclick();
  assert.equal(mockStaffCaseOrderActions.case_open_oa.order_actions[1].refund_status, 'refunded');
  await run('closeStaffDeskDialog()');

  // R1-W3.1 Item 0 (W3.1-D4): Zero inline style="..." in HTML/JS templates, [hidden] rule, attachment & Manager button isolation
  assert.ok(!/\bstyle\s*=/i.test(indexHtml), 'web/index.html must not contain any style= attributes');
  assert.ok(!/\bstyle\s*=/i.test(source), 'web/app.js HTML strings must not contain any style= attributes');
  for (const extraJs of ['chat-focus.js', 'embed.js']) {
    const extraSrc = fs.readFileSync(path.join(__dirname, '../web', extraJs), 'utf8');
    assert.ok(!/\bstyle\s*=\s*["']/i.test(extraSrc), `${extraJs} must not contain any style="..." attributes`);
  }
  assert.ok(/\[hidden\]\s*\{\s*display\s*:\s*none\s*!important/i.test(stylesCss), 'styles.css must define [hidden] { display: none !important; }');

  // Manager session: Manager-only buttons visible, unused attachment controls hidden
  assert.equal(get('btn-open-manager-console').hidden, false);
  assert.equal(get('btn-sidebar-manager-nav').hidden, false);
  assert.equal(get('btn-panel-manager-banner').hidden, false);
  assert.equal(get('chat-file-input').hidden, true);
  assert.equal(get('attachment-preview').hidden, true);

  // Staff session: Manager-only buttons hidden
  mockSessionRole = 'staff';
  await run('openSession()');
  await run('closeStaffDeskDialog()');
  assert.equal(get('btn-open-manager-console').hidden, true);
  assert.equal(get('btn-sidebar-manager-nav').hidden, true);
  assert.equal(get('btn-panel-manager-banner').hidden, true);

  // Customer session: Manager-only buttons AND unused attachment controls hidden
  mockSessionRole = 'customer';
  await run('openSession()');
  assert.equal(get('btn-open-manager-console').hidden, true);
  assert.equal(get('btn-sidebar-manager-nav').hidden, true);
  assert.equal(get('btn-panel-manager-banner').hidden, true);
  assert.equal(get('chat-file-input').hidden, true);
  assert.equal(get('attachment-preview').hidden, true);
  assert.equal(get('btn-clear-order-search').hidden, true);
  assert.equal(get('order-tabs').hidden, true);

  // R1-W3.1 Item 1 (W3.1-D3): Case lifecycle milestones render as system lines in Customer UI & Staff Desk without browser duplicates
  const hasCls = (node, cls) => String(node?.className || '').split(/\s+/).includes(cls);
  get('messages').replaceChildren();
  run('renderedStaffTurnIds.clear(); isHumanMode = false;');
  await run('toggleHumanMode()');
  let custMilestoneRows = get('messages').children.filter(r => hasCls(r, 'case-milestone-notice'));
  assert.equal(custMilestoneRows.length, 1, 'toggleHumanMode must render exactly 1 system milestone line from DB notice');
  assert.equal(custMilestoneRows[0].dataset.milestone, 'handoff_requested');
  assert.equal(get('messages').children.filter(r => hasCls(r, 'assistant')).length, 0, 'Customer UI must not fabricate extra assistant bubble for handoff');

  // Polling transcript containing handoff(951), claim(952), release(953), resolve(955) renders each once and does not duplicate on resolve
  mockTranscriptResponse = {
    conversation: { id: 'fixture-conversation', order_id: null, product_id: null },
    case: { case_id: 'case_ui_1', status: 'resolved', version: 5, has_active_timer: false },
    turns: [
      { id: 951, request_id: 'sys-notice-handoff-hof_ui_1', messages: JSON.stringify([{ role: 'assistant', content: 'Đã gửi yêu cầu gặp nhân viên. Nhân viên CSKH sẽ phản hồi trong cuộc trò chuyện này.' }]), result: JSON.stringify({ author: 'system_case_notice', milestone: 'handoff_requested', message: 'Đã gửi yêu cầu gặp nhân viên. Nhân viên CSKH sẽ phản hồi trong cuộc trò chuyện này.' }) },
      { id: 952, request_id: 'sys-notice-claim-case_ui_1-v2', messages: JSON.stringify([{ role: 'assistant', content: 'Nhân viên Khách B đã nhận ca hỗ trợ.' }]), result: JSON.stringify({ author: 'system_case_notice', milestone: 'case_claimed', message: 'Nhân viên Khách B đã nhận ca hỗ trợ.' }) },
      { id: 953, request_id: 'sys-notice-release-case_ui_1-v3', messages: JSON.stringify([{ role: 'assistant', content: 'Nhân viên Khách B đã trả ca hỗ trợ về hàng chờ.' }]), result: JSON.stringify({ author: 'system_case_notice', milestone: 'case_released', message: 'Nhân viên Khách B đã trả ca hỗ trợ về hàng chờ.' }) },
      { id: 955, request_id: 'sys-notice-resolve-case_ui_1-v4', messages: JSON.stringify([{ role: 'assistant', content: 'Nhân viên Khách B đã hoàn tất và đóng ca hỗ trợ. Hệ thống chuyển lại Trợ lý AI.' }]), result: JSON.stringify({ author: 'system_case_notice', milestone: 'case_resolved', message: 'Nhân viên Khách B đã hoàn tất và đóng ca hỗ trợ. Hệ thống chuyển lại Trợ lý AI.' }) }
    ],
    feedbacks: [{ feedback_type: 'human_handoff', reason_code: 'resolved' }]
  };
  await run('pollHumanChat()');
  custMilestoneRows = get('messages').children.filter(r => hasCls(r, 'case-milestone-notice'));
  assert.equal(custMilestoneRows.length, 4, 'Customer polling must render all 4 milestone notices without duplicating 951');
  assert.equal(get('messages').children.filter(r => hasCls(r, 'assistant')).length, 0, 'Customer resolve polling must not draw duplicate browser assistant bubble');

  // Reloading conversation via loadConversation renders all 4 system milestones cleanly
  await run('loadConversation("fixture-conversation")');
  custMilestoneRows = get('messages').children.filter(r => hasCls(r, 'case-milestone-notice'));
  assert.equal(custMilestoneRows.length, 4, 'Customer reload must preserve all 4 persisted milestone notices');
  assert.deepEqual(
    custMilestoneRows.map(r => r.dataset.milestone),
    ['handoff_requested', 'case_claimed', 'case_released', 'case_resolved']
  );

  // Staff Desk transcript reload also renders all 4 system milestones as .case-milestone-notice
  mockSessionRole = 'staff';
  await run('openSession()');
  mockStaffCaseTranscriptMap = {
    case_milestones_1: {
      conversation: { id: 'fixture-conversation' },
      case: { case_id: 'case_milestones_1', status: 'resolved', holder: null, version: 4 },
      read_only: true,
      turns: mockTranscriptResponse.turns,
      feedbacks: []
    }
  };
  await run('refreshStaffTranscript("fixture-conversation", false, "case_milestones_1")');
  const staffMilestoneRows = get('staff-chat-transcript').children.filter(r => hasCls(r, 'case-milestone-notice'));
  assert.equal(staffMilestoneRows.length, 4, 'Staff Desk transcript must render all 4 persisted milestone notices');
  mockTranscriptResponse = null;

  mockSessionRole = 'customer';
  await run('openSession()');
  await get('logout').onclick();
  assert.equal(authenticated,false);assert.equal(reloaded,true);
  assert.equal(requests.at(-1).url,'/api/logout');
  console.log(persistent ? 'PERSISTENT_ACCOUNT_UI_FLOW_OK' : 'PUBLIC_COOKIE_UI_FLOW_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
