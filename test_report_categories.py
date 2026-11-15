"""Regression coverage for stale extracted tiers in Jason's Y4 report."""
import math
import unittest
from unittest.mock import patch
from evaluation_rules import attachment_level, normalize_bmi_level
from new_iteration.render_v2 import build_context


class ReportCategories(unittest.TestCase):
    def test_attachment_boundaries(self):
        for dimension, low, middle, high in [('信任',17,18,35), ('沟通',15,16,31), ('亲近',10,11,21)]:
            with self.subTest(dimension=dimension):
                self.assertEqual(attachment_level(dimension, low), '偏低')
                self.assertEqual(attachment_level(dimension, middle), '不低')
                self.assertEqual(attachment_level(dimension, high - 1), '不低')
                self.assertEqual(attachment_level(dimension, high), '高')

    def test_invalid_closeness_does_not_become_low(self):
        for score in ['', None, 'missing', math.nan, math.inf, -1, 31]:
            with self.subTest(score=score):
                self.assertEqual(attachment_level('亲近', score), '')

    def test_jason_stale_labels_are_recomputed_and_figure_is_active(self):
        d = {'029':16, '030':17, '031':19, '038':'低', '039':'低', '040':'低',
             '027':30, '036':'高', '042':'偏低'}
        ctx = build_context({'name':'Jason'}, d)
        self.assertEqual([r['lv_text'] for r in ctx['attachment']['dims'][2]['rows']], ['不低'] * 3)
        self.assertEqual(ctx['attachment']['dims'][1]['rows'][1]['lv_text'], '不低')
        physical = ctx['physical']
        self.assertEqual(physical['level'], '偏瘦')
        self.assertEqual([s['zh'] for s in physical['shapes'] if s['active']], ['偏瘦'])

    def test_bmi_labels(self):
        for source, expected in [('偏低','偏瘦'), (' 偏瘦 ','偏瘦'), ('偏轻','偏瘦'),
                                 ('正常','正常'), ('超重','超重'), ('肥胖','肥胖'), ('','')]:
            with self.subTest(source=source):
                self.assertEqual(normalize_bmi_level(source), expected)

    def test_legacy_renderer_uses_same_categories(self):
        import generate
        with patch.dict(generate.USER_DATA, {'042':'偏低'}):
            page = generate.build_page_10()
        self.assertEqual(page['bmi_level'], '偏瘦')
        self.assertEqual([f['level'] for f in page['figures'] if f['active']], ['偏瘦'])
        self.assertEqual(generate._attachment_level('亲近', 16), '不低')


if __name__ == '__main__':
    unittest.main()
