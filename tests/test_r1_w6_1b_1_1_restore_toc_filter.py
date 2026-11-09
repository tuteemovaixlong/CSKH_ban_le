"""Phase R1 W6.1b-1.1 Item 2: the documented pgvector restore TOC filter must drop the extension entries.

The sample lines are the exact `pg_restore --list` entries captured on production on 2026-11-09.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTGRESQL_DOC = ROOT / "docs" / "POSTGRESQL.md"

EXTENSION_LINES = [
    "10; 2615 16670 SCHEMA - retailops_extensions postgres",
    "2; 3079 16671 EXTENSION - vector ",
    "21791; 0 0 COMMENT - EXTENSION vector ",
]
KEPT_LINES = [
    "11; 2615 16700 SCHEMA - retailops_identity retailops",
    "12; 2615 16701 SCHEMA - tenant_8d1a38c0cbfe46829fb62bd9bb68c541 retailops",
    "305; 1259 16900 TABLE tenant_8d1a38c0cbfe46829fb62bd9bb68c541 knowledge_chunks retailops",
]


def _documented_pattern() -> str:
    text = POSTGRESQL_DOC.read_text(encoding="utf-8")
    matches = re.findall(r'grep -Ev "([^"]+)"', text)
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one `grep -Ev` TOC filter in docs/POSTGRESQL.md, found {len(matches)}")
    return matches[0]


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    return str(git_bash) if git_bash.is_file() else None


class RestoreTocFilterTests(unittest.TestCase):
    def test_documented_filter_drops_extension_entries_and_keeps_application_objects(self):
        pattern = _documented_pattern()
        compiled = re.compile(pattern)
        for line in EXTENSION_LINES:
            self.assertIsNotNone(compiled.search(line), f"filter must drop: {line!r}")
        for line in KEPT_LINES:
            self.assertIsNone(compiled.search(line), f"filter must keep: {line!r}")

    def test_documented_filter_behaves_the_same_under_grep_ere(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not available on this host")
        pattern = _documented_pattern()
        toc = "\n".join(EXTENSION_LINES + KEPT_LINES) + "\n"
        proc = subprocess.run(
            [bash, "-c", 'grep -Ev "$1"', "sh", pattern],
            input=toc,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.stdout.splitlines(), KEPT_LINES, proc.stderr)


if __name__ == "__main__":
    unittest.main()
