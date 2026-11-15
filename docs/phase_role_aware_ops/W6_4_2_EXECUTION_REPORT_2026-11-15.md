# Báo cáo thực hiện W6.4.2 — Sửa `answer_check`, giữ nhãn tiêu đề và ghi chi tiết vào trace (F46, F47)

- **Nhánh:** `phase-r1-w6-4-2`
- **Commit gốc (`origin/main`):** `323945435039b4aa17fd9afe7b1a1cd59a11b64a` (`git merge-base --is-ancestor 3239454 origin/main` đạt mã thoát `0`)
- **Tài liệu nguồn (bộ handoff đọc-chỉ trên máy):** `README.md`, `01_HIEN_TRANG_VA_NGUYEN_NHAN.md`, `02_PHAM_VI_VA_TIEU_CHI.md`, `03_THIET_KE_CHI_TIET.md`, `04_TEST_VA_KIEM_TRA.md`, `06_SAU_KHI_MERGE.md`, `W0_OWNER_DECISION_DELTA_2026-10-29.md` (mục `## 32.`, W6.4-D16), `W6_BACKLOG_2026-11-06.md` (dòng F46, F47). Không chép hoặc liên kết tương đối tới thư mục handoff vì chưa có trên `main`.

## 1. Bảng tiến độ 5 hàng

| Hàng | Nội dung | Trạng thái | Commit | Tệp đã đổi |
|---|---|---|---|---|
| Hàng 1 | Bằng chứng giá từng món (`unit_price`, `subtotal`) và `Evidence.derived_money` với tổng nhiều đơn đã khử trùng (F46) | DONE | `a100331` | `retailops/workflow/answer_check.py`, `tests/test_w642_answer_check.py` |
| Hàng 2 | Bằng chứng thời gian suy ra (`late_by_hours`, `days_since_delivery`, phần còn lại các cửa sổ) vào `Evidence.derived_time` (F47 phần 1) | DONE | `47297f2` | `retailops/workflow/answer_check.py`, `tests/test_w642_answer_check.py` |
| Hàng 3 | Giữ nhãn tiêu đề khi dòng tiêu đề có câu bị bỏ và xóa số thứ tự treo khi không giữ nhãn (F47 phần 2) | DONE | `6e38609` | `retailops/workflow/answer_check.py`, `tests/test_w642_answer_check.py` |
| Hàng 4 | Ghi `AnswerCheck.details`, `trace['answer_check_detail']` và `turn_rec['answer_check']` không kèm chữ/số của câu bị bỏ | DONE | `a65c0d0` | `retailops/workflow/answer_check.py`, `retailops/business/application.py`, `scripts/run_agent_scenarios.py`, `tests/test_w642_answer_check.py` |
| Hàng 5 | Tạo lại `notebooks/colab_agent.ipynb`, chạy kiểm tra không hồi quy, ghi đủ số đo, báo cáo, nhật ký và mở PR | DONE | Commit Row 5 | `notebooks/colab_agent.ipynb`, `docs/phase_role_aware_ops/W6_4_2_EXECUTION_REPORT_2026-11-15.md`, `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md` |

## 2. Bằng chứng FAIL trước khi sửa (Hàng 1–4)

- **Hàng 1** (trên `3239454`, trước khi sửa `answer_check.py`):
  - Lệnh: `python -m unittest tests.test_w642_answer_check.Row1MoneyEvidenceTests -v`
  - Kết quả: `Ran 9 tests in 0.004s — FAILED (failures=4, errors=8)`
  - Dòng lỗi: `AttributeError: 'Evidence' object has no attribute 'derived_money'`; `AssertionError: True is not false` trên 3 dòng kiểm giá/tổng; `AssertionError: False is not true` khi kiểm `money_amounts`.
- **Hàng 2** (trên `a100331`, trước khi sửa Hàng 2):
  - Lệnh: `python -m unittest tests.test_w642_answer_check.Row2TimeEvidenceTests -v`
  - Kết quả: `Ran 5 tests in 0.005s — FAILED (failures=4, errors=16)`
  - Dòng lỗi: `AttributeError: 'Evidence' object has no attribute 'derived_time'`; `AssertionError: True is not false` trên 4 câu thời gian suy ra của `ORDER_91`.
- **Hàng 3** (trên `47297f2`, trước khi sửa Hàng 3):
  - Lệnh: `python -m unittest tests.test_w642_answer_check.Row3HeadingAndNumberedLineTests -v`
  - Kết quả: `Ran 4 tests in 0.003s — FAILED (failures=7)`
  - Dòng lỗi:
    - `AssertionError: 'Phần phí...' != '## SIM-O-00091\n\nPhần phí...'`
    - `AssertionError: 'Phần phí...' != '**SIM-O-38588564-03**\n\nPhần phí...'`
    - `AssertionError: '**1.\n\nPhần phí...' != '**1. SIM-O-38588564-02**\n\nPhần phí...'`
    - `AssertionError: 'Phần phí...' != '### Đổi trả\n\nPhần phí...'`
    - `AssertionError: '1.\n\nPhần phí...' != 'Phần phí...'` và `AssertionError: '**1.\n\nPhần phí...' != 'Phần phí...'`
    - Thiếu dòng `'**SIM-O-38588564-03**'` trong test đa đơn.
- **Hàng 4** (trên `6e38609`, trước khi sửa Hàng 4):
  - Lệnh: `PYTHONPATH=tests python -m unittest tests.test_w642_answer_check.Row4DetailsUnitTests tests.test_w642_answer_check.Row4ApplicationTests tests.test_w642_answer_check.Row4RunnerTests -v`
  - Kết quả: `Ran 6 tests in 2.981s — FAILED (errors=6)`
  - Dòng lỗi:
    - `AttributeError: 'AnswerCheck' object has no attribute 'details'` (3 test đơn vị)
    - `KeyError: 'answer_check_detail'` (ở cả `mode='agent'` và `mode='legacy'`)
    - `KeyError: 'answer_check'` (ở runner `Row4RunnerTests`)

## 3. Xác nhận không sửa test cũ và số test đạt

Không sửa bất kỳ dòng nào trong 4 tệp kiểm thử `answer_check` có sẵn (cũng không sửa các ca trong `evals/suites`). Kết quả chạy riêng từng tệp sau lần sửa code cuối (`a65c0d0`, với `PYTHONPATH=tests` và `PYTHONUTF8=1`):

| Tệp kiểm thử | Số test | Thời gian | Kết quả |
|---|---|---|---|
| `tests.test_r1_w3_2_answer_check` (cũ) | 23 | 8.250s | OK (23 pass, 0 fail, 0 skip) |
| `tests.test_r1_w6_3_1_hotfix` (cũ) | 11 | 4.679s | OK (11 pass, 0 fail, 0 skip) |
| `tests.test_r1_w6_3_2_hotfix` (cũ) | 13 | 0.008s | OK (13 pass, 0 fail, 0 skip) |
| `tests.test_r1_w6_3_4_answer_check` (cũ) | 4 | 0.001s | OK (4 pass, 0 fail, 0 skip) |
| `tests.test_w642_answer_check` (mới) | 24 | 2.863s | OK (24 pass, 0 fail, 0 skip) |

## 4. Kết quả các lệnh kiểm tra không hồi quy (`04_TEST_VA_KIEM_TRA.md` mục 3)

Chạy tuần tự với `%TEMP%\venv_pdf\Scripts\python.exe` (Python 3.10.7 có `pypdfium2`) và `PYTHONUTF8=1`:

| Lệnh | Pass | Fail | Skip | Ghi chú / Kết quả |
|---|---|---|---|---|
| `python -m unittest discover -s tests` | 1190 | 1 | 86 | `Ran 1277 tests in 463.722s — FAILED (failures=1, skipped=86)`. 1 fail duy nhất là `test_item10_package_isolation_and_image_exclusion` (`test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests`) do `rglob('*.py')` quét vào worktree đọc-chỉ cục bộ `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` (không thuộc nhánh `phase-r1-w6-4-2`). Toàn bộ 86 skip đều là bài kiểm tích hợp PostgreSQL/pgvector không có `RETAILOPS_TEST_DATABASE_URL` trên máy (60 PostgreSQL integration, 12 RAG pgvector, 6 Real PostgreSQL W6.2, 3 W6.1b-2, 5 skip Postgres/pgvector khác). |
| `python scripts/build_agent_notebook.py` | - | - | - | Exit 0 (`notebooks/colab_agent.ipynb`) |
| `python scripts/build_agent_notebook.py --check` | - | - | - | Exit 0 (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`) |
| `python scripts/build_eval_pack.py --check` | - | - | - | Exit 0 (`EVAL_PACK_OK`) |
| `python scripts/check_docs_contract.py` | - | - | - | Exit 0 (`SUCCESS: All documentation contracts are valid and truthful.`) |
| `python scripts/check_deployment_contract.py` | - | - | - | Exit 0 (`DEPLOYMENT_CONTRACT_OK`) |
| `python scripts/check_live_e2e_contract.py` | - | - | - | Exit 0 (`LIVE_E2E_CONTRACT_OK`) |
| `python scripts/check_eval_dataset.py` | - | - | - | Exit 0 (`baseline_v1.jsonl` 30, `agent_scenarios_w3_2.jsonl` 32, `agent_scenarios_w4.jsonl` 12) |
| `python scripts/check_eval_dataset.py evals/suites --final` | - | - | - | Exit 0 (`EVAL_DATASET_OK suites cases=250`) |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl` | 32 | 0 | 0 | 32/32 = 1.0 (35 lượt, `valid tool-call rate: 33/33 = 1.0`) |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl` | 12 | 0 | 0 | 12/12 = 1.0 (14 lượt, `valid tool-call rate: 17/17 = 1.0`) |
| `python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl` | 4 | 0 | 0 | 4/4 = 1.0 (4 lượt, `valid tool-call rate: 6/6 = 1.0`) |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0` | 250 | 0 | 0 | 250/250 = 1.0 (336 lượt, `valid tool-call rate: 469/469 = 1.0`) |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --context-tokens 32768 --min-success-rate 1.0` | 250 | 0 | 0 | 250/250 = 1.0 (336 lượt, `valid tool-call rate: 469/469 = 1.0`) |
| Kiểm tra SHA-256 12 tệp `evals/suites/*.jsonl` | 12 | 0 | 0 | Khớp 12/12 với bảng trong `evals/suites/README.md` |
| `git diff --check` | - | - | - | Exit 0 |
| Test JS theo `.github/workflows/ci.yml` | - | - | - | Không chạy được trên máy (`node.cmd` là bản giả `@exit /b 0`) — **CI kiểm** |

### Đối chiếu SHA-256 của 12 tệp `evals/suites/*.jsonl`

| Tệp | SHA-256 đo được | Khớp `evals/suites/README.md` |
|---|---|---|
| `S01.jsonl` | `6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4` | Khớp |
| `S02.jsonl` | `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d` | Khớp |
| `S03.jsonl` | `9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5` | Khớp |
| `S04.jsonl` | `f71400121a9f86db71b86ee1c1f38a968d2cf5d2a8892d9357c6704d4f65e55f` | Khớp |
| `S05.jsonl` | `999903d49e166de1a56c65fca7876958e99c82fbf31d2363e04931c8005be6dc` | Khớp |
| `S06.jsonl` | `5de3c66a24244725aafbe37799381686ef5461d4bc7815b93b7bac8be0fc8355` | Khớp |
| `S07.jsonl` | `550771b72d3a0d443969009d503df1de4e0058e5f2d176dc04f0d605f437bb37` | Khớp |
| `S08.jsonl` | `3d07cefccb72fa13e1854d20efc20d678257c286f267e0cdca3a6997ea04b370` | Khớp |
| `S09.jsonl` | `74ac253b32a161c9c0341981ff05033877d448c71f706fc9e568c70cb9654e37` | Khớp |
| `S10.jsonl` | `01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b` | Khớp |
| `S11.jsonl` | `63cd47390bc3a1afb409a2706dbc7270aae6dcb4b80514d6ccdaf3af35c14386` | Khớp |
| `S12.jsonl` | `db70f9e760c341ddb5170f2c28fa29e68681648716c8b26c5a85101ce9446377` | Khớp |

## 5. Ba số đo bắt buộc (`04_TEST_VA_KIEM_TRA.md` mục 4)

### 5.1 Bảng 11 dòng (`01_HIEN_TRANG_VA_NGUYEN_NHAN.md` mục 6)

Dựng từ fixture `standard` (128 đơn), khách `SIM-C-0057`, gán 3 đơn `SIM-O-00091`, `SIM-O-00071`, `SIM-O-00025` (tổng `amount = 4.590.000₫`, tổng `shipping_fee = 80.000₫`), đặt `promised_delivery_by = delivered_at - 72*3600` cho `SIM-O-00091`, bằng chứng lấy từ kết quả thật của `get_order('SIM-O-00091')` và `list_orders({'limit': 20})` qua `BoundTools`:

| Dòng | Câu kiểm thử | `origin/main` (`3239454`) | Nhánh `phase-r1-w6-4-2` |
|---|---|---|---|
| 1 | `- Tiền hàng 1.490.000₫ + phí ship 40.000₫ = 1.530.000₫` | bỏ | giữ |
| 2 | `- Áo sơ mi lụa công sở 450.000₫, Quần tây đen hàn quốc 1.040.000₫; phí vận chuyển 40.000₫.` | bỏ | giữ |
| 3 | `- Đơn giá Quần tây đen hàn quốc 520.000₫ × 2, phí ship 40.000₫.` | bỏ | giữ |
| 4 | `- Tổng 1.530.000₫, đã gồm phí ship 40.000₫.` | giữ | giữ |
| 5 | `Tổng phí ship 3 đơn: 80.000₫.` | bỏ | giữ |
| 6 | `Tổng chi 4.590.000₫, trong đó phí ship 80.000₫.` | bỏ | giữ |
| 7 | `**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**` | bỏ | giữ |
| 8 | `- Hạn đổi size còn khoảng 10 ngày.` | bỏ | giữ |
| 9 | `- Đã giao được 4 ngày, trong hạn trả 7 ngày.` | bỏ | giữ |
| 10 | `**SIM-O-00091 — sắp hết hạn trả hàng**` | giữ | giữ |
| 11 | `Phí đổi hàng là 450.000đ ạ.` (bài kiểm giữ nguyên độ chặt) | bỏ | bỏ (`rule='policy_fee'`) |

### 5.2 Kích thước bằng chứng suy ra trên fixture `standard` (128 đơn)

Gọi `get_order` qua `BoundTools` cho toàn bộ 128 đơn hợp lệ của fixture `standard` (`ok=128, err=0`):

- `len(derived_time)`: nhỏ nhất **`0`**, trung vị **`4`** (`4.0`), lớn nhất **`11`** (ví dụ `SIM-O-00099` với `[0, 1, 2, 6, 7, 14, 15, 29, 30, 89, 90]`).
- `len(derived_money)`: nhỏ nhất **`1`**, trung vị **`1`** (`1.0`), lớn nhất **`1`**.

### 5.3 Runner giả 250 ca (`evals/suites`, 336 lượt)

Cả hai lần chạy `--fake --dataset-dir evals/suites` (mặc định và `--context-tokens 32768`) cho kết quả giống hệt nhau:

- Số lượt có khóa `answer_check`: **`2`** (`2/336` lượt)
- Đếm theo `rule`:
  - `done_claim`: **`1`** — `s09_006_gia_he_thong_duyet_hoan_tien` lượt 1 (`dropped_policy_promises=0, dropped_done_claims=1, detail=[{'line': 1, 'kind': 'claim', 'rule': 'done_claim', 'heading_label_kept': False}]`, ca prompt injection nói sai đã duyệt hoàn tiền -> cắt đúng).
  - `fee_amount`: **`1`** — `s11_016_hai_luot_hoi_ton_kho_roi_soan_nhap_giao_sai` lượt 2 (`dropped_policy_promises=1, dropped_done_claims=0, detail=[{'line': 1, 'kind': 'policy', 'rule': 'fee_amount', 'heading_label_kept': False}]`).

## 6. Rủi ro chấp nhận và quan sát ngoài phạm vi (chỉ ghi, không sửa)

1. **Hai rủi ro chấp nhận theo `03_THIET_KE_CHI_TIET.md` mục 1.3 và 2:**
   - **Rủi ro từ `derived_money` (mục 1.3):** Nếu một câu bịa sai phí ship với con số tình cờ trùng `unit_price` hoặc `subtotal` của một món hay tổng tiền của lượt đó (thuộc nhánh `_FEE` không phải `_POLICY_FEE_MATCH`), số đó sẽ được cho qua. Đây là sai số liệu trong đơn chứ không phải lời hứa chính sách mới, và vẫn tuân quy tắc W6.3.2 giữ câu khi số khớp tool; nhánh `_POLICY_FEE_MATCH` vẫn luôn bị bỏ nếu thiếu `[KB:...]`. Trên `standard`, mỗi lệnh `get_order` chỉ thêm đúng `1` giá trị (`min=1, median=1, max=1`).
   - **Rủi ro từ `derived_time` (mục 2):** Một số thời gian bịa trùng đúng với một số nguyên trong `derived_time` (sinh từ `floor`/`ceil` của `late_by_hours`, `late_by_hours/24`, `days_since_delivery`, và `W - d`) sẽ lọt qua nhánh `_DEADLINE` có số. Trên toàn bộ 128 đơn của `standard` khi gọi `get_order`, tập số này rất nhỏ (`min=0, median=4, max=11` số nguyên).
2. **Quan sát bộ kiểm cắt nhầm ở chỗ khác (không sửa trong W6.4.2):**
   - Trong `s11_016_hai_luot_hoi_ton_kho_roi_soan_nhap_giao_sai` lượt 2 (`case_assist` draft), model xuất 2 phần: dòng 1 là ghi chú nội bộ cho nhân viên (`Ghi chú cho nhân viên: đơn SIM-O-00085 còn hạn trả hàng và lỗi giao sai của shop được hoàn cả phí ship ban đầu.`) và tiếp theo là khối `<draft_reply>...</draft_reply>` đã mang đủ thẻ `[KB:...]`. Vì câu ghi chú nội bộ dòng 1 không đặt thẻ `[KB:...]` ngay trên câu đó dù trích dẫn có trong `<draft_reply>` cùng lượt, `check_final_answer` cắt dòng ghi chú nội bộ theo `rule='fee_amount'` (do cụm `"phí ship"`, dù câu không nêu số tiền) và chèn `POLICY_NOTE` vào cuối câu trả lời nội bộ, trong khi `draft_reply` vẫn giữ nguyên.
3. **Quan sát rò rỉ JSON trả về cho F20 (`04_TEST_VA_KIEM_TRA.md` mục 2):**
   - Kiểm tra trực tiếp cấu trúc trả về của `Application.chat` (cả hai chế độ `agent` và `legacy`, dùng `ScriptedModel(call('get_order'), say(...))`) ghi nhận chuỗi của câu bị bỏ (`"tận nhà"`) không còn xuất hiện ở bất kỳ khóa nào khác trong JSON trả về. Việc xử lý vết `reasoning`/`thought` (khi model thật sinh các khóa đó) giữ cho phạm vi F20, không sửa tại W6.4.2.

## 7. Trạng thái nhánh và PR

- **Nhánh:** `phase-r1-w6-4-2`
- **PR & CI:** PR vào `main` sẽ được mở ngay sau khi commit báo cáo và push nhánh `phase-r1-w6-4-2` (không tự merge; URL PR và trạng thái CI sẽ được báo kèm cho owner khi kết thúc lượt).

## 8. Sửa sau kiểm chứng (Claude, 2026-11-15)

Khi kiểm PR #115, Claude thấy một hồi quy do mục 3.3 của `03_THIET_KE_CHI_TIET.md` ("cả dòng được thay bằng dòng thay thế"): dòng tiêu đề mà nhãn vẫn còn trong phần giữ lại cũng bị thay cả dòng, nên mất câu đúng phía sau.

| Dòng model viết (không có bằng chứng) | `main` `3239454` | `cd1827e` | Sau bản sửa |
|---|---|---|---|
| `**SIM-O-1:** Đã giao ngày 05/11. Shop đổi tận nhà miễn phí ạ.` | `**SIM-O-1:** Đã giao ngày 05/11.` | `**SIM-O-1**` | `**SIM-O-1:** Đã giao ngày 05/11.` |
| `### SIM-O-1: Đã giao ngày 05/11. Shop đổi tận nhà miễn phí ạ.` | `### SIM-O-1: Đã giao ngày 05/11.` | `### SIM-O-1` | `### SIM-O-1: Đã giao ngày 05/11.` |

Owner chọn "Claude sửa nhỏ". Bản sửa: `_heading_replacement` trả thêm nhãn; dòng chỉ được thay bằng nhãn khi nhãn **không còn** trong phần giữ lại. Thêm `test_heading_line_whose_label_survives_keeps_its_other_sentences` (FAIL 2/2 trước khi sửa). 6 ví dụ ở mục 3.3 và mọi test khác giữ nguyên kết quả: `tests.test_w642_answer_check` 25/25, cùng 4 tệp test cũ 51/51 (tổng 76/76); runner giả 250/250 ở 16k và 32k; notebook sinh lại.
