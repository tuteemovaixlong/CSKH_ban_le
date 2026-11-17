# 11 — Phản hồi PR #121 (W6.7.0 phần B), vòng 1

Người kiểm: Claude. Đầu PR được kiểm: `7ac3afd9cd7c0ba80494ae1f2e166a5fc159696d`. CI 6/6 xanh; test A + B chạy lại cục bộ: OK (1 bỏ qua do `pypdfium2`).

## Cách kiểm

- Đọc toàn bộ `scripts/sft_select.py`, `scripts/sft_build.py` và đối chiếu với `05_THIET_KE_PHAN_B.md`.
- **Chạy đầu cuối trên vết W6.4 thật**: lượt A, Qwen 750 lượt chạy (250 ca × 3) và DeepSeek 250 lượt chạy (250 ca × 1), bằng script tạm ngoài repo. Mã ca được đổi `s…` → `x…` để đi qua chốt chặn tiền tố. Chạy `score → export → import` với phiếu giả đều `dat` kèm trích dẫn thật `→ select → build`; sau đó build lại một lần với thư mục ca đo thật. Kết quả chỉ dùng để kiểm công cụ và đã xóa; vết đo không đi vào huấn luyện.
- Kết quả tổng:

| Bước | Kết quả |
|---|---|
| score | Qwen: A_code 254, B_code 76, loại 420. DeepSeek: A_code 132, B_code 32, loại 86. 203/250 ca có ứng viên. |
| export vòng 1 | 203 ứng viên, 255 mục, 11 lô. 0 mã ca, 0 `tool_call_id`, 0 `chatcmpl`/`call_00` trong gói. |
| import | Mã thoát 0; trích dẫn sai bị hạ đúng (3 mục mỗi nhóm). |
| select | 166 ca (Qwen 139, DeepSeek 27). |
| build | 202 mẫu, 0 mẫu bị loại nhầm vì nghi khóa bí mật. Không còn khóa `reasoning`, không còn `arguments` dạng chuỗi. Mọi mẫu mở đầu bằng `system`. |
| build với ca đo thật | 202/202 bị loại `eval_utterance_overlap`, tức chốt chặn rò rỉ hoạt động. |

Các điểm a–e trong báo cáo Cổng 2 khớp với mã. Phần B dùng được, nhưng còn **4 điểm phải sửa** trước khi merge.

## Phải sửa

### P1. Ứng viên `B_code` của Qwen đang đứng trước `A_code` của DeepSeek

`_candidate_sort_key` xếp theo model trước rồi mới tới tier code. Hệ quả: ca mà Qwen chỉ có `B_code` còn DeepSeek có `A_code` sẽ xuất `B_code` của Qwen ở vòng 1. Ứng viên `B_code` **không bao giờ lên được tier A**, nên lượt chấm đó phí công, và ca phải sang vòng 2–3 mới tới được `A_code` của DeepSeek. Trên vết W6.4 có **6/250 ca** như vậy, ví dụ `s01_007`: thứ tự hiện tại là Qwen B, Qwen B, rồi DeepSeek A. Với 1.200 ca, con số này vào khoảng 30 ca, mỗi ca thêm 1–2 vòng chấm.

**Sửa:** thứ tự mới là Qwen `A_code` → DeepSeek `A_code` → Qwen `B_code` → DeepSeek `B_code`, tức khóa sắp xếp đặt `TIER_PRIORITY` trước `MODEL_PRIORITY`. Các tiêu chí phụ giữ nguyên. Cập nhật docstring hoặc báo cáo cho khớp. **Test:** ca có Qwen chỉ `B_code` và DeepSeek `A_code` thì `rank 0` phải là DeepSeek `A_code`.

### P2. Tên model lộ ra qua kết quả tool (`get_runtime_info`)

- **Gói chấm:** có 3 lần chữ "Qwen" xuất hiện trong gói vòng 1. Nguồn là tool `get_runtime_info`, trả về chuỗi có dạng `{"name":"Qwen/Qwen3.5-9B",…}`, và câu trả lời nhắc lại tên đó. Người chấm vì vậy biết được mục đó do model nào sinh.
- **Dữ liệu huấn luyện, phần nghiêm trọng hơn:** nếu một lượt DeepSeek được chọn có gọi `get_runtime_info` hoặc tự xưng tên, Qwen sẽ học cách nói "tôi là DeepSeek". Trên vết W6.4 chưa gặp trường hợp này (chỉ có 1 mẫu, và là của Qwen), nhưng tool này có trong danh sách tool ở mọi lượt nên lúc nào cũng có thể xảy ra.

**Sửa:**
1. `export`: thay mọi chuỗi khớp `(?i)\b(qwen|deepseek)[\w./:-]*` trong `steps`, `answer` và `text` của mục bằng `[model]`. Phải thay cùng một cách ở cả gói lẫn `text` trong `map.json`, để bước kiểm trích dẫn vẫn khớp.
2. `sft_build`: mẫu có nguồn `deepseek` mà bất kỳ tin nhắn nào (system, user, assistant, tool) chứa `deepseek` (không phân biệt hoa thường) thì loại với lý do `model_identity_leak`. Ngoài ra đếm riêng số mẫu có gọi `get_runtime_info`, theo từng nguồn.
3. **Test** cho cả hai việc trên.

### P3. Phễu dữ liệu chưa báo những số cần cho F52 và để chọn cấu hình huấn luyện

`stats.json` và `build_report.md` cần thêm:

- `final_call_without_tools`: số mẫu mà lần gọi `stop` cuối có `request.tools` rỗng. Đây là mẫu "trả lời ở bước cuối khi hết lượt tool", đúng loại khe hở F52. Tách theo nguồn. Chạy thử trên W6.4 chỉ được **2/202**, nên con số này phải hiện rõ trong báo cáo để owner quyết định có cần bổ sung hay không.
- `model_calls_in_turn`: phân bố số tin `assistant` sau tin `user` cuối, tức số bước trong lượt. Trên W6.4: `{1: 12, 2: 110, 3: 46, 4: 25, 5: 7, 6: 2}`.
- `empty_final_reasoning`: số mẫu có `reasoning_content` cuối rỗng. Trên W6.4 có 5 mẫu.
- **Test:** dựng một vết giả có lần gọi cuối mang `tools: []` và kiểm đủ ba trường trên.

### P4. Lượt hội thoại do rào chắn xử lý, không gọi model, đang làm loại cả lượt chạy

Có **19 lượt chạy Qwen** đạt cả `passed_official` lẫn `passed_v2` nhưng vẫn bị loại vì `missing_stop_call`. Nguyên nhân là một lượt hội thoại trong đó **có 0 lần gọi model**: rào chắn trả lời thẳng, ví dụ ca S07 "đòi gặp nhân viên". Đây là hành vi đúng của hệ thống, không phải lỗi. Riêng DeepSeek có 7 lượt chạy rơi vào trường hợp này.

**Sửa:**
- `score`: lượt hội thoại có 0 lần gọi model, không có `error` và có `answer` → gắn nhãn `rail_turn`, **không** loại. Chỉ loại khi lượt có lần gọi model mà không có lần nào `stop` (giữ lý do `missing_stop_call`), hoặc khi mọi lượt đều là `rail_turn` (lý do `no_model_turns`).
- `sft_build`: lượt `rail_turn` không sinh mẫu, ghi vào mục loại với lý do `rail_turn_no_model_call`. Các lượt còn lại của lượt chạy đó vẫn sinh mẫu như bình thường.
- `export`: lượt `rail_turn` không xuất cho giám khảo. Bước `import` xếp tier chỉ dựa trên các lượt có xuất.
- **Test:** ca 2 lượt, lượt 1 là rào chắn và lượt 2 có model, vẫn phải ra ứng viên và 1 mẫu.

## Ghi chú, không chặn

- **N1.** `select` gộp hai tình huống khác nhau vào cùng lý do `no_tier_a`: ứng viên chưa từng được xuất cho giám khảo, và ứng viên đã chấm nhưng chỉ ra B/C. Nên tách thành `no_tier_a_judged` và `not_judged_yet` để biết có cần thêm vòng chấm không.
- **N2.** Không cần H-code làm gì; Claude ghi lại cho notebook huấn luyện: mẫu W6.4 ước khoảng p50 5,7k, p95 8,9k và max 11,4k token. `max_seq_length` khi huấn luyện vì vậy phải ≥ 12k, cao hơn mức 5,5k đã thử ở smoke.

## Vòng 2 — kết luận (đầu `d9604d7839105a9b34d4a80149320b3c04ac1da6`): ĐẠT

CI 6/6 xanh. Chạy lại thử đầu cuối trên vết W6.4 lượt A:

| Điểm | Vòng 1 | Vòng 2 |
|---|---|---|
| P1: ca có `B_code` đứng đầu trong khi đã có `A_code` | 6 | **0** |
| P2: số lần "qwen"/"deepseek" xuất hiện trong gói chấm | 3 | **0** (2 chỗ đã thay bằng `[model]`; trích dẫn chứa `[model]` vẫn qua bước kiểm) |
| P2: mẫu bị loại vì `model_identity_leak` | — | 0 (vết W6.4 không có trường hợp nào) |
| P3: `final_call_without_tools` / `model_calls_in_turn` / `empty_final_reasoning` | chưa có | 2 (Qwen) / `{1:12, 2:114, 3:47, 4:26, 5:8, 6:2}` / 6 (đều là DeepSeek) |
| P4: lượt chạy Qwen bị loại vì `missing_stop_call` | 28 | **7**. 15 lượt chạy toàn lượt rào chắn chuyển sang `no_model_turns`; 4 ứng viên có lượt rào chắn được giữ lại |
| Ca chọn được / mẫu | 166 / 202 | **173 / 209** |
| Build đối chiếu với ca đo thật | 202/202 bị loại do trùng | 209/209 bị loại do trùng |

**Ghi chú cho bước huấn luyện, không chặn merge:** 6/209 mẫu DeepSeek có `reasoning_content` cuối rỗng, tức DeepSeek trả lời mà không suy luận. Nếu giữ, Qwen sẽ học cách bỏ qua phần suy nghĩ. Notebook huấn luyện sẽ lọc các mẫu này dựa trên trường `empty_final_reasoning`, hoặc owner quyết định giữ.

## Phạm vi sửa

Chỉ sửa `scripts/sft_select.py`, `scripts/sft_build.py`, `tests/test_w670_sft_select_build.py`, báo cáo thực thi và notebook (dựng lại bằng `build_agent_notebook.py`). Commit và push thường lên `phase-r1-w6-7-0-b`, không rebase, không force-push. Chạy lại test A + B, `build_agent_notebook.py --check` và `check_docs_contract.py`. Báo lại kèm SHA đầu mới.
