'use strict';
// Phase R1 W6.1b-1.1 Item 3 JS UI contract tests (D8 external_order_id, customer card privacy,
// shipping status chip, Staff Desk dual IDs, and shipment card "Đã giao lúc" + VN time).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const indexHtml = fs.readFileSync('web/index.html', 'utf8');
const appJs = fs.readFileSync('web/app.js', 'utf8');

class Element {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this._classes = new Set();
    this.classList = {
      add: (...cs) => cs.forEach(c => c && this._classes.add(c)),
      remove: (...cs) => cs.forEach(c => this._classes.delete(c)),
      toggle: (c, force) => {
        const next = force === undefined ? !this._classes.has(c) : Boolean(force);
        if (next) this._classes.add(c); else this._classes.delete(c);
        return next;
      },
      contains: c => this._classes.has(c),
    };
  }
  get className() { return [...this._classes].join(' '); }
  set className(val) {
    this._classes = new Set(String(val || '').split(/\s+/).filter(Boolean));
  }
  append(...nodes) {
    for (const n of nodes) {
      if (n !== null && n !== undefined) this.children.push(typeof n === 'string' ? { textContent: n } : n);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  setAttribute(k, v) { this[k] = String(v); }
  getAttribute(k) { return this[k]; }
  removeAttribute(k) { delete this[k]; }
  remove() {}
  before() {}
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  querySelector() { return new Element('button'); }
  querySelectorAll() { return []; }
  set innerHTML(val) {
    this._innerHTML = String(val || '');
    this.children = [];
  }
  get innerHTML() { return this._innerHTML || ''; }
}

const collectText = node => {
  if (!node) return '';
  return [node.textContent || '', ...(node.children || []).map(collectText)].join(' ').replace(/\s+/g, ' ').trim();
};

function createHarness(chipEntries) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, new Element('div'));
    return nodes.get(id);
  };
  const filterChipEls = chipEntries.map(([filterKey, label]) => {
    const btn = new Element('button');
    btn.className = filterKey === 'all' ? 'filter-chip active' : 'filter-chip';
    btn.dataset.filter = filterKey;
    btn.textContent = label;
    return btn;
  });

  const state = { mockTranscriptPayload: null };
  const context = vm.createContext({
    document: {
      body: { dataset: { auth: 'cookie', dataMode: 'persistent-demo' } },
      getElementById: get,
      createElement: t => new Element(t),
      createTextNode: t => ({ textContent: String(t) }),
      querySelector: sel => get(sel),
      querySelectorAll: sel => (sel === '.filter-chip' ? filterChipEls : []),
      addEventListener: () => {},
    },
    window: { addEventListener: () => {}, matchMedia: () => ({ matches: false, addEventListener: () => {} }) },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    console,
    Intl,
    Date,
    URLSearchParams,
    AbortSignal,
    requestAnimationFrame: fn => fn(),
    setTimeout: () => 1,
    clearTimeout: () => {},
    crypto: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
    fetch: async url => {
      if (String(url).endsWith('/messages')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => state.mockTranscriptPayload,
        };
      }
      if (String(url).includes('/order-actions') || String(url).includes('/assist')) {
        return {
          ok: true,
          status: 200,
          headers: { get: () => 'application/json' },
          json: async () => ({ order_actions: [], customer_orders: [], turns: [], can_assist: false }),
        };
      }
      throw new Error('Unexpected fetch in Item 3 UI test: ' + url);
    },
  });

  vm.runInContext(appJs, context);
  return { context, get, filterChipEls, state, run: code => vm.runInContext(code, context) };
}

(async () => {
  const sampleOrders = [
    {
      id: 'ord_5aeef27f000000000000000000000101',
      external_order_id: 'SIM-O-00101',
      customer_id: 'cust_2f1b99887766',
      name: 'Áo sơ mi Oxford',
      variant: 'Trắng / M',
      amount: 299000,
      status: 'pending',
      version: 1,
    },
    {
      id: 'ord_5aeef27f000000000000000000000102',
      external_order_id: 'SIM-O-00102',
      customer_id: 'cust_2f1b99887766',
      name: 'Quần tây công sở',
      variant: 'Đen / L',
      amount: 520000,
      status: 'shipping',
      version: 3,
    },
    {
      id: 'ord_5aeef27f000000000000000000000103',
      external_order_id: 'SIM-O-00103',
      customer_id: 'cust_2f1b99887766',
      name: 'Đầm chữ A',
      variant: 'Be / S',
      amount: 650000,
      status: 'delivered',
      version: 5,
    },
  ];

  const chipBlockMatch = indexHtml.match(/<div[^>]*id="order-filter-chips"[^>]*>([\s\S]*?)<\/div>/);
  const chipMatches = chipBlockMatch
    ? [...chipBlockMatch[1].matchAll(/<button[^>]*data-filter="([^"]+)"[^>]*>([^<]+)<\/button>/g)].map(m => [m[1], m[2].trim()])
    : [];
  const chipMap = Object.fromEntries(chipMatches);
  const h = createHarness(chipMatches);

  const failures = [];
  async function check(name, fn) {
    try {
      await fn();
    } catch (err) {
      failures.push(`${name}: ${err.message.split('\n')[0]}`);
    }
  }

  // (b) Context bar "Đang trao đổi" uses external_order_id for Customer and dual ID for Manager (focus & restore)
  await check('3b_context_bar_customer_and_manager', async () => {
    h.context.__sampleOrders = sampleOrders;
    h.run(`
      currentSessionRole = 'customer';
      orderScope = 'customer';
      orders = __sampleOrders.map(o => ({ ...o }));
      showContext({
        order_id: 'ord_5aeef27f000000000000000000000102',
        external_order_id: 'SIM-O-00102',
        product_id: 'P-102'
      });
    `);
    assert.equal(h.get('conversation-context').textContent, 'Đang trao đổi: SIM-O-00102');
    assert.ok(!h.get('conversation-context').textContent.includes('ord_'));

    h.state.mockTranscriptPayload = {
      conversation: {
        id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        provider_id: 'custom',
        order_id: 'ord_5aeef27f000000000000000000000103',
        external_order_id: 'SIM-O-00103',
        product_id: 'P-202',
      },
      case: { case_id: 'case_hist_1', status: 'waiting' },
      turns: [],
    };
    await h.run('loadConversation("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")');
    assert.equal(h.get('conversation-context').textContent, 'Đang trao đổi: SIM-O-00103');

    h.run(`
      currentSessionRole = 'manager';
      orderScope = 'store_all';
      showContext({
        order_id: 'ord_5aeef27f000000000000000000000103',
        external_order_id: 'SIM-O-00103',
        product_id: 'P-202'
      });
    `);
    assert.equal(
      h.get('conversation-context').textContent,
      'Đang trao đổi: SIM-O-00103 (ord_5aeef27f000000000000000000000103)'
    );
    await h.run('loadConversation("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")');
    assert.equal(
      h.get('conversation-context').textContent,
      'Đang trao đổi: SIM-O-00103 (ord_5aeef27f000000000000000000000103)'
    );
  });

  // (c) Customer order tab hides cust_* and "Phiên bản"; Manager (store_all) retains them
  await check('3c_customer_hides_cust_and_version_manager_retains', async () => {
    h.context.__sampleOrders = sampleOrders;
    h.run(`
      currentSessionRole = 'customer';
      orderScope = 'customer';
      managerFilter = 'all';
      orders = __sampleOrders.map(o => ({ ...o }));
      selected = 'ord_5aeef27f000000000000000000000103';
      renderOrder();
    `);
    const custCards = collectText(h.get('order-card-list'));
    const custDetails = collectText(h.get('order-details'));
    assert.ok(!custCards.includes('cust_'), 'Customer order cards leaked cust_*');
    assert.ok(!custDetails.includes('cust_'), 'Customer order details leaked cust_*');
    assert.ok(!custDetails.includes('Phiên bản'), 'Customer order details leaked Phiên bản');

    h.run(`
      currentSessionRole = 'manager';
      orderScope = 'store_all';
      renderOrder();
    `);
    const mgrCards = collectText(h.get('order-card-list'));
    const mgrDetails = collectText(h.get('order-details'));
    assert.ok(mgrCards.includes('cust_2f1b99887766'));
    assert.ok(mgrDetails.includes('cust_2f1b99887766'));
    assert.ok(mgrDetails.includes('Phiên bản 5'));
  });

  // (d) Filter chips include 'shipping' ("Đang giao") and 'delivered' ("Đã giao") and filter properly
  await check('3d_filter_chips_shipping_and_delivered_label', async () => {
    assert.equal(chipMap.shipping, 'Đang giao', 'Missing shipping chip "Đang giao"');
    assert.equal(chipMap.delivered, 'Đã giao', 'Delivered chip must say "Đã giao"');
    const shippingChip = h.filterChipEls.find(b => b.dataset.filter === 'shipping');
    const allChip = h.filterChipEls.find(b => b.dataset.filter === 'all');
    assert.ok(shippingChip && typeof shippingChip.onclick === 'function');
    h.run(`orderScope = 'customer'; currentSessionRole = 'customer';`);
    shippingChip.onclick();
    assert.equal(h.get('order-card-list').children.length, 1);
    assert.ok(collectText(h.get('order-card-list')).includes('SIM-O-00102'));
    allChip.onclick();
    assert.equal(h.get('order-card-list').children.length, 3);
  });

  // (e) Staff Desk queue card & open case header show dual order IDs via formatDualOrderId
  await check('3e_staff_desk_dual_order_id', async () => {
    const staffCase = {
      case_id: 'case_sd_202',
      conversation_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      customer_id: 'cust_2f1b99887766',
      customer_name: 'Trần Thị Mai',
      order_id: 'ord_5aeef27f000000000000000000000102',
      external_order_id: 'SIM-O-00102',
      status: 'waiting',
      holder: null,
      comment: 'Hỏi vận đơn đang giao',
      updated_at: 1794236400,
    };
    h.context.__staffCase = staffCase;
    h.state.mockTranscriptPayload = {
      conversation: {
        id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        customer_id: 'cust_2f1b99887766',
        customer_name: 'Trần Thị Mai',
        order_id: 'ord_5aeef27f000000000000000000000102',
        external_order_id: 'SIM-O-00102',
      },
      case: { case_id: 'case_sd_202', status: 'waiting', holder: null, holder_name: null, version: 1 },
      read_only: false,
      turns: [],
    };
    h.run(`
      staffQueueBucket = 'waiting';
      staffDeskData = { waiting: [__staffCase], in_progress: [], resolved: [], open_count: 1 };
      renderStaffBucketList();
    `);
    const queueText = collectText(h.get('staff-queue-list'));
    assert.ok(
      queueText.includes('SIM-O-00102 (ord_5aeef27f000000000000000000000102)'),
      'Queue card missing dual order ID: ' + queueText
    );
    await h.run('selectStaffTicket(__staffCase)');
    const activeHeader = h.get('staff-active-customer').textContent;
    assert.ok(
      activeHeader.includes('SIM-O-00102 (ord_5aeef27f000000000000000000000102)'),
      'Active case header missing dual order ID: ' + activeHeader
    );
  });

  // (f) Shipment card shows "Đã giao lúc" for delivered, "Dự kiến nhận" for non-delivered, HH:mm dd/MM/yyyy VN time
  await check('3f_shipment_card_delivered_label_and_vn_time', async () => {
    const renderShipment = shipment => {
      h.context.__shipRow = new Element('div');
      h.context.__shipData = shipment;
      h.run('showShipment(__shipRow, __shipData)');
      return collectText(h.context.__shipRow);
    };
    const deliveredText = renderShipment({
      carrier: 'GHTK',
      tracking_code: 'GHTK-DEL-001',
      status: 'delivered',
      carrier_status_raw: 'delivered',
      status_text: 'Đã giao thành công',
      current_area: 'Quận Hải Châu, Đà Nẵng',
      estimated_delivery_at: '2026-11-05T12:00:00+07:00',
      delivered_at: '2026-11-04T09:17:26Z',
      delivery_attempts: 1,
      events: [
        { occurred_at: '2026-11-04T08:05:00+07:00', location: 'Kho Đà Nẵng', description: 'Bắt đầu giao hàng' },
        { occurred_at: '2026-11-04T16:17:26+07:00', location: 'Quận Hải Châu, Đà Nẵng', description: 'Giao hàng thành công' },
      ],
    });
    assert.ok(deliveredText.includes('Đã giao lúc'), 'Delivered shipment missing "Đã giao lúc": ' + deliveredText);
    assert.ok(!deliveredText.includes('Dự kiến nhận'), 'Delivered shipment still shows "Dự kiến nhận"');
    assert.ok(deliveredText.includes('16:17 04/11/2026'));
    assert.ok(deliveredText.includes('08:05 04/11/2026'));
    assert.doesNotMatch(deliveredText, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);

    const inTransitText = renderShipment({
      carrier: 'GHN',
      tracking_code: 'GHN-SHIP-002',
      status: 'out_for_delivery',
      carrier_status_raw: 'delivering',
      status_text: 'Đang giao hàng',
      current_area: 'Quận 7, TP.HCM',
      estimated_delivery_at: '2026-11-09T17:30:00+07:00',
      delivered_at: null,
      delivery_attempts: 0,
      events: [
        { occurred_at: '2026-11-09T09:45:00+07:00', location: 'Bưu cục Quận 7, TP.HCM', description: 'Nhân viên đang giao hàng' },
      ],
    });
    assert.ok(inTransitText.includes('Dự kiến nhận'));
    assert.ok(!inTransitText.includes('Đã giao lúc'));
    assert.ok(inTransitText.includes('17:30 09/11/2026'));
    assert.ok(inTransitText.includes('09:45 09/11/2026'));
    assert.doesNotMatch(inTransitText, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
  });

  if (failures.length > 0) {
    console.error('R1_W6_1B_1_1_UI_D8_V9_FAILED (' + failures.length + ' checks):');
    for (const f of failures) console.error(' - ' + f);
    process.exitCode = 1;
    return;
  }
  console.log('R1_W6_1B_1_1_UI_D8_V9_OK (5/5 checks passed)');
})().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
