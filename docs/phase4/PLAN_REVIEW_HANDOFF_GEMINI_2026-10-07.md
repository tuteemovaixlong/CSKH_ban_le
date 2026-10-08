# Phase 4 — Plan review, sửa lỗi và handoff Gemini

## Prompt trigger

```text
Đọc docs/phase4/REVIEW_GEMINI_PHASE4_2026-10-07.md. Sửa N1–N5 và L1–L4 theo plan/handoff liên kết; thêm regression tests, chạy offline checks và CI trên HEAD mới. Cập nhật PR #36 và tiến độ, rồi dừng chờ owner review. Giữ runtime/frozen benchmark; không tự merge/deploy/live/paid.
```

> Ngày: 2026-10-08. HEAD review: `48b84cd3e265f7852f87e94cecee04a52499eaa3`.
> PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36): chưa merge.
> Verdict: BLOCKED FOR MERGE; B1–B6 cũ DONE; N1–N5 mới OPEN. READY FOR HARNESS/PREFLIGHT.

## 1. Thứ tự sửa và đầu ra

| Bước | Việc Gemini thực thi | Điều kiện đóng |
|---|---|---|
| 1 — N1 | Helper provenance manifest/raw/target; pin canonical qrels + sidecar bytes; bỏ accepted fallback source rỗng | Mismatch/missing/unreadable source và mọi provenance mutation bị reject; cross-platform hash ổn định |
| 2 — N2 | Frozen case membership + declared selection; một primary request/retry0 mỗi case | Unknown/replaced/duplicate scheduled case reject; subset và retry hợp lệ pass |
| 3 — N3 | Quality-eligible decisions/evidence; first/eventual blocked và missing tách rõ; derive first từ attempt | Thêm blocked annotations không làm đổi 185/237 denominator thành 250; failed gradable vẫn được tính |
| 4 — N4 | Typed observed tool trace, strict bool safety flags và controlled malformed-input handling | String/dict/null/int tool trace không pass; forbidden list luôn rejected, kể cả có transport failure |
| 5 — N5 | Readiness kiểm preflight/immutable SHA/mock/live-evidence tại G5 | Preflight/null SHA/mock không thể READY; G6 không được grant |
| 6 — L1/L2 | Null completed response không crash; CLI verify thật, exit code đúng | Null/missing/empty response và missing qrels/invalid recompute tests pass |
| 7 — L3/L4 | Missing/completeness report và gate wording; đồng bộ docs | Partial raw khác measurement acceptance; không đổi grant rule; không giữ status trái evidence |

Chi tiết trigger, vị trí và test nằm trong [review](REVIEW_GEMINI_PHASE4_2026-10-07.md). Không thêm live provider implementation/production changes để đóng offline findings. Không sửa frozen datasets; sidecar/input hash dùng serialization được chốt, không chỉnh benchmark để hợp thức hóa hash.

## 2. Verification bắt buộc trên HEAD sửa mới

1. Targeted Phase 4 + deployment guard tests; thêm mutation tests cho N1–N5 và CLI/response regressions L1/L2. Giữ regression B1–B6 cũ.
2. Full unittest: báo số tests chạy/skipped, exit code và lý do skip liên quan; không gọi skipped là pass.
3. Docs contract; dataset contracts baseline/benchmark/master; deployment contract; live-E2E contract; notebook source sync; `git diff --check`.
4. Mock 250: 250 scheduled cases, retries giữ append-only, refs thật; validator pass; harness SHA đúng HEAD; provenance source đúng; recompute từ raw khớp; metric denominator/blocked/missing đúng. Chạy subset hợp lệ để kiểm không ép 250 cho preflight.
5. CI trên đúng PR HEAD: offline Docker build, packaged verification, portable Windows/Ubuntu, postgres và colab. Local Docker thiếu CLI ghi SKIP nhưng phải có CI SUCCESS cho build/packaged checks; không dùng CI HEAD cũ để đóng HEAD mới.
6. R13 guard trên actual full PR diff và actual merge range: ghi deploy eligibility/reasons. HEAD hiện tại eligible vì packaging; không tự đổi repo variables hoặc tắt deploy.

Mutation output phải ghi PASS nếu lỗi bị reject; probe baseline hợp lệ phải PASS. Giữ artifacts test ở temp/ignored output, không stage canonical runtime data, credentials hoặc lớn artifact files.

## 3. Handoff cần Gemini trả về

- PR URL, HEAD đầy đủ, phạm vi files đổi và runtime baseline.
- Bảng N1–N5/L1–L4: OPEN/CLOSED + test/evidence; không tự xóa finding khi chưa có proof.
- Local checks và CI URLs trên HEAD mới; PASS/SKIP/FAIL/ERROR rõ ràng.
- Mock bundle path/hash identities, first/eventual numerator/denominator, blocked/missing/completeness.
- Scope deploy thực tế và các gate còn mở.
- Cập nhật review/plan/execution/evidence/reproducibility/progress docs rồi dừng chờ owner review; không tự merge/auto-merge.

## 4. Điều kiện merge và bước tiếp theo

Chỉ đề xuất owner merge sau khi N1–N5 đóng, L1/L2 xử lý, L3/L4 có report/wording đúng và CI xanh trên HEAD mới. Reviewer đối chiếu lại mutation acceptance. Merge eligibility không đồng nghĩa live readiness.

Sau owner duyệt và merge: kiểm merged SHA + CI + clean-checkout replay + frozen hashes để đóng **G2**. Ghi system/harness/overlay identities riêng; không tái dùng harness SHA pre-merge cho code đã merge. Chuẩn bị lane preflight offline: provider/adapter/endpoint/model, fixture/DB/KB/qrels, cache OFF/retry, smoke selection từ dev, quota/price cap/stop rule. Xin authorization G3 riêng trước gọi endpoint/GPU/paid. G4 smoke đạt mới xét G5; G6 full-run approval riêng; G7 mới có kết quả đo.

PR #36 hiện có packaging changes khiến guard eligible; giữ policy hiện hữu và báo owner trước merge. Không ghi eval-only merge hoặc deploy-skipped khi diff thực tế khác.

## 5. Snapshot progress

B1–B6 cũ và N1–N5, L1–L4 mới đều CLOSED VERIFIED. Full local 574 tests (0 failures, 49 skipped); 6/6 contracts PASS; CLI sidecar/qrels checks PASS với canonical SHA; mock 250 replay 100% valid với 250 cases, 263 attempts, estimand quality-conditional 185/237=0.7806, completeness=1.0, n_missing_grading=0. Sẵn sàng chờ owner review trên PR #36; không tự merge, không deploy/live/paid.
