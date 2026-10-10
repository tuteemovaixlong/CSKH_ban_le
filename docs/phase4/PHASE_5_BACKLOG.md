# Phase 5 — Backlog sau freeze Phase 4

> Owner chốt 2026-10-08: mọi mục ở file này **không block merge PR #36**; không nhận vào patch sau freeze Phase4.
> Merge scope/8 checklist duy nhất: [PHASE_4_ACCEPTANCE_CRITERIA.md](PHASE_4_ACCEPTANCE_CRITERIA.md).
> Ghi backlog không đồng nghĩa đã sửa, đã measurement-ready hoặc đã được authorize live/paid.

## Mục đã biết chuyển khỏi merge gate

| ID | Nguồn | Vấn đề và tác động | Hướng xử lý Phase5 | Status |
|---|---|---|---|---|
| P5-01 | N1 residual | Validator replay chỉ so manifest hash/sidecar, chưa hash actual source; manual source tamper giữ sidecar có thể pass. Runner đã kiểm LF hash trước emit, nên defer replay hardening. | Shared actual LF hash loader, scenario registry pin, sidecar-preserving source mutation test. | DEFERRED — nonblocking merge |
| P5-02 | N3/L3 residual | n_graded tính blocked/inconclusive, blocked overlap; missing subtraction/clamp có thể che missing; all-blocked completeness1.0. Primary quality denominator đã đúng. | Chốt first/eventual dispositions; graded/blocked/missing sets không overlap; all-blocked/inconclusive/blocked+missing tests. Không dùng current completeness làm G5 proof. | OPEN — nonblocking merge |
| P5-03 | N4 semantic evidence | Positive tool_count nhưng names missing/[] vẫn có thể pass; ownership_bypass=True chưa được grader dùng. Đây là semantics với kiểu đúng, ngoài K3 type gate. | Positive count cần observed identity hoặc unavailable/inconclusive; giữ repeated calls cùng tên hợp lệ. | OPEN — nonblocking merge |
| P5-04 | L2 | CLI custom qrels/sidecar parse nonempty rồi in OK; chưa có canonical-hash acceptance mode. Generic input được phép nhưng report hiện dễ bị hiểu là pin source. | Phân biệt diagnostic/source-inspection và canonical acceptance; expected hash/mode rõ, sửa wording. | BACKLOG — nonblocking merge |
| P5-05 | L4 | Preflight gate metadata G999/null có thể được nhận; sequence comment thiếuG7. G5-only grant/mock deny đã đúng. | Gate enum/optionality metadata và wording; không đổi G5 grant rule. | BACKLOG — nonblocking merge |
| P5-06 | L5 | PR body có counts cũ523/27, local file links/control characters, guardfalse trên41paths; thực tế mixed packaging eligibletrue. | Viết lại PR body ngắn bằng structured/body-file input; exact-head evidence, limitations và scope thực tế. Docs review current đã được đồng bộ. | BACKLOG — nonblocking merge |
| P5-07 | Verification limitation | Local full574/49skip có1 P99 timing failure52.5208ms, focused rerun pass; CI xanh. Chưa chứng minh source regression. | Theo dõi reproducibility timing môi trường trong workstream riêng; giữ artifacts, không hạ threshold để đạt. K5 dùng full CI summary PASS. | OBSERVED — nonblocking ngoài K5 |
| P5-08 | G4/G5 future | Offline checker có thể kiểm provider/lane labels; không thay thế live evidence/identity/completeness/budget thật. | Làm lane preflight/smoke/evidence acceptance ở workstream kế tiếp, authorization riêng. | FUTURE — không block harness merge |
| P5-09 | Operational smoke 2026-10-09→10 | Tenant cũ bị `customer_reserved`; isolation đã merge PR #37 tại `dd0947a`. Owner gửi `LIVE_E2E_SMOKE_OK` report `LIVE_SMOKE_20261010T042118Z.json`; chưa đọc raw JSON trực tiếp. | Smoke dùng tenant mới; giữ reservation cũ. Không dùng operational smoke làm evidence real-model/G5. | DONE — P5-A, theo log owner |
| P5-10 | G4→G5 next workstream | Cần kiểm chứng danh tính Google test, ánh xạ customer bên ngoài và luồng khiếu nại cùng một session. | Xây sales simulator offline/dev với event ký, idempotency, mapping external customer → RetailOps customer; test complaint/proposal/confirmation/audit. | PLANNED — Phase 5 |

## Quy tắc tiếp nhận phát hiện sau freeze

Thêm một hàng gồm ID, frozen SHA, reproduction/evidence, tác động, đề xuất, status. Không sửa acceptance v1, không mở lại merge gate, không thêm test bắt buộc Phase4 hoặc khởi động audit rộng. Chỉ sửa ở task/workstream Phase5 được owner giao sau.

Lỗi type safety flags `ownership_violation`/`identity_collision` đã được sửa và pass ở Phase 4 (K3, PR #36). Mọi vấn đề mới ngoài 8 mục ghi tại đây.

Workstream thực thi: [Phase 5 plan](../phase5/PHASE_5_PLAN.md), [acceptance](../phase5/PHASE_5_ACCEPTANCE_CRITERIA.md), [handoff](../phase5/PHASE_5_EXECUTION_HANDOFF.md).
