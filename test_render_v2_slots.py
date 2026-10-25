# -*- coding: utf-8 -*-
"""v2 报告按输入 PDF 槽位整页取舍：缺哪份输入就整页不出，不留半空页面。"""

import itertools
import os
import re
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "new_iteration"))

import render_v2  # noqa: E402
from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

# 每个槽位独占的内容页 + 只属于该槽位的分隔页（封面 / 介绍 / 封底恒在）
SLOT_PAGES = {"A2": {"情绪稳定性", "依恋关系", "人格", "体质健康"},
              "B3": {"执行功能", "学习动机与策略"},
              "B4": {"自我概念", "内驱力", "认知资源", "认知能力 · 六项子指标"},
              "B6": {"职业兴趣", "能力优势", "职业价值观"}}
DIVIDERS = {"dv-xin": {"A2", "B4"}, "dv-jing": {"A2"}, "dv-xue": {"B4", "B3"}, "dv-sheng": {"B6"}}


def _render(slots):
    env = Environment(loader=FileSystemLoader(os.path.join(BASE_DIR, "new_iteration")),
                      autoescape=select_autoescape(default=True, default_for_string=True))
    ctx = render_v2.build_context({"name": "测试"}, {}, set(slots))
    return env.get_template(render_v2.TEMPLATE_NAME).render(**ctx)


class SlotPages(unittest.TestCase):
    def test_every_input_combination(self):
        for k in range(1, 5):
            for combo in itertools.combinations(render_v2.SLOTS, k):
                with self.subTest(combo=combo):
                    html = _render(combo)
                    pages = len(re.findall(r'<div class="page[ "]', html))
                    dividers = [dv for dv, need in DIVIDERS.items() if need & set(combo)]
                    expected = 3 + len(dividers) + sum(len(SLOT_PAGES[s]) for s in combo)
                    self.assertEqual(pages, expected)
                    for dv, need in DIVIDERS.items():
                        self.assertEqual(f"divider {dv}" in html, bool(need & set(combo)))

    def test_missing_slot_pages_absent(self):
        html = _render(["A2", "B4", "B6"])
        for title in SLOT_PAGES["B3"]:
            self.assertNotIn(f">{title}<", html)
        self.assertIn("认知资源", html)


class PresentSlots(unittest.TestCase):
    def test_uses_pdf_titles(self):
        self.assertEqual(render_v2.present_slots({"pdf_titles": ["A2", "B6"]}, {"066": "3"}),
                         {"A2", "B6"})

    def test_infers_from_values_without_pdf_titles(self):
        d = {"009": "55", "066": "", "072": "ESA", "059": "80"}
        # 059 可被手填思维模式覆盖，不能据此认定 B4 已上传
        self.assertEqual(render_v2.present_slots({}, d), {"A2", "B6"})


if __name__ == "__main__":
    unittest.main()
