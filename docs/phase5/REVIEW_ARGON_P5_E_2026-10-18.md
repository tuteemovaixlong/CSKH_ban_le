# Independent Review — Argon P5-E (2026-10-18)

**Verdict: CHANGES REQUIRED — tiếp tục P5-E trên PR #43; chưa merge/deploy hoặc chuyển sang performance.**

**Phạm vi:** đúng 14 tiêu chí đã chốt; không audit toàn repo hoặc mở lại P5-D/K3/K7. Nguồn chuẩn: [criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md), [plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [manual-test input](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md). Prompt sửa gộp nằm trong [handoff hiện hành](PHASE_5_E_EXECUTION_HANDOFF.md).

## Candidate và kết quả thuận lợi

- Baseline: `44540eab516831d5c8232dd80392b8e20c6cd47e`; candidate: `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb`.
- Branch `feat/phase5-e-ai-trust-account-governance`, worktree `C:/Users/HP/AppData/Local/Temp/retailops_p5e_wt` sạch; diff baseline → candidate: 28 file, 2771 dòng thêm / 44 dòng xóa, whitespace PASS. Workspace chính đang bẩn được giữ nguyên.
- [PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43) OPEN, chưa merge. [CI 39048991412](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991412) và [Ops Console 39048991359](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991359) SUCCESS; metadata xác nhận 5 checks offline, Colab Python313, portable Ubuntu/Windows và postgres SUCCESS trên head candidate. PR merge ref qua metadata: `5d812f36d4e690a8e48fab6c18dba15300369395`, không phải commit đã merge vào main.
- Argon giữ nguyên ngữ nghĩa 14 criteria và handoff/manual review; không thấy tự hạ acceptance. Có code thật cho session/tenant authorization, quota override, revoke, audit transaction, read-only intent và unknown stock. Ops Console v1 vẫn read-only.
- CI xanh chưa chứng minh đủ acceptance: review xác nhận ba lỗi runtime, một phần UI chưa làm và các khoảng trống test/evidence dưới đây. Tất cả thuộc scope ban đầu.

## R1 — Final answer bị lộ lại qua transcript/history (P1; AI1)

[application.py:357](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/retailops/business/application.py#L357) chỉ lọc `answer['message']`; dòng 409 vẫn truyền `answer['messages']` gốc vào `finish_turn`. `agent_turns.messages` giữ assistant final content chưa lọc; transcript API trả bản sao này cho khách đã đăng nhập.

Repro offline với mock model trả canary giả (không secret thật): `model_calls=1`, `chat_message_leaks=false`, `trace_leaks=false`, nhưng `persisted_assistant_final_leaks=true`; GET transcript trả 200 và final copy vẫn có canary. Cả root reviewer và subagent tái hiện được.

**Đóng R1:** đồng bộ các bản sao assistant final output trước persist/replay/transcript; kiểm final-output fields trong trace nếu có. Regression phải kiểm chat, stored assistant messages, transcript, replay và tool arguments/results theo AI1. Không suy ra đã lộ secret production. **Không yêu cầu ẩn/lọc `trace.reasoning` hay CoT**; quyết định owner giữ nguyên.

## R2 — SQLite legacy role migration không nâng cấp được DB có dữ liệu (P1; ADM1/ADM4)

[identity/store.py:188](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/retailops/identity/store.py#L188) chạy `PRAGMA foreign_keys=OFF` trong transaction `BEGIN IMMEDIATE` nên không đổi chế độ FK. Khi membership có credential/session tham chiếu, `DROP TABLE memberships` thất bại; `except Exception: pass` nuốt lỗi, giữ CHECK role cũ và bảng tạm dở dang.

Repro bằng source IdentityStore **đúng baseline `44540ea`** → tạo manager/credential giả → mở DB bằng candidate: `role_upgraded=false`, `partial_table_remaining=true`, tạo platform_admin bị `IntegrityError`. Root và subagent cùng tái hiện.

**Đóng R2:** migration có version/transaction và rollback an toàn, không nuốt lỗi. Test baseline DB có membership/credential/session → upgrade → reopen/idempotency; assert FK integrity, binding/data preservation, role mới tạo được và không bảng tạm sót. Chỉ dùng disposable DB, không migrate EC2/production.

## R3 — Display label chưa giới hạn đúng fixture demo (P2; DATA1)

[routes.py:24](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/retailops/http/routes.py#L24) chỉ kiểm data mode, P-602, tên cũ và ID sáu chữ số; không kiểm nguồn seed của tenant/customer/order. Order giả `O-123456`, customer `non_demo_customer`, không xuất phát từ demo seed, vẫn nhận nhãn đồ chơi trong persistent-demo. Root và subagent cùng tái hiện.

**Đóng R3:** dùng provenance fixture phía server, không dựa vào hình dạng ID. Positive demo và negative imported/manual/non-demo; test API list/detail/focus, UI và snapshot mọi business field. Tool/catalog giữ canonical facts; không chuyển P-602 thành P-604 hoặc đổi giá/status/variant. Record không chứng minh được nguồn fixture phải giữ canonical name và ghi limitation; không backfill/chỉnh DB thật.

## R4 — Thiếu UI quản trị account/quota (scope incomplete; ADM1–ADM6)

Candidate có HTTP API nhưng `web/` không gọi `/api/admin/accounts*` hay `/api/admin/audit-log`. `web/index.html:242` chỉ có KPI/products/SOPs/orders/audit; diff app.js chỉ dùng `display_name`. Criteria ADM1 đã ghi **“API và UI đều enforce”**; ADR chỉ mô tả API, không có owner decision hoãn UI.

**Đóng R4:** UI gọn dùng API đã có: account list/detail, usage/limit/reset, suspend/reactivate/revoke và quota override với reason/confirmation. Manager giới hạn tenant, platform_admin chọn scope rõ; customer/viewer/staff bị từ chối. Test role denial, authorized actions, error states và action→audit. Backend vẫn quyết định quyền. Giữ Ops Console v1 read-only, không mở rộng role policy hoặc xây dashboard ngoài yêu cầu.

## R5 — Required tests/evidence chưa đủ (các AC hiện có)

1. **AI6:** [test file:87](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/tests/test_phase5_e_ai_trust_and_governance.py#L87) tính EXPECTED_MANIFEST_SHA256 từ manifest lúc import rồi test tính lại cùng biểu thức; sửa prompt vẫn PASS. Pin hash literal/artifact độc lập và tamper-negative.
2. **Backend parity:** class P5-E mới luôn dựng SQLite BusinessStore. Có DSN trong job không làm nó thành PG-backed. PG mega-test có AI3/governance/DATA/quota429; chưa chạy hostile read-only AI2, final-output AI1, timeout/provider429/503 AI5 hoặc CSRF ADM6 trên PG-backed path. Bổ sung integration cần thiết; helper thuần như hash không cần nhân đôi theo DB.
3. **ADM4:** test đúng AccountQuotaStore per-membership override với concurrent reservations, UTC-day boundary, effective/expiry và reopen trên SQLite/PG. Existing test quota global `control.reserve_api_attempt` không thay được đường override mới; các test mới hiện tuần tự.
4. **AI4/DATA1:** bổ sung end-to-end final response cho missing facts/false-success/list truncation, UI display label và non-demo negative. Payload tool hoặc static source assertion đơn lẻ chưa chứng minh output/UI contract. R1 phải có assertions cả output/tool surfaces trong criteria.

Đây là danh sách hữu hạn từ criteria; không yêu cầu live model, bộ fuzz/benchmark mới hoặc nhân đôi mọi pure-unit test.

## R6 — Evidence và docs cần ghi đúng candidate (reporting)

[Evidence Argon tại candidate](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/docs/phase5/PHASE_5_E_EVIDENCE_2026-10-17.md) thiếu candidate SHA/PR/run/job URL và head→tested-ref mapping; số 700/0 skip chỉ nằm attachment. Các cột PG “covered in offline job” mô tả quá rộng. Candidate status/roadmap còn snapshot P5-D cũ vì clean baseline chưa có docs sync ở workspace chính.

**Đóng R6:** evidence theo từng AC có command/exit/count/skip/backend, head/base/tested ref và CI links. Nhập chọn lọc current-status/navigation từ workspace chính, không reset/copy đè toàn repo hoặc lấy code bẩn vào PR. Giữ nguyên review này như verdict trên `7b94f9c`; implementer cập nhật self-evidence, không tự sửa verdict reviewer thành PASS.

## Bảng đủ 14 AC tại candidate được review

`SUPPORTED` là source/test có evidence thuận lợi, chưa phải ký toàn P5-E hoặc xác minh mọi raw CI count.

| AC | Kết luận | Còn lại |
|---|---|---|
| AI1 | FAIL — final-copy leak | R1/R5 |
| AI2 | PARTIAL — SQLite controls PASS | PG read-only/confirmation R5 |
| AI3 | SUPPORTED — owner/invalid-ID SQLite + PG source | Exact execution evidence R6 |
| AI4 | PARTIAL — tool facts/truncation có | Final-response contract R5 |
| AI5 | PARTIAL — SQLite faults, PG quota429 có | PG timeout/provider429/503 R5 |
| AI6 | FAIL — hash tự tính | Pin + tamper-negative R5 |
| ADM1 | FAIL / INCOMPLETE | Migration R2 và UI R4 |
| ADM2 | SUPPORTED API / UI NOT IMPLEMENTED | UI scope/secret-denial R4 |
| ADM3 | SUPPORTED API / UI NOT IMPLEMENTED | UI lifecycle/confirmation R4 |
| ADM4 | PARTIAL | R2/R4; override concurrency/UTC/PG expiry R5 |
| ADM5 | SUPPORTED API — audit/denial/rollback | UI action→audit R4/R6 |
| ADM6 | PARTIAL — SQLite CSRF/Ops read-only | UI R4, PG-backed CSRF R5 |
| DATA1 | FAIL — non-fixture relabel | R3/R5 |
| DATA2 | SUPPORTED — unknown/null/zero + controls SQLite/PG | Preserve regression, record evidence R6 |

## Kiểm chứng và giới hạn

- Local `python -m unittest tests.test_phase5_e_ai_trust_and_governance -v`: **13/13 PASS, 0 skip**, 6.186s, exit 0.
- Notebook sync, docs contract **4/4**, deployment contract, `node --check web/app.js`, sáu Node suites chat_focus/model_status/knowledge_sources/shipment_ui/provider_selector/public_session và candidate-range whitespace: **PASS**.
- R1/R2/R3: tái hiện bằng disposable data/mock model, không network hay secret thật. AI6 hash gap được xác nhận từ source và negative conceptual mutation.
- GitHub metadata: **5/5 SUCCESS**, PostgreSQL16/pgvector service/prepare/test steps SUCCESS. Argon báo host/container mỗi lượt 700 PASS/0 skip; reviewer chưa đọc độc lập raw logs vì public log API trả 403. Không gọi thiếu raw count là CI failure.
- `node --check web/ops_console.js` trong evidence Argon không hợp lệ: file không tồn tại; chạy lại trả MODULE_NOT_FOUND. Sửa danh sách command theo đường dẫn thật, không tạo file giả.
- Không chạy lại full suite hoặc PG local khi không có disposable DSN; CI đã xanh. Không dùng thiếu DSN làm lỗi code. Không kiểm tra EC2/live model trong lượt này.

## Quyết định và điểm dừng

Review/handoff và các docs điều hướng/trạng thái liên quan đã được đồng bộ trong **workspace chính**, tổng cộng 18 tài liệu. Docs contract 4/4, related local links, inventory 181 file / 136 Markdown / 45 khác và `git diff --check -- docs` PASS; 14 dòng định nghĩa AC vẫn khớp candidate. Candidate worktree giữ sạch tại `7b94f9c`; các docs reviewer cập nhật chưa được đưa vào PR #43. Argon cần đọc handoff ở đúng workspace chính rồi nhập chọn lọc, như chỉ dẫn R6.

Argon tạo được implementation lớn và giữ workspace/criteria đúng. Cần đóng **R1–R6 trong một lượt sửa trên PR #43 hiện có**, không làm lại P5-E hoặc thêm gate. Candidate mới + CI + evidence + self-review rồi dừng cho re-review đúng danh sách này; finding ngoài scope chỉ ghi backlog.

P5-E chưa nghiệm thu. G4 AI-lane vẫn riêng; không có quyền merge/deploy/AWS/EC2/OAuth live/production DB/performance/paid tests từ review này.
