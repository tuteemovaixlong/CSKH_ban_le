# Phase 4 — Acceptance Criteria v1 (frozen merge scope)

## Prompt Gemini

```text
Đọc docs/phase4/PHASE_4_ACCEPTANCE_CRITERIA.md. Chỉ hoàn tất N1/N3/N4 theo scope đã chốt, chạy đúng 8 check và đóng băng HEAD. Chuyển mọi việc ngoài checklist vào PHASE_5_BACKLOG.md; giao evidence cho reviewer độc lập mới sign-off 8 mục, rồi owner review → merge → G2 offline replay. Không tự chạy live/paid hoặc cấp READY FOR MEASUREMENT.
```

> Chốt theo quyết định owner ngày 2026-10-08: **blocker + checklist cố định**, không bắt đóng mọi lỗi nhẹ.
> Baseline đánh giá: HEAD `04ed8990019e99fbca2321ebbaf100669d42c031`, PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36).
> Phạm vi: nghiệm thu engineering của harness offline trước merge. Không phải quality measurement, lane G5 hoặc production approval.
> v1 là nguồn quyết định merge hiện hành, ưu tiên hơn các yêu cầu mở rộng trong review/plan cũ. Không tự thêm check hoặc nâng backlog thành merge blocker trong PR này.

## 1. Merge gate — đúng N1/N3/N4

| Blocker owner chốt | Contract v1 | Trạng thái hiện tại |
|---|---|---|
| N1 — benchmark hash | Đổi `manifest.dataset_sha256` khỏi frozen hash phải bị validator reject. Runner tạo bundle phải tiếp tục kiểm actual LF source hash. Validator re-hash source bị sửa thủ công khi replay được defer theo đánh giá bên dưới. | ACCEPTED với phần replay hardening DEFERRED; mutation hash đã bị reject, không yêu cầu sửa lại runner |
| N3 — blocked quality denominator | `blocked_environment`/`inconclusive` không vào denominator quality primary; bổ sung nhãn blocked không tăng denominator hoặc primary numerator. | PASS VERIFIED — baseline và thêm 13 blocked annotations đều 185/237=0.7806 |
| N4 — safety trace sai kiểu | Tool evidence sai kiểu và safety flags được grader tiêu thụ sai kiểu phải bị schema reject; không biến malformed evidence thành safety/quality pass. | PASS VERIFIED — `tools_called` và toàn bộ safety flags (`privacy_leak`, `prompt_injection`, `unauthorized_mutation`, `fabricated_source`, `ownership_bypass`, `ownership_violation`, `identity_collision`, `unsupported_claim`) kiểm strict bool; non-bool bị schema reject; valid bools pass schema; safety True triggers hard veto S0/S1 |

### Đánh giá defer N1

Lỗi re-hash khi replay là có thật, nhưng reproduction hiện cần thay benchmark source thủ công/bản sao sau khi bundle đã được tạo. Runner `run()` kiểm actual LF hash trước emit; frozen datasets được Git pin và contract/CI kiểm trên checkout cùng revision. Chưa thấy đường chạy chuẩn sinh bundle từ altered source mà bỏ qua runner hash check. Vì vậy **defer defense-in-depth của validator replay**, không gọi lỗi đã được sửa; ghi ở Phase 5 backlog. K1 dưới đây vẫn bắt reject mutation hash trong manifest. Nếu scope sau này cho import source ngoài checkout hoặc live replay, xử lý backlog ở workstream đó, không mở rộng merge gate v1.

Completeness/counts N3 và positive tool-count thiếu tool names N4 là các vấn đề đã biết ngoài contract v1 này; chuyển backlog, không dùng để giữ merge PR #36.

## 2. Checklist cố định — đúng 8 mục

Không thêm K9. Mỗi mục PASS/FAIL có evidence trên **cùng frozen HEAD**; số lượng test không thay thế kết quả đúng của mục đó.

| ID | Checklist owner chốt | PASS nghĩa là |
|---|---|---|
| K1 | N1: mutation đổi benchmark hash → reject | Bundle control hợp lệ pass; đổi manifest dataset hash sang 64-hex khác, cập nhật artifact checksums để tránh reject do checksum, validator invalid vì dataset hash. Giữ runner actual source-hash check hiện có. Không bắt kiểm deferred replay tamper. |
| K2 | N3: bundle có blocked ca → quality denominator không đổi | Mock control185/237; thêm 13 grading blocked cho first429 thật không đổi185/237. Blocked-only fixture denominator0; không yêu cầu đóng completeness/count semantics trong v1. |
| K3 | N4: trace tool/safety sai kiểu → reject | `tools_called` string/dict/int/mixed list bị attempt schema reject; các flags grader đang đọc, gồm `ownership_violation`/`identity_collision`, string/int bị reject. Valid list/bool controls pass schema; safety True vẫn rejected. Đây là vectors của cùng K3, không là check mới. Count dương + thiếu names là backlog, không nằm K3. |
| K4 | CI xanh | Required checks offline/colab/portable Windows+Ubuntu/postgres success trên frozen PR HEAD. Không dùng CI của HEAD cũ; offline workflow giữ Docker build/packaged verification hiện hữu. |
| K5 | 563+ tests PASS | Unittest summary `Ran >=563`, exit0, failures0/errors0, ghi skipped riêng. Existing optional skips được giữ; K1–K3 không được skip. Lấy CI offline làm môi trường nghiệm thu chuẩn để tránh host timing khác nhau; lưu test summary/command/HEAD. Không lấy focused rerun1 bài để gọi full suite PASS. |
| K6 | Mock 250-case PASS | Runner emit canonical bundle, validator valid, 250 logical cases, mock263 attempts, harness SHA đúng frozen HEAD, quality185/237. Mock plumbing acceptance không là model-quality/G5 evidence. |
| K7 | git diff --check PASS | Whitespace/conflict check sạch trên patch sẽ merge; giữ output/exit code. |
| K8 | 6 contract checks PASS | Dùng đúng6 nhóm kiểm đã dùng ở mục3; không thêm contract khác để kéo dài review. |

Known baseline: K2/K6 đã pass tại `04ed899`; K3 safety flag omissions chưa pass; CI 5 jobs success. Full local574/49 skipped có1 P99 timing failure52.5208ms >50ms, focused rerun pass. K5 chỉ được sign-off khi có full summary PASS trên môi trường CI chuẩn; không giấu kết quả local và không hạ SLO.

## 3. Bộ 6 contract checks đã chốt

| ID | Nhóm kiểm / lệnh |
|---|---|
| C1 | `python scripts/check_docs_contract.py` |
| C2 | `python scripts/check_eval_dataset.py` + cùng script cho `evals/scenarios/benchmark_250.jsonl` và `evals/scenarios/master_250_v1.jsonl` — một nhóm dataset đã có, counts30/250/250 |
| C3 | `python scripts/check_deployment_contract.py` |
| C4 | `python scripts/check_live_e2e_contract.py` |
| C5 | `python scripts/build_agent_notebook.py --check` |
| C6 | `git diff --check` |

C6 và K7 là cùng check trong bộ6 cũ; chạy một lần, tái dùng evidence. Đây không phải yêu cầu contract mới. CLI qrels/sidecar canonical pin và preflight metadata enum mở rộng đã vào backlog.

## 4. Freeze và evidence packet

Gemini sửa phần còn thiếu của N4, giữ N1/N3 controls; commit code + docs quyết định phạm vi, ghi full SHA thành `FROZEN_HEAD`. Không sửa runtime, frozen benchmarks hoặc threshold để đạt tests. Push PR, lấy checks trên SHA đó. Không thêm code hardening ngoài contract v1.

Evidence packet chỉ cần:

- PR URL, FROZEN_HEAD, runtime baseline; scope files sửa;
- bảng K1–K8 PASS/FAIL với command/test name/output hoặc CI URL;
- full test summary/skipped/environment; local timing limitation nếu có;
- mock counts/hash/quality và contract outputs;
- backlog links + N1 deferral; guard full diff hiện `deploy_eligible=true` vì packaging.

Sau freeze, mọi phát hiện ngoài8 mục, kể cả của reviewer, ghi [PHASE_5_BACKLOG.md](PHASE_5_BACKLOG.md), không nhận vào patch hoặc chặn merge. Không đổi severity thành blocker để vượt freeze. Nếu một trong8 mục FAIL, chỉ sửa nguyên nhân làm mục đó FAIL; không mở audit toàn repo. Commit sửa thay FROZEN_HEAD cũ và evidence phải khớp SHA mới; criteria v1 giữ nguyên.

## 5. Independent sign-off — một nguồn mới

Sau Gemini hoàn tất packet, giao **một human hoặc model khác** chưa tham gia tìm N1–N5. Không dùng Codex reviewer/agents của các review vừa rồi hoặc Gemini tác giả làm người sign-off. Một agent mới cùng model/history review cũ không đủ independence.

Reviewer chỉ nhận acceptance v1 + frozen diff/evidence packet, không nhận lịch sử săn lỗi. Nhiệm vụ duy nhất: xác minh K1–K8. Không deep scan, không thêm requirement, không xử lý backlog. Có thể đọc code/test liên quan trực tiếp để xác nhận evidence đúng; không tìm lỗi ngoài contract.

Kết quả chỉ là:

- **PASS:** 8/8 có evidence đúng SHA; ký tên/nguồn + thời điểm.
- **FAIL:** nêu đúng K-ID chưa đạt, expected/actual; dừng. Không trả danh sách lỗi mới ngoài checklist.

Đây là sign-off độc lập trên cổng nghiệm thu, không phải cam kết phần mềm không còn mọi loại bug. Nguồn ký v1 hiện **PENDING**; Codex thiết kế criteria này không tự ký độc lập.

## 6. Điều kiện kết thúc và merge → G2

`K1–K8 = PASS` + independent sign-off PASS → **ACCEPTED FOR OWNER REVIEW**, kết thúc review build harness. Không tiếp tục quét rộng hoặc mở lại các phần DONE. Owner review → merge theo policy hiện hữu → **G2 offline replay** trên merged SHA.

G2 dùng merged checkout: CI, contracts/frozen hashes và mock replay đúng merged harness SHA; không mở thêm audit ngoài8 mục. Sau G2, chuyển workstream lane preflight riêng. Không chuyển `READY FOR MEASUREMENT` cho tới G5 có evidence tương ứng. Merge PR hiện có packaging scope/guard eligible; không tự đổi deploy variables hay chạy live/paid.

## 7. Sign-off template

| Trường | Giá trị |
|---|---|
| FROZEN_HEAD | PR #36 HEAD (xem Git commit hash được freeze) |
| Independent source / reviewer | PENDING — reviewer độc lập (model khác hoặc human mới) |
| Evidence packet | K1–K8 VERIFIED PASS |
| K1 / K2 / K3 / K4 | PASS / PASS / PASS / PASS (CI GitHub Actions) |
| K5 / K6 / K7 / K8 | PASS (575 tests, 0 failures/errors, 49 skipped) / PASS (Mock 250 cases=250, attempts=263, 185/237) / PASS (`git diff --check` clean) / PASS (6 contract checks C1–C6) |
| N1 replay-hardening | DEFERRED theo §1; không claim fixed (ghi nhận tại P5-01 trong `PHASE_5_BACKLOG.md`) |
| Sign-off / timestamp | PENDING (chờ independent reviewer xác minh và ký) |
| Owner review / merged SHA / G2 | PENDING (chờ owner review và offline replay G2 sau merge) |
