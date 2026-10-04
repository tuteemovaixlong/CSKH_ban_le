# Review GPT 6.1 Sol — Module 2.5 PR A

Ngày review: **2026-10-02**. Implementation được kiểm tra: **`7a5229e`**, nhánh **`feature/module-2.5-pr-a`**, so với baseline **`376322f`**.

> **Prompt cô đọng cho Gemini:** Đọc review này, chỉ sửa các lỗi G01–G10 của PR A và test tương ứng; chưa làm PR B/deploy. Ưu tiên CI, retry/checkpoint trước cache, propagate lỗi provider/tool, hủy đúng đơn, provenance fail-closed và size/color chính xác. Giữ nguyên frozen dataset, review Astra, handoff và file review này. Test phải tái hiện lỗi trước sửa; chạy full unittest và các CI gates, rebuild notebook cuối cùng; báo kết quả PASS/FAIL/SKIP cùng commit thực tế, không suy diễn hoàn tất từ 30 test xanh.

**Kết luận: PR A CHƯA ĐẠT NGHIỆM THU — cần sửa trước khi chuyển PR B hoặc deploy.** Có tiến bộ rõ ở cache guards, lock và wording, nhưng nhiều hợp đồng correctness chưa chạy đúng. Kết quả độc lập: **30 test mới PASS; toàn bộ suite 445 test có 2 FAIL, 1 ERROR, 43 SKIP; notebook sync FAIL**.

## 1. Phạm vi và bằng chứng

- Đã đọc toàn bộ attachment `3e97045b-1064-4abe-80d7-5183c08b558d/Pasted text.txt`, diff implementation, code thực tế, plan PR A và các hợp đồng trong execution handoff.
- Review source tại `7a5229e`; trong lúc kiểm tra có tác vụ khác thêm commit **`7d0df0d`**, chỉ bổ sung `docs/PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md`. Source/test của PR A không thay đổi, nên kết quả kiểm tra vẫn áp dụng cho implementation này. Tài liệu mới ấy không thuộc review PR A này.
- Đã chạy test offline với stub/mock model và fixture DB tạm; bổ sung tái hiện bằng bộ nhớ/DB tạm rồi dọn fixture. Không gọi model thật, API cloud, DB nghiệp vụ, deploy hoặc chỉnh code/test.
- Chỉ tạo file review này. Không sửa `review gpt 6 astra.md`, `PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md`, `SYSTEM_REVIEW_FOR_LLM.md` hoặc plan khác; không commit/push.
- Các mã G01–G10 là finding của lần review implementation này; không dùng lại mã Rxx của các vòng review tài liệu.

## 2. Kết quả kiểm tra độc lập

| Kiểm tra | Kết quả | Ý nghĩa |
|---|---|---|
| `python -B -X utf8 -m unittest discover -s tests -p test_pr_a_correctness.py` | **30/30 PASS** | Một số test không thực sự kích hoạt hợp đồng cần kiểm tra; xem G10. |
| `python -B -X utf8 -m unittest discover -s tests` | **445 tổng; 399 PASS, 2 FAIL, 1 ERROR, 43 SKIP**, exit 1 | Regression chưa đạt. Thời gian khoảng 50,9 giây. |
| `python -B -X utf8 scripts/build_agent_notebook.py --check` | **FAIL**, exit 1 | `Notebook is stale: run python scripts/build_agent_notebook.py`. |
| `python -B -X utf8 scripts/check_docs_contract.py` | **PASS 4/4** | Dataset/link/AST/docs gates; không kiểm chứng behavior runtime. |
| `python -B -X utf8 scripts/check_deployment_contract.py` | **DEPLOYMENT_CONTRACT_OK** | Static deployment contract; không chứng minh deploy hoạt động. |
| `python -B -X utf8 scripts/check_eval_dataset.py` | **EVAL_DATASET_OK**, 30 baseline cases | Không phải chạy model thật trên frozen benchmark 250 ca. |
| `node --check web/app.js` | **PASS** | JavaScript syntax; không thay thế browser behavior test. |
| `git diff --check` | **PASS** | Không có lỗi whitespace trong tracked diff tại thời điểm kiểm tra. |

**Ba test đỏ trong full discovery:**

1. `test_audit_remediation.TestAuditRemediation.test_colab_agent_notebook_sync`: bundle không khớp source hiện hành.
2. `test_order_tool_recovery.OrderToolRecoveryTests.test_t18_order_id_typo_handling_and_normalization`: expected proposal `O-819127`, actual `None`.
3. `test_schema_migration.MigrationTests.test_live_repository_does_not_recreate_a_deleted_database`: test chờ `sqlite3.OperationalError`, source đã đổi sang `ApiError(503, database_unavailable)`.

**43 SKIP:** PostgreSQL 29, knowledge/pgvector 2, RAG integration 11 và Waitress HTTP 1. Máy review không có Waitress, không cấu hình disposable PostgreSQL DSN. Chưa xác nhận live PostgreSQL/pgvector, tải HTTP/GPU hoặc chất lượng model thật.

Con số **114** trong báo cáo Gemini khớp số test của chín suite được liệt kê. Tuy nhiên, PASS ở lần chạy trước không chứng minh trạng thái commit cuối: riêng notebook-sync trong nhóm 114 đã FAIL ở checkout hiện tại. Không thể gọi kết quả đó là “kiểm thử toàn diện 100% PASS”.

## 3. Findings cần sửa

### G01 — P1: Notebook stale và regression contracts chưa được cập nhật

**Vị trí:** `notebooks/colab_agent.ipynb:54`; `scripts/build_agent_notebook.py:52,448`; `.github/workflows/ci.yml:25,80,93`; `tests/test_schema_migration.py:117`; `tests/test_order_tool_recovery.py:531`.

**Bằng chứng:** `--check` FAIL; giải mã bundle trong bộ nhớ thấy 132 embedded files, đúng một file lệch source: `tests/test_cache_engineering.py`. Notebook được build trước lần sửa test cache cuối. Full discovery còn hai regression contracts không tương thích với implementation mới.

**Cách xử lý:**

- Sau khi sửa toàn bộ source/test, rebuild notebook và chạy `--check`; không bỏ gate hoặc bỏ test khỏi bundle.
- Migration test phải chờ `ApiError` với **status 503, code `database_unavailable`**, đồng thời giữ assertion DB bị mất **không được tái tạo**. Việc normalize lỗi là đúng hướng; test contract cần cập nhật.
- T18 đang mock `{'eligible': True, 'order_id': ...}` thiếu `order.id`, trong khi guard mới yêu cầu `result['order']['id']`. Sửa fixture theo contract thật và giữ assertion normalization `O0819127 → O-819127`; **không nới guard để tin kết quả tool thiếu bằng chứng**.

**Đóng khi:** full discovery không còn ba test đỏ, notebook sync PASS và CI integration bắt buộc đạt. Local SKIP phải được báo riêng.

### G02 — P1: Cache hit bỏ qua xung đột của request dang dở; retry không cache phát hiện revision quá muộn

**Vị trí:** `retailops/business/application.py:153–202`; `retailops/workflow/checkpoints.py:101–110`; `retailops/business/store.py:705–715`. Contract: `PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md:408`.

`store.replay()` chỉ biết turn đã commit. Cache hit được commit ở Application **trước** khi `workflow()` kiểm fingerprint của graph run dang dở. Nhánh resume cũng lấy lại seed cũ mà chưa so revision/context với snapshot mới.

**Đã tái hiện bằng Application và DB tạm:**

1. Gửi FAQ với request ID cố định; stub model lỗi sau khi tạo graph run. DB còn **1 graph run, 3 checkpoints**, chưa có turn thành công.
2. Tăng `conversation.revision`, giữ context trống; seed FAQ cache; retry cùng ID.
3. Actual: **thành công `source=semantic_cache`, 0 model call, turn được commit**. Expected: **409 `conversation_changed`, không commit**.
4. Giữ ID đó nhưng đổi nội dung sang FAQ khác có cache: actual vẫn commit; expected **409 `request_conflict`**.
5. Với cache trống, revision mismatch có trả 409 nhưng **sau 1 model call**, trong khi plan yêu cầu từ chối trước model/tool execution.

**Cách xử lý:** kiểm tra identity/fingerprint và seed revision/context của run tồn tại dưới `conv_lock`, **trước cache commit và trước model/tool**. Không âm thầm thay seed/checkpoint. Giữ nguyên replay nhanh cho turn đã commit.

**Test bắt buộc:** tạo run/checkpoint thực bằng interrupted turn; retry đổi revision, đổi context, đổi digest; thử cả hit/miss. Assert status/code, không thêm model call và không commit. Thêm unchanged retry và completed replay để tránh phá idempotency.

### G03 — P1: F03 vẫn biến lỗi provider thành thành công giả và làm mất HTTP 429

**Vị trí:** `retailops/workflow/subagents/dispute_agent.py:343–352`; `retailops_providers.py:262–267`; `retailops/workflow/subagents/read_worker.py:163–167,230–246`; `retailops/business/application.py:344–347`.

Guard mới chỉ re-raise `ApiError`. Provider thực tế phát `AgentError`, nên broad catch trong dispute vẫn nuốt lỗi. Application cũng chuyển mọi `AgentError` thành 503; read worker chuyển tool 429 thành dict rồi mất status.

**Đã tái hiện:**

| Input lỗi | Actual | Expected theo F03 |
|---|---|---|
| Dispute gateway ném `AgentError(api_rate_limited, http_status=429)` | Application thành công, nói **“shop đã ghi nhận…”**, `model_used=False`, `model_calls=0`, **commit turn** | 429; không acknowledgement giả, không commit turn thành công. |
| Dispute gateway ném `AgentError(api_unavailable, http_status=503)` | Cùng thông báo thành công giả, commit turn | 503; không commit turn thành công. |
| Read worker: `get_order` ném `ApiError(429, server_busy)` | **503 `tool_response_failed`** | Giữ 429 ra HTTP boundary. |
| Read/generic gateway ném `AgentError(api_rate_limited, http_status=429)` | **503 `api_rate_limited`** | Giữ 429 ra HTTP boundary. |

Read worker còn có fallback sau lỗi model khi đã lấy được records; cần phân loại lỗi hạ tầng/overload trước fallback theo F03, tránh chỉ sửa dispute.

**Cách xử lý:** thống nhất normalization/propagation cho `ApiError`, `AgentError` provider và timeout qua worker → Application → HTTP. Không dùng broad fallback để ghi nhận nghiệp vụ chưa được thực hiện. Bảo toàn status phù hợp và metadata đã sanitize.

**Test bắt buộc:** multi-agent mặc định + standard; read/dispute; tool 429/503, provider 429/503/timeout, lỗi sau một tool thành công. Assert lỗi ra client, không commit thành công, lock được release. Test hiện tại ép standard ở `test_pr_a_correctness.py:318` và inject `ApiError` ở `:338`, nên chưa bao phủ các đường lỗi này.

### G04 — P2: Semantic Cache trả địa chỉ cho câu hỏi hotline

**Vị trí:** `retailops/business/cache.py:24–30,143–155`; `retailops/business/application.py:158–159`.

Allowlist xác định query có thể cache, nhưng không xác định hai query có cùng loại câu trả lời. Matching vẫn dùng cosine trên mọi entry, threshold 0,65.

**Tái hiện trong bộ nhớ:**

```python
cache = SemanticCache(min_similarity=0.65)
cache.store('địa chỉ của cửa hàng như thế nào', 'Địa chỉ cửa hàng: 123 Nguyễn Trãi')
hit = cache.lookup('hotline của cửa hàng như thế nào')
```

Cả hai query qua `is_static_faq_query()`. Actual: semantic hit **0,7736**, answer là **địa chỉ**, không phải hotline.

**Cách xử lý:** phân vùng cache theo canonical FAQ intent/topic hoặc dùng key intent chính xác cho miền FAQ nhỏ. Chỉ so semantic similarity trong cùng loại thông tin; tăng threshold đơn thuần không chứng minh an toàn.

**Test bắt buộc:** paraphrase cùng topic phải hit; address ↔ hotline ↔ opening/closing hours và greeting phải có negative tests, không lấy nhầm factual answer. Đây là lỗi còn tồn tại trong contract đã thu hẹp cache, dù thuật toán similarity không mới trong PR này.

### G05 — P2: Missing provenance bị hiểu là zero tool; trace lỗi có thể gây 500 sau commit

**Vị trí:** `retailops/business/application.py:314–340`, đặc biệt `:316–318`; plan `PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md:255–271`.

`tools` thiếu mặc định `[]`, `tool_count` thiếu mặc định `len(tools)`. Counter local là bằng chứng có ích cho execution hiện tại, nhưng không chứng minh provenance đầy đủ của output/resume; code chưa có completeness marker hay explicit resume exclusion.

**Đã tái hiện tại workflow output boundary:** dùng FAQ hợp lệ, return trace có `answer_source/model_calls/model_responses` nhưng thiếu cả `tools` lẫn `tool_count`: **turn được lưu và cache có 1 entry**. Contract yêu cầu unverified provenance phải từ chối store.

Trả `tool_count=None` hoặc `tools=None`: `max()`/`len()` lỗi **sau `finish_turn()`**; client nhận **500 `internal_error` nhưng turn đã commit**. Đây là kiểm tra malformed output bằng mock tại boundary, không phải khẳng định provider hiện tại luôn phát dữ liệu null.

**Cách xử lý:** quyết định cache eligibility bằng provenance được xác nhận đầy đủ, kiểm type trước khi commit; thiếu/sai provenance thì **không cache** nhưng không làm chat hợp lệ thất bại. Checkpoint resume/human handoff phải bị loại theo plan. Nếu không xác minh được lịch sử, không fallback `has_turns` thành `False` ở `:153`.

**Test bắt buộc:** FAQ hợp lệ với read tool thật, tool-cache hit, missing/null trace fields, checkpoint resume, human-support. Assert no cache, hành vi HTTP/commit nhất quán; test phải thất bại nếu xóa provenance guard.

### G06 — P1: F04 có thể đề xuất hủy sai đơn; refusal bị ghi đè thành câu trả lời rỗng

**Vị trí:** `retailops/workflow/subagents/dispute_agent.py:83–107,297,334–341`.

Guard so `result.order.id` với **`chosen_oid` do model chọn**, chưa so với **`extracted_oid` trong yêu cầu khách**. Nhánh heuristic có thể che lỗi với “hủy đơn”, nhưng không bao phủ các cách diễn đạt mà supervisor đã route tới dispute.

**Tái hiện với tool nghiệp vụ thật và gateway tool-only:**

- Input **“Hủy hàng O-102 giúp tôi”**; model gọi `prepare_cancellation(O-101)`. O-101 đủ điều kiện nên actual tạo **proposal hủy O-101**, mặc dù khách chỉ định O-102. Đây là proposal sai, chưa phải tự động hủy DB vì vẫn có confirmation.
- Cùng input; model gọi đúng O-102 đã delivered. Guard tạo refusal, nhưng `else` cuối ghi đè bằng `message.content=''`: actual **message rỗng**, proposal None; supervisor + graph cũng tái hiện được.

**Cách xử lý:** model argument, explicit/focused order đã xác minh và tool result phải trùng cùng một ID trước proposal; mismatch phải từ chối/clarify. Giữ refusal từ tool độc lập với keyword heuristic và bảo đảm final reply không rỗng.

**Test bắt buộc:** delivered/pending, tool-only responses, synonyms “hủy hàng”, model chọn đơn khác owned bởi cùng customer, result ID mismatch, mã đơn cần normalization. Không kiểm chỉ ba tình huống “hủy đơn” với MockAgent không gọi tool.

### G07 — P2: F05 còn dùng sản phẩm của focus cũ khi đơn mới không resolve được product

**Vị trí:** `retailops/workflow/subagents/dispute_agent.py:142–150,212–220`.

Sau `get_order` cho mã mới, nếu `product_id/items` không có, code vẫn fallback sang bound product cũ.

**Đã tái hiện:** focus `O-101/P-101`; O-102 thuộc customer nhưng `product_id=NULL`, name/variant không map được catalog. Input “Đơn O-102 bị rách” gọi **`get_order(O-102)` rồi `get_product(P-101)`**, tạo exchange option O-102 dựa trên bảo hành P-101.

**Cách xử lý:** chỉ reuse bound product khi bound order trùng chosen order và mapping đã xác minh; thiếu mapping của đơn mới thì clarify/abstain. Không dùng sản phẩm của đơn khác để hoàn thiện câu trả lời.

**Test bắt buộc:** spy đúng argument `get_product`, hai sản phẩm có warranty khác nhau, thêm new-order-without-product. Assertion “90 ngày” trong test hiện tại không đủ vì cả P-101/P-102 đều có 90 ngày.

### G08 — P2: F06 làm mất màu gốc, cộng tồn nhiều màu và cắt ngắn màu nhiều từ

**Vị trí:** `retailops/workflow/subagents/dispute_agent.py:185,223–243,254–284`; `retailops/business/store.py:449–450,477–482`.

**Hai lỗi đã tái hiện bằng fixture nghiệp vụ:**

1. Context `O-301/P-103`, input “Đơn O-301 đổi size L”: code skip `get_order`, `order_data` trống, tự chọn **“Tiêu chuẩn”**. Storage hiểu màu đó là không lọc màu và cộng tồn. Actual đề xuất **stock 20 trên nhiều màu**, trong khi màu gốc **Trắng stock 10**. Khi Trắng/L=0 nhưng Xanh Nhạt/L=10, vẫn báo còn hàng và tạo phương án; cùng input ở phiên không focus thì đúng là hết Trắng/L.
2. “Đơn O-301 đổi size L màu xanh nhạt” gửi tool color **`Xanh`**, báo không có variant dù **Xanh Nhạt/L có 10**. O-303 màu **Xanh Navy/L có 18** cũng bị cắt thành `Xanh` và từ chối sai.

Parsing variant gốc chỉ nhận `·` hoặc `/`; dữ liệu dùng dấu phân cách khác cũng không được resolve và rơi về “Tiêu chuẩn”. Regex còn lấy màu đầu tiên trong toàn câu, cần phân biệt màu cũ với màu muốn đổi.

**Cách xử lý:** lấy/preserve variant order thật dù đã focus; resolve size/color theo catalog đầy đủ; chưa rõ thì hỏi lại. Không dùng màu “Tiêu chuẩn” để suy diễn variant có hàng. Giữ bốn trạng thái missing/unknown/zero/positive độc lập ở worker response và proposal.

Nhánh unknown stock `:267–268` còn hứa “Em sẽ ghi nhận để CSKH kiểm tra … phản hồi lại” mà không có acknowledgement handoff. Giữ wording phù hợp backend hiện có; không triển khai ngầm F08b.

**Test bắt buộc:** focused/unfocused equivalence, nguyên màu gốc hết hàng nhưng màu khác còn, xanh nhạt/navy, câu chứa màu cũ và mới, thiếu size/color, variant unknown/null/zero/positive qua **dispute worker**, không dừng ở `BoundTools.check_inventory`.

### G09 — P2: F11 xử lý category null nhưng search vẫn crash khi aliases null

**Vị trí:** `retailops_tools.py:52`; `retailops/http/routes.py:307`; `retailops/business/store.py:235,276`.

Manager input/storage chấp nhận `aliases=null`; `_row_to_product()` decode JSON `null` thành None. Comprehension mới vẫn iterates `p.get('aliases', [])`, nên default không áp dụng khi key có value None.

**Đã tái hiện bằng product lưu trong DB tạm:** `P-999`, category None, aliases None; `search_products(query='polo')` ném **`TypeError: 'NoneType' object is not iterable`**. Một product lỗi làm cả catalog search không hoàn tất.

**Cách xử lý:** normalize null aliases thành list rỗng hoặc validate type tại input, đồng thời đọc an toàn dữ liệu đã có. Giữ xử lý category null đã sửa. Đây là null-data robustness liền kề F11, không đề nghị mở rộng kiến trúc.

**Test bắt buộc:** aliases missing/null/list, category missing/null; trường không đúng kiểu phải reject/normalize rõ ràng. Dùng product qua store/input contract, không chỉ dict fixture đã điền aliases sẵn.

### G10 — P2: Nhiều test xanh không chứng minh hợp đồng ghi trong tên/docstring

**Vị trí:** `tests/test_pr_a_correctness.py`; `tests/test_cache_engineering.py:27,162`.

| Test hiện tại | Khoảng trống | Test cần thay/bổ sung |
|---|---|---|
| F01 provenance `:188–201` | MockAgent không phát tool call; query đơn hàng vốn bị predicate chặn. | FAQ vốn eligible, execute read tool thật; assert no store. |
| F01 missing trace `:203–212` | Không gọi chat; chỉ test `has_prior_turns=True`; patch has_turns không được dùng. | Workflow output thiếu/unverified trace đi tới storage guard. |
| F02 retry `:218–230` | Không interrupted run, không retry; **assert success** thay vì 409. | Run persisted + retry thay revision/context/digest; zero new calls/no commit. |
| F02 cache race `:262–275` | Không seed cache; chỉ là ordinary busy-lock test. | Seed hit, barrier có kiểm soát, hai request; đúng một commit. |
| F02 snapshot `:295–304` | Focus đổi trước snapshot đầu, không giữa preflight và lock. | Hook/barrier giữa hai snapshot reads; fresh context giữ nguyên, bypass stale hit. |
| F03 `:310–344` | Ép standard; inject ApiError thay provider AgentError. | Default multi-agent + real provider exception type + HTTP boundary. |
| F05 `:408–424` | Chỉ nhìn “90 ngày”; hai product đều 90. | Spy đúng get_order/get_product; warranties khác nhau và missing mapping. |
| F06 `:430–470` | Chủ yếu gọi inventory trực tiếp; clarification thiếu size nên không bắt missing color. | Worker exact arguments, reply/proposal, focused/multiword/missing color. |
| F08a `:520–532` | C-001 hỏi O-303 của **C-004**, không có valid exchange; chỉ đếm feedback. | Correct owner, assert valid option/worker/stock trước khi assert no automatic queue row. |
| F08a wording `:476–486` | Forged bound O-303/P-203 với C-001, skip ownership read. | Setup bound từ đơn đúng owner qua API/store thật. |
| Cache ingestion fixture `test_cache_engineering.py:27,162` | Query đổi thành giờ mở cửa nhưng FakeAgent vẫn trả chính sách bảo hành. | Reply đúng FAQ; assert content và hit/miss, không chỉ call_count/source. |

Giữ các test hữu ích, nhưng không khóa số lượng ở 30 để tránh thêm regression case. Acceptance yêu cầu behavioral coverage; test cần đỏ khi bỏ guard tương ứng, không chỉ xanh khi helper được gọi.

## 4. Phần đã làm đúng và phần chưa thuộc PR A

| Mục | Đánh giá |
|---|---|
| F01 | Fullmatch FAQ, deictic/query/history/context/attachment guards và counter tại execute đã có; cross-intent, unverified trace/resume vẫn cần sửa. |
| F02 | Replay #2, snapshot reload và cache-hit commit đã nằm dưới conv_lock; ExitStack release lock đúng hướng. Interrupted retry contract chưa đạt. |
| F03 | SQLite OperationalError được normalize; execute trực tiếp re-raise ApiError 429/5xx. Worker/provider xuyên toàn luồng chưa đạt. |
| F04 | Guard eligible/result ID tốt hơn baseline, delivered case thường không có proposal. Chưa đảm bảo đúng explicit order và refusal luôn được giữ. |
| F05/F06 | Đã lấy product từ đơn mới và có bốn nhánh stock; fallback/variant resolution chưa đủ chính xác. |
| F08a | Nhãn Staff Desk và wording positive exchange đã trung thực hơn. Một số unknown/error paths vẫn hứa ghi nhận chưa xảy ra. |
| F11 | Category None xử lý đúng; aliases null còn crash. |

**Không coi các mục PR B pending là regression mới của PR A:** HTTP admission max 6, hoàn thiện InferenceGate/headroom, telemetry producer/importer, history retention F12, tenant-scoped ToolCache/epoch CAS F13 và OAuth SEC-01 phải được nghiệm thu ở PR B. PR C/F08b vẫn hoãn theo phạm vi được duyệt.

Tương tự, chưa yêu cầu GraphRAG, fine-tune hoặc mở rộng pipeline để đóng PR A. Việc plan READY chỉ chứng minh đặc tả đủ để triển khai; không chuyển thành implementation PASS khi test/checkpoint/error contracts còn hở.

## 5. Thứ tự sửa và điều kiện bàn giao tiếp

1. **Tái hiện trước sửa:** chuyển G02/G03/G06 thành regression tests có model/commit assertions; sửa các test chứng minh sai ở G10.
2. **Sửa safety/runtime:** retry prevalidation trước cache; propagate provider/tool failure; hủy đúng đơn và giữ refusal.
3. **Sửa cache và dữ liệu:** intent isolation, completeness/type/resume guards; order-product mapping, size/color và null aliases.
4. **Chốt regression:** cập nhật fixture cũ đúng contract, chạy full discovery và contract gates; rebuild notebook sau thay đổi source/test cuối cùng, rồi `--check`.
5. **Nghiệm thu PR A:** cung cấp commit/diff cuối, commands và kết quả PASS/FAIL/SKIP. Bắt buộc CI disposable PostgreSQL/pgvector và các HTTP/JS gates được cấu hình trong repository; không suy diễn local SKIP thành PASS.
6. **Sau PR A đạt:** triển khai PR B dựa trên `PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md`, `PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md`, `PLAN_MODULE_2_5_HARDENING_VERIFICATION.md`, `PLAN_RBAC_GOOGLE_AUTH.md` và handoff hiện có. Link `PLAN_PR_B_CONCURRENCY_CACHE_MULTI_TENANT.md` trong answer Gemini **không tồn tại** ở checkout review.

**Điều kiện thông báo READY implementation:** findings trong phạm vi PR A được đóng bằng test đúng behavior; full regression/CI bắt buộc đạt; không còn false success, wrong-order proposal, retry conflict bypass hoặc cross-intent cache hit. PR B và benchmark model thật vẫn cần acceptance riêng.

**Quyết định lần này: REQUEST CHANGES. Chưa chuyển sang PR B hoặc deploy PR A hiện tại.** File này chứa review và yêu cầu khắc phục; không phải bản sửa source hoặc xác nhận hệ thống production-ready.
