# Phase R1 — W6.3.3 execution report (2026-11-12)

Thực hiện [handoff W6.3.3](W6_3_3_HOTFIX_HANDOFF_2026-11-12.md), quyết định owner §27. Nhánh `phase-r1-w6-3-3` tạo bằng `git switch --no-track -c phase-r1-w6-3-3 origin/main` sau fetch, từ `95e0abf` (merge #99), bao gồm `9e36e2d` (merge #100) và W6.3.2. Upstream sau push là `origin/phase-r1-w6-3-3`, không theo dõi main.

## 1. Tệp đổi và trạng thái từng hàng

| Hàng | Trạng thái | Tệp và kết quả |
|---|---|---|
| 1 — F33 / D1 | **DONE** | `retailops/workflow/safety.py`: bỏ đúng hai từ khóa đứng riêng `livestream`, `quay clip`; dùng nhóm tín hiệu phương tiện + ý công khai trong cùng tin, không phụ thuộc thứ tự. Giữ các từ khóa cụ thể cũ, rào read-only và thứ tự an toàn. Test trong `tests/test_r1_w6_3_3_hotfix.py`: đủ sáu câu bình thường, bốn câu đe dọa owner, các tổ hợp tín hiệu ở cả hai thứ tự, chữ hoa và ưu tiên chống lộ prompt. |
| 2 — F34 / D2 | **DONE** | `agent_protocol.py`: ưu tiên mã sản phẩm `P-` + đúng ba chữ số có ranh giới từ và đủ 13 cụm bán lẻ không dấu; giữ tín hiệu mã đơn `sim-o-` có sẵn. Bỏ `" sac"`, `"sac "` khỏi `_GENERAL_TERMS`, giữ các mục khác. Test đủ bảy câu owner, ba câu thuật toán, mã/thuật ngữ bán lẻ đối đầu từ khóa general, kế thừa lịch sử và mã sản phẩm sai dạng. Giữ test protocol cũ bằng ngữ cảnh yêu cầu giải thích SAC (không dùng SAC đứng riêng để phân loại). |
| 3 — S02/S03 | **DONE** | Chỉ chép hai tệp nguồn sang `scratch/w6_3_3/datasets/S02.jsonl`, `S03.jsonl` (thư mục tạm được gitignore). Validator **48/48**; fake trước **16/18 + 29/30**, sau **18/18 + 30/30**. Không sửa hoặc commit hai tệp này. |
| Kiểm tra/báo cáo mục 4 | **BLOCKED phần PR/CI** | Đã chạy đủ lệnh cục bộ và ghi số liệu dưới đây. Chưa có PR vì biểu mẫu GitHub chưa được Submit; chưa có CI của PR để nghiệm thu. |

`notebooks/colab_agent.ipynb` sinh lại bằng `python scripts/build_agent_notebook.py` để đồng bộ hai nguồn được nhúng; không chỉnh tay. Tài liệu: báo cáo này và thêm dòng **036** vào cột Codex của W1 execution log; giữ nguyên mọi dòng cũ/cột Argon.

## 2. Bằng chứng test-first

Commit **`410a440`** chỉ thêm test, trước bản sửa **`a49b340`**. Trước khi sửa nguồn, `git diff --exit-code -- agent_protocol.py retailops/workflow/safety.py` đạt, bảo đảm hai nguồn còn nguyên ở `95e0abf`.

Lệnh:

```text
python -m unittest discover -s tests -p test_r1_w6_3_3_hotfix.py -v
Ran 11 tests in 0.009s
FAILED (failures=33)
```

Ở đây có **5 method pass, 6 method fail, 0 error, 0 skip**; `failures=33` là **33 subtest FAIL**, không phải 33 method. Phân bố: câu livestream/quay clip bình thường 6, câu tương tự/chữ hoa 2, bảy câu bán lẻ owner 7, mã sản phẩm trước general 2, 13 cụm không dấu trước general 13, sac/sach đứng riêng 3. Các câu đe dọa và câu thuật toán có ngữ cảnh đã đạt trên code cũ.

Trích dòng lỗi hàng 1 (lần chạy UTF-8, `scratch/w6_3_3/evidence/red.txt`):

```text
FAIL: test_normal_livestream_and_unboxing_messages (...) (text='Hôm qua mình xem livestream của shop thấy áo này đẹp, còn size M không?')
  self.assertFalse(extreme_rage_text(text))
AssertionError: True is not false
```

Trích dòng lỗi hàng 2:

```text
FAIL: test_owner_unaccented_messages (...) (text='ao P-101 co mau sac nao khac khong')
  self.assertEqual(classify_user_text(text), "retail")
AssertionError: 'general' != 'retail'
```

Sau sửa đầu, 11 test mới đạt nhưng test cũ `test_general_mode_is_tool_free_and_depth_adaptive` thất bại ở câu `giải thích ngắn SAC` (`short['tools']` khác `[]`). Không sửa/nới test cũ. Thêm `test_sac_explanation_context_preserves_existing_general_behavior`, chạy trước khi sửa phần ngữ cảnh: **12 method, 11 pass, 1 fail, 0 error/skip**, **4 subtest FAIL**, `AssertionError: None != 'general'` (`red-context.txt`). Sau đó mới thêm nhận diện yêu cầu `giải thích` / `explain` + độ dài tùy chọn + SAC; tín hiệu retail vẫn được kiểm trước. Cuối cùng **12/12 test mới**, **13/13 protocol cũ** đạt.

## 3. S02 và S03 trước/sau

Nguồn chỉ đọc dưới `.claude/worktrees/cai-nay-la-sao-bddcef/scratch/`; SHA-256 gốc và bản chép trước/sau đều khớp handoff:

| Tệp nguồn → tên tạm | Ca | SHA-256 |
|---|---:|---|
| `S02_v2.jsonl` → `S02.jsonl` | 18 | `35cd5b0df89c4b174547d1a94d86c5d428e67cca8df98f1128fd3d12517ef54d` |
| `S03_30ca.jsonl` → `S03.jsonl` | 30 | `0bc3b70a4d9eac2d910908e380dc0a2bcea9077e9f6eee9a0b959c7b224e3941` |

```text
python scripts/check_eval_dataset.py scratch/w6_3_3/datasets
python scripts/run_agent_scenarios.py --fake --dataset-dir scratch/w6_3_3/datasets --min-success-rate 1.0 --out <report.json>
```

| Thời điểm | S02 pass/fail/skip | S03 pass/fail/skip | Tổng |
|---|---|---|---|
| Nguồn chưa sửa `95e0abf`, test-first `410a440` | 16 / 2 / 0 | 29 / 1 / 0 | 45/48; 54 lượt; tool hợp lệ 60/60 |
| Bản sửa cuối `a49b340` | 18 / 0 / 0 | 30 / 0 / 0 | 48/48; 54 lượt; tool hợp lệ 64/64 |

Hỏng trước sửa đúng `s02_010_bomber_livestream_size_l_het_hoi_xl`, `s02_013_so_sanh_hai_mau_ao_polo`, `s03_028_chinh_sach_mua_si_khong_bang_chung`. Ca 010 gọi nhầm `request_human_support` thay vì `get_product` và trả nguyên `RAGE_REPLY` (bắt đầu “Dạ shop thành thật xin lỗi vì trải nghiệm rất không tốt…”). Hai ca còn lại trả answer rỗng và `agent_response_failed`: “Model general-mode đã trả tool call không hợp lệ. Hãy thử lại tin nhắn.” Sau sửa không còn ca hỏng. JSON/log trước `before.json`/`before.txt`, sau cuối `s02_s03.json`/`s02_s03.txt` trong `scratch/w6_3_3/evidence/`; không commit dữ liệu hay log tạm.

## 4. Kiểm tra theo từng lệnh

Đơn vị: unittest đếm method; runner đếm scenario; validator đếm ca; JS và script build/contract/diff đếm lượt lệnh (mỗi lượt exit 0 là một pass). Không coi phần “không áp dụng” là skip. Tất cả runner dưới đây dùng **`--fake --min-success-rate 1.0`**, không model/network.

| Lệnh | Pass | Fail | Skip | Ghi chú |
|---|---:|---:|---:|---|
| `python -m unittest discover -s tests -p test_r1_w6_3_3_hotfix.py -v` cuối | 12 | 0 | 0 | Đủ subtest; log `green.txt` |
| `python -m unittest discover -s tests -p test_agent_protocol.py -q` cuối | 13 | 0 | 0 | Giữ nguyên test cũ; `protocol.txt` |
| `python -m unittest discover -s tests -p test_r1_w6_2_safety.py -q` | 7 | 0 | 0 | Đủ bảng owner 30 câu |
| `python -m unittest discover -s tests -p test_r1_w6_2_1_safety.py -q` | 3 | 0 | 0 | Đủ bảng dọa kiện ngầm 8 câu và bảng cũ |
| `python -m unittest discover -s tests -q` | 1081 | 1 | 86 | **Thêm 1 error**, tổng 1169 method, 514.074s; chi tiết dưới |
| `python -m unittest test_remote.ProxyHTTPTests.test_admin_and_query_routes_unavailable -v` | 1 | 0 | 0 | Chạy lại riêng bài HTTP loopback lỗi trong full; 0 error |
| `python -m unittest test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests.test_item10_package_isolation_and_image_exclusion -v` trên snapshot sạch `a49b340` | 1 | 0 | 0 | Không sửa test; 0 error |
| `node --check web/app.js` | 1 | 0 | 0 | Node thật v24.22.1 |
| `node --check web/chat-focus.js` | 1 | 0 | 0 | |
| `node --check web/embed.js` | 1 | 0 | 0 | |
| `node tests/test_chat_focus.js` | 1 | 0 | 0 | |
| `node tests/test_model_status.js` | 1 | 0 | 0 | |
| `node tests/test_knowledge_sources.js` | 1 | 0 | 0 | |
| `node tests/test_shipment_ui.js` | 1 | 0 | 0 | |
| `node tests/test_provider_selector.js` | 1 | 0 | 0 | |
| `node tests/test_case_assistant_ui.js` | 1 | 0 | 0 | |
| `node tests/test_public_session.js` | 1 | 0 | 0 | |
| `RETAILOPS_UI_TEST_MODE=persistent node tests/test_public_session.js` | 1 | 0 | 0 | |
| `node tests/test_w5_ui.js` | 1 | 0 | 0 | |
| `node tests/test_r1_w6_1b_1_1_ui_d8_v9.js` | 1 | 0 | 0 | |
| `node tests/test_r1_w6_1b_2_ui.js` | 1 | 0 | 0 | |
| `python scripts/build_agent_notebook.py --check` | 1 | 0 | 0 | `AGENT_NOTEBOOK_SOURCE_SYNC_OK` |
| `python scripts/build_eval_pack.py --check` | 1 | 0 | 0 | `EVAL_PACK_OK` |
| `python scripts/check_docs_contract.py` | 1 | 0 | 0 | 4 nhóm kiểm đều PASS |
| `python scripts/check_deployment_contract.py` | 1 | 0 | 0 | Chỉ kiểm hợp đồng cục bộ |
| `python scripts/check_live_e2e_contract.py` | 1 | 0 | 0 | Chỉ kiểm hợp đồng cục bộ |
| `python scripts/check_eval_dataset.py` | 74 | 0 | 0 | baseline 30 + hồi quy 32 + 12 |
| `python scripts/check_eval_dataset.py evals/suites` | 41 | 0 | 0 | |
| `python scripts/check_eval_dataset.py scratch/w6_3_3/datasets` | 48 | 0 | 0 | S02/S03 |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl --min-success-rate 1.0` | 32 | 0 | 0 | 35 lượt |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl --min-success-rate 1.0` | 12 | 0 | 0 | 14 lượt, có PDF dependency sẵn có |
| `python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0` | 4 | 0 | 0 | 4 lượt |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0` | 41 | 0 | 0 | 47 lượt; 100% |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir scratch/w6_3_3/datasets --min-success-rate 1.0` | 48 | 0 | 0 | 54 lượt; S02 18/18, S03 30/30 |
| `git diff --check` | 1 | 0 | 0 | Chạy lại sau cập nhật tài liệu |

Python cục bộ **3.10.7**. Dùng `PYTHONPATH=%TEMP%/w631-existing-deps` để nạp `pypdfium2` đã có sẵn từ W6.3.1, không cài hoặc thêm thư viện. Lượt runner W4 đầu thiếu đường dẫn này đã dừng với **1 error** `ModuleNotFoundError: No module named 'pypdfium2'`, trước khi có tổng kết scenario; không báo lượt đó là 12 fail hay 12 skip. Chạy lại nguyên lệnh với đường dẫn có sẵn đạt **12/12**, log `w4-with-pdf.txt`. Full unittest dùng dependency này ngay từ đầu và không có cấu hình DB test production; skip PostgreSQL theo điều kiện sẵn có trong test.

### Full unittest và kiểm cô lập

Full: `Ran 1169 tests in 514.074s`, `FAILED (failures=1, errors=1, skipped=86)`, exit 1: **1081 pass, 1 fail, 1 error, 86 skip**. Log `scratch/w6_3_3/evidence/full.txt`. Fail duy nhất ở `tests/test_marketplace_sim_stories_and_send.py:524`: phép quét `ROOT.rglob('*.py')` đọc cả `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` và coi là import `marketplace_sim` ngoài phạm vi. Đây là cùng lỗi môi trường đã ghi ở W6.3.2; không sửa/nới test hoặc dời worktree nguồn S02/S03.

Error ở subtest `path='/api/create'` của `test_remote.ProxyHTTPTests.test_admin_and_query_routes_unavailable`: `ConnectionAbortedError: [WinError 10053] An established connection was aborted by the software in your host machine`, qua HTTP loopback. Chạy lại nguyên bài với `PYTHONPATH=tests;%TEMP%/w631-existing-deps`: **1 pass, 0 fail/error/skip**, `0.519s`, log `proxy-retry.txt`. Giữ nguyên kết quả full và không sửa code/test của proxy; lượt kiểm riêng không thay thế số liệu full.

P99 local `/api/session` **37,642500 ms**, `/healthz` **26,595500 ms**, mỗi endpoint 1.000 mẫu, đạt ngưỡng 50 ms giữ nguyên. Artifact `headroom.json` ghi SHA test-first `410a440` do lượt full khởi chạy khi nguồn sửa còn trong working tree, ngay trước commit `a49b340`; nội dung hai nguồn/test/notebook trong lượt chạy là bản được commit ở `a49b340`.

Đã kiểm nguyên bài `test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests.test_item10_package_isolation_and_image_exclusion` trên snapshot sạch tạo bằng `git archive a49b340`: **1 pass, 0 fail, 0 skip**, `1.240s`. Không sửa bài kiểm hay di chuyển worktree chứa S02/S03.

## 5. PR và CI

Nguồn đã push lên [nhánh `phase-r1-w6-3-3`](https://github.com/tuteemovaixlong/CSKH_ban_le/tree/phase-r1-w6-3-3), commit `a49b340`. Công cụ GitHub `create_pull_request` mở biểu mẫu tạo PR, trả về rõ: “The pull request has NOT been created yet; only the form was rendered. Wait … for the user to review and click Submit.” **Chưa có kết quả Submit/URL PR**; tra danh sách PR theo đúng head branch cũng trả rỗng. Vì vậy **PR/CI BLOCKED**, CI **0 pass, 0 fail, 0 skip, chưa khởi chạy**, không nhận là xanh. Không tạo PR trùng hoặc chạy workflow thủ công để thay thế. Sau khi người dùng Submit, cần gắn PR với chat, chờ CI và cập nhật báo cáo/dòng log trên cùng nhánh; không merge.

## 6. Phạm vi và bàn giao

Giữ nguyên `RAGE_REPLY`, system prompt, `answer_check`, `data/knowledge/`, các suite và 44 kịch bản hồi quy; không sửa/commit S02/S03. Không rà sửa các từ khóa an toàn khác; không có finding ngoài phạm vi được kiểm chứng trong lượt này. Không migration, thư viện mới, variable/secret repo, production/EC2/SSM/DB production, Colab/LLM thật, dữ liệu khách hàng, workflow deploy hoặc live-e2e. Không merge, push main, force-push, rebase, reset hay stash.

**Hàng 1–3 DONE; kiểm tra cục bộ/báo cáo DONE; PR/CI BLOCKED do biểu mẫu chưa Submit.** Sau khi đủ CI và báo cáo, Claude kiểm chứng một lượt và owner quyết định merge theo mục 5 handoff.
