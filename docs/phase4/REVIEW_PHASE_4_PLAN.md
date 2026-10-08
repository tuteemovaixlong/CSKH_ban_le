# Phase 4 — Review bản sửa Astra và handoff BUILD HARNESS

> Review specification ngày **2026-10-07**; implementation cập nhật **2026-10-08** ở HEAD `48b84cd`. Entry point hiện hành: [review Gemini](REVIEW_GEMINI_PHASE4_2026-10-07.md) và [plan/handoff](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md). Các prompt build bên dưới lưu bối cảnh/spec; thực thi sửa theo prompt đầu review hiện hành.
> Runtime baseline: **49671b928ad6badfaa01331174eb73f0e366752e**.
> Phạm vi: 16 tài liệu Phase 4 gốc, STRATEGIC_ANALYSIS_PHASE_4.md và code/runner/CI hiện có.
> Quy trình owner chốt: **Gemini build harness → mở PR → chạy CI → owner review trước merge**.

## Prompt cho Astra xhigh — sửa nhỏ trước BUILD

Owner yêu cầu thêm lượt sửa nhỏ này trước khi giao Gemini. Lượt chỉnh sửa tài liệu ngày 2026-10-07 đã áp dụng R10–R12 ở mức CLOSED(spec); R13 vẫn OPEN cho implementation/pre-merge. Phạm vi Astra là sửa specification; executable harness/schema/tests và deployment guard theo diff thực tế thuộc PR Gemini.

~~~text
Bạn là Astra, reasoning effort xhigh. Sửa nhỏ tài liệu Phase 4 trong repo:
D:\year_2026\Work_2026\agentic_AI\CSKH_ban_le

Đọc docs/phase4/REVIEW_PHASE_4_PLAN.md, các findings R10–R13 và code liên quan.
Thực hiện sửa trực tiếp tài liệu hiện có, không chỉ viết thêm đề xuất. Không viết lại
toàn bộ 16 tài liệu nếu không cần; đồng bộ các câu/example liên quan và hai review.

1. R10 — Measured zero
- Sửa PHASE_4_RESULTS_SCHEMA.md và PHASE_4_METRICS_DEFINITION.md: model_calls=0 hợp lệ
  khi observer/trace chứng minh không gọi model, gồm rule refusal/direct response/handoff,
  replay/cache. cache_hit=false/null không tự làm zero sai và cũng không chứng minh zero.
- Missing/unobserved phải null + reason; runtime default 0 không đủ evidence.
- Định nghĩa provider_inference_ms là tổng theo attempt hay latency theo inference;
  tổng có thể 0 khi instrumentation xác nhận không invocation, inference không phát sinh
  là N/A/null. Sửa ví dụ invalid hiện chỉ dựa cache_hit:null; thêm valid rule-only zero
  và invalid fabricated-zero example. Không sửa runtime để hợp thức hóa contract.

2. R11 — Gate wording
- Đồng bộ PLAN/HANDOFF/STRATEGIC/EVIDENCE/INFRA/TIMELINE ở các chỗ cần thiết:
  chỉ G5 LANE_MEASUREMENT_READY được ghi READY FOR MEASUREMENT.
- G3 là authorization; GPU/model load/endpoint smoke evidence phát sinh sau G3 ở G4,
  không đòi paid evidence trước approval. G6 full-run approval vẫn riêng.

3. R12 — Normative serialization
- Common case envelope và required lists của attempts/grading/retrieval/errors phải
  thống nhất logical_request_id và join keys; quy định unique IDs/retry joins rõ.
- Chốt convention null/unavailable reasons và typed safety/severity theo taxonomy;
  sửa examples cho nhất quán. Tách labeled-unanswerable, annotation-missing và
  not-applicable; giữ annotation/qrels hash/version khi retrieval metric N/A.
- Thêm illustrative examples đủ bảy canonical artifacts với refs liên kết hợp lệ.
  Ghi rõ mock/illustrative, không gọi JSON parse là executable schema validation.
  Machine-readable schemas, writer/validator và full-bundle tests vẫn là BUILD backlog.

4. R13 — Deployment mitigation trước merge
- Đọc .github/workflows/deploy-ec2.yml: main push có thể deploy khi
  RETAILOPS_DEPLOY_ENABLED=true; chưa được suy ra giá trị repo variable.
- Chốt một mitigation cụ thể, reviewable trong HANDOFF và prompt Gemini để eval-only
  merge không tự deploy. Guard phải dựa scope/changed files thực tế; không tùy tiện
  hardcode thư mục harness chưa tồn tại, không ignore rộng toàn scripts/.github/Dockerfile.
- Acceptance: eval-only changes không deploy; mixed eval+runtime vẫn deploy eligible
  theo policy hiện có; manual dispatch giữ nguyên; không đổi repo variables hoặc tắt
  deployment toàn cục. Gemini triển khai/test guard trong cùng harness PR.
- Giữ R13 OPEN (implementation/pre-merge) cho tới khi có guard và evidence thực tế;
  không ghi CLOSED chỉ vì đã viết mitigation. Lượt Astra này không sửa workflow/runtime.

5. Reviews và kiểm tra
- Cập nhật docs/phase4/REVIEW_PHASE_4_PLAN.md và docs/PHASE_4_REVIEW_2026-10-06.md.
  Cô đọng lịch sử; R10–R12 chỉ CLOSED(spec) nếu câu chữ/examples đã sửa và kiểm tra.
  Không đóng G1/G2 hoặc implementation checks chỉ bằng tài liệu.
- Chạy check_docs_contract.py, cả hai check_eval_dataset.py bằng explicit frozen paths,
  check_deployment_contract.py, check_live_e2e_contract.py, build_agent_notebook.py --check;
  kiểm LF hashes, JSON example parse/key/ref consistency, links và whitespace.
- Báo changed files, mapping R10–R13 trước/sau, PASS/FAIL/ERROR/SKIP và phần còn mở.
  Giữ READY FOR HARNESS/PREFLIGHT. Không build harness, paid API/cloud/deploy/live smoke,
  measurement, sửa frozen benchmark, mở PR hoặc merge trong lượt sửa docs này.

Kết thúc bằng prompt trigger Gemini đã cập nhật: BUILD HARNESS → mở PR → CI →
owner review trước merge. Gemini phải đóng executable acceptance và deployment guard;
không tự merge hoặc chuyển sang measurement.
~~~

## Prompt ngắn cho Gemini Antigravity

~~~text
Thực thi BUILD HARNESS Phase 4 offline/local trong repo CSKH_ban_le. Đọc docs/phase4/REVIEW_PHASE_4_PLAN.md, nhất là mục Prompt thực thi đầy đủ, rồi PLAN_PHASE_4_EVALUATION.md và PHASE_4_EXECUTION_HANDOFF.md. Implement evaluation-only harness/schema/fixture/grader/qrels/writer/validator/telemetry; giữ baseline business behavior, prompt, routing/RBAC, schema production và hai frozen benchmark. Đóng R10–R13 trong build PR, nhất là measured zero của refusal/handoff không gọi model. Chạy offline/adversarial acceptance và clean-checkout replay, mở PR, chạy/theo dõi CI và sửa lỗi thuộc PR. Dừng ở PR chờ owner review; không tự merge. Không chạy paid API/cloud/deploy/live smoke/full measurement. Báo evidence thật, gate đạt/còn mở; không gọi CI/mock output là READY FOR MEASUREMENT.
~~~

## Kết luận

**Đủ specification để bắt đầu BUILD HARNESS offline/local. Không còn P1 buộc quay lại một vòng sửa tài liệu lớn với Astra.** Đây là chấp nhận đầu vào build, chưa nghiệm thu harness hoặc measurement.

Bản fix đã giải quyết mâu thuẫn lớn về raw records, identity, adapter vLLM, cache/retry và 4A/4B. R10–R12 đã CLOSED(spec). R13 còn OPEN cho implementation/pre-merge. Gemini phải đóng executable acceptance R10–R12 và triển khai/test deployment guard R13 trong cùng PR; owner review trước merge. Không cần harness/schema executable hoặc GPU/price evidence đã tồn tại mới được bắt đầu build.

Trạng thái hiện hành: **READY FOR HARNESS/PREFLIGHT**. G1 chưa có implementation evidence; G2 chưa thể đóng khi PR chưa merge. Hoàn thành build, CI pass và merge vẫn cần G3 approval, G4 live smoke và G5 lane readiness; full measurement cần G6 riêng.

## Astra đã sửa như thế nào

| ID cũ | Đối chiếu bản mới | Kết quả review |
|---|---|---|
| R01 Raw JSONL/join/nullability | RESULTS_SCHEMA có contract riêng theo artifact, common envelope, retry group và unique attempt; bỏ whole-report schema áp sai lên JSONL. | Đủ để build; executable schemas/cross-file validator là deliverable. |
| R02 BUILD scope và identities | PLAN/HANDOFF/STRATEGIC cho phép evaluation tooling/overlay, giữ business/RBAC/prompt/storage/frozen input; tách system/harness/overlay. | Đã giải quyết ở spec; SHA phải đúng source thực sự chạy. |
| R03 vLLM adapter | INFRA chốt api-vllm-selfhost-v1 qua provider_id=api/OpenAI-compatible; custom chỉ /agent/* hoặc bridge pinned. | Khớp selection/protocol hiện tại; real deployment/model compatibility thuộc live preflight. |
| R04 Offline/smoke/full gates | G0→G7 tách offline, merge/replay, approval smoke, live smoke, lane ready và full approval. | Đã giải quyết; CI không cấp quyền merge hoặc paid execution. |
| R05 4A/4B | 4A là A0 baseline/decision; OCR/history/positive mutation/embedding/reranker không khóa 4A. | Đã giải quyết; paired provider comparison là conditional 4B. |
| R06 Metrics/retry/rubric | First attempt primary; eventual secondary; denominator/safety veto riêng; anchors/adjudication thành build deliverable. | Đủ thiết kế; measured-zero contract đã được chốt ở R10. Threshold/completeness pin trước live run. |
| R07 Cache/cold/warm | A0 semantic answer-cache OFF cả hai lane; ToolCache riêng; cold/warm/ablation/diagnostic có run ID riêng. | Đã giải quyết ở spec; controller/assertion cần build. |
| R08 Fixture/identity/artifact | Sidecar case→identity/fixture/focus/prior turns; canonical bundle; PG/KB/qrels/hash và unavailable identity. | Đủ để build; serialization/provenance đã chốt ở R12, executable validator vẫn là deliverable. |
| R09 Infra/shared host/timeline | Tách client concurrency, Waitress/conv_lock/InferenceGate/vLLM; offline trước approval; không tự stop shared host. | Thiết kế đủ; readiness wording đã chốt ở R11. |

“Đã giải quyết ở spec” không đồng nghĩa B01–B08/S01–S04/F/M/H checks đã chạy. Review trước gắn cả R01–R09 là CLOSED (spec) quá tuyệt đối ở measured-zero; review này giữ rõ phần còn mở.

## Findings P1/P2/P3 hiện hành

### P1 — Không có blocker mới cho việc bắt đầu BUILD offline

Thiếu harness code, schemas executable, real provider/GPU/PG evidence hoặc budget approved là deliverable/gate tiếp theo. Không yêu cầu baseline đạt 250/250 để nghiệm thu harness; grader phải phát hiện cả lỗi có thật của baseline.

### R10 — P2: Measured zero trong mọi no-model path — CLOSED(spec)

**Trước:** RESULTS_SCHEMA/METRICS chỉ cho `model_calls=0` và `provider_inference_ms=0.0` cho replay/cache, nên loại refusal, direct response và human handoff không gọi model.

**Sau:** PHASE_4_RESULTS_SCHEMA.md và PHASE_4_METRICS_DEFINITION.md chấp nhận zero khi observer/trace chứng minh không có model invocation, gồm refusal, direct response, human handoff, replay và cache. Contract yêu cầu `trace.model_invocation_observed=true` và `trace.zero_reason`; `cache_hit=false/null` không đủ bằng chứng. Missing/unobserved là `null` + `unavailable_reason`; fabricated zero bị reject.

**Giới hạn:** runtime chưa đổi; writer/validator/telemetry acceptance vẫn là BUILD backlog. R10 đóng ở mức specification, chưa phải implementation evidence.

### R11 — P3: Readiness chỉ tại G5 — CLOSED(spec)

**Trước:** một số tài liệu diễn đạt READY FOR MEASUREMENT sau G4/M5, trong khi checklist dùng G5.

**Sau:** PLAN, HANDOFF, EVIDENCE, INFRA, TIMELINE và STRATEGIC đều chốt: G3 là authorization, G4 là LIVE_SMOKE, **chỉ G5** mới được ghi `READY FOR MEASUREMENT`. G6 là full-run approval riêng; G7 là measured/baseline accepted.

**Giới hạn:** chưa có live smoke hoặc lane manifest; trạng thái tài liệu vẫn `READY FOR HARNESS/PREFLIGHT`.

### R12 — P3: Common envelope, join keys, nullability, provenance — CLOSED(spec)

**Trước:** grading/retrieval/errors chưa lặp đầy đủ logical_request_id; reason/severity/qrels provenance và bảy canonical artifacts chưa được quy định thống nhất.

**Sau:** RESULTS_SCHEMA chốt common envelope cho mọi JSONL; join keys logical/retry/attempt; refs cùng run_id; typed severity S0–S3; phân biệt labeled-unanswerable, annotation-missing, not-applicable; giữ qrels version/source/hash khi metric N/A; thêm illustrative examples cho manifest, attempts, grading, retrieval, errors, aggregate và checksums. Examples được ghi rõ là mock, không thay executable schema validation.

**Giới hạn:** machine-readable schemas, writer, validator và full-bundle tests vẫn là BUILD backlog.

### R13 — P2: Merge harness có thể tự kích hoạt deploy — OPEN (implementation/pre-merge)

**Evidence:** .github/workflows/deploy-ec2.yml nhận push vào main, chỉ ignore docs/Markdown và chạy deploy khi RETAILOPS_DEPLOY_ENABLED=true. Giá trị repo variable thực tế chưa được kiểm tra trong lượt docs này.

**Mitigation đã chốt trong spec:** cùng PR harness phải có guard dựa trên changed files thực tế: eval-only/harness-only không deploy; mixed eval + runtime vẫn giữ policy deploy; workflow_dispatch giữ nguyên; không đổi repo variables, không tắt deploy toàn cục, không ignore rộng toàn scripts/, .github/ hoặc Dockerfile. Guard phải có test eval-only, mixed-scope và manual dispatch.

**Điều kiện đóng:** chỉ CLOSED sau khi Gemini triển khai guard, test guard trong PR, CI pass và owner review diff. Việc viết mitigation không đóng implementation R13.

## Kiểm tra thực tế trong lượt review này

| Check | Kết quả và giới hạn |
|---|---|
| scripts/check_docs_contract.py | PASS 4/4: dataset integrity, stale HEAD, links/Markdown, AST tool contract. |
| check_eval_dataset.py (benchmark_250.jsonl) | PASS, 250 ca; categories 15/40/65/35/35/60. |
| check_eval_dataset.py (master_250_v1.jsonl) | PASS, 250 ca; categories 15/40/65/35/35/60. |
| Frozen benchmark LF SHA-256 | PASS; cả hai = 36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411 sau chuẩn hóa LF; không sửa dataset. |
| scripts/check_deployment_contract.py | PASS; chỉ kiểm static contract, không deploy. |
| scripts/check_live_e2e_contract.py | PASS; không chạy live E2E. |
| scripts/build_agent_notebook.py --check | PASS source sync. |
| RESULTS_SCHEMA examples | PASS: 7 JSON code blocks, 10 JSON records parse được; kiểm common envelope, logical/retry/attempt refs và measured-zero valid/invalid examples. Parse không đồng nghĩa executable schema validation. |
| Whitespace/scope | PASS explicit scan 19 Phase 4/review Markdown; git diff --check PASS. Không có runtime/frozen benchmark diff trong working tree. |
| Paid API/cloud/deploy/measurement | SKIP theo phạm vi; không thực hiện. |

Working tree lúc review chỉ có nhóm tài liệu untracked: Phase 4, strategic analysis và snapshot review; không có tracked code/runtime/dataset diff.

## Prompt thực thi đầy đủ cho Gemini Antigravity

~~~text
BUILD HARNESS Phase 4 tại:
D:\year_2026\Work_2026\agentic_AI\CSKH_ban_le

Đọc REVIEW_PHASE_4_PLAN.md (2026-10-07), PLAN_PHASE_4_EVALUATION.md,
PHASE_4_EXECUTION_HANDOFF.md và các contracts results/metrics/test matrix/taxonomy/
evidence/reproducibility/infra/statistics/cost trong docs/phase4 cùng
docs/STRATEGIC_ANALYSIS_PHASE_4.md. Đây là BUILD offline, chưa measurement.

1. Scope/Git/identity
- Kiểm tra HEAD/working tree/hướng dẫn repo. Bảo toàn tài liệu đang untracked, chụp hashes;
  tạo nhánh riêng, ưu tiên codex/phase4-harness.
- Implement evaluation-only schemas, runner/controller, fixture/identity sidecar,
  qrels/annotation, grader/adjudication, writer/validator/telemetry, CLI/tests/docs/CI.
  Không đổi business behavior/prompt/worker/routing/RBAC/production schema/adapter semantics,
  frozen benchmark hoặc labels để tăng score. Runtime bug là baseline finding riêng.
- Runtime A0 pinned 49671b928ad6badfaa01331174eb73f0e366752e. Pin đúng source runtime thực sự
  load, harness commit và overlay hash/none. G1 dùng PR-head harness SHA; sau owner merge,
  G2 dùng merged revision và replay mới. Không placeholder SHA trong accepted bundle,
  không gán SHA baseline cũ cho source khác mà thiếu bằng chứng runtime provenance.

2. Đóng R10–R13 trong cùng PR
- Sửa cache-only zero rule và ví dụ invalid trong RESULTS_SCHEMA/METRICS; valid traced
  no-model refusal/handoff được nhận, unobserved zero bị reject; timing scope rõ.
- G5 là READY FOR MEASUREMENT; paid/GPU/endpoint evidence sau G3 authorization.
- logical_request_id thống nhất ở case records; null reasons/severity typed; tách labeled
  no-evidence, missing annotation và not-applicable, giữ annotation provenance.
- Kiểm deploy-ec2.yml: push main có thể auto deploy nếu RETAILOPS_DEPLOY_ENABLED=true.
  PR phải có mitigation reviewable theo changed paths, để eval-only merge không gây deploy;
  không thay repo variables/tắt deploy toàn cục. Báo owner acceptance R13 trước merge.

3. Raw bundle/validator/CLI
- Machine-readable schemas theo artifact; không áp whole-report schema lên JSONL.
  Canonical output: manifest.json, attempts.jsonl, grading.jsonl, retrieval.jsonl,
  errors.jsonl, aggregate.json, checksums.sha256 trong run directory.
- Append mọi attempt kể cả failure; unique IDs, joins/provenance và retry sequence/class.
  Validator kiểm schema/joins/identity/frozen hashes/split/category, scheduled/attempted/
  graded/blocked coverage, checksum corruption và aggregate recompute từ raw.
- Measured zero có proof; unavailable null + reason; legacy default zero không đủ proof.
  Chốt checksum policy tránh tự tham chiếu; input hashes trong manifest.
- CLI offline run/validate/recompute/replay có help/exit code/commands; sinh canonical mock
  bundle, ghi OFFLINE/MOCK rõ. Accepted raw rows đều có common provenance.

4. Runner/fixtures/cache/retry/telemetry
- Sidecar cho 250 case: tenant/principal/role/fixture/focus/scenario family/prior turns/
  answerability/claim refs. Synthetic isolated/idempotent setup; negative-owner fixtures
  đi qua public ownership guards, không bypass để chèn invalid focus.
- A0 semantic answer-cache read/write OFF có effective assertion. Runtime chưa có switch
  chung: eval-only injected controller/no-op cache overlay có hash, giữ business/guardrails.
  ToolCache/DB/model prefix cache riêng; cross-case hits là contamination.
- Mock transport 200/empty/malformed/429/timeout/5xx; pin retry allowlist/backoff/limits,
  chỉ retry transport/runtime. Giữ từng failure; first primary, eventual/recovery secondary;
  backoff/cumulative wait quan sát được. Diagnostic/warmup/load/cold/warm/ablation run riêng.
- E2E đến đọc hết body; TTFB chỉ streaming thật; admission/conv_lock/InferenceGate/provider
  time riêng. Actual tools/arguments/results/mode/evidence từ observation, không từ expected.
- vLLM dùng provider_id=api; custom chỉ /agent/* hoặc pinned bridge. API endpoint hiện là
  process-global: reference/vLLM lane có config/process độc lập, không đổi endpoint âm thầm
  giữa cases. Preflight phải xác nhận model identity, không coi empty returned model là pass.
  Record sampling thật (API .2/2048), top_p/seed/revisions chưa expose dùng null/reason.
- run_benchmark_eval.py chỉ routing/safety; live HTTP runner giữ final retry và false-pass
  HTTP200. Không coi chúng là canonical grader/writer; reuse chỉ khi tests chặn các lỗi này.

5. Grading/annotation/metrics
- Kiểm routing, minimum required/forbidden tools, arguments/owner/outcome/evidence/claims,
  severity/S0-S1 veto. Safe answer thiếu required tool vẫn fail contract; không nới expected
  tools vì worker baseline không hỗ trợ. Không đòi runtime 250/250 để harness acceptance.
- Version anchors 0/1/2, blinded grading/manual import/adjudication. Qrels/claim labels có
  corpus/fixture source và hash; mock labels chỉ test pipeline, không là live quality.
  Chưa đủ annotation thật thì metric BLOCKED/N/A. Tối thiểu dev fixtures/qrels/anchors
  cho offline acceptance; annotation coverage thiếu cho live A0 phải được báo.
- Không tune trên held_out, không đổi frozen data. Tách N_total/N_attempt/N_graded_first/
  N_graded_eventual/N_blocked, first/eventual, conditional quality/E2E reliability.
- Formulas/CI/cluster unit, nearest-rank và denominator tests có raw evidence.
  Version preregistration config cho deadline/threshold/CI-role/completeness/repetition/cap;
  pin trước live run, không chọn sau outcomes. Chưa approved budget phải fail live gate.

6. Acceptance/CI/replay
- Adversarial tests: malformed/empty200, missing/forbidden tool, wrong owner, unsupported
  claim, correct/incorrect abstention, labeled/unlabeled no-evidence, observed/fabricated zero,
  429→200 giữ first fail, timeout, duplicate/orphan join, identity/hash/checksum/aggregate
  corruption và cache OFF.
- Offline không gọi provider/live business services; dùng mock/isolated test DB nếu cần.
  PostgreSQL/pgvector chỉ PASS khi thật sự chạy; SKIP nêu rõ, mock không đóng live preflight.
- Chạy six commands REPRODUCIBILITY (cả hai explicit frozen paths), meaningful harness tests,
  full existing runtime suite và repo CI. Không đổi test để che baseline gaps.
  Existing CI chạy tests cả trong Docker image; bảo đảm harness assets/imports có mặt ở
  môi trường test thực tế, không tạo SKIP giả để tránh packaging failure. Ghi rõ mọi
  Docker/CI/deploy-filter thay đổi phục vụ evaluation trong PR cho owner review.
- Commit implementation, clean-checkout replay và bundle/checksums tái tính được. G1 chỉ
  đóng khi offline acceptance đủ evidence; branch replay không tự đóng G2 trước merge.

7. PR/điểm dừng
- Push, mở PR, chạy/theo dõi CI, sửa failures thuộc PR. PR ghi problem/behavior, scope,
  tests/artifacts/checksums, R10–R13 closure, limitations và gates còn mở.
- Đưa bộ docs Phase 4 mà PR tham chiếu vào Git/PR, không chỉ local untracked; review diff
  tránh stage nhầm datasets/artifacts/secrets. GitHub push/PR/CI thuộc scope được giao.
- CI pass: báo PR URL/head SHA/validation, dừng chờ OWNER REVIEW TRƯỚC MERGE.
  Không tự merge hoặc bật auto-merge. Nếu thiếu quyền GitHub/CI, giữ local branch/commits
  hoàn chỉnh và báo chính xác phần external chưa làm được.
- Không paid API/cloud/shared-host/GPU lifecycle/deploy/live smoke/public load/full measurement.
  Sau owner merge mới G2 merged CI+clean replay; G3 approval→G4 live smoke→G5 lane ready;
  G6 separate full-run approval. Không tự chuyển từ build sang measurement.
~~~

## Lịch sử cô đọng

Review trước phát hiện whole-report/JSONL conflict, scope cản harness, custom→vLLM sai và dependency cycle paid-smoke. Astra đã sửa bốn nhóm này cùng retry/cache/4A–4B. Review 2026-10-07 xác nhận đủ đầu vào build, giữ R10–R13 làm acceptance cụ thể. [Snapshot cũ](../PHASE_4_REVIEW_2026-10-06.md) chỉ giữ lịch sử, không có verdict cạnh tranh.

## Mapping findings trước/sau

| Finding | Trước | Sau |
|---|---|---|
| R10 | zero chỉ được chấp nhận cho cache/replay | observed no-model path được chấp nhận; fabricated zero bị reject; missing là null + reason |
| R11 | G4/M5 và G5 diễn đạt không đồng nhất | chỉ G5 ghi READY FOR MEASUREMENT; G4 chỉ là LIVE_SMOKE |
| R12 | envelope/join/nullability/provenance chưa normative đầy đủ | common envelope, join keys, typed severity, no-evidence labels và bảy artifact examples đã chốt |
| R13 | merge harness có thể chạm deploy nếu variable bật | mitigation changed-files có implementation/9 tests/CI; toàn PR packaging eligible; báo owner trước merge |

## Prompt Gemini cập nhật

```text
BUILD HARNESS Phase 4 offline/local theo docs/phase4/REVIEW_PHASE_4_PLAN.md và PHASE_4_EXECUTION_HANDOFF.md. Implement schema/writer/validator/fixtures/grader/qrels/telemetry và acceptance cho R10–R12; triển khai/test deployment guard R13 dựa trên changed files thực tế. Giữ runtime baseline, frozen benchmarks, A0 cache OFF và không chạy paid/cloud/live smoke/measurement. Mở PR, chạy CI và clean-checkout replay, báo evidence thực tế. Sau CI xanh, DỪNG và chờ OWNER REVIEW trước merge; không tự merge hoặc chuyển READY FOR MEASUREMENT. Chuỗi bắt buộc: BUILD HARNESS → mở PR → CI → owner review.
```

## Trạng thái chốt 2026-10-07

R10–R12: CLOSED(spec), implementation còn N1–N5 acceptance. R13: DONE OFFLINE/CI; actual PR diff packaging eligible theo policy. G1 có implementation/test evidence nhưng chưa accepted đầy đủ; G2 chưa merge. Trạng thái chính thức: READY FOR HARNESS/PREFLIGHT.

