# PHASE_4_STATISTICAL_ANALYSIS — Phân tích, CI và significance

> Trạng thái: READY FOR HARNESS/PREFLIGHT. Chưa có raw run evidence; mọi số dưới đây là protocol.

## 1. Unit và estimand

Đơn vị quality là logical case_id, không phải retry. Primary estimand là first-attempt outcome trên N_total scheduled cases. Eventual outcome sau retry, retry recovery và reliability là secondary. Load samples bootstrap theo run/worker block; không coi request/retry cùng burst là độc lập.

Báo riêng N_total, N_attempt, N_graded_first, N_graded_eventual, N_blocked, skip/timeout/429 và missing evidence.

## 2. Binary outcomes

Báo tỷ lệ x/n, Wilson 95% CI; dùng Clopper–Pearson khi n nhỏ hoặc x gần 0. Provider comparison trên cùng case dùng McNemar exact và paired risk difference. Không dùng t-test cho pass/fail.

Primary first_attempt_success_rate = (first pass + first abstain_correct) / N_total. quality_conditional = (first pass + first abstain_correct) / N_graded_first. Eventual success không thay primary.

## 3. Ordinal/rubric

Mỗi chiều rubric 0/1/2 có anchors cố định. Báo median/IQR/mean; paired permutation hoặc Wilcoxon khi phù hợp. Agreement dùng weighted kappa/Krippendorff alpha; adjudication tạo grading record mới. Safety veto binary báo riêng.

## 4. Retrieval

Recall@k/MRR/nDCG chỉ tính query có qrels áp dụng; no-evidence báo N/A/metric riêng. Bootstrap theo query/template group; paired delta giữa arms có cùng qrels/corpus. Candidate recall và served-evidence coverage không gộp.

## 5. Latency/load

Percentile nearest-rank trên raw, chưa làm tròn; báo n và CI. Tách E2E, TTFB, provider inference, queue_wait, HTTP admission, conv_lock và InferenceGate. Báo riêng 429 server_busy, model_busy và provider 429 nếu phân biệt. Throughput và Jain fairness lấy từ raw per-worker/run vectors.

## 6. Missing, retry và blocked

- first attempt: reliability thật của request đầu tiên;
- eventual: kết quả sau retry policy;
- blocked_environment: không chấm quality do DB/model/network/harness.

Không bỏ case fail vì retry thành công. Diagnostic rerun là run_id riêng, không thay numerator primary.

## 7. Multiple comparisons và decision

Alpha 0.05, hai phía, CI 95%. Category/metric multiple tests dùng Benjamini–Hochberg và báo q-value. Effect size và cost/latency delta phải đi cùng p-value. Thay đổi plan sau khi xem kết quả là exploratory.

Decision:

- SUPPORTED: raw/grader/qrels/CI đầy đủ và gate đạt;
- INCONCLUSIVE: thiếu qrels/power/evidence hoặc selective availability;
- REJECTED: hard safety veto hoặc metric không đạt ngưỡng đã đăng ký.

## 8. Stopping và repetition

- dev=150 cho harness/smoke; held_out=100 chạy một lần final mỗi cell.
- Retry chỉ transport/runtime theo policy; rerun blocked/transport hoặc diagnostic đã đăng ký.
- Load mỗi level ít nhất 3 repetition độc lập; cap/duration pin trước run.
- Dừng khi đủ cap, budget/quota hard stop hoặc safety/infrastructure stop; không dừng vì một run đẹp.

## 9. Minimum report

Mỗi so sánh có n, numerator/denominator, estimate, 95% CI, paired delta, effect size, p/q-value, cost/latency delta, missing/blocked và decision. Chưa có acceptance evidence nên chưa công bố significance/score.
