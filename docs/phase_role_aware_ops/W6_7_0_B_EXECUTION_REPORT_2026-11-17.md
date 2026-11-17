# Báo Cáo Thực Thi W6.7.0 Phần B — Chọn Lượt, Xếp Tier Và Dựng Tập SFT

- **Ngày thực hiện:** 2026-11-17
- **Nhánh:** `phase-r1-w6-7-0-b` (tạo từ `origin/main` tại commit `20d623f`, sau khi PR #120 phần A được merge)
- **Mục tiêu:** Hoàn thiện công cụ phần B cho kế hoạch [W6.7](W6_7_sft_data/README.md): chọn lọc lượt chạy đạt từ Qwen3.5-9B và DeepSeek V4.1 Flash, xuất gói chấm ẩn danh 2 nhóm giám khảo có kiểm trích dẫn nguyên văn, xếp tier A/B/C và chọn 1 lượt mỗi ca (`scripts/sft_select.py`), dựng tập SFT định dạng chat template Qwen3.5 + tool + chặn rò rỉ đo/bí mật (`scripts/sft_build.py`), và bộ unit test ngoại tuyến (`tests/test_w670_sft_select_build.py`).

---

## 1. Danh Sách Tệp Đã Tạo Và Cập Nhật

| STT | Tệp | Trạng thái | Mô tả |
|---|---|---|---|
| 1 | `scripts/sft_select.py` | Tạo mới | CLI `--print-rubric`, `score`, `export` (vòng 1 và vòng 2 `--after`), `import` (tái sử dụng `eval_regrade.read_verdicts`, `effective`, `kappa` + kiểm trích dẫn cho cả `khong_dat`), và `select` (xuất `selection.json` + `selection_report.md`) |
| 2 | `scripts/sft_build.py` | Tạo mới | CLI dựng `train.jsonl`, `val.jsonl`, `stats.json`, `build_report.md` từ vết `shard-*.jsonl` của lượt chạy được chọn; chuẩn hóa `reasoning` → `reasoning_content`, `tool_calls[].function.arguments` → `dict`, giữ nguyên `system`/`tools`/lịch sử, tách train/val theo khung, chặn rò rỉ ca đo và khóa bí mật |
| 3 | `tests/test_w670_sft_select_build.py` | Tạo mới | Bộ unit test dùng dữ liệu giả trong `tempfile` (không đọc ổ ngoài, không gọi mạng), có guard `@unittest.skipUnless(HAS_PART_B, ...)` để an toàn trong Colab test bundle |
| 4 | `notebooks/colab_agent.ipynb` | Cập nhật | Đồng bộ gói test vào notebook Colab bằng `python scripts/build_agent_notebook.py` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`) |
| 5 | `docs/phase_role_aware_ops/W6_7_0_B_EXECUTION_REPORT_2026-11-17.md` | Tạo mới | Báo cáo thực thi phần B này |

---

## 2. Thiết Kế Và Điểm Kỹ Thuật Đã Triển Khai

### 2.1. `scripts/sft_select.py`
- **`--print-rubric`**: In đầy đủ hướng dẫn chấm tier SFT dựa trên quy ước `docs/phase_role_aware_ops/W6_4_4_regrade_judge/04_HUONG_DAN_CHAM.md`, bổ sung tiêu chí nhất quán suy luận (`reasoning`) – lời gọi tool (`tool_calls`) – kết quả tool (`tool_results`) – câu trả lời (`answer`), không bịa dữ kiện/chính sách ngoài kết quả tool, và quy tắc trích dẫn nguyên văn `MIN_QUOTE = 8` cho cả `dat` lẫn `khong_dat`.
- **`score`**:
  - Tải kết quả qua `eval_regrade.load_run` (`merged.json`, `manifest.json`, `shard-*.jsonl`) và chấm lại từng `(case_id, model, run)` bằng `eval_regrade.regrade_record`.
  - Gắn cờ: `dropped` (có `answer_check`), `audit` (có `answer_check_audit`), `duplicate_tool` (cùng tên tool + cùng tham số chuẩn hóa JSON trong cùng 1 lượt, đọc từ `response.tool_calls` trong vết).
  - Loại ngay (`rejected`) nếu có lần gọi `finish_reason == "length"` hoặc `response.error`, lượt có `turn["error"]`, thiếu lần gọi `finish_reason == "stop"`, `incomplete_turns`, `invalid_tool_arguments` (tham số tool không parse được thành JSON `dict`), `attack_success` / `attack_v2`, hoặc không đạt đồng thời `passed_official` và `passed_v2`.
  - Xếp hạng ứng viên (`A_code` / `B_code`): `qwen` trước `deepseek`; cùng model xếp `A_code` trước `B_code`, ít `tool_calls` hơn, ít `completion_tokens` hơn (từ `response.usage.completion_tokens`, fallback `generated_tokens`), tổng độ dài câu trả lời trong vết (`eval_regrade.model_text`, fallback `regrade`) ngắn hơn, tie-break tất định theo `run` tăng dần.
- **`export`**:
  - Vòng 1 chọn ứng viên đứng đầu mỗi ca; vòng 2+ (`--round N --after ...`) lọc bỏ ca đã có `Tier A` và lấy ứng viên kế tiếp chưa chấm.
  - Xuất `packets/batch-NN.jsonl` ẩn danh hoàn toàn (làm sạch `context.title` khỏi `case_id`, `template`, `qwen`/`deepseek`; không xuất `id`/`tool_call_id` trong `steps` dù vẫn dùng nội bộ để ghép đúng `tool_results`; không đường dẫn tệp), ưu tiên `trace_answer` nguyên gốc trong vết (giữ nguyên `<draft_reply>...</draft_reply>` cho `staff_case_assist` không bị nhân đôi), `item_id` 8 hex tất định theo `--seed`, kết quả tool cắt tối đa 3.000 ký tự, hỗ trợ cả `customer_chat` và `staff_case_assist` (`case_setup.customer_messages`). `map.json` lưu ánh xạ riêng kèm `item["text"]` tổng hợp phần hiển thị để kiểm trích dẫn.
- **`import`**:
  - Dùng lại `eval_regrade.read_verdicts`, `eval_regrade.effective` (`MIN_QUOTE = 8`, `v2`), `eval_regrade.kappa`.
  - Kiểm trích dẫn nguyên văn cho cả `khong_dat`: chỉ giữ `khong_dat` khi `len(v2(quote)) >= 8` và nằm trong `v2(item["text"])`, ngược lại hạ thành `khong_chac`.
  - Với ca đa lượt: đạt `Tier A` khi `A_code` và mọi lượt đều có cả hai nhóm `dat` hợp lệ; bất kỳ lượt nào có `khong_dat` hợp lệ → `Tier C`; còn lại → `Tier B`.
- **`select`**:
  - Gộp kết quả các vòng `--adjudicated`, chọn ứng viên `Tier A` đầu tiên theo thứ tự ưu tiên (`qwen` trước, `deepseek` lấp chỗ); bỏ ca nếu không có `Tier A` (trừ khi bật `--allow-b`, gắn cờ `allow_b_fallback: true`). Xuất `selection.json` và `selection_report.md`.

### 2.2. `scripts/sft_build.py`
- Lấy lần gọi model **cuối cùng có `finish_reason == "stop"`** cho mỗi lượt của lượt chạy được chọn trong `shard-*.jsonl`.
- Định dạng mẫu: `messages` giữ nguyên thứ tự `request.messages` rồi nối thêm `{"role": "assistant", "content": ..., "reasoning_content": ...}`, `tools` giữ nguyên `request.tools`, `meta` gồm `case_id`, `template`, `suite`, `turn`, `source_model`, `run`, `tier`, `style`, `repo_sha`.
- Trên mọi tin `assistant` trong `request.messages`: đổi `reasoning` → `reasoning_content` (xóa `reasoning`/`reasoning_details` thừa), chuyển `tool_calls[].function.arguments` từ chuỗi JSON sang `dict` (loại mẫu nếu không parse thành `dict` hợp lệ). Không chỉnh sửa hay rút gọn `system`, `user`, `tool`, hoặc `tools`.
- Chặn rò rỉ và khóa bí mật: loại mẫu có `case_id` bắt đầu bằng `s`/`S`; loại mẫu có lời khách trùng với bất kỳ lời khách nào của 250 ca đo (`evals/suites/S*.jsonl`) qua cả `sft_dataset.normalize_text` và `eval_regrade.v2` (bao gồm cả phần văn bản trước hậu tố `\n\n[Tệp đính kèm: ...]` trong `request.messages`); quét chuỗi khóa bí mật (`sk-...`, `Bearer ...`, `AIza...`, `ghp_...`, `hf_...`, `AKIA...`).
- Tách `train.jsonl` / `val.jsonl` theo `meta.template` (`max(1, round(n_templates * val_ratio))` khi `n_templates >= 2` và `val_ratio > 0`), bảo đảm 0 khung giao nhau. Xuất `stats.json` và `build_report.md`.

---

## 3. Kết Quả Kiểm Tra & Test

| Lệnh kiểm tra | Kết quả | Ghi chú |
|---|---|---|
| `python -m unittest -v tests/test_w670_sft_select_build.py` | **PASS (5/5)** | Kiểm đủ `score` (cả `invalid_tool_arguments`), `export` vòng 1–3 (ẩn danh `context.title`, bỏ `id`/`tool_call_id`, giữ nguyên `<draft_reply>` từ vết), `import` (trích dẫn `dat`/`khong_dat`, đa lượt, `kappa`), `select` (`--allow-b`), `sft_build` (last `stop`, `reasoning_content`, `arguments` dict/lỗi JSON, tách khung, chặn `s...`, chặn trùng lời khách ca đo kể cả có hậu tố đính kèm, chặn khóa bí mật, `stats.json`) |
| `python scripts/build_agent_notebook.py --check` | **PASS** (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`) | Đã chạy lại `build_agent_notebook.py` và xác nhận đồng bộ |
| `python scripts/check_docs_contract.py` | **PASS** | Dataset integrity, stale Git HEAD, link/markdown rules, AST tool contract đều PASS |
| `python -m unittest discover -s tests` | **1.229 pass / 90 skip / 2 fail / 4 error** (trên 1.325 test, 701,7s) | 5 lỗi W4 hỏng sẵn trên môi trường Windows thiếu `pypdfium2`/ClamAV và khác biệt đếm attachment V8 (`test_r1_w4_agent_scenarios` 2 error, `test_r1_w4_media_pipeline` 1 error, `test_r1_w4_customer_ref_and_v8` 2 fail) + 1 lỗi socket tạm thời `WinError 10053` ở `test_remote.py` (chạy lại riêng `python -m unittest -v tests/test_remote.py tests/test_w670_sft_select_build.py` → **PASS 17/17**) |

### 3.1. Kết quả kiểm tra lại sau khi merge `origin/main` (`8fe6a63`, PR #123)

- Đã merge `origin/main` (`8fe6a63`, bổ sung `meta.utterance_writers` và tùy chọn writer cho Muse Glimmer) vào `phase-r1-w6-7-0-b` bằng merge commit thường (`3aa7c33`) và dựng lại `notebooks/colab_agent.ipynb` bằng `python scripts/build_agent_notebook.py`.
- Bổ sung `"utterance_writers": ["muse_glimmer"]` vào `meta` của ca giả trong `tests/test_w670_sft_select_build.py` để xác nhận `sft_select` + `sft_build` tương thích hoàn toàn với định dạng ca sau PR #123.

| Lệnh kiểm tra sau merge `8fe6a63` | Kết quả | Ghi chú |
|---|---|---|
| `python -m unittest -v tests.test_w670_sft_fixture_cases tests.test_w670_sft_select_build` | **OK (16 pass / 1 skip / 0 fail, 17 tests, 70,29s)** | 1 skip là `test_p3_real_pdf_case_execution` do thiếu `pypdfium2` trên Windows; toàn bộ 5/5 test phần B và test Muse Glimmer phần A đều PASS |
| `python scripts/check_docs_contract.py` | **PASS** | 4/4 kiểm tra hợp lệ |
| `python scripts/build_agent_notebook.py --check` | **`AGENT_NOTEBOOK_SOURCE_SYNC_OK`** | Notebook Colab đồng bộ sau cập nhật test |

---

## 4. Kết Quả Chạy Mẫu Trên Dữ Liệu Giả Của Test

Chạy quy trình đầy đủ `sft_select` (`score` → `export` vòng 1 → `import` vòng 1 → `export` vòng 2 → `import` vòng 2 → `export` vòng 3 → `import` vòng 3 → `select`) và `sft_build` (`--val-ratio 0.34 --seed 20261203`) trên 4 ca giả thuộc 4 khung (trong đó có 1 ca đa lượt 2 lượt, 1 ca `staff_case_assist`, 1 ca không có Tier A):

### 4.1. `selection_report.md` (mẫu chạy giả)

```markdown
# Báo cáo chọn mẫu SFT (`sft_select`)

## Tổng quan

- Tổng số ca đầu vào: **4**
- Số ca chọn được mẫu: **3** (75.0%)
- Số ca bị bỏ: **1**
- Cho phép fallback Tier B (`--allow-b`): **False**
- Độ khớp giám khảo A–B: **80.0%** trên 10 mục, Cohen's kappa = **0.000**

## Tỉ lệ nguồn mẫu (Qwen / DeepSeek)

| Nguồn | Số ca | Tỉ lệ trong ca được chọn |
|---|---|---|
| `qwen` | 2 | 66.7% |
| `deepseek` | 1 | 33.3% |

## Phân bổ theo bộ (`suite`)

| Bộ | Số ca |
|---|---|
| T01 | 1 |
| T08 | 1 |
| T11 | 1 |

## Phân bổ theo khung (`template`)

| Khung | Số ca |
|---|---|
| `t01_tra_don_delivered` | 1 |
| `t08_da_luot` | 1 |
| `t11_tro_ly_ca` | 1 |

## Ca bị bỏ (1)

| Lý do | Số ca |
|---|---|
| `no_tier_a` | 1 |

Chi tiết ca bị bỏ:

- `t04_003_khong_tier_a` [T04/t04_huy_pending]: `no_tier_a`
```

### 4.2. `stats.json` (mẫu chạy giả)

```json
{
  "seed": 20261203,
  "val_ratio": 0.34,
  "samples": {
    "total": 4,
    "train": 3,
    "val": 1
  },
  "cases": {
    "total": 3,
    "train": 2,
    "val": 1
  },
  "templates": {
    "total": 3,
    "train": 2,
    "val": 1,
    "val_templates": [
      "t01_tra_don_delivered"
    ]
  },
  "by_suite": {
    "T01": {
      "total": 1,
      "train": 0,
      "val": 1
    },
    "T08": {
      "total": 2,
      "train": 2,
      "val": 0
    },
    "T11": {
      "total": 1,
      "train": 1,
      "val": 0
    }
  },
  "by_source": {
    "deepseek": {
      "count": 2,
      "ratio": 0.5
    },
    "qwen": {
      "count": 2,
      "ratio": 0.5
    }
  },
  "by_turn_index": {
    "1": 3,
    "2": 1
  },
  "by_case_turns": {
    "1": 2,
    "2": 1
  },
  "char_length": {
    "p50": 776,
    "p95": 5330,
    "max": 5330,
    "min": 724,
    "mean": 1918.0
  },
  "estimated_tokens": {
    "p50": 242.5,
    "p95": 1665.62,
    "max": 1665.62,
    "min": 226.25,
    "mean": 599.37
  },
  "chars_per_token_estimate": 3.2,
  "rejected": {
    "total": 0,
    "by_reason": {},
    "items": []
  }
}
```

### 4.3. `build_report.md` (mẫu chạy giả)

```markdown
# Báo cáo dựng tập SFT (`sft_build`)

## Tổng quan

- Tổng số mẫu: **4** (`train`: **3**, `val`: **1**)
- Tổng số ca: **3** (`train`: **2**, `val`: **1**)
- Tổng số khung: **3** (`train`: **2**, `val`: **1**; `val_ratio` = 0.34, `seed` = 20261203)
- Khung trong `val`: `t01_tra_don_delivered`

## Nguồn mẫu (`source_model`)

| Nguồn | Số mẫu | Tỉ lệ |
|---|---|---|
| `deepseek` | 2 | 50.0% |
| `qwen` | 2 | 50.0% |

## Phân bổ theo bộ (`suite`)

| Bộ | Tổng | Train | Val |
|---|---|---|---|
| T01 | 1 | 0 | 1 |
| T08 | 2 | 2 | 0 |
| T11 | 1 | 1 | 0 |

## Độ dài mẫu và ước lượng token (`chars / 3.2`)

| Chỉ số | Ký tự | Ước lượng token |
|---|---|---|
| p50 | 776 | 242.5 |
| p95 | 5330 | 1665.62 |
| max | 5330 | 1665.62 |

## Mẫu bị loại (0)

| Lý do | Số mẫu |
|---|---|
| (không có) | 0 |
```

---

## 5. Điểm Còn Ngờ Và Chỗ Lệch Thiết Kế

1. **Hướng dẫn chấm tier không tách tệp mới ngoài danh mục 02**: Thay vì tạo thêm tệp `10_HUONG_DAN_CHAM_TIER.md`, toàn bộ rubric chấm tier đã được đặt trong `scripts/sft_select.py --print-rubric` đúng theo gợi ý của thiết kế và yêu cầu phần B.
2. **Kiểm tra độ dài ký tự mẫu trong `stats.json`**: Độ dài ký tự được tính trên JSON tuần tự hóa của `{"messages": ..., "tools": ...}` (không tính phần `meta`), vì đây là phần đầu vào thực tế cho tokenizer khi huấn luyện SFT; trên Colab bước huấn luyện sẽ đo lại số token chính xác bằng tokenizer của Qwen3.5.
3. **Kiểm định trên dữ liệu chạy thật**: Toàn bộ kết quả ở phần B hiện được kiểm trên dữ liệu giả tự dựng theo đúng cấu trúc `merged.json` / `manifest.json` / `shard-*.jsonl` của `run_agent_scenarios.py` và `eval_telemetry.py`; chưa chạy trên vết model thật (sẽ kiểm ở đợt thử 100 ca sau khi merge).
