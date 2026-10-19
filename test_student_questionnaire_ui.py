"""学生问卷作答页交互契约测试。

2026-10-19 口径：任何题型选中后都停留在当前题，只有用户显式点「下一步」
（或按 Enter）才前进。本测试锁定模板源码，防止自动前进被重新引入；
真实停留行为由最终验收的浏览器步骤覆盖。
"""
from pathlib import Path


def test_single_choice_requires_manual_next():
    text = Path("templates/student/q_form.html").read_text(encoding="utf-8")
    assert "scheduleAdvance" not in text
    assert "_advance" not in text
    assert '@click="next()">下一步</button>' in text
