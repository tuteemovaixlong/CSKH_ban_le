// R1-W4 Item 6: Case Assistant UI tests inside Staff Desk "Thao tác ca" module (no external network).
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const indexHtml = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// 1. Static HTML & CSP checks (W3.1-D4 + W4 Item 6)
assert.ok(!/\bstyle\s*=/i.test(indexHtml), 'web/index.html must contain zero inline style attributes');
assert.ok(!/\bstyle\s*=/i.test(appJs), 'web/app.js must contain zero inline style attributes');
for (const requiredId of [
  'staff-case-assist-box',
  'btn-case-assist-summary',
  'btn-case-assist-draft',
  'staff-case-assist-input',
  'btn-case-assist-ask',
  'staff-case-assist-progress',
  'staff-case-assist-output',
  'btn-case-assist-insert'
]) {
  assert.ok(indexHtml.includes(`id="${requiredId}"`), `web/index.html must include #${requiredId}`);
}
const opsBodySection = (indexHtml.match(/<div class="staff-case-ops-body" id="staff-case-ops-body">[\s\S]*?<\/section>/) || [''])[0];
assert.ok(opsBodySection.includes('id="staff-case-assist-box"'), '#staff-case-assist-box must live inside #staff-case-ops-body');

// 2. Headless VM harness exercising real web/app.js
const nodes = new Map();
class Element {
  constructor(tag = '') {
    this.tagName = String(tag).toUpperCase();
    this._id = '';
    this.children = [];
    this.dataset = {};
    this.value = '';
    this.disabled = false;
    this.hidden = false;
    this.textContent = '';
    this.focused = false;
    this._classes = new Set();
    this.classList = {
      toggle: (cls, force) => {
        const add = force === undefined ? !this._classes.has(cls) : Boolean(force);
        if (add) this._classes.add(cls); else this._classes.delete(cls);
        return add;
      },
      add: (...cls) => cls.forEach(c => this._classes.add(c)),
      remove: (...cls) => cls.forEach(c => this._classes.delete(c)),
      contains: cls => this._classes.has(cls)
    };
  }
  get id() { return this._id; }
  set id(v) { this._id = String(v || ''); if (this._id) nodes.set(this._id, this); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return this.button ||= new Element('button'); }
  querySelectorAll() { return []; }
  before() {}
  after() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused = true; }
  setAttribute(k, v) { this[k] = v; }
  removeAttribute(k) { delete this[k]; }
  remove() {}
  addEventListener() {}
}

function collectText(node) {
  if (!node) return '';
  let out = String(node.textContent || '');
  for (const ch of (node.children || [])) {
    out += ' ' + collectText(ch);
  }
  return out;
}

const get = id => {
  if (!nodes.has(id)) {
    const el = new Element();
    el.id = id;
  }
  return nodes.get(id);
};

const document = {
  body: { dataset: { auth: 'cookie', dataMode: 'persistent-demo' } },
  getElementById: get,
  createElement: tag => new Element(tag),
  createTextNode: text => ({ textContent: String(text) }),
  querySelector: get,
  querySelectorAll: () => []
};

const storageMap = new Map();
const localStorage = {
  getItem: k => (storageMap.has(k) ? storageMap.get(k) : null),
  setItem: (k, v) => storageMap.set(k, String(v)),
  removeItem: k => storageMap.delete(k)
};

const requests = [];
let caseState = {
  case_id: 'case_w4_ui_1',
  conversation_id: 'conv_w4_ui_1',
  customer_id: 'C-001',
  customer_name: 'Khách Demo',
  order_id: 'O-101',
  status: 'waiting',
  holder: null,
  holder_name: null,
  version: 1
};
let mockAssistProgress = { active: false };
let pendingAssistDeferred = null;

const context = vm.createContext({
  document,
  console,
  Intl,
  Date,
  URLSearchParams,
  AbortSignal,
  localStorage,
  crypto: { randomUUID: () => 'w4-ui-req-id' },
  alert: () => {},
  requestAnimationFrame: fn => fn(),
  location: { reload() {} },
  fetch: async (url, options = {}) => {
    requests.push({ url, options });
    let status = 200;
    let body = {};
    if (url === '/api/session') {
      body = {
        name: 'Nhân viên Lan',
        principal_id: 'p_staff_lan',
        role: 'staff',
        tenant_id: 'shop-a',
        permissions: ['orders:read', 'staff:access']
      };
    } else if (url === '/api/providers') {
      body = { default_provider: 'api', providers: [{ id: 'api', model: 'gemma-4-12b', label: 'API', configured: true }] };
    } else if (url === '/api/orders') {
      body = { orders: [], scope: 'customer' };
    } else if (url === '/api/events') {
      body = { events: [] };
    } else if (url === '/api/conversations') {
      body = { conversations: [], conversation_id: 'conv_self', case_id: 'case_self', provider_id: 'api', context: {} };
    } else if (url === '/api/order-action-reasons') {
      body = { version: 1, role: 'staff', text_max_length: 500, reasons: [] };
    } else if (url === '/api/staff/cases') {
      body = {
        waiting: caseState.status === 'waiting' ? [caseState] : [],
        in_progress: caseState.status === 'in_progress' ? [caseState] : [],
        resolved: [],
        open_count: 1
      };
    } else if (url === '/api/staff/cases/case_w4_ui_1/messages') {
      body = {
        conversation: { id: 'conv_w4_ui_1' },
        case: { ...caseState },
        read_only: false,
        turns: [],
        feedbacks: []
      };
    } else if (url === '/api/staff/cases/case_w4_ui_1/order-actions') {
      body = { case_id: 'case_w4_ui_1', read_only: false, order_actions: [], customer_orders: [] };
    } else if (url === '/api/staff/cases/case_w4_ui_1/orders') {
      body = { case_id: 'case_w4_ui_1', read_only: false, orders: [], consent_turns: [] };
    } else if (url === '/api/staff/cases/case_w4_ui_1/claim') {
      caseState = { ...caseState, status: 'in_progress', holder: 'p_staff_lan', holder_name: 'Nhân viên Lan', version: 2 };
      body = { status: 'ok', claimed: true, case_id: 'case_w4_ui_1', case: { ...caseState } };
    } else if (url === '/api/staff/cases/case_w4_ui_1/assist' && (!options.method || options.method === 'GET')) {
      const heldByLan = caseState.status === 'in_progress' && caseState.holder === 'p_staff_lan';
      body = {
        case_id: 'case_w4_ui_1',
        can_assist: heldByLan,
        turns: []
      };
    } else if (url === '/api/staff/cases/case_w4_ui_1/assist/progress') {
      body = mockAssistProgress;
    } else if (url === '/api/staff/cases/case_w4_ui_1/assist' && options.method === 'POST') {
      const payload = JSON.parse(options.body || '{}');
      if (pendingAssistDeferred) {
        await pendingAssistDeferred;
      }
      if (payload.mode === 'summary') {
        body = {
          turn_id: 1,
          request_id: payload.request_id,
          case_id: 'case_w4_ui_1',
          mode: 'summary',
          answer: 'Khách hỏi đổi màu đơn O-101 đang ở trạng thái chờ xử lý.',
          draft_reply: null,
          sources: []
        };
      } else if (payload.mode === 'ask') {
        body = {
          turn_id: 2,
          request_id: payload.request_id,
          case_id: 'case_w4_ui_1',
          mode: 'ask',
          answer: 'Đơn O-101 hiện là pending nên chỉ hỗ trợ hủy đơn, chưa đổi trả.',
          draft_reply: null,
          sources: []
        };
      } else if (payload.mode === 'draft') {
        body = {
          turn_id: 3,
          request_id: payload.request_id,
          case_id: 'case_w4_ui_1',
          mode: 'draft',
          answer: 'Đã kiểm tra đơn O-101 cho nhân viên.',
          draft_reply: 'Chào anh/chị, đơn O-101 đang chờ xử lý nên bên em hỗ trợ hủy đơn để anh/chị đặt lại màu mong muốn ạ.',
          sources: []
        };
      }
    } else if (url === '/api/staff/reply') {
      body = { status: 'ok', turn_id: 501 };
    }
    return {
      ok: status < 400,
      status,
      headers: { get: () => 'application/json' },
      json: async () => body
    };
  }
});

vm.runInContext(appJs, context);
const run = code => vm.runInContext(code, context);

(async () => {
  await run('openSession()');
  await run('selectStaffTicket(' + JSON.stringify(caseState) + ')');

  // Unclaimed waiting case -> Staff cannot call Case Assistant yet
  assert.equal(get('btn-case-assist-summary').disabled, true, 'Unclaimed case must disable Summary for Staff');
  assert.equal(get('btn-case-assist-draft').disabled, true, 'Unclaimed case must disable Draft for Staff');
  assert.equal(get('btn-case-assist-ask').disabled, true, 'Unclaimed case must disable Ask for Staff');

  // Claim the case -> Case Assistant controls become active
  await get('btn-claim-ticket').onclick();
  assert.equal(get('btn-case-assist-summary').disabled, false, 'Claimed case must enable Summary for holder');
  assert.equal(get('btn-case-assist-draft').disabled, false, 'Claimed case must enable Draft for holder');
  assert.equal(get('btn-case-assist-ask').disabled, false, 'Claimed case must enable Ask for holder');

  // Summary calls POST /api/staff/cases/<case_id>/assist with mode='summary'
  await get('btn-case-assist-summary').onclick();
  const summaryCalls = requests.filter(r => r.url === '/api/staff/cases/case_w4_ui_1/assist' && r.options.method === 'POST');
  assert.equal(summaryCalls.length, 1);
  assert.equal(JSON.parse(summaryCalls[0].options.body).mode, 'summary');
  assert.ok(collectText(get('staff-case-assist-output')).includes('Khách hỏi đổi màu đơn O-101'));

  // Ask with progress polling (W3.2 style)
  let resolveDeferred;
  pendingAssistDeferred = new Promise(resolve => { resolveDeferred = resolve; });
  get('staff-case-assist-input').value = 'Đơn O-101 có đổi màu luôn được không?';
  const askPromise = get('btn-case-assist-ask').onclick();
  assert.equal(get('staff-case-assist-progress').hidden, false, 'Progress bar must appear while Case Assistant runs');
  mockAssistProgress = {
    active: true,
    phase: 'model',
    model_calls: 2,
    tools: [{ name: 'get_case_transcript', status: 'ok' }, { name: 'list_case_orders', status: 'ok' }]
  };
  await run('pollStaffCaseAssistProgress()');
  assert.ok(get('staff-case-assist-progress').textContent.includes('hội thoại ca → đơn hàng trong ca'));
  assert.ok(requests.some(r => r.url === '/api/staff/cases/case_w4_ui_1/assist/progress'));
  resolveDeferred();
  pendingAssistDeferred = null;
  await askPromise;

  assert.equal(get('staff-case-assist-progress').hidden, true, 'Progress bar must hide after turn completes');
  assert.equal(get('staff-case-assist-input').value, '', 'Question input clears after Ask succeeds');
  const askCalls = requests.filter(r => r.url === '/api/staff/cases/case_w4_ui_1/assist' && r.options.method === 'POST');
  assert.equal(askCalls.length, 2);
  const askBody = JSON.parse(askCalls[1].options.body);
  assert.equal(askBody.mode, 'ask');
  assert.equal(askBody.question, 'Đơn O-101 có đổi màu luôn được không?');

  // Draft + "Chèn vào ô trả lời" ONLY populates #staff-reply-input, NEVER sends /api/staff/reply!
  await get('btn-case-assist-draft').onclick();
  assert.equal(get('staff-case-assist-insert-bar').hidden, false);
  assert.equal(get('btn-case-assist-insert').disabled, false);

  const replyCallsBeforeInsert = requests.filter(r => r.url === '/api/staff/reply').length;
  get('staff-reply-input').focused = false;
  get('btn-case-assist-insert').onclick();

  assert.equal(
    get('staff-reply-input').value,
    'Chào anh/chị, đơn O-101 đang chờ xử lý nên bên em hỗ trợ hủy đơn để anh/chị đặt lại màu mong muốn ạ.'
  );
  assert.equal(get('staff-reply-input').focused, true);
  assert.equal(
    requests.filter(r => r.url === '/api/staff/reply').length,
    replyCallsBeforeInsert,
    '"Chèn vào ô trả lời" must NEVER call /api/staff/reply automatically'
  );

  console.log('CASE_ASSISTANT_UI_OK');
})().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
