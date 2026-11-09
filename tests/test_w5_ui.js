// Phase R1 W5 isolated UI & static contract tests (Items 0–6, §18 W5-D1..W5-D8, no external network).
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const WEB_DIR = path.join(ROOT, 'web');
const indexHtml = fs.readFileSync(path.join(WEB_DIR, 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(WEB_DIR, 'app.js'), 'utf8');
const embedJs = fs.readFileSync(path.join(WEB_DIR, 'embed.js'), 'utf8');

// ---------------------------------------------------------------------------
// 1. Static HTML / CSP / Sample-Prompt / Allowlist Checks (Items 0, 1, 2, 5, 6)
// ---------------------------------------------------------------------------
for (const fname of fs.readdirSync(WEB_DIR)) {
  const fpath = path.join(WEB_DIR, fname);
  if (fs.statSync(fpath).isFile()) {
    const content = fs.readFileSync(fpath, 'utf8');
    assert.ok(!content.includes('style="'), `web/${fname} must contain zero style=" attributes`);
  }
}
assert.ok(!/\bstyle\s*=/i.test(indexHtml), 'web/index.html must contain zero inline style attributes');
assert.ok(!/\bstyle\s*=/i.test(appJs), 'web/app.js must contain zero inline style attributes');

// Item 6 (W5-D8): Zero hardcoded O-101 in sample prompts / composer placeholders / embed.js
const suggestionsHtml = (indexHtml.match(/<div class="suggestions"[\s\S]*?<\/div>/) || [''])[0];
assert.ok(suggestionsHtml.length > 0, 'Composer suggestions bar must exist');
assert.ok(!suggestionsHtml.includes('O-101'), 'Sample prompt buttons in web/index.html must not contain O-101');
assert.ok(suggestionsHtml.includes('Kiểm tra đơn hàng gần nhất của tôi'), 'Sample prompt must use generic phrasing');
assert.ok(!embedJs.includes('O-101'), 'web/embed.js sample prompts must not contain O-101');
for (const deadSopOrder of ['O-301', 'O-302', 'O-303', 'O-304']) {
  assert.ok(!indexHtml.includes(deadSopOrder), `web/index.html must not hardcode ${deadSopOrder} on SOP buttons`);
  assert.ok(!appJs.includes(deadSopOrder), `web/app.js must not fall back to ${deadSopOrder} on SOP buttons`);
}

// Required W5 DOM IDs in web/index.html
for (const id of [
  'chat-send-btn',
  'btn-case-assist-stop',
  'btn-open-transfer-case',
  'staff-case-transfer-box',
  'staff-transfer-target-select',
  'btn-confirm-transfer-case',
  'btn-cancel-transfer-case',
  'tab-btn-order-actions',
  'manager-oa-needs-badge',
  'tab-content-order-actions',
  'btn-manager-oa-filter-needs-manager',
  'btn-manager-oa-filter-in-progress',
  'btn-manager-oa-filter-completed',
  'btn-manager-oa-filter-all',
  'manager-order-actions-tbody',
  'inspector-case-select',
  'inspector-tool-select',
  'inspector-args-input',
  'inspector-run-btn'
]) {
  assert.ok(indexHtml.includes(`id="${id}"`), `web/index.html must include #${id}`);
}

// Item 5 (W5-D4): Static HTML tool options must match exact 6 read-only allowlist (no request_human_support)
const inspectorSelectHtml = (indexHtml.match(/<select id="inspector-tool-select">[\s\S]*?<\/select>/) || [''])[0];
const htmlToolOptions = [...inspectorSelectHtml.matchAll(/value="([^"]+)"/g)].map(m => m[1]);
assert.deepEqual(
  htmlToolOptions,
  ['get_order', 'list_orders', 'track_shipment', 'check_inventory', 'search_knowledge', 'get_context'],
  'HTML #inspector-tool-select must match exact W5-D4 allowlist'
);
assert.ok(!inspectorSelectHtml.includes('request_human_support'), 'request_human_support must not appear in Tool Inspector');
assert.ok(!inspectorSelectHtml.includes('O-101') && !inspectorSelectHtml.includes('P-101'));

// ---------------------------------------------------------------------------
// 2. Headless VM Harness over real web/app.js
// ---------------------------------------------------------------------------
function createHarness(initialSession) {
  const nodes = new Map();
  class Element {
    constructor(tag = '') {
      this.tagName = String(tag).toUpperCase();
      this._id = '';
      this.className = '';
      this.children = [];
      this.dataset = {};
      this.value = '';
      this.disabled = false;
      this.hidden = false;
      this.open = false;
      this.textContent = '';
      this.innerHTML = '';
      this.title = '';
      this.type = '';
      this.focused = false;
      this.parentNode = null;
      this._attrs = new Map();
      this._classes = new Set();
      this.classList = {
        toggle: (cls, force) => {
          const add = force === undefined ? !this._classes.has(cls) : Boolean(force);
          if (add) this._classes.add(cls); else this._classes.delete(cls);
          return add;
        },
        add: (...cls) => cls.forEach(c => { if (c) this._classes.add(c); }),
        remove: (...cls) => cls.forEach(c => this._classes.delete(c)),
        contains: cls => this._classes.has(cls)
      };
    }
    get id() { return this._id; }
    set id(v) {
      this._id = String(v || '');
      if (this._id) nodes.set(this._id, this);
    }
    append(...items) {
      for (const item of items) {
        if (item && typeof item === 'object') {
          item.parentNode = this;
          if (item.id) nodes.set(item.id, item);
        }
        this.children.push(item);
      }
    }
    replaceChildren(...items) {
      for (const ch of this.children) {
        if (ch && typeof ch === 'object') ch.parentNode = null;
      }
      this.children = [];
      this.append(...items);
    }
    remove() {
      if (this.parentNode && Array.isArray(this.parentNode.children)) {
        this.parentNode.children = this.parentNode.children.filter(c => c !== this);
      }
      this.parentNode = null;
      if (this._id && nodes.get(this._id) === this) {
        nodes.delete(this._id);
      }
    }
    querySelector(sel) {
      if (sel && sel.startsWith('#')) return nodes.get(sel.slice(1)) || null;
      return this._qBtn ||= new Element('button');
    }
    querySelectorAll() { return []; }
    before() {}
    after() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
    focus() { this.focused = true; }
    scrollIntoView() {}
    setAttribute(k, v) { this._attrs.set(k, String(v)); this[k] = String(v); }
    getAttribute(k) { return this._attrs.has(k) ? this._attrs.get(k) : (this[k] ?? null); }
    removeAttribute(k) { this._attrs.delete(k); delete this[k]; }
    addEventListener() {}
  }

  function collectText(node) {
    if (!node) return '';
    if (typeof node === 'string') return node;
    let out = String(node.textContent || '');
    for (const ch of (node.children || [])) {
      out += ' ' + collectText(ch);
    }
    return out;
  }

  function findDescendants(node, pred, acc = []) {
    if (!node || typeof node !== 'object') return acc;
    if (pred(node)) acc.push(node);
    for (const ch of (node.children || [])) {
      findDescendants(ch, pred, acc);
    }
    return acc;
  }

  const get = id => {
    if (!nodes.has(id)) {
      const el = new Element('div');
      el.id = id;
    }
    return nodes.get(id);
  };

  // Pre-seed critical elements matching index.html defaults
  get('toggle-inspector').hidden = true;
  get('chat-send-btn').type = 'submit';
  get('btn-case-assist-stop').hidden = true;
  get('btn-open-transfer-case').hidden = true;
  get('staff-case-transfer-box').hidden = true;
  get('manager-oa-needs-badge').hidden = true;

  const bodyClasses = new Set();
  const document = {
    body: {
      dataset: { auth: 'cookie', dataMode: 'persistent-demo' },
      classList: {
        toggle: (cls, force) => {
          const add = force === undefined ? !bodyClasses.has(cls) : Boolean(force);
          if (add) bodyClasses.add(cls); else bodyClasses.delete(cls);
          return add;
        },
        add: (...c) => c.forEach(x => bodyClasses.add(x)),
        remove: (...c) => c.forEach(x => bodyClasses.delete(x)),
        contains: c => bodyClasses.has(c)
      }
    },
    getElementById: get,
    createElement: tag => {
      const e = new Element(tag);
      return e;
    },
    createTextNode: text => ({ textContent: String(text) }),
    querySelector: sel => (sel && sel.startsWith('#') ? get(sel.slice(1)) : get(sel)),
    querySelectorAll: sel => (sel === '.sop-action-btn' ? sopButtons : [])
  };
  const sopButtons = ['1', '2', '3', '4', '5', '6'].map(num => {
    const b = new Element('button');
    b.dataset.sop = num;
    return b;
  });

  const storageMap = new Map();
  const localStorage = {
    getItem: k => (storageMap.has(k) ? storageMap.get(k) : null),
    setItem: (k, v) => storageMap.set(k, String(v)),
    removeItem: k => storageMap.delete(k)
  };

  const state = {
    session: { ...initialSession },
    requests: [],
    chatDeferred: null,
    chatCancelled: false,
    assistDeferred: null,
    assistCancelled: false,
    resumeShouldFail: false,
    resolveAlreadyResolved: false,
    caseState: {
      case_id: 'case_w5_101',
      conversation_id: '11111111-2222-3333-4444-555555555555',
      handoff_id: 'hoff_w5_1',
      customer_id: 'C-001',
      customer_name: 'Lê Thị Hoa',
      order_id: 'O-888',
      status: 'waiting',
      holder: null,
      holder_name: null,
      version: 3
    },
    staffMembers: [
      { principal_id: 'p_staff_lan', display_name: 'Nhân viên Lan', role: 'staff' },
      { principal_id: 'p_staff_minh', display_name: 'Nhân viên Minh', role: 'staff' },
      { principal_id: 'p_mgr_hung', display_name: 'Quản lý Hùng', role: 'manager' }
    ],
    managerOrderActions: [
      {
        request_id: 'oar_w5_need_1',
        order_id: 'O-888',
        case_id: 'case_w5_101',
        customer_display_name: 'Lê Thị Hoa',
        type: 'return',
        exchange_kind: null,
        status: 'inspected',
        refund_status: 'pending',
        refund_decision: null,
        status_group: 'needs_manager',
        needs_manager: true,
        created_at: 1762330000,
        updated_at: 1762330500,
        closed_at: null
      },
      {
        request_id: 'oar_w5_done_2',
        order_id: 'O-889',
        case_id: 'case_w5_102',
        customer_display_name: 'Trần Văn Nam',
        type: 'cancel',
        exchange_kind: null,
        status: 'approved',
        refund_status: 'not_applicable',
        refund_decision: null,
        status_group: 'completed',
        needs_manager: false,
        created_at: 1762320000,
        updated_at: 1762320200,
        closed_at: 1762320200
      }
    ],
    convMessagesPayload: {
      conversation: { id: '22222222-3333-4444-5555-666666666666' },
      case: {
        case_id: 'case_cust_open',
        status: 'bot_active',
        has_active_timer: false
      },
      turns: [],
      feedbacks: []
    }
  };

  let uuidCounter = 0;
  const context = vm.createContext({
    document,
    console,
    Intl,
    Date,
    URLSearchParams,
    AbortSignal,
    setTimeout: () => 1,
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    localStorage,
    crypto: {
      randomUUID: () => `w5-uuid-00000000-${String(++uuidCounter).padStart(4, '0')}`
    },
    alert: () => {},
    confirm: () => true,
    requestAnimationFrame: fn => fn(),
    location: { reload() {} },
    fetch: async (url, options = {}) => {
      const method = options.method || 'GET';
      const parsedBody = options.body ? JSON.parse(options.body) : null;
      state.requests.push({ url, method, body: parsedBody });

      let httpStatus = 200;
      let resp = {};

      if (url === '/api/session') {
        resp = { ...state.session };
      } else if (url === '/api/providers') {
        resp = {
          default_provider: 'api',
          providers: [{ id: 'api', model: 'gemma-4-12b', label: 'API', configured: true }]
        };
      } else if (url === '/api/orders') {
        resp = { orders: [], scope: 'customer' };
      } else if (url === '/api/order-actions') {
        resp = { order_actions: [] };
      } else if (url === '/api/events') {
        resp = { events: [] };
      } else if (url === '/api/conversations' && method === 'GET') {
        resp = {
          conversations: [],
          conversation_id: '22222222-3333-4444-5555-666666666666',
          case_id: 'case_cust_open',
          provider_id: 'api',
          context: {}
        };
      } else if (url === '/api/conversations' && method === 'POST') {
        resp = {
          conversation_id: '22222222-3333-4444-5555-666666666666',
          case_id: 'case_cust_open',
          provider_id: 'api',
          context: {}
        };
      } else if (url.startsWith('/api/conversations/') && url.endsWith('/focus') && method === 'POST') {
        const oid = parsedBody.order_id;
        resp = {
          order: { id: oid, external_order_id: 'SIM-O-00115' },
          context: { order_id: oid },
          message: `Đã chọn đơn ${oid}.`,
          source: 'store_data'
        };
      } else if (url.startsWith('/api/conversations/') && url.endsWith('/messages')) {
        resp = state.convMessagesPayload;
      } else if (url.startsWith('/api/conversations/') && url.endsWith('/progress')) {
        resp = { active: true, phase: 'model', model_calls: 1, tools: [] };
      } else if (url.startsWith('/api/conversations/') && url.endsWith('/resume') && method === 'POST') {
        if (state.resumeShouldFail) {
          httpStatus = 500;
          resp = { error: 'resume_failed', message: 'Máy chủ tạm gián đoạn' };
        } else {
          resp = {
            status: 'ok',
            conversation_id: '22222222-3333-4444-5555-666666666666',
            case: { case_id: 'case_cust_reopened', status: 'bot_active', has_active_timer: false }
          };
        }
      } else if (url === '/api/chat' && method === 'POST') {
        if (state.chatDeferred) await state.chatDeferred;
        if (state.chatCancelled) {
          resp = {
            action: 'reply',
            cancelled: true,
            message: 'Bạn đã dừng câu trả lời.',
            source: 'user_cancelled',
            context: {},
            trace: { cancelled: true, stopped_at: 'after_model', steps: [], tools: [] }
          };
        } else {
          resp = {
            action: 'reply',
            cancelled: false,
            message: 'Câu trả lời hoàn chỉnh.',
            context: {},
            trace: { steps: [], tools: [] }
          };
        }
      } else if (url === '/api/chat/cancel' && method === 'POST') {
        state.chatCancelled = true;
        resp = { status: 'ok', cancelled: true, already_finished: false };
      } else if (url === '/api/order-action-reasons') {
        resp = { version: 1, role: state.session.role, text_max_length: 500, reasons: [] };
      } else if (url === '/api/staff/cases') {
        const c = state.caseState;
        const secondCase = {
          case_id: 'case_w5_102',
          conversation_id: '99999999-8888-7777-6666-555555555555',
          customer_id: 'C-002',
          customer_name: 'Trần Văn Nam',
          order_id: 'O-889',
          status: 'in_progress',
          holder: 'p_mgr_hung',
          holder_name: 'Quản lý Hùng',
          version: 1
        };
        resp = {
          waiting: c.status === 'waiting' ? [c] : [],
          in_progress: c.status === 'in_progress' ? [c, secondCase] : [secondCase],
          resolved: c.status === 'resolved' ? [c] : [],
          open_count: c.status === 'resolved' ? 1 : 2
        };
      } else if (url === '/api/staff/members') {
        resp = { members: state.staffMembers };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/messages$/)) {
        resp = {
          conversation: { id: state.caseState.conversation_id },
          case: { ...state.caseState },
          read_only: state.caseState.status === 'resolved',
          turns: [],
          feedbacks: []
        };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/order-actions$/)) {
        resp = { case_id: state.caseState.case_id, read_only: false, order_actions: [], customer_orders: [] };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/orders$/)) {
        resp = {
          case_id: state.caseState.case_id,
          read_only: false,
          orders: [
            { id: 'O-888', product_id: 'P-777', name: 'Áo khoác gió', variant: 'Xanh navy · Size L', status: 'delivered', version: 1 }
          ],
          consent_turns: []
        };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/claim$/) && method === 'POST') {
        state.caseState = {
          ...state.caseState,
          status: 'in_progress',
          holder: state.session.principal_id,
          holder_name: state.session.name,
          version: state.caseState.version + 1
        };
        resp = { status: 'ok', claimed: true, case_id: state.caseState.case_id, case: { ...state.caseState } };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/transfer$/) && method === 'POST') {
        const target = state.staffMembers.find(m => m.principal_id === parsedBody.to_principal_id);
        state.caseState = {
          ...state.caseState,
          holder: parsedBody.to_principal_id,
          holder_name: target ? target.display_name : parsedBody.to_principal_id,
          version: state.caseState.version + 1
        };
        resp = {
          status: 'ok',
          transferred: true,
          case_id: state.caseState.case_id,
          case: { ...state.caseState },
          notice_message: `Ca của bạn đã được chuyển cho ${state.caseState.holder_name}`
        };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/assist$/) && method === 'GET') {
        const canUse = state.session.role === 'manager' || (
          state.caseState.status === 'in_progress' && state.caseState.holder === state.session.principal_id
        );
        resp = { case_id: state.caseState.case_id, can_assist: canUse, turns: [] };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/assist\/progress$/)) {
        resp = { active: true, phase: 'model', model_calls: 1, tools: [] };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/assist\/cancel$/) && method === 'POST') {
        state.assistCancelled = true;
        resp = { status: 'ok', cancelled: true, already_finished: false };
      } else if (url.match(/^\/api\/staff\/cases\/[^/]+\/assist$/) && method === 'POST') {
        if (state.assistDeferred) await state.assistDeferred;
        if (state.assistCancelled) {
          resp = {
            turn_id: 99,
            request_id: parsedBody.request_id,
            case_id: state.caseState.case_id,
            mode: parsedBody.mode,
            cancelled: true,
            answer: 'Bạn đã dừng câu trả lời.',
            draft_reply: null,
            sources: []
          };
        } else {
          resp = {
            turn_id: 100,
            request_id: parsedBody.request_id,
            case_id: state.caseState.case_id,
            mode: parsedBody.mode,
            cancelled: false,
            answer: 'Đã phân tích ca hỗ trợ.',
            draft_reply: 'Chào chị Hoa, bên em hỗ trợ đơn O-888 ngay ạ.',
            sources: []
          };
        }
      } else if (url === '/api/staff/resolve' && method === 'POST') {
        state.caseState = { ...state.caseState, status: 'resolved', holder: null };
        resp = {
          status: 'ok',
          already_resolved: state.resolveAlreadyResolved,
          case: { ...state.caseState }
        };
      } else if (url.startsWith('/api/manager/order-actions')) {
        const qIndex = url.indexOf('?');
        const sp = new URLSearchParams(qIndex >= 0 ? url.slice(qIndex + 1) : '');
        const grp = sp.get('status_group') || 'all';
        const filtered = grp === 'all'
          ? state.managerOrderActions
          : state.managerOrderActions.filter(i => i.status_group === grp);
        resp = {
          items: filtered,
          order_actions: filtered,
          status_group: grp,
          total: filtered.length,
          limit: 50,
          offset: 0,
          has_more: false,
          counts: { needs_manager: 1, in_progress: 0, completed: 1, all: 2 }
        };
      } else if (url === '/api/manager/kpis') {
        resp = { total_orders: 2, pending_orders: 1, delivered_orders: 1, cancelled_orders: 0, total_revenue: 500000 };
      } else if (url === '/api/manager/products') {
        resp = { products: [] };
      } else if (url === '/api/manager/knowledge') {
        resp = { documents: [] };
      } else if (url === '/api/manager/orders') {
        resp = { orders: [] };
      } else if (url === '/api/manager/events') {
        resp = { events: [] };
      } else if (url === '/api/admin/accounts') {
        resp = { accounts: [] };
      } else if (url === '/api/tools/execute' && method === 'POST') {
        resp = {
          tool_name: parsedBody.tool_name,
          arguments: parsedBody.arguments,
          case_id: parsedBody.case_id,
          result: { ok: true, order_id: parsedBody.arguments?.order_id || null }
        };
      }

      return {
        ok: httpStatus < 400,
        status: httpStatus,
        headers: { get: () => 'application/json' },
        json: async () => resp
      };
    }
  });

  vm.runInContext(appJs, context);
  const run = code => vm.runInContext(code, context);
  return { get, nodes, state, run, collectText, findDescendants, sopButtons };
}

(async () => {
  // =========================================================================
  // SCENARIO A: Customer Role — Stop Button (Item 0) & Resume Case Button (Item 3)
  // =========================================================================
  {
    const h = createHarness({
      name: 'Khách Hoa',
      principal_id: 'p_cust_hoa',
      role: 'customer',
      tenant_id: 'shop-a',
      permissions: ['orders:read', 'orders:cancel']
    });
    await h.run('openSession()');

    // Item 5: Customer never sees Tool Inspector button
    assert.equal(h.get('toggle-inspector').hidden, true, 'Customer must not see #toggle-inspector');

    // Item 3: Open conversation does NOT show #btn-resume-case
    await h.run('loadConversation("22222222-3333-4444-5555-666666666666")');
    assert.equal(h.nodes.has('btn-resume-case'), false, '#btn-resume-case must not appear when case is open');

    // Item 0: Customer chat Stop button morphs during in-flight /api/chat, calls /api/chat/cancel, and reverts
    let releaseChat;
    h.state.chatDeferred = new Promise(resolve => { releaseChat = resolve; });
    h.get('message').value = 'Kiểm tra đơn hàng gần nhất của tôi';
    const sendPromise = h.run('send("Kiểm tra đơn hàng gần nhất của tôi")');

    // Let microtasks advance until /api/chat fetch is issued
    for (let i = 0; i < 10 && !h.state.requests.some(r => r.url === '/api/chat'); i++) {
      await Promise.resolve();
    }
    const sendBtn = h.get('chat-send-btn');
    assert.equal(sendBtn.type, 'button', 'Send button must switch to type="button" while chat is running');
    assert.equal(sendBtn.classList.contains('is-stop'), true, 'Send button must gain .is-stop class');
    assert.ok(sendBtn.textContent.includes('Dừng'), 'Send button must show "Dừng" label');

    // Click Stop -> calls POST /api/chat/cancel with conversation_id & request_id
    const cancelClickPromise = sendBtn.onclick({ preventDefault() {}, stopPropagation() {} });
    await cancelClickPromise;
    const chatReq = h.state.requests.find(r => r.url === '/api/chat');
    const cancelReqs = h.state.requests.filter(r => r.url === '/api/chat/cancel');
    assert.equal(cancelReqs.length, 1, 'Clicking Stop must call POST /api/chat/cancel once');
    assert.equal(cancelReqs[0].body.conversation_id, chatReq.body.conversation_id);
    assert.equal(cancelReqs[0].body.request_id, chatReq.body.request_id);

    releaseChat();
    h.state.chatDeferred = null;
    await sendPromise;

    assert.equal(sendBtn.type, 'submit', 'Send button must revert to type="submit" after turn settles');
    assert.equal(sendBtn.classList.contains('is-stop'), false, 'Send button must drop .is-stop after turn settles');
    assert.ok(h.collectText(h.get('messages')).includes('Bạn đã dừng câu trả lời.'));

    // Item 3 (W5-D5): Resolved conversation shows #btn-resume-case; error keeps button; 200 hides button
    h.state.convMessagesPayload = {
      conversation: { id: '22222222-3333-4444-5555-666666666666' },
      case: { case_id: 'case_cust_closed', status: 'resolved', has_active_timer: false },
      turns: [
        {
          id: 11,
          request_id: 'sys-notice-resolve-1',
          messages: '[]',
          result: JSON.stringify({
            author: 'system_case_notice',
            milestone: 'case_resolved',
            message: 'Ca hỗ trợ đã được đóng.'
          })
        }
      ],
      feedbacks: []
    };
    await h.run('loadConversation("22222222-3333-4444-5555-666666666666")');
    assert.equal(h.nodes.has('btn-resume-case'), true, '#btn-resume-case must appear on resolved case');
    const resumeBtn = h.get('btn-resume-case');
    assert.equal(resumeBtn.textContent, 'Tiếp tục');

    // Failure case -> shows error and keeps button enabled
    h.state.resumeShouldFail = true;
    await resumeBtn.onclick();
    assert.equal(h.nodes.has('btn-resume-case'), true, '#btn-resume-case must remain when resume fails');
    assert.equal(resumeBtn.disabled, false, '#btn-resume-case must re-enable after error');
    assert.ok(h.collectText(h.get('messages')).includes('Không thể mở lại ca hỗ trợ'));

    // Success case -> calls POST /api/conversations/<cid>/resume once and removes button
    h.state.resumeShouldFail = false;
    const resumeCallsBefore = h.state.requests.filter(r => r.url.endsWith('/resume')).length;
    await resumeBtn.onclick();
    const resumeCallsAfter = h.state.requests.filter(r => r.url.endsWith('/resume')).length;
    assert.equal(resumeCallsAfter - resumeCallsBefore, 1, 'Clicking Tiếp tục must call /resume once');
    assert.equal(h.nodes.has('btn-resume-case'), false, '#btn-resume-case must hide after 200 OK');
  }

  // =========================================================================
  // SCENARIO B: Staff Role — Inspector Hidden (Item 5), Locked Titles (Item 6),
  //             Case Assist Stop (Item 0), Direct Transfer (Item 1), Idempotent Resolve (Item 4)
  // =========================================================================
  {
    const h = createHarness({
      name: 'Nhân viên Lan',
      principal_id: 'p_staff_lan',
      role: 'staff',
      tenant_id: 'shop-a',
      permissions: ['orders:read', 'staff:access']
    });
    await h.run('openSession()');

    // Item 5 (W5-D4): Staff NEVER sees #toggle-inspector
    assert.equal(h.get('toggle-inspector').hidden, true, 'Staff must NEVER see #toggle-inspector');

    // Item 6 (W5-D7): Before selecting any case, Case Assistant buttons are disabled with clear title
    await h.run('syncStaffCaseAssistControls()');
    assert.equal(h.get('btn-case-assist-summary').disabled, true);
    assert.ok(h.get('btn-case-assist-summary').title.length > 0, 'Unselected case must set non-empty title');

    // Select unclaimed waiting case -> Transfer hidden, Case Assistant locked with "Nhận ca" title & .is-locked hint
    await h.run('selectStaffTicket(' + JSON.stringify(h.state.caseState) + ')');
    assert.equal(h.get('btn-open-transfer-case').hidden, true, 'Waiting case must hide Chuyển ca button');
    assert.equal(h.get('btn-case-assist-summary').disabled, true);
    assert.ok(
      h.get('btn-case-assist-summary').title.includes('Nhận ca'),
      `Waiting case title should mention "Nhận ca", got: ${h.get('btn-case-assist-summary').title}`
    );
    assert.equal(h.get('staff-case-assist-hint').classList.contains('is-locked'), true);

    // Held by ANOTHER staff -> Transfer hidden for non-holder Staff, title explains who holds the case
    const heldByOther = { ...h.state.caseState, status: 'in_progress', holder: 'p_staff_minh', holder_name: 'Nhân viên Minh' };
    h.state.caseState = heldByOther;
    await h.run('selectStaffTicket(' + JSON.stringify(heldByOther) + ')');
    assert.equal(h.get('btn-open-transfer-case').hidden, true, 'Non-holder Staff must NOT see Chuyển ca button');
    assert.equal(h.get('btn-case-assist-draft').disabled, true);
    assert.ok(h.get('btn-case-assist-draft').title.includes('Nhân viên Minh'));

    // Claim case as Lan -> Transfer button visible, Case Assistant enabled with empty lock title
    h.state.caseState = { ...h.state.caseState, status: 'waiting', holder: null, holder_name: null };
    await h.run('selectStaffTicket(' + JSON.stringify(h.state.caseState) + ')');
    await h.get('btn-claim-ticket').onclick();
    assert.equal(h.get('btn-open-transfer-case').hidden, false, 'Holder Staff must see Chuyển ca button');
    assert.equal(h.get('btn-case-assist-summary').disabled, false);
    assert.equal(h.get('btn-case-assist-summary').title, '');
    assert.equal(h.get('staff-case-assist-hint').classList.contains('is-locked'), false);

    // Item 0 (W5-D3): Case Assistant Stop button during in-flight /assist
    let releaseAssist;
    h.state.assistDeferred = new Promise(resolve => { releaseAssist = resolve; });
    const assistPromise = h.get('btn-case-assist-draft').onclick();
    for (let i = 0; i < 10 && !h.state.requests.some(r => r.url.endsWith('/assist') && r.method === 'POST'); i++) {
      await Promise.resolve();
    }
    const stopAssistBtn = h.get('btn-case-assist-stop');
    assert.equal(stopAssistBtn.hidden, false, '#btn-case-assist-stop must be visible while Case Assistant runs');

    await stopAssistBtn.onclick();
    const assistPostReq = h.state.requests.find(r => r.url.endsWith('/assist') && r.method === 'POST');
    const assistCancelReqs = h.state.requests.filter(r => r.url.endsWith('/assist/cancel'));
    assert.equal(assistCancelReqs.length, 1, 'Clicking Stop in Case Assistant must call /assist/cancel');
    assert.equal(assistCancelReqs[0].body.request_id, assistPostReq.body.request_id);

    releaseAssist();
    h.state.assistDeferred = null;
    await assistPromise;

    assert.equal(stopAssistBtn.hidden, true, '#btn-case-assist-stop must hide once turn finishes');
    assert.equal(
      h.get('staff-case-assist-insert-bar').hidden,
      true,
      'Cancelled Case Assistant turn must NOT expose "Bạn đã dừng câu trả lời." for insertion into reply box'
    );

    // Item 1 (W5-D2): Holder opens Transfer box -> loads /api/staff/members excluding self -> confirms transfer
    await h.get('btn-open-transfer-case').onclick();
    assert.equal(h.get('staff-case-transfer-box').hidden, false);
    const targetOpts = h.get('staff-transfer-target-select').children.map(o => o.value).filter(Boolean);
    assert.ok(!targetOpts.includes('p_staff_lan'), 'Current holder must be excluded from transfer dropdown');
    assert.deepEqual(targetOpts, ['p_staff_minh', 'p_mgr_hung']);

    h.get('staff-transfer-target-select').value = 'p_staff_minh';
    const expectedVersion = h.state.caseState.version;
    await h.get('btn-confirm-transfer-case').onclick();
    const txReqs = h.state.requests.filter(r => r.url === '/api/staff/cases/case_w5_101/transfer');
    assert.equal(txReqs.length, 1);
    assert.deepEqual(txReqs[0].body, { to_principal_id: 'p_staff_minh', version: expectedVersion });
    // After transfer to Minh, Lan is no longer holder -> Transfer button hides
    assert.equal(h.get('btn-open-transfer-case').hidden, true);

    // Item 4 (W5-D6): Second resolve returning already_resolved: true succeeds cleanly
    h.state.resolveAlreadyResolved = true;
    await h.get('btn-resolve-ticket').onclick();
    assert.ok(h.state.requests.some(r => r.url === '/api/staff/resolve'));
    assert.ok(h.get('btn-case-assist-summary').title.includes('đã đóng'));
  }

  // =========================================================================
  // SCENARIO C: Manager Role — Order-Actions Queue Tab (Item 2), Transfer Override (Item 1),
  //             and Manager-only Case-Bound Tool Inspector (Item 5)
  // =========================================================================
  {
    const h = createHarness({
      name: 'Quản lý Hùng',
      principal_id: 'p_mgr_hung',
      role: 'manager',
      tenant_id: 'shop-a',
      permissions: ['orders:read', 'orders:cancel', 'staff:access', 'manager:access']
    });
    await h.run('openSession()');

    // Item 5 (W5-D4): Manager sees #toggle-inspector, allowlist has exact 6 tools, sample args come from selected case
    assert.equal(h.get('toggle-inspector').hidden, false, 'Manager must see #toggle-inspector');
    await h.get('toggle-inspector').onclick();
    assert.equal(h.get('inspector-dialog').open, true);

    const runtimeToolValues = h.get('inspector-tool-select').children.map(o => o.value);
    assert.deepEqual(
      runtimeToolValues,
      ['get_order', 'list_orders', 'track_shipment', 'check_inventory', 'search_knowledge', 'get_context']
    );
    // Auto-selected first in_progress case (case_w5_102), then switch to case_w5_101 -> fetches /orders -> O-888 / P-777 (zero O-101 / P-101)
    assert.equal(h.get('inspector-case-select').value, 'case_w5_102');
    h.get('inspector-case-select').value = 'case_w5_101';
    await h.get('inspector-case-select').onchange();
    assert.equal(h.get('inspector-case-select').value, 'case_w5_101');
    const getOrderSample = JSON.parse(h.get('inspector-args-input').value);
    assert.deepEqual(getOrderSample, { order_id: 'O-888' });

    h.get('inspector-tool-select').value = 'check_inventory';
    h.get('inspector-tool-select').onchange();
    const invSample = JSON.parse(h.get('inspector-args-input').value);
    assert.equal(invSample.product_id, 'P-777');
    assert.equal(invSample.size, 'L');
    assert.equal(invSample.color, 'Xanh navy');
    assert.ok(!JSON.stringify(invSample).includes('P-101'));

    await h.get('inspector-run-btn').onclick();
    const execReqs = h.state.requests.filter(r => r.url === '/api/tools/execute');
    assert.equal(execReqs.length, 1);
    assert.equal(execReqs[0].body.case_id, 'case_w5_101');
    assert.equal(execReqs[0].body.tool_name, 'check_inventory');

    // Item 2 (W5-D1): Manager Console "📝 Yêu cầu đơn hàng" tab shows needs_manager badge, zero approval buttons,
    // filters by needs_manager, and clicking a row opens Staff Desk on that exact case_id!
    await h.run('switchManagerTab("order-actions")');
    assert.equal(h.get('manager-oa-needs-badge').hidden, false);
    assert.equal(h.get('manager-oa-needs-badge').textContent, '1');
    assert.equal(h.get('manager-order-actions-tbody').children.length, 2);

    // Verify zero approval/reject buttons inside the Manager Console Order-Actions table
    const buttonsInQueue = h.findDescendants(h.get('manager-order-actions-tbody'), n => n.tagName === 'BUTTON');
    assert.equal(buttonsInQueue.length, 0, 'Manager Order-Actions queue must NOT duplicate approval buttons');

    // Filter to needs_manager -> 1 row (oar_w5_need_1 -> case_w5_101)
    await h.get('btn-manager-oa-filter-needs-manager').onclick();
    assert.equal(h.get('manager-order-actions-tbody').children.length, 1);
    const needRow = h.get('manager-order-actions-tbody').children[0];
    assert.ok(h.collectText(needRow).includes('oar_w5_need_1'));
    assert.ok(h.collectText(needRow).includes('Lê Thị Hoa'));

    // Click row -> opens Staff Desk with exact case_id = case_w5_101; Manager also sees Chuyển ca even if held by Minh
    h.state.caseState = {
      ...h.state.caseState,
      case_id: 'case_w5_101',
      status: 'in_progress',
      holder: 'p_staff_minh',
      holder_name: 'Nhân viên Minh',
      version: 5
    };
    await needRow.onclick();
    assert.equal(h.get('staff-desk-dialog').open, true, 'Row click must open Staff Desk');
    assert.equal(h.run('activeStaffTicket && activeStaffTicket.case_id'), 'case_w5_101');
    assert.equal(h.get('btn-open-transfer-case').hidden, false, 'Manager must see Chuyển ca on any in_progress case');

    // SOP buttons require a selected order instead of falling back to O-301..O-304
    h.run('selected = null; orders = [{ id: "ord_sim_115", external_order_id: "SIM-O-00115" }];');
    const focusBefore = h.state.requests.filter(r => r.url.endsWith('/focus')).length;
    await h.sopButtons[0].onclick();
    await h.sopButtons[1].onclick();
    assert.equal(
      h.state.requests.filter(r => r.url.endsWith('/focus')).length,
      focusBefore,
      'SOP 1/2 must not call /focus when no order is selected'
    );
    assert.ok(
      h.collectText(h.get('messages')).includes('Vui lòng chọn một đơn hàng'),
      'SOP button without selected order must ask user to select an order'
    );

    h.run('selected = "ord_sim_115"; orders = [{ id: "ord_sim_115", external_order_id: "SIM-O-00115" }];');
    await h.sopButtons[0].onclick();
    const focusReqs = h.state.requests.filter(r => r.url.endsWith('/focus'));
    assert.equal(focusReqs.length, focusBefore + 1, 'SOP 1 with selected order must call /focus once');
    assert.equal(focusReqs.at(-1).body.order_id, 'ord_sim_115');
    assert.ok(h.collectText(h.get('messages')).includes('SOP 1'));
  }

  console.log('W5_UI_OK');
})().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
