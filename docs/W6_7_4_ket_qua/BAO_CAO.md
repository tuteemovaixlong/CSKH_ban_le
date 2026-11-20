# Báo cáo thực thi W6.7.4

Nhánh: `phase-r1-w6-7-4-proxy-hash-ds-next`, rẽ từ `ff431e140b9fd1149359cad1162e366b93c5c816` (`origin/main`, PR #135 W6.7.3).
Commit mã + test + notebook đã kiểm (sau H1–H4): `39a8334a07fe00fa727c5279f5086f7bbb918be5` (sau H1–H3 là `785031d`).
SHA đầu nhánh cuối cùng (kèm commit cập nhật báo cáo này) được ghi trong tin bàn giao đi kèm khi đẩy nhánh.

## Tóm tắt theo thẻ việc (H1–H4)

| Thẻ | Người thực hiện / Model | Commit | Vòng sửa | Nội dung chính |
|---|---|---|---:|---|
| H1 (F62 — proxy) | Hydrogen (`gemini-4-hydrogen-high`) | `267af66` | 0 | Sửa `scripts/sft_hint_proxy.py`: thêm `"trace_request_sha256"` dùng `safe_payload(json.loads(body_gốc), secrets=())` từ `scripts.eval_telemetry`; thêm `tests/test_w674_proxy_trace_hash.py`. |
| H2 (F62 — `score_runs`) | Hydrogen (`gemini-4-hydrogen-high`) | `d1b5859` | 0 | Sửa `scripts/sft_select.py` (`score_runs`): chấp nhận cả `request_sha256` và `trace_request_sha256` cho các dòng `hinted: true`, nhật ký cũ giữ nguyên kết quả; thêm `tests/test_w674_score_trace_hash.py`. |
| H3 (F63 — `ds_next`) | Hydrogen (`gemini-4-hydrogen-high`) | `785031d` | 0 | Sửa `scripts/sft_select.py` (`export_judge_round`, `build_parser`, `main`): thêm lớp `"ds_next"` sau cờ CLI `--ds-next` (mặc định tắt); thêm `tests/test_w674_ds_next.py`. |
| H4 (ghim ca/phiếu + notebook + báo cáo) | Hydrogen (`gemini-4-hydrogen-high`) | `39a8334` | 0 | Thêm `tests/test_w674_cases_pinned.py`, dựng lại `notebooks/colab_agent.ipynb` bằng `scripts/build_agent_notebook.py`, tạo báo cáo này (`docs/W6_7_4_ket_qua/BAO_CAO.md`). |

**Thẻ nào Neon phải tự sửa:** Không có (0 thẻ — Neon chỉ làm điều phối, duyệt diff và chạy lại test xác minh).

## Bất biến sinh ca/phiếu SFT v1 (H4)

Kiểm tra trong `tests/test_w674_cases_pinned.py` qua `sft_cases.generate_cases(...)` với seed mặc định (tự động skip nếu chạy trong gói Colab không có `scripts/sft_cases.py` hoặc thiếu phụ thuộc):

| Tệp | SHA256 ghim |
|---|---|
| `cases_sft_v1.jsonl` | `56d47a64908b37f2ec7ded513fca80ba1f81ce64f9ac2cbc74e064a24c44a11e` |
| `briefs_sft_v1.jsonl` | `ed8b290b9d251297fd2d7fa66d49cf16bfd10ac41013e09118dc4cbfd3fff3a4` |

## Tệp đổi toàn đợt W6.7.4

- `scripts/sft_hint_proxy.py` (H1)
- `scripts/sft_select.py` (H2, H3)
- `tests/test_w674_proxy_trace_hash.py` (H1, mới)
- `tests/test_w674_score_trace_hash.py` (H2, mới)
- `tests/test_w674_ds_next.py` (H3, mới)
- `tests/test_w674_cases_pinned.py` (H4, mới)
- `notebooks/colab_agent.ipynb` (H4, dựng lại bằng `python scripts/build_agent_notebook.py` do thêm các tệp `tests/test_w674_*.py`)
- `docs/W6_7_4_ket_qua/BAO_CAO.md` (H4, mới)

Không sửa `evals/suites`, system prompt, `retailops/`, `scripts/sft_cases.py`, `scripts/sft_templates/`, `scripts/run_agent_scenarios.py`, `scripts/eval_telemetry.py` (chỉ import).

## Lệnh test và kết quả

### Kết quả được ghi nhận ở các thẻ H1–H3 (trước H4)

- H1: `tests/test_w674_proxy_trace_hash.py` + `tests/test_w673_proxy_hints.py` — 6/6 test qua.
- H2: `tests/test_w674_score_trace_hash.py` (ghim `LEGACY_LOG_SCORE_PIN` khớp 100% trên `ff431e1`) — 3/3 test mới + các test w673/w672/w670 liên quan qua.
- H3: `tests/test_w674_ds_next.py` (ghim `ROUND2_DEFAULT_OFF_PINS` khớp 100% trên `ff431e1`) — 2/2 test mới + 88 test `test_w67*.py` qua, 1 skipped.

### Kiểm tra tại thẻ H4 (sau khi dựng lại `notebooks/colab_agent.ipynb`)

| Lệnh kiểm | Kết quả |
|---|---|
| `python -m unittest -v tests/test_audit_remediation.py` (trước khi dựng lại notebook) | 9/10 qua, 1 FAIL (`test_colab_agent_notebook_sync`: notebook lệch gói nguồn) |
| `python scripts/build_agent_notebook.py` | Dựng lại `notebooks/colab_agent.ipynb` |
| `python -m unittest -v tests/test_w674_cases_pinned.py tests/test_audit_remediation.py` | 11/11 qua (`OK`) |
| `python -m unittest -v tests/test_w674_proxy_trace_hash.py tests/test_w674_score_trace_hash.py tests/test_w674_ds_next.py` | 6/6 qua (`OK`) |

### Kiểm tra toàn bộ bộ test (Mục 6)

- Lệnh: `python -m unittest discover -s tests` (chạy trên commit `39a8334a07fe00fa727c5279f5086f7bbb918be5`)
- Tổng kết: `Ran 1400 tests in 840.622s`, `FAILED (failures=2, errors=4, skipped=90)`:
  - **5 lỗi Windows có sẵn đã biết (khớp danh mục Mục 6):**
    - `test_r1_w4_agent_scenarios` ×2 (`W4FakeGatewayRunTests.setUpClass`, `W4RealHttpAdapterTwoLayerAuthTests.test_real_adapter_sends_both_item0_headers_measures_image_tokens_and_redacts_secrets` — `ModuleNotFoundError: No module named 'pypdfium2'`)
    - `test_r1_w4_media_pipeline` ×1 (`PhaseR1W4Item4PdfAndClamAVTests.test_item4_text_pdf_scanned_pdf_limits_and_order_action_pdf_upload` — `retailops.core.ApiError`)
    - `test_r1_w4_customer_ref_and_v8` ×2 (`PhaseR1W4BusinessV8PostgresMockTests.test_postgres_mock_v7_blocked_migrated_to_v8_with_attachment_backfill_and_idempotent`, `PhaseR1W4BusinessV8SqliteMigrationTests.test_v7_fixture_with_inline_attachments_is_blocked_migrates_exact_counts_and_rerun_is_noop`)
  - **1 lỗi socket Windows tức thời ngoài phạm vi W6.7.4:**
    - `test_remote.ProxyHTTPTests.test_admin_and_query_routes_unavailable (path='/api/create')` (`ConnectionAbortedError: [WinError 10053]`; W6.7.4 không chạm `inference_proxy.py` / `tests/test_remote.py`). Đã kiểm lại `python -m unittest -v tests/test_remote.py` 5 lần liên tiếp: 5/5 lần qua (`Ran 13 tests`, `OK`).
  - **Toàn bộ test W6.7.\* và `tests/test_audit_remediation.py`:** 0 lỗi.
