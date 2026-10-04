# Bàn giao triển khai Module 2.5 — GPT 6 Astra

Ngày cập nhật trạng thái: **04/10/2026 — Asia/Bangkok**.
Trạng thái hiện tại: **N08 VERIFIED; PR A đủ điều kiện review / nghiệm thu (merge là quyết định riêng).** Code patch `c4e9976` (c4e99769ec46be3d8fe33d272527e9c73b3b0ad1); final docs tree `eebe8ed` (eebe8edefd52abb1af86e9e8bdf2173413c25fd1) được CI run 37197602401 xác nhận SUCCESS (head_sha = eebe8ed; host 479/479 PASS, 0 SKIP; container 478 PASS / 1 SKIP). CI run 37196429628 trên `c4e9976` là bằng chứng lịch sử cho code patch. Local: 479 tests, 429 PASS, 50 SKIP. Xem [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md).
Working snapshot: branch `feature/module-2.5-pr-a`.
Quỹ đạo: **trigger `N08-P11-RESOLVE-FAIL-CLOSED` hoàn tất → regression SQLite/PostgreSQL hoàn tất → suite/gates PASS → CI trên SHA cuối PASS → review / nghiệm thu PR A (tiếp theo) → merge theo quyết định riêng → PR B → implementation verification → Phase 4 benchmark**.
Nguồn quyết định/lịch sử: `docs/review gpt 6 astra.md`; điều kiện dừng hiện hành: [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md).

## 1. Mục đích và ranh giới trạng thái

Mốc **14/14 mục R01–R14** chỉ xác nhận đặc tả tài liệu tại thời điểm trước, không thay thế kiểm chứng runtime. N08 hiện được đánh giá theo bằng chứng local và final-CI tại N08_STOPPING_CONDITIONS.md.

| Mốc | Trạng thái lúc bàn giao | Điều kiện chuyển |
| --- | --- | --- |
| PLAN_READY_TO_IMPLEMENT | **ĐẠT — mốc lịch sử 01/10/2026** | Các đặc tả A/B đã sẵn sàng tại baseline lúc đó |
| N08_P1_GATES | **VERIFIED** | Local 429 PASS / 50 SKIP; CI 37196429628 trên code patch `c4e9976` (lịch sử) và CI 37197602401 trên final tree `eebe8ed` đều SUCCESS. Run trên fe25f67 là historical. |
| PR_A_ACCEPTED | **ĐỦ ĐIỀU KIỆN REVIEW / NGHIỆM THU** | Kỹ thuật đã đạt; chờ quyết định review/nghiệm thu; merge main là bước riêng, chưa thực hiện |
| PR_B | Chưa bắt đầu | Bắt đầu sau khi PR A được nghiệm thu/merge |
| IMPLEMENTATION_VERIFIED | Pending | A/B có đủ evidence theo acceptance và backend được hỗ trợ |
| SCIENTIFIC_EVALUATION_COMPLETE | Pending | Có kết quả frozen benchmark và load matrix Phase 4 |

READY chỉ áp dụng cho **Module 2.5 PR A/B**. Các plan nghiên cứu, post-thesis hoặc superseded không được coi là cùng đạt READY chỉ vì file bàn giao này tồn tại.

> **Phân định kế hoạch và thực thi:** PLAN_READY_TO_IMPLEMENT là mốc lịch sử về chất lượng tài liệu. Patch resolver fail-closed (`c4e9976`) pass local suite với 429 PASS / 50 SKIP; 50 SKIP gồm 36 `tests/test_postgres.py`, 11 `tests/test_rag_chat.py`, 2 `tests/test_knowledge.py`, 1 `tests/test_public_web.py` (thiếu PostgreSQL/pgvector DSN hoặc Waitress local) — local không tuyên bố PostgreSQL PASS. PostgreSQL/pgvector được xác minh trên CI: run 37197602401 (head_sha `eebe8ed`) host suite 479/479 PASS, 0 SKIP. PR A đủ điều kiện review / nghiệm thu. Chưa merge/deploy và chưa bắt đầu PR B.

## 2. Baseline chính xác được duyệt

- Commit repository tại thời điểm review: **d01f729**.
- Audit basis của mã nguồn trong các plan: **c30ff1d**; các thay đổi PLAN được duyệt vẫn nằm trong working tree, chưa được commit bởi reviewer.
- Do đó, chỉ checkout d01f729 sẽ không tái tạo đầy đủ bản tài liệu vừa được nghiệm thu.
- Trước triển khai, giữ nguyên các sửa hiện có và ghi lại commit/snapshot tài liệu được dùng. Không reset working tree về bản PLAN cũ.
- Bảng dưới là SHA-256 của nội dung file sau chuẩn hóa CRLF/CR về LF, tại thời điểm chốt. Nó nhận diện đúng bản đặc tả được review, không phải hash runtime hay bằng chứng CI.

| Plan nguồn | SHA-256 LF-normalized |
| --- | --- |
| [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) | `a1b75aa20831415e0618ff8a5f8e20c73af746e280dddff543d9e5b22ddcb1c7` |
| [PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md](PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md) | `3e81ef4ca1d7a4a1eb1a04b63a22d2711b13625224ed4f2c440c70def9e20311` |
| [PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md) | `635c72dab6ded794811e72c479cbd5c4292ab9c483ef7aefdc78063cc591edcf` |
| [PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md) | `015ea07717a3910c7b41677144587fa28fa86a9b41f22c368c5ae23a29a92aa5` |
| [PLAN_RBAC_GOOGLE_AUTH.md](PLAN_RBAC_GOOGLE_AUTH.md) | `c04667248251d0c8a508899498249cd6a57d214acc225a723da5bfaf846f44c2` |
| [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md) | `68fedff82e255dd12d29f222937ecb8eca5a4ca5896caf87673dde9a983a74be` |

Nếu một plan nguồn thay đổi về hợp đồng, cập nhật phạm vi review của thay đổi đó; không tiếp tục gắn READY cho một phiên bản khác mà chưa kiểm tra. Những chỉnh câu chữ không đổi hợp đồng phải được ghi nhận rõ để phân biệt với snapshot trên.

## 3. Tài liệu dùng khi triển khai

| Nội dung | Nguồn áp dụng |
| --- | --- |
| Correctness, cache/provenance, dispute, truthful wording | [PR A](PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md) |
| Acceptance tổng Module 2.5 | [Hardening & Verification](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) |
| Runtime, admission, gate và telemetry | [Runtime](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md), [Sprint](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md) |
| OAuth/RBAC | [RBAC Google Auth](PLAN_RBAC_GOOGLE_AUTH.md) |
| DB history so với prompt/UI transcript | [FIX04](PLAN_FIX_UI_04_CHAT_HISTORY_RESUME.md) |
| Thứ tự giai đoạn | [Roadmap](PLAN_ROADMAP_INDEX.md) |
| Frozen benchmark | [Evaluation Framework](PLAN_DEEPSEEK_EVAL_FRAMEWORK.md) |

Các tài liệu có nhãn superseded/post-thesis chỉ làm bối cảnh. Câu headroom cũ tại Production Scaling:26 không được dùng thay đặc tả admission hiện hành. Ghi chú P3 đó có thể dọn riêng mà không đổi kiến trúc A/B.

## 4. Phạm vi 13 hạng mục và trách nhiệm PR

| PR | Mã | Kết quả cần đạt |
| --- | --- | --- |
| A | F01 | Cache fail-closed theo query, context, lịch sử và provenance |
| A | F02 | Replay/snapshot/cache commit được serialize đúng |
| A | F03 | Lỗi hạ tầng được chuẩn hóa và propagate, không biến thành thành công giả |
| A | F04 | Proposal hủy chỉ được tạo khi đơn và eligibility hợp lệ |
| A | F05 | Đơn explicit mới quyết định product context |
| A | F06 | Xử lý chính xác size/color và bốn trạng thái tồn kho |
| A | F08a | Bot/UI không tuyên bố đã thực hiện giao dịch chưa tồn tại |
| A | F11 | Catalog thiếu category không làm crash tìm kiếm |
| B | F07 | Admission HTTP, conv_lock và InferenceGate đúng vai trò |
| B | F09 | Telemetry thật xuyên gateway → Application → Ops importer |
| B | F12 | Giữ lịch sử DB vượt 6 lượt, prompt vẫn bounded |
| B | F13 | Shared ToolCache theo tenant/customer, invalidation epoch/CAS |
| B | SEC-01 | OAuth browser binding, atomic consume, cleanup/error headers |

**Ngoài scope:** PR C/product_policy_links, migration DDL mới, durable exchange F08b, transcript pagination Phase 5–6, ASGI, horizontal scaling, GraphRAG production và fine-tuning. Giữ SQLite Business v3 / PostgreSQL Business v4.

## 5. PR A/N08 — trạng thái nghiệm thu

Bản vá (code patch `c4e9976`) xử lý hai đường fail-open trong IdentityStore.resolve(): ApiError được re-raise, lỗi truy vấn safety được log nội bộ và trả 503 collision_unresolved. Local full suite xác nhận 479 tests: 429 PASS, 50 SKIP, 0 FAIL/ERROR (50 tests SKIP gồm 36 test_postgres, 11 test_rag_chat, 2 test_knowledge, 1 test_public_web do thiếu PostgreSQL local DSN/Waitress).

Role regression đã bao phủ toàn bộ staff, manager và viewer trong shared harness; SQLite có bằng chứng local pass (56/56 PR A). Bằng chứng CI:

- **Final tree:** CI run 37197602401, head_sha `eebe8ed` (eebe8edefd52abb1af86e9e8bdf2173413c25fd1), SUCCESS — host suite 479/479 PASS (0 SKIP); container suite 478 PASS / 1 SKIP (`test_colab_agent_notebook_sync` bỏ qua do không có `scripts/build_agent_notebook.py` trong image).
- **Code patch (lịch sử):** CI run 37196429628 trên `c4e9976`, SUCCESS với cùng test counts.

**PR A đủ điều kiện chuyển sang review / nghiệm thu; quyết định merge main là bước riêng; PR B chưa bắt đầu.** Xem chi tiết trigger, allowlist và stopping gates tại [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md).

### Các hợp đồng PR A phải giữ

- FAQ dùng fullmatch; có attachment, context động, lịch sử cũ hoặc dữ liệu lịch sử chưa xác minh thì bypass.
- Helper `has_turns(customer, cid)` là thay đổi dự kiến; phải đọc dữ liệu thật với đúng customer/conversation scope dưới lock.
- Ghi `eligibility_before_turn` một lần trước thực thi, dùng cho lookup và store; không tính lại bằng cách đếm cả turn vừa commit.
- Provenance counter thuộc PR A, tính cả read tools/tool-cache hits/human-support; thiếu trace không được hiểu là zero tool.
- Replay #1 read-only; Replay #2 và reload snapshot dưới conv_lock; cache-hit finish_turn cũng dưới lock.
- Request thua conv_lock không commit; retry có context/revision đổi trả 409 theo checkpoint contract.
- HTTP 429 và lỗi hạ tầng từ tool/worker phải đi ra đúng boundary, không trở thành “đã ghi nhận” hoặc “không tìm thấy” giả.
- F04/F05/F06 dựa trên kết quả tool và bản ghi đơn thực; giữ variant_not_found/stock_unknown/zero/positive riêng.
- F08a chỉ sửa hành vi/ngôn từ phù hợp backend có thật; không ngầm triển khai F08b.
- F11 tìm kiếm an toàn khi category thiếu/null.

**Điều kiện xong A:** Các scenario và regression liên quan đạt, không sửa frozen benchmark, có diff và log chứng minh hành vi mới. Không gọi A hoàn tất chỉ vì file test đã được tạo.

## 6. PR B: Triển khai trên kết quả A đã kiểm chứng

### 6.1. Admission, lock và gate

- Admission chung cho các provider đặt trước body/session/DB ở PublicWeb; max 6 chat được nhận trên một tiến trình Waitress 8 workers.
- Non-blocking acquire; token tồn tại suốt handler và release trong finally, kể cả lỗi/early return.
- conv_lock bảo vệ từng conversation; InferenceGate chỉ giữ permit trong lúc gọi model thực.
- Dọn agent_lock ở Application và session backends sau khi các cơ chế thay thế được kiểm tra.
- K=1/Q=5, queue timeout 10 giây; model/tool loops không giữ GPU permit khi chỉ chạy tool.

| Trường hợp kiểm thử | Kết quả bắt buộc |
| --- | --- |
| HTTP admission đã nhận 6 chat | Request tiếp theo nhận 429 server_busy, không vào DB/session |
| Cùng conversation đang xử lý | 429 model_busy, không tạo thêm turn commit |
| Model queue đủ 1 active + 5 waiters | Gate từ chối thêm bằng 429 model_busy |
| Queue chờ quá hạn | 429 queue_timeout, không rò slot |
| Handler/model/tool phát sinh lỗi | Lock/token/permit được trả đúng phạm vi |

Kiểm tra Retry-After: 5 trên HTTP response theo hợp đồng overload. Gate overflow có thể kiểm tra trực tiếp ở cấp gate; HTTP admission có thể chặn request trước khi nó tới gate.

**Load test headroom:** Chạy Waitress thật với 8 workers, 6 chat được giữ bằng barrier và mô phỏng DB/tools/model chậm. Ghi vị trí client, số mẫu, thời lượng, cấu hình và trạng thái DB/tài nguyên. Đo P99 health/session ≤50 ms trong điều kiện kế hoạch; không coi đó là bảo đảm dưới flood reject hoặc khóa DB toàn cục.

### 6.2. History và cache consistency

- Bỏ prune cứng agent_turns theo LIMIT 6; giữ transcript/feedback liên quan.
- Prompt vẫn dùng cửa sổ lịch sử bounded qua store.history; pagination chưa thuộc B.
- ToolCache/epoch được chia sẻ ở session layer theo tenant, không mỗi Application một cache riêng.
- Key có tenant/customer/tool/arguments; chụp epoch trước read, compare-and-set khi ghi dưới khóa.
- Mutation order status hoặc confirm cancellation bump epoch/invalidate sau commit thành công.
- Test hai tenant trùng customer ID, nhiều Application cùng tenant và stale in-flight write sau invalidation.
- Bảo đảm phạm vi một tiến trình; không tự suy ra cache nhất quán giữa nhiều pod.

### 6.3. OAuth

- TTL 600s; cookie transient đúng Path=/auth/google, Secure, HttpOnly, SameSite=Lax.
- Verify chữ ký/TTL → browser binding → atomic consume → exchange → issue session/cleanup.
- Hai callback đồng thời chỉ một request consume/exchange; callback sai browser không burn state hợp lệ.
- Test A login → B login → callback hủy muộn của A → callback B; cookie B không bị xóa bởi callback A.
- Test HTTP response Set-Cookie trên lỗi/cleanup, không chỉ kiểm tra trạng thái bên trong.
- Tuple response phải giữ headers; body/mime phù hợp PublicWeb serializer.
- Không đổi ma trận RBAC hoặc owner scope ngoài đặc tả đã chốt.

### 6.4. Telemetry

- Đo bằng clock monotonic; tách queue_wait_ms, provider_inference_ms và E2E latency.
- Tổng hợp N model calls thực tế; không mặc định mọi turn có một hoặc hai call.
- Cache-hit/no model có inference time 0.0; giá trị chưa đo hoặc provider thiếu usage giữ null/Unknown.
- Ops importer không dùng phép fallback làm 0.0 biến thành latency tổng.
- Test timeout, provider error, cache hit và nhiều vòng tool/model; kiểm tra cả producer lẫn importer.

## 7. Lệnh kiểm tra và bằng chứng

Các lệnh dưới đây phục vụ lượt implementation; **chưa chạy toàn bộ trong đợt review plan này**. Chạy với cấu hình test phù hợp repository, DB kiểm thử riêng và ghi rõ backend.

```powershell
python -B -X utf8 scripts/check_docs_contract.py
python -B -X utf8 scripts/check_eval_dataset.py
python -B -X utf8 scripts/build_agent_notebook.py --check
python -B -X utf8 scripts/check_deployment_contract.py
python -B -m unittest discover -s tests -v
git diff --check
```

Sau khi tạo suite A:

```powershell
python -B -m unittest discover -s tests -p "test_pr_a_correctness.py" -v
```

Theo [CI hiện có](../.github/workflows/ci.yml), cần kiểm tra cả môi trường và integration backend được repository hỗ trợ. Nếu test PostgreSQL skip do thiếu RETAILOPS_TEST_DATABASE_URL, ghi rõ **SKIPPED / INTEGRATION PENDING**; không quy thành PASS PostgreSQL.

Mỗi PR lưu:

| Trường evidence | Nội dung |
| --- | --- |
| Baseline và candidate | Commit SHA và snapshot plan áp dụng |
| Phạm vi | Finding/acceptance nào được kiểm chứng |
| Môi trường | Python, backend, worker/gate settings; phiên bản provider/model nếu dùng |
| Thực thi | Lệnh, thời điểm, run ID hoặc đường dẫn log |
| Kết quả | Passed/failed/skipped, lý do skip; không chỉ số tổng |
| Race/concurrency | Cách điều khiển barrier, mã lỗi/header, trạng thái DB/cache sau race |
| Telemetry/benchmark | Cấu hình, raw results, metric definition, trạng thái cold/warm cache |

**353** là kết quả lịch sử được tài liệu repo báo cáo; **415+** là target dự kiến. Không dùng hai số này làm bằng chứng candidate đã PASS, và không viết test chỉ để đạt số lượng.

## 8. Điều kiện nghiệm thu implementation và chuyển Phase 4

Chỉ ghi IMPLEMENTATION_VERIFIED khi:

- 13 hạng mục có mapping tới thay đổi, test và kết quả thực thi.
- Suite A và acceptance B bắt buộc đạt; regression/CI không có lỗi chưa xử lý trong phạm vi thay đổi.
- Có bằng chứng SQLite và PostgreSQL phù hợp với backend được tuyên bố hỗ trợ; những phần chưa chạy được ghi pending, không nâng nhãn.
- Không còn lỗi truthfulness, race/cache isolation hoặc OAuth theo các ca đã đặc tả.
- Docs/contracts/notebook đồng bộ; frozen hashes không đổi.
- Changelog/evidence ghi rõ hạn chế và deferred scope.

Sau đó chuyển Phase 4:

1. Đánh giá frozen 250 ca theo [Evaluation Framework](PLAN_DEEPSEEK_EVAL_FRAMEWORK.md).
2. Chạy load matrix concurrency 1/2/4/8/16; đo latency/throughput/429/fairness theo thiết kế.
3. Cố định model/provider/config, tách cold/warm cache và lưu raw results trước khi viết bảng số liệu luận văn.
4. Mọi dataset candidate mới đi ra tệp khác; không sửa master hoặc benchmark mirror để tăng điểm.

Hash LF-normalized của cả hai bộ frozen:
`36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`.

## 9. Sau khi hoàn thành A/B và các giai đoạn tiếp theo

- Nếu A/B đã có evidence nhưng benchmark chưa chạy, báo rõ implementation đã kiểm chứng, scientific evaluation còn pending.
- Khi Phase 4 hoàn thành, tổng hợp kết quả thực nghiệm và giới hạn; chuyển Phase 5 Omnichannel/demo theo roadmap.
- Phase 6, PR C và F08b cần scope/ADR riêng trước khi thực hiện; không tự thêm vào PR A/B.
- Khi kết thúc một giai đoạn, cập nhật trạng thái bằng commit/run và kết quả có thật, không thay nhãn hàng loạt dựa vào lời báo cáo.
- File này là bàn giao tại mốc kết thúc sửa plan. Báo cáo hoàn thành implementation sau này phải được bổ sung bằng bằng chứng của lần triển khai thực.

## 10. Việc nên làm ngay

1. Viewer regression đã có trong shared harness; SQLite local test PASS.
2. Full test suite và 4 script gates đã hoàn tất và PASS 100%.
3. CI run 37197602401 trên final tree `eebe8ed` SUCCESS (host 479/479 PASS, container 478 PASS / 1 SKIP); CI run 37196429628 trên code patch `c4e9976` là bằng chứng lịch sử.
4. Bước tiếp theo: review / nghiệm thu PR A; quyết định merge main là bước riêng.
5. Chỉ sau khi PR A được chấp thuận/merge mới bắt đầu PR B.

## 11. Sơ đồ Mermaid tổng thể: request, cache, concurrency và OAuth

### 11.1. Tình hình dự án hiện tại

Trạng thái ngày 04/10/2026 theo N08_STOPPING_CONDITIONS.md: fix resolver và CI trên SHA cuối đã hoàn tất; bước tiếp theo là review / nghiệm thu PR A. CI cũ trên fe25f67 là lịch sử.

```mermaid
flowchart LR
    N08["P1.2 PASS<br/>P1.1 resolver fail-open (03/10)"] --> Fix["Fix swallowed ApiError + lookup failure<br/>+ SQLite/PG regression<br/>code patch c4e9976"]
    Fix --> SHA["CI 37197602401 trên final tree eebe8ed<br/>SUCCESS"]
    SHA --> Review["Code review / nghiệm thu PR A"]
    Review --> Merge["Merge PR A (quyết định riêng)"]
    Merge --> PRB["PR B: concurrency, history, cache, OAuth, telemetry"]
    PRB --> Verify["Implementation verification"]
    Verify --> Phase4["Phase 4: frozen benchmark + load matrix"]
    Limit["Known limitations: manual reconciliation; journal/recovery; chưa deploy candidate"] -. "được ghi nhận khi merge" .-> Merge
    classDef done fill:#d9ead3,stroke:#38761d,color:#222
    classDef pending fill:#fce4d6,stroke:#c65911,color:#222
    classDef next fill:#d9eaf7,stroke:#3d85c6,color:#222
    class N08,Fix,SHA done
    class Review,Merge pending
    class PRB,Verify,Phase4 next
```

### 11.2. Kiến trúc đích sau khi tích hợp PR A và PR B

Màu xanh lá là phần PR A/N08 đã triển khai theo status report; xanh dương là công việc PR B chưa bắt đầu; màu cam là điểm ghép giữa hai phần. Màu đỏ biểu thị fail-closed hoặc lỗi HTTP. Đây là sơ đồ kiến trúc theo kế hoạch, không phải bằng chứng rằng các hạng mục PR B đang chạy.



~~~mermaid
flowchart LR
    Client["Client / Browser"] --> HTTP["HTTP request"]
    HTTP --> Admission["Tier 1 — HTTP Admission<br/>max 6 accepted chat / Waitress 8"]
    Admission -->|"full: 429 server_busy<br/>Retry-After: 5"| EAdmission["Reject early<br/>no DB / session"]
    Admission -->|"admitted"| Session["Session resolve<br/>customer / tenant binding"]
    Session --> ConvLock["Tier 2 — conv_lock<br/>per conversation, non-blocking"]
    ConvLock -->|"busy: 429 model_busy"| EConv["Reject turn<br/>no commit"]
    ConvLock --> Replay["Replay #2 under lock"]
    Replay -->|"hit"| Response["HTTP response"]
    Replay -->|"miss"| Snapshot["Reload snapshot + verify history<br/>under conv_lock"]
    Snapshot --> Eligibility{"Fail-closed cache eligibility"}
    Eligibility -->|"false: context / history unknown / attachment / non-FAQ"| Workflow["Workflow checkpoint"]
    Eligibility -->|"true: static FAQ + empty history verified"| Semantic["Semantic Cache<br/>lookup under conv_lock<br/>epoch/CAS: GAP in plans"]
    Semantic -->|"hit"| SemanticCommit["finish_turn under conv_lock"]
    SemanticCommit --> Response
    Semantic -->|"miss"| Workflow
    Workflow --> Gate["Tier 3 — InferenceGate<br/>K=1, Q=5"]
    Gate -->|"queue full: 429 model_busy<br/>Retry-After: 5"| EGate["Reject / release permit"]
    Gate -->|"wait > 10s: 429 queue_timeout<br/>Retry-After: 5"| ETimeout["Timeout / release permit"]
    Gate -->|"permit"| Model["Model call<br/>provider_inference_ms"]
    Model --> ToolExec["Tool execution<br/>zero GPU permit while tools run"]
    ToolExec --> ToolCache["ToolCache<br/>tenant + customer scoped"]
    ToolCache -->|"hit"| ToolResult["Tool result"]
    ToolCache -->|"miss"| ToolCall["Read tool / DB call"]
    ToolCall --> ToolResult
    ToolResult -->|"next model call, if any"| Gate
    ToolResult --> Provenance{"Response provenance"}
    Provenance -->|"unknown trace / tool / RAG / source / dynamic context"| NoStore["Fail-closed<br/>do not store Semantic Cache"]
    Provenance -->|"verified zero tools, zero RAG, zero sources"| Finish["finish_turn + telemetry"]
    NoStore --> Finish
    Finish --> Response

    Manager["Manager mutation route<br/>update-status / cancellation confirm"] --> Epoch["Increment cache_epoch<br/>after DB commit"]
    Epoch --> ToolCache
    Epoch -. "stale in-flight write discarded by CAS" .-> NoStore

    subgraph OAuth["OAuth Login CSRF protection — SEC-01 / PR B"]
        OAuthLogin["/auth/google/login<br/>nonce + transient cookie"] --> Verify["Verify HMAC + TTL 600s"]
        Verify -->|"invalid / expired: 403 invalid_oauth_state"| OVerifyErr["Fail closed"]
        Verify --> Binding["Verify browser cookie binding"]
        Binding -->|"missing / mismatch: 403 invalid_oauth_state"| OBindingErr["Fail closed"]
        Binding --> Consume["Atomic single-use consume"]
        Consume -->|"replay / race loser: 403 invalid_oauth_state"| OConsumeErr["Fail closed"]
        Consume --> Exchange["Exchange code with Google"]
        Exchange -->|"upstream failure: 502 oauth_exchange_failed"| OExchangeErr["Cleanup Set-Cookie"]
        Exchange --> Issue["Issue session + cleanup transient cookie"]
        Issue --> Session
    end

    classDef prA fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef prB fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef cross fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#e65100;
    classDef cache fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c;
    classDef fail fill:#fff8e1,stroke:#f9a825,stroke-width:2px,color:#6d4c00;
    classDef error fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c;
    classDef oauth fill:#e0f7fa,stroke:#00838f,stroke-width:2px,color:#006064;

    class HTTP,Admission,EAdmission,Gate,EGate,ETimeout,ToolCache,ToolCall,Manager,Epoch prB;
    class ConvLock,Session,Model,Response,Finish cross;
    class Replay,Snapshot,Eligibility,Workflow,Provenance,SemanticCommit,NoStore prA;
    class Semantic,ToolResult cache;
    class OAuthLogin,Verify,Binding,Consume,Exchange,Issue oauth;
    class OVerifyErr,OBindingErr,OConsumeErr,OExchangeErr fail;
    class EConv error;
~~~

### 11.3. Đối chiếu với từng plan

| Plan | Phần khớp trong sơ đồ | Kết quả đối chiếu |
| --- | --- | --- |
| [PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md](PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md) | Replay #1/#2, conv_lock, snapshot revalidation, static-FAQ allowlist, history fail-closed, Semantic Cache lookup/store, provenance guard, workflow và F03 propagation. | **Khớp.** PR A mô tả cache-hit commit dưới conv_lock, bypass 100% khi không đủ điều kiện và không lưu khi provenance thiếu. |
| [PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md) | Admission trước session/DB, max 6, conv_lock, InferenceGate K=1/Q=5, server_busy, model_busy, queue_timeout, release trong finally, cache miss vào workflow. | **Khớp.** SLO P99 chỉ là mục tiêu dưới tải kiểm soát; sơ đồ không diễn giải 8−6 thành pool hai worker riêng. |
| [PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md) | Ba tầng concurrency, ToolCache tenant/customer scope, cache_epoch và CAS discard, OAuth verify → binding → atomic consume → exchange → session, F12 history. | **Khớp với một giới hạn cần ghi chú:** epoch/CAS được đặc tả cho **ToolCache**, không phải Semantic Cache. |
| [PLAN_RBAC_GOOGLE_AUTH.md](PLAN_RBAC_GOOGLE_AUTH.md) | Cookie transient, HMAC/TTL, browser binding, atomic consume, exchange, issue session/cleanup, RBAC session tiếp nhận sau OAuth. | **Khớp ở mức mục tiêu SEC-01.** Các test OAuth vẫn pending trong Module 2.5; trạng thái “IMPLEMENTED & ACTIVE” của tài liệu RBAC là trạng thái core OAuth/UI, không thay thế hardening SEC-01. |

### 11.4. Mâu thuẫn và khoảng trống được phát hiện

1. **Semantic Cache epoch/CAS chưa có đặc tả.** Các plan chỉ quy định cache_epoch + compare-and-set cho **ToolCache** trong F13. Semantic Cache chỉ có điều kiện fail-closed, lookup/store dưới conv_lock và provenance guard. Vì vậy node Semantic Cache được đánh dấu epoch/CAS: GAP in plans; không được triển khai epoch/CAS cho Semantic Cache chỉ dựa trên sơ đồ này.
2. **OAuth TTL giữa plan và mã nguồn hiện tại chưa đồng nhất.** RBAC/Sprint yêu cầu TTL 600 giây, còn retailops/http/auth_google.py tại baseline hiện có STATE_TTL_SECONDS = 900. Đây là khoảng cách plan → code phải xử lý và kiểm thử trong PR B; sơ đồ dùng 600 giây theo hợp đồng plan.
3. **Trạng thái OAuth khác cấp độ.** RBAC ghi core OAuth/UI là IMPLEMENTED & ACTIVE, trong khi Module 2.5 và Sprint ghi SEC-01 là PENDING TEST. Đây là khác biệt giữa core feature và hardening contract; không được dùng trạng thái core để đánh dấu SEC-01 đã xác minh.
4. **Ranh giới agent_lock được chia theo giai đoạn.** PR A giữ kiểm tra tạm thời để bảo vệ flow cache/turn; PR B mới dọn hoàn toàn agent_lock và thay bằng admission + conv_lock + InferenceGate. Sơ đồ gán conv_lock cho vùng giao nhau và admission/gate cho PR B để phản ánh thứ tự này.
5. **Error 429 chỉ áp dụng cho concurrency gates.** Fail-closed của Semantic Cache, provenance hoặc OAuth trả về bypass/không lưu hoặc lỗi 403/502; chúng không phải 429. Các mã 429 trong sơ đồ chỉ thuộc Tier 1 admission, Tier 2 conversation lock và Tier 3 model gate.
6. **OAuth cleanup trên lỗi cần response headers thật.** Các plan yêu cầu tuple response có Set-Cookie; khi triển khai phải kiểm tra HTTP response thực tế, không chỉ trạng thái nội bộ. Sơ đồ thể hiện cleanup ở nhánh exchange lỗi và sau khi cấp session.
7. **Ghi chú lịch sử:** Tại review ngày 03/10, P1.1 session-safety còn BLOCKED do resolver fail-open. Patch ngày 04/10 đã xử lý nhánh này locally, bổ sung viewer regression; CI run 37196429628 trên code patch `c4e9976` (lịch sử) và CI run 37197602401 trên final tree `eebe8ed` đều SUCCESS trên PostgreSQL container. PR A đủ điều kiện chuyển sang review / nghiệm thu; PR B chưa bắt đầu. Xem [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md).
