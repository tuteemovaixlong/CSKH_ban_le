# Lịch sử: Kế hoạch Gemini — Cleanup và bàn giao sửa N08

> **SUPERSEDED — snapshot 02/10/2026.** Prompt và trạng thái “4 P1 còn mở” bên dưới không còn là chỉ dẫn hiện hành sau N08 CI report ngày 03/10/2026. Dùng [N08_STOPPING_CONDITIONS.md](N08_STOPPING_CONDITIONS.md) và [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md) cho quyết định hiện tại; giữ file này làm lịch sử cleanup.

Ngày: **2026-10-02**
Bản rà soát đầu vào: [review_clear+project.md](review_clear+project.md)
Trạng thái kỹ thuật tham chiếu: [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md)

**Trạng thái cleanup:** ĐÃ ĐỦ ĐIỀU KIỆN CHUYỂN SANG SỬA N08. Gemini đã reconciliation các status/plan chính; không xóa code hoặc dữ liệu cục bộ. Còn metadata `SESSION_HANDOFF_2026-10-02.md` ghi nhánh `main` cần xác nhận/sửa khi chụp snapshot trước khi code.

> **Prompt Gemini cho bước tiếp theo:** Sửa duy nhất N08-A1/A2/B1/C1 theo handoff trong `review_clear+project.md`. Chụp và bảo toàn dirty tree; xác nhận branch `feature/module-2.5-pr-a` / HEAD `7d0df0d`, làm rõ nhãn `main` trong session handoff. Thêm regression cho lỗi cũ, chạy PostgreSQL disposable integration, full suite và các gates; giữ frozen hashes. Không làm PR B, cleanup thêm, commit/push/deploy. Báo exact diff và PASS/FAIL/SKIP theo từng finding.

## 1. Mục tiêu và ranh giới

Mục tiêu là giảm mơ hồ và loại bỏ đúng những artefact/code không còn giá trị **trước** khi Gemini tiếp tục các sửa lỗi N08. Đây là cleanup-only:

- Có thể chỉnh nội dung tài liệu trạng thái và index để sửa mâu thuẫn hoặc chỉ rõ thứ bậc.
- Có thể xóa source chỉ khi xác minh không được dùng qua import tĩnh/động, entrypoint, Docker, notebook, test, deployment, script vận hành và roadmap đã duyệt.
- Không sửa lỗi migration/account/PostgreSQL trong review N08; không đổi behavior runtime ngoài xóa một thành phần đã chứng minh là chết.
- Không commit, push, deploy; không đổi benchmark, migration data hoặc database cục bộ.

## 2. Chụp trạng thái trước khi thao tác

Chạy và lưu kết quả trước cleanup:

```powershell
git branch --show-current
git rev-parse --short HEAD
git status --short --untracked-files=all
git diff --cached --name-status
git diff --name-status
git ls-files --others --exclude-standard
```

Snapshot hiện đã quan sát ở đầu lượt audit:

- Branch: `feature/module-2.5-pr-a`; HEAD: `7d0df0d`.
- Có hai xóa staged: `docs/SESSION_HANDOFF_2026-09-25.md`, `docs/SESSION_SUMMARY_2026-09-21.md`.
- Working tree có sửa code/test/notebook/status/plan; có các file untracked gồm plan account, review và handoff mới.

Đây là trạng thái có sẵn, không phải cleanup target. Không được stage, unstage, khôi phục, ghi đè hoặc xóa các thay đổi này. Trước khi thao tác file nào đang dirty/untracked, so sánh status ban đầu; mặc định giữ nguyên.

## 3. Đồng bộ hồ sơ trạng thái

Đối chiếu [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md) với:

- [CURRENT_PROJECT_STATUS.md](CURRENT_PROJECT_STATUS.md)
- [SESSION_HANDOFF_2026-10-02.md](SESSION_HANDOFF_2026-10-02.md)
- [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md)
- [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)

Các bước:

1. Sửa tuyên bố “N08 hoàn tất 100%” trong operational status/handoff thành trạng thái **chưa nghiệm thu, 4 P1 đang mở**; giữ chính xác kết quả kiểm thử đã chạy và liên kết tới review mới.
2. Không đổi `PLAN_READY_TO_IMPLEMENT` trong handoff Module 2.5 thành “code complete”: trạng thái đó chỉ nói plan sẵn sàng. Thêm ngày/snapshot và liên kết review để tách plan readiness khỏi implementation verification.
3. Chọn một chỗ làm operational status hiện hành; các session handoff khác là lịch sử, không tạo thêm bản current cạnh tranh.
4. Không sửa hoặc khôi phục hai handoff cũ đang staged-delete. Nếu chúng còn được tham chiếu, chỉ ghi nhận incoming links và báo lại; không tự ý đảo quyết định staged hiện tại.

## 4. Lập bản đồ và chuẩn hóa kế hoạch

Dùng vai trò sau làm hierarchy mặc định; nếu nội dung thực tế không khớp, báo đề xuất trước khi chỉnh:

| Vai trò | Tài liệu |
|---|---|
| Strategic roadmap / trạng thái tiến độ | `PLAN_ROADMAP_INDEX.md` + một operational status hiện hành |
| Quality Gate và phạm vi tổng thể | `PLAN_MODULE_2_5_HARDENING_VERIFICATION.md` |
| PR A | `PLAN_PR_A_CONTEXT_CACHE_DISPUTE.md` |
| PR B concurrency/runtime | `PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md`; `PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md` là đặc tả runtime chi tiết được nó tham chiếu |
| Future identity/RBAC/import | Chọn một nguồn đặc tả chính giữa `PLAN_ACCOUNT_IDENTITY_IMPORT_SPECIFICATION.md` và `PLAN_GOOGLE_ACCOUNT_RBAC_PRODUCTION.md`; file còn lại phải được rút về overview/phasing, không duy trì hai bảng yêu cầu chuẩn độc lập |
| Handoff | `PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md`: readiness của kế hoạch và điều kiện nghiệm thu implementation |

Trong từng file còn hiệu lực:

- Ghi rõ `ACTIVE`, `PLANNED`, `DEFERRED`, `IMPLEMENTED` hoặc `HISTORICAL/SUPERSEDED`, snapshot code và ngày đánh giá.
- Xóa hoặc sửa trạng thái kế hoạch lỗi thời **chỉ sau khi cập nhật mọi link liên quan**.
- Không xóa historical plans, historical reviews hoặc audit evidence chỉ vì chúng cũ/lặp chủ đề.
- Việc import JSONL/XLSX, RBAC SSOT tương lai, GraphRAG, multimodal, omnichannel và fine-tuning phải tiếp tục mang nhãn planned/deferred nếu chưa có runtime evidence.

## 5. Audit code và file ứng viên

### 5.1. PostgreSQL cache helper

[pg_schema.py](../retailops/storage/pg_schema.py) có `CACHE_DDL` và `initialize_cache()` nhưng lượt tìm trong source/tests/scripts/docs không thấy call site; các plan hiện tìm thấy không yêu cầu helper này.

Gemini cần xác minh lại cả dynamic usage, schema initialization và roadmap. Sau đó đưa ra một trong hai kết quả:

- Nếu PostgreSQL semantic cache không được duyệt và helper không có consumer: đề xuất xóa `initialize_cache` cùng `CACHE_DDL`, kèm diff cụ thể.
- Nếu đây là nền tảng cho kế hoạch tương lai: giữ nguyên, ghi owner/consumer/mốc dự kiến vào đúng plan và thêm test khi feature được triển khai; không thêm implementation mới trong cleanup.

### 5.2. Scratch và artifacts

`.gitignore` bỏ qua `scratch/` và `artifacts/`. Trong scratch có các script thử nghiệm/điều tra cũ; `artifacts/business.sqlite3` là dữ liệu cục bộ.

- Liệt kê file, loại dữ liệu, thời điểm và tham chiếu trong repo.
- Có thể đề xuất lưu trữ/xóa từng script scratch nếu xác nhận đó là experiment hết hạn.
- Không xóa toàn thư mục, file DB, artifact benchmark, secret hoặc dữ liệu chỉ vì Git ignore chúng.
- Cache `__pycache__`/`.pytest_cache` chỉ được dọn nếu là dữ liệu tạo tự động và không có process sử dụng.

### 5.3. Không xóa nhầm code đang dùng

Các root-level modules hiện còn được import, test, đóng gói Docker/notebook hoặc tham chiếu deploy; không di chuyển/xóa chúng chỉ để chuẩn hóa package. Tần suất symbol thấp trong AST/grep là tín hiệu điều tra, không phải bằng chứng dead code. Trước khi đề xuất xóa bất kỳ symbol nào, ghi call-sites, dynamic references, CLI/public API, tests và plan references.

## 6. Thứ tự thao tác và báo cáo bắt buộc

1. Hoàn tất inventory, reference scan và bảng **Keep / Update / Candidate delete / Needs owner decision** trước.
2. Thực hiện cập nhật tài liệu status/hierarchy đã được phạm vi này cho phép; với deletion source hoặc ignored user data, chỉ thực hiện khi evidence đạt điều kiện mục 5. Nếu không thể chứng minh an toàn, giữ nguyên và báo candidate.
3. Kiểm tra link nội bộ, headings, duplicated status claims và `git diff --check`.
4. Chạy:
   - `python -B -X utf8 scripts/check_docs_contract.py`
   - Full unittest nếu có thay đổi code; nếu chỉ thay docs, chạy gate docs và test contract liên quan.
   - `python -B -X utf8 scripts/build_agent_notebook.py --check` nếu có sửa source/notebook mapping.
5. So sánh lại staged/unstaged/untracked status với snapshot đầu. Báo mọi file ngoài scope đã đổi; không khôi phục chúng.
6. Báo theo từng file: **giữ/sửa/xóa**, bằng chứng caller/reference, lý do, test/gate PASS/FAIL/SKIP, và commit hiện tại. Không ghi “dọn sạch hoàn toàn” nếu còn candidate chưa phân loại.

## 7. Kết quả và điều kiện kết thúc cleanup

Gemini đã hoàn thành phần cleanup chính và các điểm sau được xác nhận trong lượt review:

- `CURRENT_PROJECT_STATUS.md`, `SESSION_HANDOFF_2026-10-02.md`, roadmap và execution handoff ghi N08 chưa nghiệm thu, còn bốn P1; giữ đúng mốc `PLAN_READY_TO_IMPLEMENT` là readiness của plan.
- Roadmap và hai plan account đã nêu hierarchy/source-of-truth.
- Không có code hoặc dữ liệu người dùng bị xóa; `initialize_cache` vẫn là candidate cần quyết định riêng.
- Docs contract, deployment contract, notebook sync và `git diff --check` đều PASS; full suite theo báo cáo là 418 PASS, 43 SKIP, 0 FAIL/ERROR.

**Còn một việc metadata P2:** session handoff ghi nhánh `main`, nhưng snapshot Git hiện tại là `feature/module-2.5-pr-a` / `7d0df0d`. Trước khi sửa bug, xác nhận đây có phải branch của cùng snapshot; nếu đúng thì chỉnh metadata hoặc phân biệt deployed baseline với working branch. Điều này không ngăn bắt đầu bugfix nếu Gemini ghi đúng snapshot và không làm mất thay đổi đang có.

Cleanup được đánh giá **READY FOR N08 BUGFIX**. Bước tiếp theo là xử lý bốn finding theo [REVIEW_ACCOUNT_ORDER_WORKFLOW.md](REVIEW_ACCOUNT_ORDER_WORKFLOW.md) và handoff trong [review_clear+project.md](review_clear+project.md). Đây chưa phải nghiệm thu N08, chưa cho phép chuyển PR B, merge hoặc deploy.

## 8. Kết quả kiểm tra Gemini và gate

- Báo cáo cleanup: full suite 461 tests, 418 PASS, 43 SKIP, 0 FAIL/ERROR; skip là PostgreSQL/pgvector/RAG cần DB disposable và một test Waitress.
- Review độc lập lượt này: docs contract **PASS 4/4**, deployment contract **PASS**, notebook sync **PASS**, `git diff --check` **exit 0** (chỉ có cảnh báo line ending).
- Không có code cleanup hoặc xóa dữ liệu trong đợt cleanup; các diff code/test PR A và staged deletions có từ trước được giữ nguyên.
- Scratch inventory: 17 Python + 1 JSON ở cấp đầu thư mục, cùng một `.pyc` lồng trong `__pycache__`; không xóa vì chúng bị ignore và không có xác nhận chủ sở hữu.
- Frozen benchmark và 43 integration skips vẫn phải được giữ/giải quyết trong bước nghiệm thu N08; đặc biệt PostgreSQL v2 cần test thật, không chỉ contract tĩnh.
