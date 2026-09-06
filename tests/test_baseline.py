import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import asdict

from retailops_baseline import (
    SCHEMA, SYSTEM, LocalOllama, ModelConfig, Runner, Store,
    canonical, digest, evaluate, request_key, validate_decision,
)

GOOD = {"action": "lookup_order", "order_id": "O-101", "cancel_reason": None}


class FakeGateway:
    def __init__(self, response=None):
        self.config = ModelConfig()
        self.identity = {"name": self.config.model, "digest": "unit-test-only"}
        self.calls = 0
        self.response = response

    def inspect(self):
        return self.identity

    def generate(self, text):
        self.calls += 1
        return self.response if self.response is not None else {
            "message": {"content": json.dumps(GOOD)}, "done_reason": "stop",
            "prompt_eval_count": 100, "eval_count": 25,
        }


class ValidationTests(unittest.TestCase):
    def test_valid_lookup(self):
        self.assertEqual(validate_decision(GOOD), GOOD)

    def test_valid_cancel(self):
        validate_decision({"action": "cancel_order", "order_id": "O-1", "cancel_reason": "ordered_by_mistake"})

    def test_valid_clarification(self):
        validate_decision({"action": "clarify", "order_id": None, "cancel_reason": None})

    def test_valid_unsupported(self):
        validate_decision({"action": "unsupported", "order_id": None, "cancel_reason": None})

    def test_missing_key(self):
        with self.assertRaises(ValueError):
            validate_decision({"action": "lookup_order"})

    def test_extra_key(self):
        with self.assertRaises(ValueError):
            validate_decision({**GOOD, "execute_now": True})

    def test_bad_action(self):
        with self.assertRaises(ValueError):
            validate_decision({**GOOD, "action": "refund"})

    def test_cancel_without_reason(self):
        with self.assertRaises(ValueError):
            validate_decision({**GOOD, "action": "cancel_order"})

    def test_id_types(self):
        for oid in [True, 17, [], "DROP TABLE orders", "O 101"]:
            with self.subTest(oid=oid), self.assertRaises(ValueError):
                validate_decision({**GOOD, "order_id": oid})

    def test_unsupported_no_attached_id(self):
        with self.assertRaises(ValueError):
            validate_decision({**GOOD, "action": "unsupported"})


class CacheKeyTests(unittest.TestCase):
    def setUp(self):
        self.config = asdict(ModelConfig())
        self.identity = {"digest": "model-a", "ollama_version": "test-version"}

    def key(self, **changes):
        args = {"config": self.config, "identity": self.identity, "scope": "scope-a", "text": "hello"}
        args.update(changes)
        return request_key(**args)

    def test_same_input_same_key(self):
        self.assertEqual(self.key(), self.key())

    def test_scope_isolation(self):
        self.assertNotEqual(self.key(), self.key(scope="scope-b"))

    def test_model_version_isolation(self):
        self.assertNotEqual(self.key(), self.key(identity={"digest": "model-b"}))

    def test_decoding_config_isolation(self):
        self.assertNotEqual(self.key(), self.key(config={**self.config, "temperature": .7}))

    def test_prompt_invalidation(self):
        self.assertNotEqual(self.key(), self.key(prompt=SYSTEM + " changed"))

    def test_schema_invalidation(self):
        self.assertNotEqual(self.key(), self.key(schema={**SCHEMA, "title": "changed"}))

    def test_no_semantic_normalization(self):
        self.assertNotEqual(self.key(), self.key(text="Hello"))

    def test_stable_dictionary_serialization(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))


class StorageRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "events.sqlite3")

    def test_ttl_expiry(self):
        self.store.put("key", GOOD, ttl_s=10, now=100)
        self.assertEqual(self.store.get("key", now=109), GOOD)
        self.assertIsNone(self.store.get("key", now=110))

    def test_cache_default_off(self):
        model = FakeGateway()
        runner = Runner(model, self.store)
        runner.infer("one")
        runner.infer("one")
        self.assertEqual(model.calls, 2)

    def test_opt_in_cache_hit_no_generation(self):
        model = FakeGateway()
        runner = Runner(model, self.store)
        runner.infer("one", cache=True)
        second = runner.infer("one", cache=True)
        self.assertEqual(model.calls, 1)
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["generated_tokens"], 0)

    def test_cache_scope_isolation_in_runner(self):
        model = FakeGateway()
        runner = Runner(model, self.store)
        runner.infer("one", cache=True, scope="customer-a")
        runner.infer("one", cache=True, scope="customer-b")
        self.assertEqual(model.calls, 2)

    def test_invalid_output_not_cached(self):
        model = FakeGateway({"message": {"content": "not json"}})
        runner = Runner(model, self.store)
        self.assertFalse(runner.infer("one", cache=True)["valid"])
        self.assertFalse(runner.infer("one", cache=True)["valid"])
        self.assertEqual(model.calls, 2)

    def test_truncated_output_rejected(self):
        model = FakeGateway({"message": {"content": json.dumps(GOOD)}, "done_reason": "length"})
        result = Runner(model, self.store).infer("one")
        self.assertFalse(result["valid"])
        self.assertIn("Truncated", result["error"])

    def test_eval_bypasses_cache_each_repeat(self):
        model = FakeGateway()
        runner = Runner(model, self.store)
        path = self.path / "cases.jsonl"
        path.write_text(canonical({"id": "unit", "category": "lookup", "text": "one", "expected": GOOD}) + "\n", encoding="utf-8")
        summary = evaluate(runner, path, repeats=2)
        self.assertEqual(model.calls, 2)
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["intent_slot_exact_match"], 1.0)

    def test_remote_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            LocalOllama(ModelConfig(base_url="https://example.com"))

    def test_cloud_tag_rejected(self):
        with self.assertRaises(ValueError):
            LocalOllama(ModelConfig(model="qwen3.5:cloud"))

    def test_synthetic_cases_well_formed(self):
        path = Path(__file__).resolve().parents[1] / "data" / "smoke.jsonl"
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({x["id"] for x in cases}), 24)
        for case in cases:
            validate_decision(case["expected"])
            self.assertEqual(case["split"], "smoke_only")


if __name__ == "__main__":
    unittest.main()
