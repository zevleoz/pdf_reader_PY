"""Fictional/fake-only generation tests; these do not establish teaching quality."""
import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

from m1 import plan_pipeline as pipeline, plan_store as plans, plan_checks as checks
from m1 import plan_quality as quality, plan_kb, plan_prompts, plan_jobs
from m1 import plan_activity_proposals as proposals
import m1.plan_collaboration as collab
from test_m1_store import m1db  # noqa
from test_m1dp_api import plan_client  # noqa
from test_dp12_standalone import standalone, ready  # noqa
from test_m1dp_pipeline import FakeModel, _session_data
from test_m1_pipeline import _login


def rich_activity(n, minutes):
    a = copy.deepcopy(_session_data(n)['activities'][0])
    a.update(minutes=minutes, name='情境%d' % n, steps='导师展示假设机器人分工，学生选一句不同意见并演练%d次。' % n,
        purpose='练习表达不同意见', personalization='根据机器人分工时先点头的起点，先提供句式再撤去提示',
        input_refs=['brief.current_situation', 'brief.current_response'], student_action='选一句并实际说给导师听',
        expected_attempt='说出一次不同意见并给一个理由', support='先指选句卡，再和导师一起读', extension='假设对方不同意，再回应一次')
    return a


class RichModel(FakeModel):
    def __call__(self, prompt):
        if prompt.startswith(plan_prompts.TASK_SESSION):
            self.prompts.append(prompt)
            n = int(re.search(r'第 (\d) 节课', prompt).group(1))
            data = json.loads(prompt.split('【资料】\n')[-1])
            raw = _session_data(n)
            budget = data['timing_budget']
            raw['timing'] = {k: budget[k] for k in ('review_minutes', 'transition_minutes')}
            raw['activities'] = [rich_activity(n, budget['teaching_minutes'])]
            return raw
        if prompt.startswith(plan_prompts.TASK_ACTIVITY):
            self.prompts.append(prompt)
            data = json.loads(prompt.split('【资料】\n')[-1])
            a = rich_activity(1, data['target_minutes'])
            a['name'] = '替换：分工表达'
            return {'activity': a}
        return super().__call__(prompt)


@pytest.fixture
def draft(standalone, m1db, monkeypatch):
    p = ready(standalone, m1db.alice_id)
    monkeypatch.setattr(pipeline, 'call_model', RichModel())
    plans.begin_generation(p['id'])
    pipeline.generate(p['id'])
    return plans.get_plan(p['id'])


def propose(p):
    v = plans.current_version(p['id'])
    aid = v['doc']['sessions'][0]['activities'][0]['id']
    return pipeline.propose_activity(p['id'], p['rev'], v['id'], aid)


def accept(p, proposal):
    return proposals.accept(p['id'], proposal['id'], proposal['source_rev'],
                            proposal['source_version_id'], proposal['activity_id'])


@pytest.mark.parametrize('duration', [45, 60, 90])
def test_budget_counts_each_segment_once(standalone, m1db, monkeypatch, duration):
    p = ready(standalone, m1db.alice_id)
    p = plans.save_durations(p['id'], p['rev'], [duration]*3)
    model = RichModel()
    monkeypatch.setattr(pipeline, 'call_model', model)
    plans.begin_generation(p['id'])
    v = plans.get_version(pipeline.generate(p['id']))
    assert v['manifest']['repair']['attempts'] == 0
    for n, s in enumerate(v['doc']['sessions'], 1):
        assert sum(a['minutes'] for a in s['activities']) + sum(s['timing'].values()) == duration
        assert sum(bool(a['block_review']) for a in s['activities']) == (n == 3)
        assert not any(c['id'].startswith('dp12-timing') for c in v['checks'])
    assert len(model.prompts) == 4
    assert 'parent_priority' in model.prompts[0] and 'grounding_refs' in model.prompts[0]


def test_short_budget_refuses_before_model(standalone, m1db, monkeypatch):
    p = ready(standalone, m1db.alice_id)
    plans.save_durations(p['id'], p['rev'], [15, 15, 15])
    monkeypatch.setattr(pipeline, 'call_model', lambda _: pytest.fail('must refuse before AI'))
    with pytest.raises(ValueError, match='增加本节时长'):
        pipeline.generate(p['id'])


def test_sparse_brief_refuses_before_model(standalone, monkeypatch):
    monkeypatch.setattr(pipeline, 'call_model', lambda _: pytest.fail('sparse must refuse'))
    with pytest.raises(pipeline.PlanError):
        pipeline.generate(standalone['id'])


def test_steps_not_truncated_and_practical_limits_visible(draft):
    v = plans.current_version(draft['id'])
    a = v['doc']['sessions'][0]['activities'][0]
    steps = '先示范一句。再请学生尝试。' * 500
    a['steps']['text'] = steps
    assert any(c['id'] == 'dp12-long-0-0-steps' for c in checks.run_checks(draft, v['doc']))
    adj = []
    result = pipeline._activity(dict(rich_activity(1, 20), steps=steps), 1, 1, ['R2.2'], [], adj)
    assert result['steps']['text'] == steps
    assert adj and '未截断' in adj[0]['text']


@pytest.mark.parametrize('refs', [['brief.invented'], ['__import__(os)'], [{'text': 'brief.current_situation'}], {}, None])
def test_malformed_or_unrelated_refs_are_review_not_crash(draft, refs):
    doc = plans.current_version(draft['id'])['doc']
    doc['sessions'][0]['activities'][0]['input_refs'] = refs
    assert any(c['level'] == 'review' for c in checks.run_checks(draft, doc))


@pytest.mark.parametrize('mutate', [
    lambda d: d['sessions'].append(copy.deepcopy(d['sessions'][0])),
    lambda d: d['sessions'].__setitem__(0, None),
    lambda d: d['sessions'][0].update(timing=None),
    lambda d: d['sessions'][0]['activities'][0].update(support=12),
    lambda d: d['sessions'][0].update(activities=[None]),
])
def test_malformed_rich_save_is_400(plan_client, draft, m1db, mutate):
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    doc = plans.current_version(draft['id'])['doc']
    mutate(doc)
    res = plan_client.put('/api/m1/plans/%d/internal' % draft['id'], json={'rev': draft['rev'], 'doc': doc})
    # Route shape follows existing save API.
    assert res.status_code == 400, (res.status_code, res.get_json())
    assert checks.run_checks(draft, doc)


def test_extension_copy_and_promise_are_reviewed(draft, monkeypatch):
    from m1 import wb
    doc = plans.current_version(draft['id'])['doc']
    monkeypatch.setattr(checks, '_session_lessons', lambda *args: [{'text': 'The child can choose a different card and say one sentence.', 'name': ''}])
    doc['sessions'][0]['activities'][0]['extension']['text'] = 'The child can choose a different card and say one sentence. 已经掌握'
    result = checks.run_checks(draft, doc)
    assert any(c['id'].startswith('copy-') for c in result)
    assert any(c['id'].startswith('promise-activity-') for c in result)


def test_one_repair_for_whole_draft_failed_remains_visible(standalone, m1db, monkeypatch):
    p = ready(standalone, m1db.alice_id)
    fake = FakeModel()
    monkeypatch.setattr(pipeline, 'call_model', fake)
    plans.begin_generation(p['id'])
    v = plans.get_version(pipeline.generate(p['id']))
    assert sum(p.startswith(plan_prompts.TASK_REPAIR) for p in fake.prompts) == 1
    assert v['manifest']['repair']['attempts'] == 1
    assert any(c['label'] == '一次修订' for c in v['checks'])
    assert plans.get_plan(p['id'])['status'] == 'review'


def test_overview_regen_preserves_all_edited_activities(draft, monkeypatch):
    v = plans.current_version(draft['id'])
    doc = v['doc']
    doc['sessions'][0]['activities'][0]['steps']['text'] = 'MENTOR_EDIT_DO_NOT_CHANGE'
    plans.save_internal(draft['id'], draft['rev'], doc)
    before = plans.current_version(draft['id'])['doc']['sessions']
    plans.begin_generation(draft['id'])
    new = plans.get_version(pipeline.regenerate(draft['id'], 'overview'))
    assert new['doc']['sessions'] == before
    assert new['manifest']['repair']['attempts'] == 0


def test_targeted_repair_uses_actual_focus_and_preserves_other_sessions(draft, monkeypatch):
    v = plans.current_version(draft['id'])
    doc = v['doc']
    # Trigger a single-session timing issue.
    doc['sessions'][1]['timing']['transition_minutes'] += 3
    original = copy.deepcopy(doc)
    received = []
    def fake(prompt):
        received.append(json.loads(prompt.split('【资料】\n')[-1]))
        raw = copy.deepcopy(doc['sessions'])
        raw[1]['timing']['transition_minutes'] -= 3
        raw[0]['activities'][0]['steps'] = 'DO NOT APPLY OTHER SESSION'
        raw[2]['activities'][0]['steps'] = 'DO NOT APPLY OTHER SESSION'
        return {'sessions': raw}
    monkeypatch.setattr(pipeline, 'call_model', fake)
    cmap = pipeline._candidate_map(draft['goals'], draft['wb_grade'])
    new, record = pipeline._repair_once(draft, doc, draft['goals'], cmap, sections={2})
    assert record['attempts'] == 1
    assert new['sessions'][0] == original['sessions'][0] and new['sessions'][2] == original['sessions'][2]
    assert received[0]['candidates']['2'] == pipeline._session_candidates(doc['sessions'][1]['focus'], 2, draft['goals'], cmap)


def test_proposal_cancel_noop_replay_rejected(draft):
    before = plans.get_plan(draft['id'])
    proposal = propose(draft)
    assert plans.get_plan(draft['id']) == before
    proposals.cancel(draft['id'], proposal['id'])
    assert plans.get_plan(draft['id']) == before
    with pytest.raises(plans.StatusError):
        accept(draft, proposal)


def test_accept_new_version_preserves_practices_edits_and_source(draft):
    old = plans.current_version(draft['id'])
    doc = old['doc']
    doc['mentor_notes']['text'] = 'UNRELATED_PRIVATE_EDIT'
    doc['sessions'][2]['practice'][0]['id'] = 'stable-practice-ref'
    result = plans.save_internal(draft['id'], draft['rev'], doc)
    p = plans.get_plan(draft['id'])
    before = plans.current_version(p['id'])
    proposal = propose(p)
    result = accept(p, proposal)
    after = plans.get_version(result['version_id'])
    assert result['version_id'] != before['id']
    expected = copy.deepcopy(before['doc'])
    expected['sessions'][0]['activities'][0] = proposal['candidate']
    assert after['doc'] == expected
    assert plans.get_version(before['id']) == before
    assert after['ai_doc'] == before['ai_doc']
    with pytest.raises(plans.StatusError):
        accept(p, proposal)


@pytest.mark.parametrize('change', ['edit', 'brief', 'duration', 'approve', 'reopen'])
def test_stale_proposal_never_overwrites(draft, change):
    prop = propose(draft)
    if change == 'edit':
        doc = plans.current_version(draft['id'])['doc']
        doc['mentor_notes']['text'] = 'preserve new edit'
        plans.save_internal(draft['id'], draft['rev'], doc)
    elif change == 'brief':
        plans.save_brief(draft['id'], draft['rev'], draft['teaching_brief'])
    elif change == 'duration':
        plans.save_durations(draft['id'], draft['rev'], [45]*3)
    else:
        plans.approve(draft['id'])
        if change == 'reopen':
            plans.reopen(draft['id'])
    before = plans.get_plan(draft['id'])
    version = plans.current_version(draft['id'])
    with pytest.raises((plans.RevConflict, plans.StatusError)):
        accept(draft, prop)
    assert plans.get_plan(draft['id']) == before
    assert plans.current_version(draft['id']) == version


def test_approved_requires_reopen_and_approved_snapshot_immutable(draft):
    approved = plans.current_version(draft['id'])
    plans.approve(draft['id'])
    p = plans.get_plan(draft['id'])
    with pytest.raises(plans.StatusError):
        propose(p)
    p = plans.reopen(p['id'])
    proposal = propose(p)
    accept(p, proposal)
    assert plans.get_version(approved['id']) == approved


def test_legacy_raw_review_normalizes_copy_only(draft, m1db):
    v = plans.current_version(draft['id'])
    raw = copy.deepcopy(v['doc'])
    for s in raw['sessions']:
        s.pop('teaching_schema')
        s.pop('timing')
        s['review'] = [f['text'] for f in s['review']]
        for a in s['activities']:
            for k in plan_kb.RICH_ACTIVITY_FIELDS + ('input_refs',):
                a.pop(k, None)
    with Session(m1db.engine) as sess:
        sess.get(plans.M1PlanVersion, v['id']).doc = json.dumps(raw)
        sess.commit()
    assert not [c for c in checks.run_checks(draft, raw) if c['id'].startswith('dp12-') and c['level'] == 'review']
    plans.approve(draft['id'])
    p = plans.reopen(draft['id'])
    prop = propose(p)
    result = accept(p, prop)
    doc = plans.get_version(result['version_id'])['doc']
    assert doc['sessions'][1]['review'] == v['doc']['sessions'][1]['review']
    assert [s['practice'] for s in doc['sessions']] == [s['practice'] for s in raw['sessions']]
    with Session(m1db.engine) as sess:
        assert json.loads(sess.get(plans.M1PlanVersion, v['id']).doc) == raw


def test_proposal_job_failure_after_approval_never_recovers_plan(draft, monkeypatch, tmp_path):
    from m1 import jobs
    monkeypatch.setattr(jobs, 'JOB_DIR', str(tmp_path))
    original = pipeline.propose_activity
    saved = {}
    def delayed(*args, **kwargs):
        plans.approve(draft['id'])
        saved['plan'] = plans.get_plan(draft['id'])
        saved['version'] = plans.current_version(draft['id'])
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'propose_activity', delayed)
    v = plans.current_version(draft['id'])
    with pytest.raises((plans.RevConflict, plans.StatusError)):
        plan_jobs.run_job('a'*32, {'plan_id': draft['id'], 'kind': 'plan_activity_proposal',
            'expected_rev': draft['rev'], 'source_version_id': v['id'], 'activity_id': 's1a1'})
    assert plans.get_plan(draft['id']) == saved['plan']
    assert plans.current_version(draft['id']) == saved['version']


@pytest.mark.parametrize('bad', ['refs', 'source', 'minutes'])
def test_invalid_proposal_visible_and_accept_refused(draft, monkeypatch, bad):
    def fake(prompt):
        a = rich_activity(1, 58)
        if bad == 'refs': a['input_refs'] = ['brief.injected']
        if bad == 'source': a['source'] = {'type': 'world_bank', 'wb_id': 'unrelated'}
        if bad == 'minutes': a['minutes'] = 999
        return {'activity': a}
    monkeypatch.setattr(pipeline, 'call_model', fake)
    prop = propose(draft)
    assert prop['manifest']['repair']['attempts'] == 1
    assert any(c['level'] == 'review' for c in prop['checks'])
    with pytest.raises(ValueError):
        accept(draft, prop)


def test_concurrent_accept_only_one_wins(draft):
    prop = propose(draft)
    def attempt(_):
        try:
            return accept(draft, prop)['version_id']
        except (plans.StatusError, plans.RevConflict):
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, range(2)))
    assert sum(r is not None for r in result) == 1
    assert plans.get_plan(draft['id'])['rev'] == draft['rev']+1


def test_proposal_api_guards_polling_cancel_accept(plan_client, draft, m1db, monkeypatch):
    prop = propose(draft)
    root = '/api/m1/plans/%d/activity-proposals' % draft['id']
    _login(plan_client, m1db.bob_id, 'advisor', 'Bob')
    assert plan_client.get(root+'/'+prop['id']).status_code == 404
    for suffix in ('/accept', '/cancel'):
        assert plan_client.post(root+'/'+prop['id']+suffix, json={}).status_code == 404
    assert plan_client.post(root, json={}).status_code == 404
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    assert plan_client.get(root+'/'+prop['id']).get_json()['proposal']['id'] == prop['id']
    assert plan_client.post(root, json={'rev': True}).status_code == 400
    captured = {}
    def launch(*args, **kwargs):
        captured.update(kwargs)
        return 'a'*32
    monkeypatch.setattr(plan_jobs, 'launch_job', launch)
    body = {k: prop[k] for k in ('source_version_id', 'activity_id')}
    body['rev'] = prop['source_rev']
    assert plan_client.post(root, json=body).status_code == 202
    assert captured['expected_rev'] == draft['rev']
    assert plans.get_plan(draft['id'])['status'] == 'review'
    assert plan_client.post(root+'/'+prop['id']+'/accept', json=body).status_code == 200
    assert plan_client.post(root+'/'+prop['id']+'/accept', json=body).status_code == 409


def test_parent_payload_excludes_all_rich_fields_and_proposals(draft, monkeypatch):
    prop = propose(draft)
    accept(draft, prop)
    plans.approve(draft['id'])
    fake = RichModel()
    monkeypatch.setattr(pipeline, 'call_model', fake)
    plans.begin_generation(draft['id'], 'parent')
    pipeline.generate_parent(draft['id'])
    payload = json.loads(fake.prompts[0].split('【内部版】\n')[-1])
    dumped = json.dumps(payload)
    for key in plan_kb.RICH_ACTIVITY_FIELDS + ('input_refs', 'teaching_brief', 'proposal', 'provenance', 'source_issue'):
        assert key not in dumped


def test_proposal_accept_respects_list_lease_and_source_version(draft, m1db, plan_client):
    prop = propose(draft)
    collab.add_team_member(draft['student_id'], m1db.bob_id,
                           {'user_id': m1db.admin_id, 'role': 'admin'})
    bob = plan_client.application.test_client()
    _login(bob, m1db.bob_id, 'advisor', 'Bob')
    lease = bob.post('/api/m1/plans/%d/leases/acquire' % draft['id'],
                     json={'section': 'internal.session.1.activities',
                           'tab_id': 'bob-list'}).get_json()
    with pytest.raises(collab.LeaseConflict):
        accept(draft, prop)
    assert bob.post('/api/m1/plans/%d/leases/release' % draft['id'],
                    json={'section': 'internal.session.1.activities',
                          'token': lease['token']}).status_code == 200

    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    list_lease = plan_client.post(
        '/api/m1/plans/%d/leases/acquire' % draft['id'],
        json={'section': 'internal.session.1.activities',
              'tab_id': 'alice-list'}).get_json()
    version = plans.current_version(draft['id'])
    replacement = copy.deepcopy(version['doc']['sessions'][0]['activities'])
    replacement[0] = dict(replacement[0], name={'text': '列表替换后的活动', 'src': 'mentor'})
    patched = plan_client.patch(
        '/api/m1/plans/%d/sections/internal.session.1.activities' % draft['id'],
        json={'expected_version': list_lease['version'],
              'document_version': list_lease['document_version'],
              'lease_token': list_lease['token'],
              'idempotency_key': 'teaching-list-replace-1',
              'patch': replacement})
    assert patched.status_code == 200, patched.get_json()
    with pytest.raises((plans.RevConflict, plans.StatusError)):
        accept(draft, prop)
