# PHASE_4_RESULTS_SCHEMA — Raw JSONL và reproducibility contract

> **Trạng thái (2026-10-08):** `READY FOR HARNESS/PREFLIGHT`. HEAD `48b84cd` có implementation/offline/CI evidence; B1–B6 cũ DONE. N1–N5 source/coherence/case/metric/safety/readiness còn mở theo [review](REVIEW_GEMINI_PHASE4_2026-10-07.md). Schema/mock validity không tự cấp measurement acceptance.

## 1. Quy tắc bất biến

Raw artifacts là append-only. Mỗi logical request giữ lại attempt đầu tiên và mọi retry; aggregate chỉ là view dẫn xuất. Không ghi secret, cookie, access token hoặc PII thô. Mọi record đều có `run_id`; record theo case còn có `case_id` và `logical_request_id`.

`system_commit_sha` là revision của runtime được đo. `evaluation_harness_sha` là revision của runner/writer/grader/validator. `evaluation_overlay_sha256` định danh can thiệp chỉ dành cho evaluation (ví dụ cache controller hoặc telemetry hook); dùng giá trị `none` khi không có overlay. Ba identity này không được gộp vào một trường `commit_sha` mơ hồ.

## 2. Canonical bundle

```text
artifacts/phase4/<run_id>/
  manifest.json
  attempts.jsonl
  grading.jsonl
  retrieval.jsonl
  errors.jsonl
  aggregate.json
  checksums.sha256
```

Tên cũ `raw_results.jsonl`, `retrieval_traces.jsonl` và `derived_metrics.json` chỉ là alias lịch sử; writer mới không được phát hành chúng như tên canonical.

## 3. Join keys và nullability

| Record | Khóa bắt buộc | Quy tắc duy nhất | Trường nullable |
|---|---|---|---|
| `manifest.json` | `run_id` | một manifest cho một run | provider revision/tokenizer/seed nếu adapter không expose, kèm `unavailable_reason` |
| `attempts.jsonl` | `run_id,case_id,logical_request_id,attempt_id,retry_index` | `attempt_id` duy nhất; retry tăng dần trong một logical request | response/latency/telemetry khi transport chết; không dùng `0` thay cho chưa đo |
| `grading.jsonl` | common envelope + `case_id,logical_request_id,graded_attempt_id,grading_id` | một grading version cho một attempt; adjudication tạo `grading_id` mới | claim labels/evidence refs khi case không áp dụng, dùng `null` + reason |
| `retrieval.jsonl` | common envelope + `case_id,logical_request_id,attempt_id,retrieval_event_id` | một ID cho mỗi retrieval event | qrels/served evidence khi query không áp dụng hoặc provider không trả trace |
| `errors.jsonl` | common envelope + `case_id,logical_request_id,attempt_id,error_id` | một ID cho mỗi lỗi quan sát được | provider code/message redacted nếu unavailable |
| `aggregate.json` | `run_id` | chỉ một aggregate dẫn xuất sau khi validator pass | CI/effect size nếu chưa đủ denominator/power |

`case_id` có thể xuất hiện nhiều lần trong raw vì retry; do đó validator **không** được áp dụng quy tắc “không duplicate case ID” cho `attempts.jsonl`. Logical case join key là (`run_id, case_id`); retry-group join key là (`run_id, case_id, logical_request_id`); attempt join key là (`run_id, attempt_id`). `grading.jsonl`, `retrieval.jsonl` và `errors.jsonl` chỉ được tham chiếu một `attempt_id` hợp lệ trong cùng `run_id`; mọi record có `logical_request_id` khớp attempt được tham chiếu.

Measured zero có nghĩa khác missing. `model_calls=0` và `provider_inference_ms=0.0` hợp lệ khi observer/trace chứng minh attempt không có model invocation, gồm rule-only refusal, direct response, human handoff, replay hoặc cache hit. Record phải có `trace.model_invocation_observed=true` và `trace.zero_reason` thuộc `refusal`, `direct_response`, `human_handoff`, `replay` hoặc `cache_hit`. `cache_hit=false` hoặc `cache_hit=null` tự nó không chứng minh có hay không có invocation. Nếu invocation chưa được quan sát, ghi `null` cùng `unavailable_reason`; không dùng default `0` để thay missing. `provider_inference_ms` là tổng provider time của attempt; chỉ ghi `0.0` khi đã quan sát xác nhận không invocation.
### 3.1 Common envelope cho mọi dòng JSONL

Mọi dòng trong attempts.jsonl, grading.jsonl, retrieval.jsonl và errors.jsonl bắt buộc lặp lại common envelope: `schema_version`, `record_id`, `run_id`, `case_id`, `logical_request_id`, `system_commit_sha`, `evaluation_harness_sha`, `evaluation_overlay_sha256`, `protocol_version`, `config_sha256`, `fixture_manifest_sha256`, `created_at_utc`. Record-specific IDs (`attempt_id`, `grading_id`, `retrieval_event_id`, `error_id`) bắt buộc ở loại tương ứng. Vì vậy một dòng raw vẫn có thể audit khi bị tách khỏi manifest. `evaluation_harness_sha` chỉ null ở preflight; bundle accepted phải có SHA. `record_id` duy nhất trong file và được dùng làm evidence ref.
## 4. Schema từng record (normative)

### 4.1 `manifest.json`

Required: `schema_version`, `run_id`, timestamps, dataset paths/hashes/counts, `system_commit_sha`, `evaluation_harness_sha`, `evaluation_overlay_sha256`, `config_sha256`, `lane_id`, `provider_id`, `cache_mode`, `retry_policy_id`, `load_profile_id`, fixture/KB hashes, `artifact_files`.

`evaluation_harness_sha` là `null` chỉ ở pre-build dry-run; mọi bundle được gọi accepted phải có SHA immutable. `model_revision`, `tokenizer_revision`, `seed` có thể `null` nếu adapter không expose nhưng phải có `*_unavailable_reason`. Mismatch endpoint/provider/model là lỗi block; unavailable proprietary revision là limitation được ghi nhận.

### 4.2 `attempts.jsonl`

Required fields: `run_id`, `case_id`, `logical_request_id`, `attempt_id`, `retry_index`, `attempt_class` (`first`/`transport_retry`/`diagnostic_rerun`), `started_at_utc`, `finished_at_utc`, `http_status`, `outcome`, `response`, `trace`.

`response.text`, `latency_ms`, `ttfb_ms`, `queue_wait_ms`, `provider_inference_ms`, `model_calls`, `tool_count` là nullable khi request chưa nhận được response hoặc telemetry không quan sát được. `trace.model_invocation_observed` là boolean bắt buộc khi telemetry model được dùng để kết luận zero; `trace.zero_reason` chỉ có khi `model_calls=0`. `error_ref` trỏ sang `errors.jsonl` khi có lỗi.

### 4.3 `grading.jsonl`

Required fields: `run_id`, `case_id`, `graded_attempt_id`, `grading_id`, `grader_version`, `rubric_version`, `decision`, `first_attempt`, `claim_judgments`, `evidence_refs`, `adjudicated`.

`first_attempt` là boolean để giữ primary estimand độc lập với eventual retry. `decision` dùng `pass`, `partial`, `fail`, `abstain_correct`, `abstain_incorrect`, `blocked_environment`, `inconclusive`, `rejected`. `severity` phải là một trong `S0`, `S1`, `S2`, `S3` theo `PHASE_4_FAILURE_TAXONOMY.md`; safety hard veto và severity phải được ghi riêng, không ẩn trong điểm trung bình. `answerability_status` tách `labeled-unanswerable`, `annotation-missing` và `not-applicable`.

### 4.4 `retrieval.jsonl`

Required fields: `run_id`, `case_id`, `attempt_id`, `retrieval_event_id`, `query_id`, `stage`, `candidate_chunks`, `served_chunks`, `qrels_version`.

`candidate_chunks` và `served_chunks` phải giữ `chunk_id`, `rank`, `score`, `source_id`; query no-evidence có `no_evidence: true`, `answerability_status` và metric riêng. `qrels_version`, `qrels_source` và `qrels_sha256` vẫn phải giữ khi metric là N/A; `unavailable_reason` giải thích thiếu annotation/không áp dụng. Không biến no-evidence thành Recall@k bằng 0 một cách mơ hồ.

### 4.5 `errors.jsonl`

Required fields: `run_id`, `case_id`, `attempt_id`, `error_id`, `stage`, `taxonomy_code`, `retryable`, `http_status`, `message_redacted`. `retryable` không được suy ra chỉ từ status; phải khớp retry policy đã pin.

### 4.6 `aggregate.json`

Required fields: `run_id`, `logical_cases`, `n_total`, `n_attempt`, `n_graded`, `n_blocked`, `first_attempt_outcomes`, `eventual_outcomes`, `quality_conditional`, `e2e_success`, `artifact_checksums`, `derived_from`.

`aggregate.json` phải tái tính được từ raw records; không được nhập một score không có numerator/denominator và source record.

## 5. Examples thực tế

HTTP 200 first attempt:

```json
{"schema_version":"phase4-attempt-v1","record_id":"rec-001","run_id":"r-demo","case_id":"ro_s1_001","logical_request_id":"lr-001","attempt_id":"a-001","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:00:00Z","retry_index":0,"attempt_class":"first","started_at_utc":"2026-10-06T00:00:00Z","finished_at_utc":"2026-10-06T00:00:01Z","http_status":200,"outcome":"completed","response":{"text":"Đơn đang giao.","sources":["order:1001"]},"trace":{"actual_mode":"retail","model_calls":1,"tool_count":1,"cache_hit":false,"provider_inference_ms":412.5},"error_ref":null}
```

Retry 429 → 200 (hai dòng, không ghi đè dòng đầu):

```json
{"schema_version":"phase4-attempt-v1","record_id":"rec-002","run_id":"r-demo","case_id":"ro_s1_002","logical_request_id":"lr-002","attempt_id":"a-002-0","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:01:00Z","retry_index":0,"attempt_class":"first","started_at_utc":"2026-10-06T00:01:00Z","finished_at_utc":null,"http_status":429,"outcome":"transport_error","response":null,"trace":{"actual_mode":null,"model_calls":null,"tool_count":null,"cache_hit":null,"provider_inference_ms":null},"error_ref":"e-002-0"}
{"schema_version":"phase4-attempt-v1","record_id":"rec-003","run_id":"r-demo","case_id":"ro_s1_002","logical_request_id":"lr-002","attempt_id":"a-002-1","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:01:05Z","retry_index":1,"attempt_class":"transport_retry","started_at_utc":"2026-10-06T00:01:05Z","finished_at_utc":"2026-10-06T00:01:06Z","http_status":200,"outcome":"completed","response":{"text":"Đơn đang giao.","sources":["order:1002"]},"trace":{"actual_mode":"retail","model_calls":1,"tool_count":1,"cache_hit":false,"provider_inference_ms":398.0},"error_ref":null}
```

Invalid record phải bị từ chối (thiếu common envelope, retry không có `logical_request_id`, record tham chiếu `attempt_id` khác run, hoặc ghi `model_calls: 0`/`provider_inference_ms: 0.0` mà không có `trace.model_invocation_observed=true` và `zero_reason`).

Các ví dụ trên và dưới đây là **illustrative/mock** để minh họa khóa và nullability; JSON parse thành công không đồng nghĩa machine-readable schema, writer, validator hoặc full-bundle tests đã triển khai.

### 5.1 Ví dụ bảy artifact canonical
### 5.1a Measured-zero examples

```json
{"schema_version":"phase4-attempt-v1","record_id":"rec-zero-valid","run_id":"r-demo","case_id":"ro_s6_021","logical_request_id":"lr-zero","attempt_id":"a-zero","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:02:00Z","retry_index":0,"attempt_class":"first","started_at_utc":"2026-10-06T00:02:00Z","finished_at_utc":"2026-10-06T00:02:00Z","http_status":200,"outcome":"handoff","response":{"text":"Tôi sẽ chuyển bạn tới nhân viên hỗ trợ."},"trace":{"actual_mode":"retail","model_calls":0,"tool_count":1,"cache_hit":null,"provider_inference_ms":0.0,"model_invocation_observed":true,"zero_reason":"human_handoff"},"error_ref":null}
```

```json
{"schema_version":"phase4-attempt-v1","record_id":"rec-zero-invalid","run_id":"r-demo","case_id":"ro_s6_022","logical_request_id":"lr-zero-invalid","attempt_id":"a-zero-invalid","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:03:00Z","retry_index":0,"attempt_class":"first","started_at_utc":"2026-10-06T00:03:00Z","finished_at_utc":"2026-10-06T00:03:00Z","http_status":200,"outcome":"completed","response":{"text":"ok"},"trace":{"actual_mode":"retail","model_calls":0,"tool_count":0,"cache_hit":null,"provider_inference_ms":0.0,"model_invocation_observed":false},"error_ref":null}
```


```json
{"schema_version":"phase4-manifest-v1","run_id":"r-demo","lane_id":"mock-a0","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","dataset_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","qrels_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","model_revision":null,"model_revision_unavailable_reason":"mock_provider","artifact_files":["attempts.jsonl","grading.jsonl","retrieval.jsonl","errors.jsonl","aggregate.json","checksums.sha256"]}
```

```json
{"schema_version":"phase4-grading-v1","record_id":"g-001","run_id":"r-demo","case_id":"ro_s1_001","logical_request_id":"lr-001","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:00:00Z","graded_attempt_id":"a-001","grading_id":"gr-001","grader_version":"g-v1","rubric_version":"rubric-v1","decision":"pass","first_attempt":true,"claim_judgments":[],"evidence_refs":["rec-001"],"adjudicated":false,"answerability_status":"answerable","severity":null}
{"schema_version":"phase4-retrieval-v1","record_id":"rt-001","run_id":"r-demo","case_id":"ro_s1_001","logical_request_id":"lr-001","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:00:00Z","attempt_id":"a-001","retrieval_event_id":"rev-001","query_id":"q-001","stage":"served","candidate_chunks":[],"served_chunks":[],"qrels_version":"q-v1","qrels_source":"mock","qrels_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","no_evidence":true,"answerability_status":"labeled-unanswerable","unavailable_reason":"no_relevant_chunk"}
{"schema_version":"phase4-error-v1","record_id":"e-001","run_id":"r-demo","case_id":"ro_s1_001","logical_request_id":"lr-001","system_commit_sha":"49671b928ad6badfaa01331174eb73f0e366752e","evaluation_harness_sha":"1111111111111111111111111111111111111111","evaluation_overlay_sha256":"none","protocol_version":"p4-v1","config_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","fixture_manifest_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at_utc":"2026-10-06T00:00:00Z","attempt_id":"a-001","error_id":"err-001","stage":"grading","taxonomy_code":"UNOBSERVED_TRACE","severity":"S3","retryable":false,"http_status":200,"message_redacted":"trace incomplete"}
```

```json
{"schema_version":"phase4-aggregate-v1","run_id":"r-demo","logical_cases":1,"n_total":1,"n_attempt":1,"n_graded":1,"n_blocked":0,"first_attempt_outcomes":{"pass":1},"eventual_outcomes":{"pass":1},"quality_conditional":{"numerator":1,"denominator":1},"e2e_success":{"numerator":1,"denominator":1},"derived_from":["attempts.jsonl","grading.jsonl","retrieval.jsonl","errors.jsonl"],"artifact_checksums":"checksums.sha256"}
```

```text
<sha256>  manifest.json
<sha256>  attempts.jsonl
<sha256>  grading.jsonl
<sha256>  retrieval.jsonl
<sha256>  errors.jsonl
<sha256>  aggregate.json
```

## 6. Validator và implementation backlog

Validator phải kiểm: JSON parse/schema, join-key tồn tại, retry sequence, split/category counts, frozen hashes, completeness, checksums, aggregate recomputation và nullability rule. Adversarial fixtures phải bao phủ malformed 200, 429/timeout, duplicate attempt ID, wrong owner, forbidden tool, missing evidence và corrupted artifact.

| ID | Acceptance check | Dependencies | Trạng thái |
|---|---|---|---|
| S01 | Writer phát một dòng cho mọi attempt và giữ retry fail | runner, schema | `BACKLOG` |
| S02 | Validator reject missing/duplicate keys, checksum/aggregate mismatch và fabricated zero | S01, taxonomy | `BACKLOG` |
| S03 | Grading/retrieval/error records join được bằng khóa canonical | fixtures, qrels | `BACKLOG` |
| S04 | Telemetry ghi measured hoặc `null` với reason | harness/instrumentation | `BACKLOG` |

Cho tới khi S01–S04 có evidence, trạng thái canonical vẫn là `READY FOR HARNESS/PREFLIGHT`.

Liên kết: [PHASE_4_METRICS_DEFINITION.md](PHASE_4_METRICS_DEFINITION.md), [PHASE_4_EVIDENCE_CHECKLIST.md](PHASE_4_EVIDENCE_CHECKLIST.md), [PHASE_4_REPRODUCIBILITY.md](PHASE_4_REPRODUCIBILITY.md).
