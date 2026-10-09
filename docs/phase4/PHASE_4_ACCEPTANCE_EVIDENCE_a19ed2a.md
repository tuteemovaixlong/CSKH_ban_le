# Phase 4 — Evidence cho acceptance v1 tại a19ed2a

> Ngày kiểm tra: 2026-10-08. Frozen HEAD: `a19ed2a74e457fcba9eee76f206156d1f4ea446b`.
> PR [#36](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/36), branch `codex/phase4-harness`, open/unmerged; remote head khớp local lúc kiểm tra.
> Runtime/patch baseline: `49671b928ad6badfaa01331174eb73f0e366752e`. Acceptance: [v1](PHASE_4_ACCEPTANCE_CRITERIA.md).
> Verdict: **K1–K6 PASS; K7 FAIL; K8 C1–C5 PASS/C6 FAIL. Independent sign-off PENDING.** Codex verification này không thay thế reviewer khác/human mới.

## 1. Checklist cố định — không thêm mục

| ID | Evidence đúng SHA | Kết quả |
|---|---|---|
| K1 | Control mock250 valid; đổi `manifest.dataset_sha256` sang `a`×64, refresh checksums; validator invalid vì `dataset_sha256 mismatch`, expected LF hash `36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411` | PASS |
| K2 | `Phase4Grader` tạo13blocked gradings cho first429 thật; append real attempt refs, recompute aggregate/checksums; bundle valid, quality trước/sau185/237=0.7806. All-blocked fixture numerator0/denominator0/rate0 | PASS |
| K3 | `tools_called` string/dict/int/mixed-list:4/4 reject. 8flags × string/int/None:24/24 reject; boolFalse/True:16/16 schema pass. `ownership_violation=True` và `identity_collision=True`:rejected/S0 | PASS |
| K4 | 5GitHub check-runs success trên PR HEAD đúng SHA: offline, colab-python313, portable Windows/Ubuntu, postgres; links bên dưới | PASS |
| K5 | `python -m unittest discover -s tests -p 'test_*.py' -q` trên Windows/Python3.10: `Ran 575 tests in 87.247s`, `OK (skipped=49)`, exit0, failures0/errors0; exact-head CI cũng success | PASS |
| K6 | Mock runner250: validator valid; cases250, attempts263, gradings250, retrievals250, errors13; `evaluation_harness_sha` đúng full frozen HEAD; quality185/237=0.7806 | PASS |
| K7 | `git diff --check 49671b928ad6badfaa01331174eb73f0e366752e HEAD`: exit1,5EOF blank lines (output bên dưới) | FAIL |
| K8 | C1 docs4/4, C2 datasets30/250/250, C3 deployment, C4 live-E2E, C5 notebook sync PASS. C6 tái dùng K7 exit1 | FAIL — C6 |

K1/K2/K3/K6 được chạy bằng probe trong `TemporaryDirectory`, không sửa source/frozen scenarios. K1 có control valid và refresh checksums để không reject nhầm vì checksum; K2 dùng gradings thật. K3 dùng một completed attempt hợp lệ từ control mock; strict bool được thử trên đủ8flags: privacy_leak, prompt_injection, unauthorized_mutation, fabricated_source, ownership_bypass, ownership_violation, identity_collision, unsupported_claim. Đây là vectors trong checklist v1, không thêm check mới.

Full suite ghi headroom artifact vào TEMP qua `RETAILOPS_HEADROOM_ARTIFACT_PATH`; không đổi P99 threshold/runtime. Log exception thuộc fixture lỗi không phải unittest failures; kết luận dựa summary/exit0. Full574 có P99 fail tại04ed899 là lịch sử đã lưu, không dùng focused rerun thay summary575 hiện hành.

Sau khi soạn packet/review/plan và đồng bộ tiến độ, docs contract được kiểm lại4/4PASS; `git diff --check` cho riêng thay đổi tài liệu mới cũng exit0. Các cập nhật này chưa commit/push và không thay code/tests. Kết quả này không thay K7 của patch baseline→frozenHEAD đangFAIL; Gemini cần gộp docs rồi freezeSHA mới.

## 2. K7/C6 — output và sửa tối thiểu

```text
docs/phase4/CHAPTER_4_OUTLINE.md:136: new blank line at EOF.
docs/phase4/PHASE_4_ABLATION_STUDY.md:89: new blank line at EOF.
docs/phase4/PHASE_4_FAILURE_TAXONOMY.md:109: new blank line at EOF.
docs/phase4/PHASE_4_THREATS_TO_VALIDITY.md:80: new blank line at EOF.
docs/phase4/REVIEW_PHASE_4_PLAN.md:289: new blank line at EOF.
```

Gemini chỉ bỏ blank lines thừa cuối5file, giữ một newline cuối mỗi file. Đây là lỗi nhẹ của **K7 đã có**, không phải blocker code mới hoặc K9. `git diff --check` trên worktree sạch sau commit kiểm empty diff, nên exit0 trước đây không chứng minh patch merge sạch. Sau docs update số dòng có thể đổi; kiểm theo cùng base→HEAD để hết cả5 báo lỗi.

## 3. C1–C6 và CI

| Contract | Lệnh/nhóm kiểm | Kết quả |
|---|---|---|
| C1 | `python scripts/check_docs_contract.py` | PASS4/4 |
| C2 | `python scripts/check_eval_dataset.py`, cùng script cho benchmark_250/master_250_v1 theo acceptance | PASS30/250/250 |
| C3 | `python scripts/check_deployment_contract.py` | PASS |
| C4 | `python scripts/check_live_e2e_contract.py` | PASS |
| C5 | `python scripts/build_agent_notebook.py --check` | PASS |
| C6 | `git diff --check 49671b928ad6badfaa01331174eb73f0e366752e HEAD` | FAIL exit1 |

- [Offline](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37737662457/job/113180800991)
- [Colab Python3.13](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37737662457/job/113180800625)
- [Portable Windows](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37737662255/job/113180800476)
- [Portable Ubuntu](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37737662255/job/113180800401)
- [Postgres](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/37737662255/job/113180800122)

CI conclusions dựa check-runs đúng HEAD và workflow source. Không suy đoán job-step metadata; không claim đã chạy Docker local. PR có mixed packaging, guard `deploy_eligible=true`; owner cần biết trước merge.

## 4. Packet cho reviewer mới và bước tiếp theo

Nguồn độc lập chỉ nhận acceptance v1, frozen diff và packet SHA mới sau sửaK7; không nhận lịch sử tìmN1–N5. Chỉ xác minh8mục, PASS/FAIL và ký nguồn/thời điểm. Không dùng Codex reviewer/agents cũ hoặc Gemini tác giả làm sign-off. Hiện **PENDING**; không yêu cầu sign-offPASS khi K7 đangFAIL.

Giữ N1 actual-source replay hardening DEFERRED(P5-01), N3 counts/completeness(P5-02), N4 tool-name semantics(P5-03), L2/L4/L5 và mọi việc ngoài8mục trong [Phase5 backlog](PHASE_5_BACKLOG.md). Không mở audit rộng.

Gemini sửa đúngK7 → commit/freezeSHA mới → verify8check/CI đúngSHA → independent8/8 PASS → owner review → merge → G2 offline trên mergedSHA → dừng review harness/chuyển lane preflight. Không READY FOR MEASUREMENT trướcG5. Chưa thay variables/merge/deploy/live/paid.
