# W6.3.2 execution report — 2026-11-12

## Nguồn và nhánh

- Thực hiện đúng handoff `W6_3_2_HOTFIX_HANDOFF_2026-11-12.md` và quyết định owner §26 đã merge trên main.
- `git fetch origin main`; `git switch --no-track -c phase-r1-w6-3-2 origin/main` tại `139a270dd09a8e3bf44072f82e7d305fb1a7a535`. Sau push, upstream là `origin/phase-r1-w6-3-2`, không theo dõi main.
- PR [#98](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/98), base `main`, head `phase-r1-w6-3-2`; không merge.

## Bằng chứng viết test trước, FAIL trước sửa

Commit test-only `66c5e1c` chứa `tests/test_r1_w6_3_2_hotfix.py`, mã `answer_check.py` lúc chạy vẫn nguyên từ main. Lệnh:

```text
python -m unittest discover -s tests -p test_r1_w6_3_2_hotfix.py -v
Ran 9 tests in 0.008s
FAILED (failures=29, errors=8)
```

Đây là 29 failure assertion/subtest và 8 error assertion/subtest; theo method: 2 pass, 5 fail, 2 error, 0 skip. Log đầy đủ cục bộ `%TEMP%/w632-red.txt`.

| Hàng | Test trên code chưa sửa và dòng lỗi |
|---|---|
| 1 / F30 | `test_order_shipping_facts_need_matching_tool_money`: `AssertionError: 'Phần phí, giao nhận và thời hạn em chưa có ...' != 'Dạ đơn SIM-O-00084 tổng thanh toán 380.000 VNĐ ...'`; cả hai ví dụ, `30k` và câu size 43 bị cắt. `test_money_formats_and_ids` FAIL. `test_money_evidence_walks_all_tool_results_but_rejects_bool_and_non_int`: `AttributeError: 'Evidence' object has no attribute 'money_amounts'`. |
| 2 / F31 | `test_refund_facts_need_completed_evidence`: `AssertionError: 'Em chưa thực hiện thay đổi nào trên đơn qua chat ...' != 'Khoản thanh toán 3.820.000 VNĐ ... hoàn tiền thành công ...'`. `test_each_refund_evidence_source`: `AttributeError: 'Evidence' object has no attribute 'refunded'`. |
| 3 / F32 | `test_only_numbers_before_time_units_are_deadlines`: `AssertionError: 'Phần phí, giao nhận và thời hạn ...' != 'Hiện đơn đã hết thời hạn trả hàng ... Bộ Nồi Inox 3 Đáy Cao Cấp bảo hành 365 ngày ...'`. Câu size 43, ×2 và test năm đơn vị thời gian cũng FAIL. |

Rà soát bổ sung F31: viết `test_refund_context_is_not_another_completed_action` trước sửa bổ sung, chạy riêng `-k test_refund_context_is_not_another_completed_action -v`: **0 pass, 1 fail, 0 skip**, 2 subtest FAIL. Câu `Đơn đã được hoàn tiền sau khi trả hàng ạ.` và `Đơn đã được hoàn tiền cho yêu cầu đổi size ạ.` bị cắt vì chỉ có danh từ/ngữ cảnh trả hàng, đổi size. Sau đó mới sửa để kiểm khẳng định hành động khác qua `_CLAIMS` và động từ phối hợp sau “và/đồng thời/cũng”. Bộ mới cuối **10 pass, 0 fail, 0 error, 0 skip**; các câu thực sự khẳng định đã hủy/đổi/trả/gửi/tạo yêu cầu vẫn bị cắt khi thiếu bằng chứng.

## Tệp đổi và nghiệm thu theo hàng

| Hàng | Trạng thái | Tệp và hành vi |
|---|---|---|
| 1 / F30 | DONE | `retailops/workflow/answer_check.py`: thu số tiền nguyên (loại bool) từ bốn trường qua mọi kết quả tool trong lượt; phân tích số tiền có phân cách nghìn, số ≥1.000, tiền k/nghìn/ngàn/triệu/đ/VNĐ/VND; bỏ ID và số nhỏ không đơn vị. Chỉ giữ câu phí ship/vận chuyển/giao khi có số và tất cả khớp; nhánh chính sách phí và logistics vẫn chặn. Test `ShippingFeeTests` trong tệp mới. |
| 2 / F31 | DONE | Cùng tệp nguồn: cờ `refunded` theo payment status hoặc `refund_summary`/`refund` completed/refunded_total > 0; chỉ miễn khẳng định hoàn tiền có bằng chứng, kiểm tiếp khẳng định hành động khác. Test `RefundTests`, gồm pending, thiếu tool, nguồn không phải tool, hủy/đổi/trả/gửi/tạo yêu cầu. |
| 3 / F32 | DONE | Cùng tệp nguồn: chỉ lấy số ngay trước ngày/tuần/tháng/năm/giờ trong nhánh deadline; không số thời gian thì dùng cờ thời hạn/mốc giao của F29. Test `DeadlineProductNumbersTests`; test F29 cũ giữ nguyên và đạt. |
| 4 / S01 | DONE | Chỉ sao chép byte vào `%TEMP%/w632-s01/S01.jsonl`, không sửa hoặc commit nguồn hay bản tạm. Trước sửa 18/26; sau sửa 26/26. Không còn ca hỏng cần ghi câu trả lời. |

`notebooks/colab_agent.ipynb` chỉ sinh lại bằng `python scripts/build_agent_notebook.py` vì notebook nhúng cả mã nguồn và test; không chỉnh tay, không truy cập Colab. Tài liệu thay đổi gồm báo cáo này và một dòng mới 034 trong cột Codex của W1 execution log; không sửa dòng cũ.

## S01 trước và sau

- Nguồn: `.claude/worktrees/cai-nay-la-sao-bddcef/scratch/S01_26ca_check.jsonl` theo handoff.
- SHA-256 gốc và bản tạm trước/sau đều là `865094b62d9c92f66a1380c58c765607feb2378211b2d21c4cfc1226c8f6d53f`.
- `python scripts/check_eval_dataset.py <temp-dir>`: **26 pass, 0 fail, 0 skip** trước và sau.
- Trước sửa: runner `--fake --dataset-dir <temp-dir> --out <temp-report>`: **18 pass, 8 fail, 0 skip / 26**, 31 lượt, tool-call 52/52 hợp lệ. Hỏng đúng `s01_001`, `s01_003`, `s01_010`, `s01_014`, `s01_016`, `s01_021`, `s01_024`, `s01_026` như handoff.
- Sau sửa cuối: runner thêm `--min-success-rate 1.0`: **26 pass, 0 fail, 0 skip / 26**, 31 lượt, tool-call 52/52 hợp lệ. Báo cáo JSON cục bộ `%TEMP%/w632-s01-before.json` và `%TEMP%/w632-s01-after.json`.

## Kết quả từng lệnh

Các dòng script hợp đồng/build/diff dùng đơn vị một lượt kiểm (riêng validator dataset đếm ca, runner đếm scenario, unittest đếm method, JS đếm lượt lệnh). Không biến “không áp dụng” thành test skip.

| Lệnh | Pass | Fail | Skip | Bằng chứng / ghi chú |
|---|---:|---:|---:|---|
| `python -m unittest discover -s tests -p test_r1_w6_3_2_hotfix.py -v` cuối | 10 | 0 | 0 | Bao gồm mọi subtest |
| `python -m unittest discover -s tests -p test_r1_w3_2_answer_check.py -q` | 23 | 0 | 0 | Bộ answer check trước hotfix |
| `python -m unittest discover -s tests -p test_r1_w6_3_1_hotfix.py -q` | 11 | 0 | 0 | Giữ nguyên F29 và kiểm W6.3.1 |
| `python -m unittest discover -s tests -q` | 1067 | 1 | 86 | 1.154 method, 0 error, 536.243s; lỗi quét worktree cũ, chi tiết dưới |
| JS theo `ci.yml`, Node thật v24.22.1 | 11 | 0 | 0 | 10 tệp + public session persistent |
| `node --check` từng tệp `web/*.js` | 3 | 0 | 0 | app.js, chat-focus.js, embed.js |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | AGENT_NOTEBOOK_SOURCE_SYNC_OK |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | EVAL_PACK_OK |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 4/4 mục hợp đồng đạt |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | DEPLOYMENT_CONTRACT_OK |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | Chỉ kiểm hợp đồng |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | 30 baseline + 32 W3.2 + 12 W4 |
| `python scripts/check_eval_dataset.py evals/suites` | 41 | 0 | 0 | Giữ nguyên suite |
| `python scripts/check_eval_dataset.py <temp S01 dir>` | 26 | 0 | 0 | Trước và sau |
| `python scripts/run_agent_scenarios.py --fake --min-success-rate 1.0` | 32 | 0 | 0 | 35 lượt |
| Cùng runner `--fake --dataset evals/agent_scenarios_w4.jsonl --min-success-rate 1.0` | 12 | 0 | 0 | 14 lượt |
| Cùng runner `--fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0` | 4 | 0 | 0 | 4 lượt |
| Cùng runner `--fake --dataset-dir evals/suites --min-success-rate 1.0` | 41 | 0 | 0 | 47 lượt |
| Cùng runner `--fake --dataset-dir <temp S01 dir> --min-success-rate 1.0` | 26 | 0 | 0 | 31 lượt; trước sửa 18 pass, 8 fail |
| `git diff --check` | 1 | 0 | 0 | Không lỗi khoảng trắng |

Lượt full đầu (trước test bổ sung cuối) chạy **1.153 method: 1.065 pass, 2 fail, 0 error, 86 skip**, `595.059s`. Hai fail: `test_waitress_real_http_chat_saturation_headroom` với P99 `/api/session` **67,121600 ms > 50 ms**; `test_item10_package_isolation_and_image_exclusion` quét `ROOT.rglob('*.py')` rồi coi test ở `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` là import ngoài phạm vi. Không sửa ngưỡng hoặc dời/sửa worktree chứa S01. Chạy nguyên bài package isolation trên snapshot sạch tạo bằng `git archive 7100daa` vào thư mục tạm: **1 pass, 0 fail, 0 skip**. Suite đầy đủ được chạy lại trên code/test cuối để bảng trên phản ánh đúng bản giao.

Lượt full cuối: `Ran 1154 tests in 536.243s`, `FAILED (failures=1, skipped=86)`, exit 1. Chỉ còn lỗi package isolation nêu trên; mọi test W6.3.2 và answer check đều đạt. P99 `/api/session` cuối **45,700700 ms**, `/healthz` **27,173900 ms**, mỗi endpoint 1.000 mẫu, cùng đạt ngưỡng 50 ms. Log `%TEMP%/w632-full-final.txt`; artifact đo cục bộ `%TEMP%/headroom_p99_artifact.json`. Không thay đổi bài kiểm, fixture hoặc ngưỡng P99 để làm xanh.

Python cục bộ 3.10.7 dùng `PYTHONPATH=%TEMP%/w631-existing-deps` để nạp package PDF 5.14.0 đã có sẵn từ lượt W6.3.1, trùng phiên bản repo ghim. Không cài hay thêm thư viện. Không cấu hình DB production; các test PostgreSQL không có DB test được skip theo code hiện có; CI cung cấp PostgreSQL/pgvector tạm.

## PR, CI và điểm dừng

Commit test-first `66c5e1c`, sửa đầu `546fba1`, mã nguồn cuối `7100daaa0bd158878c4e3f9bac20eacbdcbb7f29`.

- PR [#98](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/98).
- [CI mã nguồn cuối](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/43198756343): **3 pass, 0 fail, 0 skip / 3 job** (`offline`, `colab-python313`, `clamav-smoke`).
- [Ops Console mã nguồn cuối](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/43198756285): **3 pass, 0 fail, 0 skip / 3 job** (`portable ubuntu`, `portable windows`, `postgres`).
- Native unittest với PostgreSQL/pgvector thật: `Ran 1154 tests in 377.931s`, `OK`: **1.154 pass, 0 fail, 0 error, 0 skip**.
- Unittest trong image: `Ran 1154 tests in 436.121s`, `OK (skipped=25)`: **1.129 pass, 0 fail, 0 error, 25 skip**. Đủ 10 test W6.3.2 đều `ok` ở cả native và image.
- P99 CI native: `/healthz` **1,124 ms**, `/api/session` **3,352 ms**, kiểm toàn vẹn artifact SUCCESS. Artifact mang SHA checkout merge thử của PR `376f4b9377a3396ff3fc8ecfbe807305a3f512b7`; head mã nguồn vẫn là `7100daa`, không merge PR.
- Kiểm image/helpers, HTTPS cookie qua CA tạm và packaged resolve-targets đều đạt. Log offline cục bộ `%TEMP%/w632-ci-offline.log`.

**DONE hàng 1–4; không có blocker hotfix.** Cục bộ còn một fail do worktree cũ; cùng bài đạt trên snapshot sạch và CI native/image. Kết quả CI 6/6 ở trên gắn với commit mã nguồn cuối `7100daa`; commit tài liệu báo cáo + dòng 034 được tạo sau kết quả này, không nhận kết quả này là CI của commit tài liệu đó. Sau khi ghi báo cáo và log, chạy lại hợp đồng tài liệu/build checks và `git diff --check`, commit/push tài liệu trên nhánh PR và dừng để owner review.

Tuân thủ mục Cấm: không merge/push main/force-push/rebase/reset/stash; không đổi variable/secret; không chạy deploy/live-e2e; không EC2/SSM/production DB/Colab/LLM thật/dữ liệu khách hàng; không thêm thư viện; không sửa hoặc commit S01/suite/hồi quy. Không đổi POLICY_NOTE/CLAIM_NOTE, rào, system prompt hay kho knowledge. Owner quyết định merge và các bước triển khai/smoke sau đó.

## Lượt 2 (sửa sau kiểm chứng)

Phạm vi theo chỉ dẫn trực tiếp của owner: chỉ sửa regression W6.3.2-D2 do mẫu mới `(?:đã|vừa)\s+được\s+hoàn\b` coi việc hoàn hàng về kho và hoàn tất giao hàng là hoàn tiền. Owner xác nhận không có mục 6 “Lượt 2” trong handoff và không yêu cầu nhập một thay đổi khác vào nhánh.

### Test-first và bằng chứng FAIL

Trên code hiện tại `671ed85`, chỉ thêm ba test method trong `tests/test_r1_w6_3_2_hotfix.py`, chưa sửa application. Lệnh:

```text
python -m unittest discover -s tests -p test_r1_w6_3_2_hotfix.py -v
Ran 13 tests in 0.011s
FAILED (failures=17)
```

Theo method: **11 pass, 2 fail, 0 error, 0 skip**; 17 subtest FAIL. Log `%TEMP%/w632-r2-red.txt`; commit test-only **`ebeb6f0`**, trước commit sửa **`1f137cb`**.

- `test_returned_shipments_and_completion_are_not_refund_claims`: cả ba câu owner nêu bị thay bằng `CLAIM_NOTE`, ví dụ `AssertionError: 'Em chưa thực hiện thay đổi nào trên đơn ...' != 'Đơn SIM-O-00027 đã được hoàn về kho sau 3 lần giao không thành công ạ.'`; hai câu còn lại là `Hàng đã được hoàn về kho của shop ạ.` và `Việc giao hàng đã được hoàn tất vào hôm qua ạ.`. Hai câu hoàn kho dùng tool có `order_status: cancelled`, `payment_status: unpaid`, `refund_summary: null`, shipment `returned`; câu giao hàng dùng `delivered`, `paid`.
- `test_non_refund_continuations_after_da_or_vua_are_preserved`: 14 subtest FAIL cho `đã`/`vừa` kết hợp bảy tiếp nối `về kho`, `về shop`, `về cửa hàng`, `về người gửi`, `tất`, `thiện`, `chỉnh`.
- `test_refund_to_wallet_account_and_success_still_need_completed_evidence` đã PASS trước sửa: `Khoản 490.000đ đã được hoàn về ví của anh/chị ạ.` và các biến thể về tài khoản/thành công vẫn bị cắt khi pending hoặc thiếu tool; có bằng chứng refunded thì được giữ.

### Thay đổi và trạng thái

**DONE phần regression:** `retailops/workflow/answer_check.py` dùng chung `_REFUND_COMPLETION` với negative lookahead loại đúng bảy tiếp nối owner chỉ định, cả tại `_CLAIMS` và `_REFUND_WORDS`. Hoàn về ví, về tài khoản, hoàn thành công và hoàn trả vẫn đi qua kiểm bằng chứng hoàn tiền. Không thay đổi quy tắc khác, ghi chú trả khách hoặc dữ liệu đánh giá. `notebooks/colab_agent.ipynb` sinh lại từ nguồn/test bằng script, không truy cập Colab.

Sau sửa: **13 pass, 0 fail, 0 error, 0 skip** của W6.3.2; giữ cả `Đơn đã được hoàn trả rồi ạ.` và `Đơn đã được hoàn thành công ạ.` khi có bằng chứng, cắt khi pending/thiếu tool. Bộ answer check cũ **23/23**, W6.3.1 **11/11**.

| Lệnh chạy lại trong Lượt 2 | Pass | Fail | Skip | Ghi chú |
|---|---:|---:|---:|---|
| `python -m unittest discover -s tests -p test_r1_w6_3_2_hotfix.py -v` | 13 | 0 | 0 | Test-first FAIL phía trên |
| `python -m unittest discover -s tests -p test_r1_w3_2_answer_check.py -q` | 23 | 0 | 0 | Giữ nguyên test cũ |
| `python -m unittest discover -s tests -p test_r1_w6_3_1_hotfix.py -q` | 11 | 0 | 0 | Giữ nguyên test cũ |
| `python -m unittest discover -s tests -q` | 1070 | 1 | 86 | 1.157 method, 0 error, 547.452s; lỗi quét worktree cũ |
| JS theo `ci.yml`, Node thật v24.22.1 | 11 | 0 | 0 | Gồm public session persistent |
| `node --check` từng tệp `web/*.js` | 3 | 0 | 0 | Không đổi JS |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | Đã sinh lại notebook |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | Không đổi eval pack |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 4/4 mục hợp đồng |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | Chỉ kiểm hợp đồng |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | Không chạy live-e2e |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | Giữ nguyên dữ liệu |
| `python scripts/check_eval_dataset.py evals/suites` | 41 | 0 | 0 | Giữ nguyên suite |
| `python scripts/check_eval_dataset.py <temp S01 dir>` | 26 | 0 | 0 | Giữ nguyên bản tạm từ lượt trước |
| Runner `--fake --min-success-rate 1.0` | 32 | 0 | 0 | 35 lượt |
| Runner `--fake --dataset evals/agent_scenarios_w4.jsonl --min-success-rate 1.0` | 12 | 0 | 0 | 14 lượt |
| Runner `--fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0` | 4 | 0 | 0 | 4 lượt |
| Runner `--fake --dataset-dir evals/suites --min-success-rate 1.0` | 41 | 0 | 0 | 47 lượt |
| Runner `--fake --dataset-dir <temp S01 dir> --min-success-rate 1.0` | 26 | 0 | 0 | 31 lượt, 52/52 tool-call hợp lệ |
| `git diff --check` | 1 | 0 | 0 | Không lỗi khoảng trắng |

S01 nguồn và bản tạm vẫn có SHA-256 `865094b62d9c92f66a1380c58c765607feb2378211b2d21c4cfc1226c8f6d53f`; không sửa hoặc commit S01. Dùng package PDF đã có sẵn qua cùng `PYTHONPATH` của lượt trước, không thêm thư viện. JSON runner cục bộ có tiền tố `%TEMP%/w632-r2-`; full unittest `%TEMP%/w632-r2-full.txt`.

Full unittest Lượt 2: `Ran 1157 tests in 547.452s`, `FAILED (failures=1, skipped=86)`, exit 1. Fail duy nhất là `test_item10_package_isolation_and_image_exclusion` tại `tests/test_marketplace_sim_stories_and_send.py:524`, quét vào `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` như lượt trước. Trên snapshot sạch tạo từ `git archive 1f137cb`, nguyên bài đạt **1 pass, 0 fail, 0 skip**, `1.230s`. Không sửa test hoặc dời worktree chứa S01. P99 cục bộ `/api/session` **46,238900 ms**, `/healthz` **23,649500 ms**, đạt ngưỡng 50 ms giữ nguyên.

### Nhánh, PR và CI của Lượt 2

Đã push thường hai commit `ebeb6f0`, `1f137cb` vào **`phase-r1-w6-3-2`**, không force-push. Khi đọc lại GitHub sau push, PR [#98](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/98) đã ở trạng thái **MERGED**, head đã merge là `671ed85`. Vì vậy các commit Lượt 2 nằm trên cùng nhánh nhưng không thể thêm vào diff của PR #98 đã merge; không có CI mới cho `1f137cb` qua PR đó. Kết quả CI xanh của `671ed85` không phải kết quả Lượt 2. Executor không thực hiện merge; đã báo tình trạng và chờ owner quyết định PR mới hay chỉ bàn giao nhánh.

Owner chọn mở PR mới từ nhánh hiện tại. Đã mở [PR #100](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/100), base `main`, head `phase-r1-w6-3-2`, mã nguồn `1f137cb33eb3d39f57a01f1aeb91647c0f0e5fdb`. Fetch xác nhận `origin/main` ở `810004b` (merge PR #98); không merge main vào nhánh, không rebase. CI Lượt 2 được kiểm trên PR #100, không dùng kết quả PR #98 thay thế.

**CI mã nguồn Lượt 2 `1f137cb`: 6 pass, 0 fail, 0 skip / 6 job.**

- [CI](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/43208181180): `offline`, `colab-python313`, `clamav-smoke` SUCCESS, **3/3 job**.
- [Ops Console](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/43208181217): portable Ubuntu/Windows và PostgreSQL SUCCESS, **3/3 job**.
- Native unittest với PostgreSQL/pgvector thật: `Ran 1157 tests in 404.451s`, `OK`: **1.157 pass, 0 fail, 0 error, 0 skip**.
- Unittest trong image: `Ran 1157 tests in 453.257s`, `OK (skipped=25)`: **1.132 pass, 0 fail, 0 error, 25 skip**. Đủ 13 test W6.3.2 đều `ok` ở cả hai lượt.
- P99 native: `/healthz` **1,028 ms**, `/api/session` **6,495 ms**; kiểm toàn vẹn artifact SUCCESS, SHA checkout merge thử `8da14b92ead6e8a2549acaa5ef65e9dc970db776`. Đây là checkout CI của PR mở, executor không merge PR. Kiểm image/helpers và HTTPS/cookie qua CA tạm đều đạt. Log cục bộ `%TEMP%/w632-r2-ci-offline.log`.

**DONE Lượt 2; không có blocker regression.** Một fail cục bộ do quét worktree cũ được giữ nguyên trong báo cáo; cùng bài đạt trên snapshot sạch và CI. Kết quả CI trên gắn với mã nguồn `1f137cb`, trước commit tài liệu báo cáo Lượt 2 và dòng 035 W1 log; không nhận kết quả đó là CI của commit tài liệu sau. Sau commit/push tài liệu trên cùng nhánh, dừng để owner kiểm chứng và quyết định merge PR #100.

Mục Cấm tiếp tục được tuân thủ; không sửa hoặc chạy thêm bất kỳ tác vụ production/deploy/live-e2e/LLM thật nào.
