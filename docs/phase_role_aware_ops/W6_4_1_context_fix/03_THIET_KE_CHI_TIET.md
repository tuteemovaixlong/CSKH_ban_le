# 03 — Thiết kế chi tiết

Mọi tên trường, tham số và mô tả tool dưới đây là **bắt buộc theo đúng nguyên văn**. Muốn đổi thì dừng và hỏi owner.

## 1. Trần tổng theo cửa sổ (hàng 1)

Chuyển hàm `context_tokens()` từ `compaction.py` sang `agent_protocol.py` để chỉ còn **một nguồn**, rồi thay hai hằng cố định ở dòng 9–10:

```python
# agent_protocol.py (thêm `import os` nếu chưa có)
def context_tokens():
    value = int(os.environ.get('RETAILOPS_MODEL_CONTEXT_TOKENS', '16384'))
    if not 4096 <= value <= 131072:
        raise ValueError('RETAILOPS_MODEL_CONTEXT_TOKENS must be 4096–131072')
    return value

def max_characters():
    return 36000 * context_tokens() // 16384       # 36000 ở 16k, 72000 ở 32k, 18000 ở 8k

CONTEXT_TOKENS = context_tokens()                  # giữ cho code và test cũ; giá trị lúc import
MAX_CHARACTERS = max_characters()                  # giữ cho code và test cũ; giá trị lúc import
```

**Hai chỗ đang dùng trần tổng phải gọi hàm lúc chạy, không dùng hằng:** kiểm giao thức ở `agent_protocol.py` dòng 407 (`characters > MAX_CHARACTERS`) đổi thành `characters > max_characters()`, và `retailops/workflow/agent.py` dòng 148 đổi thành `fit_transcript(outgoing, max_characters() - 200)`. Lý do: runner (`scripts/run_agent_scenarios.py`) import `retailops_providers`, kéo theo `agent_protocol`, ở khoảng dòng 1206, **trước** khi đặt `RETAILOPS_MODEL_CONTEXT_TOKENS` theo cờ `--context-tokens` (khoảng dòng 1201–1248). Còn `compaction` thì được import muộn hơn, khi dựng `World`. Nếu trần tổng chỉ tính lúc import, lượt đo `--context-tokens 32768` sẽ có ngân sách từng phần ở 32k nhưng trần tổng kẹt ở 36.000.

```python
# retailops/workflow/compaction.py
from agent_protocol import context_tokens          # thay cho định nghĩa cũ; giữ tên để code khác import được
```

- **Không** để `agent_protocol.py` import bất cứ thứ gì trong `retailops.workflow`: `retailops/workflow/__init__.py` import `graph`, và `graph` dẫn ngược về `agent_protocol`, tạo import vòng. Chiều ngược lại (`compaction` import `agent_protocol`) thì an toàn, vì `agent_protocol` chỉ import thư viện chuẩn.
- Kiểm import bằng `python -c "import agent_protocol, retailops.workflow.agent, retailops.workflow.compaction"`, và chạy riêng từng module test liên quan.
- Giữ nguyên tên `CONTEXT_TOKENS` và `MAX_CHARACTERS` để code và test đang import trực tiếp không gãy; code mới dùng `max_characters()`.
- Các ngân sách trong `compaction.py` vẫn tính lúc import module đó, như hiện nay. Với runner thì đúng, vì `compaction` được import sau khi đã đặt biến.

## 2. `list_orders` (hàng 2)

### 2.1 Trường của một đơn trong bản tóm tắt

Dựng bằng cách lấy hồ sơ đầy đủ hiện có (`self.read_order(oid, focus=False)`) rồi **chỉ giữ** các khóa dưới đây, đúng thứ tự này. Khóa nào hồ sơ không có thì bỏ qua, không thêm `null`.

| Khóa | Nguồn | Ghi chú |
|---|---|---|
| `id` | hồ sơ | mã nội bộ; chế độ `legacy` đọc khóa này |
| `external_order_id` | hồ sơ | mã sàn; `legacy` và rào an toàn đọc |
| `status` | hồ sơ | `legacy` đọc |
| `ordered_at` | hồ sơ | ISO như hiện tại |
| `name` | hồ sơ | tên hiển thị hiện có, ví dụ "Áo sơ mi … và 1 sản phẩm khác"; `legacy` đọc |
| `product_id` | hồ sơ | |
| `variant` | hồ sơ | `legacy` đọc |
| `amount` | hồ sơ | tổng tiền đơn; `legacy` đọc |
| `currency` | hồ sơ | |
| `shipping_fee` | hồ sơ | |
| `payment_method` | hồ sơ | |
| `payment_status` | hồ sơ | |
| `promised_delivery_by` | hồ sơ | |
| `delivered_at` | hồ sơ | |
| `items` | `hồ sơ['items']` | danh sách món rút gọn, mỗi món chỉ có `name`, `variant`, `quantity`, `subtotal`; đơn không có dòng món thì `[]` |

Không giữ: `internal_order_id` (trùng `id`), `source_system`, `payment`, `delivery`, `refund`, `refund_summary`, `eligibility`, `vouchers`, `recipient`, `address`, `as_of`, `source`, `version` và mọi khóa khác. Model xem chi tiết bằng `get_order`.

### 2.2 Tham số

```python
tool('list_orders', LIST_ORDERS_DESCRIPTION,
     {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20,
                'description': 'How many orders to return; default 5.'},
      'offset': {'type': 'integer', 'minimum': 0,
                 'description': 'How many of the newest orders to skip; default 0. Use next_offset from the previous call.'}},
     required=[])
```

`required=[]` là bắt buộc: hàm `tool()` mặc định coi mọi thuộc tính là bắt buộc.

**Phải sửa `validate_tool`** (`agent_protocol.py` dòng 306–322). Hàm này hiện ép **mọi** giá trị tham số phải là chuỗi khác rỗng, tối đa 64 ký tự, nên giữ nguyên thì mọi lời gọi có phân trang sẽ bị tính là gọi tool sai. Cách sửa:

- Thêm bảng `INTEGER_ARGUMENTS = {'list_orders': {'limit': (1, 20), 'offset': (0, 10000)}}`.
- Với các khóa trong bảng này: chấp nhận `int` (không chấp nhận `bool`), hoặc chuỗi chỉ gồm chữ số (một số parser trả số dưới dạng chuỗi), rồi chuyển về `int`. Ngoài khoảng thì `ProtocolError('Invalid tool argument value')`.
- Trả về `arguments` đã chuẩn hóa sang `int`.
- Mọi khóa khác giữ đúng luật chuỗi như cũ. Hàm vẫn trả `arguments` như hiện nay.

Trong `BoundTools.__call__` (`retailops_tools.py` dòng 209), vẫn kiểm lại `limit` và `offset` để phòng các đường gọi không qua `validate_tool` (chế độ `legacy`, gọi trực tiếp). Sai thì trả `{'error': 'invalid_arguments', 'message': 'limit phải từ 1 đến 20; offset phải từ 0 trở lên.'}`, **không** ném exception. Không truyền thì dùng `limit=5`, `offset=0`.

### 2.3 Thứ tự và kết quả trả về

- Sắp các dòng từ `self.store.orders(customer)` theo `ordered_at` thô của bảng (cột `REAL`, epoch) **giảm dần**; `ordered_at` rỗng xếp cuối; cùng `ordered_at` thì theo `id` giảm dần. Chỉ sắp trong tool, **không** sửa `store.orders()`, vì chỗ khác đang dùng thứ tự cũ.
- Lấy lát `[offset : offset + limit]`, rồi dựng bản tóm tắt cho từng đơn trong lát.

```json
{
  "orders": [ … ],
  "total_count": 7,
  "returned_count": 5,
  "offset": 0,
  "limit": 5,
  "has_more": true,
  "next_offset": 5,
  "truncated": true,
  "note": "Đang hiện 5/7 đơn gần nhất. Gọi lại list_orders với offset=5 để xem tiếp, hoặc get_order để xem chi tiết một đơn."
}
```

- `has_more = offset + returned_count < total_count`; `truncated` luôn bằng `has_more`, vì rào an toàn đọc `truncated`.
- `next_offset` chỉ có khi `has_more` là true; `note` cũng chỉ có khi đó.
- `offset` lớn hơn hoặc bằng `total_count`: `orders` rỗng, `has_more` false, kèm `note`: "Không còn đơn nào sau vị trí này; khách có {total_count} đơn."
- Khách không có đơn nào: `orders` rỗng, `total_count` 0, không có `note`.

### 2.4 Mô tả tool, nguyên văn

```text
List the authenticated customer's orders as short summaries, newest first: 5 per call by default (limit up to 20; offset pages through older orders). Each summary has both order IDs, status, ordered_at, amount, shipping_fee, payment status, delivery dates and item names with quantities. Call get_order for payment, delivery, refund and eligibility details. When has_more is true, say how many of total_count are shown and offer to show more (offset=next_offset) or to narrow down.
```

Đặt chuỗi này vào hằng `LIST_ORDERS_DESCRIPTION` trong `agent_protocol.py`. **Không** đưa hướng dẫn phân trang vào `SYSTEM`.

## 3. `list_case_orders` của Trợ lý ca (hàng 3)

- Trong `_list_case_orders` (`retailops/workflow/case_assist.py` 416–447), vẫn dựng hồ sơ bằng `_format_case_order` như cũ, rồi chỉ giữ các khóa sau, đúng thứ tự: `id`, `external_order_id`, `status`, `ordered_at`, `name`, `product_id`, `variant`, `amount`, `currency`, `shipping_fee`, `payment_status`, `delivered_at`, `days_since_delivery`, `allowed_action_types`, `has_open_order_action`, `items` (rút gọn như 2.1).
- Giữ `LIMIT 20` và thứ tự hiện tại. Thêm `total_count` (đếm `COUNT(*)` các đơn của khách) và `truncated` (`total_count > 20`).
- Giữ các khóa cấp trên hiện có: `case_id`, `orders`, `count`.
- Mô tả tool `list_case_orders`, nguyên văn:

```text
READ ONLY: list the orders of the current case's customer as short summaries (without customer PII): IDs, status, dates, amount, payment status, delivery age, allowed actions, open-request flag and item names with quantities. Call get_case_order for payment, refund, eligibility and stock details.
```

- `get_case_order` giữ nguyên hồ sơ đầy đủ.

## 4. Rút gọn kết quả tool theo thứ tự mới (hàng 4)

Viết lại phần thân của `compact_tool_result(result, limit=None)` trong `retailops/workflow/compaction.py`. Giữ chữ ký hàm và hành vi ở hai đầu.

```text
text = dump(result)
nếu len(text) <= limit: trả text                          # như cũ, trả nguyên văn

# Pha A: rút chuỗi, giữ nguyên số phần tử
với string_cap trong (240, 160, 120, 80):
    v = rút_chuỗi(result, string_cap)                    # chỉ cắt chuỗi dài hơn cap, thêm "…"
    nếu vừa limit sau khi đặt v["_truncated"] = True: trả

# Pha B: bỏ khóa ít giá trị, vẫn giữ nguyên số phần tử
v = bỏ_khóa(v, LOW_VALUE_KEYS)                           # đệ quy vào dict và list
nếu vừa: trả

# Pha C: lúc này mới cắt đuôi danh sách
với list_cap trong (10, 6, 4, 2):
    w = cắt_danh_sách(v, list_cap)                        # thêm một chuỗi ghi chú làm phần tử cuối
    nếu vừa: trả

# Chốt cuối như cũ: {"_truncated": true, "note": …, "preview": …}
```

- `LOW_VALUE_KEYS = ('description', 'image_url', 'images', 'note', 'notes', 'raw', 'metadata', 'as_of', 'source')`. Không bỏ khóa `note` ở cấp trên cùng của kết quả `list_orders`: đó là hướng dẫn phân trang. Cách làm: chỉ bỏ các khóa này **từ cấp thứ hai trở xuống**.
- Phần tử ghi chú khi cắt danh sách đổi thành tiếng Việt: `"…(còn {n} mục bị ẩn do giới hạn hiển thị; hỏi hẹp hơn hoặc dùng tool xem chi tiết)"`.
- Kết quả dạng dict được rút gọn thì luôn có `"_truncated": true` ở cấp trên cùng, như hiện nay.
- Không làm danh sách khóa riêng cho từng tool. Gốc lỗi của `list_orders` đã xử lý ở hàng 2.
- `fit_transcript` và `fit_history` gọi `compact_tool_result` thì tự hưởng thứ tự mới; không sửa logic khác của hai hàm này.

## 5. Tài liệu cho bộ đánh giá (hàng 5)

Thay ô "Trả về" của dòng `list_orders` trong bảng mục 3.1 của `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md`. Ô "Tham số" đổi thành `limit` (mặc định 5, tối đa 20), `offset` (mặc định 0). Ô "Trả về" viết bằng tiếng Việt, ngắn: "tóm tắt các đơn của khách, mới nhất trước: mã sàn, mã nội bộ, trạng thái, ngày đặt, số tiền, phí ship, thanh toán, ngày giao, các món kèm số lượng; `total_count`, `has_more`, `next_offset`; chi tiết thanh toán, vận chuyển, hoàn tiền, điều kiện xử lý thì xem bằng `get_order`". Nếu mục 3.2 có dòng `list_case_orders` thì sửa tương tự theo 03 mục 3.
