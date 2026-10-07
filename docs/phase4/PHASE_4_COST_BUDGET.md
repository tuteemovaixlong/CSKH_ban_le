# Phase 4 — Cost Budget and Tracking

Status: READY FOR HARNESS/PREFLIGHT — no paid API/cloud/GPU run is authorized or executed by this document (2026-10-06).

## 1. Cost model

run_total = EC2_compute + GPU_compute + API_usage + storage + egress + observability + annotation + contingency.

Record estimates and actuals separately. Missing price is UNKNOWN, never zero. Track these ledgers independently:

- application quota (for example API turn limit);
- provider billing/rate quota;
- GPU/instance capacity;
- GitHub/CI quota;
- annotation/grader and artifact storage.

## 2. Cost centers

| Cost center | Quantity | Evidence |
|---|---|---|
| control-plane/shared host | control_hours | ownership, instance ID, start/stop |
| short-lived GPU runner | gpu_hours | type, region, image, start/stop |
| reference API | tokens/requests | provider usage/export, model ID |
| model warmup/download | hours/GB | logs and storage |
| retry/variance/smoke | requests/tokens | run IDs and retry records |
| grader/annotation | cases/hours | annotation ledger |
| storage/egress/logs | GB/time | artifact URI and billing |
| contingency | approved percent | approval record |

Existing public/shared EC2 must not be stopped by a Phase 4 script without an ownership/runbook decision. g6.xlarge/L4/Colab are candidate resources only.

## 3. Approval and caps

~~~yaml
budget:
  approval_id: PENDING
  hard_cap_usd: null
  lane_id: PENDING
  smoke_cap_usd: null
  full_run_cap_usd: null
  retry_cap_usd: null
  app_quota_budget: null
  provider_quota_budget: null
  gpu_hours_cap: null
  price_source: PENDING
~~~

No paid or cloud run starts until approval_id, price source, lane, hard cap and stop rule are non-null. Smoke approval and full-run approval are separate. Merge/CI is not cost approval.

## 4. Tracking record

~~~json
{"run_id":"phase4-YYYYMMDD-HHMMSS","timestamp_utc":"2026-10-06T00:00:00Z","cost_center":"gpu_runner|reference_api|storage|egress|annotation|control_plane","provider":"aws|api_provider|github|other","resource_id":"redacted-or-public-id","quantity":0,"unit":"instance_hour|request|input_token|output_token|gb_month|gb|case_hour","unit_price_usd":null,"amount_usd":null,"price_source":"billing_export_or_dashboard","evidence_ref":"artifact-or-invoice-reference"}
~~~

amount_usd equals quantity × unit_price after documented rounding. If unavailable, amount remains null and final cost claim is blocked.

## 5. Stop rules

Stop before the next batch when projected spend exceeds 80% of cap, price/quota is unknown, credentials appear, retry expands without new evidence, configuration identity changes, or application/provider/GPU quota is exhausted. Report scheduled, attempted, graded and blocked denominators.

## 6. Backlog

| ID | Acceptance | Status |
|---|---|---|
| C01 | smoke/full/retry budgets isolated from app daily quota and provider quota | BACKLOG |
| C02 | hard cap, approval ID and live price source recorded | BACKLOG |
| C03 | warmup/download/annotation/retry/shared-host allocation included | BACKLOG |
| C04 | stop event leaves shared public resource unchanged | BACKLOG |

Until C01–C04 have evidence, no paid/cloud/GPU execution is authorized.
