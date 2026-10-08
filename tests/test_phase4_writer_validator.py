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

    def test_h9_duplicate_unadjudicated_grading_rejected(self):
        """Mutation test for H9: duplicate unadjudicated gradings for same attempt must be rejected."""
        runner = Phase4MockRunner(run_id="run_dup_grade", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])

        # Create duplicate unadjudicated grading for the same graded_attempt_id
        dup_gr = dict(
            first_gr,
            record_id="rec_dup_gr_999",
            grading_id="gr_dup_999",
            decision="fail",
            adjudicated=False,
        )
        lines.append(json.dumps(dup_gr))
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("Multiple unadjudicated gradings" in e for e in report.errors))

    def test_h9_adjudication_precedence_and_aggregate_integrity(self):
        """Adjudication precedence: adjudicated grading supersedes initial unadjudicated grading."""
        runner = Phase4MockRunner(run_id="run_adj_prec", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])

        # Step 1: Initial unadjudicated grading is a fail
        first_gr["decision"] = "fail"
        lines[0] = json.dumps(first_gr)

        # Step 2: Add an adjudicated grading for the same attempt that overturns fail to pass
        adj_gr = dict(
            first_gr,
            record_id="rec_adj_001",
            grading_id="gr_adj_001",
            decision="pass",
            adjudicated=True,
        )
        lines.append(json.dumps(adj_gr))
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Re-sync aggregate.json using recompute_aggregate_from_raw
        man_path = self.test_dir / "manifest.json"
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
        attempts = [json.loads(l) for l in (self.test_dir / "attempts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        gradings = [json.loads(l) for l in (self.test_dir / "grading.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        errors = [json.loads(l) for l in (self.test_dir / "errors.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

        new_agg = recompute_aggregate_from_raw(manifest, attempts, gradings, errors)
        (self.test_dir / "aggregate.json").write_text(json.dumps(new_agg, indent=2) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertTrue(report.is_valid, f"Validation failed: {report.errors}")
        # Rate must not exceed 1.0, and the adjudicated pass must be counted
        self.assertEqual(report.recomputed_aggregate["quality_conditional"]["rate"], 1.0)
        self.assertLessEqual(report.recomputed_aggregate["quality_conditional"]["numerator"], 3)

        # Step 3: Now inject a second adjudicated grading -> must be rejected
        second_adj = dict(adj_gr, record_id="rec_adj_002", grading_id="gr_adj_002")
        with open(gr_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(second_adj) + "\n")
        writer.write_checksums()

        report2 = val.validate()
        self.assertFalse(report2.is_valid)
        self.assertTrue(any("Multiple adjudicated gradings" in e for e in report2.errors))

    def test_r12_error_ref_bidirectional_integrity(self):
        """Attempts error_ref and errors.jsonl error_id must be strictly bidirectional."""
        runner = Phase4MockRunner(run_id="run_err_ref_test", output_dir=self.test_dir)
        runner.run(max_cases=6)

        att_path = self.test_dir / "attempts.jsonl"
        lines = att_path.read_text(encoding="utf-8").splitlines()
        first_att = json.loads(lines[0])

        # 1. Non-existent error_ref on attempt
        tampered_att = dict(first_att, error_ref="err_nonexistent_999")
        lines[0] = json.dumps(tampered_att)
        att_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("references error_ref 'err_nonexistent_999' which does not exist" in e for e in report.errors))

        # 2. Mismatched error_ref on target attempt
        # Reset attempt line
        lines[0] = json.dumps(first_att)
        att_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Modify error record in errors.jsonl to point to first_att without first_att referencing it
        err_path = self.test_dir / "errors.jsonl"
        err_lines = err_path.read_text(encoding="utf-8").splitlines()
        if err_lines:
            first_err = json.loads(err_lines[0])
            first_err["attempt_id"] = first_att["attempt_id"]
            err_lines[0] = json.dumps(first_err)
            err_path.write_text("\n".join(err_lines) + "\n", encoding="utf-8")

            writer.write_checksums()
            report2 = val.validate()
            self.assertFalse(report2.is_valid)
            self.assertTrue(any("specifies attempt_id" in e and "but attempt's error_ref is" in e for e in report2.errors))

    def test_r12_qrels_sha_mismatch_detected(self):
        """retrieval.jsonl qrels_sha256 mismatch with manifest must be rejected."""
        runner = Phase4MockRunner(run_id="run_qrels_mismatch", output_dir=self.test_dir)
        runner.run(max_cases=3)

        ret_path = self.test_dir / "retrieval.jsonl"
        lines = ret_path.read_text(encoding="utf-8").splitlines()
        first_rt = json.loads(lines[0])
        first_rt["qrels_sha256"] = "e" * 64
        lines[0] = json.dumps(first_rt)
        ret_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("does not match manifest qrels_sha256" in e for e in report.errors))

    def test_f1_orphan_evidence_ref_detected(self):
        """Blocker F1: orphan evidence_ref referencing non-existent record must be rejected."""
        runner = Phase4MockRunner(run_id="run_orphan_ref", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])
        first_gr["evidence_refs"] = ["rec_nonexistent_999"]
        lines[0] = json.dumps(first_gr)
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("orphan ref" in e for e in report.errors))

    def test_f1_self_referential_evidence_ref_detected(self):
        """Blocker F1: grading record referencing its own record_id must be rejected."""
        runner = Phase4MockRunner(run_id="run_self_ref", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        lines = gr_path.read_text(encoding="utf-8").splitlines()
        first_gr = json.loads(lines[0])
        first_gr["evidence_refs"] = [first_gr["record_id"]]
        lines[0] = json.dumps(first_gr)
        gr_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("cannot reference itself" in e for e in report.errors))

    def test_f1_cross_case_evidence_ref_detected(self):
        """Blocker F1: grading record referencing a record from a different case_id must be rejected."""
        runner = Phase4MockRunner(run_id="run_cross_case_ref", output_dir=self.test_dir)
        runner.run(max_cases=3)

        gr_path = self.test_dir / "grading.jsonl"
        att_path = self.test_dir / "attempts.jsonl"
        gr_lines = gr_path.read_text(encoding="utf-8").splitlines()
        att_lines = att_path.read_text(encoding="utf-8").splitlines()

        first_gr = json.loads(gr_lines[0])
        second_att = json.loads(att_lines[1])
        self.assertNotEqual(first_gr["case_id"], second_att["case_id"])

        first_gr["evidence_refs"] = [second_att["record_id"]]
        gr_lines[0] = json.dumps(first_gr)
        gr_path.write_text("\n".join(gr_lines) + "\n", encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("case_id" in e and "!=" in e for e in report.errors))

    def test_f2_manifest_placeholder_sha_rejected(self):
        """Blocker F2: placeholder evaluation_harness_sha in manifest must be rejected by validator."""
        runner = Phase4MockRunner(run_id="run_placeholder_man", output_dir=self.test_dir)
        runner.run(max_cases=3)

        man_path = self.test_dir / "manifest.json"
        man = json.loads(man_path.read_text(encoding="utf-8"))
        man["evaluation_harness_sha"] = "1" * 40
        man["is_preflight"] = False
        man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")

        writer = CanonicalBundleWriter(self.test_dir)
        writer.write_checksums()

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("cannot be a placeholder" in e for e in report.errors))

    def test_f2_preflight_bundle_accepted_with_warning(self):
        """Blocker F2: is_preflight=True runner creates valid preflight bundle with warning."""
        runner = Phase4MockRunner(
            run_id="run_preflight_valid",
            output_dir=self.test_dir,
            is_preflight=True,
            harness_sha=None,
        )
        runner.run(max_cases=3)

        val = CanonicalBundleValidator(self.test_dir)
        report = val.validate()
        self.assertTrue(report.is_valid, f"Expected valid preflight bundle, got errors: {report.errors}")
        self.assertTrue(report.is_preflight)
        self.assertTrue(any("preflight" in w.lower() for w in report.warnings))


if __name__ == "__main__":
    unittest.main()
