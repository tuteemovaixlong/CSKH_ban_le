# Tham vấn W6.4.3 — Bộ kiểm câu trả lời (`answer_check`) và lỗi "quá 4 tool mỗi bước"

> **Ngày:** 2026-11-15. **Người hỏi:** owner; Claude soạn tài liệu.
> **Người được tham vấn:** Gemini 4 Carbon. **Chỉ tư vấn:** không sửa tệp, không commit, không chạy lệnh ghi, không gọi model hay API trả phí, không truy cập EC2, Colab hay dữ liệu production.
> **Code tham chiếu:** `origin/main` tại `ece0b0b4004ad1fdfddfbcca8abaa86cc69fe408` (đang chạy trên production, image `sha256:1034776f…`).
> **Kết quả (2026-11-15):** Carbon đề xuất thu hẹp bộ kiểm; owner chốt W6.4-D17, thực hiện theo [handoff W6.4.3](../W6_4_3_answer_check_scope/README.md). Carbon chỉ ra hai chỗ tài liệu này viết chưa đúng: (a) trích dẫn `[KB:…]` và câu rào đón chỉ được miễn ở luật chính sách, không miễn ở luật "đã làm"; (b) `enforce_final_answer_grounding` còn mục 3 (đơn không tìm thấy) và mục 4 (khẳng định hủy, hoàn tiền), trong đó mục 4 có lỗi (F50).
> Owner muốn một ý kiến độc lập trước khi chọn hướng. Tài liệu cố trình bày trung lập; chỗ nào là ý kiến của Claude thì ghi rõ.

## 1. Hệ thống trong một trang

- **RetailOps** là trợ lý chăm sóc khách hàng bán lẻ, đề tài khóa luận: nộp báo cáo 2026-12-19, bảo vệ 20–23/12/2026.
- **Vòng agent** (`retailops/workflow/agent.py`): model đọc tin khách, gọi tool (`list_orders`, `get_order`, `search_knowledge`, `get_current_time`…), rồi viết câu trả lời. Ngân sách mỗi lượt (`agent_protocol.py:31–33`): tối đa 6 lần gọi model, 10 tool, **4 tool trong một bước**.
- **Sau khi model viết xong**, câu trả lời đi qua hai bộ kiểm trong code rồi mới tới khách:
  - `enforce_final_answer_grounding` (`retailops/guardrails/topic_filter.py:456`): chặn bịa giá, tồn kho, bảo hành khi tool trả rỗng; ép nói "danh sách chưa đủ" khi bị cắt.
  - **`check_final_answer`** (`retailops/workflow/answer_check.py`, 393 dòng): chủ đề của tài liệu này.
- **Model:** production có hai ô. Ô "API" chạy DeepSeek V4.1 Flash (`deepseek-flash`). Ô "Custom" chạy Qwen3.5-9B trên vLLM, Colab L4. Lượt đo chính W6.4 chạy Qwen3.5-9B trên **250 ca đã đóng băng** (12 bộ S01–S12, trong đó có ca chuyển thể từ τ²-bench retail và AgentDojo), chấm tự động bằng `scripts/run_agent_scenarios.py`.
- **Ràng buộc:**
  - đo phải tái lập được;
  - CI chạy runner với model giả theo kịch bản, không có model thật;
  - container `web` chỉ 512 MB RAM, không GPU;
  - tránh thêm thư viện nặng;
  - DeepSeek còn khoảng 3,5 USD dùng được;
  - còn khoảng 5 tuần.

## 2. `answer_check` làm gì

Quyết định gốc W3.2-D3, W3.2-D11: model viết câu trả lời; code chỉ **xóa những câu mà bằng chứng của lượt không đỡ được**, rồi nối một câu ghi chú cho mỗi loại đã xóa. Cách làm:

1. Tách câu trả lời theo dòng, mỗi dòng tách theo dấu câu.
2. Mỗi câu qua các luật theo thứ tự dưới đây.
3. "Bằng chứng" (`tool_evidence`) là các trường số và cờ trong JSON tool của lượt: `amount`, `shipping_fee`, `unit_price`, `subtotal`, số ngày cửa sổ đổi/trả/bảo hành, cờ còn hạn, mốc giao, và từ W6.4.2 thêm vài số suy ra như tổng tiền hàng, số giờ trễ, số ngày còn lại.

Câu có trích dẫn `[KB:…]` từ `search_knowledge`, câu hỏi, câu rào đón ("chưa rõ", "chưa thể xác nhận") thì luôn được giữ. Hai luật chính sách dưới cũng chỉ xét câu có từ ngữ cảnh chính sách (đổi, trả, hoàn, hủy, bảo hành, ship, vận chuyển, giao hàng…).

| Luật (`rule`) | Nhóm | Câu bị xóa khi | Ví dụ bị xóa | Ghi chú nối |
|---|---|---|---|---|
| `handoff_claim` | khẳng định đã làm | nói đã chuyển nhân viên mà không có tool chuyển thành công trong lượt | "Em đã chuyển cuộc trò chuyện cho nhân viên rồi ạ." | `HANDOFF_NOTE` |
| `done_claim` | khẳng định đã làm | nói shop/hệ thống đã hủy, đổi, trả, hoàn tiền, đã gửi yêu cầu mà tool không cho thấy | "Em đã hủy đơn SIM-O-00115 cho anh/chị rồi ạ." | `CLAIM_NOTE` |
| `logistics` | lời hứa chính sách | tận nhà, 2 chiều, shipper đến lấy, 1 đổi 1… không trích dẫn | "Shop đổi size tận nhà cho anh/chị ạ." | `POLICY_NOTE` |
| `policy_fee` | lời hứa chính sách | miễn phí, phí đổi/trả, shop chịu phí… không trích dẫn | "Shop miễn phí đổi hàng ạ." | `POLICY_NOTE` |
| `fee_amount` | **so khớp số** | có "phí ship/vận chuyển/giao" và có số tiền không nằm trong bằng chứng, hoặc không có số nào | "Phí ship đơn này là 35.000đ ạ." (tool ghi 40.000) | `POLICY_NOTE` |
| `deadline_number` | **so khớp số** | có từ thời hạn ("trong", "quá", "hạn"…) đi với số ngày/giờ không nằm trong bằng chứng | "Thời hạn đổi trả là 30 ngày." (chính sách 7) | `POLICY_NOTE` |
| `deadline_no_fact` | **so khớp số** | có "thời hạn", "hạn đổi/trả" mà lượt không có cờ cửa sổ hay mốc giao nào | "Đơn còn trong thời hạn đổi trả ạ." | `POLICY_NOTE` |

Mã: các regex ở `answer_check.py:35–99`; `_policy_rule` ở dòng 264; `_unfounded_claim` ở dòng 290; `_unfounded_handoff` ở dòng 306; `check_final_answer` ở dòng 351.

`POLICY_NOTE` = "Phần phí, giao nhận và thời hạn em chưa có trích dẫn từ kho chính sách của shop nên chưa thể xác nhận ạ."

## 3. Lịch sử xóa nhầm (đều thấy trên production hoặc khi kiểm)

| Mã | Nhóm luật | Câu đúng bị xóa | Đã sửa ở |
|---|---|---|---|
| F29 | so khớp số (thời hạn) | "đơn … vẫn trong thời hạn giao dự kiến" dù tool có mốc giao | W6.3.1 |
| F30 | so khớp số (phí) | "phí ship 30.000" dù đúng `shipping_fee` | W6.3.2 |
| F32 | so khớp số (thời hạn) | "Bộ Nồi Inox **3** Đáy … bảo hành 365 ngày": số 3 trong tên bị coi là số ngày | W6.3.2 |
| F46 | so khớp số (phí) | "Tiền hàng 799.000₫ + phí ship 40.000₫" vì giá món chưa là bằng chứng | W6.4.2 |
| F47 | so khớp số (thời hạn) | "trễ hạn 72 giờ" vì số giờ trễ chưa là bằng chứng; xóa luôn dòng tiêu đề mã đơn | W6.4.2 |
| **mới** | so khớp số (phí) | dòng có ngày "09/11/2026" và "phí ship": năm **2026** bị đọc thành số tiền 2026₫ | chưa sửa |
| F31 | khẳng định đã làm | "đơn đã được hoàn tiền" dù hoàn tiền đã completed | W6.3.2 |
| F35 | khẳng định đã làm | "không thể vừa trả vừa đổi": "vừa" bị hiểu là "vừa mới" | W6.3.4 |

Đếm: **6 lần ở nhóm so khớp số**, 2 lần ở nhóm khẳng định đã làm. Nhóm lời hứa chính sách rõ chữ (`logistics`, `policy_fee`) chưa ghi nhận lần xóa nhầm nào. Trên runner giả 250 ca (336 lượt), bộ kiểm chỉ sửa 2 lượt: một `done_claim` đúng, một `fee_amount` ở ghi chú nội bộ của Trợ lý ca.

## 4. Smoke production 2026-11-15, sau deploy W6.4.2

Ô DeepSeek, tài khoản khách có 3 đơn (`SIM-O-38588564-01/-02/-03`).

**Câu 1 "liệt kê các đơn của tôi"** (lượt `9cdbe635-…`): model viết bảng 5 cột (Mã đơn, Ngày đặt, Sản phẩm, Tổng tiền, Trạng thái). **Cả 3 dòng dữ liệu bị xóa**, chỉ còn tiêu đề bảng và `POLICY_NOTE`. Claude tái hiện trên `ece0b0b`, với bằng chứng là `list_orders` của 3 đơn:

| Dòng | Kết quả | Luật |
|---|---|---|
| `\| SIM-O-…-02 \| 09/11/2026 \| Áo khoác … \| 839.000₫ (gồm phí ship 40.000₫) \| Đang vận chuyển \|` | **xóa** | `fee_amount` (2026 bị đọc là tiền) |
| cùng dòng nhưng ngày ghi `09/11` | giữ | — |
| `\| … \| 839.000₫ \| Đang vận chuyển (trễ hạn 54 giờ) \|` | **xóa** | `deadline_number` (bản tóm tắt `list_orders` không có `late_by_hours`) |
| `- Đặt ngày 09/11/2026, phí ship 40.000₫.` | **xóa** | `fee_amount` |

Không có bản gốc câu trả lời; trace chỉ ghi số dòng và tên luật (`trace.answer_check_detail`).

**Câu 2 "phân tích cả 3 đơn giúp tôi"** (lượt `725b77cc-…`): **HTTP 503 `agent_response_failed`**, cả lượt hỏng. Trace:

```json
"model_errors": [{"call": 2, "code": "agent_response_failed", "error_kind": "ProtocolError",
  "provider_message": "Too many tool calls in a model step", "finish_reason": "tool_calls",
  "completion_tokens": 356, "had_reasoning": true}]
```

- Bước 1 model gọi lại `list_orders`; suy luận ghi "I claimed 3 orders without calling list_orders", vì lịch sử gửi model không giữ lượt gọi tool. `SYSTEM` cũng dặn đọc lại tool trước khi trả lời về đơn.
- Bước 2 model xin **hơn 4 tool một lúc**. Có thể là 3 `get_order`, `get_current_time` và `search_knowledge`; chưa xác minh được vì không có bản gốc.
- `assistant_message` (`agent_protocol.py:391–392`) ném `ProtocolError` khi số tool trong bước > `MAX_TOOLS_PER_STEP = 4`. Lỗi được ném lên, cả lượt hỏng, không có cơ hội làm lại.
- `SYSTEM` dòng 3 viết "Independent lookups may be requested together in one step." nhưng **không nói giới hạn 4**.
- Lần smoke trước (ảnh `c5250ba7…`), cùng câu này, model gọi đúng 4 tool trong một bước nên chạy được.
- Lỗi này có từ W3.2, **không do `answer_check`**.

## 5. Claude thử phương án trên bản sao (offline, không đụng production)

Hai bản sao của `ece0b0b`:
- **B** = thu hẹp: `_policy_rule` không còn trả `fee_amount`, `deadline_number`, `deadline_no_fact`; giữ `logistics`, `policy_fee`, `done_claim`, `handoff_claim`.
- **C** = gỡ hẳn: `check_final_answer` trả nguyên văn.

| Kiểm | `ece0b0b` hiện tại | B (thu hẹp) | C (gỡ hẳn) |
|---|---|---|---|
| 4 tệp test cũ của bộ kiểm (51 test) | 51/51 | **9 test đỏ** (W3.2: 2, W6.3.1: 2, W6.3.2: 5) | **22 test đỏ** (W3.2: 9, W6.3.1: 4, W6.3.2: 8, W6.3.4: 1) |
| `tests/test_w642_answer_check.py` (25 test) | 25/25 | 12 đỏ (đúng dự kiến: các test này khóa luật so khớp số) | 15 đỏ, 3 lỗi |
| Runner giả 250 ca | 250/250; 2 lượt bị sửa (`done_claim`, `fee_amount`) | 250/250; 1 lượt bị sửa (`done_claim`) | 250/250; 0 lượt bị sửa |
| 32 kịch bản W3.2 | 32/32 | 32/32 | **31/32**: đỏ `policy_uncited_promise_is_removed_by_the_server` |
| 12 kịch bản W4 | 12/12 | 12/12 | 12/12 |

Nhận xét:
- 250 ca đóng băng không có ca nào chấm trực tiếp việc bộ kiểm xóa câu: với model giả theo kịch bản, gỡ hẳn vẫn đạt 250/250. Tác dụng của bộ kiểm chỉ lộ ra với model thật.
- Các test đỏ ở B là test khóa đúng các luật bị bỏ. Ví dụ "Thời hạn đổi trả là 30 ngày" và "Phí ship đơn này là 20.000đ" (sai số) phải bị xóa; ở B chúng lọt qua.
- C làm đỏ thêm các test khóa luật khẳng định đã làm: hủy, hoàn tiền, chuyển nhân viên.

## 6. Các hướng đang cân nhắc

| Hướng | Nội dung | Ưu | Nhược |
|---|---|---|---|
| **A. Giữ, vá tiếp** | Sửa lỗi đọc năm thành tiền; thêm `late_by_hours` vào bản tóm tắt `list_orders` hoặc suy số giờ trễ từ ngày | Không đổi hành vi đã đo, ít test cũ phải sửa | Đã vá 6 lần ở nhóm so khớp số; regex ngày tháng, số tiền tiếng Việt còn nhiều dạng chưa gặp |
| **B. Thu hẹp** | Bỏ 3 luật so khớp số; giữ khẳng định đã làm và lời hứa chính sách rõ chữ | Hết nguồn của 6/8 lần xóa nhầm; code gọn | Một thời hạn chính sách bịa ("đổi trong 30 ngày") hay số phí ship sai sẽ không bị chặn; phải sửa test cũ và ghi quyết định |
| **C. Gỡ hẳn** | Không kiểm câu trả lời | Đơn giản nhất | Mất chặn "em đã hủy đơn / đã hoàn tiền / đã chuyển nhân viên" trong khi chat không bao giờ tự đổi đơn; mất một lớp phòng thủ của các ca AgentDojo |
| **D. Model kiểm trong luồng** | Model nhỏ hoặc cross-encoder kiểm số liệu, trả Đúng/Sai (DeepSeek gợi ý) | Không cần regex | Thêm độ trễ và chỗ hỏng; Colab free không ổn định; container 512 MB; không tái lập, CI không có model; model nhỏ yếu so số và tiếng Việt |
| **E. Chấm ngoại tuyến** | Kết hợp với A/B/C: sau lượt đo, DeepSeek đọc câu trả lời và kết quả tool, trả JSON lỗi số liệu | Đo được tỉ lệ bịa số và độ chính xác của bộ kiểm; không ảnh hưởng production | Tốn một ít DeepSeek; không chặn được lúc chạy |
| **F. Khẳng định có cấu trúc** | Model xuất câu trả lời kèm danh sách khẳng định trỏ về trường tool; code so khớp | Chính xác, giải thích được | Đổi `SYSTEM` và định dạng đầu ra; phải đo lại; quá lớn trước 19/12 |

**Lỗi quá 4 tool mỗi bước (F48), các cách:**
- (i) chạy 4 tool đầu, trả cho model một kết quả lỗi cho phần thừa ("chỉ chạy tối đa 4 tool mỗi bước, gọi tiếp ở bước sau");
- (ii) không chạy tool nào, trả lỗi cho mọi tool để model gọi lại;
- (iii) nâng giới hạn (ví dụ 6) mà vẫn trong trần 10 tool mỗi lượt;
- (iv) ghi giới hạn vào `SYSTEM` hoặc mô tả tool.

Các cách này kết hợp được.

**Ý kiến hiện tại của Claude** (để Carbon phản biện): B cộng E cộng F48 cách (i)+(iv). Claude từng nói "nhóm khẳng định đã làm chưa xóa nhầm lần nào"; câu đó **sai**: F31 và F35 thuộc nhóm này, đều đã sửa.

## 7. Câu hỏi cho Carbon

1. Trong bối cảnh khóa luận (đo tái lập, 5 tuần, model 9B và DeepSeek), nên **giữ và vá (A)**, **thu hẹp (B)**, hay **gỡ hẳn (C)** `answer_check`? Có hướng nào tốt hơn cả ba không?
2. Nếu thu hẹp: luật nào giữ, luật nào bỏ? Có luật nào nên chuyển từ "xóa câu" sang "chỉ ghi vào trace" (không xóa, để đo)?
3. Với lời hứa thời hạn bịa ("đổi trong 30 ngày") và số phí sai: chấp nhận rủi ro, giữ một luật hẹp hơn, hay chuyển sang chấm ngoại tuyến (E)?
4. Lỗi quá 4 tool mỗi bước: chọn cách nào trong (i)–(iv)? Có cần đổi câu "Independent lookups may be requested together in one step" trong `SYSTEM` không? Lưu ý `SYSTEM` dài 5.993 ký tự, khi có focus tối đa là 6.284, trần 6.400: chỉ còn khoảng 116 ký tự.
5. Lịch sử hội thoại không giữ lượt gọi tool, nên model gọi lại tool đã có. Có nên xử lý trong đợt này không, hay để W6.5?
6. Trình bày trong khóa luận: có nên đo **có/không** `answer_check` như một cấu hình đối chứng (ablation) trên tập con 100 ca? Nên dùng chỉ số gì (tỉ lệ đạt, tỉ lệ câu khẳng định sai lọt qua, tỉ lệ xóa nhầm)?
7. Rủi ro của hướng được chọn với các ca an toàn (AgentDojo, S09 "giả hệ thống duyệt hoàn tiền")?
8. Claude và owner đang bỏ sót điều gì?

## 8. Mẫu trả lời mong muốn

1. **Đề xuất** (một câu) và mức tự tin.
2. **Lý do**, có dẫn chứng từ tài liệu này hoặc từ code đã đọc.
3. **Danh sách thay đổi cụ thể:** tệp, hàm, luật nào giữ/bỏ; cách xử lý lỗi quá 4 tool.
4. **Test** cần thêm, test cũ nào phải sửa và vì sao.
5. **Số đo** cần có trước/sau, và cách đưa vào khóa luận.
6. **Rủi ro** còn lại và cách theo dõi.
7. **Điểm chưa chắc**, cần owner quyết.

Trả lời bằng tiếng Việt. Không viết code hoàn chỉnh; chỉ mô tả thay đổi đủ để executor làm theo.

## 9. Tệp để đọc (chỉ đọc)

Repo chính: `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le`. Đọc theo `origin/main`, ví dụ `git show origin/main:retailops/workflow/answer_check.py`. Không checkout, không đổi nhánh, không sửa gì.

| Tệp | Đọc gì |
|---|---|
| `retailops/workflow/answer_check.py` | toàn bộ (393 dòng) |
| `agent_protocol.py` | dòng 25–60 (ngân sách, `SYSTEM`), 370–420 (`assistant_message`) |
| `retailops/workflow/agent.py` | dòng 130–250 (vòng gọi model và tool, xử lý lỗi) |
| `retailops/business/application.py` | dòng 700–730 và 1340–1375 (chỗ gọi `check_final_answer`) |
| `retailops_tools.py` | dòng 128–175 (bản tóm tắt `list_orders`) |
| `tests/test_r1_w3_2_answer_check.py`, `tests/test_r1_w6_3_1_hotfix.py`, `tests/test_r1_w6_3_2_hotfix.py`, `tests/test_r1_w6_3_4_answer_check.py`, `tests/test_w642_answer_check.py` | hành vi đang được khóa bằng test |
| `docs/phase_role_aware_ops/W0_OWNER_DECISION_DELTA_2026-10-29.md` | quyết định W3.2-D3, W3.2-D11 (tìm theo mã) |

Tài liệu chưa lên `main`, đọc tại worktree `D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/`: `docs/phase_role_aware_ops/W6_BACKLOG_2026-11-06.md` (F29–F47), §32 trong `W0_OWNER_DECISION_DELTA_2026-10-29.md`, thư mục `docs/phase_role_aware_ops/W6_4_2_answer_check_fix/`.

## 10. Prompt owner dán vào Antigravity

```text
Bạn là người tư vấn độc lập (Gemini 4 Carbon). Đọc tài liệu tham vấn tại:
D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le/.claude/worktrees/cai-nay-la-sao-bddcef/docs/phase_role_aware_ops/W6_4_3_answer_check_consult/README.md

Đọc thêm các tệp ở mục 9 của tài liệu đó, trong repo D:/year_2026/Work_2026/agentic_AI/CSKH_ban_le, CHỈ theo origin/main (git show origin/main:<đường dẫn>). Không checkout, không đổi nhánh, không sửa, không tạo tệp, không commit, không chạy test hay script, không gọi model hay API trả phí, không truy cập EC2 hay Colab.

Trả lời 8 câu hỏi ở mục 7 theo mẫu ở mục 8, bằng tiếng Việt, có dẫn chứng (tệp và dòng). Phản biện cả ý kiến của Claude ở mục 6. Nếu thấy tài liệu sai so với code, chỉ ra chỗ sai.
```
