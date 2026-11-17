# 03 — Thiết kế phần A: dữ liệu `sft_v1`, runner, bộ sinh khung ca, lời khách

## A1. `scripts/build_sft_fixture.py`

Tái hiện đúng nguyên mẫu ở [01](01_HIEN_TRANG.md), tất định:

```text
python scripts/build_sft_fixture.py --out data/demo_events/store_events_sft_v1.jsonl
  (mặc định --seed 20261201 --days 30 --merchant-id MERCHANT-SIM-001)
```

1. Thư mục làm việc tạm; `marketplace_sim` `init` với seed và merchant trên (gọi module hoặc `python -m marketplace_sim`, không sửa package).
2. Sửa bảng `sim_meta` trong `sim.sqlite3`: `next_customer_no=5001`; `next_order_no`, `next_shipment_no`, `next_payment_no`, `next_refund_no`, `next_voucher_no` `=50001`; `next_story_no=501`.
3. `run --days 30`; chạy lần lượt đủ 13 tên trong `marketplace_sim.stories.STORY_NAMES`; `export`.
4. Ghi `…_sft_v1.meta.json`: seed, days, merchant, bộ đếm, danh sách story, số sự kiện theo loại, số đơn, số khách, SHA-256 của tệp sự kiện, lệnh dựng.
5. Tự kiểm và dừng nếu sai: không mã đơn/khách nào trùng `data/demo_events/store_events.jsonl`; số đơn trong khoảng 100–160.

Commit cả tệp sự kiện và tệp mô tả (cỡ ~2.000 dòng như tệp chuẩn).

## A2. Runner (`scripts/run_agent_scenarios.py`) — chỉ thêm nhánh

- `FIXTURES['sft_v1'] = 'store_events_sft_v1.jsonl'`.
- `_provision_demo_template`: với `sft_v1`, `provision_tenant('shop-scenarios', …, seed_demo=False)` rồi làm **đúng các bước của `BusinessStore.seed()`** (đọc hàm đó; hiện là thêm khách `manager`/`system`, `seed_catalog`, rồi nạp sự kiện) nhưng gọi `seed_demo_store_events(store, jsonl_path=ROOT / 'data/demo_events/store_events_sft_v1.jsonl')`. Không sửa `BusinessStore.seed()`.
- `load_dataset(path)`: nếu ca có `meta` **và** `id` bắt đầu bằng `t` → kiểm bằng `scripts.sft_dataset.validate_train_case`; mọi trường hợp khác giữ nguyên đường cũ.
- Không đổi `--dataset-dir` (chỉ cho S01–S12), không đổi chấm điểm. Mọi ca huấn luyện chạy qua `--dataset <tệp ca>` + `--only-file` như bộ đo.

## A3. `scripts/sft_dataset.py`

- `validate_train_case(case)`:
  - `id` khớp `t(0[1-9]|1[0-2])_[0-9]{3}_[a-z0-9_]+`, dài ≤ 60; `category == id[:3]`; `meta.suite == category.upper()` (T01…T12);
  - `fixture == 'sft_v1'`; `meta.split == 'train'`; `meta.origin == 'sinh_sft'`; `meta.template` là khung đã đăng ký; `meta.style` thuộc `STYLES` của `eval_dataset_v2` (`chuan`, `teencode`, `khong_dau`, `sai_chinh_ta`, `dai`);
  - phần cấu trúc còn lại (turns, `expect`, `fake_model`, `final_state`, Trợ lý ca…) kiểm bằng **chính `eval_dataset_v2.validate_case`** trên một bản sao đã chuẩn hóa (`id`/`category`/`meta.suite` đổi `t`→`s`, `split` → `dev`, `origin` → `mo_phong`, bỏ `meta.template`, `fixture` → `standard`). Không sửa `eval_dataset_v2.py`.
  - `customer` có trong tệp sự kiện `sft_v1`.
- `validate_train_set(cases)`: `id` duy nhất; mỗi khung ≤ 15 ca; lời khách (sau khi điền) không trùng chuẩn hóa với bất kỳ `user` nào của 250 ca.

## A4. Bộ sinh khung ca: `scripts/sft_cases.py` + `scripts/sft_templates/`

```text
python scripts/sft_cases.py generate --out <thư mục ngoài repo> [--pilot 100] [--seed 20261202]
  → cases_sft_v1.jsonl (lời khách là chỗ trống), briefs_sft_v1.jsonl, generate_report.md
python scripts/sft_cases.py check --out <thư mục>      # chạy runner --fake trên mọi ca, phải đạt 100%
```

**Khung ca** (`scripts/sft_templates/tNN_*.py`, đăng ký trong `scripts/sft_templates/__init__.py`): mỗi khung là một đối tượng có
- `template_id`, `suite` (T01–T12), `target` (số ca), danh sách giọng được dùng;
- `select(view)` → danh sách "chỗ dữ liệu" phù hợp (ví dụ: đơn `pending` của một khách; đơn đã giao 3–6 ngày; đơn đã giao 9–14 ngày; đơn trễ quá 48 giờ chưa có voucher; hoàn tiền thất bại; đơn COD đang giao; sản phẩm thiếu trường giặt ủi…);
- `build(slot, rng)` → một ca: `turns[].expect`, `turns[].fake_model`, `final_state`, `knowledge`, `title`, `meta.source_note`, cộng **phiếu lời khách** cho từng lượt.

**`view` lấy dữ kiện bằng chính đường mà tool của agent dùng**: dựng tenant mẫu `sft_v1` qua `_provision_demo_template('sft_v1', …)` của runner, rồi đọc đơn/sản phẩm/vận đơn bằng các hàm đọc mà tool `get_order`, `list_orders`, `track_shipment`, `get_product`, `check_inventory`… gọi (tìm trong code; chỉ đọc). **Không tự tính lại** hạn trả, hạn đổi, giờ trễ, quyền hủy — lấy từ đúng trường hệ thống trả cho model (ví dụ `can_open_return`, `within_return_window`, `days_since_delivery`, `late_by_hours`). Tuổi đơn không phụ thuộc ngày chạy (đồng hồ dời về "bây giờ").

**Kỳ vọng (`expect`)**: theo đúng các khóa của bộ đo (`tools_called`, `tools_any`, `tools_not_called`, `max_tool_calls`, `action`, `order_action`, `human_support`, `answer_any`, `answer_all`, `answer_not`, `sources`, `attack_not`…), suy từ luật chính sách (`data/knowledge/`) và trường hệ thống. Được phép dùng **cùng kiểu kỹ năng** với ca đo (đó là thứ cần học) và cùng kiểu nhóm cụm; **không** chép `title`, `user` của ca đo.

**`fake_model`**: lời gọi tool và câu trả lời mẫu thỏa `expect` (dùng `{{last_tool.…}}` như bộ đo, trích dẫn bằng `citation_id` thật của `search_knowledge`). Dùng để kiểm `expect` khớp dữ liệu (`check` phải đạt 100%); **không** dùng làm mẫu huấn luyện.

**Phiếu lời khách** (một dòng mỗi lượt): `{brief_id, case_id, turn, suite, template, style, persona, intent, must_include[] (mã đơn, tên SP…), may_include[], must_not_include[] (cụm trả lời của expect và mọi dữ kiện khách không thể biết), earlier_turns[] (lời khách các lượt trước, tóm tắt việc trợ lý đã làm), length (ngắn/vừa/dài), notes}`. Ca chèn lệnh có thêm `injection` (nội dung kẻ tấn công cần chèn nguyên văn). Trợ lý ca (T11) không có lời khách ở lượt nhân viên; phiếu dành cho **tin nhắn của khách trong `case_setup`** và nội dung tệp/tin nhắn chèn.

**Phân bổ và đa dạng**: theo [04](04_DANH_MUC_KHUNG_CA.md); mỗi khung ≤ 15 ca; giọng theo tỉ lệ `STYLES`; không lặp cùng (khung, đơn, ý định); `--pilot 100` lấy phân tầng theo bộ (mỗi bộ tối thiểu 5).

## A5. Lời khách: `scripts/sft_utterances.py`

```text
python scripts/sft_utterances.py fill --dir <thư mục generate> --endpoint https://api.deepseek.com/chat/completions \
    --model deepseek-flash --concurrency 8 [--allow-peak] [--limit N]
  → cases_sft_v1_filled.jsonl, utterances_cache.jsonl, utterances_report.md
```

- Khóa từ `DEEPSEEK_API_KEY`; chỉ `urllib`; ghi đệm sau mỗi câu (chạy tiếp được); không in khóa.
- **Chặn giờ cao điểm**: giờ Việt Nam (UTC+7) thứ Hai–thứ Sáu 13:00–17:00 → dừng với thông báo, trừ khi `--allow-peak`.
- Lời nhắc (tiếng Việt, cố định, ghi trong code): vai "người viết lời khách cho bộ dữ liệu CSKH thương mại điện tử Việt Nam"; nhận phiếu JSON; trả **chỉ** JSON `{"user": "..."}`; viết đúng giọng (`khong_dau` không dấu; `teencode` viết tắt kiểu chat; `sai_chinh_ta` vài lỗi gõ tự nhiên; `dai` 3–6 câu kể lể); bắt buộc chứa `must_include`; không chứa `must_not_include`; không nói thay trợ lý; không nhắc tới AI/hệ thống/prompt (trừ ca chèn lệnh, khi đó chèn `injection` nguyên văn); temperature 1.0.
- **Kiểm bằng code** mỗi câu: đủ `must_include` (mã đơn đúng nguyên văn); không có `must_not_include` (so bằng `eval_regrade.v2`); độ dài theo phiếu; `khong_dau` không có ký tự có dấu; độ giống với **mọi** `user` của 250 ca: Jaccard 5-gram ký tự ≤ 0,45 và không chung chuỗi con ≥ 40 ký tự; với các câu khác cùng khung: Jaccard ≤ 0,7. Hỏng → gửi lại kèm lý do, tối đa 3 lần; vẫn hỏng → loại ca, ghi báo cáo.
- Ghi kết quả bằng cách thay chỗ trống `user` trong ca; ca Trợ lý ca ghi vào `case_setup`.

## A6. Test (`tests/test_w670_sft_fixture_cases.py`)

- Fixture: tệp đã commit khớp SHA trong `.meta.json`; 0 mã trùng tệp chuẩn; `_provision_demo_template('sft_v1')` dựng được và có đúng số đơn; fixture `standard` và `late_voucher_issued` cho kết quả như trước (so số đơn/khách với trước khi sửa).
- `validate_train_case`: ca hợp lệ qua; ca sai `id`/`split`/`origin`/`fixture`/`template` bị từ chối; ca đo (`s…`) vẫn đi đường `validate_case` cũ.
- Bộ sinh: `--pilot` nhỏ (ví dụ 24 ca) sinh được, qua kiểm, `check` (runner `--fake`) đạt 100%; mỗi khung ≤ 15; phân bổ đúng tỉ lệ.
- Lời khách: client giả; kiểm từng luật (thiếu mã đơn, lộ cụm đáp án, có dấu ở `khong_dau`, trùng ca đo) đều bắt được; chặn giờ cao điểm (giả đồng hồ); chạy tiếp từ đệm.
- Toàn bộ test cũ xanh; `scripts/eval_dataset_v2.py --final`/`validate_suites` 250 ca và SHA 12/12 như cũ.
