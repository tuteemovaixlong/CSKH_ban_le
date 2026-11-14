"""Offline contracts for W6.3.5 owner decisions D1-D3."""
import unittest
import re
from pathlib import Path

from agent_protocol import SYSTEM, TOOLS, ProtocolError, agent_system, validate_messages, validate_tool


class HumanSupportPromptTests(unittest.TestCase):
    def test_staff_only_requests_transfer_in_same_turn(self):
        description = next(t['function']['description'] for t in TOOLS
                           if t['function']['name'] == 'request_human_support')
        for phrase in ('Staff-only work: call request_human_support this turn without asking; say transferred.',):
            with self.subTest(source='SYSTEM', phrase=phrase):
                self.assertTrue(phrase in SYSTEM, f'SYSTEM missing: {phrase}')
        for label, text in [('tool description', description)]:
            for phrase in (
                'in the same turn, without asking first',
                "changing an order's delivery address or recipient",
                'issuing or correcting a VAT invoice',
                "disputing a carrier's false failed-delivery report",
                'Then tell the customer the case has been transferred',
                'Questions that only ask for information',
                'who issues invoices, staff hours or fees',
                'are not requests for a human',
            ):
                with self.subTest(source=label, phrase=phrase):
                    self.assertTrue(phrase in text, f'{label} missing: {phrase}')
        self.assertIn('when user requests or on severe complaint', description)

    def test_shipping_offer_and_reason_validation_stay_intact(self):
        self.assertTrue("when an order is in 'shipping' status, explain self-service "
                        'cancellation is unavailable and offer transfer to human support.' in SYSTEM)
        self.assertEqual(validate_tool('request_human_support', {'reason': 'x' * 1000}),
                         {'reason': 'x' * 1000})
        for args in ({'reason': ''}, {'reason': 'x' * 1001}, {'reason': 'help', 'extra': True}):
            with self.subTest(args_length=len(args.get('reason', ''))):
                with self.assertRaises(ProtocolError):
                    validate_tool('request_human_support', args)


class OpenOrderRequestPromptTests(unittest.TestCase):
    def test_one_open_request_per_order_and_tool_conflict(self):
        for phrase in (
            'One open cancel/return/exchange per order',
            'if two, explain and ask which',
            'If tool reports open, say so; no second',
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in SYSTEM, f'SYSTEM missing: {phrase}')

    def test_new_rules_fit_existing_limit_with_longest_focus(self):
        focused = agent_system({'order_id': 'O-' + '9' * 62, 'product_id': 'P-' + '9' * 62})
        self.assertLessEqual(len(focused.strip()), 6400)
        validate_messages([{'role': 'system', 'content': focused}, {'role': 'user', 'content': 'đơn này'}])


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / '.github').is_dir(),
                     'repository workflow files are not shipped in the image; checked on the source tree')
class WorkflowTimeoutTests(unittest.TestCase):
    def test_deploy_and_offline_timeouts(self):
        root = ROOT
        for filename, job, minutes in (
            ('deploy-ec2.yml', 'deploy', 40),
            ('ci.yml', 'offline', 30),
        ):
            with self.subTest(workflow=filename, job=job):
                text = (root / '.github' / 'workflows' / filename).read_text(encoding='utf-8')
                block = re.search(rf'^  {job}:\n(.*?)(?=^  [\w-]+:|\Z)',
                                  text, re.MULTILINE | re.DOTALL)
                self.assertIsNotNone(block, f'job {job} missing')
                self.assertRegex(block.group(1), rf'(?m)^    timeout-minutes: {minutes}$')


if __name__ == '__main__':
    unittest.main()
