"""DP16-A：目标与教学活动不再有逐字段字数上限，完整长文原样保存。"""
from __future__ import annotations

import copy
import json
import re

import pytest

import m1.plan_checks as checks
import m1.plan_kb as plan_kb
import m1.plan_pipeline as pipeline
import m1.plan_prompts as prompts
import m1.plan_quality as quality
import m1.plan_store as pstore
from m1 import plan_activity_proposals as proposals
from test_dp13_collab import (_acquire, _add_bob, _client_for, _patch,
                              _release)
from test_m1dp_api import plan_client  # noqa: F401
from test_m1dp_pages_internal import _internal_doc, _plan_with_internal
from test_m1dp_pipeline import FakeModel, _session_data, ready  # noqa: F401
from test_m1dp_store import _goal
from test_m1_store import m1db  # noqa: F401

RICH_KEYS = plan_kb.RICH_ACTIVITY_FIELDS


def _doc():
    doc = _internal_doc()
    for session in doc['sessions']:
        if session['n'] > 1:
            session['review'] = [{'text': '上次回顾一', 'src': 'mentor'},
                                 {'text': '上次回顾二', 'src': 'mentor'}]
        for activity in session['activities']:
            activity['source'] = {'type': 'ai_original'}
    return doc


def _direct_plan_with_internal(db):
    pstore.ensure_tables(db.engine)
    plan = pstore.create_plan(
        db.student_id, mentor_user_id=db.alice_id, block_no=1,
        period_start='2026-09-01', period_end='2026-12-01', credits='3',
        source_mode='mentor_inputs', created_by=db.alice_id)
    plan = pstore.save_goals(plan['id'], plan['rev'], [_goal()])
    doc = _doc()
    version = pstore.add_version(plan['id'], part='internal', kind='ai_draft',
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan['id'], 'internal', version_id=version['id'])
    return pstore.get_plan(plan['id'])


def _long(prefix, unit, repeats, suffix='_END'):
    return prefix + '\n' + (unit * repeats) + '\n尾巴哨兵' + suffix


LONG_GOAL = _long('目标哨兵_START', '把感受说清楚，再说出一次不同意见。', 40)
LONG_START = _long('起点哨兵_START', '小组分工时先点头，回家才表达。', 35)
LONG_EXPECTED = _long('预期哨兵_START', '三节课里能主动说出一次不同意见。', 35)

LONG_NAME = _long('名称哨兵_START', '活动名称', 30)
LONG_STEPS = _long('步骤哨兵_START', '第一步示范，第二步请学生复述并演练。\n', 250)
LONG_QUESTIONS = _long('问题哨兵_START', '你现在注意到了什么？\n', 160)
LONG_MATERIALS = _long('材料哨兵_START', '情境卡、记录表。\n', 130)

LONG_RICH = {
    'purpose': _long('目的哨兵_START', '对应目标并说明教学目的。\n', 50),
    'personalization': _long('个性化哨兵_START', '根据机器人分工情境调整步骤。\n', 70),
    'student_action': _long('行动哨兵_START', '学生选一句并说给导师听。\n', 140),
    'expected_attempt': _long('尝试哨兵_START', '说出一次不同意见并给理由。\n', 90),
    'support': _long('支持哨兵_START', '先指选句卡再一起读。\n', 140),
    'extension': _long('进阶哨兵_START', '对方不同意时再回应一次。\n', 140),
}


def test_old_caps_are_gone_from_config_and_quality():
    assert not hasattr(plan_kb, 'ACTIVITY_LIMITS')
    assert 'name100' not in prompts.SESSION_PROMPT
    assert 'steps4000' not in prompts.SESSION_PROMPT


@pytest.mark.parametrize('fixture_name', ['standalone_plan', 'report_plan'])
def test_goal_text_round_trips_exactly(request, fixture_name):
    plan = request.getfixturevalue(fixture_name)
    goals = [{
        'code': 'R2.2',
        'goal': {'text': LONG_GOAL, 'src': 'mentor'},
        'start': {'text': LONG_START, 'src': 'ai'},
        'expected': {'text': LONG_EXPECTED, 'src': 'edited'},
        'locked': True,
    }]
    saved = pstore.save_goals(plan['id'], plan['rev'], goals)
    goal = saved['goals'][0]
    assert goal['goal']['text'] == LONG_GOAL
    assert goal['start']['text'] == LONG_START
    assert goal['expected']['text'] == LONG_EXPECTED
    assert goal['start']['src'] == 'ai'
    assert goal['expected']['src'] == 'edited'
    assert pstore.get_plan(plan['id'])['goals'][0]['goal']['text'] == LONG_GOAL


@pytest.fixture()
def standalone_plan(m1db):
    return _direct_plan_with_internal(m1db)


@pytest.fixture()
def report_plan(m1db):
    pstore.ensure_tables(m1db.engine)
    return _plan_with_internal(m1db, doc=_doc())


def _activity_payload():
    payload = {
        'name': {'text': LONG_NAME, 'src': 'mentor'},
        'steps': {'text': LONG_STEPS, 'src': 'mentor'},
        'questions': {'text': LONG_QUESTIONS, 'src': 'mentor'},
        'materials': {'text': LONG_MATERIALS, 'src': 'mentor'},
    }
    for key, value in LONG_RICH.items():
        payload[key] = {'text': value, 'src': 'mentor'}
    return payload


@pytest.mark.parametrize('fixture_name', ['report_plan', 'standalone_plan'])
def test_activity_child_patch_preserves_complete_text(plan_client, m1db,
                                                      request, fixture_name):
    plan = request.getfixturevalue(fixture_name)
    client = _client_for(plan_client, m1db.alice_id, 'advisor', 'Alice')
    section = 'internal.session.1.activity.s1a1'
    payload = _activity_payload()

    lease = _acquire(client, plan['id'], section).get_json()
    assert lease.get('ok'), lease
    saved = _patch(client, plan['id'], section, payload, lease,
                   expected=lease['version'])
    assert saved.status_code == 200, saved.get_json()
    assert _release(client, plan['id'], section, lease).status_code == 200

    stored = pstore.current_version(plan['id'], 'internal')['doc']
    activity = stored['sessions'][0]['activities'][0]
    for key, field in payload.items():
        assert activity[key]['text'] == field['text'], key
        assert activity[key]['src'] == 'mentor', key
    assert '\n' in activity['steps']['text']
    assert activity['steps']['text'].endswith('尾巴哨兵_END')


def test_whole_doc_save_and_legacy_string_fields_keep_text(plan_client, m1db,
                                                           report_plan):
    client = _client_for(plan_client, m1db.alice_id, 'advisor', 'Alice')
    plan = pstore.get_plan(report_plan['id'])
    doc = copy.deepcopy(pstore.current_version(plan['id'], 'internal')['doc'])
    activity = doc['sessions'][0]['activities'][0]
    activity['name'] = {'text': LONG_NAME, 'src': 'mentor'}
    activity['steps'] = {'text': LONG_STEPS, 'src': 'mentor'}
    activity['questions'] = {'text': LONG_QUESTIONS, 'src': 'mentor'}
    activity['materials'] = {'text': LONG_MATERIALS, 'src': 'mentor'}
    for key, value in LONG_RICH.items():
        activity[key] = value

    res = client.put('/api/m1/plans/%d/internal' % plan['id'],
                     json={'rev': plan['rev'], 'doc': doc})
    assert res.status_code == 200, res.get_json()
    assert res.get_json()['ok'] is True

    stored = pstore.current_version(plan['id'], 'internal')['doc']
    saved = stored['sessions'][0]['activities'][0]
    assert saved['name']['text'] == LONG_NAME
    assert saved['steps']['text'] == LONG_STEPS
    assert saved['questions']['text'] == LONG_QUESTIONS
    assert saved['materials']['text'] == LONG_MATERIALS
    for key, value in LONG_RICH.items():
        assert saved[key] == value


def test_quality_has_no_length_only_findings_but_required_checks_remain(
        report_plan):
    plan = pstore.get_plan(report_plan['id'])
    doc = copy.deepcopy(pstore.current_version(plan['id'], 'internal')['doc'])
    activity = doc['sessions'][0]['activities'][0]
    activity.update(_activity_payload())
    activity['input_refs'] = ['brief.learning_need']
    findings = quality.review(plan, doc)
    assert not any(item['id'].startswith('long-') for item in findings)
    assert not any('超过' in item['text'] and '字符' in item['text']
                   for item in findings)

    broken = copy.deepcopy(doc)
    broken['sessions'][0]['activities'][0]['purpose'] = {'text': '', 'src': 'ai'}
    broken['sessions'][0]['activities'][0]['input_refs'] = ['brief.invented']
    broken_ids = {item['id'] for item in quality.review(plan, broken)}
    assert 'dp12-missing-0-0-purpose' in broken_ids
    assert 'dp12-refs-0-0' in broken_ids


class LongModel(FakeModel):
    def __call__(self, prompt):
        if prompt.startswith(prompts.TASK_SESSION):
            self.prompts.append(prompt)
            n = int(re.search(r'第 (\d) 节课', prompt).group(1))
            data = json.loads(prompt.split('【资料】\n')[-1])
            raw = _session_data(n)
            budget = data['timing_budget']
            raw['timing'] = {key: budget[key]
                             for key in ('review_minutes', 'transition_minutes')}
            activity = raw['activities'][0]
            activity.update(_activity_payload())
            activity['input_refs'] = list(data['grounding_refs'])[:2]
            activity['minutes'] = budget['teaching_minutes']
            raw['activities'] = [activity]
            return raw
        if prompt.startswith(prompts.TASK_ACTIVITY):
            self.prompts.append(prompt)
            data = json.loads(prompt.split('【资料】\n')[-1])
            activity = copy.deepcopy(_session_data(1)['activities'][0])
            activity.update(_activity_payload())
            activity['input_refs'] = list(data['grounding_refs'])[:2]
            activity['minutes'] = data['target_minutes']
            return {'activity': activity}
        if prompt.startswith(prompts.TASK_GOAL):
            self.prompts.append(prompt)
            return {'goal': LONG_GOAL, 'start': LONG_START,
                    'expected': LONG_EXPECTED}
        return super().__call__(prompt)


def test_fake_model_initial_and_proposal_keep_long_text(ready, monkeypatch):
    _db, plan = ready
    model = LongModel()
    monkeypatch.setattr(pipeline, 'call_model', model)
    pstore.begin_generation(plan['id'], 'internal')
    pipeline.generate(plan['id'])
    version = pstore.get_version(pstore.get_plan(plan['id'])['current_version_id'])
    activity = version['doc']['sessions'][0]['activities'][0]
    assert activity['name']['text'] == LONG_NAME
    assert activity['steps']['text'] == LONG_STEPS
    assert activity['purpose']['text'] == LONG_RICH['purpose']

    updated = pipeline.fill_goal(plan['id'], 'R2.2')
    goal = next(item for item in updated['goals'] if item['code'] == 'R2.2')
    assert goal['start']['text'] == LONG_START
    assert goal['expected']['text'] == LONG_EXPECTED

    current = pstore.get_plan(plan['id'])
    proposal = pipeline.propose_activity(
        plan['id'], current['rev'], current['current_version_id'],
        activity['id'])
    accepted = proposals.accept(plan['id'], proposal['id'],
                                proposal['source_rev'],
                                proposal['source_version_id'],
                                proposal['activity_id'])
    assert accepted
    stored = pstore.current_version(plan['id'], 'internal')['doc']
    replaced = stored['sessions'][0]['activities'][0]
    assert replaced['name']['text'] == LONG_NAME
    assert replaced['steps']['text'] == LONG_STEPS
    assert replaced['extension']['text'] == LONG_RICH['extension']


def test_second_account_conflict_and_reapply_keep_long_text(plan_client, m1db,
                                                             report_plan):
    plan = pstore.get_plan(report_plan['id'])
    _add_bob(m1db)
    alice = _client_for(plan_client, m1db.alice_id, 'advisor', 'Alice')
    bob = _client_for(plan_client, m1db.bob_id, 'advisor', 'Bob')
    section = 'internal.session.1.activity.s1a1'

    lease_a = _acquire(alice, plan['id'], section).get_json()
    first = _patch(alice, plan['id'], section,
                   {'steps': {'text': LONG_STEPS, 'src': 'mentor'}},
                   lease_a, expected=lease_a['version'])
    assert first.status_code == 200, first.get_json()
    assert _release(alice, plan['id'], section, lease_a).status_code == 200

    lease_b = _acquire(bob, plan['id'], section, tab='bob-tab').get_json()
    second = _patch(bob, plan['id'], section,
                    {'questions': {'text': LONG_QUESTIONS, 'src': 'mentor'}},
                    lease_b, expected=lease_b['version'])
    assert second.status_code == 200, second.get_json()
    assert _release(bob, plan['id'], section, lease_b).status_code == 200

    stale_lease = _acquire(alice, plan['id'], section, tab='alice-tab').get_json()
    stale = _patch(alice, plan['id'], section,
                   {'materials': {'text': LONG_MATERIALS, 'src': 'mentor'}},
                   stale_lease, expected=0)
    assert stale.status_code == 409
    assert stale.get_json()['code'] == 'stale_section'
    fresh_version = stale.get_json()['current_version']

    reapplied = _patch(alice, plan['id'], section,
                       {'materials': {'text': LONG_MATERIALS, 'src': 'mentor'}},
                       stale_lease, expected=fresh_version)
    assert reapplied.status_code == 200, reapplied.get_json()
    assert _release(alice, plan['id'], section, stale_lease).status_code == 200

    activity = (pstore.current_version(plan['id'], 'internal')['doc']
                ['sessions'][0]['activities'][0])
    assert activity['steps']['text'] == LONG_STEPS
    assert activity['questions']['text'] == LONG_QUESTIONS
    assert activity['materials']['text'] == LONG_MATERIALS


def test_plan_js_captures_multiline_with_innertext_and_neutral_counter():
    from pathlib import Path
    js = (Path(__file__).parent / 'static' / 'm1' / 'plan.js').read_text(
        encoding='utf-8')
    assert "data-multiline') === '1'" in js
    assert 'field.innerText' in js
    assert "Array.from(value).length + ' 字'" in js
    assert 'length + \'/\' + limit' in js


def test_print_template_receives_complete_long_text(plan_client, m1db,
                                                     report_plan):
    plan = pstore.get_plan(report_plan['id'])
    client = _client_for(plan_client, m1db.alice_id, 'advisor', 'Alice')
    doc = copy.deepcopy(pstore.current_version(plan['id'], 'internal')['doc'])
    activity = doc['sessions'][0]['activities'][0]
    activity.update(_activity_payload())
    res = client.put('/api/m1/plans/%d/internal' % plan['id'],
                     json={'rev': plan['rev'], 'doc': doc})
    assert res.status_code == 200, res.get_json()
    html = client.get('/m1/plans/%d/print' % plan['id']).get_data(as_text=True)
    assert '步骤哨兵_START' in html and '尾巴哨兵_END' in html
    assert '目的哨兵_START' in html
    assert '问题哨兵_START' in html and '材料哨兵_START' in html
    assert LONG_STEPS.split('\n')[0] in html
