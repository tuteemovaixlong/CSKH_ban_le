# Rà soát dọn dẹp dự án — code, plans, reviews và dữ liệu cục bộ

Ngày: **2026-10-02**
Snapshot audit ban đầu: nhánh `feature/module-2.5-pr-a`, HEAD `7d0df0d`. Phần audit ban đầu chỉ đọc; phần sau bổ sung review kết quả Gemini và nội dung bàn giao, không chỉnh code hoặc dữ liệu dự án.

## Kết luận

Ưu tiên dọn **mâu thuẫn trạng thái và ranh giới tài liệu**, không chạy lệnh xóa hàng loạt. Rà soát tĩnh hiện **chưa chứng minh được module runtime lớn nào an toàn để xóa**. Có một helper PostgreSQL cache không thấy call site, nhưng cần chốt nó có thuộc kiến trúc dự kiến không trước khi loại bỏ.

Cây làm việc vốn đã có thay đổi trước lượt này: hai file handoff cũ đang staged để xóa; nhiều file code/test/notebook và tài liệu đang sửa; có handoff và review mới chưa tracked. Các thay đổi này nằm ngoài lượt audit và phải được giữ nguyên. Không dùng `git clean`, `git reset`, `git checkout --` hay lệnh tương đương để “làm sạch”.

## Phát hiện cần xử lý

### P1 — Trạng thái N08 mâu thuẫn giữa báo cáo và review — ĐÃ KHẮC PHỤC TRONG LƯỢT CLEANUP

[Phát hiện ban đầu:] [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) và [SESSION_HANDOFF_2026-10-02.md](SESSION_HANDOFF_2026-10-02.md) ghi PR A/N08 hoàn tất 100%, trái với [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md), nơi còn bốn blocker P1: transaction identity/business không rollback đồng bộ; migration vẫn đổi mapping khi business DB không mở được; linking account legacy không kiểm email đã xác minh; runtime PostgreSQL từ chối schema identity v2. Gemini đã sửa CURRENT status, session handoff, roadmap và handoff plan để nói rõ N08 chưa nghiệm thu và dẫn tới review hiện hành. Nội dung mâu thuẫn này **không còn xuất hiện trong các trạng thái đã kiểm tra**.

Kết quả test lịch sử được giữ lại; trạng thái implementation đã tách khỏi kết quả đó. Đây là phần cleanup quan trọng nhất và đạt yêu cầu.

### P1 — “READY” của handoff và “READY” của implementation bị lẫn — ĐÃ LÀM RÕ

[PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md) vẫn giữ mốc `PLAN_READY_TO_IMPLEMENT` ngày 2026-10-01 cho readiness của **kế hoạch**. Gemini thêm ghi chú phân biệt rõ mốc đó với `PR_A_VERIFIED` và liên kết tới các review implementation hiện hành. Lịch sử plan được bảo toàn.

### P2 — Nhiều plan Module 2.5 cùng mang nhãn ACTIVE

[PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md), [PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md](PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md), [PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md) và [PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md) có phạm vi chồng lấn nhưng vai trò khác nhau: plan cha, PR A, sprint PR B và đặc tả runtime. Các tài liệu viện dẫn baseline cũ như `c30ff1d` trong khi code hiện ở nhánh/HEAD khác.

Không nên xóa các plan này chỉ vì lặp chủ đề. Nên ghi rõ một thứ bậc: roadmap → plan cha Module 2.5 → plan con theo PR; mỗi file con ghi phần nào là nguồn chi tiết có thẩm quyền và snapshot nào đang mô tả.

### P2 — Hai tài liệu identity/account cần một nguồn thẩm quyền rõ

[PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md](PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md) và [PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md](PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md) cùng đề cập Google identity, RBAC, N08 và triển khai giai đoạn sau; file mới liên kết file kia như đặc tả chi tiết. Chúng có thể bổ trợ nhau, nhưng hiện dễ được đọc như hai kế hoạch độc lập và lẫn thiết kế mục tiêu với trạng thái code hiện tại.

Giữ lại cả hai nếu phạm vi riêng còn giá trị; chỉ định một file làm đặc tả chuẩn, file còn lại làm overview/roadmap và liên kết tới mục cụ thể. Các thiết kế tương lai như import JSONL/XLSX phải được gắn nhãn **planned**, không mô tả như capability đã triển khai.

### P2 — Review, status, handoff là các loại hồ sơ khác nhau

Các file `review gpt 6 astra.md`, `review gpt 6.1 sol.md` và `REVIEW_ACCOUNT_ORDER_WORKFLOW.md` ghi nhận những snapshot/lượt kiểm tra khác nhau. Giữ lịch sử review; không xóa để làm gọn. Thêm trong index/roadmap một bản đồ ngắn nêu file nào là review lịch sử, file nào là kết luận N08 mới nhất, file nào là trạng thái hiện tại. `SYSTEM_REVIEW_FOR_LLM.md` tự ghi snapshot cũ nên không dùng thay cho review code hiện hành.

### P2 — Có một helper cache PostgreSQL chưa thấy được sử dụng

Trong [pg_schema.py](../retailops/storage/pg_schema.py#L104), `CACHE_DDL` và `initialize_cache()` có định nghĩa nhưng không có call site trong source/tests/scripts/docs được tìm thấy. Hiện SemanticCache được tạo và dùng trong Application; chưa tìm thấy kế hoạch yêu cầu bảng PostgreSQL này.

Đây là **candidate cần quyết định**, chưa phải kết luận chắc chắn là rác: nếu PostgreSQL semantic cache không nằm trong roadmap được duyệt, có thể đề xuất bỏ helper và DDL cùng test/contract liên quan (nếu có); nếu sẽ dùng trong tương lai, giữ và ghi rõ module nào sẽ gọi, khi nào và test nào bảo vệ. Không được xóa trước khi kiểm tra toàn bộ dynamic/import/config paths lần cuối.

### P3 — Thư mục cục bộ bị ignore không thuộc source tree

`.gitignore` bỏ qua toàn bộ `scratch/` và `artifacts/`. `scratch/` hiện có các script debug/thử nghiệm cũ; `artifacts/business.sqlite3` là database cục bộ. Không tìm thấy các script scratch được code tracked gọi trực tiếp, nhưng điều đó không chứng minh chúng không còn giá trị cho người dùng.

Có thể phân loại từng script scratch thành giữ, lưu trữ hoặc xóa sau khi chủ sở hữu xác nhận. **Không xóa database, artifacts, credentials, hoặc toàn thư mục ignored bằng lệnh tổng quát.** Cache tạo tự động như `__pycache__/` và `.pytest_cache/` là nhóm riêng; dọn chỉ khi không có tiến trình sử dụng và không chứa dữ liệu cần lưu.

## Những phần đã kiểm tra là đang dùng hoặc cần giữ

- Các module root như `retailops_agent.py`, `retailops_baseline.py`, `retailops_tools.py`, `retailops_conversation.py`, `retailops_providers.py`, `retailops_mcp_server.py`, `inference_proxy.py` còn được import, kiểm tra bởi test, đóng gói Docker/notebook hoặc tham chiếu trong deploy. Không coi đây là legacy để xóa chỉ vì chúng nằm ngoài package `retailops/`.
- `retailops/workflow/mcp_client.py` còn được test và được plan MCP tham chiếu.
- Nhiều symbol xuất hiện một lần trong AST scan là test methods, protocol/framework hooks hoặc entrypoints; số lần grep thấp không đủ chứng minh code chết.
- Các plan ghi rõ `SUPERSEDED/HISTORICAL` là tư liệu nền. Giữ chúng nếu roadmap hoặc review còn liên kết; tránh xóa mà không sửa incoming links và lưu bằng chứng.

## Giới hạn rà soát

Đã kiểm inventory, trạng thái Git, tiêu đề/trạng thái các plan, tham chiếu chéo, một lượt tìm symbol tĩnh trong Python và vị trí scratch/artifacts. Tìm kiếm tên không phát hiện được mọi dynamic import, entrypoint framework hoặc hợp đồng vận hành; vì vậy báo cáo phân biệt candidate với code chắc chắn không dùng. Đây chưa phải chứng minh toán học rằng toàn repo không còn dead code.

## Quyết định dọn dẹp đề xuất

1. Trước hết đồng bộ trạng thái N08 và lập bản đồ nguồn tài liệu.
2. Giữ nguyên các plan lịch sử, frozen datasets và thay đổi đang có trong Git index/working tree.
3. Yêu cầu Gemini đưa danh sách file/symbol sẽ xóa kèm toàn bộ call-site, plan reference, packaging/runtime entrypoint và test evidence **trước khi xóa**.
4. Chỉ dọn scratch/cache đã phân loại; không đụng database hoặc dữ liệu ignored chưa xác nhận.
5. Sau cleanup, chạy docs contract; nếu xóa code thì chạy suite liên quan và full suite. Kiểm tra diff để bảo đảm đợt này chưa lẫn với việc đóng N08-A1/A2/B1/C1.

**Kết luận ban đầu:** Dự án cần reconciliation tài liệu có kiểm soát; chưa có căn cứ xóa hàng loạt source hoặc ignored files.

## Review vòng cleanup của Gemini và bàn giao bước tiếp theo

Đã đối chiếu báo cáo Gemini tại attachment `bd495de8-8552-40fd-be40-3f618ba8e492/Pasted text.txt` với Git status hiện tại, các file status/plan mà Gemini sửa và các gate có thể chạy độc lập.

**Phần cleanup đạt:** Gemini sửa `CURRENT_PROJECT_STATUS.md`, `SESSION_HANDOFF_2026-10-02.md`, `PLAN_ROADMAP_INDEX.md`, `PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md` và quan hệ giữa hai plan account để ghi N08 còn bốn blocker, phân định `PLAN_READY_TO_IMPLEMENT` với nghiệm thu code, và chỉ định spec identity/import làm nguồn kiến trúc chuẩn. Không xóa code, dữ liệu cục bộ, scratch, artifacts hay frozen benchmark. Quyết định giữ `initialize_cache` làm candidate chờ chủ sở hữu là thận trọng; việc này không chặn sửa N08.

**Kiểm chứng:** báo cáo đính kèm có kết quả full suite **461 tổng: 418 PASS, 43 SKIP, 0 FAIL/ERROR** (68,087 giây). 43 test bị skip vẫn là PostgreSQL/pgvector/RAG integration thiếu DB disposable và một test Waitress; chúng không được tính là pass. Tôi chạy lại độc lập `scripts/check_docs_contract.py` (**4/4 PASS**), `scripts/check_deployment_contract.py` (**DEPLOYMENT_CONTRACT_OK**), `scripts/build_agent_notebook.py --check` (**AGENT_NOTEBOOK_SOURCE_SYNC_OK**) và `git diff --check` (**exit 0**, chỉ có cảnh báo LF/CRLF). Cleanup không thêm code changes so với working tree PR A đã có; các thay đổi đó vẫn chưa commit.

**Điểm còn cần sửa/ghi rõ, mức P2:** [SESSION_HANDOFF_2026-10-02.md](SESSION_HANDOFF_2026-10-02.md) vẫn ghi `Nhánh: main`, trong khi working tree hiện tại là `feature/module-2.5-pr-a`, HEAD `7d0df0d`. [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md) ghi application snapshot `main`/`c6c7a1a`, có thể là deployed baseline có chủ ý; cần phân biệt nó với branch đang review. Sửa/giải thích trường snapshot này ở đầu lượt code tiếp theo để không chạy nhầm branch. Gemini cũng gọi scratch là “18 script”; inventory hiện có **17 `.py` + 1 `.json` ở thư mục gốc scratch và 1 `.pyc` trong `__pycache__`**. Đây là lỗi mô tả nhỏ, không ảnh hưởng cleanup hay code.

**Quyết định:** cleanup **đủ điều kiện để bắt đầu sửa bốn bug N08**. Điều này **không** có nghĩa N08 đã đạt, PR A đã nghiệm thu, hay PR B/deploy sẵn sàng. Trước khi sửa, ghi nhận branch/HEAD/diff; giữ nguyên toàn bộ staged, unstaged và untracked changes đang có. Không reset/checkout/clean tree. N08-C1 cần integration trên PostgreSQL disposable; 43 skip hiện tại chưa chứng minh phần đó.

### Nội dung bàn giao cho lượt sửa bug

- **Working branch/snapshot:** `feature/module-2.5-pr-a` / `7d0df0d`; working tree bẩn có sẵn PR A code/test, tài liệu và hai staged deletions. Gemini phải chụp lại `git status --short --untracked-files=all`, `git diff --cached --name-status`, `git diff --name-status` trước khi sửa và bảo toàn mọi mục hiện hữu.
- **Phạm vi duy nhất:** N08-A1 transaction/recovery identity–business; N08-A2 fail-closed khi không truy cập được tenant business DB; N08-B1 xác minh email trước khi link legacy account; N08-C1 PostgreSQL identity schema guard/migration v1→v2.
- **Acceptance:** mỗi finding có regression tái hiện lỗi cũ; xử lý lỗi giữa các transaction và retry/restart không để identity/business lệch; lỗi storage không đổi owner hoặc cấp session với mapping chưa kiểm chứng; email `email_verified` false/thiếu không link account; PostgreSQL v2 được startup guard chấp nhận và v1 có đường upgrade được kiểm chứng.
- **Kiểm chứng cuối:** full unittest; PostgreSQL disposable integration (không tính skip thành pass); docs/deployment/notebook contracts; frozen hash không đổi; review diff theo đúng bốn finding. Không commit/push/deploy và chưa chuyển PR B trong cùng lượt.

> **Prompt Gemini:** Cleanup đã được review; bắt đầu chỉ sửa N08-A1/A2/B1/C1 theo handoff trong `docs/review_clear+project.md`. Trước tiên xác nhận branch/HEAD thực tế (`feature/module-2.5-pr-a`, `7d0df0d`) và giữ nguyên mọi staged/unstaged/untracked change; sửa nhãn `main` trong session handoff nếu nó mô tả cùng working snapshot. Thêm regression tái hiện lỗi cũ cho từng finding, chạy PostgreSQL disposable thật cho schema v1/v2, full suite và các gates; giữ frozen hashes. Không làm PR B, cleanup thêm, commit, push hay deploy. Báo diff, PASS/FAIL/SKIP và bằng chứng từng finding; chưa tuyên bố hoàn tất nếu còn blocker.
