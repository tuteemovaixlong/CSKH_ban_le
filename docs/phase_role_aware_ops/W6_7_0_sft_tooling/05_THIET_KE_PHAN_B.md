# 05 — Thiết kế phần B: chọn lượt, xếp tier, dựng tập SFT

Đầu vào sau khi owner chạy (notebook do Claude làm): tệp ca đã điền lời khách; thư mục kết quả Qwen (runner `--repeat 4`) và DeepSeek (`--repeat 2`), mỗi thư mục có `merged.json`, `shard-*.jsonl` (vết), `manifest.json` — cùng định dạng thư mục đo W6.4.

## B1. `scripts/sft_select.py`

### `score`

```text
python scripts/sft_select.py score --cases <cases_sft_v1_filled.jsonl> --run qwen=<thư mục> --run deepseek=<thư mục> --out scores.json
```

Với mỗi `(case_id, model, run)`:
- `passed_official` (báo cáo runner) và `passed_v2` (dùng lại `eval_regrade.regrade_record` với ca huấn luyện làm `case`);
- cờ: lượt nào có `answer_check` (đã xóa câu) → `dropped`; có `answer_check_audit` → `audit`; gọi tool trùng (cùng tên + cùng tham số trong một lượt, đọc từ `tool_calls` của vết) → `duplicate_tool`; bất kỳ lần gọi nào `finish_reason == "length"` hoặc lỗi → **loại**;
- số liệu xếp hạng: tổng số lời gọi tool, tổng `completion_tokens`, độ dài câu trả lời.

**Tier code:** `A_code` = `passed_official` và `passed_v2` và không cờ; `B_code` = đạt nhưng có cờ; còn lại loại.

**Thứ tự ứng viên mỗi ca:** Qwen trước DeepSeek; trong cùng model: `A_code` trước `B_code`, ít tool hơn, ít `completion_tokens` hơn, câu trả lời ngắn hơn.

### `export` (gói giám khảo, cùng quy ước W6.4.4)

```text
python scripts/sft_select.py export --scores scores.json --out <thư mục chấm> --round 1   # vòng 1: ứng viên đứng đầu mỗi ca
python scripts/sft_select.py export --scores scores.json --out <thư mục chấm vòng 2> --round 2 --after <adjudicated vòng 1>  # ca chưa có tier A: ứng viên kế tiếp
```

- Chỉ xuất ứng viên `A_code`/`B_code`. Mỗi mục là **một lượt hội thoại** của ứng viên: lời khách (các lượt), từng bước của trợ lý (phần suy nghĩ, lời gọi tool + tham số, kết quả tool cắt 3.000 ký tự), câu trả lời cuối.
- Câu hỏi (dat = mẫu tốt): *"Phần suy nghĩ và câu trả lời có nhất quán với các lời gọi tool và kết quả tool không, và có tránh khẳng định dữ kiện/chính sách không có trong kết quả tool không?"*
- Ẩn danh như W6.4.4: không tên model, không mã ca, `item_id` ngẫu nhiên, `map.json` riêng; nhóm A và B độc lập; dùng lại hướng dẫn chấm dạng [`../W6_4_4_regrade_judge/04_HUONG_DAN_CHAM.md`](../W6_4_4_regrade_judge/04_HUONG_DAN_CHAM.md) với phần bổ sung cho câu hỏi này (viết trong `scripts/sft_select.py --print-rubric` hoặc tệp `docs/…/W6_7_0_sft_tooling/10_HUONG_DAN_CHAM_TIER.md` do H-code soạn, Claude duyệt).

### `import`

```text
python scripts/sft_select.py import --judge-dir <thư mục chấm> --scores scores.json --out adjudicated_round1.json
python scripts/sft_select.py select --scores scores.json --adjudicated adjudicated_round1.json [adjudicated_round2.json] --out selection.json
```

- Dùng lại `eval_regrade.read_verdicts`, `effective` (kiểm trích dẫn bằng code), `kappa`.
- **Tier A** = `A_code` và cả hai nhóm `dat` với trích dẫn hợp lệ. Có nhóm `khong_dat` (trích dẫn hợp lệ) → **C**. Còn lại (bất đồng, `khong_chac`, `B_code`) → **B**.
- **Chọn mỗi ca:** ứng viên tier A đầu tiên theo thứ tự ứng viên (Qwen trước). Không có A → bỏ ca (tùy chọn `--allow-b` lấy B và gắn cờ). Một ca chọn **một** lượt chạy (mọi lượt hội thoại của lượt chạy đó).
- `selection.json` + `selection_report.md`: số ca có mẫu, tỉ lệ Qwen/DeepSeek, theo bộ, theo khung, độ khớp A–B, số ca bị bỏ và lý do.

## B2. `scripts/sft_build.py`

```text
python scripts/sft_build.py --selection selection.json --cases <tệp ca> --out-dir <thư mục> [--val-ratio 0.1] [--seed 20261203]
  → train.jsonl, val.jsonl, stats.json, build_report.md
```

**Một mẫu cho mỗi lượt hội thoại** của lượt chạy được chọn. Lấy lần gọi model **cuối cùng có `finish_reason == "stop"`** của lượt đó trong vết:

```json
{"messages": [<request.messages giữ nguyên thứ tự: system, user, assistant (tool_calls), tool, …>,
              {"role": "assistant", "content": "<response.content>", "reasoning_content": "<response.reasoning>"}],
 "tools": <request.tools>,
 "meta": {"case_id": "t04_137_…", "template": "…", "suite": "T04", "turn": 1, "source_model": "qwen|deepseek",
          "run": 2, "tier": "A", "style": "teencode", "repo_sha": "<từ provenance>"}}
```

- Mọi tin `assistant` trong `request.messages`: đổi khóa `reasoning` → `reasoning_content` (định dạng chat template Qwen3.5); `tool_calls[].function.arguments` **chuyển từ chuỗi JSON sang object**; không parse được → loại mẫu, ghi lý do.
- Giữ nguyên system prompt, mô tả tool và lịch sử như runner đã gửi (đây là điều đảm bảo "khớp hệ thống"). Không sửa, không rút gọn nội dung.
- **Chặn rò rỉ đo:** loại mẫu có `case_id` bắt đầu bằng `s`; loại mẫu có lời khách trùng (chuẩn hóa) với bất kỳ `user` nào của 250 ca; quét chuỗi giống khóa (`sk-…`, `Bearer …`) → loại và báo.
- **Tách train/val theo khung**: ~10% khung (theo seed) vào val; mọi mẫu của một khung nằm cùng một phía.
- `stats.json`: số mẫu, số ca, theo bộ, theo nguồn (Qwen/DeepSeek), số lượt; độ dài mỗi mẫu tính bằng ký tự (p50/p95/max) và ước token (ký tự / 3,2 — chỉ để chọn GPU; Claude đo lại bằng tokenizer thật trên Colab).

## B3. Test (`tests/test_w670_sft_select_build.py`)

Thư mục kết quả giả tự dựng (2 ca × Qwen 4 lần + DeepSeek 2 lần, có lượt hỏng, lượt có cờ, lượt `length`):
- `score` xếp tier code và thứ tự ứng viên đúng (Qwen trước; A trước B; ít tool hơn).
- `export` không lộ tên model/mã ca; `import` kiểm trích dẫn, gộp bảo thủ; `select` lấy Qwen tier A khi có, DeepSeek khi Qwen không có A, bỏ ca khi không ai có A.
- `sft_build`: đổi `reasoning` → `reasoning_content`, `arguments` thành object, lấy đúng lần gọi `stop` cuối của lượt, tách train/val theo khung, loại mẫu `s…` và mẫu trùng lời khách ca đo, báo thống kê.
