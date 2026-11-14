"""DP10：空的发展目标要看得见、要点名。"""
from __future__ import annotations

import re

import m1.plan_store as pstore
from app_utils import BASE_DIR
from test_m1dp_pages_internal import _mentor, page_client  # noqa: F401
from test_m1dp_store import _create, _goal, _published_prep, plan_db  # noqa: F401
from test_m1_store import m1db  # noqa: F401


def _page(client, plan_id):
    return client.get("/m1/plans/%d" % plan_id).get_data(as_text=True)


def test_blocker_names_only_the_empty_goals_in_order(plan_db):
    prep, report = _published_prep(plan_db)
    plan = _create(plan_db, prep, report)
    pstore.save_goals(plan["id"], plan["rev"], [
        _goal("R1.1", text=""), _goal("R2.2"), _goal("R3.5", text="   ")])
    blockers = pstore.generate_blockers(pstore.get_plan(plan["id"]))
    assert "R1.1、R3.5 的发展目标还没写" in blockers
    assert not any("目标还不能为空" in item for item in blockers)
    assert not any("R2.2" in item for item in blockers)


def test_step1_card_shows_placeholder_label_and_warning(page_client, m1db):  # noqa: F811
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    pstore.save_goals(plan["id"], plan["rev"], [_goal("R1.1", text="")])
    _mentor(page_client, m1db)

    html = _page(page_client, plan["id"])
    assert 'data-placeholder="写这一项的发展目标（必填）"' in html
    assert 'aria-label="R1.1 发展目标"' in html and 'role="textbox"' in html
    # 元素必须真正为空，:empty 才会生效
    assert re.search(r'data-goal-text="R1.1"[^>]*></span>', html)
    assert re.search(r'data-goal-warn="R1.1">还没写发展目标，生成前要补上。', html)
    assert "R1.1 的发展目标还没写" in html

    plan = pstore.get_plan(plan["id"])
    pstore.save_goals(plan["id"], plan["rev"], [_goal("R1.1", text="能说出感受")])
    html = _page(page_client, plan["id"])
    assert re.search(r'data-goal-warn="R1.1" hidden>', html)
    assert "data-missing" not in html
    assert "发展目标还没写" not in html.split('id="genHint"')[1].split("</span>")[0]


def test_unlocked_empty_goal_has_no_warning(page_client, m1db):  # noqa: F811
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    pstore.save_goals(plan["id"], plan["rev"], [_goal("R1.1", locked=False, text="")])
    _mentor(page_client, m1db)
    html = _page(page_client, plan["id"])
    assert re.search(r'data-goal-warn="R1.1" hidden>', html)
    assert "data-missing" not in html


def test_lock_handler_checks_goal_text_before_saving():
    js = (BASE_DIR / "static" / "m1" / "plan.js").read_text(encoding="utf-8")
    start = js.index("document.querySelectorAll('[data-lock]')")
    block = js[start:js.index("function addGoal", start)]
    check = block.index("goalEmpty(goal)")
    assert check < block.index("saveGoals()")
    assert check < block.index("/fill")
    assert "先写这一项的发展目标，再锁定。" in block
    assert ".focus()" in block[check:block.index("saveGoals()")]


def test_prefill_control_and_generated_goal_badge(page_client, m1db, monkeypatch):  # noqa: F811
    from m1 import plan_pipeline
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    pstore.save_goals(plan['id'], plan['rev'], [_goal('R1.1', text='')])
    _mentor(page_client, m1db)
    def unexpected_call(*args, **kwargs):
        raise AssertionError('GET must not call the model')
    monkeypatch.setattr(plan_pipeline, 'call_model', unexpected_call)
    assert 'data-fill-goal="R1.1"' in _page(page_client, plan['id'])
    pstore.save_goal_ai(plan['id'], 'R1.1', '起点', '预期', goal='生成目标')
    html = _page(page_client, plan['id'])
    assert 'data-goal-ai="R1.1-goal">AI</span>' in html
    assert '生成目标' in html
    assert '导师选择能力；AI 起草“发展目标”“当前起点”和“阶段预期进展”，由导师编辑并确认。' in html
    assert 'AI 只填' not in html
