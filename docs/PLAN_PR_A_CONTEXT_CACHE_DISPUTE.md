# KẾ HOẠCH TRIỂN KHAI PR A: CONTEXT, CACHE, DISPUTE & TRUTHFUL BOUNDARY

> **Mã kế hoạch:** `PLAN_PR_A_CONTEXT_CACHE_DISPUTE`
> **Trạng thái:** ACTIVE IMPLEMENTATION PLAN (DEMO REVISION v1.2)
> **Phiên bản:** 1.2 (2026-10-01)
> **Audit basis / Documentation baseline reviewed:** `c30ff1d`
> **Thuộc phân hệ:** Module 2.5 — System Hardening & Quality Gate
> **Mục tiêu:** Khắc phục dứt điểm 6 lỗi logic trọng yếu (F01–F06), lỗi crash catalog (F11) và thiết lập ranh giới ngôn từ trung thực (F08a) liên quan đến rò rỉ ngữ cảnh cache, vi phạm serialization phiên chat, nuốt lỗi hạ tầng trong tool execution, đề xuất hủy đơn sai lệch và ngộ nhận trạng thái phê duyệt đổi hàng. Mỗi hạng mục đều có tệp/hàm, hành vi mong đợi, test tương ứng và trạng thái chưa kiểm chứng.
> **Tài liệu tham chiếu:** [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) · [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)

---

## 1. Danh Mục Lỗi & Bằng Chứng Tái Hiện (Root Cause Analysis)

| Mã | Tên Lỗi | Vị Trí Code Nguồn | Nguyên Nhân Kỹ Thuật Gốc | Hậu Quả Vận Hành |
| :---: | :--- | :--- | :--- | :--- |
| **F01** | Cache trả bảo hành của sản phẩm khác / Rò rỉ context | `retailops/business/cache.py:22-38`<br/>`retailops/business/application.py:130,159,296-300` | `is_cacheable_query(text)` chỉ dùng blacklist regex trên text thô rồi mặc định `return True`. Không có kiểm tra context và không thể biết trước câu hỏi có cần RAG/citations hay không. Khi cache-hit, dòng 159 gán đè context của snapshot hiện tại vào câu trả lời cũ. | Khách đang xem áo khoác P-102 (90 ngày) hỏi *"Áo này bảo hành bao lâu?"* nhận nhầm câu trả lời cache của áo thun P-101. Rò rỉ thông tin chéo giữa các phiên chat. |
| **F02** | Cache-hit commit ngoài `conv_lock` | `retailops/business/application.py:130-167` | Dòng 166 gọi `self.store.finish_turn()` ghi vào DB trước khi `conv_lock.acquire()` được gọi ở dòng 178. | Hai request đến cùng lúc (1 cache-hit, 1 chat thường) gây race condition, CAS conflict (`conversation_changed`), và thứ tự commit bất định giữa các phiên chat. |
| **F03** | Nuốt lỗi hạ tầng (429/503/timeout) trong tool và worker | `retailops/business/application.py:235-242,302-316`<br/>`retailops/workflow/subagents/dispute_agent.py:100-111,163-174,241-245`<br/>`retailops/business/store.py:68-84` | - Tại `Application.execute()` (dòng 237), mọi `ApiError` đều bị bắt và chuyển đổi thành dict `{'error': exc.code}` (kể cả lỗi hạ tầng 5xx/429/DB timeout).<br/>- Dispute worker bắt broad `except Exception` biến thành `is_order_ok = False` ("không tìm thấy đơn") hoặc trả *"Shop đã ghi nhận"* với `complete=True`.<br/>- `Application.chat()` thực hiện preflight (load snapshot, replay) trước `try` chính, nếu SQLite DB locked (`sqlite3.OperationalError`) sẽ không được chuẩn hóa thành 503. | Che giấu sự cố hạ tầng, client không nhận được mã HTTP 503/429 để retry, vi phạm hợp đồng trung thực (truthfulness) và làm sai lệch telemetry. |
| **F04** | Tạo proposal hủy cho đơn delivered | `retailops/workflow/subagents/dispute_agent.py:82-91,232-237`<br/>`retailops_tools.py:71-79` | Dòng 82 chỉ kiểm tra `if name == "prepare_cancellation" and extracted_oid:`, không kiểm tra `result.get('eligible')`. Tool `prepare_cancellation` trả `eligible: False` cho đơn đã giao (không có key `error`), nhưng worker vẫn sinh `action_proposal`. | Đơn đã giao `O-102` (`delivered`) vẫn bị tạo proposal hủy và bot hiển thị hướng dẫn khách bấm *"Xác nhận hủy"* trên màn hình. |
| **F05** | Đổi đơn mới dùng product_id của đơn cũ | `retailops/workflow/subagents/dispute_agent.py:120-127,183-190` | Dòng 120 và 183 ưu tiên `pid = bound_context.get("product_id")` cũ trước khi kiểm tra dữ liệu từ bản ghi đơn hàng mới tra cứu. | Đang xem đơn O-101 (áo P-101), khách nói *"Đơn O-102 bị rách chỉ"*, worker đọc đơn O-102 nhưng lại tra cứu bảo hành của áo P-101. |
| **F06** | Collapse trạng thái tồn kho & Hardcode size/color | `retailops/workflow/subagents/dispute_agent.py:196-207`<br/>`data/products.json:13-18` | Dòng 196 tự gán mặc định size `"L"`. Dòng 200 hardcode `color="Tiêu chuẩn"`. Dòng 204 dùng `stock_res.get("stock") or 0` gộp `None` thành hết hàng (`stock == 0`). Catalog P-101 chỉ có màu Trắng nhưng hỏi màu Đen bị coi là hết hàng. | Đổi size bị sai lệch hoàn toàn; không phân biệt được biến thể không tồn tại (`variant_not_found`), dữ liệu chưa có (`stock_unknown`) và hết hàng (`stock == 0`). |
| **F08a** | Ngôn từ không trung thực & Hổng UI/Queue Đổi hàng | `retailops/workflow/subagents/dispute_agent.py:147,219`<br/>`web/app.js:1022,1721-1757`<br/>`web/index.html:209-210`<br/>`retailops/business/store.py:771-782` | - Frontend (`web/app.js:1022`) hoàn toàn KHÔNG render proposal card hay nút xác nhận cho `action_proposal` đổi hàng.<br/>- Store `escalations()` chỉ lấy `feedback_type='human_handoff'`, exchange proposal không tự vào queue CSKH.<br/>- Bot tự nói *"Em đã ghi nhận đề xuất trên màn hình"* / *"chuyển chuyên viên CSKH duyệt"*.<br/>- Nút Staff Desk gọi `/api/staff/reply` chỉ là chat text nhưng nút và alert tuyên bố *"Duyệt Đổi Mới 1-1"*, *"Đã tạo vận đơn bưu cục, kho tổng đã xuất giữ hàng"*. | Vi phạm nghiêm trọng tính trung thực trong trải nghiệm người dùng (Truthful UX); ngộ nhận trạng thái xử lý khi chưa có backend transaction bền vững. |
| **F11** | Crash 500 khi sản phẩm thiếu category | `retailops_tools.py:49-50`<br/>`retailops/http/routes.py:290` | `search_products` nối chuỗi trực tiếp `' '.join([p['id'], p['name'], p['category']] + p['aliases'])`. Khi Manager tạo sản phẩm không nhập category (`category=None`), hàm ném `TypeError` sập luồng chat 500 của mọi khách hàng khi duyệt catalog. | Bất kỳ yêu cầu tìm kiếm sản phẩm nào cũng có nguy cơ sập HTTP 500 nếu catalog chứa sản phẩm có `category=None`. |

> [!NOTE]
> **Phân định ranh giới F08:**
> - **F08a (Thuộc phạm vi PR A — Truthful Wording Boundary)**: Sửa toàn bộ ngôn từ của Bot AI và UI Staff Desk đảm bảo trung thực tuyệt đối: Bot chỉ thông báo *"đã xác định được phương án phù hợp"*; KHÔNG nói "đã tạo phiếu", "xem đề xuất trên màn hình", hay "đã gửi chuyên viên CSKH duyệt" khi chưa có UI render và chưa persist ticket. Nút Staff Desk và alert chuyển từ "Duyệt đổi thành công" sang "Xác nhận đã tiếp nhận / Đã gửi phản hồi cho khách", KHÔNG tuyên bố giữ kho hay tạo vận đơn bưu cục.
> - **F08b (Khoảng trống hoãn triển khai — DEFERRED / OUT OF SCOPE FOR MODULE 2.5)**: Việc xây dựng bảng lưu trữ bền vững `exchange_requests`, API xác nhận của khách, API phê duyệt của nhân viên và state machine 2-stage hoàn chỉnh sẽ được thiết kế riêng biệt trong giai đoạn sau Module 2.5, tuyệt đối không gộp vào PR A, PR B hay PR C.

---

## 2. Thiết Kế Kiến Trúc & Sơ Đồ Hệ Thống Duy Nhất

Sơ đồ Mermaid dưới đây mô tả chính xác sự chuyển đổi từ **Hiện trạng tại HEAD (BEFORE)** sang **Kiến trúc mục tiêu của PR A (AFTER)**:

```mermaid
flowchart TB
    %% ==========================================
    %% SUBGRAPH 1: BEFORE — CURRENT HEAD
    %% ==========================================
    subgraph BEFORE["BEFORE — Current HEAD (Race Conditions, Context Leaks & Heuristic Vulnerabilities)"]
        direction TB

        B_Req["1. Khách gửi tin nhắn chat<br/>(text, request_id, conversation_id)"] --> B_Snap["2. Load Conversation Snapshot<br/>(Lấy context hiện tại: order_id, product_id)"]

        B_Snap --> B_Rep1{"3. Replay #1 Check<br/>(store.replay)"}
        B_Rep1 -- "Hit" --> B_RepRet["Return Replayed Turn<br/>(Fast Path read-only)"]

        B_Rep1 -- "Miss" --> B_CacheLookup{"4. Semantic Cache Lookup<br/>(Chỉ regex text thô, MÙ ngữ cảnh)"}

        %% BUG F01 & F02 Detail
        B_CacheLookup -- "Hit" --> B_F01["⚠️ BUG F01: Context Leak (Rò rỉ dữ liệu)<br/>- is_cacheable_query() mặc định return True<br/>- Gán đè order_id/product_id của snapshot khách này vào câu trả lời cũ<br/>- Khách hỏi P-102 nhận nhầm thông số của P-101!"]

        B_F01 --> B_F02["💥 BUG F02: Race Condition / Vi phạm Serialization<br/>- finish_turn() bị gọi NGOÀI conv_lock!<br/>- 2 request cùng lúc gây CAS conflict, conversation_changed<br/>- Thứ tự commit bất định giữa các phiên chat!"]

        B_F02 --> B_CacheRet["Trả về kết quả Cache Hit cho khách"]

        B_CacheLookup -- "Miss" --> B_Lock["5. Kiểm tra agent_lock & Acquire conv_lock"]
        B_Lock --> B_Wf["6. Khởi tạo Workflow Checkpoint"]
        B_Wf --> B_Rep2{"7. Replay #2 Check<br/>(Bắt request thắng đua lock)"}
        B_Rep2 -- "Hit" --> B_Rep2Ret["Return Replay"]

        B_Rep2 -- "Miss" --> B_Dispute["8. Chạy Subagent: run_dispute_agent()"]

        %% Dispute Bugs Detail
        B_Dispute --> B_CancelCall["Khách yêu cầu hủy đơn<br/>Gọi execute('prepare_cancellation')"]
        B_CancelCall --> B_F04["❌ BUG F04: Tạo Proposal BẤT CHẤP Tool Result<br/>- Không kiểm tra result.eligible (đơn delivered O-102 trả eligible=False)!<br/>- Worker vẫn sinh action_proposal.cancel_order<br/>- Bot nói dối: 'Em đã mở bảng xem lại đề xuất hủy...'"]

        B_Dispute --> B_InnerTool["Gọi execute('get_order') / 'get_product'"]
        B_InnerTool --> B_F03_In["❌ BUG F03: Nuốt lỗi Hạ tầng<br/>- Application.execute() convert ApiError 5xx thành tool error dict<br/>- Dispute worker try/except Exception nuốt thành is_order_ok=False<br/>- Bot nói dối khách: 'Không tìm thấy đơn hàng'"]

        B_Dispute --> B_F05["❌ BUG F05: Stale Context lấn át Đơn mới<br/>- Ưu tiên bound_context.product_id CŨ trước<br/>- Khách đang chat O-101, nói sang O-102<br/>- Bot vẫn lấy product_id của O-101 để tra bảo hành!"]

        B_Dispute --> B_SizeCall["Khách đổi size<br/>Gọi execute('check_inventory')"]
        B_SizeCall --> B_F06["❌ BUG F06: Collapse dữ liệu & Hardcode sai<br/>- Hardcode color='Tiêu chuẩn', mặc định size='L'<br/>- stock_res.get('stock') or 0 biến None thành 0<br/>- P-101 chỉ có màu Trắng, hỏi màu Đen bị coi là hết hàng thay vì variant_not_found!"]

        B_Dispute --> B_F03_Out["❌ BUG F03 (Outer): Nuốt ngoại lệ toàn cục<br/>- except Exception ngoài cùng nuốt sạch ApiError/429/503<br/>- Gán 'Shop đã ghi nhận' và hoàn thành turn complete=True giả mạo!"]

        B_Dispute --> B_F08_Before["❌ BUG F08: Ngôn từ sai sự thật & Hổng Queue nhân viên<br/>- Bot nhận: 'Đã tạo phiếu gửi CSKH duyệt' (thực tế chưa persist, không vào queue)<br/>- UI khách: Không hề render proposal card đổi hàng<br/>- Nút Staff Duyệt: Gọi /api/staff/reply chat text nhưng nhận 'Đã tạo vận đơn, kho đã giữ hàng'!"]
    end

    %% ==========================================
    %% SUBGRAPH 2: AFTER — PR A TARGET
    %% ==========================================
    subgraph AFTER["AFTER — PR A Target (Strict Serialization, Fail-Closed Cache & Truthful Recommendations)"]
        direction TB

        A_Req["1. Khách gửi tin nhắn chat<br/>(text, request_id, conversation_id)"] --> A_Snap["2. Load Conversation Snapshot<br/>(Chuẩn hóa SQLite OperationalError -> ApiError 503 tại storage boundary)"]
        A_Snap --> A_Digest["3. Tính toán SHA256 Request Digest"]

        A_Digest --> A_Rep1{"4. Replay #1 Fast Path<br/>(Read-only, 0 Lock, 0 GPU)"}
        A_Rep1 -- "Đã commit trước đó" --> A_Rep1Ret["⚡ Trả ngay kết quả Replay cũ<br/>(Không tốn lock, không tốn quota/GPU)"]

        A_Rep1 -- "Turn mới" --> A_Lock["5. Kiểm tra agent_lock & Acquire conv_lock non-blocking<br/>(Giữ agent_lock move-only; cleanup triệt để thuộc PR B)"]
        A_Lock -- "Đang bận xử lý" --> A_429["Trả về HTTP 429: model_busy<br/>(Loser nhận 429 ngay, 0 DB commit, 0 model call)"]

        A_Lock -- "Đã giữ Lock" --> A_Rep2{"6. Replay #2 (Dưới Lock)<br/>(Bắt concurrent request vừa commit xong)"}
        A_Rep2 -- "Đã commit" --> A_Rep2Ret["Trả kết quả Replay & Release Lock"]

        A_Rep2 -- "Turn mới" --> A_Reval["7. Reload & Revalidate Snapshot (Dưới Lock)<br/>(store.conversation nạp context mới nhất từ DB)"]
        A_Reval --> A_CacheElig{"8. Điều kiện Cache Fail-Closed (F01 FIX):<br/>- Revalidated snapshot không có order/product context?<br/>- Không attachment, không deictic words?<br/>- Khớp Allowlist FAQ tĩnh (giờ mở cửa, địa chỉ)?<br/>(Query không rõ ràng / RAG / Policy -> bypass)"}

        A_CacheElig -- "Thỏa mãn (Allowlist FAQ tĩnh)" --> A_CacheLook{"9. Semantic Cache Lookup"}
        A_CacheElig -- "Không thỏa mãn / RAG / Bối cảnh động" --> A_Bypass["Bypass Cache 100%<br/>(Chuyển sang luồng Workflow)"]

        %% Cache hit serialization
        A_CacheLook -- "Hit" --> A_FinLock["✅ F02 FIX: finish_turn() DƯỚI conv_lock<br/>- Commit từ snapshot vừa revalidate (không dùng snapshot cũ)<br/>- Giải phóng conv_lock trong ExitStack callback<br/>- Không CAS conflict, không rò rỉ dữ liệu"]
        A_FinLock --> A_CacheDone["Trả kết quả Cache Hit cho khách"]

        A_CacheLook -- "Miss" --> A_Bypass

        A_Bypass --> A_ModelWf["10. Khởi tạo Workflow & Cấp Permit Model<br/>(Chỉ cấp GPU permit khi thực sự gọi model)"]
        A_ModelWf --> A_DispAgent["11. Chạy Dispute Subagent Chuẩn hóa"]

        %% Dispute Target Fixes
        A_DispAgent --> A_OrderRes["✅ F05 FIX: Phân giải Thứ tự Ưu tiên Đơn hàng<br/>- Mã đơn explicit trong tin nhắn hiện tại THẮNG TUYỆT ĐỐI<br/>- Gọi get_order(new_id) để lấy dữ liệu mới nhất<br/>- Trích xuất product_id từ chính đơn mới này"]

        A_OrderRes --> A_Taxonomy{"✅ F03 FIX: Phân loại Lỗi & Chuẩn hóa Telemetry"}

        A_Taxonomy -- "Lỗi Hạ tầng (exc.status >= 500 hoặc == 429)" --> A_Propagate["Propagate / Re-raise Error ra ngoài<br/>- Application.execute() re-raise ApiError hạ tầng<br/>- Ghi model_calls attempt, không nuốt lỗi<br/>- Client nhận đúng HTTP 503/429/500"]

        A_Taxonomy -- "Lỗi Nghiệp vụ 4xx (not_found, denied)" --> A_TruthBiz["Giải thích trung thực cho khách<br/>(Ví dụ: Đơn O-999 không thuộc tài khoản của bạn)"]

        A_Taxonomy -- "Đơn hàng hợp lệ" --> A_ActionType{"Phân loại Nghiệp vụ"}

        %% Hủy đơn (1-stage direct)
        A_ActionType -- "Yêu cầu Hủy đơn" --> A_PrepCancel["Gọi execute('prepare_cancellation')"]
        A_PrepCancel --> A_F04{"✅ F04 FIX: Kiểm tra Toàn diện Tool Result<br/>- result không chứa key error?<br/>- result.eligible is True?<br/>- result.order.id khớp chính xác mã đơn?"}
        A_F04 -- "Đủ điều kiện (Pending)" --> A_MakeProp["Tạo action_proposal & Hiển thị Dialog xác nhận"]
        A_F04 -- "Không đủ điều kiện (Delivered)" --> A_NoProp["TUYỆT ĐỐI KHÔNG TẠO PROPOSAL<br/>Giải thích trung thực: Đơn đã giao không thể hủy"]

        %% Đổi hàng / Đổi size
        A_ActionType -- "Đổi size / Đổi hàng" --> A_InvResolve["✅ F06 FIX: Xác định Biến thể Chính xác<br/>- Giữ màu từ đơn gốc nếu khách không nêu màu mới<br/>- Hỏi lại nếu mơ hồ, không tự ép 'Tiêu chuẩn' hay size 'L'"]
        A_InvResolve --> A_StockCheck["Gọi execute('check_inventory', pid, size, color)"]
        A_StockCheck --> A_StockClass{"Phân loại Trạng thái Kho"}
        A_StockClass -- "variant_not_found" --> A_VarNotFound["Báo biến thể không tồn tại trong danh mục<br/>(P-101 không có màu Đen)"]
        A_StockClass -- "stock_unknown" --> A_StockUnk["Báo tồn kho chưa xác định (catalog stock=NULL)"]
        A_StockClass -- "stock == 0" --> A_OutStock["Báo hết hàng chính xác, gợi ý tư vấn mẫu khác"]
        A_StockClass -- "stock > 0" --> A_SizeProp["✅ F08a FIX: Ngôn từ Đổi hàng Trung thực (PR A Boundary)<br/>- AI: 'Size L màu Đen còn hàng. Em đã xác định được một phương án đổi phù hợp này...' (KHÔNG nói 'đã tạo phiếu', KHÔNG nói 'xem trên màn hình')<br/>- UI Staff: Đổi nút thành 'Xác nhận đã tiếp nhận', KHÔNG tuyên bố 'Duyệt đổi thành công', giữ kho hay tạo vận đơn"]
    end

    %% Ghi chú hoãn F08b
    subgraph DEFERRED_NOTE["Ghi chú: F08b Durable Exchange Lifecycle — DEFERRED (Ngoài phạm vi Module 2.5)"]
        direction TB
        F_Note["Vòng đời 2-stage hoàn chỉnh (Khách bấm Xác nhận gửi -> Lưu DB exchange_requests -> Queue Staff Desk -> Nhân viên duyệt/từ chối transaction) được hoãn lại, yêu cầu thiết kế riêng biệt trong giai đoạn sau."]
    end

    A_SizeProp -.->|Hoãn triển khai F08b| DEFERRED_NOTE

    %% ==========================================
    %% STYLING
    %% ==========================================
    classDef bug fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c;
    classDef fix fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef fast fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef warn fill:#fff3e0,stroke:#ef6c00,stroke-width:2px,color:#e65100;
    classDef note fill:#f5f5f5,stroke:#9e9e9e,stroke-width:1px,stroke-dasharray: 4 4,color:#424242;

    class B_F01,B_F02,B_F04,B_F03_In,B_F05,B_F06,B_F03_Out,B_F08_Before bug;
    class A_FinLock,A_CacheElig,A_OrderRes,A_Taxonomy,A_F04,A_InvResolve,A_SizeProp fix;
    class A_Rep1Ret,B_RepRet fast;
    class A_429,A_Propagate,A_NoProp,A_VarNotFound,A_StockUnk warn;
    class F_Note note;
```

---

## 3. Thiết Kế Kỹ Thuật Chi Tiết Từng Tệp Mã Nguồn

### 3.1. Tệp `retailops/business/cache.py` & `retailops/business/application.py`
1. **Kiến Trúc An Toàn Cache 3 Yếu Tố (Tri-Factor Cache Safety)**:
   Để giải quyết dứt điểm lỗi rò rỉ ngữ cảnh F01 và duy trì tính nhất quán 100% giữa query filter, lookup và store:
   - **Lớp 1: Bộ Lọc Cú Pháp Truy Vấn (Query Filter - `is_cacheable_query(text)`)**:
     * Là bộ lọc thuần túy cấp cú pháp (syntax filter), kiểm tra văn bản đầu vào độc lập với context session:
       1. Độ dài tối thiểu 2 ký tự, tối đa 1.000 ký tự.
       2. Loại bỏ câu hỏi chứa mã đơn (`ORDER_PATTERN = r'\b[Oo]-\d+\b'`), mã sản phẩm (`PRODUCT_PATTERN = r'\b[Pp]-\d+\b'`), hoặc từ khóa mutation (`MUTATION_PATTERN`).
       3. Loại bỏ câu hỏi chứa đại từ chỉ định phụ thuộc ngữ cảnh (`DEICTIC_PATTERN = r'\b(nó|món này|cái này|sản phẩm này|đơn này|áo này|quần này|đây|này)\b'`).
       4. Cho phép các câu hỏi FAQ tĩnh/chung chung (tương thích 100% với `tests/test_cache_engineering.py:38-41`).
     ```python
     DEICTIC_PATTERN = re.compile(r'\b(nó|món này|cái này|sản phẩm này|đơn này|áo này|quần này|đây|này)\b', re.IGNORECASE)

     def is_cacheable_query(text: str) -> bool:
         if not isinstance(text, str):
             return False
         cleaned = text.strip()
         if len(cleaned) < 2 or len(cleaned) > 1000:
             return False
         if ORDER_PATTERN.search(cleaned) or PRODUCT_PATTERN.search(cleaned) or MUTATION_PATTERN.search(cleaned):
             return False
         if DEICTIC_PATTERN.search(cleaned):
             return False
         return True
     ```
   - **Lớp 2: Bảo Vệ Ngữ Cảnh Hội Thoại, Lịch Sử Thật & Predicate FAQ Tĩnh (Lookup Guard tại `Application.chat()`)**:
     * Không chỉ dựa vào cú pháp, bước lookup kiểm tra predicate thực thi `is_static_faq_query(text)`, snapshot và lịch sử thật từ database:
```python
# Allowlist toàn câu chuẩn hóa với neo bắt đầu/kết thúc (^...$)
STATIC_FAQ_PATTERNS = [
    # Giờ mở cửa / làm việc của shop
    re.compile(r'^(shop\s+)?(mở\s+cửa|giờ\s+làm\s+việc|hoạt\s+động)(\s+lúc)?(\s+mấy\s+giờ|\s+khi\s+nào|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    re.compile(r'^(mấy\s+giờ\s+)?(shop\s+)?(mở\s+cửa|đóng\s+cửa)$', re.IGNORECASE),
    # Địa chỉ / vị trí cửa hàng
    re.compile(r'^(địa\s+chỉ|vị\s+trí)(\s+của)?\s+(shop|cửa\s+hàng)(\s+ở\s+đâu|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    re.compile(r'^(shop|cửa\s+hàng)\s+(ở\s+đâu|nằm\s+ở\s+đâu)$', re.IGNORECASE),
    # Hotline / liên hệ chung của shop
    re.compile(r'^(số\s+điện\s+thoại|hotline|tổng\s+đài|liên\s+hệ)(\s+của)?\s+(shop|cửa\s+hàng)(\s+là\s+gì|\s+như\s+thế\s+nào)?$', re.IGNORECASE),
    # Lời chào chuẩn
    re.compile(r'^(xin\s+chào|chào\s+shop|hi\s+shop|hello\s+shop)$', re.IGNORECASE),
]

def normalize_faq_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    t = text.strip().lower()
    t = re.sub(r'[\?\.!,;:]', '', t)
    return re.sub(r'\s+', ' ', t).strip()

def is_static_faq_query(text: str) -> bool:
    norm = normalize_faq_text(text)
    if not norm:
        return False
    # Chặn câu phức hợp, liên từ nối, câu hỏi dữ liệu cá nhân, hoặc chứa từ khóa chính sách/vận chuyển
    compound_or_personal = re.compile(
        r'\b(và|hoặc|nhưng|với|của\s+tôi|của\s+em|của\s+mình|tôi|nhận\s+hàng|giao\s+hàng|phí\s+ship|vận\s+chuyển|bảo\s+hành|điều\s+kiện|chính\s+sách|quy\s+định)\b',
        re.IGNORECASE
    )
    if compound_or_personal.search(norm):
        return False
    # So khớp tuyệt đối toàn câu (fullmatch)
    return any(p.fullmatch(norm) for p in STATIC_FAQ_PATTERNS)

def is_cache_eligible_for_lookup(text: str, snapshot: dict, has_prior_turns: bool, attachment=None) -> bool:
    if attachment is not None:
        return False
    if not is_cacheable_query(text):
        return False
    # Fail-closed: Nếu lịch sử không xác nhận được là False (True hoặc None/missing/error),
    # tức phiên đã có trao đổi trước đó hoặc không thể xác minh -> BYPASS lookup 100%!
    if has_prior_turns is not False:
        return False
    # Snapshot phải là dict hợp lệ và không gắn context đơn hàng / sản phẩm
    if not isinstance(snapshot, dict) or snapshot.get('order_id') is not None or snapshot.get('product_id') is not None:
        return False
    # Fail-closed: Câu hỏi bắt buộc phải khớp predicate FAQ tĩnh chuẩn
    if not is_static_faq_query(text):
        return False
    return True
```
     * **Nguồn Dữ Liệu Lịch Sử Thật Dưới Lock**:
       - `BusinessStore.conversation(customer, cid)` ([store.py:583-590](../retailops/business/store.py#L583)) chỉ trả bản ghi bảng `conversations`, không chứa trường lịch sử các turns.
       - Bổ sung hàm kiểm tra lịch sử có thật: `has_prior_turns = self.store.has_turns(customer, cid)` (`[ADD / PLANNED]` trên `BusinessStore`: `SELECT 1 FROM agent_turns WHERE customer_id = ? AND conversation_id = ? LIMIT 1`).
       - Nếu `has_prior_turns` trả về `True` (đã có lượt trước) hoặc không xác minh được (`None`/exception), hệ thống coi là không an toàn và **BYPASS LOOKUP 100%**.
     * **Ghi nhận `eligibility_before_turn`**: Trước khi thực thi, tính toán và lưu `eligibility_before_turn = is_cache_eligible_for_lookup(text, snapshot, has_prior_turns, attachment)`. Lookup dùng giá trị này; sau đó Store tái sử dụng cùng giá trị này để quyết định ghi cache (tránh việc đếm lại turn vừa commit làm chặn lưu cache).
   - **Lớp 3: Kiểm Chứng Nguồn Gốc Phản Hồi (Response Provenance Guard tại `Application.chat()`)**:
     * **Trách nhiệm triển khai thuộc PR A**: Trong codebase hiện tại, `run_multiagent` (`retailops/workflow/graph.py:164`) không tự động trả về `tool_count` trong output mặc định, và luồng `human-support` (`graph.py:154`) nằm ngoài các vị trí cộng trace thông thường. Vì vậy, **PR A sở hữu trách nhiệm triển khai Response Provenance Counter** tại biên thực thi `Application.execute()` (đếm chính xác số lượt gọi tool thực tế, bao gồm cả read tools như `get_current_time`, `get_order`, và luồng human-support).
     * **Nguyên tắc Fail-Closed Provenance**: Tuyệt đối không giả định *"thiếu trace = 0 tool"*. Nếu trace bị thiếu, không hoàn chỉnh hoặc chưa được xác thực, hệ thống coi là không đủ điều kiện và **TỪ CHỐI LƯU CACHE**.
     * **Điều kiện Ghi Cache (Cache Store Allowed)**:
       Chỉ lưu vào `SemanticCache` khi và chỉ khi:
       1. `eligibility_before_turn is True` (bảo đảm điều kiện trước turn đã được xác thực an toàn: phiên chưa có lượt chat trước đó, snapshot không có order/product context, query là static FAQ).
       2. Lượt thực thi vừa hoàn tất xác nhận chắc chắn `tool_count == 0` và `len(tools_called) == 0` (kể cả read tools).
       3. Không truy vấn RAG (`not bound.knowledge.searches`) và không trích dẫn tài liệu (`not result.get('sources')`).
       4. Không có ràng buộc phiên bản (`not bound.versions`).
       5. Không có context động phát sinh trong turn (`snapshot.get('order_id') is None and snapshot.get('product_id') is None`).
     * **TUYỆT ĐỐI CẤM LƯU VÀO SEMANTIC CACHE** nếu:
       1. Lượt hội thoại đã gọi bất kỳ công cụ nào (`len(tools_called) > 0` hoặc `tool_count > 0`), bao gồm cả `get_current_time`, `get_order`, `search_knowledge`, hoặc tool-cache hit.
       2. Có truy vấn tri thức RAG hoặc trích dẫn nguồn tài liệu.
       3. Có ràng buộc phiên bản dữ liệu động.
       4. Ngữ cảnh hội thoại đã gắn sản phẩm hoặc đơn hàng.
       5. `eligibility_before_turn is False` (phiên có lịch sử, câu hỏi không thuộc FAQ tĩnh).
       6. Checkpoint resume hoặc luồng human handoff.

   - **Bảng Quyết Định Chung Cho Lookup / Store (Decision Matrix)**:

   | Loại câu hỏi / Tình huống | Cú pháp / Đại từ? | Đính kèm? | Context Snapshot? | Static FAQ Predicate? | Công cụ/RAG thực thi? | Điều kiện Lookup? | Điều kiện Store? |
   | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
   | **FAQ tĩnh chung** ("shop mở cửa mấy giờ", địa chỉ shop) | Hợp lệ (0 đại từ) | Không | Trống (`None`) | **TRUE (khớp allowlist)** | 0 tool (`tools == []`) | **CHO PHÉP** | **CHO PHÉP** |
   | **Chứa đại từ chỉ định** ("cái này", "món đó", "nó") | Vi phạm | Bất kỳ | Bất kỳ | Bất kỳ | Bất kỳ | **BYPASS (CẤM)** | **CẤM** |
   | **Có tệp đính kèm** (ảnh/tài liệu) | Bất kỳ | Có | Bất kỳ | Bất kỳ | Bất kỳ | **BYPASS (CẤM)** | **CẤM** |
   | **Phiên có ngữ cảnh động** (`order_id` hoặc `product_id`) | Bất kỳ | Bất kỳ | Có ID | Bất kỳ | Bất kỳ | **BYPASS (CẤM)** | **CẤM** |
   | **Tra cứu chính sách cần RAG** ("bảo hành bao lâu", phí ship) | Hợp lệ | Không | Trống | **FALSE (ngoài allowlist)** | Có RAG/Search | **BYPASS (CẤM)** | **CẤM** |
   | **Nghiệp vụ / Mutation** (hủy đơn, đổi hàng, "O-101", "P-101") | Vi phạm | Bất kỳ | Bất kỳ | Bất kỳ | Bất kỳ | **BYPASS (CẤM)** | **CẤM** |
   | **Bất kỳ lượt nào có gọi tool** (`len(tools) > 0` hoặc `tool_count > 0`) | Bất kỳ | Bất kỳ | Bất kỳ | Bất kỳ | Có tool | N/A | **CẤM LƯU 100%** |
   | **Trace thiếu / Không xác thực tool** | Bất kỳ | Bất kỳ | Bất kỳ | Bất kỳ | Không xác định | N/A | **CẤM LƯU (Fail-closed)** |

### 3.2. Tệp `retailops/business/store.py` (Chuẩn hóa Storage Boundary)
1. **Chuẩn hóa Ngoại lệ Cơ sở Dữ liệu tại Storage Boundary**:
   - Do `Application.chat()` thực hiện các thao tác preflight (nạp snapshot, Replay #1, catalog rev) trước khối `try` chính, việc chuẩn hóa ngoại lệ SQLite phải được bọc tại boundary `BusinessStore.connection` hoặc một boundary bao trùm toàn bộ preflight:
     ```python
     # Trong BusinessStore.connection
     except sqlite3.OperationalError as exc:
         db.rollback()
         raise ApiError(503, 'database_unavailable', 'Cơ sở dữ liệu tạm thời gián đoạn. Vui lòng thử lại sau ít phút.') from exc
     ```
   - Đảm bảo mọi lỗi rớt kết nối hoặc lock database ở bất kỳ chặng nào (preflight hay runtime) đều trở thành HTTP 503 chuẩn xác.

### 3.3. Tệp `retailops/business/application.py`
1. **Hợp đồng Tuần tự hóa, Snapshot Revalidation & Replay 2 Chặng cho AI/Cache Turns**:
   - **Chặng 1 (Replay #1 Fast Path)**: Chạy `store.replay(customer, cid, request_id, digest)` ngay ở đầu hàm `chat()` (0 lock wait, 0 GPU permit). Nếu đã commit trước đó $\rightarrow$ Trả kết quả ngay lập tức.
   - **Chặng 2 (Acquire Lock non-blocking & agent_lock)**:
     - Giữ nguyên kiểm tra `self.agent_lock` (chỉ di chuyển vị trí nếu cần bảo vệ cache serialization; việc dọn dẹp và xóa bỏ hoàn toàn `agent_lock` vẫn thuộc sở hữu của PR B).
     - Lấy `conv_lock = self.inference_gate.get_conversation_lock(conv_key)`. Gọi `conv_lock.acquire(blocking=False)`.
     - Nếu thất bại $\rightarrow$ Ném ngay `ApiError(429, 'model_busy')`. Request thua lock nhận 429 ngay, không commit DB, không tốn inference.
     - Đăng ký `conv_lock.release` qua `ExitStack`.
   - **Chặng 3 (Replay #2, Snapshot Revalidation & History Verification Under Lock)**:
     - Kiểm tra lại `store.replay` dưới lock để bắt kịp request thắng đua vừa commit xong.
     - **Reload & Revalidate Conversation Snapshot**: Gọi lại `snapshot = self.store.conversation(customer, cid)` ngay dưới `conv_lock` để lấy bản chụp ngữ cảnh mới nhất từ DB. Nếu request trước đó vừa thắng đua và cập nhật context (`order_id` / `product_id`), bản chụp mới sẽ phản ánh ngay lập tức.
     - **Nối Dữ Liệu Lịch Sử Thật (History Verification Under Lock)**: Gọi `has_prior_turns = self.store.has_turns(customer, cid)` (`[ADD / PLANNED]` trên `BusinessStore`: `SELECT 1 FROM agent_turns WHERE customer_id = ? AND conversation_id = ? LIMIT 1`). Nếu hàm trả về `True` hoặc gặp lỗi/không xác minh được (`has_prior_turns is not False`), hệ thống đánh dấu phiên đã có lịch sử.
     - **Xác định Tính Đủ Điều Kiện Trước Turn (`eligibility_before_turn`)**:
       `eligibility_before_turn = is_cache_eligible_for_lookup(text, snapshot, has_prior_turns, attachment)`
       Giá trị boolean này được ghi nhận cố định cho toàn bộ lượt chat và được tái sử dụng khi quyết định lưu cache tại Chặng 5 (không tính lại sau `finish_turn`).
     - **Xử lý Retry sau Turn Dang Dở (Aborted Turn / Checkpoint Replay Contract)**:
       * Nếu lượt trước bị gián đoạn (do lock race, lỗi DB, hoặc crash) và client gửi retry với cùng `request_id`:
       * Nếu `conversation.revision` hoặc ngữ cảnh đã thay đổi so với thời điểm khởi tạo ban đầu: Từ chối với HTTP 409 `conversation_changed` để client nạp lại phiên mới; **tuyệt đối không âm thầm thay đổi seed/checkpoint** làm sai lệch tính tất định của replay.
   - **Chặng 4 (Cache Lookup & Commit Under Lock)**:
     - Kiểm tra `eligibility_before_turn`: Chỉ thực hiện lookup khi `eligibility_before_turn is True` (bảo đảm snapshot không có attachment, không có order/product context, lịch sử rỗng đã xác thực, và khớp predicate FAQ tĩnh). Mọi trường hợp còn lại bypass lookup 100%.
     - Khi cache hit, kiểm tra tính hợp lệ và gọi `self.store.finish_turn(...)` **bên trong phạm vi bảo vệ của `conv_lock` với snapshot mới nhất**.
   - **Chặng 5 (Workflow Execution & Provenance Store Decision)**:
     - Đi tiếp vào workflow multi-agent, chỉ xin inference permit khi thực sự gọi model.
     - Tại biên kết thúc turn: Quyết định lưu `SemanticCache` tuân thủ nghiêm ngặt điều kiện `eligibility_before_turn is True` kết hợp Response Provenance Guard (0 tool, 0 RAG, 0 source).
2. **Sửa `Application.execute()` — Chặn nuốt lỗi hạ tầng (F03 Tool Contract)**:
   - Sửa chính xác theo thuộc tính `exc.status` (HTTP status number int) thay vì so sánh nhầm `exc.code`:
     ```python
     try:
         res = bound(name, arguments)
     except ApiError as exc:
         # Ngoại lệ hạ tầng (HTTP status == 429 hoặc >= 500) BẮT BUỘC re-raise để fail turn
         if exc.status == 429 or exc.status >= 500:
             raise
         # Chỉ các lỗi nghiệp vụ 4xx (404 not found, 403 denied) mới chuyển thành dict tool result
         if name in ('get_order', 'get_context', 'track_shipment', 'prepare_cancellation'):
             bound.context = {'order_id': None, 'product_id': None}
             bound.cancel_order = None
             bound.shipment = None
         return {'error': exc.code, 'message': exc.message}
     ```
### 3.4. Tệp `retailops/workflow/subagents/dispute_agent.py`
1. **Phân loại Lỗi Hạ tầng vs Nghiệp vụ (F03 Taxonomy)**:
   - Xóa bỏ các khối broad `except Exception` nuốt lỗi quanh `get_order` và toàn worker.
   - Ngoại lệ hạ tầng (`ApiError` có `exc.status == 429` hoặc `exc.status >= 500`): Bắt buộc **re-raise** ra ngoài để fail turn và trả mã HTTP tương ứng.
   - Lỗi nghiệp vụ (`order_not_found`, `permission_denied`): Trả lời trung thực lý do từ chối hỗ trợ.
2. **Chuẩn hóa Telemetry Tối thiểu (Không kéo PR B vào PR A)**:
   - Tăng `trace['model_calls']` TRƯỚC khi gọi `gateway.chat(...)` để ghi nhận lượt attempt.
   - Tăng `trace['model_responses']` SAU KHI nhận phản hồi hợp lệ từ model.
3. **Kiểm tra Toàn diện Kết quả Tool Hủy đơn (F04)**:
   - Hợp đồng thực tế của `retailops_tools.py`: Khi đơn ở trạng thái `delivered`, tool trả về `{"order": order, "eligible": False, "transaction_performed": False, ...}` (không có key `error`).
   - Guard condition:
     ```python
     is_eligible = (
         isinstance(result, dict)
         and not result.get("error")
         and result.get("eligible") is True
         and result.get("order", {}).get("id") == chosen_oid
     )
     ```
   - Chỉ tạo `action_proposal` khi `is_eligible is True`. Nếu `False`, phản hồi trung thực: *"Đơn hàng O-xxx hiện ở trạng thái 'delivered', shop không thể hỗ trợ hủy đơn..."* (Không mở dialog xác nhận hủy).
4. **Thứ tự Ưu tiên Đơn hàng Mới (F05 Precedence)**:
   - `Mã đơn explicit trong tin nhắn` $\rightarrow$ `Dữ liệu order từ get_order(new_id)` $\rightarrow$ `product_id trích xuất từ đơn mới này` $\rightarrow$ Chỉ fallback về `bound_context.product_id` cũ nếu tiếp tục xử lý cùng một đơn hàng cũ.
5. **Ngữ nghĩa Biến thể Chính xác (F06 Exact Inventory)**:
   - Trích xuất màu và size từ yêu cầu hoặc giữ nguyên biến thể đơn gốc nếu khách muốn đổi size cùng màu. Hỏi lại khách nếu mơ hồ, không tự ý gán size L hay color="Tiêu chuẩn".
   - Phân biệt rõ 4 trạng thái:
     1. `variant_not_found`: Biến thể không tồn tại trong catalog (ví dụ: P-101 màu Đen).
     2. `stock_unknown`: Catalog có sản phẩm nhưng trường `stock` là `None`/chưa xác định (dữ liệu thiếu, khác với lỗi DB 503).
     3. `stock == 0`: Hết hàng trong kho.
     4. `stock > 0`: Còn hàng sẵn sàng đổi.
6. **Ranh giới Ngôn từ Đổi hàng Trung thực (F08a Truthful Wording)**:
   - Sửa câu chữ thành: *"Dạ em đã kiểm tra kho cho đơn {oid}: Size {target_size} hiện còn {stock_qty} sản phẩm. Em đã xác định được một phương án đổi phù hợp này; nếu anh/chị muốn tiếp tục, hệ thống cần ghi nhận yêu cầu để CSKH xem xét hỗ trợ ạ."*
   - Tuyệt đối KHÔNG nói: *"Em đã tạo phiếu đề xuất"*, *"xem đề xuất trên màn hình"*, hay *"đã gửi chuyên viên CSKH duyệt"*.

### 3.5. Tệp `web/app.js` và `web/index.html`
1. **Sửa Ngôn từ Giao diện Nút Bấm và Alert của Nhân viên (F08a)**:
   - Trong `web/index.html`:
     - Sửa nút `btn-approve-exchange-1to1`: Đổi nhãn từ `✅ Duyệt Đổi Mới 1-1` $\rightarrow$ `📩 Xác nhận tiếp nhận Đổi 1-1`.
     - Sửa nút `btn-approve-exchange-size`: Đổi nhãn từ `✅ Duyệt Đổi Size 2 Chiều` $\rightarrow$ `📩 Xác nhận tiếp nhận Đổi Size`.
   - Trong `web/app.js`:
     - Trong `approveExchange1to1()` và `approveExchangeSize()`: Do nút này chỉ gửi tin nhắn qua `/api/staff/reply`, sửa câu chat gửi cho khách thành:
       *"Dạ chuyên viên CSKH đã tiếp nhận thông tin yêu cầu đổi hàng của đơn {oid}. Shop sẽ liên hệ xác nhận chi tiết hỗ trợ mình sớm nhất ạ."*
     - Sửa alert thông báo: Đổi từ `Đã duyệt thành công! Kho tổng đã ghi nhận giữ hàng` $\rightarrow$ `Đã gửi phản hồi tiếp nhận cho khách hàng qua chat.`
     - Xóa bỏ các tuyên bố sai sự thật: *"Hệ thống đã kết nối bưu cục tạo vận đơn thu hồi..."* và *"Kho tổng đã xuất giữ sản phẩm..."*.

### 3.6. Tệp `retailops_tools.py` — An Toàn Tìm Kiếm Sản Phẩm (F11 Tool Safety)
1. **Xử lý An toàn Khi Duyệt Catalog (`category=None` và `aliases`)**:
   - Trong `search_products`:
     ```python
     query = normalize(args['query']).strip()
     products = []
     for p in self.catalog.products.values():
         cat = p.get('category') or ''
         aliases = [str(a) for a in p.get('aliases', []) if a]
         searchable = normalize(' '.join([str(p.get('id', '')), str(p.get('name', '')), cat] + aliases))
         if query in searchable:
             products.append(p)
     ```
   - Chống văng ngoại lệ `TypeError: sequence item 2: expected str instance, NoneType found` khi catalog chứa sản phẩm tạo từ Manager thiếu danh mục.

---

## 4. Ma Trận Kiểm Thử Hồi Quy (Test Regression Matrix — 30 Scenarios)

| Finding | Kịch bản Kiểm thử (Scenario) | Điều kiện Đầu vào / Kích hoạt | Kỳ vọng Kết quả (Expected Output) | Trạng thái Commit DB? | Tiêu tốn Model Call? |
|---|---|---|---|:---:|:---:|
| **F01** | Cross-product context cache leak | Hội thoại focus `P-102` hỏi "áo này bảo hành bao lâu" | Bypass cache 100% (không dùng cache của P-101); gọi model tra cứu đúng P-102 | Có (sau workflow) | Có (`calls=1, resp=1`) |
| **F01** | Deictic / Context-dependent query | Query chứa "món này", "cái này" | Bypass cache 100% | Có | Có (`calls=1, resp=1`) |
| **F01** | True context-free static FAQ hit | Hội thoại mới KHÔNG có `order_id`/`product_id` hỏi "shop mở cửa mấy giờ" | Cache hit thành công; trả lời FAQ tĩnh | Có (`finish_turn` dưới lock) | **Không (0 call)** |
| **F01** | Policy / Shipping / Personal / Compound query safety | Query chính sách bảo hành/phí ship, câu hỏi cá nhân ("địa chỉ nhận hàng của tôi là gì?", "số điện thoại của tôi là gì?"), hoặc câu ghép hỗn hợp ("shop mở cửa mấy giờ và phí ship bao nhiêu?") | Bị chặn bởi `is_static_faq_query` fullmatch -> `is_cache_eligible_for_lookup` trả False -> bypass cache lookup 100%; Response Provenance Guard cấm ghi cache | Có | Có (`calls=1, resp=1`) |
| **F01** | Tool execution provenance guard | Turn hội thoại có gọi bất kỳ tool nào (ví dụ `get_current_time` hoặc read tool) | TUYỆT ĐỐI KHÔNG ghi vào Semantic Cache (`len(tools) > 0` hoặc `tool_count > 0` tước quyền cache) | Có (sau workflow) | Có (`calls=1, resp=1`) |
| **F01** | Missing / Unverified trace guard | Lượt thực thi thiếu trường trace hoặc không xác thực được tool | Nguyên tắc Fail-closed: Coi là unverified -> CẤM ghi Semantic Cache | Có | Có |
| **F02** | Aborted turn retry with context change | Retry request_id cũ sau khi turn dang dở nhưng revision/context DB đã đổi | Từ chối với HTTP 409 `conversation_changed`, không ghi đè seed/checkpoint cũ | Không commit | Không (0 call) |
| **F02** | Same `request_id` replay | Gửi lại cùng `request_id` và cùng `digest` sau khi turn đã commit | Replay #1 hit trả kết quả ngay tức thì; không acquire lock | Không đổi | **Không (0 call)** |
| **F02** | Different `request_id` race | Hai request khác `request_id` gửi đồng thời trên cùng conversation | Request A thắng lock thực thi; Request B nhận **HTTP 429 `model_busy` ngay** | Request A: Có<br/>Request B: Không | Request A: 1 call<br/>Request B: 0 call |
| **F02** | Cache-hit vs Chat race | 1 request cache-hit đua với 1 chat request cùng conversation | Request thắng giữ lock thực thi; request thua nhận **HTTP 429** | 1 turn commit | 0 hoặc 1 call |
| **F02** | Lock release after fatal failure | Request bị lỗi 500 hoặc ngoại lệ giữa chừng khi đang giữ lock | `conv_lock` bắt buộc được release trong ExitStack; request tiếp theo chạy bình thường | Không commit lỗi | `calls=0, resp=0` (nếu preflight) hoặc `calls=1, resp=0` (nếu gateway) |
| **F02** | Snapshot revalidation under lock | Request A thắng lock cập nhật `order_id='O-101'`; Request B chờ sau lock | Khi Request B vào lock, reload snapshot $\rightarrow$ thấy `order_id` $\rightarrow$ bypass cache, không commit snapshot cũ | Có | Có (`calls=1, resp=1`) |
| **F03** | Infrastructure error in execute() | `bound('get_order')` ném `ApiError(503)` | `execute()` re-raise ra ngoài; KHÔNG nuốt thành dict error | Không commit | `calls=1, resp=1` (tool chạy sau model) |
| **F03** | DB Outage during preflight | Mock DB raise `sqlite3.OperationalError` tại storage boundary | Chuẩn hóa / Re-raise `ApiError(503, 'database_unavailable')` ra ngoài | Không commit | `calls=0, resp=0` (chưa gọi model) |
| **F03** | Model Overload 429 | Gateway trả về 429 trước response | Propagate HTTP 429 ra client; KHÔNG nuốt thành "shop đã ghi nhận" | Không commit | `calls=1, resp=0` |
| **F03** | Business not found | Khách nhập mã đơn không tồn tại (`O-999`) | Trả lời trung thực: "không tìm thấy đơn O-999 trong hệ thống" | Có | Có (`calls=1, resp=1`) |
| **F04** | Cancellation on Delivered order (`O-102`) | Khách yêu cầu hủy đơn đã giao `O-102` | Tool trả `eligible=False` $\rightarrow$ KHÔNG tạo proposal; giải thích đơn đã giao không thể hủy | Có | Có (`calls=1, resp=1`) |
| **F04** | Cancellation on Pending order (`O-101`) | Khách yêu cầu hủy đơn đang chờ `O-101` | Tool trả `eligible=True` $\rightarrow$ Tạo `action_proposal` hợp lệ | Có | Có (`calls=1, resp=1`) |
| **F04** | Cancellation order ID mismatch | Tool trả về mã đơn không khớp với tin nhắn khách gửi | KHÔNG tạo `action_proposal` | Có | Có (`calls=1, resp=1`) |
| **F05** | New explicit order vs Stale focus | Đang focus `O-101` (`P-101`), khách chat: "Đơn O-102 bị bung chỉ" | Gọi `get_order(O-102)` và `get_product(P-102)` (assert gọi đúng P-102) | Có | Có (`calls=1, resp=1`) |
| **F06** | Variant not found | Khách muốn đổi `P-101` sang size L màu Đen | Trả về `variant_not_found` (vì P-101 chỉ có màu Trắng); hướng dẫn chọn màu có sẵn | Có | Có (`calls=1, resp=1`) |
| **F06** | Catalog stock unknown | Khách đổi sản phẩm có `stock = NULL` trong catalog | Trả về `stock_unknown` trung thực, không đồng nhất với lỗi 503 | Có | Có (`calls=1, resp=1`) |
| **F06** | Variant out of stock | Khách đổi sang biến thể có thật nhưng tồn kho bằng 0 | Trả về thông báo hết hàng chính xác (`stock == 0`), đề xuất tư vấn | Có | Có (`calls=1, resp=1`) |
| **F06** | Variant in stock | Khách đổi sang biến thể có hàng (`stock > 0`) | Thông báo còn hàng và xác định phương án đổi trung thực | Có | Có (`calls=1, resp=1`) |
| **F06** | Missing size / color clarification | Khách chỉ chat "tôi muốn đổi size" | Hỏi lại khách cụ thể size và màu; KHÔNG tự ép size L hay màu "Tiêu chuẩn" | Có | Có (`calls=1, resp=1`) |
| **F08a-1** | Exchange valid option AI wording | AI tìm thấy size còn hàng (`stock > 0`) | Bot nói trung thực "đã xác định được phương án"; KHÔNG nói "đã tạo phiếu", KHÔNG nói "đã gửi chuyên viên CSKH duyệt" | Có | Có (`calls=1, resp=1`) |
| **F08a-2** | Customer UI rendering check | API trả về exchange option | Khách không thấy card xác nhận trên màn hình $\rightarrow$ Bot KHÔNG bảo khách "xem đề xuất trên màn hình" | Có | Có (`calls=1, resp=1`) |
| **F08a-3** | Staff button simulation wording | Nhân viên bấm Xác nhận tiếp nhận trên Staff Desk | Gửi phản hồi tiếp nhận CSKH; KHÔNG tuyên bố duyệt thành công, tạo vận đơn hay giữ kho | Có | Không (chat text) |
| **F08a-4** | No automatic queue insertion | AI tìm thấy phương án đổi hàng | Khẳng định `conversation_feedback` không bị chèn bản ghi rác khi chưa có human handoff | Có | Có (`calls=1, resp=1`) |
| **F11** | Null category in catalog | Catalog chứa sản phẩm `P-999` có `category=None`, gọi `search_products` | Tìm kiếm an toàn, không ném `TypeError`, trả về kết quả tìm kiếm bình thường | Không (read tool) | Có (`calls=1, resp=1`) |

---

## 5. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

1. **Test Suite PR A PASS 100%**: File `tests/test_pr_a_correctness.py` bao phủ toàn bộ 30 kịch bản ma trận kiểm thử F01–F06, F08a và F11 đạt kết quả PASS (`[CHƯA KIỂM CHỨNG / PENDING TEST]`, cần tạo test suite này trong PR A).
2. **Không phá vỡ Regression**: Toàn bộ các test suite hiện hữu (`test_audit_remediation.py`, `test_manager_crud.py`, `test_conversation.py`, `test_system_foundation.py`) tiếp tục PASS.
3. **Docs Contract PASS**: Chạy `python scripts/check_docs_contract.py` đạt 4/4 cổng kiểm định toàn vẹn.
4. **Cô lập Ngữ cảnh Triệt để**: Không có hiện tượng rò rỉ dữ liệu bảo hành/sản phẩm qua Semantic Cache; query có context động hoặc câu hỏi cần RAG trích xuất bị bypass cache; turn gọi bất kỳ tool nào (`tools` không rỗng hoặc `tool_count > 0`, kể cả `get_current_time`) bị tước quyền ghi cache.
5. **Serialization & Revalidation Đúng Đắn**: Toàn bộ các turn AI/cache trên route `/api/chat` phải được commit an toàn bên dưới `conv_lock`; dưới lock bắt buộc revalidate snapshot ngữ cảnh từ database trước khi accept cache hit; request thua lock nhận HTTP 429 ngay lập tức.
6. **Trung thực Vận hành**: Lỗi hạ tầng trong tool execution không bị nuốt; đề xuất hủy chỉ tạo khi đủ điều kiện; ngôn từ đổi hàng không ngộ nhận trạng thái backend; nút Staff Desk không tuyên bố duyệt giao dịch ảo.
7. **Tool Search Safety**: Sản phẩm có `category=None` không gây lỗi `TypeError` trong `search_products`.
8. **Bảo Vệ Benchmark Đóng Băng**: Toàn bộ kịch bản kiểm thử mới của PR A tuân thủ nguyên tắc không can thiệp, không biến đổi và không nới lỏng bộ 250 kịch bản Master Benchmark (Frozen Baseline) dùng cho đánh giá thực nghiệm Luận văn.

---

## 6. Trình Tự Thực Thi

1. **Bước 1**: Tạo file kiểm thử `tests/test_pr_a_correctness.py` chứa các kịch bản ma trận kiểm thử (Red baseline).
2. **Bước 2**: Chỉnh sửa [`retailops/business/store.py`](../retailops/business/store.py) (storage boundary normalization), [`retailops/business/cache.py`](../retailops/business/cache.py), [`retailops_tools.py`](../retailops_tools.py) (F11 safe category search) và [`retailops/business/application.py`](../retailops/business/application.py) để giải quyết F01, F02, F03, F11.
3. **Bước 3**: Chỉnh sửa [`retailops/workflow/subagents/dispute_agent.py`](../retailops/workflow/subagents/dispute_agent.py), [`web/index.html`](../web/index.html) và [`web/app.js`](../web/app.js) để giải quyết F03 (worker level), F04, F05, F06, F08a.
4. **Bước 4**: Chạy test `tests/test_pr_a_correctness.py` xác nhận chuyển sang Green.
5. **Bước 5**: Chạy toàn bộ regression test suite và chạy kiểm tra hợp đồng tài liệu `check_docs_contract.py`.
