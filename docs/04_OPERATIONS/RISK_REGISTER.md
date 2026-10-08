# Risk register

> Scope: risks evidenced by the current Phase 4 review/acceptance/backlog and deployment source. This file does not create new blockers.
>
> Cache: [`../_digest/code/INFRA.digest`](../_digest/code/INFRA.digest). Source backlog: [`../phase4/PHASE_5_BACKLOG.md`](../phase4/PHASE_5_BACKLOG.md).

| ID | Risk / impact | Current status | Mitigation / next owner action | Evidence |
|---|---|---|---|---|
| P5-01 | Replay validator can trust a preserved sidecar/manifest without hashing altered benchmark source. | DEFERRED, nonblocking merge. | Shared actual-LF hashing and sidecar-preserving mutation test in Phase 5. | `../phase4/PHASE_5_BACKLOG.md:9-12` |
| P5-02 | Blocked/inconclusive records can overlap graded counts and hide missing completeness. | OPEN, nonblocking merge. | Define first/eventual dispositions and non-overlapping sets; do not use current completeness as G5 proof. | `../phase4/PHASE_5_BACKLOG.md:9-13` |
| P5-03 | Positive tool count without observed names and an unused ownership alias weaken semantic evidence. | OPEN, nonblocking merge. | Require observed identity or explicit unavailable/inconclusive handling. | `../phase4/PHASE_5_BACKLOG.md:9-13` |
| P5-04 | Diagnostic qrels/sidecar parsing can be mistaken for canonical hash acceptance. | BACKLOG, nonblocking merge. | Separate diagnostic from canonical expected-hash mode. | `../phase4/PHASE_5_BACKLOG.md:14` |
| P5-05 | Preflight metadata can accept null/unknown gate labels. | BACKLOG, nonblocking merge. | Define gate enum/optionality; retain G5-only grant rule. | `../phase4/PHASE_5_BACKLOG.md:15` |
| P5-06 | Historical PR counts/links and eligibility wording can mislead review. | BACKLOG, nonblocking merge. | Rewrite PR body from exact-head evidence. | `../phase4/PHASE_5_BACKLOG.md:16` |
| P5-07 | Local timing variance can fail HTTP headroom while CI is green. | OBSERVED outside K5; nonblocking under v1. | Preserve failure/environment; do not lower SLO or loop tests. | `../phase4/PHASE_5_BACKLOG.md:17`; `../phase4/PHASE_4_ACCEPTANCE_EVIDENCE_8a666fc.md:28-32` |
| P5-08 | Offline checks cannot establish live provider, identity, budget or completeness evidence. | FUTURE, nonblocking merge. | Handle in separately authorized G4/G5 lane workstream. | `../phase4/PHASE_5_BACKLOG.md:18`; `../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:87-91` |
| INFRA-01 | Deployment may publish/roll out when guard and variable allow it; current cloud state is unknown from source. | [UNVERIFIED] runtime state. | Verify repository variables/environment during owner-authorized deployment review. | `../../.github/workflows/deploy-ec2.yml:15-36`; `../../deploy/SETUP.md:101-127` |

No new risk IDs or merge blockers are introduced here; post-freeze findings remain in Phase 5 (`../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md:60-72`).
