"""Temporary, hash-checked source transformation for the isolated repair branch.
Removed by the same branch workflow after successful tests and notebook generation.
"""
import hashlib
from pathlib import Path

REPAIRS = {
  "agent_protocol.py": {
    "before": "57ee733d51256e5c7f7d66285d4f980af36a273f449fb7d66294adecebad014b",
    "after": "8aaddb7d1e957f634546f3fe9e65d37413ac9142b1d5c86f8b54750ede1c89de",
    "edits": [[104, 105, "    tool('track_shipment', 'Read available synthetic shipment data for one owned order. Missing carrier data is unknown; this does not query live carriers.',\n"]]
  },
  "retailops/business/application.py": {
    "before": "8242c4fbc1b217717dae3226086360dd1b566497eb5b25d591be252191abaec2",
    "after": "e47b00683f923dc62a6af3e25355809714d1c1b19f1652126f86612901babb09",
    "edits": [
      [203, 204, "                    if name in ('get_order', 'get_context', 'track_shipment', 'prepare_cancellation'):\n"],
      [206, 206, "                        bound.shipment = None\n"],
      [233, 234, "                      'message': answer['message'], 'source': answer['trace'].get('answer_source', 'llm_agent'),\n                      'model_used': answer['trace'].get('model_responses', answer['trace'].get('model_calls', 0)) > 0,\n"],
      [253, 254, "            if (not attachment and result['source'] == 'llm_agent'\n                    and not result['trace'].get('degraded') and is_cacheable_query(text) and not bound.cancel_order\n"]
    ]
  },
  "retailops/workflow/subagents/witty_agent.py": {
    "before": "772bc2f6fa7ebd02ecf2c52c656cd907eaffacfbabc122f86c2b5d3c0cd2d0bd",
    "after": "874d9d9b9fb94520d7801a0be0d61c985a3a3bed80f78de98407f85d180f5689",
    "edits": [
      [4, 4, "import time\n"],
      [5, 5, "from retailops.workflow.subagents.read_worker import worker_messages, call_model\n"],
      [51, 74, "    # Preserve the attached image/history. Infrastructure errors must propagate.\n    prompt = WITTY_SYSTEM_PROMPT + (\n        \"\\nIf an image is attached, describe the visible image directly in Vietnamese. \"\n        \"Do not pretend to see an absent/unavailable image or turn image questions into sales copy.\"\n    )\n    prompt_messages = worker_messages(state, prompt)\n    response = call_model(gateway, prompt_messages, False, time.monotonic() + timeout,\n                          state.setdefault('trace', {}))\n    if response.get('tool_calls'):\n        from retailops_agent import AgentError\n        raise AgentError('agent_response_failed', 'Tools are disabled for this response.', state['trace'])\n    content = response['content']\n    state['trace']['answer_source'] = 'llm_agent'\n"]
    ]
  },
  "retailops/workflow/supervisor.py": {
    "before": "a435312bde5c22c3ce27b35da0b83407472a61753db27f1ca0b628d601705f2f",
    "after": "681d5cec9a55cdae2491f55a7f741cbfba4518a073711d2738fa95317c351664",
    "edits": [
      [6, 6, "from retailops_conversation import normalize\n"],
      [42, 42, "    folded = normalize(last_user_msg)\n    plural_orders = bool(re.search(r'\\b(cac don|tat ca (cac )?don|liet ke don|kiem tra don)\\b', folded))\n"],
      [107, 108, "    elif plural_orders or any(kw in lower_msg for kw in ORDER_KEYWORDS) or re.search(r'\\b(o-\\d+|dh\\d+)\\b', lower_msg):\n"]
    ]
  },
  "retailops_providers.py": {
    "before": "aee6a59d7ec878c45a3929f3981123a93b50886791019ad8163a5f25d6f3a26a",
    "after": "d14b16751d2e6a02c6298580a8cbc2179dc0646a00a150a631d99101dad66cee",
    "edits": [
      [74, 74, "        self.is_custom = bool(custom_endpoint)\n"],
      [105, 106, "        if self.is_custom:\n            provider_name = 'custom_api'\n        elif self.is_anthropic:\n"],
      [154, 154, "\n    def payload_messages(self, messages, system_prompt):\n        \"\"\"Exactly one system turn; preserve transport indices/tool IDs.\"\"\"\n        translated = self.translate(messages)\n        if translated and translated[0].get('role') == 'system':\n            worker_prompt = translated[0]['content']\n            content = system_prompt if worker_prompt == system_prompt else system_prompt + '\\n\\n' + worker_prompt\n            translated[0] = {'role': 'system', 'content': content}\n            return translated\n        return [{'role': 'system', 'content': system_prompt}, *translated]\n"],
      [204, 204, "        pending_ids = []\n"],
      [207, 208, "            if m['role'] == 'system':\n                system_prompt += '\\n\\n' + m['content']\n                i += 1\n            elif m['role'] == 'user':\n"],
      [230, 232, "                tool_calls = (saved.get('tool_calls') if saved else None) or m.get('tool_calls') or []\n                pending_ids = []\n                for j, call in enumerate(tool_calls):\n"],
      [234, 235, "                    cid = call.get('id') or f'history_{i}_{j}'\n                    pending_ids.append(cid)\n                    content.append({'type': 'tool_use', 'id': cid, 'name': fn['name'], 'input': args})\n"],
      [241, 242, "                    if not pending_ids:\n                        raise ProtocolError('Missing Anthropic tool call ID')\n                    cid = pending_ids.pop(0)\n"],
      [297, 298, "        payload = {'model': self.model, 'messages': self.payload_messages(messages, system_prompt),\n"]
    ]
  },
  "retailops_tools.py": {
    "before": "5207f4594c5b2185f674406c446ad7b726f8e9a02d232b0ff023572dca9cb027",
    "after": "bd3c28643b9dbe5a814c259019d575a6c82fab0f109ba8304e6a1469065404ea",
    "edits": [
      [188, 198, "            # Unknown per-account synthetic orders have no carrier record. Do not\n            # fabricate a tracking code, carrier, location or delivery promise.\n            shipment = carriers.get(oid) or {\n                'carrier': None, 'tracking_code': None, 'status': 'unknown',\n                'status_text': 'Ch\\u01b0a c\\u00f3 d\\u1eef li\\u1ec7u h\\u00e0nh tr\\u00ecnh v\\u1eadn chuy\\u1ec3n',\n                'current_location': None, 'shipper': None,\n                'estimated_delivery': None, 'steps': []\n            }\n"],
      [199, 200, "            return {'order_id': oid, 'shipment': shipment, 'order_status': order['status'],\n                    'source': 'synthetic-demo/shipments'}\n"]
    ]
  },
  "web/app.js": {
    "before": "c2ca01fd33233b471373d3404e03d262c02d9a31c021ff1523d5475063a43a07",
    "after": "d3be22f2fe77d212c52615df7cca86f84f681ac6515fbbeda163610f938ceb9a",
    "edits": [
      [132, 133, "const sourceLabels = {tool_result: 'K\u1ebft qu\u1ea3 c\u00f4ng c\u1ee5 \u0111\u00e3 x\u00e1c minh', interface: 'H\u01b0\u1edbng d\u1eabn giao di\u1ec7n', store_data: 'D\u1eef li\u1ec7u \u0111\u01a1n h\u00e0ng', llm_agent: 'H\u1ed9i tho\u1ea1i model'};\n"],
      [663, 664, "const eventLabels = {order_viewed: 'Tra c\u1ee9u \u0111\u01a1n', cancellation_proposed: 'T\u1ea1o \u0111\u1ec1 xu\u1ea5t h\u1ee7y', order_cancelled: '\u0110\u00e3 x\u00e1c nh\u1eadn h\u1ee7y', proposal_dismissed: 'B\u1ecf \u0111\u1ec1 xu\u1ea5t', model_extraction: 'Model ph\u00e2n t\u00edch y\u00eau c\u1ea7u', model_unavailable: 'Kh\u00f4ng k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c model', chat_replied: 'Tr\u1ea3 l\u1eddi h\u1ed9i tho\u1ea1i', agent_replied: 'Ph\u1ea3n h\u1ed3i h\u1ed9i tho\u1ea1i', agent_failed: 'L\u01b0\u1ee3t chat ch\u01b0a ho\u00e0n t\u1ea5t'};\n"]
    ]
  },
  "Dockerfile": {
    "before": "f8620e2ad7d7362214cbcc58910cbf0fe33d5eb06df86f372e318dcc0d3bc61f",
    "after": "78b3dd68cdaee12e5826d7c49df0bd64eadf00785ac0ea43821ba96c25b10d7c",
    "edits": [[11, 11, "COPY deploy/source_consistency.py /app/deploy/\n"]]
  },
  "deploy/rollout-public-web.sh": {
    "before": "e9d214b251cb80540ed1cca11b0403e74fa6a705147607685674a3db89bd2d99",
    "after": "54c21794a036b9bfb2ef7dfcd72e2f401066ea1f045366e1329c0b1319847b50",
    "edits": [
      [79, 79, "overlay_changed=false\ncompose_backup=\"\"\n\n"],
      [80, 81, "  if [[ \"$overlay_changed\" == true && -f \"$compose_backup\" ]]; then\n    cp -p \"$compose_backup\" compose.public.yaml\n  fi\n  if [[ -z \"$previous_image\" || ( \"$previous_image\" == \"$image_ref\" && \"$overlay_changed\" != true ) ]]; then\n"],
      [105, 106, "  local host target_hash live_hash health target_source live_source active_container\n"],
      [118, 119, "  [[ \"$live_hash\" == \"$target_hash\" ]] || return 1\n  # An image ID is insufficient when a host code directory is mounted over /app.\n  target_source=$(docker run --rm --pull never --network none --entrypoint python \"$image_ref\" /app/deploy/source_consistency.py digest) || return 1\n  active_container=$(\"${compose[@]}\" ps -q web) || return 1\n  live_source=$(docker exec \"$active_container\" python /app/deploy/source_consistency.py digest) || return 1\n  [[ \"$live_source\" == \"$target_source\" ]] || { echo 'PUBLIC_WEB_SOURCE_MISMATCH' >&2; return 1; }\n  echo \"PUBLIC_WEB_SOURCE_MATCH=$live_source\"\n"],
      [121, 122, "# Retire ONLY the old script's exact read-only code mounts. Keep /data,\n# catalog/knowledge fixtures, secrets, custom configuration and DB mounts intact.\n# Back up the original compose file so rollback restores code AND its mounts.\ncompose_candidate=$(mktemp /opt/retailops/compose.image-code.XXXXXX)\nif ! docker run --rm -i --pull never --network none --entrypoint python \"$image_ref\" /app/deploy/source_consistency.py strip < compose.public.yaml > \"$compose_candidate\"; then\n  rm -f \"$compose_candidate\"\n  exit 1\nfi\nif ! cmp -s compose.public.yaml \"$compose_candidate\"; then\n  compose_backup=$(mktemp /opt/retailops/compose.pre-image-code.XXXXXX)\n  cp -p compose.public.yaml \"$compose_backup\"\n  mv \"$compose_candidate\" compose.public.yaml\n  overlay_changed=true\n  if ! \"${compose[@]}\" config --quiet; then\n    cp -p \"$compose_backup\" compose.public.yaml\n    exit 1\n  fi\n  echo \"PUBLIC_WEB_LEGACY_CODE_MOUNTS_REMOVED backup=$compose_backup\"\nelse\n  rm -f \"$compose_candidate\"\nfi\n\nif [[ \"$running_image_id\" != \"$target_image_id\" || \"$overlay_changed\" == true ]]; then\n"]
    ]
  }
}

root = Path(__file__).resolve().parents[1]
# Validate every preimage before any file is changed.
for name, change in REPAIRS.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == change['before'], name
for name, change in REPAIRS.items():
    path = root / name
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    for first, last, text in reversed(change['edits']):
        lines[first:last] = text.splitlines(keepends=True)
    result = ''.join(lines).encode('utf-8')
    assert hashlib.sha256(result).hexdigest() == change['after'], name
    path.write_bytes(result)
    print('REPAIR_SOURCE_VERIFIED', name, change['after'])
