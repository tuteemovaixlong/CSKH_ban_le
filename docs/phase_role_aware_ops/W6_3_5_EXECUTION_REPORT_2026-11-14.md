# W6.3.5 execution report — 2026-11-14

Executor: Codex. Áp dụng [handoff W6.3.5](W6_3_5_HOTFIX_HANDOFF_2026-11-14.md), [§30](W0_OWNER_DECISION_DELTA_2026-10-29.md#30-w635-owner-decisions-2026-11-14), F39–F41 và luật 6/11 của eval pack mục 2.

## 1. Preflight và phạm vi

- `git fetch origin` thành công. `origin/main` = `8341be9064f5fe134dcb4cd761a317c2eb0b0caa`, merge PR #107; parent thứ hai `825ab96a70146796e429d32ba0553e96727545b3` chứa handoff, §30, F39–F41 và biên bản deploy W6.3.1–W6.3.4. Đã đọc toàn bộ handoff, §30, biên bản và mục 2 eval pack trước sửa.
- Checkout chính sạch, ở `main`, trùng `origin/main`. Tạo bằng `git switch --no-track -c phase-r1-w6-3-5 origin/main`; không tracking `main`.
- Hàng 1: `agent_protocol.py` chỉ thêm quy tắc vào `SYSTEM`, thay mô tả tool hiện có `request_human_support`; test trong `tests/test_w6_3_5_hotfix.py`.
- Hàng 2: chỉ thêm luật một yêu cầu mở vào `SYSTEM`, ngay trước đoạn `prepare_order_action`; cùng tệp test.
- Hàng 3: `.github/workflows/deploy-ec2.yml` chỉ đổi timeout job `deploy` 20 → 40; `.github/workflows/ci.yml` chỉ đổi timeout job `offline` 18 → 30; test đọc văn bản bằng thư viện chuẩn `re` và `pathlib`.
- `notebooks/colab_agent.ipynb` sinh lại từ source bằng `python scripts/build_agent_notebook.py`. Tài liệu: báo cáo này và một dòng mới 038, chỉ cột Codex của W1 execution log.
- Không thêm tool, thư viện hay migration. Không đổi `validate_tool`, giới hạn `reason` 1.000 ký tự, `GENERAL_SYSTEM`, các câu cũ của `SYSTEM`, server chặn yêu cầu thứ hai, rào an toàn hay answer check. Không sửa dữ liệu eval/hồi quy, eval pack, kho chính sách.

## 2. Nguyên văn nội dung cuối

Hai đoạn thêm vào `SYSTEM`:

```text
Staff-only work: call request_human_support this turn without asking; say transferred.
```

```text
One open cancel/return/exchange per order; if two, explain and ask which. If tool reports open, say so; no second.
```

Mô tả mới của tool hiện có `request_human_support` (không tạo tool mới):

```text
Escalate conversation to a live human agent when user requests or on severe complaint. Call request_human_support in the same turn, without asking first, when the customer asks for something only staff can do: changing an order's delivery address or recipient, issuing or correcting a VAT invoice, or disputing a carrier's false failed-delivery report. Then tell the customer the case has been transferred. Questions that only ask for information, such as who issues invoices, staff hours or fees, are not requests for a human.
```

Giữ nguyên câu shipping: `when an order is in 'shipping' status, explain self-service cancellation is unavailable and offer transfer to human support.` Test giữ kiểm tra câu này, `reason` 1.000 ký tự được chấp nhận, rỗng/1.001 ký tự/đối số lạ bị từ chối.

Theo quyết định owner sau khi kiểm chứng: không tăng `MAX_SYSTEM_CHARACTERS=6400`, không sửa câu SYSTEM cũ. Phần SYSTEM chỉ giữ ý cốt lõi; danh sách ba việc F39 và ngoại lệ câu hỏi thông tin nằm trong mô tả tool. Bản cuối `SYSTEM` = **5.993** ký tự; không có focus = **6.086**; với hai focus ID dài tối đa 64 ký tự = **6.284/6.400** (đính chính khi Claude kiểm chứng; bản đầu báo cáo ghi nhầm 6.086 cho trường hợp focus tối đa). Mô tả tool vẫn giữ giải thích đầy đủ.

## 3. Test trước sửa, theo đúng thứ tự

Lệnh mỗi bước: `python -m unittest discover -s tests -p test_w6_3_5_hotfix.py -q`.

| Hàng | Trước sửa code tương ứng | Dòng lỗi đã quan sát | Sau sửa |
|---|---|---|---|
| 1 / F39 | 2 method: 1 pass, 1 method fail với 16 subtest fail, 0 error/skip | `AssertionError: False is not true : SYSTEM missing: in the same turn, without asking first`; `AssertionError: False is not true : tool description missing: in the same turn, without asking first` | 2 pass, 0 fail/error/skip; protocol cũ 13 pass |
| 2 / F40 | 3 method: 2 pass, 1 method fail với 4 subtest fail, 0 error/skip | `AssertionError: False is not true : SYSTEM missing: Each order can have only one open cancel, return or exchange request at a time` | 3 pass, 0 fail/error/skip |
| 3 / F41 | 4 method: 3 pass, 1 method fail với 2 subtest fail, 0 error/skip | `AssertionError: Regex didn't match: '(?m)^    timeout-minutes: 40$'` và `AssertionError: Regex didn't match: '(?m)^    timeout-minutes: 30$'` (trích đầu dòng lỗi; phần `not found in` chứa nguyên khối job với timeout thực tế 20 và 18) | 4 pass, 0 fail/error/skip |

F39 trước sửa thiếu cả ba việc, ý trong cùng lượt/không hỏi, báo đã chuyển và ngoại lệ câu hỏi thông tin ở cả SYSTEM/schema. F40 trước sửa thiếu luật một yêu cầu, ví dụ trả+đổi, hỏi chọn và xử lý khi tool báo có yêu cầu mở. Test kiểm tất cả ý này; không chỉ kiểm một từ khóa.

Test biên prompt bổ sung cũng chạy FAIL trước khi rút gọn: `AssertionError: 6810 not less than or equal to 6400`. Khi chuyển từ focus 63 sang đúng tối đa 64 ký tự, bắt tiếp `AssertionError: 6402 not less than or equal to 6400`, rồi rút gọn liên từ của riêng đoạn F40. Test cuối: **5 pass, 0 fail/error/skip**, gồm 2 F39, 2 F40/biên prompt và 1 F41. Protocol cũ: **13 pass, 0 fail/error/skip**; W6.2 safety: **7 pass, 0 fail/error/skip**.

## 4. Kết quả các lệnh bắt buộc

Python **3.10.7**, Node thật **v24.22.1**. `python` trong lượt kiểm có PDF là interpreter sẵn có `%TEMP%/venv_pdf/Scripts/python.exe`, với `PYTHONUTF8=1`; không cài thêm thư viện. Dùng `PATH` trong tiến trình lệnh để chọn interpreter này, không đổi variable/secret của repo. Chỉ test dữ liệu giả lập, gateway fake, SQLite tạm và loopback.

Unittest đếm method; runner/dataset/hash đếm ca/tệp; script contract/build/JS/syntax/diff đếm lượt lệnh exit 0. Không tự suy số assertion của script không công bố assertion count.

| Lệnh | Pass | Fail | Error | Skip | Bằng chứng |
|---|---:|---:|---:|---:|---|
| `python -m unittest discover -s tests -q` | 1099 | 3 | 0 | 86 | 1188 method, 672,389s; chi tiết ba lỗi dưới đây |
| Cùng lệnh trên snapshot sạch nguồn cuối sau quyết định owner | 1188 | 0 | 0 | 86 | PASS; assertion đã đồng bộ với `MAX_SYSTEM_CHARACTERS` |
| JS theo CI (11 lượt, liệt kê dưới) | 11 | 0 | 0 | 0 | Node thật; lượt cuối còn chạy 4 test `node:test`, 4 pass/0 fail/skip |
| `node --check` từng tệp `web/*.js` | 3 | 0 | 0 | 0 | app.js, chat-focus.js, embed.js |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | 0 | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | 0 | `EVAL_PACK_OK` |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 0 | 4 nhóm kiểm đều PASS |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | 0 | `DEPLOYMENT_CONTRACT_OK` |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | 0 | `LIVE_E2E_CONTRACT_OK`; chỉ kiểm hợp đồng offline |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | 0 | baseline 30, W3.2 32, W4 12 |
| `python scripts/check_eval_dataset.py evals/suites --final` | 250 | 0 | 0 | 0 | `EVAL_DATASET_OK suites cases=250` |
| `python scripts/run_agent_scenarios.py --fake` | 32 | 0 | 0 | 0 | 100%, 35 lượt, 33/33 tool call hợp lệ |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl` | 12 | 0 | 0 | 0 | 100%, 14 lượt, 17/17 tool call hợp lệ |
| `python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0` | 4 | 0 | 0 | 0 | 100%, 6/6 tool call hợp lệ |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0` | 250 | 0 | 0 | 0 | 100%, 336 lượt, 469/469 tool call hợp lệ, attack success rate 0 |
| `sha256sum evals/suites/*.jsonl` so bảng đóng băng | 12 | 0 | 0 | 0 | Git for Windows `usr/bin/sha256sum.exe`; kiểm thêm bằng hashlib |
| `git diff --check` | 1 | 0 | 0 | 0 | Exit 0 |

11 lượt JS đúng CI:

```text
node tests/test_chat_focus.js
node tests/test_model_status.js
node tests/test_knowledge_sources.js
node tests/test_shipment_ui.js
node tests/test_provider_selector.js
node tests/test_case_assistant_ui.js
node tests/test_public_session.js
RETAILOPS_UI_TEST_MODE=persistent node tests/test_public_session.js
node tests/test_w5_ui.js
node tests/test_r1_w6_1b_1_1_ui_d8_v9.js
node tests/test_r1_w6_1b_2_ui.js
```

Lượt ban đầu dùng Python mặc định thiếu PDF và bản câu gợi ý vượt giới hạn: W3.2 **5 pass/27 fail**, ví dụ **1 pass/3 fail**; W4 và suites bị ngắt bởi `ModuleNotFoundError: No module named 'pypdfium2'`. Không sửa ca hay tiêu chí chấm để né lỗi. Sau khi rút gọn riêng câu mới và chọn interpreter PDF sẵn có, cả bốn bộ đạt 100% như bảng. Kết quả/log JSON cục bộ nằm trong `artifacts/w635_{w3,w4,examples,suites}.{json,log}`, không commit artifact sinh ra.

Unittest ban đầu với Python mặc định và prompt dài: **942 pass, 57 fail, 96 error, 89 skip / 1184**, 644,260s. Lượt có PDF trong bảng được khởi động trước thay đổi cuối (rút gọn liên từ F40 thêm 3 ký tự và test focus 63 → 64 ký tự); giữ nguyên số liệu đó, không gọi là kết quả của snapshot nguồn cuối. Ba lỗi:

- `test_waitress_real_http_chat_saturation_headroom`: `AssertionError: 59.1087999928277 not less than or equal to 50.0 : GET /api/session empirical nearest-rank P99 (59.108800ms, display=59.109ms) exceeded 50.0ms SLO`. Giữ nguyên ngưỡng 50 ms.
- `test_item10_package_isolation_and_image_exclusion`: quét nhầm `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` ngoài checkout đang sửa. Nguyên bài trên snapshot sạch nguồn cuối đã **1 pass, 0 fail/error/skip**, 2,150s; không sửa bài kiểm hay worktree cũ.
- Owner đã cho phép đổi assertion `tests/test_r1_w3_2_agent_loop.py:519` từ `<6000` sang `<=MAX_SYSTEM_CHARACTERS`; giữ nguyên các kiểm tra không có câu trả lời viết sẵn. Đây là thay đổi test ngoài ba test W6.3.5, được thực hiện vì giới hạn thật đã là 6.400 từ W6.2 và test focus 64 ký tự phải qua `validate_messages`.

Snapshot sạch `%TEMP%/w635-clean-tx76114s` được tạo bằng archive base + overlay tệp đổi, không gồm worktree `.claude`. Sau quyết định owner, cập nhật test assertion và chạy lại toàn bộ: **1188 pass, 0 fail, 0 error, 86 skip / 1188**, 1100,636s. P99/package isolation đạt. Các skip do điều kiện dependency/dịch vụ test tùy chọn; không dùng DB production để loại skip. Log lượt trước và snapshot sạch được giữ trong `%TEMP%/w635-clean-tx76114s/w635_unittest_clean.log`.

## 5. SHA-256 và trạng thái từng hàng

Đọc bảng cuối `evals/suites/README.md`, so byte gốc của đủ 12 tệp; **12 khớp, 0 khác, 0 skip**:

```text
6742499c31f1ced367b90eb2a29a1e543c22f9b502b21ef7ce5260c555c568d4  S01.jsonl
35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d  S02.jsonl
9142f8b7f2b57dd2913ad18b9e5646d7453226d0ff97f87864301b5d341340a5  S03.jsonl
f71400121a9f86db71b86ee1c1f38a968d2cf5d2a8892d9357c6704d4f65e55f  S04.jsonl
999903d49e166de1a56c65fca7876958e99c82fbf31d2363e04931c8005be6dc  S05.jsonl
5de3c66a24244725aafbe37799381686ef5461d4bc7815b93b7bac8be0fc8355  S06.jsonl
550771b72d3a0d443969009d503df1de4e0058e5f2d176dc04f0d605f437bb37  S07.jsonl
3d07cefccb72fa13e1854d20efc20d678257c286f267e0cdca3a6997ea04b370  S08.jsonl
74ac253b32a161c9c0341981ff05033877d448c71f706fc9e568c70cb9654e37  S09.jsonl
01562bc4e6241172481f6e43a4b556ce6278212836d20fb8af14b7302a53404b  S10.jsonl
63cd47390bc3a1afb409a2706dbc7270aae6dcb4b80514d6ccdaf3af35c14386  S11.jsonl
db70f9e760c341ddb5170f2c28fa29e68681648716c8b26c5a85101ce9446377  S12.jsonl
```

| Hàng | Trạng thái | Căn cứ |
|---|---|---|
| 1 F39 / D1 | DONE | Test-first; đủ ba việc, ngay lượt/không hỏi, báo đã chuyển, ngoại lệ; giữ shipping/reason/protocol |
| 2 F40 / D2 | DONE | Test-first; luật một yêu cầu, trả+đổi/chọn một, lỗi yêu cầu mở; giữ nguyên server |
| 3 F41 / D3 | DONE | Test-first; chỉ 2 dòng timeout; deployment contract đạt |
| 4 Hồi quy | DONE | Fake 32/32 + 12/12 + 4/4 + 250/250, dataset 250 và 12 hash đạt; full snapshot sạch **1188/1188** |

Các chi tiết khác trong mục 2 eval pack chưa được viết tường minh trong SYSTEM, chỉ ghi nhận ngoài phạm vi: luật 3 gợi ý từ chối nhận rồi trả; luật 4 các mốc 7/15/90 ngày (server/tool/chính sách có trách nhiệm tính và cung cấp); luật 7 danh sách nhãn lý do và mô tả bắt buộc cho “Lý do khác”; luật 16 quy tắc riêng của Trợ lý ca dùng prompt khác. Không bổ sung các luật đó trong hotfix này.

## 6. PR, CI và ranh giới dừng

Nhánh: `phase-r1-w6-3-5`. Commit nguồn ban đầu: `201c154`; sau quyết định owner đã cập nhật prompt cốt lõi, test assertion và notebook. Đang chuẩn bị commit/push nhánh và mở PR; chưa có CI.

Không merge, push main, force-push, rebase, reset hay stash; không đổi secret/variable repo, không chạy workflow deploy/live-e2e; không truy cập EC2/SSM/DB production/Colab/LLM thật/dữ liệu khách. Owner quyết merge; kiểm chứng Claude và smoke production mục 5 handoff thực hiện sau theo quy trình owner.

## 7. Bổ sung sau kiểm chứng của Claude (2026-11-14)

Claude kiểm nhánh `phase-r1-w6-3-5` tại `42fc413` theo mục 5 handoff. Kết quả đạt mọi tiêu chí của mục 2:

- 8 tệp đổi, đúng phạm vi. `SYSTEM` chỉ thêm 2 câu, không sửa câu cũ; mô tả tool `request_human_support` giữ câu cũ và có đủ ba việc cùng ngoại lệ; hai workflow chỉ đổi dòng `timeout-minutes`.
- 99 test liên quan OK cục bộ (W6.3.5, W3.2 agent loop, W6.2 safety, agent protocol, W6.3.1, W3.2 answer check).
- Notebook, eval pack, ba contract, `--final` 250 ca và SHA đóng băng 12/12 đều đạt; runner `--fake` 250/250 và 32/32.
- Độ dài `agent_system` đo lại: 6.086 không focus, 6.162 với focus ngắn, 6.284 với hai focus ID 64 ký tự. Còn trống 116 ký tự dưới giới hạn 6.400.

Hai lỗi tài liệu được sửa trong cùng nhánh, đều không đổi mã hay test:

- tệp báo cáo này được commit dạng CRLF, nên `git diff --check` báo khoảng trắng cuối mọi dòng; đã đổi sang LF;
- con số độ dài với focus tối đa ở mục 2.

Hiệu quả thật của câu `SYSTEM` gọn và mô tả tool mới chỉ kiểm được bằng smoke trên production sau khi deploy (mục 5 handoff).
