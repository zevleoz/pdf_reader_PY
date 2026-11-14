"""Goal prefill uses fake models and isolated test databases only."""
import json

import pytest

from m1 import plan_pipeline as pipeline, plan_store as pstore, report_store as rstore
from test_m1_store import m1db  # noqa: F401
from test_m1dp_store import plan_db, _create, _goal, _published_prep  # noqa: F401
from test_m1dp_api import plan_client  # noqa: F401
from test_m1_pipeline import _login


def setup_plan(db, *, text='', locked=False):
    prep, report = _published_prep(db)
    doc = {'plan': [{'ability': 'R2.2', 'goal': {'text': '在小组讨论中表达不同意见'}},
                    {'ability': 'R3.3', 'goal': {'text': 'UNRELATED'}}]}
    rstore.add_version(report['id'], y4_ratings={}, evidence=[], ai_doc=doc,
                       doc=doc, checks=[], manifest={}, status='approved')
    report = rstore.get_report(prep['id'])
    plan = _create(db, prep, report)
    goal = _goal(text=text, locked=locked)
    goal['start'] = {'text': '', 'src': 'ai'}
    goal['expected'] = {'text': '', 'src': 'ai'}
    return pstore.save_goals(plan['id'], plan['rev'], [goal])


def fake(prompt):
    data = json.loads(prompt.split('【资料】\n')[1])
    assert data['report_plan_suggestions'] == [
        {'ability': 'R2.2', 'goal': '在小组讨论中表达不同意见'}]
    return {'goal': '在小组讨论中尝试表达一次不同意见', 'start': '先同意别人',
            'expected': '尝试说明理由'}


@pytest.mark.parametrize('locked', [False, True])
def test_grounded_goal_and_legacy_recovery(plan_db, monkeypatch, locked):
    plan = setup_plan(plan_db, locked=locked)
    monkeypatch.setattr(pipeline, 'call_model', fake)
    result = pipeline.fill_goal(plan['id'], 'R2.2')['goals'][0]
    assert result['goal'] == {'text': '在小组讨论中尝试表达一次不同意见', 'src': 'ai'}
    assert result['start']['text'] == '先同意别人'
    assert result['expected']['text'] == '尝试说明理由'
    assert result['locked'] is locked
    assert pstore.get_plan(plan['id'])['goals'][0] == result


def test_preserves_concurrent_mentor_changes(plan_db, monkeypatch):
    plan = setup_plan(plan_db)
    def edit_during_generation(prompt):
        current = pstore.get_plan(plan['id'])
        goal = current['goals'][0]
        goal['goal'] = {'text': '导师目标', 'src': 'mentor'}
        goal['start'] = {'text': '导师起点', 'src': 'edited'}
        goal['expected'] = {'text': '', 'src': 'edited'}
        pstore.save_goals(plan['id'], current['rev'], [goal])
        return fake(prompt)
    monkeypatch.setattr(pipeline, 'call_model', edit_during_generation)
    goal = pipeline.fill_goal(plan['id'], 'R2.2')['goals'][0]
    assert goal['goal']['text'] == '导师目标'
    assert goal['start']['text'] == '导师起点'
    assert goal['expected'] == {'text': '', 'src': 'edited'}


def test_manual_goal_and_incomplete_response(plan_db, monkeypatch):
    plan = setup_plan(plan_db, text='已有目标')
    monkeypatch.setattr(pipeline, 'call_model', fake)
    assert pipeline.fill_goal(plan['id'], 'R2.2')['goals'][0]['goal']['text'] == '已有目标'
    current = pstore.get_plan(plan['id'])
    current['goals'][0]['goal']['text'] = ''
    pstore.save_goals(plan['id'], current['rev'], current['goals'])
    before = pstore.get_plan(plan['id'])
    monkeypatch.setattr(pipeline, 'call_model', lambda _: {'start': 'a', 'expected': 'b'})
    with pytest.raises(pipeline.PlanError, match='请重试'):
        pipeline.fill_goal(plan['id'], 'R2.2')
    assert pstore.get_plan(plan['id']) == before


def test_api_save_fill_generate(plan_client, m1db, monkeypatch):
    from m1 import plan_jobs
    plan = setup_plan(m1db, locked=True)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    monkeypatch.setattr(pipeline, 'call_model', fake)
    launches = []
    def launch(plan_id, kind, **kwargs):
        launches.append(kind)
        if kind == 'plan_goal':
            pipeline.fill_goal(plan_id, kwargs['code'])
        return 'fake-job'
    monkeypatch.setattr(plan_jobs, 'launch_job', launch)
    root = '/api/m1/plans/%d' % plan['id']
    assert plan_client.get(root).status_code == 200
    assert launches == []
    assert plan_client.put(root + '/goals', json={'rev': plan['rev'], 'goals': plan['goals']}).status_code == 200
    assert plan_client.post(root + '/generate').status_code == 409
    assert plan_client.post(root + '/goals/R2.2/fill').status_code == 202
    current = pstore.get_plan(plan['id'])
    assert current['goals'][0]['goal']['src'] == 'ai'
    pstore.save_inputs_ai(plan['id'], {key: '资料' for key in pipeline.INPUT_KEYS})
    assert plan_client.post(root + '/generate').status_code == 202
    assert launches == ['plan_goal', 'plan_generate']


def test_model_list_fields_are_plain_text():
    assert pipeline._text(['句1', {'text': '句2'}, '', ['句3']]) == '句1\n句2\n句3'
    assert pipeline._field({'text': ['句1', '句2']}) == {'text': '句1\n句2', 'src': 'ai'}


@pytest.mark.parametrize('value, expected', [
    ('["句1", "句2"]', '句1\n句2'),
    ("['句1', {'text': '句2', 'src': 'ai'}]", '句1\n句2'),
    ('普通正文 [例子]', '普通正文 [例子]'),
    ('[先观察，再提问]', '[先观察，再提问]'),
    ('[1, 2]', '[1, 2]'),
    ("[__import__('os').system('false')]", "[__import__('os').system('false')]"),
])
def test_legacy_list_text_is_safe(value, expected):
    assert pstore._legacy_list_text(value) == expected


def test_read_normalization_does_not_rewrite_snapshot(plan_db):
    from sqlalchemy.orm import Session
    plan = setup_plan(plan_db)
    raw = "['句1', '句2']"
    doc = {'sessions': [{'activities': [{'steps': {'text': raw, 'src': 'edited'},
                                       'questions': {'text': raw, 'src': 'ai'}}]}]}
    version = pstore.add_version(plan['id'], part='internal', kind='ai_draft',
                                ai_doc=doc, doc=doc, checks=[])
    first = pstore.get_version(version['id'])
    assert first['doc']['sessions'][0]['activities'][0]['steps'] == {
        'text': '句1\n句2', 'src': 'edited'}
    assert first['doc']['sessions'][0]['activities'][0]['questions']['text'] == '句1\n句2'
    assert first['ai_doc'] == doc
    with Session(plan_db.engine) as sess:
        stored = sess.get(pstore.M1PlanVersion, version['id'])
        assert json.loads(stored.doc) == doc
