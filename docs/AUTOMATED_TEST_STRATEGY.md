# RetailOps Automated Test Strategy

This document defines the permanent rule for new RetailOps work: **a feature is not complete until its regression coverage is added to the automated suite at the appropriate layer**.

## Test layers

### L1 — deterministic repository/CI tests

Use for business invariants, protocol contracts, storage migrations, authorization, retrieval contracts, UI JavaScript behavior and deployment-script validation.

Requirements:

- no paid inference;
- no production credentials;
- deterministic and repeatable;
- runs on every pull request;
- safety failures are blocking failures.

The evaluation dataset contract under `evals/` is validated here. Do not convert unit-test counts into an agent-quality score.

### L2/L3 — release image and live deployment smoke

Every `main` deployment builds and verifies the exact release image, publishes it by digest, rolls it to EC2 through SSM, and then runs `deploy/live-e2e.py --mode smoke` against the public HTTPS surface.

Smoke verifies:

- `deployed.env` and the running web container use the exact expected image;
- `/healthz` reports PostgreSQL and `retailops-agent-v2`;
- the public login surface is reachable through Caddy;
- an isolated synthetic member can log in;
- server-bound tenant/customer/role/session metadata is correct;
- owned order reads and provider metadata work;
- logout invalidates the session;
- credentials are revoked and never written to logs/reports.

Smoke is intentionally model-free, so it can run after every deploy without spending external inference.

### L4 — attended full live E2E

Run `.github/workflows/live-e2e.yml` with `mode=full` when a release or model/retrieval/business-workflow change needs full production-path evidence.

Full mode adds:

- real configured model selection;
- tool-free general mode;
- order tool execution;
- product tool execution;
- tenant-scoped knowledge ingestion and RAG citation provenance;
- cancellation preparation without mutation;
- explicit HITL proposal/confirmation;
- web-container restart with session/proposal/chat replay persistence;
- duplicate-confirm idempotency and exactly-one cancellation audit event;
- viewer read access with cancellation denied by server authorization.

The full runner uses an isolated synthetic tenant and revokes generated credentials. The tenant is retained for audit evidence until a dedicated retention/cleanup policy is added.

## Definition of Done for future PRs

For every new feature or bug fix:

1. Identify the invariant or regression that can break.
2. Add/extend deterministic CI coverage whenever the behavior can be tested without a live model.
3. Add or extend `evals/scenarios/*.jsonl` when the change affects agent behavior, retrieval or safety outcomes.
4. Add a smoke assertion when the change affects deployment, public HTTPS, identity/session binding or essential live reads.
5. Add a full-L4 assertion when the change affects real-model routing/tool use, HITL, persistence, idempotency, authorization or RAG grounding.
6. Do not merge if the new behavior has no appropriate regression coverage unless the PR explicitly documents why automation is impossible.

## Commands

Repository contracts:

```bash
python3 scripts/check_eval_dataset.py
python3 -m py_compile deploy/live-e2e.py deploy/trigger_live_e2e.py
python3 scripts/check_live_e2e_contract.py
python3 -m unittest discover -s tests -v
```

On the EC2 host:

```bash
sudo python3 /opt/retailops/live-e2e.py --mode smoke
sudo python3 /opt/retailops/live-e2e.py --mode full
```

The normal deploy workflow runs smoke automatically. Full mode is intentionally attended because it can consume live model quota/cost and mutates only isolated synthetic test data.

## Evidence levels

- **L1:** repository tests/contracts pass.
- **L2:** exact image built/published/activated.
- **L3:** exact image is live and healthy; live smoke passes.
- **L4:** full real-model/business E2E passes and a sanitized report is saved under `/opt/retailops/e2e-reports/`.
