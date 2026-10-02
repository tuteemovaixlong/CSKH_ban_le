# Review GPT 6.1 Sol — Verify đợt sửa N08-A/B/C/D

Ngày: **2026-10-02**. Snapshot: working tree chưa commit trên **7d0df0d**, nhánh **feature/module-2.5-pr-a**. Đối chiếu attachment **e841d20c-c1df-4af4-94ba-77d448d90a78/Pasted text.txt** với code và test liên quan. Phạm vi: migration account legacy, Google linking, PostgreSQL parity, live provisioning và bảo toàn N03; không audit toàn hệ thống.

> **Prompt cho Gemini:** Chỉ sửa 4 finding N08-A1/A2/B1/C1 dưới đây: migration identity–business phải phục hồi được khi commit lỗi và fail-closed khi thiếu business DB; legacy linking phải yêu cầu email đã xác minh; PostgreSQL phải nhận đúng schema v2 và xử lý upgrade an toàn. Thêm regression tái hiện từng lỗi, chạy PostgreSQL disposable thật, giữ N03 và live SQLite đã đạt. Chạy suite/gates/hash, đồng bộ notebook cuối; không sửa review/handoff/dataset, không deploy. Báo PASS/FAIL/SKIP và bằng chứng đóng từng finding.

**Kết luận: CHƯA SẴN SÀNG nghiệm thu N08 hoặc chuyển giao với nhãn “đã hoàn tất”.** Claim **461 tests = 418 PASS, 43 SKIP, 0 FAIL/ERROR** được xác nhận, nhưng kiểm tra bổ sung phát hiện **4 finding P1**, thuộc 3 nhóm: migration hai DB, xác minh khi link account legacy, và hợp đồng schema PostgreSQL. N03 và đường live SQLite đã đạt trong phạm vi kiểm chứng.

## 1. Kết quả kiểm chứng độc lập

| Kiểm tra | Kết quả | Ý nghĩa |
|---|---|---|
| python -B -X utf8 -m unittest discover -s tests | **461 tổng; 418 PASS, 43 SKIP, 0 FAIL, 0 ERROR**, exit 0; **56,893 giây** | Khớp số liệu Gemini; chưa bao phủ các lỗi bổ sung bên dưới. |
| python -B -X utf8 scripts/build_agent_notebook.py --check | **AGENT_NOTEBOOK_SOURCE_SYNC_OK** | Notebook đồng bộ source. |
| scripts/check_docs_contract.py | **PASS 4/4** | Contract tĩnh; không chứng nhận migration/account linking đúng. |
| scripts/check_deployment_contract.py | **DEPLOYMENT_CONTRACT_OK** | Không phải kết quả deploy hay integration database. |
| git diff --check | **PASS**, exit 0 | Có cảnh báo LF/CRLF; không có lỗi whitespace trong diff. |
| Hai frozen benchmark | **Hash giữ nguyên** | Chi tiết ở mục 6. |
| N03 qua Application → PublicWeb WSGI | **PASS** | 503, public tool_unavailable, log/event giữ mã gốc, không commit turn. |
| Live SQLite qua Settings → bootstrap → callback WSGI | **PASS** | Login mới có 0 đơn, 0 sản phẩm demo; provision lỗi trả 503, không cấp session. |
| Migration hai DB khi identity commit lỗi | **FAIL về hành vi** | Identity rollback nhưng business đã commit. |
| Migration khi tenant business DB không mở được | **FAIL về hành vi** | Vẫn đổi membership, chưa quarantine đơn cũ. |
| Callback với Google userinfo email_verified=False | **FAIL về điều kiện linking** | Vẫn cấp session gắn account legacy. |
| Hàm PostgreSQL schema guard, metadata v2 | **FAIL về code contract** | Hàm thật từ chối v2; metadata được stub, chưa chạy PostgreSQL thật. |

**43 SKIP là skip thật:** 29 test_postgres, 2 test_knowledge, 11 test_rag_chat do chưa có RETAILOPS_TEST_DATABASE_URL; 1 test_public_web thiếu Waitress. Các test RAG này yêu cầu disposable PostgreSQL/pgvector, **không phải 11 test bắt buộc external provider** như báo cáo ghi. Không tính skip thành pass.

Các reproduction bổ sung dùng DB tạm, source legacy lấy từ HEAD, scripted model và HTTP/Google response mock. Không gọi Google/cloud thật, không dùng tenant DB đang chạy. **0 FAIL của unittest suite và các finding ngoài suite là hai loại bằng chứng khác nhau.**

## 2. Những phần Gemini đã sửa đúng

- **N08-A, nhánh thành công trên SQLite:** đã mở business DB; order/conversation mơ hồ được đưa về quarantine; hai membership được cấp customer mới; tạo business customer và xóa session cũ. Test mới đã có cả identity và business DB, tốt hơn vòng trước.
- **N08-B, legacy account thông thường:** đã tìm principal derive từ email và liên kết sub với principal đó; test giữ membership/customer/đơn cũ đạt. Lookup theo cùng sub khi đổi email cũng giữ customer. Live thiếu sub bị từ chối **400 missing_sub**.
- **N08-C, cấu trúc:** PostgreSQL DDL đã có external_identities và customer_links; có nhánh migration identity v1 → v2; importer nhận thêm hai bảng và bỏ qua bảng không tồn tại trong snapshot cũ.
- **N08-D, SQLite:** Settings đã nhận live; bootstrap và callback truyền mode. Kiểm độc lập bằng WSGI ghi nhận **302 Found**, **orders=0, products=0, customers=1**.
- **Provision failure:** inject lỗi business store ở callback live → **503 customer_provision_failed**, **0 lần gọi cấp session**, không có header Set-Cookie. Session có sẵn trước đó không bị tăng thêm.
- **N03:** inject ApiError(503, database_unavailable, secret-detail) từ tool → WSGI trả **503 tool_unavailable**, không chứa secret-detail; event và ERROR log giữ **original_code=database_unavailable, stage=tool_execution, tool=get_order**; history có **0 turn**.

N03 có log nội bộ và event trong bộ nhớ; chưa kiểm hệ thống thu log hoặc rule alert production. Live SQLite đạt không đồng nghĩa backend PostgreSQL đã đạt.

## 3. Findings cần sửa

### N08-A1 — P1: Transaction hai DB không rollback đồng bộ

**Vị trí:** [identity/store.py](../retailops/identity/store.py) (dòng 124), các nhánh business transaction tại dòng 126–175 và 207–211; identity chỉ commit tại dòng 248.

Business store dùng **connection/transaction riêng**, commit ngay khi thoát with b_conn_ctx; outer identity transaction chưa commit. Lỗi phát sinh ở identity commit hoặc một tenant xử lý sau đó không rollback các business transaction đã hoàn tất. Claim “toàn bộ thao tác rollback an toàn” chưa đúng.

**Tái hiện:** dựng hai account bằng source legacy tại HEAD, cùng customer CG-7b9b7957, có đơn O-9001 trong tenant DB thật. Tạo deferred foreign-key violation trong identity transaction rồi chạy helper migration thật; lỗi xảy ra khi commit:

~~~text
identity commit: IntegrityError
identity memberships: CG-7b9b7957, CG-7b9b7957  (rollback)
business O-9001 owner: quarantine_CG-7b9b7957  (đã commit)
business cust_<UUID> được tạo: 2                (đã commit)
~~~

Identity vẫn giữ mapping cũ trong khi business đã chuyển đơn và tạo customer mới. Audit event nằm trong identity transaction cũng rollback, nên trạng thái business không có event commit tương ứng.

**Yêu cầu:** thiết kế transaction chung nếu phù hợp hoặc migration có journal/trạng thái, recovery và idempotency; chặn phục vụ account bị ảnh hưởng khi chưa hoàn tất. Không tuyên bố atomic chỉ vì hai DB đều dùng connection(write=True).

**Đóng khi:** regression inject lỗi **sau business write, tại identity commit**, lỗi ở tenant thứ hai và restart/retry chứng minh không phục vụ mapping lệch, không mất/quyền sở hữu sai; hoàn tất recovery có audit rõ ràng.

### N08-A2 — P1: Không mở được business DB vẫn di trú identity

**Vị trí:** [identity/store.py](../retailops/identity/store.py) (dòng 79), dòng 79–104 và 176–183.

get_tenant_db_conn() nuốt lỗi resolver/connection rồi thử SQLite fallback. Khi cả hai không lấy được business DB, trả None; helper vẫn đổi customer của membership thứ hai và ghi legacy_collision_migrated. Không biết đơn/history hiện hữu thuộc ai nhưng vẫn cho account giữ ID cũ.

**Tái hiện:** tenant business DB có đơn nhưng đường mount không ở fallback; resolver trong fixture báo lỗi. Helper **không raise**, commit hai customer khác nhau trong identity, trong khi:

~~~text
business O-9001 owner: CG-7b9b7957
membership trỏ customer không có trong business: 1
identity event: legacy_collision_migrated
quarantine: chưa thực hiện
~~~

Đây là hành vi identity-only của lỗi cũ trong nhánh database không sẵn sàng. Một account vẫn gắn customer dùng chung và có khả năng thấy đơn mơ hồ khi business DB hoạt động trở lại.

**Yêu cầu:** fail-closed khi không kiểm được business data: giữ mapping chưa di trú, đánh dấu/chặn account collision và báo lỗi có thể vận hành; không ghi sự kiện “migrated” thành công. Không biến lỗi đọc/update conversation thành kết luận “không có conversation”.

**Đóng khi:** thiếu mount, lỗi resolver, lỗi đọc bảng và lỗi update conversation đều không gán owner ngẫu nhiên, không tạo customer link mồ côi, không phát session dùng mapping chưa được xác minh; retry sau khi storage phục hồi hoàn tất an toàn.

### N08-B1 — P1: Link account legacy bằng email chưa được xác minh

**Vị trí:** [auth_google.py](../retailops/http/auth_google.py) (dòng 168–177), đoạn nhận/trả userinfo; [public.py](../retailops/http/public.py) (dòng 105); [identity/store.py](../retailops/identity/store.py) (dòng 408).

Code mới dùng email để tìm và link principal legacy. exchange_code_for_user_info() **không kiểm hoặc truyền email_verified**; callback không có guard; store chỉ yêu cầu sub không rỗng ở live. Có sub hợp lệ không chứng minh email dùng để tìm account cũ đã được xác minh.

**Tái hiện qua adapter exchange thật và callback WSGI:** mock HTTP token/userinfo responses; profile có email trùng account legacy, sub khác và email_verified=False:

~~~text
callback: 302 Found
same_legacy_membership: True
visible_legacy_orders: 1
session được cấp: có
~~~

Kiểm này chứng minh boundary hiện chấp nhận linking không đạt điều kiện xác minh email; không phải kết quả gọi Google thật hoặc bằng chứng sự cố production.

**Yêu cầu:** giữ và kiểm tín hiệu xác minh từ provider trước khi dùng email để linking; thiếu/false phải từ chối linking legacy. Phân biệt lookup account đã có (issuer, sub) với lần chuyển đổi legacy qua email. Account legacy đã bind một sub khác không được tự gộp thêm identity chỉ vì email trùng; cần bằng chứng/linking flow rõ ràng.

**Đóng khi:** qua callback, email verified true bảo toàn account cũ; false/missing không link hoặc cấp quyền vào đơn cũ; sub khác với principal đã bind không được tự merge; cùng sub đổi email vẫn giữ account hợp lệ.

### N08-C1 — P1: PostgreSQL schema v2 bị runtime từ chối

**Vị trí:** [postgres.py](../retailops/storage/postgres.py) (dòng 89); [pg_repositories.py](../retailops/storage/pg_repositories.py) (dòng 23).

Đã thêm IDENTITY_SCHEMA_CURRENT=2 và IDENTITY_SCHEMA_COMPATIBLE=(1,2), nhưng assert_schema() vẫn dùng:

~~~python
supported = (1,) if component == 'identity' else BUSINESS_SCHEMA_COMPATIBLE
~~~

PostgresSessions tạo PostgresIdentityStore(dsn) với create=False, gọi check_schema() trước login. Vì vậy schema được tạo/nâng lên v2 bị startup guard từ chối. Ngược lại, v1 được chấp nhận dù các API mới cần hai bảng mà v1 legacy chưa có; constructor mặc định không gọi migration.

**Kiểm độc lập:** gọi **hàm assert_schema() thật**, stub riêng driver SQL builder và metadata trả về từ DB:

~~~text
identity metadata version=1: ACCEPTED
identity metadata version=2: REJECTED — Unsupported PostgreSQL schema version or component.
~~~

Đây là failure có thể xác định từ code và hàm guard; **chưa phải PostgreSQL integration execution**. Môi trường hiện thiếu cả psycopg và test DSN.

**Yêu cầu:** thống nhất initializer, schema guard và startup path. Runtime cần nhận schema v2; v1 phải có đường upgrade rõ ràng hoặc bị từ chối với hướng dẫn migrate, không được chấp nhận thiếu bảng cho API mới. Migration phải xử lý collision có business data an toàn; ON CONFLICT DO NOTHING khi backfill customer_links không thay thế reconciliation owner.

**Đóng khi:** trên PostgreSQL disposable, chạy fresh v2 → startup → Google login; legacy v1 → upgrade → startup → relogin giữ đơn; collision quarantine, import và rollback/retry có regression chạy thật. Không đóng bằng test kiểm chuỗi DDL.

## 4. Vì sao full suite xanh vẫn còn lỗi

- Test N08-A đã có business DB, nhưng nhánh lỗi hiện chỉ inject FaultyStore.connection(); chưa tạo failure tại **outer identity commit sau business commit**.
- Fixture của test lỗi còn có fallback tenant DB hợp lệ, nên không kiểm tình huống **resolver lỗi và fallback cũng không mở được DB**. Đoạn try/except RuntimeError không bắt buộc phải có exception.
- Test N08-B gọi login trực tiếp với chuỗi sub; chưa đưa email_verified=False/missing qua exchange/callback.
- Test N08-C chỉ kiểm DDL, constant và danh sách importer. Có import initialize nhưng không chạy migration, assert_schema, PostgresSessions hoặc Google login trên DB.
- Test N08-D đã đi qua Settings/bootstrap/route, là cải thiện đúng. Kiểm độc lập thêm WSGI và lỗi provisioning đạt trên SQLite; PostgreSQL vẫn bị N08-C1 chặn.

Cần thêm đúng các regression cho bốn finding; không cần audit lại toàn hệ thống hoặc tăng số test bằng assertion trùng implementation.

## 5. Tình hình và bước tiếp theo

| Hạng mục | Trạng thái |
|---|---|
| N03 sanitize, giữ mã gốc, không commit turn lỗi | **VERIFIED PASS** tại boundary kiểm tra. |
| UUID và order isolation cho account mới | **PASS trong local suite**; không chứng nhận mọi tình huống legacy/backend. |
| N08-A happy path SQLite | **PASS**, nhưng lỗi transaction/storage còn **A1/A2 OPEN P1**. |
| N08-B legacy relogin thông thường | **PASS**, nhưng điều kiện linking còn **B1 OPEN P1**. |
| N08-C PostgreSQL | DDL/migration đã bổ sung; **C1 OPEN P1**, integration **PENDING**. |
| N08-D live SQLite | **VERIFIED PASS** cả zero-demo-data và provision failure không cấp session. |
| Full suite/notebook/contracts/hash | **PASS** trong phạm vi tương ứng; **43 SKIP** còn nguyên. |

**Bước tiếp theo:** Gemini sửa bốn finding, thêm regression tái hiện, chạy PostgreSQL disposable và đồng bộ notebook. Sau đó review lại N08; chỉ chuyển sang PR B hoặc giai đoạn account/import tiếp theo khi không còn blocker ở phạm vi này. Chưa cần tạo tài liệu “đợt sửa hoàn tất” và chưa deploy.

## 6. Toàn vẹn và phạm vi thao tác

Cả hai file evals/scenarios/master_250_v1.jsonl và evals/scenarios/benchmark_250.jsonl:

- Raw SHA-256: **81f64611eb09eb4d319a29257e9c456fbffff07779182b130832fd7780062105**.
- SHA-256 sau chuẩn hóa CRLF → LF: **36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411**.

Chỉ chủ động ghi đè **file review này**. Không sửa code/test/config/spec/notebook/dataset hoặc các review/handoff khác; không commit/push/deploy. Các reproduction chỉ tạo DB trong thư mục temporary.

Đối chiếu manifest đầu lượt với manifest trước khi ghi review cho thấy ba tài liệu trạng thái phiên có thay đổi đồng thời ngoài các thao tác review: CURRENT_PROJECT_STATUS.md thay nội dung; SESSION_HANDOFF_2026-09-25.md và SESSION_SUMMARY_2026-09-21.md không còn; xuất hiện SESSION_HANDOFF_2026-10-02.md. Không sửa hoặc khôi phục các file này. Không có thay đổi code/dataset do lượt kiểm tra này gây ra.

Review này thay thế toàn bộ nội dung cũ, chỉ kết luận phần liên quan đến báo cáo Gemini lần này.
