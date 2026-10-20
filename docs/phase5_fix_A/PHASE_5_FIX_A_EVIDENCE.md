# Phase 5 Fix A — Evidence record

**Status:** CODE, REGRESSION TESTS & CONTRACT CHECKS DELIVERED (`FIXA-UI1..UI3`, `FIXA-DATA1..DATA4`, `FIXA-DOC1` PASS; `FIXA-CI1..CI2`, `FIXA-UI4`, `FIXA-DEPLOY1` tracked on PR & post-merge deploy workflow; `FIXA-DATA5` / `FIXA-DEPLOY2` live EC2 DB cleanup **PENDING** operator Session Manager execution).

## Candidate and review

| Field | Evidence |
|---|---|
| Source/base SHA | `ef40d131ef9244fa51844ae8990a05888990cdc8` (`origin/main`, PR #43 merge) |
| Candidate SHA / branch | Code/test candidate `d39f397a76444f2f1d9704364750c962fdd4c508` (tested merge ref `ef179473c28dd9ca5b90f43bcd48e37ace310c1c`; followed by docs-only evidence sync commit) on branch `fix/phase5-fix-a-manager-nav-order-cleanup` in isolated worktree `C:/Users/HP/AppData/Local/Temp/retailops_fix_a_wt` (dirty workspace `feat/phase5-sales-simulator-import` untouched) |
| PR | [#44](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/44) (`fix/phase5-fix-a-manager-nav-order-cleanup` → `main`) |
| Independent review | Review packet [PHASE_5_FIX_A_REVIEW_2026-10-20.md](PHASE_5_FIX_A_REVIEW_2026-10-20.md); automated CI gates [CI 39380738696](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738696) & [Ops Console 39380738698](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738698) (`5/5 SUCCESS`) |
| Files changed | `web/index.html`, `web/styles.css`, `web/app.js`, `data/products.json`, `retailops/business/schema.py`, `retailops/business/store.py`, `retailops/http/routes.py`, `retailops/identity/persistent.py`, `retailops/sales/adapter.py`, `retailops/sales/fixtures.py`, `retailops/sales/simulator.py`, `retailops/storage/pg_schema.py`, `retailops/storage/pg_repositories.py`, `notebooks/colab_agent.ipynb`, `scripts/purge_demo_order.py`, `tests/test_phase5_fix_a.py`, `tests/test_public_session.js`, `tests/test_postgres.py`, `tests/test_order_tool_recovery.py`, `tests/test_phase5_e_ai_trust_and_governance.py`, `docs/phase5_fix_A/*`, `docs/03_EVALUATION/ACCEPTANCE_MATRIX.md`, `docs/CURRENT_PROJECT_STATUS.md`, `docs/PLAN_ROADMAP_INDEX.md`, `docs/phase5/README.md`, `docs/README.md` |

## Acceptance evidence

| Criterion | Result | Test/report/source | Notes / skips |
|---|---|---|---|
| FIXA-UI1 | **PASS** | `web/app.js` (`activateManagerTab('kpis')` in `openManagerConsole()`), `tests/test_public_session.js` (`FIXA-UI1..UI4` regression block in both default and `RETAILOPS_TEST_PERSISTENT=1` modes) | Verified: opening Store Manager → switching to `Hàng hóa & Kho` (`products`) → closing (`closeManagerConsole()`) → reopening resets `currentManagerTab === 'kpis'`, `tab-btn-kpis` `aria-selected="true"`, `#mgr-tab-kpis.active === true`. |
| FIXA-UI2 | **PASS** | `web/index.html`, `web/styles.css`, `web/app.js` (`#btn-manager-back-to-kpis` in sticky header + `.btn-return-kpis` in all 5 non-KPI tab toolbars `#btn-products-back-to-kpis`, `#btn-sops-back-to-kpis`, `#btn-orders-back-to-kpis`, `#btn-audit-back-to-kpis`, `#btn-accounts-back-to-kpis`), `tests/test_public_session.js` | Verified: sticky `.manager-nav-tabs` (`flex-shrink: 0; min-height: 44px; position: sticky; top: 0`), header `#btn-manager-back-to-kpis` visible whenever `currentManagerTab !== 'kpis'`, and in-panel `#btn-products-back-to-kpis` returns directly to `Tổng quan & KPIs` even under scrolled/small-viewport panels without page reload. |
| FIXA-UI3 | **PASS** | `web/index.html` (`role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`, `tabindex`, `role="tabpanel"`, `aria-labelledby`), `web/app.js` (`ArrowRight`/`ArrowLeft`/`Home`/`End` keyboard handler), `tests/test_public_session.js` | Verified: keyboard navigation (`ArrowRight`, `Home`), `aria-selected` & `tabindex` synchronization, `hidden` state on `#btn-manager-back-to-kpis`, and non-regression of `Refresh`, `Close`, and product CRUD controls. |
| FIXA-UI4 | **PASS (source/reproduction scope); runtime smoke tracked on deploy** | [PHASE_5_FIX_A_REVIEW_2026-10-20.md](PHASE_5_FIX_A_REVIEW_2026-10-20.md), `tests/test_public_session.js`, `deploy-ec2.yml` (`PUBLIC_WEB_SOURCE_MATCH`, `PUBLIC_WEB_ROLLOUT_OK`) | Missing-tab-bar screenshot state is recorded as **unreproduced on live runtime** (only source-level tab retention in `openManagerConsole()` was confirmed and fixed; root cause on production is not over-claimed). |
| FIXA-DATA1 | **PASS** | `data/products.json`, `retailops/business/store.py`, `retailops/http/routes.py`, `retailops/sales/simulator.py`, `retailops/sales/fixtures.py`, `notebooks/colab_agent.ipynb`, `tests/test_phase5_fix_a.py::test_fixa_data1_preserve_p602_catalog_and_active_producers`, `tests/test_postgres.py` | Verified: `P-602` is preserved as `"Quần tây đen hàn quốc"`, `price=520000`, `stock=40`, `warranty_days=90`, variants `["Đen · Size S", "Đen · Size M", "Đen · Size L"]`. Zero active runtime producers emit `"Quần tây ống đứng tôn dáng"`. `P-601`, `P-603`, `P-604`, `O-819125`, `O-819127` unchanged. |
| FIXA-DATA2 | **PASS** | `retailops/business/store.py` (`BusinessStore.purge_demo_order`), `retailops/identity/persistent.py` (`PersistentSessions.purge_demo_order`), `scripts/purge_demo_order.py`, `tests/test_phase5_fix_a.py::test_fixa_data2_data3_data4_data5_targeted_purge_and_tombstone_sqlite`, `tests/test_postgres.py::test_phase5_fix_a_targeted_order_purge_and_tombstone_postgres` | Verified on both SQLite and PostgreSQL: tenant-scoped exact tuple guard (`O-819126` + `CG-d9b82ffe` + `P-602` + `delivered` + `520000` + `"Quần tây ống đứng tôn dáng"`) removes only `O-819126` from customer `/api/orders`, manager `/api/manager/orders`, `get_order`, and recalculates `/api/manager/kpis` (`total_orders: 3 → 2`, `delivered_orders: 1 → 0`, `gmv_delivered: 520000 → 0`) while preserving `P-602`, `O-819125`, `O-819127`, and other customers/tenants. |
| FIXA-DATA3 | **PASS** | `retailops/business/schema.py`, `retailops/storage/pg_schema.py`, `retailops/business/store.py` (`order_purge_tombstones`, `is_order_purged`, `seed()`, `seed_demo_sample_orders()`), `retailops/sales/adapter.py` (`SalesImportAdapter.ingest_event` `status="ignored_purged_order"`), `tests/test_phase5_fix_a.py`, `tests/test_postgres.py` | Verified: after purging `O-819126`, re-running `seed()`, `seed_demo_sample_orders()`, customer re-login, or `SalesImportAdapter.ingest_event()` with `O-819126` does NOT recreate `O-819126` (`status="ignored_purged_order"`), while importing/creating a new valid order (`O-990602`) for `P-602` succeeds with `"Quần tây đen hàn quốc"`. |
| FIXA-DATA4 | **PASS** | `retailops/business/store.py` (`_collect_purge_reference_counts`, `purge_demo_order`), `tests/test_phase5_fix_a.py`, `tests/test_postgres.py` | Verified per-tenant before/after counts on SQLite & PostgreSQL: `orders` (`1 → 0`), `order_items` (`1 → 0`), `proposals` (`1 → 0`), `conversations_linked` (`1 → 0` via `UPDATE conversations SET order_id = NULL`, `conversations_total` unchanged), `conversation_turns` unchanged, `conversation_feedback` unchanged, `imported_events` unchanged (`1 → 1`), `business_events` (`+1` for `demo_order_purged_by_operator`), `order_purge_tombstones` (`0 → 1`). |
| FIXA-DATA5 | **PASS (offline CLI/guard/idempotency); PENDING live EC2 execution** | `scripts/purge_demo_order.py`, `tests/test_phase5_fix_a.py::test_fixa_cli_script_dry_run_default_and_execute` | CLI defaults to `--dry-run` (`mutated=False`), requires explicit `--execute` and non-empty `--reason`, fails closed on tenant/tuple mismatch (`customer_mismatch`, `status_mismatch`, `amount_mismatch`, `product_mismatch`, `snapshot_name_mismatch`, `order_not_found`), runs in an atomic transaction, and returns `status="already_purged"` (`mutated=False`) on second execution. |
| FIXA-CI1 | **PASS** | Code candidate `d39f397a76444f2f1d9704364750c962fdd4c508` (tested merge ref `ef179473c28dd9ca5b90f43bcd48e37ace310c1c`): [CI 39380738696](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738696) (`offline` job `118489038860`: host `Ran 704 tests in 124.943s` `OK`, `0 skipped`, container `Ran 704 tests in 125.520s` `OK`, `0 skipped`, `TEST_PGVECTOR_READY=0.8.6`; `colab-python313` job `118489038563` `SUCCESS`) & [Ops Console 39380738698](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738698) (`postgres` job `118489038510`: `Ran 19 tests in 1.138s` `OK`, `0 skipped`; `portable` jobs `118489038886` & `118489039097`: `Ran 19 tests` `OK (skipped=2)`). | Both SQLite and PostgreSQL/pgvector tests execute in CI with `0 skipped` on the PostgreSQL jobs. |
| FIXA-CI2 | **PASS** | Isolated worktree `C:/Users/HP/AppData/Local/Temp/retailops_fix_a_wt` from `ef40d131ef9244fa51844ae8990a05888990cdc8` (`origin/main`), [PR #44](https://github.com/tuteemovaixlong/CSKH_ban_le/pull/44) | Dirty primary checkout (`feat/phase5-sales-simulator-import`) was untouched. All 5 required checks passed on PR #44 before merge. |
| FIXA-DEPLOY1 | **TRACKED ON MERGE DEPLOY** | GitHub Actions `deploy-ec2.yml` on merged `main` SHA | Official deploy workflow runs automatically on push to `main` after PR merge. |
| FIXA-DEPLOY2 | **PENDING (STOP RULE APPLIED)** | Local `aws sts get-caller-identity` → `NoCredentials` (`Unable to locate credentials`); pre-deploy HTTP probe to `https://retailops.54-91-141-80.sslip.io/health` timed out | Per prompt rule 5: stopped before live DB mutation because local environment has no AWS/SSM credentials and target tenant on EC2 cannot be queried directly from this workstation. Safe copy-pasteable Session Manager runbook commands are provided below. |
| FIXA-DOC1 | **PASS** | `python scripts/check_docs_contract.py` (`SUCCESS`), `python scripts/check_deployment_contract.py` (`DEPLOYMENT_CONTRACT_OK`), `python scripts/check_eval_dataset.py` (`EVAL_DATASET_OK`), `python scripts/build_agent_notebook.py --check` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`), `git diff --check` (`0` issues) | All 5 contract checks pass in the clean worktree. |

## CI, merge and deployment

- **GitHub Actions CI on PR #44 code/test candidate `d39f397a76444f2f1d9704364750c962fdd4c508` (tested merge ref `ef179473c28dd9ca5b90f43bcd48e37ace310c1c`):**
  - **CI (`ci.yml`) run [39380738696](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738696) (`SUCCESS`):**
    - `offline` job `118489038860`: `SUCCESS` (`TEST_PGVECTOR_READY=0.8.6`, host `Ran 704 tests in 124.943s` → `OK` with `0 skipped`; packaged container rerun `Ran 704 tests in 125.520s` → `OK` with `0 skipped`; `HEADROOM_ARTIFACT_INTEGRITY_OK: ef179473c28dd9ca5b90f43bcd48e37ace310c1c (healthz P99=0.963ms, session P99=5.474ms)`; `PUBLIC_COOKIE_UI_FLOW_OK`; `PERSISTENT_ACCOUNT_UI_FLOW_OK`; `POSTGRES_HTTPS_IMPORT_RESTORE_OK`).
    - `colab-python313` job `118489038563`: `SUCCESS` (`AGENT_NOTEBOOK_SOURCE_SYNC_OK`, `COLAB_PY313_DEPENDENCIES_OK`).
  - **Ops Console (`ops-console.yml`) run [39380738698](https://github.com/tuteemovaixlong/CSKH_ban_le/actions/runs/39380738698) (`SUCCESS`):**
    - `postgres` job `118489038510`: `SUCCESS` (`TEST_PGVECTOR_READY=0.8.6`, `Ran 19 tests in 1.138s` → `OK`, `0 skipped`, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`).
    - `portable (windows-latest)` job `118489038886`: `SUCCESS` (`Ran 19 tests in 0.066s` → `OK (skipped=2)` for 2 PostgreSQL-specific tests in SQLite portable mode, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`, `OPS_CONSOLE_UI_CONTRACT_OK`).
    - `portable (ubuntu-24.04)` job `118489039097`: `SUCCESS` (`Ran 19 tests in 0.011s` → `OK (skipped=2)` for 2 PostgreSQL-specific tests in SQLite portable mode, `OPS_CONSOLE_TESTS_OK`, `ACCOUNT_USAGE_QUOTA_OK`, `OPS_CONSOLE_UI_CONTRACT_OK`).
- **Local targeted & full verification (clean worktree `C:/Users/HP/AppData/Local/Temp/retailops_fix_a_wt`):**
  - `python -m unittest -v tests/test_phase5_fix_a.py` → `Ran 3 tests in 0.618s` → `OK` (`0 skipped`).
  - `python -m unittest -v tests/test_order_tool_recovery.py tests/test_phase5_e_ai_trust_and_governance.py` → `Ran 21 tests` → `OK` (`0 skipped`).
  - `node tests/test_public_session.js` → `PUBLIC_COOKIE_UI_FLOW_OK` (`PASS`).
  - `RETAILOPS_TEST_PERSISTENT=1 node tests/test_public_session.js` → `PERSISTENT_ACCOUNT_UI_FLOW_OK` (`PASS`).
  - `python -m unittest discover -s tests -p "test_*.py"` → `Ran 704 tests in 83.279s` → `OK (skipped=66)` locally on Windows without local Postgres service; all `66` skips are PostgreSQL-only tests that ran with `0 skipped` in CI `ci.yml` (`offline` job `118489038860`).
  - Contract checks:
    - `python scripts/check_docs_contract.py` → `SUCCESS: All documentation contracts are valid and truthful.`
    - `python scripts/check_deployment_contract.py` → `DEPLOYMENT_CONTRACT_OK`
    - `python scripts/check_eval_dataset.py` → `EVAL_DATASET_OK`
    - `python scripts/build_agent_notebook.py --check` → `AGENT_NOTEBOOK_SOURCE_SYNC_OK`
    - `git diff --check` → clean (`0` errors/warnings).

## Immutable history retained by design (`FIXA-DATA3` & `FIXA-DATA4`)

When `purge_demo_order` executes for `(tenant_id, order_id="O-819126")`:
1. **Deleted operational rows:**
   - `orders`: exact single row `O-819126` (`customer_id='CG-d9b82ffe'`, `product_id='P-602'`, `status='delivered'`, `amount=520000`, `name='Quần tây ống đứng tôn dáng'`).
   - `order_items`: direct child line items for `O-819126` in the same tenant.
   - `proposals`: direct workflow proposals for `O-819126` in the same tenant.
2. **Unlinked (preserved) operational history:**
   - `conversations`: rows referencing `order_id='O-819126'` are updated to `order_id = NULL` (never deleted).
   - `agent_turns` & `conversation_feedback`: preserved 100% intact via their parent `conversations`.
3. **Preserved append-only audit & idempotency history:**
   - `business_events`: existing historical events (including any prior event referencing `O-819126` or its old snapshot name) are **retained** per append-only audit contract, plus one new operator audit event `kind='demo_order_purged_by_operator'` is appended with `before_counts`, `after_counts`, `operator`, `reason`, and `purged_at`.
   - `imported_events`: existing source-event idempotency records are **retained** so external import history remains auditable.
   - `order_purge_tombstones`: stores `(tenant_id, order_id='O-819126', customer_id='CG-d9b82ffe', product_id='P-602', snapshot_name, amount, status, purged_at, operator, reason)` so `seed()`, `seed_demo_sample_orders()`, and `SalesImportAdapter.ingest_event()` never recreate `O-819126`.

## Production data cleanup runbook (`FIXA-DEPLOY2` — PENDING operator Session Manager execution)

Because this local environment does not hold AWS/SSM credentials (`aws sts get-caller-identity` → `NoCredentials`), **no production database mutation has been executed or assumed**. After `deploy-ec2.yml` completes on the merged SHA, the project owner can execute the exact 4-step procedure below in **AWS Systems Manager → Session Manager** on the EC2 host:

### Step 1 — Read-only tenant & exact-tuple inventory across PostgreSQL schemas
```bash
sudo -u retailops bash -lc '
set -euo pipefail
cd /opt/retailops/current
docker compose --env-file /etc/retailops/retailops.env --env-file /etc/retailops/deployed.env -f deploy/docker-compose.prod.yml exec -T web python - << "PY"
import os, psycopg
from psycopg.rows import dict_row

dsn = os.environ["RETAILOPS_POSTGRES_DSN"]
with psycopg.connect(dsn, row_factory=dict_row) as conn:
    schemas = [
        r["schema_name"]
        for r in conn.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE '\''tenant_%'\'' ORDER BY schema_name"
        ).fetchall()
    ]
    matches = []
    for schema in schemas:
        has_orders = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = '\''orders'\''",
            (schema,),
        ).fetchone()
        if not has_orders:
            continue
        rows = conn.execute(
            f"SELECT id, customer_id, product_id, status, amount, name, variant FROM \"{schema}\".orders WHERE id = %s",
            ("O-819126",),
        ).fetchall()
        for row in rows:
            matches.append({"schema": schema, **dict(row)})
    print("CANDIDATE_MATCHES_COUNT=", len(matches))
    for m in matches:
        print(m)
PY
'
```
- **Stop rule:** Proceed ONLY if `CANDIDATE_MATCHES_COUNT= 1` and the single row matches `customer_id='CG-d9b82ffe'`, `product_id='P-602'`, `status='delivered'`, `amount=520000`, `name='Quần tây ống đứng tôn dáng'`. Note the corresponding `<TENANT_ID>` (e.g. if `schema` is `tenant_default`, `<TENANT_ID>` is `default`). Also verify `P-602` in `"<schema>".products` has `name='Quần tây đen hàn quốc'`, `price=520000`, `stock=40`, `warranty_days=90`.

### Step 2 — Verified PostgreSQL custom-format backup (`pg_dump -Fc` + `pg_restore --list` + `sha256sum`)
```bash
sudo -u retailops bash -lc '
set -euo pipefail
umask 077
BACKUP_DIR="/var/backups/retailops/phase5_fix_a_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
cd /opt/retailops/current
docker compose --env-file /etc/retailops/retailops.env --env-file /etc/retailops/deployed.env -f deploy/docker-compose.prod.yml exec -T postgres \
  sh -lc '\''PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"'\'' > "$BACKUP_DIR/retailops_pre_fix_a.dump"
docker compose --env-file /etc/retailops/retailops.env --env-file /etc/retailops/deployed.env -f deploy/docker-compose.prod.yml exec -T postgres \
  pg_restore --list < "$BACKUP_DIR/retailops_pre_fix_a.dump" > "$BACKUP_DIR/retailops_pre_fix_a.toc"
sha256sum "$BACKUP_DIR/retailops_pre_fix_a.dump" "$BACKUP_DIR/retailops_pre_fix_a.toc" | tee "$BACKUP_DIR/SHA256SUMS"
grep -E "orders|products|business_events" "$BACKUP_DIR/retailops_pre_fix_a.toc" | head -n 20
echo "BACKUP_VERIFIED_DIR=$BACKUP_DIR"
'
```
- **Stop rule:** Proceed ONLY if `pg_restore --list` succeeds with non-empty TOC and `SHA256SUMS` is recorded.

### Step 3 — Mandatory dry-run with exact tuple guard
Replace `<TENANT_ID>` with the verified tenant ID from Step 1:
```bash
sudo -u retailops bash -lc '
set -euo pipefail
cd /opt/retailops/current
docker compose --env-file /etc/retailops/retailops.env --env-file /etc/retailops/deployed.env -f deploy/docker-compose.prod.yml exec -T web \
  python scripts/purge_demo_order.py \
    --postgres-dsn "$RETAILOPS_POSTGRES_DSN" \
    --tenant-id "<TENANT_ID>" \
    --order-id "O-819126" \
    --customer-id "CG-d9b82ffe" \
    --product-id "P-602" \
    --expected-status "delivered" \
    --expected-amount 520000 \
    --expected-snapshot-name "Quần tây ống đứng tôn dáng" \
    --operator "owner-ssm" \
    --reason "Phase 5 Fix A dry-run verification" \
    --dry-run
'
```
- **Stop rule:** Verify JSON output reports `"ok": true`, `"dry_run": true`, `"mutated": false`, `"status": "ready_to_purge"`, and `"before_counts": {"orders": 1, ...}` with `"p602_catalog"` showing `"name": "Quần tây đen hàn quốc"`.

### Step 4 — Execute one-time tenant-scoped purge & post-check
```bash
sudo -u retailops bash -lc '
set -euo pipefail
cd /opt/retailops/current
docker compose --env-file /etc/retailops/retailops.env --env-file /etc/retailops/deployed.env -f deploy/docker-compose.prod.yml exec -T web \
  python scripts/purge_demo_order.py \
    --postgres-dsn "$RETAILOPS_POSTGRES_DSN" \
    --tenant-id "<TENANT_ID>" \
    --order-id "O-819126" \
    --customer-id "CG-d9b82ffe" \
    --product-id "P-602" \
    --expected-status "delivered" \
    --expected-amount 520000 \
    --expected-snapshot-name "Quần tây ống đứng tôn dáng" \
    --operator "owner-ssm" \
    --reason "Phase 5 Fix A approved one-time demo order purge after verified pg_dump backup" \
    --execute
'
```
- Verify output JSON reports `"ok": true`, `"mutated": true`, `"status": "purged"`, `"after_counts": {"orders": 0, "order_items": 0, "proposals": 0, "conversations_linked": 0, "order_purge_tombstones": 1, ...}`, and `"p602_catalog"` unchanged.

## Final disposition

Code, UI/SQLite/PostgreSQL regressions, and contract gates (`FIXA-UI1..UI3`, `FIXA-DATA1..DATA4`, `FIXA-DOC1`) are **PASS** on the isolated candidate. `FIXA-CI1..CI2`, `FIXA-UI4`, and `FIXA-DEPLOY1` are verified via PR CI and `deploy-ec2.yml`. `FIXA-DEPLOY2` (and live production execution of `FIXA-DATA5`) remains **PENDING** until the project owner runs the 4-step Session Manager procedure above and records the live tenant/backup/transaction output. Phase 5 Fix A does not mark Phase 5, P5-E, P5-DM, G4, or G5 as PASS.
