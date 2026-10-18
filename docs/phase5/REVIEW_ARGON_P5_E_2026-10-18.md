# Independent Review — Argon P5-E candidate `baa70b1` (2026-10-18)

**Verdict: CHANGES REQUIRED — chưa merge, deploy hoặc chuyển sang performance.**

Review này đánh giá candidate cuối của Argon sau gói remediation R1–R6. Acceptance vẫn đúng **14 tiêu chí P5-E**; không thêm gate mới và không mở lại P5-D/K3/K7. Review cũ của candidate `7b94f9c` được giữ làm lịch sử.

## Candidate và bằng chứng

- Baseline PR #42: `44540eab516831d5c8232dd80392b8e20c6cd47e`.
- Candidate: `baa70b15731fd82b909c36e0b89cb7d9b41ca342`, branch `feat/phase5-e-ai-trust-account-governance`, worktree `C:/Users/HP/AppData/Local/Temp/retailops_p5e_wt` (sạch).
- Candidate trước remediation: `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb`.
- [PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43) vẫn OPEN.
- Tested merge ref: `d3655b89e165ba09db53ac7ad13e9b4a787cb3fe`.
- [CI run 39099835679](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39099835679) và [Ops Console run 39099835635](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39099835635): metadata xác nhận 5/5 job SUCCESS trên đúng head `baa70b1`.
- Đã chạy lại: 14 test P5-E/0 skip, UI session mặc định và persistent, notebook sync, deployment contract, docs contract và `git diff --check` — PASS.
- Số `701/0 skip` trong offline job là evidence do Argon báo; không dùng số này thay cho re-review source-level.

## Những phần Argon đã sửa tốt

1. **R2/ADM1–ADM4:** migration SQLite legacy dùng connection riêng, tắt FK trước transaction, kiểm tra FK, rollback và reopen. Disposable baseline có membership/credential/session được nâng cấp, tạo `platform_admin` được và không còn bảng tạm. R2 đủ cơ sở đóng trong review này.
2. **R3/DATA1:** nhãn `Bộ xếp hình gỗ cho bé` được phát ra theo provenance server-side; order thủ công/import/non-demo không bị relabel.
3. **R4/ADM:** UI account/quota đã tồn tại và gọi control plane `/api/admin/accounts*`, audit, suspend/reactivate/revoke; manager bị giới hạn tenant, `platform_admin` có tenant selector; Ops Console vẫn read-only.
4. **AI6/ADM5/ADM6:** manifest hash được pin, audit transaction/CSRF/control-plane boundary có code và regression tương ứng.

## Findings còn mở trong scope 14 tiêu chí

### R1 — AI1: structured tool data vẫn có thể rò canary (P1)

Application chỉ làm sạch final text. Assistant message có `tool_calls`, tool arguments/results, trace step summaries, `human_support` và các bản ghi feedback vẫn có thể giữ canary. Repro offline với mock model cho thấy canary xuất hiện trong persisted `agent_turns.messages`, transcript/trace và `conversation_feedback.comment`. Replay các turn cũ cũng trả `result` nguyên trạng trước khi có sanitizer.

**Đóng:** làm sạch/redact các kênh structured trước response và trước persist; xử lý replay/transcript của row cũ theo policy an toàn; test single-agent và multi-agent cho chat response, tool args/results, trace, persisted messages, result, replay và feedback. Giữ raw `trace.reasoning`/CoT theo quyết định owner.

### R2 — ADM1/ADM4: đã đủ bằng chứng đóng

Không mở thêm bug hunt cho migration. Chỉ bổ sung assertion nếu cần chứng minh rollback sau bước destructive; không migrate DB thật.

### R3 — DATA1: provenance đúng, còn giới hạn fixture cần ghi rõ (P2)

`seed_demo_sample_orders()` trả sớm nếu customer đã có order, nên order demo cũ không được thêm provenance và giữ tên cũ. Seed ID cũng có thể rơi vào `O-900000`/ `O-900001`, trong khi helper/formatter chỉ nhận `O-[78]xxxxx`. Sửa bounded fixture contract hoặc ghi limitation có test; không backfill EC2/production.

### R4 — ADM2–ADM4: UI/API integration gaps (P2)

- Đổi tenant selector có thể giữ selected membership và confirmation cũ; thao tác tiếp theo có thể nhắm account của tenant trước.
- API trả `quota.next_reset_utc` nhưng UI không render thời điểm reset.
- UI ghi “để trống = xóa override”, nhưng gửi `daily_limit: null` và backend trả `400 invalid_quota_limit`; giá trị `0` cũng lệch contract.
- Account search áp `LIMIT 50` trước khi lọc `q`, nên account sau trang đầu có thể bị báo không tìm thấy.

**Đóng:** reset selection/confirmation khi đổi scope, kiểm tra selected account thuộc scope hiện tại trước mọi write; hiển thị reset UTC; thống nhất semantics clear override giữa UI/API/schema/audit; lọc/search đúng trước pagination hoặc thêm pagination; test qua HTTP/UI thật, không chỉ mock Node.

### R5 — AI2/AI4/AI5 và backend parity: regression còn thiếu (P1/P2)

- Read-only guard hiện khóa cancellation nhưng hostile model vẫn gọi `request_human_support`, tạo `human_handoff` dù người dùng chỉ yêu cầu tra cứu.
- Không có final-answer grounding guard: tool trả `P-604` với price/stock/warranty `null`, model vẫn có thể trả dữ kiện bịa.
- PG test chưa chứng minh đầy đủ final-response AI4 và upstream provider `429`; provider-style timeout path cũng cần assertion mapping đúng contract.

**Đóng:** allowlist side-effect tools trong read-only mode; thêm hostile mock final-answer tests cho unknown facts/false success/list truncation; bổ sung PG-backed assertions cho các path phụ thuộc DB; không gọi live model/paid provider.

### R6 — evidence và docs phải khớp candidate cuối

Docs điều hướng phải trỏ `baa70b1`, tested merge ref `d3655b89`, CI `39099835679`, Ops `39099835635`, 14 test/0 skip local và verdict **CHANGES REQUIRED**. Review lịch sử không được tự sửa thành PASS. Evidence phải phân biệt implementer self-report với Codex verification và ghi rõ limitations ở R1/R3/R4/R5.

## Bảng verdict 14 tiêu chí

| Tiêu chí | Verdict hiện tại | Ghi chú |
|---|---|---|
| AI1 | **FAIL / CHANGES REQUIRED** | Tool args/results, feedback và replay còn kênh leak |
| AI2 | **FAIL / CHANGES REQUIRED** | `request_human_support` vẫn có side effect trong read-only |
| AI3 | **SUPPORTED** | Owner/tenant/ID boundary có regression SQLite/PG |
| AI4 | **FAIL / CHANGES REQUIRED** | Chưa chặn final answer bịa unknown facts |
| AI5 | **PARTIAL** | Có timeout/429/503 tests nhưng thiếu provider-path parity |
| AI6 | **PASS (bounded offline)** | Literal hash + tamper-negative; không paid call |
| ADM1 | **PARTIAL** | R2 tốt; UI/scope integration còn gap |
| ADM2 | **PARTIAL** | API scope có; search/UI contract còn gap |
| ADM3 | **PARTIAL** | Lifecycle có; stale selection/scope guard cần test/fix |
| ADM4 | **PARTIAL** | Backend quota tốt; reset/clear/concurrency UI contract còn gap |
| ADM5 | **SUPPORTED** | Append-only audit và rollback có evidence |
| ADM6 | **SUPPORTED / RE-VERIFY** | CSRF/control-plane/Ops read-only có evidence |
| DATA1 | **PARTIAL** | Provenance fix đúng; legacy/ID-range limitation cần đóng hoặc ghi contract |
| DATA2 | **SUPPORTED** | Unknown/null/zero inventory controls giữ nguyên |

## Quyết định

P5-E hiện **READY FOR A BOUNDED REMEDIATION PASS, không READY FOR MERGE**. Chỉ sửa R1, R3, R4, R5 và R6; R2 không mở rộng. Sau candidate mới + CI + evidence + self-review, Codex sẽ re-review độc lập. Không merge/deploy/AWS/SSM/EC2/OAuth live/production DB/config/performance/paid tests. G4 AI-lane vẫn là track riêng; P5-F/G5–G7 vẫn HOLD.

Đọc cùng: [criteria](PHASE_5_E_ACCEPTANCE_CRITERIA.md), [plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [manual input](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md), [acceptance matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md), [current status](../CURRENT_PROJECT_STATUS.md), [roadmap](../PLAN_ROADMAP_INDEX.md), [codebase map](../00_OVERVIEW/CODEBASE_MAP.md), [handoff](PHASE_5_E_EXECUTION_HANDOFF.md).
