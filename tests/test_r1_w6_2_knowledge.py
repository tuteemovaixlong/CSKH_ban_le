"""W6.2-D3/D5: immutable policy corpus, prune and real pgvector retrieval."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from retailops.business import eligibility
from retailops.knowledge import cli
from retailops.knowledge.chunking import read_directory
from retailops.knowledge.repository import KnowledgeRepository
from retailops.knowledge.tool import KnowledgeTool
from tests._w6_1b_2_pg_base import RealPostgresW61b2Base, pg_test_enabled

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "data/knowledge"
POLICY_FILES = {"cancellation.md", "delivery_inspection.md", "faq.md", "invoice_vat.md", "payments.md", "policy_mega_sale_delay_voucher.md", "policy_shipper_complaint.md", "policy_size_exchange_twoway.md", "policy_warranty_exchange_1to1.md", "refunds.md", "returns.md", "shipping.md", "shipping_fees.md", "store_hours_contact.md"}
RETRIEVAL_CASES = [
    ("Tôi có quyền trả hàng không?", "returns.md"),
    ("áo chật quá muốn đổi size L được không", "policy_size_exchange_twoway.md"),
    ("bao lâu thì tôi nhận lại tiền hoàn", "refunds.md"),
    ("hoàn tiền mất bao lâu", "refunds.md"),
    ("phí ship bao nhiêu", "shipping_fees.md"),
    ("shop có xuất hóa đơn VAT không", "invoice_vat.md"),
    ("mấy giờ shop có nhân viên trực", "store_hours_contact.md"),
    ("giờ làm việc của shop", "store_hours_contact.md"),
    ("có được kiểm hàng trước khi nhận không", "delivery_inspection.md"),
    ("đồng kiểm khi nhận hàng", "delivery_inspection.md"),
    ("đơn giao trễ có được đền bù voucher không", "policy_mega_sale_delay_voucher.md"),
    ("shipper báo không liên lạc được nhưng tôi ở nhà", "policy_shipper_complaint.md"),
    ("sản phẩm bị bung chỉ có được bảo hành không", "policy_warranty_exchange_1to1.md"),
    ("đơn đang giao có hủy được không", "cancellation.md"),
    ("thanh toán bằng ví điện tử được không", "payments.md"),
    ("bao lâu thì giao hàng tới", "shipping.md"),
    ("trợ lý làm được gì", "faq.md"),
    ("shop có phải bồi thường không", "faq.md"),
]


class KnowledgeContractTests(unittest.TestCase):
    def test_cli_prune_and_list_arguments(self):
        parser = argparse.ArgumentParser()
        cli.add_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["knowledge", "ingest", "--tenant", "isolated", "--prune"])
        self.assertTrue(args.prune)
        self.assertEqual(parser.parse_args(["knowledge", "list", "--tenant", "isolated"]).knowledge_action, "list")

    def test_policy_corpus(self):
        self.assertEqual({p.name for p in POLICIES.iterdir() if p.is_file()}, POLICY_FILES)
        for path in sorted(POLICIES.iterdir()):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertRegex(text, re.compile(r"^# .+", re.MULTILINE))
                self.assertIn("Tài liệu giả lập của RetailOps Demo", text)
                for obsolete in ("Tự động phát hành", "Tạo Phiếu", "Phiếu Đề Xuất", "kích hoạt lệnh khiếu nại", "Họ tên, Số điện thoại", "SPX", "GHTK", "Kho BN"):
                    self.assertNotIn(obsolete.casefold(), text.casefold())

    def test_policy_numbers_match_server_constants(self):
        for filename, value, unit in (
            ("returns.md", eligibility.RETURN_WINDOW_DAYS, "ngày"),
            ("policy_size_exchange_twoway.md", eligibility.SIZE_EXCHANGE_WINDOW_DAYS, "ngày"),
            ("policy_warranty_exchange_1to1.md", eligibility.DEFAULT_WARRANTY_DAYS, "ngày"),
            ("policy_mega_sale_delay_voucher.md", eligibility.LATE_DELIVERY_COMPENSATION_THRESHOLD_HOURS, "giờ"),
            ("policy_mega_sale_delay_voucher.md", f"{eligibility.LATE_DELIVERY_COMPENSATION_VOUCHER_VND:,}".replace(",", "."), "VNĐ"),
        ):
            with self.subTest(file=filename, value=value):
                self.assertIn(f"{value} {unit}", (POLICIES / filename).read_text(encoding="utf-8"))


@unittest.skipUnless(pg_test_enabled(), "Real PostgreSQL W6.2 tests run in PR CI")
class KnowledgePostgresW62Tests(RealPostgresW61b2Base):
    def command(self, *args):
        env = {**os.environ, "RETAILOPS_STORAGE_BACKEND": "postgresql", "RETAILOPS_DATABASE_URL": self.dsn}
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "retailops", "knowledge", *args, "--tenant", "shop-demo"], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_prune_renamed_document_list_search_and_idempotency(self):
        first, second = self.root / "A", self.root / "B"
        first.mkdir(); second.mkdir()
        for directory, files in ((first, ("keep.md", "old.md", "removed.md")), (second, ("keep.md", "renamed.md"))):
            for name in files:
                content = "# Synthetic policy\n\n" + ("zebracobalt discontinued policy" if name in ("old.md", "removed.md") else "size exchange policy")
                (directory / name).write_text(content, encoding="utf-8")
        self.assertEqual(self.command("ingest", "--path", str(first))["documents"], 3)
        repo = KnowledgeRepository(self.store)
        before = {r["source_key"]: r for r in repo.list_documents()}
        self.assertEqual(self.command("ingest", "--path", str(second))["deactivated"], [])
        self.assertTrue(all(r["active"] == 1 for r in repo.list_documents()))
        # Use the fixture's unique term: shared words such as "policy" legitimately match keep.md too.
        self.assertEqual({r["source_key"] for r in KnowledgeTool(self.store).search("zebracobalt")["results"]}, {"old.md", "removed.md"})
        self.assertEqual(self.command("ingest", "--path", str(second), "--prune")["deactivated"], ["old.md", "removed.md"])
        listed = self.command("list")["documents"]
        self.assertEqual(len(listed), 4)
        for row in listed:
            self.assertTrue({"source_key", "title", "active", "checksum", "chunks", "updated_at"} <= row.keys())
            if row["source_key"] in ("old.md", "removed.md"):
                self.assertEqual(row["active"], 0)
                self.assertGreater(row["updated_at"], before[row["source_key"]]["updated_at"])
                self.assertEqual(row["checksum"], before[row["source_key"]]["checksum"])
                self.assertGreater(row["chunks"], 0)
        self.assertTrue({r["source_key"] for r in repo.search("zebracobalt discontinued policy")} <= {"keep.md", "renamed.md"})
        self.assertEqual(KnowledgeTool(self.store).search("zebracobalt")["results"], [])
        self.assertEqual(self.command("ingest", "--path", str(second), "--prune")["deactivated"], [])
        repo.ingest(read_directory(first))
        self.assertTrue(all(r["active"] == 1 for r in repo.list_documents()))

    def test_owner_18_queries_through_knowledge_tool(self):
        self.assertEqual(KnowledgeRepository(self.store).ingest(read_directory(POLICIES))["documents"], 14)
        for number, (query, expected) in enumerate(RETRIEVAL_CASES, 1):
            with self.subTest(number=number, query=query):
                result = KnowledgeTool(self.store).search(query)
                keys = [r["source_key"] for r in result.get("results", [])]
                print("W62_RETRIEVAL", json.dumps({"number": number, "query": query, "expected": expected, "returned": keys}, ensure_ascii=False))
                self.assertIn(expected, keys, json.dumps(result, ensure_ascii=False))
