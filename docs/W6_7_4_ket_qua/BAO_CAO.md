# Báo cáo thực thi W6.7.4

Nhánh: `phase-r1-w6-7-4-proxy-hash-ds-next`, rẽ từ `ff431e140b9fd1149359cad1162e366b93c5c816` (`origin/main`, PR #135 W6.7.3).
Commit mã logic đã kiểm (sau H1–H3): `785031d46ecbba885b15d6f97204a837b0350aff`.
SHA đầu nhánh cuối cùng sau khi điều phối viên gộp H4 và chạy toàn bộ `unittest discover` ở Mục 6 sẽ được cập nhật/ghi trong tin bàn giao đi kèm.

## Tóm tắt theo thẻ việc (H1–H4)

| Thẻ | Người thực hiện / Model | Commit | Vòng sửa | Nội dung chính |
|---|---|---|---:|---|
| H1 (F62 — proxy) | Hydrogen (`gemini-4-hydrogen-high`) | `267af66` | 0 | Sửa `scripts/sft_hint_proxy.py`: thêm `"trace_request_sha256"` dùng `safe_payload(json.loads(body_gốc), secrets=())` từ `scripts.eval_telemetry`; thêm `tests/test_w674_proxy_trace_hash.py`. |
| H2 (F62 — `score_runs`) | Hydrogen (`gemini-4-hydrogen-high`) | `d1b5859` | 0 | Sửa `scripts/sft_select.py` (`score_runs`): chấp nhận cả `request_sha256` và `trace_request_sha256` cho các dòng `hinted: true`, nhật ký cũ giữ nguyên kết quả; thêm `tests/test_w674_score_trace_hash.py`. |
| H3 (F63 — `ds_next`) | Hydrogen (`gemini-4-hydrogen-high`) | `785031d46ecbba885b15d6f97204a837b0350aff` | 0 | Sửa `scripts/sft_select.py` (`export_judge_round`, `build_parser`, `main`): thêm lớp `"ds_next"` sau cờ CLI `--ds-next` (mặc định tắt); thêm `tests/test_w674_ds_next.py`. |
| H4 (ghim ca/phiếu + notebook + báo cáo) | Hydrogen (`gemini-4-hydrogen-high`) | Trên nhánh `w674-h4` | 0 | Thêm `tests/test_w674_cases_pinned.py`, dựng lại `notebooks/colab_agent.ipynb` bằng `scripts/build_agent_notebook.py`, tạo báo cáo này (`docs/W6_7_4_ket_qua/BAO_CAO.md`). |

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
