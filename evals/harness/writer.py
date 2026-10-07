"""Canonical writer and checksum calculator for Phase 4 artifact bundles.

Normative reference:
- docs/phase4/PHASE_4_RESULTS_SCHEMA.md
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import hashlib
import json

from evals.harness.constants import CANONICAL_ARTIFACT_FILES
from evals.harness.schema import (
    validate_aggregate,
    validate_attempt_record,
    validate_error_record,
    validate_grading_record,
    validate_manifest,
    validate_retrieval_record,
)


def compute_sha256(path: Path) -> str:
    """Computes SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class CanonicalBundleWriter:
    """Writes Phase 4 canonical evaluation artifacts with strict schema compliance."""

    def __init__(self, run_dir: Path, validate_on_write: bool = True):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.validate_on_write = validate_on_write

        self.manifest_path = self.run_dir / "manifest.json"
        self.attempts_path = self.run_dir / "attempts.jsonl"
        self.grading_path = self.run_dir / "grading.jsonl"
        self.retrieval_path = self.run_dir / "retrieval.jsonl"
        self.errors_path = self.run_dir / "errors.jsonl"
        self.aggregate_path = self.run_dir / "aggregate.json"
        self.checksums_path = self.run_dir / "checksums.sha256"

        # Ensure canonical JSONL files exist even when 0 records are appended
        for p in (self.attempts_path, self.grading_path, self.retrieval_path, self.errors_path):
            if not p.exists():
                p.touch()

    def write_manifest(self, manifest_data: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_manifest(manifest_data)
        self.manifest_path.write_text(
            json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )

    def append_attempt(self, attempt_record: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_attempt_record(attempt_record)
        with open(self.attempts_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(attempt_record, ensure_ascii=False) + "\n")

    def append_grading(self, grading_record: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_grading_record(grading_record)
        with open(self.grading_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(grading_record, ensure_ascii=False) + "\n")

    def append_retrieval(self, retrieval_record: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_retrieval_record(retrieval_record)
        with open(self.retrieval_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(retrieval_record, ensure_ascii=False) + "\n")

    def append_error(self, error_record: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_error_record(error_record)
        with open(self.errors_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(error_record, ensure_ascii=False) + "\n")

    def write_aggregate(self, aggregate_data: Dict[str, Any]) -> None:
        if self.validate_on_write:
            validate_aggregate(aggregate_data)
        self.aggregate_path.write_text(
            json.dumps(aggregate_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )

    def write_checksums(self) -> Dict[str, str]:
        """Calculates and writes checksums.sha256 for all 6 bundle artifacts.

        Does not self-reference checksums.sha256.
        """
        checksums: Dict[str, str] = {}
        target_files = [
            "manifest.json",
            "attempts.jsonl",
            "grading.jsonl",
            "retrieval.jsonl",
            "errors.jsonl",
            "aggregate.json",
        ]

        lines = []
        for filename in target_files:
            file_path = self.run_dir / filename
            if file_path.is_file():
                sha = compute_sha256(file_path)
                checksums[filename] = sha
                lines.append(f"{sha}  {filename}")
            else:
                # Ensure missing canonical file is flagged
                raise FileNotFoundError(f"Cannot generate checksums: missing canonical artifact {file_path}")

        self.checksums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return checksums
