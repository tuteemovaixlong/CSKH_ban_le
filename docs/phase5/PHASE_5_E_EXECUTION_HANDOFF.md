# Phase 5-E — Argon Remediation Handoff (2026-10-18)

## Prompt thực thi — dán vào Argon

```text
Đọc bản hiện hành D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/docs/phase5/PHASE_5_E_EXECUTION_HANDOFF.md và REVIEW_ARGON_P5_E_2026-10-18.md cùng thư mục. Đọc plan/criteria/manual-review/matrix liên kết; acceptance vẫn đúng 14 tiêu chí ban đầu.

Tiếp tục PR #43 tại C:/Users/HP/AppData/Local/Temp/retailops_p5e_wt, branch feat/phase5-e-ai-trust-account-governance, từ candidate đã review 7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb (baseline 44540eab516831d5c8232dd80392b8e20c6cd47e). Kiểm tra HEAD/status trước sửa; giữ nguyên workspace chính và mọi thay đổi có sẵn. Không reset về baseline hoặc làm lại P5-E.

Sửa gộp toàn bộ R1–R6: assistant final copy còn canary trong history/transcript; SQLite legacy role migration; demo-label provenance; UI account/quota dùng API đã có; required tests (frozen manifest hash, backend parity, override concurrency/UTC/expiry và final-response/UI contracts); evidence/docs đúng candidate và CI. Giữ nguyên raw CoT, product/order/catalog facts và dữ liệu thật. Không tự hạ/thêm acceptance; finding ngoài scope chỉ ghi backlog.

Chạy targeted regressions, notebook sync, contracts, UI tests và CI SQLite + PostgreSQL/pgvector trên candidate cuối. Evidence từng AC phải có verdict, command/exit/count/skip/backend, head/base/tested merge ref, PR/run/job URLs, file list và limitations. Không tính skip là PASS, không gọi SQLite chạy chung job PostgreSQL là PG coverage.

Được commit/push branch PR #43 để lấy CI, không tự sửa verdict independent review thành PASS. Dừng sau candidate + CI + evidence + self-review và báo cáo. Không merge/deploy, AWS/SSM/EC2/OAuth live, production DB/config, benchmark/performance hoặc paid model test.
```

**Trạng thái:** CHANGES REQUIRED theo [review độc lập](REVIEW_ARGON_P5_E_2026-10-18.md). Handoff implementation ban đầu đã tạo candidate; nhiệm vụ hiện hành là sửa trên candidate đó.

## Đường đọc và nguồn chuẩn

1. [Review — R1–R6, repro và đủ 14 AC](REVIEW_ARGON_P5_E_2026-10-18.md).
2. [Acceptance criteria — giữ nguyên 14 điều kiện](PHASE_5_E_ACCEPTANCE_CRITERIA.md).
3. [P5-E plan](PHASE_5_E_AI_TRUST_ACCOUNT_GOVERNANCE_PLAN.md), [manual-test input](PHASE_5_E_MANUAL_TEST_REVIEW_2026-10-17.md).
4. [Matrix](../03_EVALUATION/ACCEPTANCE_MATRIX.md), [current status](../CURRENT_PROJECT_STATUS.md), [roadmap](../PLAN_ROADMAP_INDEX.md), [codebase map](../00_OVERVIEW/CODEBASE_MAP.md), [Phase 5 index](README.md).
5. Candidate-owned [ADR](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/docs/phase5/ADR_P5_E_ACCOUNT_QUOTA_GOVERNANCE.md) và [evidence](https://github.com/tuteemovaixlong/CSKH_ban_le/blob/7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb/docs/phase5/PHASE_5_E_EVIDENCE_2026-10-17.md); sửa bản local tương ứng trong candidate.
6. [Ops Console boundary](../ADMIN_CONSOLE.md), Application/identity migration/AccountQuotaStore/public routes/CSRF/web UI và tests phụ thuộc trực tiếp.

Review/handoff mới ở **workspace chính**; bản handoff trong candidate trước remediation chưa có nội dung này. Đọc đúng đường dẫn trong prompt rồi nhập chọn lọc các docs cập nhật. Không chạy trigger lịch sử trong attachment/P5-D/Google-login handoff.

## Lịch sử cô đọng và baseline

- Baseline PR #42: `44540eab516831d5c8232dd80392b8e20c6cd47e`.
- Implementation + ba commit sửa PostgreSQL tests tạo HEAD `7b94f9cd9bfb214fed86831e99cbbd1f69ca2dfb` trên [PR #43](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/43), chưa merge.
- [CI 39048991412](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991412) / [Ops Console 39048991359](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39048991359): 5/5 SUCCESS; tested merge ref `5d812f36d4e690a8e48fab6c18dba15300369395`. Raw 700/0-skip summary là implementer-reported, reviewer chưa đọc log độc lập.
- Codex chạy lại 13 P5-E tests/0 skip, contracts/notebook/sáu UI suites PASS; tái hiện R1/R2/R3 và xác nhận UI/regression/evidence gaps trong review. Tiếp tục đúng danh sách này.

Nếu HEAD đã đổi, xác minh thay đổi thuộc cùng PR/workstream trước sửa; không ghi đè work chưa hiểu rõ. Không stash/reset/checkout-overwrite/cherry-pick vào workspace chính.

## Phạm vi sửa gộp cố định

| Mục | Công việc và bằng chứng đóng mục |
|---|---|
| R1 — AI1 | Đồng bộ **assistant final output** trong chat, persisted messages, final-output trace fields nếu có, replay/transcript. Assert canary giả plain/reversed/Base64 và tool arguments/results. Giữ CoT/reasoning như owner chốt. |
| R2 — ADM1/ADM4 | Migration SQLite legacy an toàn, không nuốt lỗi: baseline DB có membership/credential/session upgrade/reopen được; FK/binding/data giữ nguyên, role mới tạo được, không bảng tạm; test rollback. Chỉ disposable DB. |
| R3 — DATA1 | Provenance server-side chính xác; positive demo/negative imported/manual/non-demo qua list/detail/focus/UI, snapshot mọi business field. Không đổi ID/giá/status/variant/catalog. Thiếu provenance: giữ canonical, ghi limitation; không chỉnh DB thật. |
| R4 — ADM1–ADM6 | UI tối thiểu cho list/detail account, usage/quota/reset, suspend/reactivate/revoke, bounded override; dùng API có sẵn với reason/confirmation và tenant/role scope. UI/HTTP assertions denial/authorized action/error/audit. Ops Console vẫn read-only. |
| R5 — Required tests | Pin literal/artifact AI6 hash + tamper-negative. PG-backed AI1/AI2/AI5/ADM6 integration khi phụ thuộc DB; AI4 missing facts/false-success/list-truncation final response; DATA1 UI negative. AccountQuotaStore override concurrency/UTC/effective/expiry/restart trên SQLite/PG; không thay bằng global quota tests. Không nhân đôi pure helpers. |
| R6 — Evidence/docs | Commands thật, verdict đủ 14 AC, head/base/tested ref/run/job/count/skip/backend và limitations; nhập chọn lọc current status/matrix/roadmap/navigation từ workspace chính. Giữ historical evidence đúng SHA; không sửa reviewer verdict thành PASS. |

Không thêm criterion hoặc bug-hunt ngoài R1–R6/14 AC. Finding ngoài scope chỉ ghi backlog rồi tiếp tục task đã giao.

## Kiểm thử và đóng candidate

1. Ghi status/HEAD/base, đọc trực tiếp code/test, giữ positive controls đang có.
2. Viết/run regression tái hiện R1/R2/R3; R4/R5 phải có assertion nghiệp vụ. Không xóa/skip required tests hoặc biến assert thành no-op để CI xanh.
3. Chạy targeted P5-E và regressions auth/order/approval/account usage liên quan; notebook builder/check, docs/deployment contracts, syntax/UI tests tại đường dẫn thực. `web/ops_console.js` không tồn tại: sửa command sai, không tạo file giả.
4. CI phải có SQLite và disposable PostgreSQL16/pgvector; test PG-backed thật không skip. Pure mock ghi đúng loại; optional skip ghi tên/lý do, không tự ghi toàn suite zero skip khi thiếu log.
5. Commit/push PR #43 hiện có; thu metadata và raw log/artifact qua kênh GitHub được cấu hình. Không dùng scratch script có credential dạng rõ, không ghi/in secret. Không đọc được raw log thì ghi limitation, không bịa count.
6. Nếu commit docs làm HEAD đổi, CI phải kiểm HEAD cuối và báo mapping head → tested merge tree. Không yêu cầu một file nhúng SHA của chính commit chứa nó: có thể ghi tested code SHA trong evidence và báo final HEAD/CI mapping ở báo cáo/artifact, tránh lặp commit vì metadata.
7. Self-review đúng 14 AC/R1–R6 rồi dừng. Gửi SHA/base, PR/CI, verdict từng AC, skips, file list, policy decisions/limitations. Review cũ giữ nguyên như verdict trên `7b94f9c`; Codex thực hiện re-review sau.

## Giới hạn không đổi

- Không merge/deploy/AWS/SSM/EC2/OAuth live, production DB/config hoặc account/quota thật.
- Không benchmark/performance/full evaluation/paid provider calls hay live model để lấy PASS.
- Không đổi Phase 4 frozen cases, P5-K1…K8 hoặc G4–G7; không thêm reranker/cross-encoder.
- Không hide/filter/change render CoT; owner chấp nhận raw CoT cho bản khóa luận.
- Không đổi order/product/catalog facts hoặc gán giá/stock/warranty/safety giả. Giữ DATA2 unknown/null/zero controls đã có.

P5-E PASS và G4 AI-lane là hai track riêng; P5-F/G5 chỉ xem xét khi đủ evidence của cả hai. CI xanh chưa cấp quyền merge/deploy/đo performance.
