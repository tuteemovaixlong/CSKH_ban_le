#!/usr/bin/env python3
"""Static contract checks for the live E2E deployment harness."""
from pathlib import Path

ROOT = Path.cwd()
runner = (ROOT / 'deploy' / 'live-e2e.py').read_text(encoding='utf-8')
trigger = (ROOT / 'deploy' / 'trigger_live_e2e.py').read_text(encoding='utf-8')
publish = (ROOT / 'deploy' / 'publish_and_activate.py').read_text(encoding='utf-8')
dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
workflow = (ROOT / '.github' / 'workflows' / 'live-e2e.yml').read_text(encoding='utf-8')

assert 'deploy/live-e2e.py' in dockerfile, 'live E2E runner must be packaged into the release image'
assert 'live-e2e.py' in publish, 'deployment must install the exact release E2E runner'
assert '--mode smoke' in publish, 'deployment must execute live smoke after rollout'
assert 'workflow_dispatch:' in workflow, 'live E2E workflow must support attended runs'
assert 'id-token: write' in workflow, 'live E2E workflow must use AWS OIDC rather than static AWS keys'
assert 'deploy-retailops-demo' in workflow, 'live E2E must serialize with deployment'
assert 'trigger_live_e2e.py' in workflow, 'workflow must use the checked-in SSM trigger'

for forbidden in ('print(credential', 'print(customer_credential', 'print(viewer_credential', 'print(staff_credential', 'echo $credential'):
    assert forbidden not in runner, f'credential logging is forbidden: {forbidden}'

required_checks = (
    'exact_live_image', 'health', 'public_login_surface', 'session_binding', 'orders',
    'account_usage', 'general_model', 'order_model_tool', 'product_model_tool', 'rag_model_tool',
    'model_prepares_but_does_not_mutate', 'restart_pending_persistence',
    'confirm_idempotency_and_backend_state', 'staff_denied_manager_scope',
)
for name in required_checks:
    assert name in runner, f'missing live E2E check: {name}'

assert 'order_action_request_id' in runner, 'live E2E must verify OD-05 order_action_request_id on confirm'
assert '/api/order-actions' in runner, 'live E2E must verify created order action via /api/order-actions'
assert 'first.get("status") == "requested"' in runner, 'live E2E must verify requested status after confirm'
assert '(order_after.get("order") or {}).get("status") == "pending"' in runner, 'live E2E must verify order stays pending until human review'
for legacy_id in ('"C-001"', '"O-101"', '"C-002"', '"P-001"'):
    assert legacy_id not in runner, f'retired legacy seed identifier is forbidden in live E2E runner: {legacy_id}'
assert 'select_seeded_targets' in runner, 'live E2E must resolve targets dynamically from seeded tenant data'

print('LIVE_E2E_CONTRACT_OK')
