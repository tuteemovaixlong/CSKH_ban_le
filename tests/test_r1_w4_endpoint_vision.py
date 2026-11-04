"""Phase R1 W4 — Item 0 (two-layer Colab endpoint & pinned runtime) and Item 1 (vision capability config)."""
import ast
import hashlib
import io
import json
import os
import re
import tempfile
import types
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from gemma_fakes import FIXTURE_ENDPOINT, FIXTURE_KEY, FIXTURE_MODEL, chat_reply, http_error
from retailops.business.application import Application
from retailops.business.store import BusinessStore
from retailops.config import Settings
from retailops.core import ApiError
from retailops.models import build_gateways
from retailops_agent import AgentError, run_agent
from retailops_providers import TUNNEL_TOKEN_HEADER, OpenRouterAgent, api_from_environment

ROOT = Path(__file__).resolve().parents[1]
TUNNEL_TOKEN = "tunnel_secret_fixture_" + "t" * 30


def _load_vllm_notebook_symbols():
    rel = "notebooks/colab_vllm_l4.py"
    source = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(n in ("VLLM_VERSION", "TEMPLATE_URL", "TEMPLATE_SHA256", "MAX_IMAGES_PER_REQUEST") for n in names):
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in (
            "verify_and_patch_chat_template",
            "build_vllm_server_command",
            "open_colab_ngrok_tunnel",
        ):
            keep.append(node)
    mod = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {
        "hashlib": hashlib,
        "json": json,
        "re": re,
        "urllib": types.SimpleNamespace(parse=urllib.parse),
    }
    exec(compile(mod, rel, "exec"), ns)
    return ns, source


class W4Item0EndpointAndPinnedRuntimeTests(unittest.TestCase):
    def test_vllm_notebook_pins_runtime_verifies_template_digest_and_sets_hardening_flags(self):
        ns, source = _load_vllm_notebook_symbols()
        self.assertEqual(ns["VLLM_VERSION"], "0.32.0")
        self.assertIn(f"vllm=={ns['VLLM_VERSION']}", source)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", ns["TEMPLATE_SHA256"]))
        self.assertIn(ns["VLLM_VERSION"], ns["TEMPLATE_URL"])

        # Valid template digest passes and patches the string-arguments branch
        sample_raw = (
            b"{# header #}\n"
            + (b"x" * 1200)
            + b"""\n                    {%- elif function['arguments'] is none -%}
                    {%- else -%}
                        {{- raise_exception(
                            "chat_template: tool_calls[].function.arguments must be a "
                            "JSON object (mapping), not a string. Deserialize arguments "
                            "before passing to the template."
                        ) -}}
                    {%- endif -%}"""
        )
        expected_digest = hashlib.sha256(sample_raw).hexdigest()
        patched = ns["verify_and_patch_chat_template"](sample_raw, expected_sha256=expected_digest)
        self.assertIn("function['arguments'] is string", patched)
        self.assertNotIn("must be a \"", patched)

        # Tampered template bytes fail closed before writing
        with self.assertRaises(RuntimeError) as bad_digest:
            ns["verify_and_patch_chat_template"](sample_raw + b"!", expected_sha256=expected_digest)
        self.assertIn("SHA-256", str(bad_digest.exception))

        # Server command requires API key, disables request logs, and limits images per request
        with self.assertRaises(RuntimeError):
            ns["build_vllm_server_command"]("python3", FIXTURE_MODEL, "fp8", "/tmp/t.jinja", "short")

        cmd = ns["build_vllm_server_command"](
            "python3", FIXTURE_MODEL, "fp8", "/content/tool_chat_template_gemma4.jinja", FIXTURE_KEY
        )
        self.assertIn("--api-key", cmd)
        self.assertEqual(cmd[cmd.index("--api-key") + 1], FIXTURE_KEY)
        self.assertIn("--no-enable-log-requests", cmd)
        self.assertIn("--disable-uvicorn-access-log", cmd)
        self.assertIn("--limit-mm-per-prompt", cmd)
        mm_cfg = json.loads(cmd[cmd.index("--limit-mm-per-prompt") + 1])
        self.assertEqual(mm_cfg, {"image": 3})

    def test_ngrok_tunnel_enforces_two_layer_traffic_policy_on_static_domain(self):
        ns, _ = _load_vllm_notebook_symbols()
        open_tunnel = ns["open_colab_ngrok_tunnel"]

        class FakeNgrok:
            def __init__(self, url="https://shop-static.ngrok-free.app"):
                self.url = url
                self.connect_calls = []

            def get_tunnels(self):
                return []

            def disconnect(self, url):
                pass

            def set_auth_token(self, tok):
                pass

            def connect(self, port, proto="http", **kwargs):
                self.connect_calls.append((port, proto, kwargs))
                return types.SimpleNamespace(public_url=self.url)

        fake = FakeNgrok()
        # Missing static domain or tunnel token is rejected when two-layer mode is required
        with self.assertRaises(RuntimeError):
            open_tunnel(fake, 8001, ["ngrok-auth"], ngrok_domain="", tunnel_token=TUNNEL_TOKEN, require_two_layer=True)
        with self.assertRaises(RuntimeError):
            open_tunnel(
                fake, 8001, ["ngrok-auth"], ngrok_domain="shop-static.ngrok-free.app", tunnel_token="", require_two_layer=True
            )

        url = open_tunnel(
            fake,
            8001,
            ["ngrok-auth"],
            ngrok_domain="shop-static.ngrok-free.app",
            tunnel_token=TUNNEL_TOKEN,
            require_two_layer=True,
        )
        self.assertEqual(url, "https://shop-static.ngrok-free.app")
        self.assertEqual(len(fake.connect_calls), 1)
        _, _, kwargs = fake.connect_calls[0]
        self.assertEqual(kwargs["domain"], "shop-static.ngrok-free.app")
        policy = kwargs["traffic_policy"]
        expr = policy["on_http_request"][0]["expressions"][0]
        self.assertIn("x-retailops-tunnel-token", expr)
        self.assertIn(TUNNEL_TOKEN, expr)
        self.assertEqual(policy["on_http_request"][0]["actions"][0]["config"]["status_code"], 403)

    def test_gguf_notebook_is_marked_non_production_and_refuses_default_execution(self):
        src = (ROOT / "notebooks" / "colab_llama_server_gguf.py").read_text(encoding="utf-8")
        self.assertIn("NON_PRODUCTION_ONLY = True", src)
        self.assertIn("KHÔNG DÙNG TRÊN PRODUCTION", src)

    def test_app_sends_both_headers_reads_secret_files_and_redacts_secrets_in_401_403_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "api_key.secret"
            tun_file = Path(tmp) / "tunnel_token.secret"
            key_file.write_text(FIXTURE_KEY + "\n", encoding="utf-8")
            tun_file.write_text(TUNNEL_TOKEN + "\n", encoding="utf-8")

            env = {
                "RETAILOPS_PUBLIC_ORIGIN": "https://retailops.example.com",
                "RETAILOPS_PUBLIC_INVITE_TOKEN": "invite_" + "x" * 36,
                "RETAILOPS_API_ENABLED": "true",
                "RETAILOPS_API_ENDPOINT": FIXTURE_ENDPOINT,
                "RETAILOPS_API_MODEL": FIXTURE_MODEL,
                "RETAILOPS_API_KEY_FILE": str(key_file),
                "RETAILOPS_API_TUNNEL_TOKEN_FILE": str(tun_file),
            }
            settings = Settings.from_environment("public", environ=env)
            self.assertNotIn(FIXTURE_KEY, repr(settings))
            self.assertNotIn(TUNNEL_TOKEN, repr(settings))
            gateways = build_gateways(settings)
            adapter = gateways.api
            self.assertIsNotNone(adapter)

            seen_requests = []

            class FakeResponse(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    self.close()

            def fake_open(request, timeout=0):
                seen_requests.append(dict(request.header_items()))
                return FakeResponse(json.dumps(chat_reply("Xin chào")).encode("utf-8"))

            turn_adapter = adapter.for_turn()
            with patch.object(turn_adapter._opener, "open", side_effect=fake_open):
                res = turn_adapter.chat([{"role": "user", "content": "alo"}], False, 5)
            self.assertEqual(res["message"]["content"], "Xin chào")
            sent_headers = {k.lower(): v for k, v in seen_requests[0].items()}
            self.assertEqual(sent_headers["authorization"], f"Bearer {FIXTURE_KEY}")
            self.assertEqual(sent_headers[TUNNEL_TOKEN_HEADER.lower()], TUNNEL_TOKEN)

            # Both 401 and 403 record clear diagnostics in trace.model_errors without leaking secrets
            store = BusinessStore(Path(tmp) / "business.sqlite3")
            store.seed()
            app = Application(store, {}, api_infer=adapter, api_daily_limit=50)
            cid = app.new_conversation("C-001", {"provider_id": "api"})["conversation_id"]

            for status_code, expected_layer in ((401, "api_key"), (403, "tunnel_policy_or_forbidden")):
                leaky_body = {
                    "error": (
                        f"Auth rejected ({status_code}): Authorization: Bearer {FIXTURE_KEY} "
                        f"X-RetailOps-Tunnel-Token: {TUNNEL_TOKEN} at {FIXTURE_ENDPOINT}"
                    )
                }
                err_obj = http_error(status_code, leaky_body)
                with patch("urllib.request.OpenerDirector.open", side_effect=err_obj):
                    with self.assertRaises(ApiError) as caught:
                        app.chat(
                            "C-001",
                            {"conversation_id": cid, "text": "tra cứu đơn O-101", "request_id": f"req_{status_code}_" + "a" * 16},
                        )
                self.assertEqual(caught.exception.status, 503)
                self.assertEqual(caught.exception.code, "api_auth_failed")
                model_errors = caught.exception.trace.get("model_errors") or []
                self.assertEqual(len(model_errors), 1)
                self.assertEqual(model_errors[0]["http_status"], status_code)
                self.assertEqual(model_errors[0]["code"], "api_auth_failed")
                self.assertEqual(model_errors[0]["auth_layer"], expected_layer)
                serialized = json.dumps(caught.exception.trace, ensure_ascii=False)
                self.assertNotIn(FIXTURE_KEY, serialized)
                self.assertNotIn(TUNNEL_TOKEN, serialized)
                self.assertNotIn(FIXTURE_ENDPOINT, serialized)

            # api_from_environment also honors RETAILOPS_API_KEY_FILE and RETAILOPS_API_TUNNEL_TOKEN_FILE
            with patch.dict(os.environ, env, clear=True):
                env_agent = api_from_environment()
                self.assertEqual(env_agent.tunnel_token, TUNNEL_TOKEN)
                self.assertEqual(env_agent.key, FIXTURE_KEY)


if __name__ == "__main__":
    unittest.main()
