# Read-only Admin Console v1

The customer website is unchanged. This optional service runs on the same EC2 instance, behind Caddy, on a separate admin hostname and Docker network. There is no new EC2 instance and no public port 8100. Linux root is not a web user.

## What is implemented

- An independent `opsconsole` package, not imported by the customer runtime.
- Routing evaluation of the existing 30-case dataset, including separate dev/held-out summaries. This calls the actual `agent_protocol.request_mode`, without model inference.
- An allowlisted importer for existing `LIVE_SMOKE_*.json` and `LIVE_FULL_*.json` results. It never reruns those tests or converts a prior result into a fresh test pass. Exact source SHA256 and image digest are recorded.
- Immutable run folders: manifest, per-case JSONL, failures, metrics, CSV and checksums. Reimporting the same live report is idempotent.
- Router accuracy, per-class precision/recall/F1, macro-F1, confusion matrix, contract outcomes, critical checks, observed tokens/model/tool counts and latency.
- IR metric primitives for labeled retrieval experiments; without qrels, retrieval scores remain null. No live Recall@K/faithfulness score is fabricated.
- Read-only PostgreSQL usage snapshots from retained business events and successful login events. Not from bounded conversation history.
- Evaluation history, category chart, confusion matrix, trace latency, token usage, failure explorer; usage windows of 24h/7d/30d, traffic filter, daily events, per-model and pseudonymous per-tenant summaries; deployment snapshots.
- Optional PNG rendering with `python -m opsconsole.plot <report.json> --out <new-folder>` in an environment with matplotlib. The dashboard itself requires no CDN/chart dependency.

## Interpretation limits

Router-only evaluation is NOT model task accuracy. The current dataset has no fixture identity or machine-checkable business outcome for every case, and `expected_tools` describes a family rather than a mandatory sequence. v1 therefore does not pretend to grade all business/agent outcomes from that file.

Live E2E imports retain source timestamps. HTTP-through-Caddy evidence is not a Playwright browser test. Citation provenance is not semantic grounding. `task_success`, `rag_recall_at_5`, `semantic_groundedness`, full funnels, replay-rate and browser message count remain unmeasured until dedicated instrumentation/labels exist.

Latency p95 is displayed only with at least 20 observations, p99 with at least 100. These are descriptive sample quantiles, not statistical guarantees. Cost null is unknown, even for a custom model: no GPU/EC2 infrastructure cost is assumed to be zero. Known sums always include coverage counts. Recorded traces are not a billing ledger and checkpoint retries may duplicate previously incurred usage.

Successful-login principals are not DAU. Business events identify tenant/customer bindings, not necessarily the acting principal. Events are not messages; an HTTP replay or failure before an audit event may leave no event. Tenant-prefix classification (`e2e-`, `eval-`, `ci-`, `test-`) is an explicit heuristic used to separate test traffic, not an authorization boundary. All data is synthetic-demo.

## Security and privacy

The admin container has only read-only sanitized files. It has no DB credential, model key, public port, Docker socket, shell endpoint or evaluation execution button. Caddy is the authentication boundary for every admin URL (including data and assets), using a dedicated `opsadmin` Basic Auth identity over HTTPS and a bcrypt hash. The browser/password manager can retain the login; customer credentials do not grant admin access. Authorization and Cookie headers are removed before proxying to the admin service. The admin network is internal and is not attached to the customer web container.

This first version is a single operator read-only credential, NOT complete admin/evaluator/viewer account management. Authentication changes and credential rotation are operator-only. Do not publish the admin service directly or remove Caddy authentication. A separate application-role/SSO layer is a later phase.

The exporter uses the existing operator's application DSN exclusively in a read-only repeatable-read transaction with lock/statement timeouts. The dashboard never receives it. Exported tenant identifiers use HMAC and a host-only salt; raw principal/customer/session IDs, names, emails, messages and model answers are not exported. Files stay on the host; there is no external telemetry vendor.

## Deployment (EC2 / SSM, not Windows)

`admin-console.py` is installed from the exact release image by CD. The first installation is an attended operation after the customer rollout and smoke pass:

```bash
sudo python3 /opt/retailops/admin-console.py install --image "THE_ACTIVATED_PINNED_IMAGE" --commit "THE_40_CHARACTER_RELEASE_SHA"
```

The placeholders above are not literal values. The installer checks them against the active web image; a concurrent or mismatched deployment fails closed.

It derives `admin-<customer-host>`, creates a private operator credential only if absent, writes a Caddy import/Compose overlay, validates Caddy before recreation, starts the read-only service, and tests anonymous denial, valid login, wrong-password denial and lack of a published port. Customer health is checked afterward. A systemd timer refreshes sanitized metadata every two minutes; refresh never invokes a model. Existing reports are imported, not reexecuted.

Retrieve the initial operator login directly in your private SSM terminal, once:

```bash
sudo cat /opt/retailops/admin-secrets/initial-login.json
```

Do not paste the output into chat, Git or tickets. The Linux root account is not used as the web identity. Files remain root-only. A previously provisioned password is not silently rotated during redeployment.

```bash
sudo python3 /opt/retailops/admin-console.py verify
sudo python3 /opt/retailops/admin-console.py refresh
sudo systemctl status retailops-console-refresh.timer
```

The metadata is a snapshot, not realtime. The UI marks snapshots older than ten minutes as stale. Query limits cause explicit `source_partial`, not invented totals. Snapshot export failure keeps the previous snapshot.

After initial setup, CD updates an already-configured console from the new activated release after the customer smoke check, then reruns customer smoke. It does not enable an admin site or provision credentials on hosts where `admin.env` is absent.

Stop/start with a changed public IP still needs BOTH customer Host and Origin corrected. Rerun admin installation with the current image/commit afterward to align the derived admin hostname. No Elastic IP is provisioned automatically.

## Data and rollback

`/opt/retailops/console-data/runs/` contains retained evaluation artifacts; `usage.json` and `deployment.json` are atomically replaced snapshots. `/opt/retailops/admin-secrets/` is operator-only. `/opt/retailops/admin-caddy/` holds the bcrypt-protected site definition. The initial customer Caddyfile is backed up before adding the optional import.

Disabling the timer and admin container is independent of customer data. Do NOT delete PostgreSQL, `api.env`, customer credentials, business audit or Caddy certificate volumes when disabling analytics. Keep the optional Caddy import empty or restore the recorded pre-admin config and validate/recreate Caddy. An admin failure is not permission to roll back or erase business data.

## Regression tests

`python scripts/check_ops_console.py` tests arithmetic, missing data, failure precedence, immutable/deduplicated artifacts, privacy, windows, traversal, host validation and read-only endpoints. With `RETAILOPS_TEST_DATABASE_URL` it also tests PostgreSQL export on an explicitly disposable tenant. CI has native Windows/Python 3.12 and Linux coverage for this new module; it does not claim the existing Windows suite has been repaired.

References: https://caddyserver.com/docs/caddyfile/directives/basic_auth ; https://scikit-learn.org/stable/modules/generated/sklearn.metrics.classification_report.html ; https://docs.github.com/en/actions/tutorials/store-and-share-data .
