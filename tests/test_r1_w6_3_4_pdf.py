"""W6.3.4-D3: test the runner's bytes through the real PDF projection."""
import importlib.util
import re
import unittest

from retailops.business.evidence import project_pdf_for_model
from scripts import run_agent_scenarios as runner


def page_text(index):
    prefix = (f'Page {index} invoice (draft) \\ Latin-1 café\n'
              'www.thongtin-xacminh-401.com hoso-khach@retailops-archive.com\n'
              + 'W' * 85 + '\n')
    return prefix + ('alpha beta gamma delta ' * 30)[:500 - len(prefix)]


@unittest.skipUnless(importlib.util.find_spec('pypdfium2'), 'requires pypdfium2 (CI requirements-web.txt)')
class SyntheticPdfTests(unittest.TestCase):
    def assert_pages_visible(self, pages):
        raw = runner._make_text_pdf_bytes(pages)
        self.assertEqual(raw, runner._make_text_pdf_bytes(pages), 'identical input must produce identical bytes')
        projection = project_pdf_for_model(raw, include_pixels=False)
        self.assertEqual(projection['page_count'], len(pages))
        excerpt = projection['excerpt']
        for index, page in enumerate(pages, 1):
            with self.subTest(page=index):
                self.assertEqual(len(page), 500)
                actual = excerpt.split(f'[Trang {index}] ', 1)[1].split('[Trang ', 1)[0]
                self.assertEqual(' '.join(actual.split()), ' '.join(page.split()))
                self.assertIn('www.thongtin-xacminh-401.com', actual)
                self.assertIn('hoso-khach@retailops-archive.com', actual)

    def test_one_500_character_page(self):
        self.assert_pages_visible([page_text(1)])

    def test_three_500_character_pages(self):
        self.assert_pages_visible([page_text(i) for i in range(1, 4)])

    def test_s11_011_invoice_fields_reach_excerpt(self):
        case = next(c for c in runner.load_dataset('evals/suites/S11.jsonl') if c['id'].startswith('s11_011'))
        pages = case['case_setup']['customer_messages'][1]['attachment']['pages']
        excerpt = project_pdf_for_model(runner._make_text_pdf_bytes(pages), include_pixels=False)['excerpt']
        for text in ('0399887700', '0399887766', 'Sao Mai'):
            with self.subTest(text=text):
                self.assertIn(text, re.sub(r'\s+', ' ', excerpt))


if __name__ == '__main__':
    unittest.main()
