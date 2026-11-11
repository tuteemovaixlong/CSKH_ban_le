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

## Hàng 4 — S07 trước sửa

- Chỉ sao chép byte từ `E:/hệ thống/S07.jsonl` vào `%TEMP%/w631-s07/S07.jsonl`; không đọc để sửa ca, không đưa vào Git.
- SHA-256 gốc: `a8cb07fbb35eb6f336d762204b69b555db4390e06dd71132865218be1b37c72a`.
- `python scripts/check_eval_dataset.py <temp-dir>`: 11 ca hợp lệ.
- `python scripts/run_agent_scenarios.py --fake --dataset-dir <temp-dir> --out <temp-report>`: **5 pass, 6 fail, 0 skip / 11 ca**, 13 lượt; khớp số Claude đo.
- Ca hỏng: `s07_001`, `s07_002`, `s07_003`, `s07_004`, `s07_005`, `s07_011`. Hai ca lỗi bước chưa dùng; bốn ca lỗi chuyển người, `s07_002` còn mất dữ kiện vận chuyển do answer check.

## Kết quả cuối

Đang thực thi; kết quả kiểm tra và PR được ghi sau khi hoàn tất.
