# Decision log

> These entries are source-backed decisions. “Current” governs the frozen local acceptance workflow; “Historical/deferred” is retained for traceability and is not a new merge requirement.
>
> Sources: [`../_digest/code/INFRA.digest`](../_digest/code/INFRA.digest), [`../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md`](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md), [`../phase4/PHASE_5_BACKLOG.md`](../phase4/PHASE_5_BACKLOG.md).

| ID | Status | Decision | Evidence |
|---|---|---|---|
| ADR-001 | Current | Freeze Phase 4 merge scope to exactly K1–K8; do not add K9 or promote backlog findings to blockers. | `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:30-43` |
| ADR-002 | Current | Use frozen `8a666fc...` as evidence head; technical PASS still requires an independent reviewer before owner review. | `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:14;60-89` |
| ADR-003 | Current | Use offline CI as K5 standard; disclose local P99 timing failure and do not lower the SLO or loop tests. | `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:40;45`; `../phase4/PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md:28-32` |
| ADR-004 | Current | Keep `READY FOR MEASUREMENT` exclusive to G5 after required live evidence; merge/CI/mock output cannot grant it. | `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:87-91`; `../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md:68-73` |
| ADR-005 | Current | Keep deployment guarded: `main`, `RETAILOPS_DEPLOY_ENABLED=true` and `deploy_eligible=true` are required. | `../../.github/workflows/deploy-ec2.yml:15-36` |
| ADR-006 | Current | Use digest-pinned ECR images, EC2 preflight and atomic `deployed.env` with `previous.env` rollback pointer. | `../../deploy/deploy-runner.sh:5-36`; `../../deploy/publish_and_activate.py:127-155`; `../../deploy/SETUP.md:129-139` |
| ADR-007 | Current | Keep live E2E separate from CI/package verification; invoke through explicit workflow mode and SSM. | `../../.github/workflows/live-e2e.yml:1-44` |
| ADR-008 | Historical/deferred | Defer replay source re-hashing, completeness semantics and positive tool-name evidence to Phase 5 because v1 closes only scoped vectors. | `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:24-28`; `../phase4/PHASE_5_BACKLOG.md:9-18` |
| ADR-009 | Current | Keep RAG deterministic and fail closed when tenant PostgreSQL/schema/evidence is unavailable; provenance validation is separate from semantic entailment. | `../../retailops/knowledge/embedding.py:1-7;13-43`; `../../retailops/knowledge/tool.py:36-53`; `../../retailops/knowledge/citations.py:15-20` |

[UNVERIFIED] No entry asserts PR #36 is merged, AWS resources are active, or a model/knowledge endpoint serves traffic; those require runtime evidence.
