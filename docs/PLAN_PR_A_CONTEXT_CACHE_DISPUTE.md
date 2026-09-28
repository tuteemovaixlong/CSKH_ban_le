# KẾ HOẠCH TRIỂN KHAI PR A: CONTEXT, CACHE & DISPUTE CORRECTNESS

> **Mã kế hoạch:** `PLAN_PR_A_CONTEXT_CACHE_DISPUTE`  
> **Trạng thái:** ACTIVE IMPLEMENTATION PLAN  
> **Phiên bản:** 1.0 (2026-09-28)  
> **Audit basis / Documentation baseline reviewed:** `b93eb5a`  
> **Thuộc phân hệ:** Module 2.5 — System Hardening & Quality Gate  
> **Mục tiêu:** Khắc phục dứt điểm 6 lỗi logic trọng yếu (F01 – F06) liên quan đến rò rỉ ngữ cảnh cache, vi phạm serialization phiên chat, nuốt lỗi hạ tầng và đề xuất không trung thực trong Dispute worker.  
> **Tài liệu tham chiếu:** [PLAN_MODULE_2_5_HARDENING_VERIFICATION.md](PLAN_MODULE_2_5_HARDENING_VERIFICATION.md) · [PLAN_ROADMAP_INDEX.md](PLAN_ROADMAP_INDEX.md)

---

## 1. Danh Mục Lỗi & Bằng Chứng Tái Hiện (Root Cause Analysis)

| Mã | Tên Lỗi | Vị Trí Code Nguồn | Nguyên Nhân Kỹ Thuật Gốc | Hậu Quả Vận Hành |
| :---: | :--- | :--- | :--- | :--- |
| **F01** | Cache trả bảo hành của sản phẩm khác | `retailops/business/cache.py:22-38`<br/>`retailops/business/application.py:296-300` | `is_cacheable_query(text)` chỉ regex tìm `P-\d+` và `O-\d+`. Câu hỏi gián tiếp *"Món này bảo hành bao lâu?"* được coi là cacheable. Điều kiện lưu dòng 298 chỉ kiểm tra thiếu `order_id`, bỏ qua `product_id`. | Phiên chat P-603 hỏi bảo hành 180 ngày; phiên chat sau hỏi P-602 (vốn 90 ngày) nhận nhầm 180 ngày từ cache. Mất trích dẫn nguồn `sources`. |
| **F02** | Cache-hit ghi turn ngoài `conv_lock` | `retailops/business/application.py:129-178` | Tại dòng 166, cache-hit gọi `self.store.finish_turn()` ghi vào DB trước khi `conv_lock.acquire()` được gọi ở dòng 178. | Nếu cùng một phiên chat gửi tin dồn dập, request cache-hit sẽ ghi turn song song, có thể gây xung đột revision hoặc ghi đè lịch sử. |
| **F03** | Dispute nuốt lỗi hạ tầng (429/503) | `retailops/workflow/subagents/dispute_agent.py:241-255` | Khối `except Exception as exc:` bắt mọi ngoại lệ, log warning rồi trả về câu xã giao *"Dạ shop đã ghi nhận..."* với `complete=True`. | Khi vLLM sập (503) hoặc hàng đợi quá tải (429), worker giả vờ như đã xong, client không nhận được mã lỗi để retry, mất telemetry sự cố. |
| **F04** | Tạo proposal hủy cho đơn delivered | `retailops/workflow/subagents/dispute_agent.py:82-91,232-237` | Dòng 82 chỉ kiểm tra `if name == "prepare_cancellation" and extracted_oid:`, không kiểm tra kết quả `result.get('eligible')`. | Với đơn đã giao `O-102`, dù tool báo `eligible=False`, worker vẫn tạo proposal hủy và hướng dẫn khách bấm *"Xác nhận hủy"*. |
| **F05** | Đổi đơn mới dùng product_id của đơn cũ | `retailops/workflow/subagents/dispute_agent.py:120-127` | Dòng 120 ưu tiên `pid = bound_context.get("product_id") or bound_obj.get("product_id")` trước khi đọc sản phẩm từ đơn mới. | Đang xem đơn O-101 (áo P-101), khách nói *"Đơn O-102 bị rách"*, worker đọc đơn O-102 nhưng lại tra cứu bảo hành của áo P-101. |
| **F06** | Đổi size bỏ qua màu & hardcode size L | `retailops/workflow/subagents/dispute_agent.py:196-204` | Dòng 196 thiếu size tự gán `"L"`. Dòng 200 hardcode `color="Tiêu chuẩn"` khiến store cộng dồn tồn kho tất cả các màu. | Khách xin đổi size L màu Đen (hết hàng), worker cộng kho màu Trắng/Xanh rồi báo còn 8 sản phẩm sẵn sàng đổi. |

---

## 2. Thiết Kế Kỹ Thuật Chi Tiết Từng Tệp Mã Nguồn

### 2.1. Tệp `retailops/business/cache.py`
1. **Nâng cấp hàm kiểm tra điều kiện cache `is_cacheable_query`**:
   - Mở rộng signature nhận thêm tham số ngữ cảnh: `is_cacheable_query(text: str, context: Optional[dict] = None) -> bool`.
   - Nếu `context` được truyền vào và có chứa bất kỳ trường định danh nào (`product_id`, `order_id`), hàm **bắt buộc trả về `False`**.
   - Bổ sung nhận diện các từ khóa chỉ định ngữ cảnh gián tiếp (Deictic words): *"món này", "cái này", "sản phẩm này", "đơn này", "áo này", "quần này", "nó"* $\implies$ Không bao giờ được coi là câu hỏi FAQ chung nếu thiếu ngữ cảnh độc lập.
2. **Bảo toàn trích dẫn nguồn (Provenance) trong `SemanticCache`**:
   - Khi `store(text, answer, action, sources=None)`: Lưu thêm mảng `sources` của câu trả lời.
   - Khi `lookup(query_text)`: Trả về dict chứa cả `sources` (dạng `KB:[a-f0-9]{24}`) để caller khôi phục trích dẫn hợp lệ.

### 2.2. Tệp `retailops/business/application.py`
1. **Đưa toàn bộ luồng Replay và Cache vào trong phạm vi `conv_lock`**:
   - Di chuyển việc lấy khóa phiên `conv_lock = self.inference_gate.get_conversation_lock(conv_key)` lên **trước** bước kiểm tra Replay và Semantic Cache.
   - Luồng thực thi chuẩn:
     ```python
     conv_key = f"{customer}:{snapshot['id']}"
     conv_lock = self.inference_gate.get_conversation_lock(conv_key)
     if not conv_lock.acquire(blocking=False):
         self.overload_429_count += 1
         raise ApiError(429, 'model_busy', 'Cuộc trò chuyện này đang xử lý một yêu cầu khác. Bạn thử lại sau nhé.')
     
     stack = ExitStack()
     stack.callback(conv_lock.release)
     try:
         # 1. Kiểm tra Replay (idempotency)
         replay = self.store.replay(customer, snapshot['id'], request_id, digest)
         if replay:
             return replay
         
         # 2. Kiểm tra Semantic Cache (chỉ chạy khi KHÔNG có product/order context)
         has_context = bool(snapshot.get('order_id') or snapshot.get('product_id'))
         if not has_context and is_cacheable_query(text):
             cached = self.semantic_cache.lookup(text)
             if cached:
                 # Ghi turn an toàn bên trong conv_lock
                 ...
                 return cached_result
         
         # 3. Chạy Multi-Agent Workflow...
     ```
2. **Chặn lưu Cache khi phiên có ngữ cảnh sản phẩm**:
   - Tại dòng 296–300, siết chặt điều kiện lưu cache sau khi kết thúc turn:
     ```python
     is_context_free = not bound.context.get('product_id') and not bound.context.get('order_id') and not snapshot.get('product_id') and not snapshot.get('order_id')
     if (not attachment and result['source'] == 'llm_agent' 
             and is_context_free and is_cacheable_query(text) 
             and result.get('action') == 'reply'):
         self.semantic_cache.store(text, answer['message'], action=result['action'], sources=result.get('sources'))
     ```

### 2.3. Tệp `retailops/workflow/subagents/dispute_agent.py`
1. **Phân loại và re-raise lỗi hạ tầng (F03)**:
   - Sửa khối ngoại lệ cuối hàm:
     ```python
     except ApiError:
         raise  # Bắt buộc ném 429, 503, 504 ra ngoài application
     except Exception as exc:
         import logging
         logging.getLogger("retailops.dispute_agent").warning("Dispute agent parse fallback: %s", exc)
         final_content = "Dạ shop đã ghi nhận phản hồi của anh/chị và sẽ ưu tiên kiểm tra xử lý ngay ạ!"
     ```
   - Trong khối gọi `gateway.chat`, nếu gateway ném lỗi thì không tăng `trace["model_calls"]` như một lượt thành công rỗng.
2. **Kiểm tra cờ `eligible` khi chuẩn bị hủy đơn (F04)**:
   - Tại dòng 82:
     ```python
     if name == "prepare_cancellation" and extracted_oid:
         chosen_oid = args.get("order_id") or extracted_oid
         if isinstance(chosen_oid, str) and chosen_oid.upper().startswith('O0'):
             chosen_oid = 'O-' + chosen_oid[2:]
         
         is_eligible = isinstance(result, dict) and bool(result.get("eligible"))
         if is_eligible:
             action_proposal = {
                 "action": "cancel_order",
                 "order_id": chosen_oid,
                 "reason": args.get("reason", "Khách yêu cầu hủy"),
                 "status": "pending_user_confirmation"
             }
         else:
             action_proposal = None
             curr_status = result.get("order", {}).get("status") if isinstance(result, dict) else "không hợp lệ"
             cancellation_rejected_reason = curr_status
     ```
   - Tại dòng 232: Nếu tool hủy trả về không đủ điều kiện (ví dụ đơn đã giao `delivered`), worker phản hồi trung thực:
     *"Dạ đơn hàng {oid} hiện ở trạng thái '{curr_status}', nên shop không thể hỗ trợ hủy đơn được nữa..."* — Tuyệt đối không sinh proposal và không thông báo mở bảng hủy.
3. **Ưu tiên sản phẩm của đơn hàng mới (F05)**:
   - Tại dòng 120: Khi `extracted_oid` được xác định từ câu hỏi của khách, nếu `extracted_oid` khác với `bound_context.order_id` cũ:
     ```python
     pid = None
     if isinstance(order_data, dict):
         pid = order_data.get("product_id")
         if not pid:
             items = order_data.get("items", [])
             if items and isinstance(items, list) and isinstance(items[0], dict):
                 pid = items[0].get("product_id")
     # Chỉ fallback về bound_context cũ khi KHÔNG tìm thấy pid từ đơn hàng mới
     if not pid and extracted_oid == bound_oid:
         pid = bound_context.get("product_id")
     ```
4. **Trích xuất chính xác màu sắc & kích thước khi đổi size (F06)**:
   - Trích xuất màu từ tin nhắn của khách qua danh mục màu chuẩn (`Đen`, `Trắng`, `Xanh`, `Nâu`, `Xám`...).
   - Nếu khách không đề cập màu: Tra cứu màu gốc của sản phẩm trong đơn hàng `order_data`.
   - Nếu vẫn không xác định được màu hoặc size: **Không tự ý gán mặc định size L hay color="Tiêu chuẩn"**; phản hồi yêu cầu khách làm rõ:
     *"Dạ anh/chị muốn đổi sang size và màu sắc nào ạ? Shop hiện có các màu [Trắng, Đen] để mình chọn nhé ạ!"*
   - Gọi `check_inventory(product_id=pid, size=target_size, color=target_color)`. Phân biệt rõ:
     - `variant_not_found`: Màu hoặc size không tồn tại trong danh mục.
     - `stock == 0`: Hết hàng trong kho.
     - `stock > 0`: Còn hàng sẵn sàng đổi.

---

## 3. Bộ Kịch Bản Kiểm Thử Hồi Quy Mới (Test Suite)

Tạo tệp kiểm thử chuyên biệt: `tests/test_pr_a_correctness.py` gồm 6 test cases chuẩn:

```python
# tests/test_pr_a_correctness.py

def test_f01_cache_does_not_leak_cross_product_warranty():
    """Hội thoại A hỏi P-603 -> 180 ngày. Hội thoại B focus P-602 hỏi cùng câu -> phải trả 90 ngày."""

def test_f02_cache_hit_under_conv_lock():
    """Request cache-hit khi conv_lock đang bị giữ phải bị chặn với HTTP 429 hoặc tuần tự hóa an toàn."""

def test_f03_dispute_propagates_apierror_429_and_503():
    """Khi gateway ném ApiError(429) hoặc ApiError(503), dispute worker phải re-raise, không trả complete=True."""

def test_f04_dispute_rejects_cancellation_for_delivered_order():
    """Đơn O-102 (delivered) gọi prepare_cancellation trả eligible=False -> không được tạo proposal hủy."""

def test_f05_dispute_respects_new_order_product_context():
    """Focus O-101/P-101, khách khiếu nại đơn O-102/P-102 -> worker phải đọc bảo hành của P-102, không lấy P-101."""

def test_f06_size_exchange_respects_color_filter():
    """Yêu cầu đổi sang size L màu Đen khi biến thể đó hết hàng -> worker phải báo hết hàng, không gộp tồn kho màu khác."""
```

---

## 4. Tiêu Chí Nghiệm Thu (Acceptance Criteria)

1. **Test Suite PASS 100%**: Toàn bộ 6 test case mới trong `tests/test_pr_a_correctness.py` đạt PASS.
2. **Không phá vỡ Regression**: Toàn bộ các test suite hiện hữu (`test_audit_remediation.py`, `test_manager_crud.py`, `test_conversation.py`, `test_system_foundation.py`) tiếp tục PASS.
3. **Docs Contract PASS**: `python scripts/check_docs_contract.py` đạt 4/4 cổng kiểm định.
4. **Không phát sinh rò rỉ ngữ cảnh**: Chạy kịch bản probe đối kháng P-603 vs P-602 xác nhận cache hoàn toàn cô lập.

---

## 5. Trình Tự Thực Thi Từng Bước

1. **Bước 1**: Tạo file test `tests/test_pr_a_correctness.py` chứa các ca tái hiện lỗi (Ban đầu sẽ FAIL để làm Red baseline).
2. **Bước 2**: Chỉnh sửa [`retailops/business/cache.py`](../retailops/business/cache.py) và [`retailops/business/application.py`](../retailops/business/application.py) để xử lý F01 và F02.
3. **Bước 3**: Chỉnh sửa [`retailops/workflow/subagents/dispute_agent.py`](../retailops/workflow/subagents/dispute_agent.py) để xử lý F03, F04, F05, F06.
4. **Bước 4**: Chạy test `tests/test_pr_a_correctness.py` xác nhận chuyển sang Green.
5. **Bước 5**: Chạy toàn bộ test regression và xác minh hợp đồng tài liệu.
