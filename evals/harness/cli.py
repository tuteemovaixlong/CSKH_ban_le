"""Command-line interface for Phase 4 Scientific Evaluation Harness.

Commands:
- mock-run: Run offline mock benchmark emitting canonical bundle.
- validate: Validate an existing run bundle against Phase 4 schema.
- recompute: Recompute aggregate.json from raw records.
- sidecar-check: Check sidecar fixture integrity.
- qrels-check: Check Qrels dataset integrity.
"""

from pathlib import Path
from typing import List, Optional
import argparse
import json
import sys
import uuid

from evals.harness.grader import Phase4Grader
from evals.harness.qrels import QrelsManager
from evals.harness.runner import Phase4MockRunner
from evals.harness.sidecar import generate_benchmark_sidecar
from evals.harness.validator import CanonicalBundleValidator


def cmd_mock_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"mock_run_{uuid.uuid4().hex[:8]}"
    out_dir = Path(args.outdir) if args.outdir else Path("artifacts") / "phase4" / run_id
    runner = Phase4MockRunner(
        run_id=run_id,
        output_dir=out_dir,
        benchmark_path=Path(args.benchmark) if args.benchmark else None,
        cache_mode=args.cache_mode,
    )
    print(f"Executing Phase 4 mock-run (run_id={run_id}) into {out_dir}...")
    runner.run(max_cases=args.max_cases)
    print("Mock run complete. Validating output bundle...")
    val = CanonicalBundleValidator(out_dir)
    rep = val.validate()
    if rep.is_valid:
        print(f"SUCCESS: Run bundle is valid! (cases={rep.logical_case_count}, attempts={rep.attempt_count})")
        return 0
    else:
        print(f"FAIL: Bundle validation errors: {rep.errors}")
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: Directory not found: {run_dir}", file=sys.stderr)
        return 1
    val = CanonicalBundleValidator(run_dir)
    rep = val.validate()
    if rep.is_valid:
        print(f"VALID: Bundle '{rep.run_id}' in {run_dir} passed all Phase 4 checks!")
        print(f"  Attempts: {rep.attempt_count}, Gradings: {rep.grading_count}, Retrievals: {rep.retrieval_count}, Errors: {rep.error_count}")
        return 0
    else:
        print(f"INVALID: Bundle '{rep.run_id}' in {run_dir} failed validation:")
        for err in rep.errors:
            print(f"  - {err}")
        return 1


def cmd_recompute(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        return 1
    val = CanonicalBundleValidator(run_dir)
    rep = val.validate()
    if not rep.is_valid:
        print(f"ERROR: Bundle validation failed for '{run_dir}':", file=sys.stderr)
        for err in rep.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    if rep.recomputed_aggregate:
        print(json.dumps(rep.recomputed_aggregate, indent=2, ensure_ascii=False))
        return 0
    else:
        print(f"ERROR: Failed to recompute aggregate: {rep.errors}", file=sys.stderr)
        return 1


def cmd_sidecar_check(args: argparse.Namespace) -> int:
    dataset_path = Path(args.benchmark or "evals/scenarios/benchmark_250.jsonl")
    if not dataset_path.is_file():
        print(f"ERROR: Benchmark file not found: {dataset_path}", file=sys.stderr)
        return 1
    try:
        sidecar_dict, sha256 = generate_benchmark_sidecar(dataset_path)
        if not sidecar_dict or not sha256:
            print(f"ERROR: Benchmark sidecar is empty: {dataset_path}", file=sys.stderr)
            return 1
        print(f"SIDECAR_OK: cases={len(sidecar_dict)}, sha256={sha256}")
        return 0
    except Exception as exc:
        print(f"ERROR: Sidecar generation failed: {exc}", file=sys.stderr)
        return 1


def cmd_qrels_check(args: argparse.Namespace) -> int:
    qrels_path = Path(args.qrels) if args.qrels else Path("evals/qrels/policy_qrels_v1.json")
    if not qrels_path.is_file():
        print(f"ERROR: Qrels file not found: {qrels_path}", file=sys.stderr)
        return 1
    try:
        qm = QrelsManager(qrels_path)
        if not qm.entries or not qm.sha256:
            print(f"ERROR: Qrels entries empty or missing SHA-256: {qrels_path}", file=sys.stderr)
            return 1
        print(f"QRELS_OK: version={qm.version}, count={len(qm.entries)}, sha256={qm.sha256}")
        return 0
    except Exception as exc:
        print(f"ERROR: Qrels check failed: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4 Evaluation Harness CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # mock-run
    p_run = subparsers.add_parser("mock-run", help="Run offline mock benchmark and emit bundle")
    p_run.add_argument("--run-id", help="Explicit run ID")
    p_run.add_argument("--outdir", "--output-dir", dest="outdir", help="Output directory")
    p_run.add_argument("--benchmark", help="Benchmark JSONL file")
    p_run.add_argument("--max-cases", type=int, help="Limit number of cases")
    p_run.add_argument("--cache-mode", default="answer_cache_off", help="Cache mode (must be answer_cache_off for A0)")
    p_run.set_defaults(func=cmd_mock_run)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate an existing run bundle")
    p_val.add_argument("--run-dir", required=True, help="Path to run directory")
    p_val.set_defaults(func=cmd_validate)

    # recompute
    p_recomp = subparsers.add_parser("recompute", help="Recompute aggregate from raw records")
    p_recomp.add_argument("--run-dir", required=True, help="Path to run directory")
    p_recomp.set_defaults(func=cmd_recompute)

    # sidecar-check
    p_sidecar = subparsers.add_parser("sidecar-check", help="Check benchmark sidecar generation")
    p_sidecar.add_argument("--benchmark", help="Benchmark JSONL file")
    p_sidecar.set_defaults(func=cmd_sidecar_check)

    # qrels-check
    p_qrels = subparsers.add_parser("qrels-check", help="Check Qrels file integrity")
    p_qrels.add_argument("--qrels", help="Path to qrels JSON")
    p_qrels.set_defaults(func=cmd_qrels_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
