# 01 — Hiện trạng (mã `main` = `4cd3902`)

## Bộ đo và runner

- 250 ca đo: `evals/suites/S01.jsonl` … `S12.jsonl`, đóng băng (SHA 12/12). Mỗi dòng một ca: `id` (`sNN_NNN_mo_ta`), `category`, `title`, `fixture` (`standard` hoặc `late_voucher_issued`), `customer` (`SIM-C-xxxx`), `meta` (`suite`, `split` dev/held_out, `style`, `origin`, `vn_context`, `source_note`), `knowledge`, `turns[]` (`user`, `fake_model`, `expect`), `final_state`; Trợ lý ca (S11) thêm `actor: "staff_case_assist"`, `case_setup`, `turns[].mode`.
- Bộ kiểm định dạng ca: `scripts/eval_dataset_v2.py` (`validate_case`, `validate_suites`) — **chặt cho ca đo**: `id` phải `sNN_…`, `split` ∈ dev/held_out, `origin` ∈ mo_phong/tau2_retail/agentdojo, `fixture` ∈ FIXTURES của chính file đó.
- Runner `scripts/run_agent_scenarios.py`:
  - `FIXTURES` (khoảng dòng 72) và `_provision_demo_template(fixture_name, …)` (khoảng dòng 590): dựng một tenant mẫu bằng `provision_tenant(…, seed_demo=True)`; `seed_demo=True` gọi `BusinessStore.seed()` (`retailops/business/store.py` khoảng dòng 1212): thêm khách `manager`, `system`, `seed_catalog`, rồi `seed_demo_store_events(self)` với tệp mặc định `data/demo_events/store_events.jsonl`.
  - `seed_demo_store_events(bstore, *, sessions=None, jsonl_path=None, no_notices=False)` (`retailops/integration/demo_seed.py` khoảng dòng 156) **đã nhận đường dẫn tệp khác** và dời đồng hồ sự kiện về "bây giờ" (sự kiện mới nhất = lúc chạy) → tuổi đơn (số ngày từ lúc giao, số giờ trễ) **không phụ thuộc ngày chạy**.
  - `load_dataset(path)` (khoảng dòng 110): tệp có `meta` thì gọi `validate_case` (chặt cho ca đo).
  - `World` dựng mỗi ca một tenant tạm từ tenant mẫu; `run_scenario` chấm bằng `grade_turn` + `grade_final_state`.
  - `--trace-out` ghi mỗi lần gọi model: `case_id`, `run`, `turn`, `request` (`messages` gồm system/user/assistant có `tool_calls` và `reasoning`/tool; `tools`; tham số lấy mẫu), `response` (`content`, `reasoning`, `tool_calls`, `finish_reason`, `usage`). Khóa đã được che.
  - Báo cáo (`--out`): `scenarios[]` mỗi `(id, run)` với `passed`, `failures`, `turns[]` (`answer` đầy đủ từ #118, `answer_complete`, `answer_check`, `answer_check_audit`, `tools`, `action`, `error`), `attack_success`.
- Công cụ chấm lại `scripts/eval_regrade.py` (#118): `v2`, `regrade_record`, gói giám khảo ẩn danh, kiểm trích dẫn, gộp bảo thủ hai nhóm — **dùng lại** cho phần B.

## Sàn ảo (`marketplace_sim`)

`python -m marketplace_sim init --data-dir D --seed N --merchant-id ID` → `run --data-dir D --days N` → `story --data-dir D <tên>` (13 kịch bản trong `marketplace_sim/stories.py` `STORY_NAMES`) → `export --data-dir D --out F`. Bộ đếm mã (`next_customer_no`, `next_order_no`, `next_shipment_no`, `next_payment_no`, `next_refund_no`, `next_voucher_no`, `next_story_no`) nằm trong bảng `sim_meta` của `D/sim.sqlite3`, bắt đầu từ 1 (`DEFAULT_SEED = 20261106`).

## Nguyên mẫu Claude đã chạy (2026-11-16)

1. `init --seed 20261201 --merchant-id MERCHANT-SIM-001`; sửa `sim_meta`: khách bắt đầu 5001, đơn/vận đơn/thanh toán/hoàn tiền/voucher 50001, kịch bản 501.
2. `run --days 30`; chạy đủ 13 `story`; `export` → **2.011 sự kiện, 129 đơn, 92 khách** (bộ đo: 2.003 sự kiện, 128 đơn, 89 khách).
3. Mã đơn `SIM-O-50001…`, `SIM-O-ST-511…513`; **trùng mã đơn và mã khách với dữ liệu bộ đo: 0**.
4. Nạp vào tenant tạm bằng `provision_tenant(…, seed_demo=False)` + thêm `manager`/`system` + `seed_catalog` + `seed_demo_store_events(store, jsonl_path=…)`: 2.011 sự kiện nhận, 0 trùng, 129 đơn. **Không cần sửa `retailops/`.**
