'use strict';
const byId = id => document.getElementById(id);
const node = (tag, text, className) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; };
const known = value => typeof value === 'number' && Number.isFinite(value);
const fmt = value => known(value) ? new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 2}).format(value) : 'Chưa đo';
const pct = value => known(value) ? (value * 100).toFixed(1) + '%' : 'Chưa đo';
let runs = [], usage = null, activeRun = null;
async function api(path) { const response = await fetch(path, {credentials: 'same-origin', cache: 'no-store'}); if (!response.ok) throw new Error('Không đọc được dữ liệu (' + response.status + ').'); return response.json(); }
function cards(id, entries) { const area = byId(id); area.replaceChildren(); for (const [label, value, detail] of entries) { const card = node('div', undefined, 'card'); card.append(node('span', label), node('strong', value), node('small', detail || '')); area.append(card); } }
function bars(id, entries, percentage = false) {
  const area = byId(id); area.replaceChildren(); entries = entries.filter(([,v]) => known(v));
  if (!entries.length) { area.append(node('p', 'Chưa có quan sát để vẽ biểu đồ.', 'empty')); return; }
  const max = percentage ? 1 : Math.max(1, ...entries.map(([,v]) => v));
  for (const [label, value] of entries) { const row = node('div', undefined, 'bar-row'); const track = node('div', undefined, 'bar-track'), fill = node('div', undefined, 'bar-fill'); fill.style.width = Math.max(0, Math.min(100, value / max * 100)) + '%'; track.append(fill); row.append(node('span', label), track, node('span', percentage ? pct(value) : fmt(value), 'bar-value')); area.append(row); }
}
function emptyMetric(id, text) { const area = byId(id); area.replaceChildren(node('p', text, 'empty')); }
function table(id, headers, rows) { const area = byId(id); area.replaceChildren(); if (!rows.length) { area.append(node('p', 'Không có bản ghi.', 'empty')); return; } const t = node('table'); const head = node('tr'); for (const h of headers) head.append(node('th', h)); t.append(head); for (const row of rows) { const tr = node('tr'); for (const value of row) tr.append(node('td', String(value))); t.append(tr); } area.append(t); }
function confusion(m) { const area = byId('confusion'); area.replaceChildren(); if (!m || !m.n) { area.append(node('p', 'Run này không đo routing.', 'empty')); return; } const t = node('table', undefined, 'matrix'); const h = node('tr'); ['', ...m.predicted_labels].forEach(x => h.append(node('th', x))); t.append(h); m.confusion_matrix.forEach((values, i) => { const row = node('tr'); row.append(node('th', m.actual_labels[i])); values.forEach((value, j) => row.append(node('td', String(value), i === j ? 'hit' : value ? 'miss' : ''))); t.append(row); }); area.append(t); }
async function showRun() {
  if (!byId('run').value) { byId('eval-note').textContent = 'Chưa có evaluation run. Runner chạy qua CLI/CI, không tự chạy khi mở trang.'; return; }
  activeRun = await api('/api/runs/' + encodeURIComponent(byId('run').value)); const m = activeRun.metrics;
  const routerOnly = activeRun.kind === 'router';
  byId('eval-note').textContent = routerOnly ? 'ROUTER ONLY: không gọi LLM, vì vậy latency/token/cost của model là N/A chứ không phải instrumentation bị lỗi. Dev và held-out được lưu riêng trong artifact.' : 'LIVE REPORT IMPORT: dữ liệu từ bài HTTP E2E đã chạy; không phải benchmark toàn bộ dataset hay browser automation.';
  cards('eval-cards', [['Cases / contract', fmt(m.cases), 'Không đồng nhất với số người dùng'], ['Routing accuracy', pct(m.routing.accuracy), 'n = ' + m.routing.n], ['Router macro-F1', pct(m.routing.macro_f1), 'Unknown predictions tính là sai'], ['Inference calls', fmt(activeRun.manifest?.inference_calls), routerOnly ? 'Router-only run' : 'Theo manifest'], ['Critical checks', m.critical_checks.status, 'Đã đo: ' + m.critical_checks.evaluated]]);
  bars('category-chart', Object.entries(m.by_category).map(([k,v]) => [k,v.pass_rate]), true);
  confusion(m.routing);
  if (routerOnly) {
    emptyMetric('latency-chart', 'N/A — run router không gọi LLM. Chọn một LIVE FULL run để xem latency đã ghi nhận.');
    emptyMetric('token-chart', 'N/A — run router có inference_calls = 0 nên không phát sinh token model.');
  } else {
    bars('latency-chart', activeRun.cases.filter(c => c.trace).map(c => [c.category, c.trace.latency_ms]));
    bars('token-chart', [['Prompt', m.usage.prompt_tokens.known_sum], ['Generated', m.usage.generated_tokens.known_sum]]);
  }
  table('failures', ['Case', 'Nhóm', 'Expected', 'Actual', 'Check fail / chưa đo'], activeRun.cases.filter(c => c.status !== 'pass').map(c => [c.id,c.category,c.expected_mode || '-',c.actual_mode || '-',Object.entries(c.checks).filter(([,v]) => v !== true).map(([k]) => k).join(', ')]));
  byId('manifest').textContent = JSON.stringify({run_id: activeRun.run_id, kind: activeRun.kind, created_at: activeRun.created_at, ...activeRun.manifest, latency: m.usage.latency_ms, cost: m.usage.reported_cost_usd}, null, 2);
  byId('limits').textContent = m.limits.join(' ');
}
function showUsage() {
  if (!usage?.windows) { byId('usage-note').textContent = 'Chưa có usage snapshot. Không thay dữ liệu thiếu bằng 0.'; return; }
  const selected = usage.windows[byId('traffic').value][byId('window').value], age = Math.max(0, Date.now()/1000 - usage.generated_at);
  byId('usage-note').textContent = 'Snapshot: ' + new Date(usage.generated_at * 1000).toLocaleString('vi-VN') + ' | ' + (age > 600 ? 'STALE: ' : '') + Math.round(age/60) + ' phút trước. ' + (usage.source_partial ? 'CẢNH BÁO: giới hạn quét, kết quả chưa đầy đủ. ' : '') + 'Login users không phải DAU; event count không phải message count.';
  const cost = selected.usage.reported_cost_usd, latency = selected.usage.latency_ms;
  cards('usage-cards', [['Login principals', fmt(selected.unique_login_principals), 'Tài khoản có login thành công'], ['Chat outcomes ghi nhận', fmt(selected.recorded_chat_outcomes), 'Không bao gồm mọi HTTP retry'], ['Latency p50', known(latency.p50) ? (latency.p50/1000).toFixed(2) + 's' : 'Chưa đo', 'p95: ' + (known(latency.p95) ? (latency.p95/1000).toFixed(2) + 's' : 'chưa đủ mẫu')], ['Prompt tokens', fmt(selected.usage.prompt_tokens.known_sum), 'Coverage: ' + pct(selected.usage.prompt_tokens.coverage)], ['Output tokens', fmt(selected.usage.generated_tokens.known_sum), 'Coverage: ' + pct(selected.usage.generated_tokens.coverage)], ['Chi phí API đã biết', known(cost.known_sum) ? '$' + cost.known_sum.toFixed(6) : 'Unknown', 'Coverage: ' + pct(cost.coverage)]]);
  bars('event-chart', Object.entries(selected.event_counts)); bars('daily-chart', Object.entries(selected.daily_events_utc));
  table('models', ['Provider / model','Traces','Model calls','Prompt tokens','Output tokens','p50 ms','p95 ms'], Object.entries(selected.by_model).map(([k,v]) => [k,v.n,fmt(v.model_calls.known_sum),fmt(v.prompt_tokens.known_sum),fmt(v.generated_tokens.known_sum),fmt(v.latency_ms.p50),fmt(v.latency_ms.p95)]));
  table('tenants', ['Tenant (pseudonym)','Events','Login principals','Customer bindings'], (usage.tenants || []).map(t => [t.tenant,t.last_30_days.events,t.last_30_days.unique_login_principals,t.last_30_days.active_customer_bindings]));
  byId('usage-limits').replaceChildren(...usage.limitations.map(text => node('p', text, 'muted')));
}
async function refresh() { try { const data = await api('/api/runs'); runs = data.runs; const prior = byId('run').value; byId('run').replaceChildren(); for (const run of runs) { const option = node('option', run.kind + ' | ' + run.created_at + ' | ' + run.run_id); option.value = run.run_id; byId('run').append(option); } if (runs.some(r => r.run_id === prior)) byId('run').value = prior; usage = await api('/api/usage'); await showRun(); showUsage(); const dep = await api('/api/deployment'); byId('deployment').textContent = JSON.stringify(dep, null, 2); byId('status').textContent = 'Đã tải ' + runs.length + ' runs | Read only | Invalid artifacts: ' + data.invalid_reports; } catch (error) { byId('status').textContent = error.message; } }
if (typeof document !== 'undefined') {
  byId('refresh').onclick = refresh; byId('run').onchange = () => showRun().catch(e => {byId('status').textContent = e.message;}); byId('window').onchange = showUsage; byId('traffic').onchange = showUsage;
  document.querySelectorAll('[data-tab]').forEach(button => { button.onclick = () => { document.querySelectorAll('.view').forEach(section => { section.hidden = section.id !== button.dataset.tab; }); document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('active', b === button)); }; });
  refresh();
}
if (typeof module !== 'undefined') module.exports = {known, fmt, pct};
