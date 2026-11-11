# W6.3 — báo cáo thực thi phần code (2026-11-10)

## Cập nhật theo kiểm chứng Claude — 2026-11-11

Phần này là báo cáo hiện tại, thay các kích thước và kết quả chạy ngày 2026-11-10 ở
phần lịch sử bên dưới. Sửa tiếp PR #87 trên nhánh `phase-r1-w6-3`, không mở PR mới.

| Yêu cầu | Tệp sửa | Trạng thái |
|---|---|---|
| 1. Tài liệu gọn | `scripts/build_eval_pack.py`, `tests/test_r1_w6_3_build_pack.py`, bốn khối GENERATED của `khoa_luan/eval_pack/03_HE_THONG_VA_DU_LIEU.md` | DONE |
| 2. Nhóm hoàn tiền | `scripts/build_eval_pack.py`, `tests/test_r1_w6_3_build_pack.py`, khối `customers_orders` | DONE |
| 3. Tập con phân tầng | `scripts/eval_stats.py`, `scripts/run_agent_scenarios.py`, `tests/test_r1_w6_3_stats.py`, `tests/test_r1_w6_3_runner.py`, `evals/README.md` | DONE |
| Đồng bộ và báo cáo | notebook sinh `notebooks/colab_agent.ipynb`, báo cáo này, dòng 030 cột Codex của log W1 | DONE |

### Dữ liệu được rút gọn

Tệp `03` giảm từ **680.365 byte / 20.634 dòng** xuống **112.110 byte / 1.073 dòng**
(UTF-8, dưới mục tiêu 120 KB). Test kiểm toàn tệp sinh dưới **150.000 byte** trên
checkout có tài liệu; trong image không chứa luận văn, vẫn kiểm kích thước các khối sinh.
128 đơn được giữ đủ, mỗi đơn đúng một dòng bảng Markdown với 15 cột owner yêu cầu.
Các trường hoàn tiền/voucher trống ghi `—`, không suy diễn là đã hoàn hay đã phát.
Số ngày đặt/giao và số ngày còn lại dùng một chữ số thập phân. Quyết định đủ điều
kiện lấy nguyên từ server; số ngày còn lại chỉ định dạng bằng cửa sổ server trừ
số ngày sau giao do server tính. `tool_results` chỉ giữ tên tool, tham số, verdict,
mã lý do và 3–5 trường quyết định; không nhúng toàn bộ đơn. Catalog cũng chuyển
biến thể thành bảng, giữ đủ giá, bảo hành, chất liệu, cách giặt và tồn kho.

| Khối | Byte UTF-8 | Dòng | Trích đoạn |
|---|---:|---:|---|
| tool_results | 18.272 | 141 | `"tool":"prepare_order_action"`, `"eligible":false`, `"reason_code":"order_not_pending"` |
| customers_orders | 46.915 | 158 | `hủy: có; trả: không; đổi size: không; bảo hành: không` |
| catalog | 14.671 | 400 | `P-101 · Áo thun Essential`, biến thể `Trắng · Size XL`, tồn `0` |
| knowledge | 20.593 | 287 | `# Chính sách hủy đơn hàng` |

Phần viết tay của `03` giữ nguyên; tất cả thay đổi nằm giữa bốn cặp marker sinh.
Bốn ví dụ và 44 ca hồi quy không đổi trong lượt sửa này.

### Nhóm hoàn tiền

Phân nhóm từ `refund_summary`: `latest_status == completed` **hoặc**
`refunded_total > 0` thuộc “đã hoàn tiền”. Trạng thái failed/pending/processing
có nhóm riêng “hoàn tiền thất bại hoặc đang chờ”; một đơn có thể thuộc cả hai
nhóm nếu có hoàn một phần rồi lần mới thất bại. Có test dữ liệu tổng hợp cho trường hợp đó.

Đối chiếu trực tiếp fixture standard từ demo runner của nhánh hiện tại:
**18 dòng completed / 18 đơn**, **2 failed**, **1 pending**, **1 processing**.
Do đó bản đồ sinh liệt kê **18 đơn đã hoàn**, **4 đơn thất bại/đang chờ**;
con số 28 trong nhận xét không khớp snapshot dữ liệu hiện tại. Không chỉnh dữ liệu
giả lập để ép thành 28. Test yêu cầu nhóm completed có ít nhất một mã đơn.

### Tập con W6.4

```sh
python scripts/eval_stats.py subset --size 100 --seed 20261110 evals/suites > subset_100.txt
python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --only-file subset_100.txt
python scripts/eval_stats.py compare A.json B.json --cases subset_100.txt
```

Lệnh subset in đúng một mã mỗi dòng, chọn ngẫu nhiên trong từng bộ sau khi phân
bổ theo tỉ lệ bằng phần dư lớn nhất (Hamilton), hòa thì mã bộ tăng dần. Sắp ID
trước khi lấy mẫu để không phụ thuộc thứ tự dòng; cùng seed/dữ liệu cho cùng danh sách.
Test tổng hợp 250 ca cho phân bổ 100 ca S01–S12 là
`11,7,12,8,11,9,6,7,10,4,9,6`; seed khác chọn ca khác.
`compare --cases` chỉ so giao của danh sách với cả hai báo cáo, báo rõ các ID bị loại,
từ chối giao rỗng và vẫn bắt buộc hash dữ liệu khớp. Không có `--cases` giữ kiểm
cùng tập ca. `--only-file` nhận UTF-8 có BOM, bỏ dòng trống, từ chối file rỗng,
ID trùng hoặc không có trong dataset; nếu dùng cùng `--only` thì hợp hai danh sách.

### Kiểm tra lại mục 4

Viết test trước sửa: bốn bài mới trên bản cũ chạy `Ran 4 tests`,
`FAILED (failures=1, errors=3)`: kích thước `680365 not less than 150000`,
CLI chưa biết `subset`, `--cases`, `--only-file`. Log cục bộ:
`artifacts/w6_3_revision/red.txt`. Sau triển khai, bộ mục tiêu build/stats/runner:
**20 pass, 0 fail, 0 skip**. Test phân bổ đã sửa đáp án tie-break bằng phép chia
phần dư nguyên: S05 nhận 11 và S12 nhận 6, không đổi thuật toán để ép kết quả sai.

| Lệnh / nhóm (lượt sửa 2026-11-11) | Pass | Fail/error | Skip |
|---|---:|---:|---:|
| `python -m unittest discover -s tests -q` | 1013 | 1 fail, 1 error | 80 |
| Test mục tiêu `test_r1_w6_3_build_pack`, `test_r1_w6_3_stats`, `test_r1_w6_3_runner` | 20 | 0 | 0 |
| Test kích thước/bảng/nhóm hoàn tiền sau chỉnh kiểm tra image không chứa luận văn | 1 | 0 | 0 |
| Node: 11 lượt JS theo ci.yml, thêm Ops Console UI, 3 syntax check web/*.js | 15 | 0 | 0 |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 |
| `python scripts/check_eval_dataset.py` | 1 | 0 | 0 |
| Runner fake hai tệp hồi quy | 32 + 12 | 0 | 0 |
| Runner fake `06_vi_du.jsonl` | 4 | 0 | 0 |
| Runner fake suites rỗng, `--min-success-rate 1.0` | 0 ca, exit 0 | 0 | 0 |
| `git diff --check` | 1 | 0 | 0 |

Unittest cục bộ chạy 1095 bài trong 616.243 giây. Fail duy nhất là bài cô lập package
quét vào worktree cũ dưới `.claude/worktrees` như lượt trước. Error duy nhất là
`test_waitress_real_http_chat_saturation_headroom` timeout ở HTTP request loopback
(timeout 5 giây), không phải assertion chấm dữ liệu/tool/subset. Không sửa hoặc bỏ
hai bài đó; CI checkout sạch kiểm lại cả unittest/pgvector và image với ngưỡng nguyên bản.
80 skip cục bộ gồm hai bài PostgreSQL W6.3; trạng thái PostgreSQL thật và CI trên đầu
nhánh cuối được ghi riêng trong mô tả PR khi hoàn tất, không suy diễn skip thành pass.

Log cục bộ: `artifacts/w6_3_revision/unittest.txt`, `focused.txt`, `checks.json`,
`node.json`, các báo cáo fake `w32.json`, `w4.json`, `examples.json`.


PR hiện tại: https://github.com/tuteemovaixlong/CSKH_ban_le/pull/87.
Kết quả CI trên đầu nhánh cuối được cập nhật trong mô tả và tab Checks của PR.
Không sửa các tệp W6.2, không thêm/sửa ca trong `evals/suites/`, không gọi model thật,
không migration/thêm thư viện, không đổi secret/variable/api.env, không deploy hay merge.
`git fetch origin` xác nhận origin/main vẫn là `7b0356d`, chưa cần merge W6.2.

---

## Lịch sử thực thi lần đầu — 2026-11-10


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
| 7 | `.github/workflows/ci.yml`, `.github/workflows/ops-console.yml`, `evals/suites/README.md`, `evals/README.md`, `notebooks/colab_vllm_l4.py`, notebook sinh `notebooks/colab_agent.ipynb`, `docs/phase_role_aware_ops/W6_3_CODE_EXECUTION_REPORT_2026-11-10.md`, log W1 cột Codex | DONE: các bước code/tài liệu hoàn tất; kết quả CI cuối ở PR |

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
