# Báo cáo thực hiện W6.4.3 — Thu hẹp phạm vi chặn `answer_check`, ghi vết luật số, tách Trợ lý ca, sửa bộ kiểm 2 & ngân sách tool mỗi bước (F48–F51)

## 1. Điều kiện bắt đầu và quyết định áp dụng

- **Nhánh:** `phase-r1-w6-4-3` (tạo bằng `git switch --no-track -c phase-r1-w6-4-3 origin/main`; `branch.phase-r1-w6-4-3.merge` không trỏ về `main`, đẩy lên `origin/phase-r1-w6-4-3`).
- **Commit gốc (`origin/main`):** `ece0b0b4004ad1fdfddfbcca8abaa86cc69fe408` (`git merge-base --is-ancestor ece0b0b origin/main` đạt mã thoát `0`; kiểm tra trạng thái kho sạch trước khi cắt nhánh).
- **Tài liệu nguồn (bộ handoff đọc-chỉ trên máy, không sao chép hay liên kết tương đối):** `README.md`, `01_HIEN_TRANG_VA_NGUYEN_NHAN.md`, `02_PHAM_VI_VA_TIEU_CHI.md`, `03_THIET_KE_CHI_TIET.md`, `04_TEST_VA_KIEM_TRA.md`, `06_SAU_KHI_MERGE.md`, `W0_OWNER_DECISION_DELTA_2026-10-29.md` (mục `## 32.`, `W6.4-D17`), `W6_BACKLOG_2026-11-06.md` (các dòng `F48`, `F49`, `F50`, `F51`), và `W6_4_3_answer_check_consult/README.md` (tham khảo bối cảnh).
- **Quyết định bổ sung trong lúc thực hiện (Quyết định Owner A1):** Khi chạy toàn bộ `unittest discover -s tests -q`, bài kiểm cũ `tests/test_r1_w3_2_agent_scenarios.py` (`RunnerNotesFailuresTests.test_the_server_side_checks_are_what_the_scenarios_rely_on`, dòng 292–296) thất bại do mock `type('R', (), {'changed': False, 'text': text, 'dropped_policy': 0, 'dropped_claims': 0})()` thiếu thuộc tính `audit` khi gặp `if checked.audit:` ở Hàng 2. Theo chỉ đạo owner A1: giữ nguyên `if checked.audit:` trong `retailops/business/application.py` đúng nguyên văn `03_THIET_KE_CHI_TIET.md` mục 2, và bổ sung `'details': (), 'audit': ()` vào object giả `R` trong `tests/test_r1_w3_2_agent_scenarios.py:292-293` (giữ nguyên toàn bộ các assertion khác).

## 2. Bảng tiến độ 6 hàng (`02_PHAM_VI_VA_TIEU_CHI.md`)

| Hàng | Việc | Trạng thái | Commit | Tệp đã đổi |
|---|---|---|---|---|
| Hàng 1 | `answer_check` chỉ chặn 4 luật (`BLOCKING_RULES`); 3 luật số/thời hạn chỉ ghi vết (`AUDIT_RULES`, `AnswerCheck.audit`); hai chỉnh của `policy_fee` (`_POLICY_FEE`, `zero_shipping_fee`/`own_free_shipping`); `_NOT_MONEY` bỏ qua ngày/giờ/SĐT che; cập nhật docstring (F49, W6.4-D17) | DONE | `cd06f15` | `retailops/workflow/answer_check.py`, `tests/test_w643_answer_check_scope.py`, `tests/test_r1_w3_2_answer_check.py`, `tests/test_r1_w6_3_1_hotfix.py`, `tests/test_r1_w6_3_2_hotfix.py`, `tests/test_w642_answer_check.py` |
| Hàng 2 | Ghi `trace['answer_check_audit']` khi `checked.audit` có phần tử (kể cả khi `not checked.changed`) ở cả hai chế độ `agent` và `legacy`; ghi `turn_rec['answer_check_audit']` trong runner | DONE | `3ab62a2` | `retailops/business/application.py`, `scripts/run_agent_scenarios.py`, `tests/test_w643_answer_check_scope.py` |
| Hàng 3 | Trợ lý ca (`case_assist`) giữ nguyên văn ghi chú nội bộ cho nhân viên, chỉ kiểm `draft_reply`, thay đúng đoạn nháp trong `clean_answer` (`count=1`) và ghi `answer_check`, `answer_check_detail`, `answer_check_audit` từ `draft_checked` (F51) | DONE | `2beaea0` | `retailops/business/application.py`, `tests/test_w643_answer_check_scope.py` |
| Hàng 4 | Bộ kiểm thứ hai (`enforce_final_answer_grounding` mục 4) xét `tool_evidence(messages)` trước khi thay, tách riêng khẳng định hủy và hoàn tiền, ưu tiên `external_order_id` fallback `id`, bỏ `delivery=`/`address=` (F50) | DONE | `9987a1a` | `retailops/guardrails/topic_filter.py`, `tests/test_phase5_e_ai_trust_and_governance.py`, `tests/test_w643_answer_check_scope.py` |
| Hàng 5 | Nâng `MAX_TOOLS_PER_STEP = MAX_TOOL_CALLS` (10) trong `agent_protocol.py` dòng 33; giữ nguyên `SYSTEM` (5.993 ký tự) và trần 10 tool/lượt `agent_budget_exceeded` (F48, W6.4-D17) | DONE | `e02d470` | `agent_protocol.py`, `tests/test_w643_answer_check_scope.py` |
| Hàng 6 | Áp dụng A1 ở `tests/test_r1_w3_2_agent_scenarios.py`, sinh lại `notebooks/colab_agent.ipynb`, chạy đủ bộ kiểm và số đo, lập báo cáo & nhật ký W1, đẩy nhánh và mở PR | DONE | `8dd015a` + commit báo cáo/log cuối | `tests/test_r1_w3_2_agent_scenarios.py`, `notebooks/colab_agent.ipynb`, `docs/phase_role_aware_ops/W6_4_3_EXECUTION_REPORT_2026-11-15.md`, `docs/phase_role_aware_ops/W1_EXECUTION_LOG_2026-10-31.md` |

## 3. Bằng chứng FAIL trước khi sửa (Hàng 1–5)

Mỗi hàng 1–5 đều viết test mới trong `tests/test_w643_answer_check_scope.py` theo `04_TEST_VA_KIEM_TRA.md` mục 2 và chạy trên mã trước khi sửa (với `PYTHONUTF8=1`, `PYTHONPATH=tests`):

- **Hàng 1 (trên `ece0b0b`, trước khi sửa `answer_check.py`):**
  - Lệnh: `python -m unittest tests.test_w643_answer_check_scope.Row1AnswerCheckScopeTests -v`
  - Kết quả: `Ran 1 test in 0.001s — FAILED (errors=1)`
  - Dòng lỗi: `ImportError: cannot import name 'AUDIT_RULES' from 'retailops.workflow.answer_check'`.
- **Hàng 2 (trên `cd06f15`, trước khi sửa `application.py` và `run_agent_scenarios.py`):**
  - Lệnh: `python -m unittest tests.test_w643_answer_check_scope.Row2ApplicationTraceTests tests.test_w643_answer_check_scope.Row2RunnerAuditTests -v`
  - Kết quả: `Ran 4 tests in 3.044s — FAILED (errors=3)`
  - Dòng lỗi:
    - `Row2ApplicationTraceTests.test_audit_recorded_even_when_unchanged_in_both_modes (mode='agent')`: `KeyError: 'answer_check_audit'` (dòng 166 lúc chạy)
    - `Row2ApplicationTraceTests.test_audit_recorded_even_when_unchanged_in_both_modes (mode='legacy')`: `KeyError: 'answer_check_audit'` (dòng 166 lúc chạy)
    - `Row2RunnerAuditTests.test_runner_records_answer_check_audit_when_present_and_omits_when_clean`: `KeyError: 'answer_check_audit'` (dòng 217 lúc chạy)
- **Hàng 3 (trên `3ab62a2`, trước khi sửa nhánh `case_assist` trong `application.py`):**
  - Lệnh: `python -m unittest tests.test_w643_answer_check_scope.Row3CaseAssistTests -v`
  - Kết quả: `Ran 3 tests in 0.457s — FAILED (failures=1, errors=1)`
  - Dòng lỗi:
    - `test_draft_reply_records_audit_without_dropping_or_altering_clean_answer`: `KeyError: 'answer_check_audit'` (vì `case_assist` cũ chỉ ghi trace khi `changed`)
    - `test_internal_note_kept_verbatim_while_draft_reply_is_checked`: `AssertionError: 'Shop đổi tận nhà miễn phí cho khách.' not found in 'Phần phí, giao nhận và thời hạn em chưa có trích dẫn từ kho chính sách của shop nên chưa thể xác nhận ạ.'` (toàn văn ghi chú nội bộ bị `check_final_answer` cắt bỏ).
- **Hàng 4 (trên `2beaea0`, trước khi sửa `topic_filter.py` mục 4):**
  - Lệnh: `python -m unittest tests.test_w643_answer_check_scope.Row4SecondGuardTests -v`
  - Kết quả: `Ran 5 tests in 0.004s — FAILED (failures=5)`
  - Dòng lỗi:
    - `test_cancelled_order_keeps_cancel_completion_reply`: `AssertionError: 'Dạ qua kênh chat, hệ thống chưa thực hiện hủy đơn hàng ord_x; đơn ord_x hiện đang ở trạng thái cancelled (chưa bị hủy) và chưa ghi nhận thông tin giao hàng/địa chỉ (delivery=None, address=None)...' != 'Đơn SIM-O-00091 đã được hủy thành công ạ.'`
    - `test_refunded_order_keeps_refund_completion_reply`: `AssertionError` đè câu đã hoàn tiền đúng bằng câu `"chưa thực hiện hủy đơn hàng ord_x ... (delivery=None, address=None)..."`
    - `test_pending_order_replaces_false_cancel_with_external_id_and_no_raw_fields`: `AssertionError` xuất `ord_x` và `delivery=None, address=None` thay cho `SIM-O-00091`
    - `test_unrefunded_order_replaces_false_refund_claim`: `AssertionError` xuất câu hủy (`delivery=None, address=None`) thay cho câu hoàn tiền
    - `test_no_order_in_tools_uses_separate_cancel_and_refund_fallbacks_and_cancel_priority`: `AssertionError` dùng fallback hủy chung cho khẳng định hoàn tiền.
- **Hàng 5 (trên `9987a1a`, trước khi sửa `agent_protocol.py` dòng 33):**
  - Lệnh: `python -m unittest tests.test_w643_answer_check_scope.Row5ToolsPerStepTests -v`
  - Kết quả: `Ran 3 tests in 1.696s — FAILED (failures=2, errors=1)`
  - Dòng lỗi:
    - `test_max_tools_per_step_constant_and_assistant_message_bounds`: `AssertionError: 4 != 10`
    - `test_seven_tools_in_single_step_succeed_and_pass_validate_messages`: `retailops.core.ApiError: Không nhận được câu trả lời hợp lệ từ model. Chat chưa thực hiện thay đổi đơn.` (`agent_response_failed` vì bước gọi 7 tool bị `ProtocolError` ở ngưỡng `4`)
    - `test_six_plus_five_tools_still_hits_turn_budget_exceeded`: `AssertionError: 'agent_response_failed' != 'agent_budget_exceeded'` (bước 1 có 6 tool đã bị chặn trước khi chạm trần lượt 10 tool).

## 4. Danh sách đầy đủ các test cũ đã sửa (`04_TEST_VA_KIEM_TRA.md` mục 3 và quyết định owner A1)

Không bỏ bất kỳ câu thử nào; mọi câu dính luật chặn (`policy_fee`, `fee_amount`/`policy_fee` như `"Phí ship do shop chịu hoàn toàn."`, `logistics`, `done_claim`, `handoff_claim`) vẫn giữ nguyên assertion bị xóa + chèn ghi chú. Tệp `tests/test_r1_w6_3_4_answer_check.py` không có trong bảng mục 3 và **giữ nguyên không sửa** (`4/4 PASS`).

| Tệp | `Lớp.hàm` | Câu thử / đoạn mã đã sửa | Lý do và cách sửa |
|---|---|---|---|
| `tests/test_r1_w3_2_answer_check.py` | `FinalAnswerCheckTests.test_uncited_policy_promises_are_removed` | `"Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng."`, `"Thời hạn đổi trả là 30 ngày."` (4 câu còn lại giữ nguyên khẳng định bị xóa) | Hai câu chỉ dính `deadline_number` (W6.4.3): chuyển từ kiểm xóa sang kiểm giữ nguyên văn, `changed=False`, `dropped=(0, 0)`, `audit` có `deadline_number`. |
| `tests/test_r1_w3_2_answer_check.py` | `FinalAnswerCheckTests.test_a_structured_warranty_fact_from_a_tool_is_not_a_promise` | `"Sản phẩm này được bảo hành 120 ngày ạ."` (sai số so với tool `90`) và `"Sản phẩm này được bảo hành 90 ngày ạ."` (không tool) | Dính `deadline_number`: chuyển sang giữ nguyên văn, `changed=False`, `audit` ghi `deadline_number`. |
| `tests/test_r1_w6_3_1_hotfix.py` | `DeadlineTests.test_server_deadline_facts_survive_only_with_tool_evidence` | Vế không bằng chứng của 3 câu: `"Đơn SIM-O-1 còn trong hạn trả hàng ạ."` (`deadline_no_fact`), `"Đơn SIM-O-1 đang trên đường vận chuyển qua GHN và vẫn trong thời hạn giao dự kiến ạ."` (`deadline_no_fact`), `"Đơn của anh/chị còn hạn đổi size 15 ngày ạ."` (`deadline_number`) | Vế có bằng chứng giữ nguyên; vế không bằng chứng chuyển sang `changed=False`, giữ nguyên văn và ghi `audit` đúng luật (`deadline_no_fact` / `deadline_number`). |
| `tests/test_r1_w6_3_1_hotfix.py` | `DeadlineTests.test_fee_logistics_and_unknown_numbers_still_need_citations` | `"Shop cho đổi trong 30 ngày ạ."`, `"Shop cho đổi trong 7 đến 30 ngày ạ."`, `"Thời hạn trả là 1 ngày ạ."` (bằng chứng `bool` `True`) (hai câu `"Shop miễn phí ship đổi size lần đầu ạ."` và `"Shop đổi tận nhà trong 15 ngày ạ."` giữ khẳng định bị xóa) | Ba câu số ngày không khớp/bằng chứng `bool` dính `deadline_number`: chuyển sang `changed=False`, giữ nguyên văn và `audit` ghi `deadline_number`. |
| `tests/test_r1_w6_3_2_hotfix.py` | `ShippingFeeTests.test_order_shipping_facts_need_matching_tool_money` | Vế không bằng chứng của toàn bộ `FACTS` và câu `'Đơn gồm 2 đôi giày size 43, tổng 1.860.000 VNĐ đã gồm 40.000 VNĐ phí ship ạ.'` | Vế không bằng chứng dính `fee_amount`: chuyển sang `changed=False`, giữ nguyên văn và `audit` ghi `fee_amount`. |
| `tests/test_r1_w6_3_2_hotfix.py` | `ShippingFeeTests.test_policy_logistics_missing_or_mismatched_money_still_drop` | `'Phí ship đơn này là 20.000đ ạ.'`, `'Phí ship đơn SIM-O-30000 size 43 ×2 ạ.'`, `'Phí ship 30k tổng 400000 ạ.'` (10 câu còn lại, gồm `'Phí ship do shop chịu hoàn toàn.'` nhờ nhánh `_POLICY_FEE`, giữ khẳng định bị xóa) | Ba câu số tiền phí ship sai/không nêu tiền đổi/trả dính `fee_amount`: chuyển sang `changed=False`, giữ nguyên văn và `audit` ghi `fee_amount`. |
| `tests/test_r1_w6_3_2_hotfix.py` | `ShippingFeeTests.test_money_evidence_walks_all_tool_results_but_rejects_bool_and_non_int` | Hai lượt giả lập tool nằm sai ở role `'user'` và `'assistant'` đối với `self.FACTS[0]` | Không có tool message nên câu phí ship dính `fee_amount`: giữ nguyên văn, `changed=False`, `audit` ghi `fee_amount`. |
| `tests/test_r1_w6_3_2_hotfix.py` | `DeadlineProductNumbersTests.test_only_numbers_before_time_units_are_deadlines` | Vế không bằng chứng của 3 câu (`...bảo hành 365 ngày...` `deadline_number`, `...bảo hành 365 ngày ạ.` `deadline_number`, `...còn trong thời hạn trả hàng ạ.` `deadline_no_fact`) | Vế có bằng chứng giữ nguyên; vế không bằng chứng chuyển sang `changed=False`, giữ nguyên văn và `audit` ghi đúng luật. |
| `tests/test_r1_w6_3_2_hotfix.py` | `DeadlineProductNumbersTests.test_unknown_time_numbers_and_all_time_units` | `'Bộ Nồi Inox 3 Đáy bảo hành 30 ngày ạ.'`, `'Shop đổi trong 30 ngày ạ.'` (hai nơi), và `f'Shop đổi size 43 trong 7 {unit} ạ.'` khi `return_window_days: 15` | Toàn bộ chỉ dính `deadline_number`: chuyển sang `changed=False`, giữ nguyên văn và `audit` ghi `deadline_number`. |
| `tests/test_w642_answer_check.py` | `Row1MoneyEvidenceTests` (`test_item_prices_and_subtotal_kept_with_order_91_and_dropped_without_evidence`, `test_policy_fee_and_wrong_shipping_amount_still_dropped_with_order_91`, `test_multi_order_derived_money_and_totals_kept`) | Vế không bằng chứng của các câu giá/tổng đơn và câu `'Phí ship đơn này là 35.000đ ạ.'` | Dính `fee_amount`: giữ nguyên văn, `changed=False`, `dropped_policy=0`, `audit` ghi `fee_amount`; `'Phí đổi hàng là 450.000đ ạ.'` và `'Shop miễn phí ship đổi size lần đầu ạ.'` giữ khẳng định bị xóa (`policy_fee`). |
| `tests/test_w642_answer_check.py` | `Row2TimeEvidenceTests` (`test_derived_time_sentences_kept_with_order_91_and_dropped_without_evidence`, `test_unknown_or_policy_time_numbers_still_dropped_with_order_91`) | Vế không bằng chứng 4 câu thời gian suy ra và `' - Hạn đổi size còn khoảng 12 ngày.'`, `'Shop cho đổi trong 30 ngày ạ.'` | Dính `deadline_number`: giữ nguyên văn, `changed=False`, `dropped_policy=0`, `audit` ghi `deadline_number`. |
| `tests/test_w642_answer_check.py` | `Row3HeadingAndNumberedLineTests` (`test_heading_table_examples_without_evidence`, `test_smoke_multi_order_response_preserves_order_and_second_heading`, `test_orphan_numbered_item_removed_when_sentence_dropped`, `test_heading_separators_empty_label_and_stranded_citation`) | Đổi cụm kích hoạt trong dòng mẫu từ luật số sang luật chặn (`trễ hạn 72 giờ, sắp hết hạn trả hàng` / `quá hạn 54 giờ` / `trễ hạn trả hàng 72 giờ` → `đổi tận nhà miễn phí 2 chiều`; `**Phí ship:** 30.000đ` → `**Phí ship:** do shop chịu hoàn toàn.`; `2) Thời hạn đổi trả là 30 ngày.` → `2) Phí ship do shop chịu hoàn toàn.`) | Để kiểm đúng hành vi giữ nhãn tiêu đề và xóa số thứ tự treo khi dòng bị luật chặn cắt (theo chỉ dẫn `04_TEST_VA_KIEM_TRA.md` mục 3), giữ nguyên kỳ vọng nhãn tiêu đề và số thứ tự. |
| `tests/test_w642_answer_check.py` | `Row4DetailsUnitTests` (`test_five_line_details_order_keys_and_no_leaked_text`, `test_policy_fee_vs_logistics_hedge_and_deadline_no_fact`, `test_heading_label_kept_flag_and_unchanged_details_empty`) | Dòng 2 (`fee_amount`), dòng 3 (`deadline_number`), câu `'Đơn còn trong thời hạn đổi trả ạ.'` (`deadline_no_fact`), và tiêu đề `'**SIM-O-00091 — trễ hạn 72 giờ, sắp hết hạn trả hàng**'` (`deadline_number`) | Chuyển các mục này từ `res.details` sang `res.audit`, xác nhận câu gốc vẫn nằm trong `res.text`, kiểm cấu trúc `{'line', 'rule'}` không lộ chữ/số. |
| `tests/test_phase5_e_ai_trust_and_governance.py` | `Phase5EAITrustAndGovernanceTests` (dòng 759, kịch bản `O-101`) | Bỏ `self.assertIn("delivery=None", res_o101["message"])`, thay bằng `self.assertNotIn("delivery=", res_o101["message"])` và `self.assertNotIn("address=", res_o101["message"])` | Theo Hàng 4 (`F50`, `03_THIET_KE_CHI_TIET.md` mục 4), câu thay thế không còn rò `delivery=` và `address=`; giữ nguyên `pending`, `chưa bị hủy`, `not in "đã được hủy thành công"`. |
| `tests/test_r1_w3_2_agent_scenarios.py` | `RunnerNotesFailuresTests.test_the_server_side_checks_are_what_the_scenarios_rely_on` (dòng 292–293) | Bổ sung `'details': (), 'audit': ()` vào object giả `R` trong `patch.object(application, 'check_final_answer', ...)` | Theo quyết định owner **A1**: **object giả phải khớp các trường của `AnswerCheck` sau W6.4.3** (`application.py` giữ nguyên `if checked.audit:`). Không đổi assertion nào của test. |

## 5. Kết quả các lệnh kiểm tra (`04_TEST_VA_KIEM_TRA.md` mục 4)

Chạy tuần tự sau lần sửa code/test cuối cùng (`tests/test_r1_w3_2_agent_scenarios.py` và `notebooks/colab_agent.ipynb`) với `%TEMP%\venv_pdf\Scripts\python.exe` (Python 3.10.7 có sẵn `pypdfium2`) và `PYTHONUTF8=1`:

| Lệnh | Pass | Fail | Skip | Thời gian / Kết quả ghi nhận |
|---|---|---|---|---|
| `python -m unittest discover -s tests -q` | 1212 | 1 | 86 | `Ran 1299 tests in 444.805s — FAILED (failures=1, skipped=86)`. **1 fail duy nhất đã biết trên máy owner:** `test_item10_package_isolation_and_image_exclusion` (`test_marketplace_sim_stories_and_send.MarketplaceSimIsolationTests`) do `rglob('*.py')` quét vào worktree đọc-chỉ `.claude/worktrees/cai-nay-la-sao-bddcef/tests/test_marketplace_sim_contract.py` (không sửa). **86 skip** là các bài tích hợp PostgreSQL/pgvector/`waitress`/`bash` khi không đặt `RETAILOPS_TEST_DATABASE_URL` trên Windows. |
| `python scripts/build_agent_notebook.py` | - | - | - | Exit 0 (sinh lại `notebooks/colab_agent.ipynb`) |
| `python scripts/build_agent_notebook.py --check` | - | - | - | Exit 0 (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`) |
| `python scripts/build_eval_pack.py --check` | - | - | - | Exit 0 (`EVAL_PACK_OK`) |
| `python scripts/check_docs_contract.py` | - | - | - | Exit 0 (`1..4 PASS`, `SUCCESS: All documentation contracts are valid and truthful.`) |
| `python scripts/check_deployment_contract.py` | - | - | - | Exit 0 (`DEPLOYMENT_CONTRACT_OK`) |
| `python scripts/check_live_e2e_contract.py` | - | - | - | Exit 0 (`LIVE_E2E_CONTRACT_OK`) |
| `python scripts/check_eval_dataset.py` | - | - | - | Exit 0 (`baseline_v1.jsonl` 30, `agent_scenarios_w3_2.jsonl` 32, `agent_scenarios_w4.jsonl` 12) |
| `python scripts/check_eval_dataset.py evals/suites --final` | - | - | - | Exit 0 (`EVAL_DATASET_OK suites cases=250`) |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w3_2.jsonl --min-success-rate 1.0` | 32 | 0 | 0 | Exit 0 (`32/32 = 1.0`, 35 lượt, `valid tool-call rate: 33/33 = 1.0`, `p50 196.61 ms`) |
| `python scripts/run_agent_scenarios.py --fake --dataset evals/agent_scenarios_w4.jsonl --min-success-rate 1.0` | 12 | 0 | 0 | Exit 0 (`12/12 = 1.0`, 14 lượt, `valid tool-call rate: 17/17 = 1.0`, `p50 63.39 ms`) |
| `python scripts/run_agent_scenarios.py --fake --dataset khoa_luan/eval_pack/06_vi_du.jsonl --min-success-rate 1.0` | 4 | 0 | 0 | Exit 0 (`4/4 = 1.0`, 4 lượt, `valid tool-call rate: 6/6 = 1.0`, `p50 163.44 ms`) |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --min-success-rate 1.0` | 250 | 0 | 0 | Exit 0 (`250/250 = 1.0`, 336 lượt, `valid tool-call rate: 469/469 = 1.0`, `p50 199.32 ms`) |
| `python scripts/run_agent_scenarios.py --fake --dataset-dir evals/suites --context-tokens 32768 --min-success-rate 1.0` | 250 | 0 | 0 | Exit 0 (`250/250 = 1.0`, 336 lượt, `valid tool-call rate: 469/469 = 1.0`, `p50 198.5 ms`) |
| Đối chiếu SHA-256 12 tệp `evals/suites/*.jsonl` (`hashlib.sha256`, tương đương `sha256sum`) | 12 | 0 | 0 | Khớp 12/12 với bảng trong `evals/suites/README.md` |
| `git diff --check` | - | - | - | Exit 0 (và kiểm tra thủ công LF/không `\x08`, `len(agent_protocol.SYSTEM) == 5993`) |
| Toàn bộ lệnh test JS trong `.github/workflows/ci.yml` | - | - | - | **CI kiểm** (máy Windows chỉ có `node.cmd` bản giả, không có Node thật) |

### Chạy riêng từng module kiểm thử liên quan (`PYTHONPATH=tests`)

| Module | Pass | Fail | Skip | Thời gian | Ghi chú |
|---|---|---|---|---|---|
| `tests.test_w643_answer_check_scope` | 21 | 0 | 0 | 5.077s | OK (test mới Hàng 1–5) |
| `tests.test_r1_w3_2_answer_check` | 23 | 0 | 0 | 7.482s | OK (sửa đúng 2 hàm theo bảng mục 3) |
| `tests.test_r1_w6_3_1_hotfix` | 11 | 0 | 0 | 3.726s | OK (sửa đúng 2 hàm theo bảng mục 3) |
| `tests.test_r1_w6_3_2_hotfix` | 13 | 0 | 0 | 0.011s | OK (sửa đúng 5 hàm theo bảng mục 3) |
| `tests.test_r1_w6_3_4_answer_check` | 4 | 0 | 0 | 0.002s | OK (**không sửa dòng nào**) |
| `tests.test_w642_answer_check` | 25 | 0 | 0 | 2.547s | OK (sửa đúng 4 lớp theo bảng mục 3) |
| `tests.test_phase5_e_ai_trust_and_governance` | 14 | 0 | 0 | 9.502s | OK (sửa đúng dòng 759 theo bảng mục 3) |
| `tests.test_r1_w3_2_agent_loop` | 40 | 0 | 0 | 15.944s | OK (không sửa dòng nào) |
| `tests.test_r1_w3_2_agent_scenarios` | 34 | 0 | 0 | 27.521s | OK (áp dụng quyết định A1 ở dòng 292–293) |

### Bảng SHA-256 của 12 tệp `evals/suites/*.jsonl`

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

## 6. Ba số đo bắt buộc (`04_TEST_VA_KIEM_TRA.md` mục 5)

### 6.1 Bảng 12 dòng (`origin/main` `ece0b0b` vs `phase-r1-w6-4-3`)

Chạy trực tiếp `check_final_answer` trên bộ `LIST_2` và `GET_9` của `04_TEST_VA_KIEM_TRA.md` mục 2 trước khi sửa (`ece0b0b`) và sau W6.4.3 (`phase-r1-w6-4-3`):

| # | Dòng kiểm | Bằng chứng | `origin/main` (`ece0b0b`) | Nhánh `phase-r1-w6-4-3` |
|---|---|---|---|---|
| 1 | `\| SIM-O-38588564-02 \| 09/11/2026 \| Áo khoác Everyday \| 839.000₫ (gồm phí ship 40.000₫) \| Đang vận chuyển \|` | `LIST_2` | xóa (`fee_amount`) | giữ (không ghi vết) |
| 2 | `- Đặt ngày 2026-11-09, phí ship 40.000₫.` | `LIST_2` | xóa (`fee_amount`) | giữ (không ghi vết) |
| 3 | `\| SIM-O-38588564-02 \| 839.000₫ \| Đang vận chuyển (trễ hạn 54 giờ) \|` | `LIST_2` | xóa (`deadline_number`) | giữ (ghi vết `deadline_number`) |
| 4 | `Shipper 090***1234 sẽ giao hàng, phí ship 0đ ạ.` | `GET_9` | xóa (`fee_amount`) | giữ (không ghi vết) |
| 5 | `Sản phẩm còn bảo hành 3 tháng ạ.` | `GET_9` | xóa (`deadline_number`) | giữ (ghi vết `deadline_number`) |
| 6 | `Anh/chị được đổi hàng trong 7 ngày kể từ khi nhận hàng.` | `GET_9` | giữ (không) | giữ (không ghi vết) |
| 7 | `Thời hạn đổi trả là 30 ngày.` | `GET_9` | xóa (`deadline_number`) | giữ (ghi vết `deadline_number`) |
| 8 | `Phí ship do shop chịu hoàn toàn.` | `GET_9` | xóa (`fee_amount`) | xóa (`policy_fee`) |
| 9 | `Đơn SIM-O-9 được miễn phí ship ạ.` | `GET_9` | xóa (`policy_fee`) | giữ (không ghi vết) |
| 10 | `Đổi size lần đầu được miễn phí ship ạ.` | `GET_9` | xóa (`policy_fee`) | xóa (`policy_fee`) |
| 11 | `Shop đổi size tận nhà cho anh/chị ạ.` | `GET_9` | xóa (`logistics`) | xóa (`logistics`) |
| 12 | `Em đã hủy đơn SIM-O-9 cho anh/chị theo chính sách [KB:0123456789abcdef01234567].` | `GET_9` | xóa (`done_claim`) | xóa (`done_claim`) |

### 6.2 Runner giả 250 ca (`evals/suites`, 336 lượt)

So sánh bản chạy trước W6.4.3 (`ece0b0b`) và sau W6.4.3 (`phase-r1-w6-4-3`) với `--fake --dataset-dir evals/suites`:

| Chỉ số | Trên `ece0b0b` | Sau W6.4.3 (`phase-r1-w6-4-3`) | Chi tiết theo `rule` |
|---|---|---|---|
| Số kịch bản đạt | `250/250 = 1.0` (336 lượt, 469/469 valid tool calls) | `250/250 = 1.0` (336 lượt, 469/469 valid tool calls) | Giữ nguyên độ đạt 100% ở cả 16k và 32k |
| Số lượt có `answer_check` (bị xóa câu) | `2` (`2/336` lượt) | `1` (`1/336` lượt) | - `ece0b0b`: `done_claim: 1` (`s09_006_gia_he_thong_duyet_hoan_tien` lượt 1); `fee_amount: 1` (`s11_016_hai_luot_hoi_ton_kho_roi_soan_nhap_giao_sai` lượt 2).<br>- Sau W6.4.3: `done_claim: 1` (`s09_006_gia_he_thong_duyet_hoan_tien` lượt 1 giữ nguyên chặn đúng); `s11_016` lượt 2 không còn bị cắt nhầm vì cụm `"phí ship"` ở dòng 1 nằm trong ghi chú nội bộ ngoài thẻ `<draft_reply>` (được Hàng 3 / `F51` gỡ khỏi `check_final_answer`, còn `<draft_reply>` đã có đủ trích dẫn `[KB:...]`). |
| Số lượt có `answer_check_audit` (ghi vết) | Chưa có khóa (`0`) | `0` (`0/336` lượt) | Đếm theo `rule`: `{}` (chỉ phát sinh ở các ca nói số tiền/thời hạn thiếu bằng chứng như trong unit test Hàng 1–3; bộ 250 ca mẫu `--fake` không kích hoạt câu nào thuộc `AUDIT_RULES`). |

### 6.3 Tổng hợp danh sách test cũ đã sửa

Xem đầy đủ bảng chi tiết 6 tệp (5 tệp trong bảng `04_TEST_VA_KIEM_TRA.md` mục 3 + `tests/test_r1_w3_2_agent_scenarios.py:292-293` theo quyết định owner A1) kèm từng câu thử và lý do ở **Mục 4** phía trên.

## 7. Những chỗ khác có thể còn xóa hoặc thay nhầm câu đúng (chỉ ghi, không sửa)

1. **`retailops/guardrails/topic_filter.py` — `enforce_final_answer_grounding` (mục 1, 3 và 4):**
   - **Mục 1 (dòng 537–575):** Khi có ít nhất một sản phẩm trong `inspected_products` có trường `None` (`price`, `stock` khi không lấy biến thể, hoặc `warranty_days`), biểu thức kiểm giá/tồn kho/bảo hành quét trên **toàn bộ `lower_reply`** (ví dụ bất kỳ số tiền nào `...\s*(?:đ|vnđ|...)` hay cụm `"còn hàng"`), không gắn với mã/tên sản phẩm tương ứng. Nếu một câu trả lời hợp lệ nhắc song song sản phẩm A đủ thông tin (hoặc tổng tiền đơn hàng) cùng sản phẩm B thiếu trường, câu trả lời vẫn có thể bị thay toàn bộ bằng `"Chưa có thông tin: sản phẩm ..."`.
   - **Mục 3 (dòng 605–616):** Nếu cùng một lượt gọi cả một `get_order` `order_not_found` và một `get_order` hợp lệ khác nhưng câu trả lời không chứa đúng 5 cụm đánh dấu (`"không tìm thấy"`, `"chưa tìm thấy"`, `"không thuộc tài khoản"`, `"không có đơn"`, `"order_not_found"`), toàn bộ `out_text` bị thay bằng thông báo không tìm thấy đơn.
   - **Mục 4 (dòng 618–662):** `inspected_order` chỉ đọc `t_res.get("order")` của `get_order` đơn lẻ chứ chưa đọc danh sách `orders` từ `list_orders` (nên lượt chỉ gọi `list_orders` mà bị thay câu sẽ rơi về nhánh không mã đơn dù `tool_evidence` vẫn đọc được cờ `cancelled`/`refunded`); ngoài ra `evidence.cancelled` và `evidence.refunded` tính chung toàn lượt chứ chưa theo từng `order_id` nếu cùng lượt tra nhiều đơn khác trạng thái; và chuỗi thay thế vẫn giữ tên trạng thái tiếng Anh (`pending`, `delivered`) theo đúng danh sách ngoài phạm vi W6.4.3 ở `02_PHAM_VI_VA_TIEU_CHI.md`.
2. **`retailops/workflow/answer_check.py`:**
   - `Evidence.zero_shipping_fee` tính chung cho cả lượt: nếu cùng lượt tra cứu 1 đơn `shipping_fee == 0` và 1 đơn `shipping_fee > 0`, câu `"miễn phí ship"` không nêu ngữ cảnh đổi/trả/lần đầu cho đơn có phí sẽ được `own_free_shipping` cho qua.
   - Ở hội thoại nhiều lượt của khách, lịch sử gửi vòng kiểm hiện không giữ lượt tool của các lượt trước (`W3.2-D8`, thuộc phạm vi W6.5), nên nếu lượt sau model nhắc lại miễn phí ship của đơn hay trạng thái đã hủy/hoàn tiền mà không gọi lại tool thì `tool_evidence(messages)` chưa có bằng chứng của lượt trước.

## 8. Trạng thái nhánh, PR và CI

- **Nhánh:** `phase-r1-w6-4-3`
- **URL PR:** https://github.com/tuteemovaixlong/CSKH_ban_le/pull/116 (chỉ mở PR vào `main`, **không merge**)
- **Kết quả CI kiểm tra tại thời điểm commit `8dd015a` (`gh pr checks 116`):**
  - `colab-python313`: **pass** (17s)
  - `portable (windows-latest)`: **pass** (25s)
  - `portable (ubuntu-24.04)`: **pass** (14s)
  - `postgres`: **pass** (2m8s — toàn bộ bộ kiểm PostgreSQL thật)
  - `clamav-smoke`: **pass** (44s)
  - `offline`: **pending** tại thời điểm ghi báo cáo (sẽ được đẩy kèm commit tài liệu cuối để chạy đủ lại cả test JS trên Linux/Docker CI).
