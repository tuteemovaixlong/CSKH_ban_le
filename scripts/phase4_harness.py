#!/usr/bin/env python3
"""Entrypoint script for Phase 4 Scientific Evaluation Harness."""
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness.cli import main

if __name__ == "__main__":
    sys.exit(main())
