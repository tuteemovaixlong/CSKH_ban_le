"""Ghim SHA256 đầu ra sinh ca/phiếu SFT v1 cho W6.7.4."""
import hashlib
import tempfile
import unittest
from pathlib import Path

if not (Path(__file__).resolve().parents[1] / "scripts/sft_cases.py").is_file():
    raise unittest.SkipTest("Công cụ SFT không nằm trong gói Colab ứng dụng")

try:
    from scripts import sft_cases
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"Thiếu phụ thuộc sinh ca SFT: {exc}") from exc

CASES_SHA256 = "56d47a64908b37f2ec7ded513fca80ba1f81ce64f9ac2cbc74e064a24c44a11e"
BRIEFS_SHA256 = "ed8b290b9d251297fd2d7fa66d49cf16bfd10ac41013e09118dc4cbfd3fff3a4"


class SftCasesPinnedTests(unittest.TestCase):
    """Kiểm tra SHA256 của cases_sft_v1.jsonl và briefs_sft_v1.jsonl không đổi."""

    def test_generate_cases_and_briefs_sha256_pinned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sft_cases.generate_cases(root)
            cases_sha = hashlib.sha256((root / "cases_sft_v1.jsonl").read_bytes()).hexdigest()
            briefs_sha = hashlib.sha256((root / "briefs_sft_v1.jsonl").read_bytes()).hexdigest()
            self.assertEqual(cases_sha, CASES_SHA256)
            self.assertEqual(briefs_sha, BRIEFS_SHA256)


if __name__ == "__main__":
    unittest.main()
