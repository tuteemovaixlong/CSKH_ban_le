# 03 — Thiết kế chi tiết

Mọi tên hằng, trường, khóa trace, tên luật và câu chữ dưới đây phải dùng **đúng nguyên văn**. Số dòng theo `ece0b0b`. Claude đã dựng một bản nguyên mẫu của mục 1 trên bản sao tạm (không commit) và chạy bảng ở 04 mục 2: khớp cột "Sau W6.4.3".

## 1. Hàng 1 — `retailops/workflow/answer_check.py`

### 1.1 Hai nhóm luật

Thêm gần các hằng regex:

```python
BLOCKING_RULES = ('handoff_claim', 'done_claim', 'logistics', 'policy_fee')
AUDIT_RULES = ('fee_amount', 'deadline_number', 'deadline_no_fact')
```

`_policy_rule` (dòng 264) giữ nguyên chữ ký, thứ tự xét và tên luật trả về. Chỉ đổi chỗ dùng nó:

- `_sentence_drop_info` (dòng 336): chỉ trả `('policy', rule)` khi `rule in BLOCKING_RULES`. Thứ tự vẫn là `_unfounded_handoff`, rồi luật chính sách chặn, rồi `_unfounded_claim`.
- `check_final_answer` (dòng 351): với câu **được giữ**, gọi `_policy_rule`; nếu kết quả thuộc `AUDIT_RULES` thì thêm `{'line': line_no, 'rule': rule}` vào danh sách ghi vết. Câu bị xóa vì luật chặn thì không ghi vết.
- `_any_sentence_dropped` (dòng 347, dùng cho nhãn tiêu đề) tự động chỉ xét luật chặn vì đi qua `_sentence_drop_info`.

### 1.2 `AnswerCheck` thêm trường ghi vết

```python
@dataclass(frozen=True)
class AnswerCheck:
    text: str
    dropped_policy: int = 0
    dropped_claims: int = 0
    details: tuple = ()
    audit: tuple = ()
```

- Mỗi phần tử của `audit` là dict **đúng 2 khóa**: `line` (int, đếm từ 1 như `details`) và `rule` (một tên trong `AUDIT_RULES`). Không chữ, không số của câu.
- `changed` giữ nguyên định nghĩa (chỉ tính câu bị xóa).
- Không có câu nào bị xóa: trả `AnswerCheck(text, audit=tuple(audit))`, trong đó `text` là văn bản gốc như hiện nay.

### 1.3 "Phí ship do shop chịu" là lời hứa phí

Thêm một nhánh vào cuối `_POLICY_FEE` (dòng 36–39):

```python
r'phí (?:ship|vận chuyển|giao(?: hàng)?)[^.!?\n]{0,20}?(?:do\s+)?(?:shop|bên em|cửa hàng|chúng em)\s+(?:chịu|hỗ trợ|trả|bao)'
```

Kết quả: "Phí ship do shop chịu hoàn toàn." và "Phí vận chuyển sẽ được shop hỗ trợ." thành `policy_fee` (chặn). Claude đã kiểm các câu đúng trong test cũ của W6.3.2, như "… (đã gồm 30.000 VNĐ phí ship, COD đã thanh toán) …", không khớp nhánh này.

### 1.4 "Miễn phí ship" của chính đơn có phí ship 0

`Evidence` thêm trường cuối:

```python
zero_shipping_fee: bool = False
```

`tool_evidence` đặt `True` khi gặp dict có `type(shipping_fee) is int and shipping_fee == 0`.

Thêm hằng:

```python
_FREE_SHIPPING = re.compile(r'miễn phí (?:ship|vận chuyển|giao hàng)|free ?ship|miễn cước(?: ship| vận chuyển)?')
_RETURN_CONTEXT = re.compile(r'đổi|trả|hoàn|bảo hành')
```

Trong nhánh `_FEE` của `_policy_rule`, câu được coi là nói về phí ship của chính đơn (`own_free_shipping`) khi **đủ cả ba** điều kiện:
1. `evidence.zero_shipping_fee` là `True`;
2. câu không có `_RETURN_CONTEXT`;
3. sau khi xóa mọi đoạn khớp `_FREE_SHIPPING`, `_POLICY_FEE_MATCH` không còn khớp gì.

Khi đó:
- câu **không** phải `policy_fee`;
- nếu câu không có số tiền nào thì không dính luật nào;
- nếu có số tiền thì so như luật `fee_amount` hiện nay (và chỉ ghi vết).

Ví dụ:
- "Đơn SIM-O-9 được miễn phí ship ạ." với `shipping_fee = 0`: giữ, không ghi vết.
- "Đổi size lần đầu được miễn phí ship ạ.": vẫn `policy_fee`, vì có "đổi".

### 1.5 Ngày, giờ, số điện thoại che không phải tiền

Thêm hằng và dùng trong `_money_amounts` (dòng 245), ngay sau `_FACT_ID.sub`:

```python
_NOT_MONEY = re.compile(r'\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b|\b\d{1,2}:\d{2}(?::\d{2})?\b|\d{2,4}\*{2,}\d{2,4}')
```

```python
for match in _MONEY.finditer(_NOT_MONEY.sub(' ', _FACT_ID.sub(' ', plain))):
```

Lưu ý khi viết bằng script: `\b` trong chuỗi Python thường là ký tự backspace. Dùng chuỗi `r'...'` và kiểm lại tệp sau khi ghi.

### 1.6 Giữ nguyên

- Phần gom bằng chứng của W6.4.2 (`derived_money`, `derived_time`). Nó vẫn dùng cho ghi vết.
- Cách giữ nhãn tiêu đề, bỏ dòng chỉ còn số thứ tự, `details` (W6.4.2). Các cơ chế này giờ chỉ chạy khi có câu dính luật chặn.
- Docstring đầu tệp: viết lại cho đúng (4 luật xóa câu, 3 luật chỉ ghi vết), giữ dẫn chiếu W3.2-D3, W3.2-D11, thêm W6.4-D17.

## 2. Hàng 2 — trace và runner

`retailops/business/application.py`, nhánh khách (dòng 716–722): giữ nguyên khối `if checked.changed:`, thêm **ngoài** khối đó:

```python
if checked.audit:
    answer['trace']['answer_check_audit'] = [dict(a) for a in checked.audit]
```

`scripts/run_agent_scenarios.py`, trong `run_scenario`, ngay sau khối `answer_check` (dòng 893–898):

```python
if trace.get('answer_check_audit'):
    turn_rec['answer_check_audit'] = list(trace['answer_check_audit'])
```

Không đổi `summarize`, định dạng báo cáo hay `eval_stats`.

## 3. Hàng 3 — Trợ lý ca (`application.py:1341–1370`)

Hiện nay dòng 1351 kiểm **toàn văn** (`raw_answer_text`), sửa nó, rồi mới tách bản nháp (dòng 1364) và kiểm bản nháp lần nữa (dòng 1366). Đổi thành:

1. **Bỏ** lần kiểm toàn văn ở dòng 1351–1358. `raw_answer_text` không bị sửa bởi bộ kiểm.
2. Giữ nguyên `cited_sources` (trước đó) và kiểm rò rỉ canary trên `raw_answer_text`.
3. `clean_answer, draft_reply = extract_case_assist_draft(raw_answer_text, mode)` như cũ.
4. Nếu có `draft_reply`:
   ```python
   draft_checked = check_final_answer(draft_reply, answer.get("messages"))
   if draft_checked.changed:
       clean_answer = clean_answer.replace(draft_reply, draft_checked.text, 1)  # nhân viên thấy đúng bản nháp sẽ gửi
       draft_reply = draft_checked.text
       answer["trace"]["answer_check"] = {"dropped_policy_promises": draft_checked.dropped_policy,
                                          "dropped_done_claims": draft_checked.dropped_claims}
       answer["trace"]["answer_check_detail"] = [dict(d) for d in draft_checked.details]
   if draft_checked.audit:
       answer["trace"]["answer_check_audit"] = [dict(a) for a in draft_checked.audit]
   ```
   Sau đó kiểm rò rỉ canary trên bản nháp như cũ.

`extract_case_assist_draft` dựng `clean_answer` bằng cách nối phần trước, bản nháp và phần sau, nên `draft_reply` nằm nguyên văn trong `clean_answer`. Ở chế độ `draft` không có thẻ, `clean_answer` bằng chính bản nháp. Nếu thấy trường hợp `replace` không tìm được bản nháp, dừng và hỏi.

## 4. Hàng 4 — `retailops/guardrails/topic_filter.py`, mục 4 (dòng 618–643)

- Tách bốn mẫu hiện có thành hai nhóm: ba mẫu đầu là **câu hủy**, mẫu `đã\s+hoàn\s+tiền\s+thành\s+công` là **câu hoàn tiền**. Giữ nguyên văn các mẫu.
- Lấy bằng chứng bằng `tool_evidence(messages)` từ `retailops.workflow.answer_check`. Tệp đó chỉ import thư viện chuẩn, nên không tạo import vòng; kiểm lại khi sửa.
- `cancel_claim = any(câu hủy khớp) and not evidence.cancelled`.
- `refund_claim = câu hoàn tiền khớp and not evidence.refunded`.
- Chỉ khi `cancel_claim or refund_claim` mới thay câu trả lời. Tìm `inspected_order` như cũ, rồi đặt `code = inspected_order.get("external_order_id") or inspected_order.get("id")` và `ostatus = inspected_order.get("status", "pending")`.

Câu thay thế **nguyên văn**, ưu tiên `cancel_claim` khi cả hai cùng đúng:

| Trường hợp | Câu |
|---|---|
| hủy, có đơn | `f"Dạ qua kênh chat, hệ thống chưa thực hiện hủy đơn hàng {code}; đơn {code} hiện đang ở trạng thái {ostatus} (chưa bị hủy). Mọi thao tác hủy đơn đều cần tạo đề xuất hợp lệ và được anh/chị bấm xác nhận trực tiếp ạ."` |
| hủy, không có đơn | giữ nguyên câu hiện tại ở dòng 640–643 |
| hoàn tiền, có đơn | `f"Dạ hệ thống chưa ghi nhận hoàn tiền cho đơn {code}; đơn {code} hiện đang ở trạng thái {ostatus}. Tiền hoàn chỉ được xác nhận khi dữ liệu thanh toán của đơn ghi nhận đã hoàn ạ."` |
| hoàn tiền, không có đơn | `"Dạ hệ thống chưa ghi nhận hoàn tiền cho đơn này. Tiền hoàn chỉ được xác nhận khi dữ liệu thanh toán của đơn ghi nhận đã hoàn ạ."` |

Bỏ hẳn đoạn "chưa ghi nhận thông tin giao hàng/địa chỉ (delivery=…, address=…)".

## 5. Hàng 5 — `agent_protocol.py:33`

```python
MAX_TOOLS_PER_STEP = MAX_TOOL_CALLS  # W6.4-D17: một bước được dùng hết ngân sách tool của lượt
```

- Đặt ngay sau `MAX_TOOL_CALLS = 10`. Không đổi chỗ nào khác:
  - `assistant_message` (dòng 391, 406) và `validate_messages` (dòng 468) tự dùng giá trị mới;
  - `agent.py:195` vẫn trả `agent_budget_exceeded` khi tổng cả lượt vượt 10;
  - nhánh `legacy` giữ `LEGACY_MAX_TOOL_CALLS = 8`.
- Không sửa `SYSTEM`.
