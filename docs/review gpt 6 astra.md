# Review GPT 6 Astra

Ngày: **01/10/2026 — Asia/Bangkok**. Baseline repository: **d01f729**. Đối tượng: bộ PLAN Module 2.5 trong working tree sau vòng Gemini sửa R03/R12. **Nội dung này thay thế toàn bộ review trước.**

## Prompt ngắn cho Gemini

> Bộ plan Module 2.5 đã đạt READY. Chỉ đồng bộ câu headroom cũ tại PLAN_PRODUCTION_SCALING.md:26 với đặc tả Runtime, giữ trạng thái superseded/post-thesis và phạm vi PR A/B. Dùng PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md làm hướng dẫn cho lượt triển khai tiếp theo. Không sửa code/config/dataset/review trong lượt chốt tài liệu; không commit/push/deploy.

## Thông báo nghiệm thu kế hoạch

**PLAN_READY_TO_IMPLEMENT — MODULE 2.5, PR A → PR B.**

**14/14 mục R01–R14 đã đóng ở mức đặc tả. Không còn phát hiện P0/P1/P2 chặn việc triển khai trong phạm vi được review.** Hai mục cuối R03/R12 đáp ứng tiêu chí đóng của vòng trước.

Đợt chỉnh kế hoạch Module 2.5 có thể kết thúc. Đã tạo riêng [PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md](PLAN_EXECUTION_HANDOFF_GPT6_ASTRA.md) trong cùng lượt nghiệm thu, ghi baseline, phạm vi, thứ tự triển khai, kiểm thử và bằng chứng cần thu thập.

**Giới hạn của READY:** Đây là chấp nhận kế hoạch để bắt đầu viết code. Không phải xác nhận các lỗi runtime đã sửa, mọi test đã PASS, hệ thống đã sẵn sàng production hoặc toàn bộ plan Phase 4–6 đã được duyệt triển khai. Các nhãn PENDING TEST của implementation phải được giữ đến khi có kết quả thật.

Còn một ghi chú P3 ở tài liệu đã superseded và một lỗi ghi lệnh trong báo cáo Gemini; xem phần ghi chú. Hai điểm này không làm thay đổi đặc tả A/B hoặc chặn mốc READY.

## R03 — Đã đóng: Headroom và SLO có điều kiện

Đối chiếu trực tiếp:

| Tài liệu | Bằng chứng |
| --- | --- |
| [Module 2.5:130–136](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md#L130) | Admission trước session/DB; max 6; release finally; không còn bảo đảm hai worker rảnh tuyệt đối. |
| [Sprint:16](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L16) và [84–93](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L84) | Đã bỏ mô tả WSGI không bị block bởi inference; ba tầng và giới hạn tài nguyên nhất quán. |
| [Runtime:82–93](PLAN_RUNTIME_EFFICIENCY_CONCURRENCY.md#L82) | Phân biệt chat được nhận, reject và model queue; mô tả rõ mục tiêu P99. |
| [Roadmap:79](PLAN_ROADMAP_INDEX.md#L79) | Tóm tắt PR B phản ánh đúng giới hạn của limiter. |
| [AC-09](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md#L236) | Nghiệm thu theo cấu hình/tải có kiểm soát; giữ đúng error contract. |

Hợp đồng hiện đã đủ rõ để triển khai:

- Một tiến trình Waitress, 8 workers; admission nhận tối đa 6 chat đồng thời cho tổng các provider.
- Acquire không chặn trước đọc body/session/DB; request vượt ngân sách nhận 429; token được trả trong finally.
- Không suy ra worker pool riêng hay hai worker luôn rảnh từ phép trừ 8 − 6.
- P99 ≤50 ms cho health/session là mục tiêu đo tại client trong harness có 6 chat được giữ bằng barrier, mô phỏng DB/tools/model chậm; tài nguyên dùng chung không bị khóa/cạn kiệt ngoài điều kiện đã định.
- Flood request bị reject và DB bị khóa toàn cục là tình trạng khác; không lấy SLO trên làm bảo đảm cho chúng.

| Điều kiện | Mã HTTP / error |
| --- | --- |
| Admission đầy | 429 / server_busy |
| Conversation lock bận | 429 / model_busy |
| Model queue đầy | 429 / model_busy |
| Chờ queue quá 10 giây | 429 / queue_timeout |

Giữ header Retry-After: 5 theo hợp đồng overload và kiểm tra response thực khi triển khai. Các thông số K=1/Q=5 vẫn là mục tiêu của PR B.

**Kết luận:** R03 đóng. Không yêu cầu thêm ASGI, worker pool riêng hoặc thay kiến trúc trong vòng này.

## R12 — Đã đóng: Phân biệt evidence, số hạng mục và target test

Đã xác nhận:

1. [AC-14](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md#L241) và [D03](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L179) dùng **CODE INSPECTED — SQLite v3 assertions tại a6ec080; TEST EXECUTION EVIDENCE PENDING**; PostgreSQL vẫn code-inspected/integration-pending.
2. [K04](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L184) ghi **HISTORICAL RESULT REPORTED**, dẫn CURRENT_PROJECT_STATUS.md:52–56; không còn gắn “353/353 CI passed tại a6ec080”.
3. [Module:7](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md#L7) và [Roadmap:59](PLAN_ROADMAP_INDEX.md#L59) thống nhất **13 hạng mục**: F01–F07, F08a, F09, F11–F13, SEC-01.
4. [Sprint:29](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L29) và [203](PLAN_CONCURRENCY_RELATIONAL_KNOWLEDGE_SPRINT.md#L203) xác định **415+ là target dự kiến**; không coi đó là số test hiện hữu hoặc đã chạy.
5. Ma trận PR A thực tế vẫn có **30 dòng scenario**, đúng với tiêu đề và acceptance.

Số test là thông tin kế hoạch; điều kiện nghiệm thu phải dựa vào coverage và kết quả các ca bắt buộc. Không cần chạy DB hoặc GitHub Actions chỉ để đổi nhãn tài liệu thành PASS trong vòng này.

**Kết luận:** R12 đóng. Bằng chứng runtime tiếp tục được thu thập ở giai đoạn implementation.

## Ma trận nghiệm thu toàn bộ R01–R14

| Mã | Kết quả | Căn cứ và giới hạn |
| --- | --- | --- |
| R01 | **Đóng đặc tả** | FAQ fullmatch; has_turns dự kiến có nguồn DB thật; unknown fail-closed; eligibility_before_turn dùng chung lookup/store; provenance thuộc PR A. |
| R02 | **Đóng đặc tả** | Replay hai chặng, reload snapshot dưới conv_lock, retry đổi revision/context trả 409; không đổi seed/checkpoint âm thầm. |
| R03 | **Đóng đặc tả** | Admission có giới hạn rõ; SLO có điều kiện; error codes chuẩn. |
| R04 | **Đóng đặc tả** | RBAC phân biệt quyền UI/API và owner scope; không gán quyền xem/hủy hộ ngoài hợp đồng. |
| R05 | **Đóng đặc tả** | OAuth xác minh trước consume nguyên tử; response lỗi mang Set-Cookie; callback cũ không xóa cookie login mới. |
| R06 | **Đóng đặc tả** | DB không prune theo 6 lượt; prompt vẫn bounded; transcript/pagination có phạm vi rõ. |
| R07 | **Đóng đặc tả** | Benchmark đóng băng; converter dùng output candidate riêng. |
| R08 | **Đóng đặc tả** | Sprint và PR A không còn heading bị lặp/nối hỏng; roadmap có mốc baseline rõ. |
| R09 | **Đóng đặc tả** | Telemetry xuyên producer/importer; phân biệt zero/null, queue wait/model time, N model calls. |
| R10 | **Đóng đặc tả** | Shared ToolCache theo tenant/customer; epoch/CAS discard stale writes; phạm vi một tiến trình. |
| R11 | **Đóng đặc tả** | Ma trận tải 1/2/4/8/16 và các chỉ số đo được giữ cho Phase 4. |
| R12 | **Đóng đặc tả** | Evidence không vượt quá phạm vi kiểm chứng; 13 hạng mục, 30 scenario, target 415+ phân biệt rõ. |
| R13 | **Đóng đặc tả** | Mermaid/heading PR A được bảo toàn; kiểm tra nguồn không thay thế browser render. |
| R14 | **Đóng đặc tả** | migrate(db, component, initialize), SQLite Business v3/PostgreSQL Business v4; không thêm migration A/B. |

Không mở lại các quyết định đã đạt hoặc kéo phần deferred vào A/B. Việc code chưa thực hiện các mục trên là trạng thái implementation pending đã được kế hoạch thừa nhận.

## Kiểm tra độc lập trong lượt này

| Kiểm tra | Kết quả |
| --- | --- |
| python -B -X utf8 scripts/check_docs_contract.py | **PASS 4/4** |
| git diff --check | **PASS, exit 0** |
| Hai khối Python query filter và FAQ/history guard trích từ Markdown | **AST PASS 2/2** |
| Predicate chạy thuần bộ nhớ | **PASS 15/15 assertion** |
| Ma trận PR A | **30 scenario** |
| Heading PR A và Sprint | Không phát hiện heading lặp hoặc nối vào bullet |
| Hai bộ master/benchmark | Mỗi bộ 250 ca; hash LF-normalized đúng giá trị ghim theo checker |
| Fingerprint nguồn kế hoạch | Đã ghi SHA-256 của sáu plan chính trong file bàn giao |
| Bảo toàn workspace | Đối chiếu SHA-256 282 tệp tracked trước/sau khi ghi hai tài liệu review/bàn giao |

15 assertion gồm: 3 FAQ hợp lệ; 4 phản ví dụ cá nhân/câu ghép/chính sách; 4 giá trị lịch sử None/True/False/0; 4 trường hợp order/product/attachment/snapshot thiếu. Chạy chính mã được trích từ plan, không dùng script scratch của Gemini thay thế.

**Không chạy mới:** toàn bộ runtime suite, PostgreSQL integration, live OAuth, load test Waitress, model/API hoặc benchmark khoa học. Không tuyên bố kết quả của những kiểm tra chưa chạy. Checker tài liệu không tự chứng minh tính đúng của runtime và không render Mermaid.

## Ghi chú không chặn READY

### N1 — P3: Một câu cũ trong tài liệu Production Scaling

[PLAN_PRODUCTION_SCALING:26](PLAN_PRODUCTION_SCALING.md#L26) còn mô tả InferenceGate “luôn chừa ít nhất 2 luồng trống”. Đây là cách diễn đạt cũ, không đúng để dùng làm đặc tả runtime hiện tại.

Tuy nhiên, [metadata dòng 2](PLAN_PRODUCTION_SCALING.md#L2), [phạm vi dòng 13](PLAN_PRODUCTION_SCALING.md#L13) và [Roadmap:54](PLAN_ROADMAP_INDEX.md#L54) đã đánh dấu tài liệu **SUPERSEDED / NEEDS UPDATE, Phase 6 post-thesis**. Vì vậy câu này không có quyền thay thế đặc tả Module 2.5 đang áp dụng và không mở lại R03.

Gemini có thể đồng bộ riêng câu đó hoặc dẫn sang Runtime plan, giữ nguyên deferred scope. Không cần một vòng thiết kế lại A/B.

### N2 — Ghi lệnh kiểm tra trong báo cáo Gemini

Bảng cuối attachment ghi `python -m check_docs_contract`, còn log thao tác và file thật dùng `scripts/check_docs_contract.py`. Lệnh đã được tôi xác minh là:

```powershell
python -B -X utf8 scripts/check_docs_contract.py
```

Đây là lỗi ghi lại lệnh trong phần trả lời, không phải một lỗi contract của bộ plan. Dùng đúng lệnh trên cho các lượt sau.

## Quỹ đạo tiếp theo

**Dừng vòng sửa kiến trúc plan; chuyển sang thực hiện có bằng chứng theo file bàn giao.**

1. Chốt snapshot tài liệu được duyệt làm baseline ở lượt thực thi; hiện các sửa PLAN vẫn ở working tree.
2. **PR A:** Viết test tái hiện cho correctness/cache/provenance/dispute/truthful wording, triển khai và chạy regression.
3. **PR B sau PR A:** Admission/gate, history, shared cache/epoch, OAuth và telemetry đến importer.
4. Công bố **IMPLEMENTATION_VERIFIED** khi các acceptance bắt buộc có kết quả thật theo backend/môi trường; không dùng số test dự kiến hoặc lịch sử để thay thế.
5. **Phase 4:** Benchmark frozen 250 ca và tải 1/2/4/8/16; cố định cấu hình, tách cold/warm cache, giữ raw results.
6. **Phase 5–6:** Omnichannel và các mở rộng theo scope riêng. PR C, F08b, ASGI/horizontal scaling không tự được kích hoạt khi A/B xong.

**Hai artifact của lượt này:** File review được thay thế toàn bộ và file bàn giao được tạo mới. Không sửa bất kỳ PLAN nguồn, code, config hoặc dataset nào; không commit/push/deploy.
