"""Kiểm thử tích hợp W6.1b-1 giữa marketplace_sim và RetailOps (bỏ qua trong production image)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from retailops.integration.contract import (
    ALL_EVENT_TYPES,
    ContractValidationError,
    INBOUND_EVENT_TYPES,
    W6_1B_1_SUPPORTED_EVENT_TYPES,
    validate_event_v2,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_MARKETPLACE_SIM = (ROOT / "marketplace_sim").is_dir()

if HAS_MARKETPLACE_SIM:
    from marketplace_sim.simulator import MarketplaceSimulator
    from marketplace_sim.stories import STORY_NAMES


@unittest.skipUnless(
    HAS_MARKETPLACE_SIM,
    "marketplace_sim không đóng gói vào production image.",
)
class MarketplaceSimContractBridgeTests(unittest.TestCase):
    """W6.1b-1 Item 1: mọi ví dụ và file export của sàn ảo đều qua bộ kiểm v2 của RetailOps."""

    def test_all_marketplace_sim_examples_pass_retailops_v2_validator(self) -> None:
        examples_dir = ROOT / "marketplace_sim" / "examples"
        seen: set[str] = set()
        for path in sorted(examples_dir.glob("*.json")):
            ev = json.loads(path.read_text(encoding="utf-8"))
            etype = ev["event_type"]
            seen.add(etype)
            with self.subTest(file=path.name, event_type=etype):
                validated = validate_event_v2(copy.deepcopy(ev))
                self.assertEqual(validated["event_type"], etype)
                if etype in INBOUND_EVENT_TYPES:
                    validate_event_v2(copy.deepcopy(ev), allow_requests=False)
                else:
                    with self.assertRaises(ContractValidationError):
                        validate_event_v2(copy.deepcopy(ev), allow_requests=False)
        self.assertEqual(seen, set(ALL_EVENT_TYPES))

    def test_full_simulator_export_passes_retailops_v2_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_dir = Path(tmp) / "sim_store"
            sim = MarketplaceSimulator.initialize(store_dir, seed=20261108)
            sim.run_days(5)
            for story_name in STORY_NAMES:
                sim.insert_story(story_name)
            export_path = Path(tmp) / "exported.jsonl"
            count = sim.export_events(export_path)
            self.assertGreater(count, 50)
            lines = export_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), count)
            seen_types: set[str] = set()
            for line in lines:
                ev = json.loads(line)
                validated = validate_event_v2(ev, allow_requests=False)
                seen_types.add(validated["event_type"])
            # 7 loại sự kiện W6.1b-1 từ init + run + 13 story đều có mặt và vượt qua bộ kiểm
            self.assertEqual(seen_types, set(W6_1B_1_SUPPORTED_EVENT_TYPES))

            # Phát thêm voucher.issued qua ingest_voucher_requests để kiểm đủ cả 8 loại inbound
            req_example = json.loads(
                (ROOT / "marketplace_sim" / "examples" / "voucher.requested.json").read_text(
                    encoding="utf-8"
                )
            )
            req_jsonl = Path(tmp) / "voucher_requests.jsonl"
            req_jsonl.write_text(
                json.dumps(req_example, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            req_res = sim.ingest_voucher_requests(req_jsonl)
            self.assertEqual(req_res["issued"], 1)
            export_all_path = Path(tmp) / "exported_all_8.jsonl"
            count_all = sim.export_events(export_all_path)
            self.assertEqual(count_all, count + 1)
            seen_all_types: set[str] = set()
            for line in export_all_path.read_text(encoding="utf-8").splitlines():
                ev = json.loads(line)
                validated = validate_event_v2(ev, allow_requests=False)
                seen_all_types.add(validated["event_type"])
            self.assertEqual(seen_all_types, set(INBOUND_EVENT_TYPES))


if __name__ == "__main__":
    unittest.main()
