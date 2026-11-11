# W6.3.1 execution report — 2026-11-11

## Nguồn và nhánh

- Đã chạy `git fetch origin`; nhánh `phase-r1-w6-3-1` tạo bằng `git switch --no-track -c phase-r1-w6-3-1 origin/main` tại `1bb9dab9ffafc248df813da241cb0d14993752b5`, trong worktree riêng.
- `origin/main` tại thời điểm fetch chưa có handoff W6.3.1 hoặc §25. Đã đọc trực tiếp nguyên văn hai tệp tại worktree nhánh tài liệu `docs/r1-w6-3-1-hotfix-handoff`, commit `8e9c26bfc43df5d94ca91d27aa44d97d67eb133c`; thực thi theo chỉ thị owner trong chat này. Không nhập các thay đổi tài liệu đó vào nhánh thực thi.

## Bằng chứng test-first, trước khi sửa production code

`python -m unittest discover -s tests -p test_r1_w6_3_1_hotfix.py -v`:
`Ran 10 tests in 4.834s`, `FAILED (failures=18)` (18 assertion/subtest thất bại, 0 error; 4 test method pass, 6 fail, 0 skip).

| Hàng | Test và lỗi quan sát trên code chưa sửa |
|---|---|
| 1 | `test_reason_lengths_create_real_handoffs`, lengths 65/300/1000: `AssertionError: None != 'escalated_to_human'`. Length 1 đã tạo `handoff_episodes` thật. `test_unfounded_handoff_claims_need_success_this_turn`: câu `Em đã chuyển cuộc trò chuyện cho nhân viên ạ.` vẫn còn thay vì ghi chú khi tool lỗi. |
| 2 | `test_server_deadline_facts_survive_only_with_tool_evidence`: cả ba câu dữ kiện trong handoff bị thay bằng `POLICY_NOTE`. `test_each_deadline_field_and_false_eligibility_is_evidence`: `AssertionError: True is not false` cho các trường số ngày/cờ mới. |
| 3 | `test_rail_can_leave_two_steps_unused`: `AssertionError: False is not true : ['turn 1: 2 scripted reply(ies) were never asked for: the script is out of date']`. Test yêu cầu `get_order` vẫn lỗi và cũng bị báo thừa bước. |

Tệp test mới dùng dữ liệu tổng hợp. Lượt chạy nháp đầu phát hiện tên bảng fixture sai (`handoffs`); đã sửa thành `handoff_episodes` và chạy lại như kết quả trên trước khi sửa mã nguồn.

Rà soát bổ sung hàng 1: viết `test_hedge_after_a_completed_transfer_does_not_prove_it` và chạy riêng thấy `Ran 1 test`, `FAILED (failures=1)`: câu `Em đã chuyển yêu cầu cho nhân viên nhưng chưa có phản hồi ạ.` vẫn được giữ do hedge phía sau. Sau đó bỏ miễn trừ hedge trong kiểm khẳng định chuyển người; câu hỏi/đề nghị không có khẳng định hoàn tất vẫn được giữ. Bộ mới cuối cùng **11 pass, 0 fail, 0 skip**; bộ `answer_check` cũ **23 pass, 0 fail, 0 skip**.

## Hàng 4 — S07 trước sửa

- Chỉ sao chép byte từ `E:/hệ thống/S07.jsonl` vào `%TEMP%/w631-s07/S07.jsonl`; không đọc để sửa ca, không đưa vào Git.
- SHA-256 gốc: `a8cb07fbb35eb6f336d762204b69b555db4390e06dd71132865218be1b37c72a`.
- `python scripts/check_eval_dataset.py <temp-dir>`: 11 ca hợp lệ.
- `python scripts/run_agent_scenarios.py --fake --dataset-dir <temp-dir> --out <temp-report>`: **5 pass, 6 fail, 0 skip / 11 ca**, 13 lượt; khớp số Claude đo.
- Ca hỏng: `s07_001`, `s07_002`, `s07_003`, `s07_004`, `s07_005`, `s07_011`. Hai ca lỗi bước chưa dùng; bốn ca lỗi chuyển người, `s07_002` còn mất dữ kiện vận chuyển do answer check.

## Kết quả cuối

| Hàng | Trạng thái | Tệp và hành vi |
|---|---|---|
| 1 | DONE | `agent_protocol.py`: chỉ `request_human_support.reason` nhận 1–1.000 ký tự. `retailops/workflow/answer_check.py`: ghi nhận `escalated_to_human` trong tool của lượt, cắt khẳng định đã chuyển không có căn cứ và thêm đúng câu ghi chú; giữ câu hỏi/đề nghị. Test mới ở `tests/test_r1_w6_3_1_hotfix.py`; fixture acknowledgement cũ ở `tests/test_r1_w3_2_answer_check.py` được bổ sung kết quả chuyển thành công theo D1, các assertion giữ nguyên. |
| 2 | DONE | `answer_check.py`: thu bốn trường số ngày, ba cờ điều kiện thời hạn và ba mốc giao; chỉ miễn trích dẫn cho dữ kiện thời hạn đủ bằng chứng, giữ nguyên yêu cầu trích dẫn phí/giao nhận. Bỏ qua chữ số nằm trong ID định danh, để `SIM-O-1` không bị hiểu thành số ngày (đúng hai ví dụ không có số ngày trong handoff). Không thêm luật riêng cho S07. |
| 3 | DONE | `scripts/run_agent_scenarios.py`: ở fake, lượt không gọi model bỏ kiểm bước thừa và ghi `rail_answered: true`; `grade_turn` và `grade_final_state` giữ nguyên. Ca tổng hợp vẫn hỏng khi đòi `get_order`; lượt model thật sự chạy vẫn lỗi khi thừa bước. |
| 4 | DONE | S07 sau sửa **11 pass, 0 fail, 0 skip / 11**, 13 lượt, tool hợp lệ 15/15; không còn ca hỏng. SHA-256 tệp gốc và bản tạm không đổi. |

`notebooks/colab_agent.ipynb` được sinh lại từ nguồn, không chỉnh tay.

| Lệnh kiểm | Pass | Fail | Skip | Ghi chú |
|---|---:|---:|---:|---|
| Test W6.3.1 cô lập sau sửa | 11 | 0 | 0 | 11 test method; mọi subtest đạt |
| `unittest discover -s tests -p test_r1_w3_2_answer_check.py -q` | 23 | 0 | 0 | Bộ cũ giữ nguyên assertion, thêm bằng chứng chuyển thành công cho fixture |
| `python -m unittest discover -s tests -q` | pending | pending | pending | Đang chạy toàn bộ |
| JS theo `ci.yml`, Node v24.22.1 | 11 | 0 | 0 | Gồm public session mặc định và persistent |
| `node --check web/*.js` | 3 | 0 | 0 | Từng tệp bằng Node thật |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | `EVAL_PACK_OK` |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | Cả bốn mục hợp đồng đạt |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | `DEPLOYMENT_CONTRACT_OK` |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | Chỉ kiểm hợp đồng, không chạy live-e2e |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | 30 baseline + 32 W3.2 + 12 W4 hợp lệ |
| `check_eval_dataset.py <temp S07 dir>` | 11 | 0 | 0 | Trước sửa, không sửa dữ liệu |
| Runner fake W3.2 | 32 | 0 | 0 | 35 lượt |
| Runner fake W4 | 12 | 0 | 0 | 14 lượt |
| Runner fake `khoa_luan/eval_pack/06_vi_du.jsonl` | 4 | 0 | 0 | 4 lượt |
| Runner fake S07 sau sửa | 11 | 0 | 0 | 13 lượt; trước sửa 5 pass / 6 fail |
| `git diff --check` | 1 | 0 | 0 | Không lỗi khoảng trắng |

Lượt W4 đầu chạy bằng Python 3.10.7 thiếu `pypdfium2`, dừng sau 1 ca pass với `ModuleNotFoundError`. Đã dùng đúng thư viện `pypdfium2==5.14.0` có sẵn trong runtime của app (trùng phiên bản đã ghim ở repo), sao chép package vào thư mục tạm và đặt `PYTHONPATH` chỉ cho lệnh kiểm để chạy W4 đạt 12/12. Không cài dependency mới, không sửa requirements.

PR: [#94](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/94), base `main`, head `phase-r1-w6-3-1`. CI đang theo dõi; sẽ ghi kết quả cuối trước khi dừng. Không merge, không deploy; không sửa suite/hồi quy, prompt, rào an toàn hoặc kho chính sách. Không truy cập production hay model thật.
