"""Unit tests for Ops Console evaluation importer preserving 0.0 inference latency (F09 / AC-10)."""
import json
import tempfile
import unittest
from pathlib import Path

from opsconsole.evaluation import import_benchmark


class OpsConsoleImporterTests(unittest.TestCase):
    def test_importer_preserves_zero_inference_latency(self):
        """Canonical test name matching AC-10 specification."""
        doc = {
            "provider": "custom",
            "model": "qwen2.5:7b-instruct",
            "dataset": "test_dataset.jsonl",
            "cases": [
                {
                    "id": "case_cache_hit",
                    "category": "faq_greeting",
                    "passed": True,
                    "status": 200,
                    "trace": {
                        "latency_ms": 12.5,
                        "queue_wait_ms": 0.0,
                        "provider_inference_ms": 0.0,  # Exact 0.0 for cache hit
                        "model_calls": 0,
                        "model_responses": 0,
                    },
                },
                {
                    "id": "case_model_turn",
                    "category": "order_lookup",
                    "passed": True,
                    "status": 200,
                    "trace": {
                        "latency_ms": 150.0,
                        "queue_wait_ms": 10.0,
                        "provider_inference_ms": 135.0,
                        "model_calls": 1,
                        "model_responses": 1,
                    },
                },
                {
                    "id": "case_no_inference_telemetry",
                    "category": "legacy_case",
                    "passed": True,
                    "status": 200,
                    "trace": {
                        "latency_ms": 80.0,
                    },
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(doc, f)
            tmp_path = f.name

        try:
            report = import_benchmark(tmp_path)
            case_results = {c["id"]: c for c in report["cases"]}

            # 1. Cache hit turn preserves 0.0
            cache_case = case_results["case_cache_hit"]
            self.assertEqual(cache_case["trace"]["provider_inference_ms"], 0.0)
            self.assertEqual(cache_case["trace"]["latency_ms"], 12.5)

            # 2. Model turn preserves measured provider_inference_ms
            model_case = case_results["case_model_turn"]
            self.assertEqual(model_case["trace"]["provider_inference_ms"], 135.0)
            self.assertEqual(model_case["trace"]["queue_wait_ms"], 10.0)

            # 3. Missing provider_inference_ms falls back to latency_ms
            legacy_case = case_results["case_no_inference_telemetry"]
            self.assertEqual(legacy_case["trace"]["provider_inference_ms"], 80.0)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
