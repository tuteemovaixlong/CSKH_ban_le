# Phase 5 — G2 Offline Replay Evidence trên Merged SHA 8868c5c

- **Merged SHA**: `8868c5c498b1c64241bc791eb0166d82415cfeb0`
- **Base Tree Hash**: `fd7d727e40f2bdde238ccf6fed9ead77379daf14` (khớp hoàn toàn tree của PR #36 `cf19766`)
- **Parent 1 (main baseline)**: `49671b928ad6badfaa01331174eb73f0e366752e`
- **Parent 2 (PR #36 HEAD)**: `cf19766176749c40fa4321e2b35c9d03896812db`
- **Xác minh tại**: 2026-10-09T21:38:00+07:00
- **Trạng thái G2**: **PASS (ĐẠT)** — Sẵn sàng cho chặng P5-A (Smoke Isolation).

---

## 1. Kết quả kiểm tra bộ 6 Contracts C1–C6

| ID | Contract / Lệnh | Kết quả | Chi tiết |
|---|---|:---:|---|
| **C1** | `python scripts/check_docs_contract.py` | **PASS** | 4/4 checks passed (Dataset integrity, Stale Git HEAD, Link & markdown rules, AST Dynamic tool contract). |
| **C2** | `python scripts/check_eval_dataset.py` (+ 250 scenarios) | **PASS** | `baseline_v1.jsonl`: 30 cases OK.<br>`benchmark_250.jsonl`: 250 cases OK.<br>`master_250_v1.jsonl`: 250 cases OK. |
| **C3** | `python scripts/check_deployment_contract.py` | **PASS** | `DEPLOYMENT_CONTRACT_OK`: Các mốc packaging, pgvector, Caddy, rollout, cutover hợp lệ. |
| **C4** | `python scripts/check_live_e2e_contract.py` | **PASS** | `LIVE_E2E_CONTRACT_OK`: Các mốc kiểm tra live E2E, OIDC, packaging không rò rỉ credential. |
| **C5** | `python scripts/build_agent_notebook.py --check` | **PASS** | `AGENT_NOTEBOOK_SOURCE_SYNC_OK`: Notebook agent đồng bộ tuyệt đối với source tree. |
| **C6** | `git diff --check 49671b928ad6badfaa01331174eb73f0e366752e HEAD` | **PASS** | Exit code 0, không có trailing whitespace hay lỗi format dòng. |

---

## 2. Kết quả Mock 250 Replay trên Merged Harness SHA

Lệnh thực thi:
```bash
python -m evals.harness.cli mock-run --run-id g2_replay_8868c5c --outdir artifacts/g2_mock_250_bundle
python -m evals.harness.cli validate --run-dir artifacts/g2_mock_250_bundle
```

Kết quả bundle validator và aggregate:
- **Validator Report**: `VALID: Bundle 'g2_replay_8868c5c' in artifacts/g2_mock_250_bundle passed all Phase 4 checks!`
- **Evaluation Harness SHA**: `8868c5c498b1c64241bc791eb0166d82415cfeb0` (khớp chính xác merged SHA)
- **Logical Cases**: `250`
- **Attempts**: `263` (250 first attempts + 13 transport retries)
- **Gradings**: `250`
- **Retrievals**: `250`
- **Errors**: `13` (tương ứng 13 trường hợp 429 admission retry)
- **Quality Conditional (First Attempt)**:
  - `numerator`: **185**
  - `denominator`: **237**
  - `rate`: **0.7806** (khớp chuẩn frozen quality baseline)
- **Frozen Benchmark Hash**: Khớp `FROZEN_BENCHMARK_LF_SHA256` (`30d52b1263c9ebffb53dfa32b2e8ebdb8778f6c4ff43eb894bfba894a4b4ee99`).

---

## 3. Targeted Unit Tests

- `tests.test_phase4_writer_validator.TestWriterAndValidator.test_r12_frozen_benchmark_hash_mismatch`: **PASS** (K1 mutation reject)
- `tests.test_phase4_writer_validator.TestWriterAndValidator.test_n3_quality_conditional_excludes_blocked_environment`: **PASS** (K2 blocked denominator)
- `tests.test_phase4_schema`: **PASS** (K3 schema strict typing)
- `tests.test_phase4_grader`: **PASS** (K3 grader hard safety veto)
- Tổng cộng 40 targeted tests hoàn thành trong 0.185s, 0 failures, 0 errors.

---

## 4. Kết luận Gate G2

Gate G2 offline replay trên commit `8868c5c498b1c64241bc791eb0166d82415cfeb0` **CHÍNH THỨC ĐẠT (PASS)**.
Đủ điều kiện chuyển sang bước sửa `live-e2e.py` cho chặng P5-A (Smoke Isolation).
