# W6.3 — báo cáo thực thi phần code (2026-11-10)

Nhánh `phase-r1-w6-3` từ `origin/main` tại `7b0356d`, không theo dõi main.
Phạm vi theo handoff W6.3 mục 2 hàng 1–7 và owner decisions §23.

## Thay đổi theo hàng

| Hàng | Tệp | Trạng thái |
|---|---|---|
| 1 | `scripts/check_eval_dataset.py`, `scripts/eval_dataset_v2.py`, `tests/test_r1_w6_3_dataset.py` | DONE: kiểm bản 2 và hạn mức `--final`, giữ kiểm dữ liệu cũ |
| 2 | `scripts/run_agent_scenarios.py`, `scripts/eval_knowledge.py`, `retailops/workflow/compaction.py`, `retailops_providers.py`, `tests/test_r1_w6_3_runner.py`, `tests/test_r1_w6_3_postgres.py` | DONE: PostgreSQL thật đạt, không skip |
| 3 | `scripts/eval_stats.py`, `tests/test_r1_w6_3_stats.py` | DONE: bootstrap trên ca, McNemar chính xác, kiểm hash/tập ca |
| 4 | `scripts/eval_retrieval.py`, `tests/test_r1_w6_3_postgres.py` | DONE: PostgreSQL thật đạt, không skip |
| 5 | `scripts/build_eval_pack.py`, `tests/test_r1_w6_3_build_pack.py`, bốn khối sinh trong `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` | DONE: tool thật, dữ liệu demo runner, thời gian tương đối, phát hiện lệch |
| 6 | `khoa_luan/eval_pack/06_vi_du.jsonl` | DONE: giữ bốn tình huống, đổi khách/đơn/chính sách sang dữ liệu mới; fake 4/4 |
| 7 | `.github/workflows/ci.yml`, `.github/workflows/ops-console.yml`, `evals/suites/README.md`, `evals/README.md`, `notebooks/colab_vllm_l4.py`, notebook sinh `notebooks/colab_agent.ipynb`, log W1 cột Codex | DONE: các bước code/tài liệu hoàn tất; kết quả CI cuối ở PR |

## Bằng chứng test trước, FAIL trước sửa

Hàng 1: viết `tests/test_r1_w6_3_dataset.py` trước khi có code validator.
`python -m unittest tests.test_r1_w6_3_dataset -v` trên code gốc:
`Ran 4 tests`, `FAILED (errors=24)` (gồm các subtest), lỗi
`AttributeError: module 'scripts.check_eval_dataset' has no attribute 'validate_suites'`.

Hàng 2: viết `tests/test_r1_w6_3_runner.py` trước sửa runner/config.
`python -m unittest tests.test_r1_w6_3_runner -v` trên code gốc:
`Ran 5 tests`, `FAILED (failures=2, errors=3)`.
Các lỗi chức năng: `unrecognized arguments: --repeat 3 --thinking off --context-tokens 8192 ...`,
`TypeError: run_suite() got an unexpected keyword argument 'repeat'`,
ngân sách thực tế `(5200, 12000, 6000, 1500)` khác kỳ vọng `(2600, 6000, 3000, 750)`,
`synthetic injection canary` không xuất hiện trong kết quả tool `get_product`.
Fixture HTTP của bài thinking ban đầu thiếu trường phản hồi hợp lệ; đã sửa fixture,
rồi chạy bài đó với mã provider nguyên bản lấy bằng `git show origin/main:retailops_providers.py`:
`Ran 1 test`, `FAILED (errors=1)`, `KeyError: 'chat_template_kwargs'` khi đòi trường thinking=false.
Không sửa lùi hay thay mã sản phẩm để tạo FAIL.

Hàng 3: viết `tests/test_r1_w6_3_stats.py` trước tạo script thống kê.
`python -m unittest tests.test_r1_w6_3_stats -v`: `Ran 3 tests`, `FAILED (errors=3)`,
`ModuleNotFoundError: No module named 'scripts.eval_stats'`.

Log nguyên bản cục bộ: `artifacts/w6_3/row1_red.txt`, `row2_red.txt`,
`row2_provider_red.txt`, `row3_red.txt` (artifacts bị gitignore).

## Khối dữ liệu sinh

Kích thước là UTF-8, chỉ tính nội dung giữa cặp marker, gồm newline cuối.

| Khối | Byte | Dòng |
|---|---:|---:|
| `tool_results` | 235,438 | 6,646 |
| `customers_orders` | 378,283 | 12,408 |
| `catalog` | 34,392 | 1,293 |
| `knowledge` | 20,593 | 287 |

Trích `tool_results`:
```json
"action_type": "cancel", "eligible": false,
"ineligible_reason": {"code": "order_not_pending"}
```

Trích `customers_orders`:
```text
| trễ quá 48 giờ | SIM-O-ST-013 |
| có voucher bồi thường (late_voucher_issued) | SIM-O-ST-013 |
```

Trích `catalog`:
```json
"id": "P-101", "name": "Áo thun Essential", "price": 299000
```

Trích `knowledge`:
```text
# Chính sách hủy đơn hàng
Tài liệu giả lập của RetailOps Demo, không phải cam kết thương mại thực tế.
```

Dữ liệu toàn bộ lấy từ `_provision_demo_template('standard')` và `'late_voucher_issued'`.
Đồng hồ chỉ cố định bên trong script sinh; ngày giờ xuất ra tương đối theo bây giờ.
Mã nội bộ ngẫu nhiên được thay bằng mã sàn khi trình bày. Bản đồ giao thất bại kể cả
mốc thất bại trong hành trình; nhóm trễ dùng `late_by_hours` do server tính, kể cả
đơn đã giao trễ. Test sinh hai lần bằng nhau; đổi một chữ ở bản sao kho tri thức
làm `--check` trả 1. Phần viết tay ngoài marker đã đối chiếu nguyên trạng.

## Kết quả kiểm tra

Báo cáo lệnh dưới đây dùng kết quả thực tế; pass/fail/skip của script là số lượt
lệnh, còn runner là số ca. Không bỏ hay nới bài kiểm để làm xanh.

| Lệnh / nhóm | Pass | Fail/error | Skip | Kết quả |
|---|---:|---:|---:|---|
| `python -m unittest discover -s tests -q` (lượt cuối tại workspace) | 1008 | 1 fail, 0 error | 80 | 1089 bài, 538.310 giây; lỗi môi trường workspace mô tả dưới |
| Test cô lập package trên snapshot sạch của commit `f007c37` | 1 | 0 | 0 | PASS |
| `python -m unittest tests.test_r1_w6_3_dataset tests.test_r1_w6_3_runner tests.test_r1_w6_3_stats -q` | 17 | 0 | 0 | PASS |
| Test PostgreSQL W6.3 trên CI, hàng 2 và 4 | 2 | 0 | 0 | PostgreSQL/pgvector thật, không skip |
| Node: đủ 11 lượt test JS trong ci.yml | 11 | 0 | 0 | PASS, gồm public session ở cả hai mode |
| Node: `opsconsole/tests/test_ui.js` | 1 | 0 | 0 | PASS |
| Node: `--check` đủ 3 file web/*.js | 3 | 0 | 0 | PASS |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | AGENT_NOTEBOOK_SOURCE_SYNC_OK |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | EVAL_PACK_OK |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 4 mục hợp đồng PASS |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | DEPLOYMENT_CONTRACT_OK |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | LIVE_E2E_CONTRACT_OK, chỉ kiểm tĩnh |
| `python scripts/check_eval_dataset.py` | 1 | 0 | 0 | baseline 30 ca, W3.2 32 ca, W4 12 ca; suites rỗng hợp lệ |
| `python scripts/check_eval_dataset.py khoa_luan/eval_pack/06_vi_du.jsonl` | 1 | 0 | 0 | 4 ca hợp lệ |
| Runner `--fake` W3.2 | 32 | 0 | 0 | 1.0 |
| Runner `--fake --dataset evals/agent_scenarios_w4.jsonl` | 12 | 0 | 0 | 1.0 |
| Runner `--fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl` | 4 | 0 | 0 | 1.0 |
| Runner `--fake --dataset-dir evals/suites --min-success-rate 1.0` | 0 ca | 0 | 0 | exit 0, đúng yêu cầu thư mục chưa có ca |
| `git diff --check` | 1 | 0 | 0 | PASS |

Lỗi duy nhất trong lượt unittest cuối là
`test_item10_package_isolation_and_image_exclusion`: phép quét `ROOT.rglob('*.py')`
đọc vào worktree cũ `.claude/worktrees/cai-nay-la-sao-bddcef/tests/` và nhận import
`marketplace_sim` nằm ngoài hai thư mục được phép của checkout hiện tại. Không sửa
hay xóa worktree đó. Cùng bài kiểm chạy trên snapshot sạch từ `git archive f007c37`
đạt `1 pass, 0 fail, 0 skip` trong 2.413 giây. CI checkout sạch đã đạt bước
`Unit, pgvector and HTTP contract tests` và bước kiểm artifact P99.
80 skip cục bộ chủ yếu do PostgreSQL không được cấu hình; hai bài W6.3 bắt buộc đã
chạy riêng trên PostgreSQL thật ở PR và đều đạt.

Lượt unittest đầu (trước bổ sung đúng dependency cục bộ và sửa lỗi được phát hiện):
1085 bài, `997 pass, 4 fail, 4 error, 80 skip`. Lỗi có thiếu pypdfium2, notebook sinh
chưa đồng bộ, fixture AST của hàm vLLM và quét worktree ngoài. Đã sửa mã W6.3,
sinh lại notebook và chạy lượt cuối ở trên; không sửa test hồi quy để nới điều kiện.

Các giá trị thống kê đã kiểm: McNemar `b=10,c=2` cho `p=0.03857421875`, `b=c`
cho `p=1`; bootstrap 50/100 cho khoảng `[0.4,0.6]`, lặp seed cho cùng kết quả.
Gateway giả cố ý hỏng đúng lần thứ hai cho pass@1=`2/3`, pass^3=`0`; chèn cụm tấn công
cho `attack_success=true` trong khi `utility=true`. Bộ sinh được test ổn định qua
hai lần chạy và phát hiện lệch khi thay một chữ ở bản sao knowledge.

PR: https://github.com/tuteemovaixlong/CSKH_ban_le/pull/87 (base main, không merge).
Bằng chứng PostgreSQL tại commit code `f007c37`:
https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/42829346187/job/129874976108
— hai bài W6.3 `Ran 2 tests in 2.600s`, `OK`, không skip.
Kết quả CI cuối cùng của đầu nhánh và số liệu unittest trên CI được ghi trong mô tả
PR #87 khi bàn giao; tab Checks của PR là nguồn trạng thái hiện tại.

Nhánh main kiểm lại qua `git ls-remote origin refs/heads/main` vẫn là `7b0356d`;
chưa có W6.2 merge trước nên không cần merge main hay sinh lại vì xung đột W6.2.

## Giới hạn và phạm vi đã giữ

Không migration, không thêm dependency; pypdfium2 cục bộ lấy đúng phiên bản/hash đã có
trong requirements-web vào thư mục artifacts tạm. Không gọi LLM, Colab, production DB,
EC2/SSM; không đổi api.env, variable hay secret; không chạy deploy/live-e2e workflow.
Chỉ chạy script kiểm hợp đồng live-e2e tĩnh theo yêu cầu.

Không sửa các tệp W6.2; không sửa 44 ca hồi quy, không thêm/sửa JSONL trong evals/suites.
README là tệp duy nhất thêm trong thư mục suites. Phần 250 ca còn lại do quy trình dữ liệu
sau merge thực hiện; `--final` hiện từ chối đúng vì thiếu S01–S12, tổng 0/250.

Owner quyết định merge. Executor chỉ mở PR vào main và dừng sau báo cáo, không merge.
