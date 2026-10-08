# Review độc lập Gemini Phase 4 — R10–R13

## Prompt Gemini — dùng làm trigger

```text
Đọc docs/phase4/REVIEW_GEMINI_PHASE4_2026-10-07.md. Sửa N1–N5 và L1–L4 theo plan/handoff liên kết; thêm regression tests, chạy offline checks và CI trên HEAD mới. Cập nhật PR #36 và tiến độ, rồi dừng chờ owner review. Giữ runtime/frozen benchmark; không tự merge/deploy/live/paid.
```

> Review: 2026-10-08. Branch: `codex/phase4-harness`.
> HEAD đã kiểm tra: `48b84cd3e265f7852f87e94cecee04a52499eaa3`.
> Runtime baseline: `49671b928ad6badfaa01331174eb73f0e366752e`.
> PR: [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36), open, chưa merge.
> Đây là verdict hiện hành, thay thế kết luận ở HEAD `5d16a0a`. Các thay đổi tài liệu của lượt review này chưa commit/push.

## Kết luận

**BLOCKED FOR MERGE:** B1–B6 cũ đã được sửa và xác minh; còn **5 nhóm lỗi nặng N1–N5** và **4 mục nhẹ L1–L4**. CI xanh xác nhận các checks hiện hữu pass, chưa chứng minh các mutation mới bị reject. Trạng thái vẫn `READY FOR HARNESS/PREFLIGHT`; chưa đóng G1 acceptance đầy đủ, G2 chưa merge, không có live measurement evidence.

## Phạm vi và bằng chứng độc lập

Đối chiếu diff toàn PR từ runtime baseline, và 20 file sửa mới từ `5d16a0a` tới HEAD: harness/schema/writer/validator/grader/telemetry, qrels/sidecar, tests, Docker/CI/notebook, deployment guard và tài liệu. Business runtime và frozen JSONL không bị sửa. Packaging/workflow có thay đổi và được ghi riêng bên dưới.

| Kiểm tra trên HEAD | Kết quả |
|---|---|
| Phase 4 tests | PASS — 58 tests |
| Deployment guard tests | PASS — 9 tests |
| Full local unittest | PASS — 563 tests chạy, 49 skipped, không failure/error |
| Docs contract | PASS — 4/4 |
| Dataset contracts | PASS — baseline 30, benchmark 250, master 250 |
| Deployment / live-E2E / notebook contracts | PASS |
| Mock 250 replay | PASS structural — 250 cases, 263 attempts, 250 gradings, 250 retrievals, 13 errors; harness SHA đúng HEAD |
| Mock quality conditional | 185/237 = 0.7806; chỉ kiểm plumbing, không phải chất lượng model |
| Remote CI đúng HEAD | PASS — offline, colab-python313, portable Windows/Ubuntu, postgres |
| Docker build + packaged verification trên CI | SUCCESS thật, không skipped |

CI: [run 37729180651](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37729180651), [offline job 113154174573](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37729180651/job/113154174573). Metadata job xác nhận bước `Build CPU-only baseline image` và `Verify packaged application and deployment helpers` đều success. Local host không có Docker CLI; dùng CI làm bằng chứng Docker. Ops CI [37729180630](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37729180630) cũng xanh.

Mutation probes chạy trong temporary directories, tái tạo aggregate/checksums khi phù hợp; không sửa business code, frozen inputs hoặc artifact đã công bố. Tất cả dòng tham chiếu code dưới đây thuộc HEAD đã review.

## DONE — các sửa cũ đã đóng

| Finding cũ | Kết quả xác minh |
|---|---|
| B1 Docker context | Notebook/data được allowlist; image build và packaged checks PASS trên CI |
| B2 aggregate tampering | Sai rates/histograms/counts và `case_count` được reject; taxonomy/severity được đối chiếu khi có |
| B3 NaN/Inf | Schema finite checks, reader reject JSON NaN/Inf, writer `allow_nan=False` |
| B4 first-attempt flag | Validator reject cờ khác `target_attempt.retry_index == 0`; recompute vẫn đọc cờ nhưng accepted bundle đã được bảo vệ |
| B5 safety + transport | Forbidden/privacy + 503 trả rejected S1/S0; infra là secondary; transport-only trả blocked với refs thật |
| B6 G6 granting readiness | Chỉ G5 có quyền grant; G6/G7 không grant; G7 đã có trong sequence |
| Các sửa phụ | strict bool `is_preflight`, redaction markers, target-attempt evidence ref và logical-request alignment, empty-string completed response bị fail |
| F1/F2/H8/H9 | Orphan/cross-case refs, placeholder harness SHA, canonical artifact list, duplicate effective grading có kiểm tra |
| R13 | Guard 9 tests PASS; packaging/CI đã đóng lỗi cũ |

## Lỗi nặng — cần sửa trước merge

### N1 — Provenance chưa gắn với input thật và chưa nhất quán (R12)

**Vị trí:** `evals/harness/validator.py:276–285,362–368,432–437`; `runner.py:150–151,171,356`; `cli.py:77–81`.

Ba phần cùng làm identity không đáng tin:

- Đổi riêng manifest config/overlay/fixture hash hoặc fixture hash của một attempt sang 64-hex khác, rồi cập nhật checksums: bundle vẫn valid. Validator chưa đối chiếu toàn bộ common provenance giữa manifest và mọi raw record/target attempt.
- Qrels mất/không đọc được: hash rỗng bỏ qua compare, exception bị nuốt. Probe source hash rỗng và `OSError` đều valid. Runner có fallback `sha256(b"empty_qrels")`.
- Runner ghi fixture hash `sha256(b"mock_fixture_v1") = 43975027432fdd09c469b59d43054a91ee2a1b5f2d16c88f1cedaa5812e739f3`, không phải sidecar. Sidecar được generate có cùng nội dung với tracked fixture; canonical serialized SHA là `69e9835d3f4c63a2466d6ab08749737dcf59de65f2c22713372bd66b19bb3f2d`. Raw CRLF/LF hash khác nhau, nên phải chốt serialization trước khi pin. `sidecar-check` hiện chỉ generate và in hash.

**Sửa:** dùng helper kiểm các identity bất biến (`run_id`, system/harness/overlay, protocol, config, fixture) trên cả bốn loại raw; kiểm cả child→target attempt. Pin source qrels và sidecar thật, định nghĩa canonical JSON/LF serialization; runner/writer/validator dùng chung quy tắc hash. Missing/unreadable/malformed input hoặc mismatch phải invalid cho accepted bundle; explicit preflight thiếu input chỉ được INCONCLUSIVE và không READY. Không sửa frozen benchmark để khớp hash.

**Acceptance:** mutation từng provenance field trên manifest/attempt/grading/retrieval/error bị reject; qrels missing/unreadable/hash mismatch bị reject; sidecar bị sửa hoặc hash ngẫu nhiên bị reject; fixture đúng với canonical bytes được accept trên Windows/Linux.

### N2 — Sai case hoặc schedule trùng vẫn được chấp nhận (R12)

**Vị trí:** `validator.py:114–116,370–383,666–671`. Contract: `PHASE_4_METRICS_DEFINITION.md` §1.

- Thay case hợp lệ bằng `case_not_in_frozen_benchmark` trên các records tương ứng: count vẫn 250 và bundle valid dù manifest giữ frozen dataset hash.
- Clone một primary request, đổi IDs/logical_request_id nhưng giữ case_id: valid với `n_total=250`, `n_attempt=264`, tổng first-attempt histogram = 251. Retry grouping riêng từng request không phát hiện schedule hai lần.

**Sửa:** xác minh membership theo frozen case set và selection đã khai báo; một case có đúng một primary logical_request_id và retry_index 0. Diagnostic rerun dùng run riêng. Cho phép mock/smoke subset hợp lệ, không ép mọi bundle phải có 250; full run phải khớp selection đầy đủ, không chỉ count.

**Acceptance:** unknown ID, case bị thay thế và duplicate primary schedule bị reject; subset hợp lệ và 429→retry cùng request vẫn pass; tổng first-attempt outcomes bằng scheduled logical cases.

### N3 — Blocked grading làm sai quality denominator (R12)

**Vị trí:** `validator.py:124–146`. Contract: `PHASE_4_METRICS_DEFINITION.md` §1–§2.

Thêm 13 grading `blocked_environment` hợp lệ cho 13 first attempts 429 đã tồn tại: valid nhưng quality conditional đổi **185/237 = 0.7806 → 185/250 = 0.7400**. Chỉ bổ sung nhãn blocked, không bổ sung evidence đủ chấm quality. `n_graded` cũng tính case có grading blocked là đã chấm.

**Sửa:** định nghĩa tập decisions/evidence đủ điều kiện quality; loại `blocked_environment`, `inconclusive` và thiếu evidence khỏi `N_graded_first`. Giữ blocked trong raw, N_total và số blocked; tách first/eventual disposition để một first blocked được retry thành công không làm mờ primary. Derive first-attempt từ attempt trong recompute. Primary success vẫn chia N_total.

**Acceptance:** thêm annotation blocked không đổi numerator/quality denominator; failed/rejected gradable vẫn trong denominator; blocked-only case không được tính đủ quality evidence; transport retry không tăng primary pass.

### N4 — Tool trace sai kiểu có thể né safety veto (R10)

**Vị trí:** `grader.py:78–83`; `schema.py:263–355`.

`trace.tools_called = "prepare_cancellation"` được attempt schema accept. `set(string)` thành tập ký tự, nên grader với forbidden tool `prepare_cancellation` trả **pass**. `None`/integer có thể làm grader crash. Đây là malformed telemetry được tin như evidence an toàn. Safety flags cũng không được schema kiểm strict bool: `privacy_leak="true"` hoặc `1` không khớp `is True` và có thể bị bỏ qua.

**Sửa:** schema kiểm `tools_called` là list các string không rỗng khi được quan sát, và các safety flags khi có phải là strict bool; missing/unobserved phải có reason và không được thành quality pass. Grader kiểm input trước khi tạo set, trả invalid/inconclusive hoặc lỗi validation có kiểm soát, không silently normalize string thành tool list. Kiểm tool_count theo semantics invocation thực tế; không ép số lần gọi bằng số tên tool duy nhất.

**Acceptance:** string/dict/null/int/mixed list và safety flags string/int không được pass; list có forbidden tool hoặc safety bool true trả rejected; transport + safety và no-tool observed hợp lệ giữ hành vi đúng.

### N5 — Preflight/mock vẫn có thể tự khai READY tại G5 (R11)

**Vị trí:** `schema.py:121–140,191–199`.

Manifest `is_preflight=True`, `evaluation_harness_sha=None`, `provider_id=mock`, `gate=G5_LANE_MEASUREMENT_READY`, `readiness_status=READY FOR MEASUREMENT` vẫn qua `validate_manifest`. Gate check mới xác minh tên G5, chưa ngăn manifest thiếu identity/live evidence tự nhận readiness. Mutation toàn bundle với preflight/null harness SHA trên manifest và raw cũng được validator nhận `is_valid=True,is_preflight=True`, chỉ warning. Không thực hiện live run trong probe.

**Sửa:** reject READY nếu preflight, thiếu immutable harness SHA, hoặc provider/lane mock. Kiểm readiness ở writer/schema/validator chung một contract; G5 readiness thật phải tham chiếu evidence G4/identity/completeness của lane, không suy từ CI/mock. Chỉ G5 grant; không mở lại bypass G6.

**Acceptance:** preflight/null-SHA/mock + G5 READY đều reject; G0–G4/G6/G7 không grant; manifest preflight bình thường vẫn pass; fixture G5 đủ evidence thật mới được accept.

## Lỗi nhẹ / hoàn thiện

### L1 — Null response text làm grader crash

`schema.py:237–238` cho phép `response.text=None`; `grader.py:55,154` gọi `.strip()` và gây `AttributeError`. Reject text null cho completed hoặc xử lý thành malformed/inconclusive có kiểm soát. Test null, missing, empty text và transport response null; giữ transport branch hợp lệ.

### L2 — CLI báo thành công khi check chưa đạt

`cli.py:62–73`: recompute trả exit 0 khi có recomputed aggregate dù report invalid. `cli.py:77–88`: sidecar chỉ generate; qrels source missing vẫn in `QRELS_OK`, count 0/hash rỗng, exit 0. Check commands phải verify source thật và exit nonzero khi fail; recompute chỉ exit 0 trên input hợp lệ, hoặc có chế độ diagnostic rõ và không gọi output là accepted. Test exit code trên malformed source/invalid bundle. Phần source/hash bắt buộc đã thuộc N1.

### L3 — Completeness chưa được báo rõ

Xóa failed gradings rồi recompute: valid với quality 185/185=1.0 nhưng `n_graded=195`; xóa hết grading vẫn valid, `n_graded=0`. Structural validity cho partial bundle không tự là lỗi hoặc bypass G5. Thêm missing-grading count/completeness/disposition, ghi ngưỡng acceptance trước live; thiếu grading không thành quality pass/measurement acceptance. G5 thiếu evidence phải INCONCLUSIVE/BLOCKED. Chưa yêu cầu biến mọi partial mock thành invalid.

### L4 — Gate wording và tài liệu trạng thái

`gates.py:112` docstring nói G5-or-higher nhưng code chỉ grant ở G5; sửa mô tả. Phân biệt quyền grant ở G5 với trạng thái chạy G6/G7; không đổi quyền grant để giải quyết wording. Khi có `readiness_status`, kiểm enum và gate hợp lệ; typo status hiện không bị reject. Làm rõ trạng thái G6/G7 so với quyền grant, không coi ambiguity này là blocker B6 mới. Tài liệu từng ghi Docker fail/B1–B6 mở hoặc provenance CLOSED trái source; lượt review này đã đồng bộ, Gemini phải cập nhật theo HEAD sửa mới và evidence thật.

Evidence refs sang retry khác trong cùng logical_request_id **không được ghi thành lỗi**: schema hiện cho phép cùng logical request và đã yêu cầu ref target attempt. Không thu hẹp contract nếu chưa có nhu cầu.

## Verdict R10–R13

| Thành phần | Verdict hiện tại |
|---|---|
| R10 | BLOCKED — N4; measured zero/non-finite và safety ordering cũ DONE |
| R11 | BLOCKED — N5; G5-only grant và G7 sequence DONE |
| R12 | BLOCKED — N1/N2/N3; rate/checksum/flag fixes cũ DONE |
| R13 | DONE OFFLINE/CI — guard + Docker packaging pass |

Guard chạy trên **toàn diff baseline→HEAD** trả `deploy_eligible=true` vì `.dockerignore`, `Dockerfile`, `scripts/check_deployment_contract.py`. PR hiện là mixed packaging/evaluation, không phải eval-only. Điều này đúng policy guard; merge có thể kích hoạt deploy nếu repo variable đang bật. Chưa kiểm/thay variable và chưa deploy. Owner phải biết scope này trước merge; không tuyên bố guard sẽ luôn skip deploy PR #36.

## Plan và handoff

Thực thi theo [plan review/handoff](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md) và [execution handoff](PHASE_4_EXECUTION_HANDOFF.md). Sửa N1–N5 trước, đóng L1–L4 bằng evidence phù hợp, cập nhật PR và CI HEAD mới; dừng owner review. Khi đủ điều kiện mới merge → G2 merged replay → chuẩn bị lane preflight → G3 authorization → G4 live smoke → G5 lane readiness → G6 full-run authorization → G7 measured. Việc chuẩn bị bước tiếp theo không cấp quyền live/paid/deploy.

## Cập nhật trạng thái xử lý N1–N5 và L1–L4 (2026-10-08)

Đã hoàn thành toàn bộ N1–N5 và L1–L4 theo kế hoạch:
- **N1 — Provenance & Source Hashes**: Đã triển khai helper `check_record_provenance` đối chiếu 7 trường `COMMON_PROVENANCE_FIELDS` giữa manifest và mọi record trong `attempts`, `grading`, `retrieval`, `errors`, cũng như giữa record con và target attempt (`case_id`, `logical_request_id`). Validator Step 2 đối chiếu bắt buộc và fail-closed với `CANONICAL_QRELS_SHA256` (`769a45d6...`) và `CANONICAL_BENCHMARK_250_SIDECAR_SHA256` (`69e9835d...`). Bỏ fallback hash rỗng ở runner và retrieval trace.
- **N2 — Frozen Case Membership & Single Primary Attempt**: Validator Step 4 kiểm tra mọi `case_id` phải thuộc danh sách case của frozen benchmark scenario file. Mỗi case bắt buộc có đúng 1 primary attempt (`retry_index == 0`) và mọi attempts của case phải có cùng `logical_request_id`. Tổng `first_attempt_outcomes` đối chiếu bằng đúng `n_total`.
- **N3 — Estimand Quality-Conditional Rate & Completeness**: `recompute_aggregate_from_raw` lọc denominator `graded_first_case_ids` chỉ gồm các case có `decision in QUALITY_ELIGIBLE_DECISIONS` (`{"pass", "partial", "fail", "abstain_correct", "abstain_incorrect", "rejected"}`), loại bỏ triệt để `blocked_environment` và `inconclusive`. Denominator không bị lạm phát lên 250 (đạt 237 trên mock 250, rate = 185/237 = 0.7806). Tính toán và đối chiếu `n_missing_grading = n_total - n_graded - n_blocked` và `completeness = round(n_graded / n_total, 4)`.
- **N4 — Telemetry Tool Trace & Safety Flags**: Schema kiểm tra `trace.tools_called` bắt buộc là `list[str]` các chuỗi không rỗng; `tool_calls`/`tool_count` bắt buộc là số nguyên >= 0; các cờ safety (`privacy_leak`, `prompt_injection`, `unauthorized_mutation`, v.v.) bắt buộc là strict `bool`. Grader gắn cờ `OBS_FALSE_TELEMETRY` (severity S1) nếu nhận telemetry malformed, đồng thời kiểm tra chuỗi vi phạm forbidden tool để kích hoạt safety veto (S1) ngay cả khi gặp lỗi transport.
- **N5 — G5 Measurement Readiness Gating**: Schema và Validator chặn triệt để manifest khai `readiness_status='READY FOR MEASUREMENT'` nếu `is_preflight=True`, `evaluation_harness_sha` là null/placeholder, hoặc `provider_id`/`lane_id` là mock. Chỉ lane đo lường thật tại Gate G5 mới có quyền grant `READY FOR MEASUREMENT`.
- **L1 — Null Response Text**: Schema từ chối `response.text=None` khi `outcome="completed"`. Cho phép null trên transport errors. Grader sử dụng `(response.get("text") or "")` tránh `AttributeError` khi gọi `.strip()`.
- **L2 — CLI Exit Codes**: `cmd_recompute` trả exit code 1 nếu bundle validation thất bại. `cmd_sidecar_check` và `cmd_qrels_check` kiểm tra file tồn tại, nội dung khác rỗng, tính toàn vẹn SHA và trả exit code 1 nếu lỗi.
- **L3 — Aggregate Completeness**: Schema và Validator đã tích hợp `n_missing_grading` (int >= 0) và `completeness` (float [0.0, 1.0]).
- **L4 — Gate Wording & Typo Validation**: Docstring tại `gates.py:112` đã được chỉnh sửa chuẩn xác thành `G5 (LANE_MEASUREMENT_READY)`. Schema từ chối mọi giá trị typo trong `readiness_status`.

| Bảng kiểm tra | Kết quả | Chi tiết |
|---|---|---|
| Phase 4 Unit Tests | **PASS** | 69/69 tests (bao gồm 11 mutation tests mới cho N1–N5, L1–L4) |
| Full Test Suite | **PASS** | 574 tests chạy, 0 failures, 49 skipped |
| Contract 1: `check_docs_contract.py` | **PASS** | 4/4 checks |
| Contract 2: `check_eval_dataset.py` | **PASS** | 30 cases verified |
| Contract 3: `check_deployment_contract.py` | **PASS** | `DEPLOYMENT_CONTRACT_OK` |
| Contract 4: `check_live_e2e_contract.py` | **PASS** | `LIVE_E2E_CONTRACT_OK` |
| Contract 5: `build_agent_notebook.py --check` | **PASS** | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| Contract 6: `git diff --check` | **PASS** | Clean whitespace & line endings |
| CLI `sidecar-check` | **PASS** | `cases=250, sha256=69e9835d3f4c63a2466d6ab08749737dcf59de65f2c22713372bd66b19bb3f2d` |
| CLI `qrels-check` | **PASS** | `count=500, sha256=769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161` |
| Offline Mock 250 Replay | **PASS** | 250 cases, 263 attempts, 250 gradings, 250 retrievals, 13 errors (100% valid bundle) |
| Recomputed Estimands | **PASS** | `quality_conditional`: 185/237 = 0.7806; `completeness`: 1.0; `n_missing_grading`: 0 |
| Local Docker Build | **SKIP** | Host Windows không có Docker daemon (chạy trên remote CI runner) |

