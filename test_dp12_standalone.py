"""Standalone foundation acceptance with fictional students and fake model calls."""
import copy
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session

import db
import m1.plan_context as context
import m1.plan_pipeline as pipeline
import m1.plan_store as plans
import m1.store as store
from test_m1_store import m1db  # noqa: F401
from test_m1dp_api import plan_client  # noqa: F401
from test_m1dp_pipeline import FakeModel
from test_m1dp_store import _goal, _create, _published_prep
from test_m1_pipeline import _login


@pytest.fixture
def standalone(m1db):
    plans.ensure_tables(m1db.engine)
    with Session(m1db.engine) as session:
        student = session.get(db.Student, m1db.incomplete_student_id)
        student.grade = ''
        session.commit()
    return plans.create_plan(m1db.incomplete_student_id, source_mode='mentor_inputs',
                             mentor_user_id=m1db.alice_id, block_no=1,
                             period_start='2026-11-17', period_end='2026-12-17')


def item(text, provenance='mentor', use=True):
    return {'text': text, 'provenance': provenance, 'source_ref': '',
            'use_for_teaching': use, 'disclosure': 'internal_only'}


def brief():
    return {'learning_need': item('练习表达不同意见'),
            'current_situation': item('机器人小组分工时同伴抢先决定'),
            'current_response': item('先点头，回家才说不愿意'),
            'student_wish': item('想说出自己的想法', 'student'),
            'parent_priority': item('希望更主动', 'parent'),
            'interests': item('机器人', 'student'),
            'teaching_implications': item('用机器人分工场景练一句不同意见'),
            'topics_to_avoid': item('PRIVATE_UNAUTHORIZED_MARKER', use=False)}


def ready(plan, actor):
    plan = plans.save_brief(plan['id'], plan['rev'], brief())
    plan = plans.confirm_brief(plan['id'], plan['rev'], actor)
    return plans.save_goals(plan['id'], plan['rev'], [_goal('R2.2'), _goal('R3.3')])


def test_zero_meeting_creation_eligibility_lists_hub_and_grade_optional(plan_client, m1db):
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    sid = m1db.incomplete_student_id
    # This student has neither Y4 nor meetings/reports.
    eligible = plan_client.get('/api/m1/plans/eligible?source_mode=mentor_inputs').get_json()['students']
    assert sid in [row['student_id'] for row in eligible]
    res = plan_client.post('/api/m1/plans', json={
        'source_mode': 'mentor_inputs', 'student_id': sid, 'block_no': 1,
        'period_start': '2026-11-17', 'period_end': '2026-12-17'})
    assert res.status_code == 201, res.get_json()
    plan = res.get_json()['plan']
    assert plan['prep_id'] is plan['report_id'] is plan['report_version_id'] is None
    assert plan['wb_grade'] is None and plan['goals'] == [] and plan['teaching_brief'] == {}
    assert plan['session_durations'] == [60, 60, 60]
    assert res.get_json()['next_action']['action'] == 'supply_brief'
    hub = plan_client.get(f'/api/m1/students/{sid}/overview').get_json()
    assert hub['preps'] == [] and hub['plans'][0]['id'] == plan['id']
    assert hub['create_plan']['href'] == '/api/m1/plans'
    page = plan_client.get(f'/m1/students/{sid}')
    assert page.status_code == 200
    assert 'id="m1StudentHub"' in page.get_data(as_text=True)
    rows = plan_client.get('/api/m1/students').get_json()['students']
    assert next(row for row in rows if row['id'] == sid)['plan']['id'] == plan['id']
    assert plan_client.get('/api/m1/plans').get_json()['plans'][0]['id'] == plan['id']
    assert plans.report_state(plan)['applicable'] is False
    assert store.list_preps(student_id=sid, user={'role': 'admin'}) == []


@pytest.mark.parametrize('changes', [
    {'period_start': '2026-02-30'}, {'period_end': '2026-11-01'},
    {'block_no': 0}, {'block_no': True}, {'sessions': 2}, {'wb_grade': 10},
    {'mentor_user_id': 99999}, {'source_mode': 'other'}, {'prep_id': 1},
])
def test_direct_create_rejects_invalid_header(plan_client, m1db, changes):
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    payload = {'source_mode': 'mentor_inputs', 'student_id': m1db.incomplete_student_id,
               'block_no': 1, 'period_start': '2026-11-17', 'period_end': '2026-12-17'}
    payload.update(changes)
    assert plan_client.post('/api/m1/plans', json=payload).status_code in (400, 403)
    assert plans.list_plans({'role': 'admin'}) == []


def test_assignment_respects_student_scope_and_revoked_m1_access(plan_client, m1db):
    _login(plan_client, m1db.admin_id, 'admin')
    payload = {'source_mode': 'mentor_inputs', 'student_id': m1db.incomplete_student_id,
               'mentor_user_id': m1db.bob_id, 'block_no': 1,
               'period_start': '2026-11-17', 'period_end': '2026-12-17'}
    assert plan_client.post('/api/m1/plans', json=payload).status_code == 400
    payload['mentor_user_id'] = m1db.alice_id
    with Session(m1db.engine) as session:
        session.get(db.User, m1db.alice_id).m1_access = 0
        session.commit()
    res = plan_client.post('/api/m1/plans', json=payload)
    assert res.status_code == 400 and '心有灵析权限' in res.get_json()['error']


@pytest.mark.parametrize('role,owner,view,edit', [
    ('advisor', 'alice', True, True), ('advisor', 'bob', False, False),
    ('admin', 'admin', True, True), ('viewer', 'viewer', False, False),
    ('advisor_all', 'bob', True, False), ('m1_admin', 'bob', True, True),
])
def test_permissions_including_jobs_uploads_brief_and_hub(plan_client, standalone, m1db, monkeypatch, tmp_path, role, owner, view, edit):
    from m1 import jobs
    monkeypatch.setattr(jobs, 'JOB_DIR', str(tmp_path / 'jobs'))
    uid = getattr(m1db, owner + '_id')
    if role in ('advisor_all', 'm1_admin'):
        with Session(m1db.engine) as session:
            user = session.get(db.User, uid)
            user.student_scope = 'all'
            user.m1_admin = int(role == 'm1_admin')
            session.commit()
    _login(plan_client, uid, 'advisor' if role in ('advisor_all', 'm1_admin') else role,
           {'alice': 'Alice', 'bob': 'Bob'}.get(owner, ''))
    if role in ('advisor_all', 'm1_admin'):
        # plan_client deliberately stubs is_authenticated; fill the policy snapshot
        # normally refreshed from the persisted account by authentication.
        with plan_client.session_transaction() as session:
            session['student_scope'] = 'all'
            session['m1_admin'] = int(role == 'm1_admin')
    pid, sid = standalone['id'], standalone['student_id']
    jobs.write_job('a' * 32, plan_id=pid, status='done')
    assert (plan_client.get(f'/api/m1/plans/{pid}').status_code == 200) == view
    assert (plan_client.get(f'/api/m1/students/{sid}/overview').status_code == 200) == view
    assert (plan_client.get('/api/m1/jobs/' + 'a' * 32).status_code == 200) == view
    response = plan_client.put(f'/api/m1/plans/{pid}/brief', json={'rev': standalone['rev'], 'teaching_brief': brief()})
    assert (response.status_code == 200) == edit
    upload = plan_client.post(f'/api/m1/plans/{pid}/files', data={'file': (io.BytesIO(b'fictional note'), 'notes.txt')})
    assert (upload.status_code == 201) == edit
    if edit:
        fid = upload.get_json()['file']['id']
        assert 'stored_path' not in upload.get_json()['file']
        assert plan_client.delete(f'/api/m1/plan-files/{fid}').status_code == 200


def test_same_student_other_mentor_view_only_and_student_scope_not_prep_scope(plan_client, standalone, m1db):
    # Bob is a mentor of an unrelated prep for Alice's student; this gives no direct-plan access.
    m1db.prep(standalone['student_id'], m1db.bob_id)
    _login(plan_client, m1db.bob_id, 'advisor', 'Bob')
    assert plan_client.get(f"/api/m1/plans/{standalone['id']}").status_code == 404
    with Session(m1db.engine) as session:
        session.get(db.User, m1db.bob_id).advisor_name = 'Alice'
        session.commit()
    _login(plan_client, m1db.bob_id, 'advisor', 'Alice')
    assert plan_client.get(f"/api/m1/plans/{standalone['id']}").status_code == 200
    assert plan_client.put(f"/api/m1/plans/{standalone['id']}/durations", json={'rev': standalone['rev'], 'session_durations': [45,60,75]}).status_code == 403


def test_brief_confirmation_revision_duration_readiness_and_approved_snapshot(standalone, m1db):
    pid = standalone['id']
    assert any('教学简报' in error for error in plans.generate_blockers(standalone))
    plan = ready(standalone, m1db.alice_id)
    assert plans.generate_blockers(plan) == []
    assert 'preferences' not in plan['teaching_brief']
    assert plan['teaching_brief']['parent_priority']['provenance'] == 'parent'
    plan = plans.save_durations(pid, plan['rev'], [45,60,75])
    assert plan['brief_confirmed_revision'] == plan['brief_revision']
    old = plan
    changed = brief()
    changed['current_response']['text'] = '沉默'
    plan = plans.save_brief(pid, plan['rev'], changed)
    assert plan['brief_confirmed_revision'] is None
    with pytest.raises(plans.RevConflict):
        plans.confirm_brief(pid, old['rev'], m1db.alice_id)
    plan = plans.confirm_brief(pid, plan['rev'], m1db.alice_id)
    plans.begin_generation(pid)
    version = plans.add_version(pid, part='internal', doc={'snapshot': 'approved'}, ai_doc={'snapshot': 'approved'})
    plans.finish_generation(pid, version_id=version['id'])
    plans.approve(pid, m1db.alice_id)
    plan = plans.get_plan(pid)
    with pytest.raises(plans.StatusError):
        plans.save_brief(pid, plan['rev'], brief())
    with pytest.raises(plans.StatusError):
        plans.save_durations(pid, plan['rev'], [45,45,45])
    assert plans.get_version(version['id'])['doc'] == {'snapshot': 'approved'}


@pytest.mark.parametrize('durations', [[60,60], [60,60,60,60], [True,60,60], [0,60,60], [181,60,60], ['60',60,60], None])
def test_duration_validation(standalone, durations):
    with pytest.raises(ValueError):
        plans.save_durations(standalone['id'], standalone['rev'], durations)


@pytest.mark.parametrize('bad', [
    {'invented': item('x')}, {'interests': 'robotics'},
    {'interests': item('x', 'unknown')}, {'interests': dict(item('x'), disclosure='public')},
    {'interests': dict(item('x'), use_for_teaching='yes')},
    {'interests': dict(item('x', 'file'), source_ref='999')},
    {'interests': dict(item('x', 'report'), source_ref='1')},
])
def test_brief_shape_provenance_and_ownership_validation(standalone, bad):
    with pytest.raises(ValueError):
        plans.save_brief(standalone['id'], standalone['rev'], bad)


def test_direct_source_does_not_change_after_later_report(standalone, m1db):
    plan = ready(standalone, m1db.alice_id)
    before = copy.deepcopy(plan)
    _published_prep(m1db, student_id=standalone['student_id'])
    assert plans.get_plan(plan['id']) == before
    assert context.build_context(plan)['report_doc'] == {}
    assert plans.generate_blockers(plan) == []


def test_direct_generation_approve_parent_fake_model_and_private_context(standalone, m1db, monkeypatch):
    plan = ready(standalone, m1db.alice_id)
    plan = plans.save_personal(plan['id'], plan['rev'], 'RAW_PRIVATE_NOTE_MARKER', 'RAW_PRIVATE_SUMMARY_MARKER')
    fake = FakeModel()
    monkeypatch.setattr(pipeline, 'call_model', fake)
    def no_report(*_):
        raise AssertionError('direct plan must not read a report')
    monkeypatch.setattr(pipeline.rstore, 'get_report_by_id', no_report)
    monkeypatch.setattr(pipeline.rstore, 'get_version', no_report)
    plans.begin_generation(plan['id'])
    vid = pipeline.generate(plan['id'])
    version = plans.get_version(vid)
    assert len(version['doc']['sessions']) == 3
    assert len(fake.prompts) == 5  # overview + three sessions + one bounded repair
    assert version["manifest"]["repair"]["attempts"] == 1
    for prompt in fake.prompts:
        assert '机器人' in prompt and 'parent_priority' in prompt
        assert 'PRIVATE_UNAUTHORIZED_MARKER' not in prompt
        assert 'RAW_PRIVATE' not in prompt
    assert 'duration_minutes' in fake.prompts[1]
    assert version['manifest']['teaching_context']['session_durations'] == [60,60,60]
    plans.approve(plan['id'], m1db.alice_id)
    plans.begin_generation(plan['id'], 'parent')
    parent_id = pipeline.generate_parent(plan['id'])
    assert plans.get_plan(plan['id'])['parent_status'] == 'draft'
    prompt = fake.prompts[-1]
    for private in ('teaching_context', 'parent_priority', 'provenance', 'PRIVATE_', 'RAW_PRIVATE', '机器人小组分工时同伴抢先决定'):
        assert private not in prompt
    plans.confirm_parent(plan['id'], m1db.alice_id)
    plans.export_parent(plan['id'], m1db.alice_id)
    assert plans.get_plan(plan['id'])['parent_status'] == 'exported'
    assert plans.get_version(parent_id)['source_version_id'] == vid


@pytest.mark.parametrize('mode', ['report', 'mentor_inputs'])
def test_parent_prompt_never_receives_internal_brief_or_unapproved_notes(m1db, standalone, monkeypatch, mode):
    from test_m1dp_api import _internal_doc
    if mode == 'report':
        prep, report = _published_prep(m1db)
        plan = _create(m1db, prep, report)
    else:
        plan = standalone
    private = brief()
    private['parent_priority']['text'] = 'PARENT_INTERNAL_ONLY_SECRET'
    private['parent_priority']['source_ref'] = 'SOURCE_REFERENCE_SECRET'
    plan = plans.save_brief(plan['id'], plan['rev'], private)
    plan = plans.confirm_brief(plan['id'], plan['rev'], m1db.alice_id)
    plan = plans.save_personal(plan['id'], plan['rev'], 'NOTES_SECRET', 'SUMMARY_SECRET')
    plan = plans.save_goals(plan['id'], plan['rev'], [_goal()])
    plans.add_version(plan['id'], part='internal', doc=_internal_doc(), ai_doc=_internal_doc())
    plans.finish_generation(plan['id'])
    plans.approve(plan['id'], m1db.alice_id)
    fake = FakeModel()
    monkeypatch.setattr(pipeline, 'call_model', fake)
    pipeline.generate_parent(plan['id'])
    assert 'SECRET' not in fake.prompts[-1]
    assert 'teaching_context' not in fake.prompts[-1]


def test_extract_uploaded_notes_and_goal_fill_grounded_in_confirmed_brief(standalone, m1db, monkeypatch):
    plans.add_file(standalone['id'], filename='fictional.txt', text='FILE_MARKER 机器人小组', text_status='ok')
    plan = plans.save_personal(standalone['id'], standalone['rev'], 'MENTOR_NOTE_MARKER')
    prompts = []
    def extract(prompt):
        prompts.append(prompt)
        assert 'FILE_MARKER' in prompt and 'MENTOR_NOTE_MARKER' in prompt
        return {'needs': '表达不同意见', 'teaching_brief': {'learning_need': item('表达不同意见')}}
    monkeypatch.setattr(pipeline, '_ask', extract)
    plan = pipeline.read_report(plan['id'])
    assert plan['inputs']['needs']['src'] == 'ai'
    assert plan['goals'] == [] and plan['brief_confirmed_revision'] is None
    assert not plan['teaching_brief']['learning_need']['use_for_teaching']
    plan = ready(plan, m1db.alice_id)
    def fill(prompt):
        assert '机器人小组' in prompt and 'parent_priority' in prompt
        assert 'MENTOR_NOTE_MARKER' not in prompt and 'FILE_MARKER' not in prompt
        return {'start': '先点头', 'expected': '说出一句不同意见'}
    monkeypatch.setattr(pipeline, '_ask', fill)
    filled = pipeline.fill_goal(plan['id'], 'R2.2')
    assert filled['goals'][0]['locked'] is True  # AI never selects/locks new competencies.
    assert filled['goals'][0]['start']['text'] == '先点头'


def test_ai_extraction_cannot_overwrite_concurrent_revision(standalone, monkeypatch):
    plan = plans.save_personal(standalone['id'], standalone['rev'], 'fictional note')
    def concurrent_edit(_prompt):
        plans.save_durations(plan['id'], plan['rev'], [45,45,45])
        return {'needs': 'stale', 'teaching_brief': {'learning_need': item('stale')}}
    monkeypatch.setattr(pipeline, '_ask', concurrent_edit)
    with pytest.raises(plans.RevConflict):
        pipeline.read_report(plan['id'])
    current = plans.get_plan(plan['id'])
    assert current['session_durations'] == [45,45,45]
    assert current['teaching_brief'] == {}


def test_simultaneous_brief_writes_only_one_revision_wins(standalone):
    barrier = threading.Barrier(2)
    def update(n):
        barrier.wait()
        try:
            plans.save_durations(standalone['id'], standalone['rev'], [n,n,n])
            return 'saved'
        except plans.RevConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [45,75]))
    assert sorted(results) == ['conflict', 'saved']
    assert plans.get_plan(standalone['id'])['rev'] == standalone['rev'] + 1


def test_readiness_is_specific_and_server_next_action(plan_client, standalone, m1db):
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    url = f"/api/m1/plans/{standalone['id']}"
    response = plan_client.post(url + '/generate', json={'rev': standalone['rev']})
    assert response.status_code == 409
    body = response.get_json()
    assert body['next_action']['action'] == 'supply_brief'
    assert all('报告' not in blocker for blocker in body['blockers'])
    assert any('学习需要' in blocker for blocker in body['blockers'])
    assert any('当前情境' in blocker for blocker in body['blockers'])
    assert plan_client.put(url + '/brief', json={'rev': standalone['rev'], 'teaching_brief': brief()}).status_code == 200
    stale = plan_client.post(url + '/brief/confirm', json={'rev': standalone['rev']})
    assert stale.status_code == 409
    assert plans.get_plan(standalone['id'])['brief_confirmed_revision'] is None


def test_complete_direct_api_job_lifecycle(plan_client, standalone, m1db, monkeypatch, tmp_path):
    """Exercise actual routes, job runner, polling, approval and parent confirmation."""
    import uuid
    from m1 import jobs, plan_jobs
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    monkeypatch.setattr(jobs, 'JOB_DIR', str(tmp_path / 'jobs'))
    monkeypatch.setattr(plan_jobs, 'JOB_DIR', str(tmp_path / 'jobs'))
    fake = FakeModel()
    monkeypatch.setattr(pipeline, 'call_model', fake)
    def launch(plan_id, kind, **kwargs):
        job_id = uuid.uuid4().hex
        args = {'plan_id': plan_id, 'kind': kind, 'actor_id': kwargs.get('actor_id'),
                'previous_status': kwargs.get('previous_status'),
                'expected_rev': kwargs.get('expected_rev')}
        jobs.write_job(job_id, status='queued', plan_id=plan_id, kind=kind,
                       steps=plan_jobs.new_steps(kind))
        assert plan_jobs.run_job(job_id, args) == 0
        return job_id
    monkeypatch.setattr(plan_jobs, 'launch_job', launch)
    url = f"/api/m1/plans/{standalone['id']}"
    plan = standalone
    res = plan_client.put(url + '/brief', json={'rev': plan['rev'], 'teaching_brief': brief()})
    assert res.status_code == 200
    plan = res.get_json()['plan']
    res = plan_client.post(url + '/brief/confirm', json={'rev': plan['rev']})
    assert res.status_code == 200
    plan = res.get_json()['plan']
    res = plan_client.put(url + '/goals', json={'rev': plan['rev'], 'goals': [_goal('R2.2'), _goal('R3.3')]})
    assert res.status_code == 200
    plan = res.get_json()['plan']
    res = plan_client.post(url + '/generate', json={'rev': plan['rev']})
    assert res.status_code == 202, res.get_json()
    job = plan_client.get('/api/m1/jobs/' + res.get_json()['job_id']).get_json()['job']
    assert job['status'] == 'done' and job['plan_id'] == plan['id']
    detail = plan_client.get(url).get_json()
    res = plan_client.post(url + '/approve', json={'rev': detail['plan']['rev']})
    assert res.status_code == 200 and res.get_json()['plan']['status'] == 'approved'
    res = plan_client.post(url + '/parent/generate')
    assert res.status_code == 202
    # The mentor must select a practice and acknowledge both family suggestions.
    detail = plan_client.get(url).get_json()
    assert plan_client.post(url + '/parent/confirm',
                            json={'rev': detail['plan']['rev']}).status_code == 409
    doc = detail['parent']['doc']
    doc['practice'] = [doc['practice_options'][0]['ref']]
    doc['family_seen'] = [True, True]
    saved = plan_client.put(url + '/parent', json={'rev': detail['plan']['rev'], 'doc': doc})
    assert saved.status_code == 200, saved.get_json()
    res = plan_client.post(url + '/parent/confirm',
                           json={'rev': saved.get_json()['plan']['rev']})
    assert res.status_code == 200, res.get_json()
    result = plan_client.get(url).get_json()
    assert result['plan']['parent_status'] == 'confirmed'
    assert len(result['internal']['doc']['sessions']) == 3
    assert result['parent']['source_version_id'] == result['internal']['id']
    assert result['next_action']['action'] == 'export_parent'


def test_report_brief_extraction_is_explicit_and_preserves_report_source(m1db, monkeypatch):
    plans.ensure_tables(m1db.engine)
    prep, report = _published_prep(m1db)
    plan = _create(m1db, prep, report)
    # Seed bounded report context as an existing approved report projection.
    monkeypatch.setattr(pipeline, '_report_view', lambda doc: {'needs': 'REPORT_CONTEXT_MARKER'})
    def extract(prompt):
        assert 'REPORT_CONTEXT_MARKER' in prompt
        return {'needs': '表达', 'teaching_brief': {
            'learning_need': dict(item('表达', 'report'), source_ref=str(plan['report_version_id']))}}
    monkeypatch.setattr(pipeline, '_ask', extract)
    result = pipeline.extract_inputs(plan['id'])
    assert result['source_mode'] == 'report'
    assert result['report_id'] == plan['report_id']
    assert result['teaching_brief']['learning_need']['provenance'] == 'report'
    assert not result['teaching_brief']['learning_need']['use_for_teaching']
    assert result['brief_confirmed_revision'] is None


def test_new_extract_route_checks_revision_and_queues_source_aware_job(plan_client, standalone, m1db, monkeypatch):
    from m1 import plan_jobs
    _login(plan_client, m1db.alice_id, 'advisor', 'Alice')
    called = []
    monkeypatch.setattr(plan_jobs, 'launch_job', lambda pid, kind, **kw: called.append((pid, kind, kw)) or 'b' * 32)
    url = f"/api/m1/plans/{standalone['id']}/brief/extract"
    assert plan_client.post(url).status_code == 400
    assert plan_client.post(url, json={'rev': 999}).status_code == 409
    assert called == []
    assert plan_client.post(url, json={'rev': standalone['rev']}).status_code == 202
    assert called[0][1] == 'plan_brief'
    assert called[0][2]['expected_rev'] == standalone['rev']


def test_queued_extraction_refuses_revision_changed_before_worker_start(standalone, monkeypatch, tmp_path):
    from m1 import jobs, plan_jobs
    monkeypatch.setattr(jobs, 'JOB_DIR', str(tmp_path / 'jobs'))
    monkeypatch.setattr(plan_jobs, 'JOB_DIR', str(tmp_path / 'jobs'))
    plans.save_durations(standalone['id'], standalone['rev'], [45,45,45])
    monkeypatch.setattr(pipeline, '_ask', lambda prompt: pytest.fail('stale queued job must not call AI'))
    with pytest.raises(plans.RevConflict):
        plan_jobs.run_job('b' * 32, {'plan_id': standalone['id'], 'kind': 'plan_brief',
                                    'expected_rev': standalone['rev']})
    assert jobs.read_job('b' * 32)['status'] == 'error'


def test_goal_fill_refuses_unconfirmed_brief_and_concurrent_edit(standalone, m1db, monkeypatch):
    plan = plans.save_goals(standalone['id'], standalone['rev'], [_goal()])
    with pytest.raises(pipeline.PlanError, match='确认教学简报'):
        pipeline.fill_goal(plan['id'], 'R2.2')
    plan = ready(plan, m1db.alice_id)
    def concurrent_edit(_):
        plans.save_durations(plan['id'], plan['rev'], [45,45,45])
        return {'start': 'stale start', 'expected': 'stale expected'}
    monkeypatch.setattr(pipeline, '_ask', concurrent_edit)
    with pytest.raises(plans.RevConflict):
        pipeline.fill_goal(plan['id'], 'R2.2')
    assert plans.get_plan(plan['id'])['goals'][0]['start']['text'] != 'stale start'


def test_only_confirmed_authorized_strengths_reach_direct_design(standalone, m1db):
    plan = plans.save_inputs(standalone['id'], standalone['rev'], {'strengths': 'RAW_PROFILE_STRENGTH_SECRET'})
    assert pipeline._teaching_inputs(plan)['strengths'] == ''
    content = brief()
    content['strengths'] = item('CONFIRMED_STRENGTH_MARKER：愿意帮助同伴', 'student')
    plan = plans.save_brief(plan['id'], plan['rev'], content)
    assert pipeline._teaching_inputs(plan)['strengths'] == ''
    plan = plans.confirm_brief(plan['id'], plan['rev'], m1db.alice_id)
    payload = pipeline._teaching_inputs(plan)
    assert payload['strengths'] == content['strengths']['text']
    assert 'RAW_PROFILE_STRENGTH_SECRET' not in str(payload)
    content['strengths']['use_for_teaching'] = False
    plan = plans.save_brief(plan['id'], plan['rev'], content)
    plan = plans.confirm_brief(plan['id'], plan['rev'], m1db.alice_id)
    assert pipeline._teaching_inputs(plan)['strengths'] == ''
