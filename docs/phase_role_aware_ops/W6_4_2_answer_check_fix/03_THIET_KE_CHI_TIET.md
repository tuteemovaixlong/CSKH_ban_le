# 03 — Thiết kế chi tiết

Mọi tên hằng, trường, khóa trace và tên luật dưới đây phải dùng **đúng nguyên văn**. Mọi thay đổi code nằm trong `retailops/workflow/answer_check.py`, trừ mục 4.3 (`retailops/business/application.py`) và 4.4 (`scripts/run_agent_scenarios.py`).

"Số nguyên" nghĩa là `type(x) is int` (loại `bool`). "Số" nghĩa là `int` hoặc `float` nhưng không phải `bool`, và là số hữu hạn (`math.isfinite`).

## 1. Hàng 1 — tiền của món và tổng suy ra (F46)

### 1.1 Thêm trường tiền trực tiếp

```python
_MONEY_FIELDS = ('shipping_fee', 'amount', 'refunded_total', 'pending_total', 'unit_price', 'subtotal')
```

`tool_evidence` vẫn đi qua mọi độ sâu như cũ, nên giá và thành tiền của từng món trong `items` vào `money_amounts`.

### 1.2 Trường mới `derived_money`

Thêm vào `Evidence` (đặt sau các trường hiện có, mặc định `frozenset()`):

```python
derived_money: frozenset = field(default_factory=frozenset)
```

Trong lúc đi qua JSON của các tin `role == 'tool'` của lượt:

1. **Tiền hàng của một đơn.** Gặp một dict có khóa `items` là list **khác rỗng** mà **mọi** phần tử là dict có `subtotal` là số nguyên → thêm tổng các `subtotal` vào `derived_money`.
2. **Hồ sơ đơn.** Một dict là hồ sơ đơn khi `amount` và `shipping_fee` đều là số nguyên, và có mã: `id` là chuỗi khác rỗng, nếu không có thì `external_order_id` là chuỗi khác rỗng. Mã này dùng để khử trùng: cùng một đơn xuất hiện ở `list_orders` và `get_order` chỉ tính một lần (lấy bản gặp đầu tiên). Bản ghi thanh toán (có `amount` nhưng không có `shipping_fee`) không phải hồ sơ đơn.
3. **Tổng nhiều đơn.** Sau khi đi hết các tin của lượt, nếu có **từ 2 hồ sơ đơn khác mã trở lên**: thêm tổng `amount`, tổng `shipping_fee`; và nếu mọi hồ sơ đều có tiền hàng theo bước 1 thì thêm tổng tiền hàng.

Không thêm bất kỳ phép tính nào khác (không lấy `amount − shipping_fee`, không cộng một phần các đơn).

### 1.3 Dùng trong luật phí

Trong nhánh `_FEE` của luật chính sách, đổi điều kiện so số tiền từ `numbers <= evidence.money_amounts` thành `numbers <= (evidence.money_amounts | evidence.derived_money)`. Nhánh phí chính sách (`_POLICY_FEE_MATCH`) **không đổi**: luôn bỏ khi không có trích dẫn.

**Rủi ro chấp nhận:** một câu "phí ship là X" mà X trùng đúng giá một món của lượt sẽ lọt. Đây là sai số liệu của đơn chứ không phải lời hứa chính sách, và quy tắc W6.3.2 ("giữ câu khi mọi số tiền khớp tool") vẫn đúng tinh thần. Ghi vào báo cáo.

## 2. Hàng 2 — số thời gian suy ra từ trường của tool (F47 phần 1)

Thêm vào `Evidence`:

```python
derived_time: frozenset = field(default_factory=frozenset)
```

Với **mỗi dict** gặp trong JSON tool của lượt:

1. `late_by_hours` là số và `> 0`, gọi là `h`: thêm `floor(h)`, `ceil(h)`, `floor(h / 24)`, `ceil(h / 24)`.
2. `days_since_delivery` là số và `>= 0`, gọi là `d`: thêm `floor(d)`, `ceil(d)`. Với mỗi khóa trong `('return_window_days', 'size_exchange_window_days', 'warranty_window_days')` **của cùng dict** mà giá trị `W` là số nguyên và `W >= d`: thêm `floor(W - d)`, `ceil(W - d)`.

Mọi giá trị thêm vào đều là `int`. `late_by_hours = 0.0`, `None`, chuỗi, `bool` thì bỏ qua.

Trong nhánh `_DEADLINE`: đổi `not numbers <= evidence.deadline_days` thành `not numbers <= (evidence.deadline_days | evidence.derived_time)`. Nhánh không có số (cần `has_window` hoặc `has_delivery_date`) **không đổi**.

**Rủi ro chấp nhận:** một số thời gian bịa trùng đúng một số suy ra của lượt sẽ lọt. Ghi vào báo cáo cùng số lượng số suy ra trên fixture ở 04 mục 4.

## 3. Hàng 3 — giữ nhãn khi phải bỏ dòng tiêu đề (F47 phần 2)

### 3.1 Dòng tiêu đề

Một dòng `L` của câu trả lời (sau `split('\n')`) là **dòng tiêu đề** khi `L` **không** bắt đầu bằng dấu danh sách (`^\s*(?:[-*+]|\d+[.)])\s+`) và rơi vào một trong hai dạng:

| Dạng | Nhận diện trên `s = L.strip()` | Phần tạo nhãn | Cách viết lại |
|---|---|---|---|
| (a) tiêu đề Markdown | `^(#{1,6})\s+(.+?)\s*#*$` | nhóm 2 | `<nhóm 1> <nhãn>` |
| (b) mở đầu bằng chữ đậm | `s` bắt đầu bằng `**…**` (đoạn đậm đầu tiên, không lồng). Chỉ tính khi **cả dòng** là đoạn đậm đó (cho phép thêm `:` ở cuối), **hoặc** chữ trong đoạn đậm có một mã khớp `_FACT_ID` (ví dụ `SIM-O-00091`) | chữ trong đoạn đậm | `**<nhãn>**` |

### 3.2 Nhãn

Từ "phần tạo nhãn", cắt tại **vị trí sớm nhất** của một trong các dấu ngăn: `' — '`, `' – '`, `' - '`, `': '`, `' | '`; lấy phần trước, rồi `strip(' :–—-')`. Không có dấu ngăn thì nhãn là cả phần tạo nhãn (đã strip).

### 3.3 Khi nào áp dụng

Chỉ khi dòng tiêu đề có **ít nhất một câu bị bỏ** theo luật như hiện nay. Khi đó:

- Dựng dòng thay thế theo cột "Cách viết lại".
- Chạy lại ba luật trên dòng thay thế với cùng bằng chứng. Nhãn rỗng, hoặc dòng thay thế vẫn có câu bị bỏ → giữ hành vi cũ cho dòng đó.
- Nếu không, và **nhãn không còn nằm trong phần giữ lại của dòng** → cả dòng được thay bằng dòng thay thế. Nếu nhãn vẫn còn (ví dụ `**SIM-O-1:** Đã giao ngày 05/11. Shop đổi tận nhà miễn phí ạ.` còn lại `**SIM-O-1:** Đã giao ngày 05/11.`) thì giữ hành vi cũ, để không mất câu đúng. Điều kiện này Claude thêm khi kiểm PR #115; bản đầu của mục này thiếu nó.
- Bộ đếm `dropped_policy`, `dropped_claims` và ghi chú cuối giữ nguyên như hành vi cũ (câu bị bỏ vẫn được đếm). Trích dẫn trong câu bị bỏ vẫn đi theo cơ chế `orphan_refs` như cũ.

Ví dụ (không có bằng chứng; cột giữa là kết quả Claude chạy trên `3239454`):

| Dòng gốc | Trên `3239454` | Sau W6.4.2 |
|---|---|---|
| `**SIM-O-38588564-03 — trễ hạn 72 giờ, sắp hết hạn trả hàng**` | dòng trống | `**SIM-O-38588564-03**` |
| `**1. SIM-O-38588564-02** — Đang giao hàng, quá hạn 54 giờ.` | `**1.` (vỡ: `_SPLIT` cắt sau "1.") | `**1. SIM-O-38588564-02**` |
| `### Đổi trả: miễn phí 2 chiều tận nhà` | dòng trống | `### Đổi trả` |
| `**Miễn phí đổi trả 2 chiều**` | dòng trống | dòng trống (nhãn vẫn là lời hứa) |
| `- **SIM-O-1 — trễ hạn trả hàng 72 giờ**` | dòng trống | dòng trống (dòng danh sách, giữ hành vi cũ) |
| `**Phí ship:** 30.000đ` | dòng trống | dòng trống (đoạn đậm không có mã đơn, không phải cả dòng) |

### 3.4 Dòng chỉ còn số thứ tự

`_SPLIT` cắt sau dấu chấm của số thứ tự ("1. "), nên một dòng có thể chỉ còn lại "1." hay "**1." sau khi bỏ câu. Với dòng có ít nhất một câu bị bỏ và không được thay bằng nhãn ở 3.3: nếu phần còn lại sau khi bỏ mọi ký tự `*`, `#`, `_` và khoảng trắng khớp `^(?:\d+[.)])?$` thì dòng đó thành dòng trống. Không đổi bộ đếm.

Kết quả của bộ kiểm chạy lại qua bộ kiểm phải không đổi (tính lũy đẳng, đã có test cho hành vi cũ).

## 4. Hàng 4 — ghi lại câu nào bị bỏ, vì luật nào, không ghi chữ

### 4.1 `AnswerCheck`

Thêm trường cuối, mặc định rỗng để mọi chỗ gọi cũ không đổi:

```python
details: tuple = ()
```

Mỗi phần tử là một dict có **đúng 4 khóa**:

| Khóa | Kiểu | Ý nghĩa |
|---|---|---|
| `line` | `int` | Số thứ tự dòng trong văn bản đưa vào, đếm từ 1, theo `split('\n')` sau chuẩn hóa NFC |
| `kind` | `'policy'`, `'claim'` hoặc `'handoff'` | Loại câu bị bỏ |
| `rule` | xem 4.2 | Luật đã bỏ câu |
| `heading_label_kept` | `bool` | Dòng này là dòng tiêu đề và đã được thay bằng nhãn theo mục 3 |

Một phần tử cho **mỗi câu bị bỏ**, theo thứ tự xuất hiện. Vì câu chuyển nhân viên đang được đếm vào cả `dropped_claims`, nên luôn có `len(details) == dropped_policy + dropped_claims`. **Không** ghi chữ của câu, không ghi con số nào của câu.

### 4.2 Tên luật

| `kind` | `rule` | Khi nào |
|---|---|---|
| `handoff` | `handoff_claim` | `_unfounded_handoff` đúng |
| `policy` | `logistics` | khớp `_LOGISTICS` |
| `policy` | `policy_fee` | khớp `_FEE` và khớp `_POLICY_FEE_MATCH` |
| `policy` | `fee_amount` | khớp `_FEE`, không phải phí chính sách, nhưng không có số tiền hoặc có số tiền không nằm trong bằng chứng |
| `policy` | `deadline_number` | khớp `_DEADLINE`, có số thời gian không nằm trong bằng chứng |
| `policy` | `deadline_no_fact` | khớp `_DEADLINE`, không có số, không có cờ cửa sổ hay mốc giao |
| `claim` | `done_claim` | `_unfounded_claim` đúng |

Cách làm gợi ý: tách `_uncited_policy_promise` thành `_policy_rule(sentence, evidence) -> str | None` trả tên luật, và giữ `_uncited_policy_promise` là hàm bọc trả `bool` để diff nhỏ. Thứ tự xét luật và kết quả giữ/bỏ **không đổi**.

### 4.3 Trace trong ứng dụng

Ở `retailops/business/application.py`, hai chỗ đang ghi `trace['answer_check']` (khoảng dòng 717–721 và 1350–1356): giữ nguyên dict hai khóa cũ, và **thêm** khóa riêng:

```python
answer['trace']['answer_check_detail'] = [dict(d) for d in checked.details]
```

(chỗ thứ hai dùng `answer["trace"]`). Chỉ ghi khi `checked.changed`. Không đổi chỗ kiểm bản nháp (dòng 1364). Không đổi giao diện web.

### 4.4 Runner đánh giá

Ở `scripts/run_agent_scenarios.py`, trong `run_scenario`, sau các khóa tùy chọn đang có của `turn_rec` (khoảng dòng 885–892), thêm:

```python
trace = result.get('trace') or {}
if trace.get('answer_check'):
    turn_rec['answer_check'] = {**trace['answer_check'], 'detail': list(trace.get('answer_check_detail') or [])}
```

Lượt không bị bộ kiểm sửa thì **không có** khóa `answer_check`. Không đổi `summarize`, định dạng báo cáo hay `eval_stats`.

## 5. Không đổi

- Ba câu ghi chú, `_SPLIT`, `_fragments`, các regex `_FEE`, `_LOGISTICS`, `_DEADLINE`, `_POLICY_CONTEXT`, `_HEDGE`, `_CLAIMS`, `_TIME_NUMBER`, `_FACT_ID`.
- `deadline_days`, `warranty_days` và các cờ cũ của `Evidence` giữ đúng giá trị như trước với cùng đầu vào. `money_amounts` chỉ khác khi đầu vào có `unit_price` hoặc `subtotal` (có test cũ so bằng với đầu vào không có hai khóa này).
- Hành vi với câu có trích dẫn, câu hỏi, câu rào đón.
