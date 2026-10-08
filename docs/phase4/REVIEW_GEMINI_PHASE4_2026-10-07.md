# Review độc lập Gemini Phase 4 — R10–R13

## Prompt Gemini — dùng làm trigger

```text
Đọc docs/phase4/PHASE_4_ACCEPTANCE_CRITERIA.md. Chỉ hoàn tất N1/N3/N4 theo scope đã chốt, chạy đúng 8 check và đóng băng HEAD. Chuyển mọi việc ngoài checklist vào PHASE_5_BACKLOG.md; giao evidence cho reviewer độc lập mới sign-off 8 mục, rồi owner review → merge → G2 offline replay. Không tự chạy live/paid hoặc cấp READY FOR MEASUREMENT.
```

> Review: 2026-10-08. Branch: `codex/phase4-harness`.
> HEAD đã kiểm tra: `04ed8990019e99fbca2321ebbaf100669d42c031`.
> Runtime baseline: `49671b928ad6badfaa01331174eb73f0e366752e`.
> PR: [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36), open/unmerged; PR head khớp local.
> Verdict này thay thế review `48b84cd` và các đoạn Gemini tự ghi CLOSED. Chỉ các thay đổi tài liệu của lượt review này chưa commit/push.

## Quyết định nghiệm thu owner — ưu tiên hơn phân loại findings cũ

Owner chốt **blocker + đúng 8 check** tại [Acceptance Criteria v1](PHASE_4_ACCEPTANCE_CRITERIA.md). Không mở rộng audit. N1 manual-source replay hardening **DEFERRED**; mutation manifest hash vẫn bắt reject. N3 quality denominator **DONE**; completeness/counts chuyển Phase5. N4 tools type đã đúng, chỉ còn type safety flags grader sử dụng phải đóng K3. L2/L4/L5 và positive-count thiếu tool names vào [Phase5 backlog](PHASE_5_BACKLOG.md), **không block merge**.

**Verdict merge hiện tại: PENDING K3 + frozen-head evidence + independent sign-off 8/8.** Các findings nguồn bên dưới giữ evidence/history, không tự thành yêu cầu sửa trong PR này. Status vẫn READY FOR HARNESS/PREFLIGHT; chưa merge/G2/live. Reviewer Codex hiện tại không được dùng làm independent sign-off.


## Phạm vi và verification độc lập

Đối chiếu 24 file trong diff `48b84cd → 04ed899`, và scope toàn PR từ runtime baseline: schema/constants/grader/gates/runner/validator/CLI, tests, notebook bundle và toàn bộ docs tiến độ Gemini commit. Business runtime/frozen datasets giữ nguyên. Notebook chỉ đổi cell source bundle sinh tự động, không đổi số cells hoặc outputs; source-sync contract pass.

| Check | Kết quả trên HEAD hiện tại |
|---|---|
| Phase 4 targeted | PASS — 69 tests |
| Deployment guard | PASS — 9 tests |
| Full local unittest | **FAIL lần đầu** — 574 tests, 49 skipped, 1 failure P99 headroom; không error |
| Focused rerun bài P99 đã fail | PASS — 1 test, không sửa code/ngưỡng |
| Docs contract | PASS — 4/4 |
| Dataset baseline / benchmark / master | PASS — 30 / 250 / 250 |
| Deployment / live-E2E / notebook sync / diff whitespace | PASS |
| Mock 250 | VALID structural — 250 cases, 263 attempts, 250 gradings/retrievals, 13 errors; harness SHA đúng HEAD |
| Mock aggregate | quality 185/237=0.7806; current eventual completeness=1.0, missing=0; chưa chứng minh semantics trên blocked/missing |
| Exact-head remote CI | SUCCESS — offline, colab-python313, portable Windows/Ubuntu, postgres |

Full local failure: `tests/test_http_headroom.py:630`, GET `/api/session` P99 **52.520800 ms > 50 ms**. Chạy lại riêng bài đó pass. Business HTTP/runtime/headroom test không đổi trong patch; hiện là tín hiệu timing không ổn định trên host, chưa chứng minh regression do harness. Không giấu failure hoặc gọi lần full này PASS; không hạ ngưỡng để đóng review.

CI [37733503190](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37733503190), offline job [113167758983](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37733503190/job/113167758983), Ops [37733503225](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37733503225): 5 check-runs đều success, PR head đúng `04ed899`. Workflow offline có Docker build/packaged tests bắt buộc, không có điều kiện skip ở các bước này. Không có local Docker CLI. Public job-step API bị rate limit; kết luận CI dựa check-runs và workflow source, không bịa step metadata.

Mutation probes dùng temporary source copies/bundles, cập nhật aggregate/checksums khi phù hợp. Không sửa frozen scenario files hoặc code production để tái hiện.

## DONE / phần đã sửa đúng

| Finding | Trạng thái chính xác |
|---|---|
| B1–B6 cũ | DONE VERIFIED — packaging, rates/histograms, finite JSON, first flag consistency, safety-before-transport, G5-only grant |
| N1 common provenance + qrels | DONE phần này — 7 trường manifest/raw/target được đối chiếu; 28 field mutations bị reject; qrels missing/unreadable/hash mismatch fail-closed; runner bỏ empty fallback |
| N1 fixture hash | DONE phần sinh — hash từ generated canonical sidecar thay placeholder; source benchmark hash khi validator replay còn mở dưới đây |
| N2 | DONE — unknown IDs, duplicate primary request, retry sequence kiểm đúng; valid subset/retry vẫn pass. Selection full/live cụ thể phải preregister khi mở lane |
| N3 quality denominator | DONE phần này — thêm 13 blocked first-429 grading vẫn giữ 185/237; completeness/missing chưa đúng |
| N4 tools type + một số flags | DONE phần này — string/int/mixed tools bị schema reject; còn omissions/contradiction dưới đây |
| N5 | DONE bypass mock/preflight/null-SHA — các bundle này không grant G5; G6 không grant. Live G4 proof/identity/budget/completeness vẫn là acceptance bước sau, checker offline không tự chứng minh lane ready |
| L1 | DONE — completed text null reject; null transport response không crash |
| L2 recompute/missing paths | DONE phần này — invalid bundle/missing paths exit 1; canonical source checks còn mở |
| L3 | PARTIAL — có fields/type checks; calculation sai, gộp sửa trong N3 |
| L4 | DONE typo status enum và G5 docstring; preflight gate metadata còn nhẹ |
| R13 | DONE OFFLINE/CI — 9 guard tests, deployment contract và exact-head CI success |

## Findings source tại HEAD04 — disposition theo acceptance v1

### N1 — Validator chưa hash file benchmark thực tế

**Disposition: DEFERRED → P5-01; không block merge.** Chỉ K1 mutation manifest hash thuộc cổng Phase4; cách sửa/reproduction dưới đây dành Phase5.

**Vị trí:** `evals/harness/validator.py:359–384`; runner đã kiểm LF source hash tại `runner.py:139–144`.

Validator generate sidecar từ scenario file và chỉ so `manifest.dataset_sha256` với constant. Nó không hash scenario bytes đang đọc. Probe tạo bản sao benchmark, thêm `source_audit_marker` vào `user_text` của case đầu (IDs, focus và sidecar giữ nguyên): actual LF SHA thành `1701a1f254ad9c0deb82eb06675279eb70fec33e3b327a59e32be108a123725a`, khác frozen `36fa8c7a...`; sidecar vẫn `69e9835d...`; bundle cũ vẫn **valid, errors=[]** khi validator dùng source copy. Repo frozen file không bị chỉnh.

**Sửa nhỏ nhất:** helper chung load scenario + normalize CRLF→LF + SHA-256; kiểm actual source hash khớp manifest và frozen identity trước sidecar/membership. Resolve benchmark ID từ registry/path được pin, không chỉ tin filename/manifest hash. Generated sidecar là input hiện tại; ghi rõ canonical serialization. Không ép hash raw CRLF fixture phải bằng canonical JSON hash và không sửa frozen bytes.

**Acceptance:** source edit giữ nguyên sidecar/IDs vẫn reject; LF/CRLF cùng nội dung pass theo convention; missing/unreadable/malformed source fail-closed; runner và validator dùng chung hash rule. Giữ 28 provenance mutations và qrels controls đã pass.

### N3 + L3 — N_graded/completeness/missing còn sai

**Disposition: quality denominator DONE; counts/completeness → P5-02, không block merge.** Acceptance v1 chỉ yêu cầu blocked không đổi denominator.

**Vị trí:** `validator.py:165–177,205–207`. Contract: metrics §1–§2 (`N_graded` là case đủ evidence quality, completeness=`N_graded/N_total`).

`graded_case_ids` vẫn nhận mọi decision, kể cả blocked/inconclusive. Blocked set chồng lên graded; `max(0,total-graded-blocked)` trừ trùng và che missing.

Probe dùng **3 primary 429 thật + errors thật**, bỏ retries, gọi `Phase4Grader` tạo blocked grading: validator valid nhưng trả **n_total=3, n_graded=3, n_blocked=3, completeness=1.0**, quality denominator 0. Probe blocked + một case không có grading cũng có thể báo missing 0. Denominator 185/237 đã sửa, không làm lại phần đó.

**Sửa nhỏ nhất:** xác định một disposition cho từng case tại cấp first/eventual; quality-eligible set dùng cho `N_graded`. Missing tính bằng hiệu tập case với các dispositions đã khai báo, không trừ counts overlap hoặc clamp lỗi. Nếu giữ n_graded eventual, báo primary completeness/blocked/missing riêng để first-429 được recover không che thiếu primary evidence. Schema, recompute, validator và metrics docs dùng cùng semantics; blocked-only/inconclusive không thành complete quality.

**Acceptance:** all-blocked/all-inconclusive không completeness 1; blocked+missing báo đúng missing; blocked→retry pass tách primary/eventual; `n_total` bao gồm mọi scheduled case; gradable fail/rejected vẫn trong denominator; thêm blocked annotation không đổi 185/237.

### N4 — Safety flags không đồng nhất và tool-count thiếu evidence

**Disposition: sai kiểu safety flags vẫn thuộc K3.** Positive-count nhưng missing names là semantic improvement → P5-03, không block merge; không thêm vào checklist type.

**Vị trí:** `schema.py:377–395`; `grader.py:80–114`.

- Schema kiểm `ownership_bypass`, grader lại đọc `ownership_violation` và `identity_collision`. Hai flags grader dùng nhận `"true"`/`1`, schema accept, grader **pass**, full canonical bundle cũng valid. Bool True controls trả rejected S0 đúng. `ownership_bypass=True` hiện bị grader bỏ qua.
- Case frozen `ro_s5_011` yêu cầu no-tool và có 12 forbidden tools. `tool_count=1` nhưng `tools_called=[]` hoặc absent vẫn schema accept, grader pass, bundle valid. Type/range checks không chứng minh tool nào đã gọi; không được mặc định thiếu trace thành an toàn.

**Sửa nhỏ nhất:** shared canonical safety-flag definitions giữa observer/schema/grader; kiểm strict bool mọi flag được tiêu thụ. Chốt canonical ownership name/alias, không để hai nơi dùng hai tên. Tool count dương phải có tool-name evidence hoặc explicit unavailable/inconclusive, không quality pass; observed no-tool có count 0/list rỗng hợp lệ. Không ép số calls bằng số tên tool duy nhất; repeated calls cùng tên vẫn hợp lệ. Grader gọi validation chung hoặc xử lý malformed evidence có kiểm soát trước mọi early return.

**Acceptance:** ownership/identity string/int bị reject; true controls rejected S0 cả completed và mixed transport; alias policy nhất quán. Positive count + missing/empty names không pass; observed zero và repeated same tool pass khi hợp lệ. Giữ forbidden-string/privacy/transport regression đã đóng.

## Lỗi nhẹ — chuyển Phase5, không block merge

### L2 — CLI chưa xác minh canonical integrity

`cli.py:85–121` kiểm tồn tại/nonempty và in hash nhưng không đối chiếu expected canonical hash. Bản qrels có nội dung đổi vẫn `QRELS_OK`, exit 0, SHA `99c8cd69...`; sidecar-preserving benchmark edit cũng `SIDECAR_OK`. Không nói đã verify frozen integrity nếu chỉ parse/generate được.

Default canonical check nên đối chiếu actual LF dataset, canonical sidecar và qrels expected SHA; input tùy chọn cho diagnostic phải ghi rõ mode hoặc nhận expected hash riêng. Mismatch canonical exit 1; generic diagnostic không gọi canonical acceptance. Missing-path/recompute fixes giữ nguyên.

### L4 — Gate metadata preflight chưa được kiểm

`schema.py:195–213` chỉ kiểm gate khi status là measurement-ready. Preflight status + `gate="G999"`/null vẫn accept. Khi gate được khai báo, kiểm enum; chốt rõ có bắt buộc gate khi có readiness_status hay không. `gates.py:10` sequence comment cũng thiếu G7. Đây là metadata/wording, không mở lại quyền grant G6.

### L5 — Review/progress/PR description chưa nhất quán

Review header vẫn HEAD cũ/BLOCKED N1–N5, cuối file lại nói toàn bộ CLOSED; plan cũng mâu thuẫn. Lượt review này thay bằng một verdict trên HEAD mới. Gemini cần tiếp tục cập nhật sau sửa bằng evidence thật.

PR #36 description đang ghi 523/27 tests và guard `deploy_eligible=false` trên 41 files; hiện là 69+9 targeted, full local có failure/rerun và full PR guard **true** vì packaging. Body còn local system URL links/control characters từ escaped text. Gemini viết lại PR body ngắn: scope, residual closures, exact HEAD, verification/limitations, CI links, mixed packaging eligibility và owner-review gate. Dùng structured body hoặc `--body-file` có newlines thật; không thêm claim all-CLOSED/full-PASS thiếu proof.

## Verdict R10–R13 và deployment

| Thành phần | Verdict |
|---|---|
| R10 | PENDING K3 — safety flags type; semantic tool evidence vào backlog |
| R11 | DONE OFFLINE GUARD — L4 backlog; live readiness chưa nghiệm thu |
| R12 | ACCEPTABLE SCOPE v1 — hash mutation/quality denominator DONE; source replay/completeness deferred Phase5 |
| R13 | DONE OFFLINE/CI — guard + packaging checks đạt |

Toàn diff baseline→HEAD guard trả **deploy_eligible=true** do `.dockerignore`, `Dockerfile`, `scripts/check_deployment_contract.py`. PR mixed packaging/evaluation; merge có thể deploy khi policy/variable hiện hữu cho phép. Chưa kiểm/thay repo variables, chưa merge/deploy. Không nói PR eval-only hoặc luôn skip deploy.

## Plan và bước tiếp theo

Chỉ thực thi [acceptance v1](PHASE_4_ACCEPTANCE_CRITERIA.md) và [plan](PLAN_REVIEW_HANDOFF_GEMINI_2026-10-07.md). Hoàn tất K3 còn thiếu, freeze code HEAD, verify đúng 8 check, một model khác/human chưa review N1–N5 sign-off 8/8. PASS thì kết thúc review engineering; owner review → merge → G2 offline replay. Mọi phát hiện ngoài checklist sau freeze ghi Phase5, không block merge. Không tự chạy live/paid hoặc cấp READY FOR MEASUREMENT trước G5.
