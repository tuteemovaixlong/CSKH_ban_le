"""Tests for CanonicalBundleWriter, CanonicalBundleValidator, joins, and checksums."""

from pathlib import Path
import json
import shutil
import tempfile
import unittest

from evals.harness.constants import (
    CANONICAL_ARTIFACT_FILES,
    PROTOCOL_VERSION,
    SCHEMA_VERSION_ATTEMPT,
    SCHEMA_VERSION_ERROR,
    SCHEMA_VERSION_GRADING,
    SCHEMA_VERSION_MANIFEST,
    SCHEMA_VERSION_RETRIEVAL,
    SYSTEM_BASELINE_COMMIT_SHA,
)
from evals.harness.runner import Phase4MockRunner
from evals.harness.validator import CanonicalBundleValidator, recompute_aggregate_from_raw
from evals.harness.writer import CanonicalBundleWriter


class TestWriterAndValidator(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="phase4_test_bundle_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mock_runner_produces_valid_bundle(self):
        runner = Phase4MockRunner(
            run_id="run_valid_test",
            output_dir=self.test_dir,
            cache_mode="answer_cache_off",
        )
        runner.run(max_cases=5)

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertTrue(report.is_valid, f"Validation failed: {report.errors}")
        self.assertEqual(report.logical_case_count, 5)
        self.assertGreaterEqual(report.attempt_count, 5)

        # Check all 7 canonical files are present
        for fname in CANONICAL_ARTIFACT_FILES:
            self.assertTrue((self.test_dir / fname).is_file(), f"Missing file: {fname}")

    def test_checksum_corruption_detected(self):
        runner = Phase4MockRunner(run_id="run_corrupt_test", output_dir=self.test_dir)
        runner.run(max_cases=3)

        # Corrupt attempts.jsonl by modifying a line
        att_path = self.test_dir / "attempts.jsonl"
        with open(att_path, "a", encoding="utf-8") as f:
            f.write("\n")

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Checksum mismatch for attempts.jsonl" in e for e in report.errors))

    def test_orphan_grading_attempt_id_detected(self):
        runner = Phase4MockRunner(run_id="run_orphan_test", output_dir=self.test_dir)
        runner.run(max_cases=3)

        # Append an orphan grading record that references a non-existent attempt_id
        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])
        orphan_gr = dict(first_gr, grading_id="gr_orphan_999", graded_attempt_id="att_nonexistent_999")

        with open(gr_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(orphan_gr) + "\n")

        # Re-write checksums so only the join error is tested
        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("not found in attempts.jsonl" in e for e in report.errors))

    def test_duplicate_attempt_id_detected(self):
        runner = Phase4MockRunner(run_id="run_dup_test", output_dir=self.test_dir)
        runner.run(max_cases=3)

        att_path = self.test_dir / "attempts.jsonl"
        lines = att_path.read_text(encoding="utf-8").splitlines()
        first_att = json.loads(lines[0])
        dup_att = dict(first_att, record_id="rec_dup_999")

        with open(att_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dup_att) + "\n")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Duplicate attempt_id" in e for e in report.errors))

    def test_aggregate_recomputation_mismatch_detected(self):
        runner = Phase4MockRunner(run_id="run_mismatch_test", output_dir=self.test_dir)
        runner.run(max_cases=3)

        # Tamper with aggregate.json
        agg_path = self.test_dir / "aggregate.json"
        agg_data = json.loads(agg_path.read_text(encoding="utf-8"))
        agg_data["n_total"] = 999  # deliberate falsification

        agg_path.write_text(json.dumps(agg_data, indent=2) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("aggregate.json n_total mismatch" in e for e in report.errors))

    def test_r12_join_provenance_tampering(self):
        """Mutation test: changing run_id, case_id, or logical_request_id must invalidate bundle."""
        runner = Phase4MockRunner(run_id="run_join_prov", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])

        # Tamper case_id of grading record
        tampered_gr = dict(first_gr, case_id="tampered_case_id")
        lines[0] = json.dumps(tampered_gr)
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("case_id 'tampered_case_id' !=" in e for e in report.errors))

    def test_r12_frozen_benchmark_hash_mismatch(self):
        """Mutation test: tampered dataset_sha256 in manifest must be rejected."""
        runner = Phase4MockRunner(run_id="run_hash_mismatch", output_dir=self.test_dir)
        runner.run(max_cases=2)

        man_path = self.test_dir / "manifest.json"
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
        manifest["dataset_sha256"] = "f" * 64
        man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("dataset_sha256 mismatch" in e for e in report.errors))

    def test_r12_duplicate_record_id_detected(self):
        """Duplicate record_id in different files must be rejected."""
        runner = Phase4MockRunner(run_id="run_dup_rec", output_dir=self.test_dir)
        runner.run(max_cases=2)

        # Force identical record_id into grading.jsonl that already exists in attempts.jsonl
        att_path = self.test_dir / "attempts.jsonl"
        first_att = json.loads(att_path.read_text(encoding="utf-8").splitlines()[0])
        existing_rec_id = first_att["record_id"]

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])
        first_gr["record_id"] = existing_rec_id
        lines[0] = json.dumps(first_gr)
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any(f"Duplicate record_id '{existing_rec_id}'" in e for e in report.errors))

    def test_r12_checksums_rejects_non_canonical_file(self):
        """checksums.sha256 with extra or invalid entry must be rejected."""
        runner = Phase4MockRunner(run_id="run_bad_chk", output_dir=self.test_dir)
        runner.run(max_cases=2)

        chk_path = self.test_dir / "checksums.sha256"
        with open(chk_path, "a", encoding="utf-8") as f:
            f.write(f"{'a' * 64}  disallowed_extra.txt\n")

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Non-canonical or disallowed entry 'disallowed_extra.txt'" in e for e in report.errors))


if __name__ == "__main__":
    unittest.main()
