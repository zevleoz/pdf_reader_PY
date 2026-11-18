"""DP12 Task 4：内部版编辑器的时长、富字段、单项替换入口与直接创建页。"""
from __future__ import annotations

import re
from pathlib import Path

from m1 import plan_store as pstore
from m1.plan_context import BRIEF_FIELDS

from test_m1dp_pages_internal import (  # noqa: F401  (fixtures)
    _block,
    _internal_doc,
    _mentor,
    _plan_with_internal,
    page_client,
)
from test_m1_store import m1db  # noqa: F401

RICH_KEYS = ('purpose', 'personalization', 'student_action',
             'expected_attempt', 'support', 'extension')


def _rich_doc():
    doc = _internal_doc()
    for session in doc['sessions']:
        session['teaching_schema'] = 2
        session['timing'] = {
            'review_minutes': 0 if session['n'] == 1 else 5,
            'transition_minutes': 2,
        }
        for activity in session['activities']:
            if activity['block_review']:
                continue
            for key in RICH_KEYS:
                activity[key] = {'text': '%s %s' % (key, session['n']), 'src': 'ai'}
            activity['input_refs'] = ['brief.learning_need']
            activity['source_issue'] = '简报里这一项目标写得较长，需要压缩'
    return doc


def _direct_plan(db, block_no=1):
    return pstore.create_plan(
        db.student_id,
        mentor_user_id=db.alice_id,
        block_no=block_no,
        period_start='2026-09-01',
        period_end='2026-12-01',
        credits='3',
        source_mode='mentor_inputs',
        created_by=db.alice_id,
    )


def _brief(**values):
    brief = {key: {'text': '', 'provenance': 'mentor', 'use_for_teaching': False}
             for key in BRIEF_FIELDS}
    for key, text in values.items():
        brief[key] = {'text': text, 'provenance': 'mentor', 'use_for_teaching': True}
    return brief


def test_direct_page_mounts_inputs_and_hides_report_ui(page_client, m1db):
    plan = _direct_plan(m1db)
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert 'id="m1DirectInputs"' in html
    assert 'direct_inputs.js' in html
    assert 'data-source-mode="mentor_inputs"' in html
    assert '直接创建' in html
    for marker in ('id="reportWarn"', 'Development Input', 'id="summaryText"',
                   'id="fileInput"', '会后报告<span class="req">必需</span>'):
        assert marker not in html
    assert '已确认的教学简报' in html
    assert 'data-duration="0"' in html and 'data-duration="2"' in html


def test_report_page_keeps_report_ui_without_direct_mount(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert 'id="m1DirectInputs"' not in html
    assert '会后报告<span class="req">必需</span>' in html
    assert 'id="summaryText"' in html
    assert 'data-source-mode="report"' in html
    assert '报告创建' in html


def test_duration_fields_render_and_save_refreshes_plan(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    inputs = re.findall(r'data-duration="(\d)"[^>]*value="(\d+)"', html, re.S)
    assert inputs == [('0', '60'), ('1', '60'), ('2', '60')]
    assert '合计 180 分钟' in html

    bad = page_client.put('/api/m1/plans/%d/durations' % plan['id'],
                          json={'rev': plan['rev'], 'session_durations': [10, 60, 60]})
    assert bad.status_code == 400

    saved = page_client.put('/api/m1/plans/%d/durations' % plan['id'],
                            json={'rev': plan['rev'], 'session_durations': [45, 60, 75]})
    assert saved.status_code == 200
    body = saved.get_json()
    assert body['plan']['session_durations'] == [45, 60, 75]
    assert body['plan']['rev'] > plan['rev']

    refreshed = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert re.search(r'data-duration="0"[^>]*value="45"', refreshed, re.S)
    assert re.search(r'data-duration="2"[^>]*value="75"', refreshed, re.S)
    assert '合计 180 分钟' in refreshed


def test_rich_sessions_render_timing_totals_fields_and_refs(page_client, m1db):
    plan = _plan_with_internal(m1db, doc=_rich_doc())
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert 'data-version="%d"' % pstore.current_version(plan['id'], 'internal')['id'] in html
    assert 'data-timing="0"' in html and 'data-timing="2"' in html
    assert '上次回顾 5 分钟' in html and '转换 2 分钟' in html
    assert '合计 32 分钟' in html and '合计 47 分钟' in html
    assert '可用于教学 43 分钟' in html
    assert '-28 分钟' in html and '-13 分钟' in html
    assert '建议 3–5 项，仅提示，不阻止批准' in html

    assert 'data-path="sessions.0.activities.0.purpose.text"' in html
    assert 'data-path="sessions.2.activities.0.extension.text"' in html
    assert '教学设计细节' in html
    assert '教学目标与理由' in html and '学生卡住时' in html and '学生准备好时' in html
    assert '依据：' in html and '学习需要' in html
    assert '来源提示：简报里这一项目标写得较长' in html
    assert 'data-op="propose-activity"' in html


def test_legacy_document_has_no_rich_editor(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert '教学设计细节' not in html
    assert 'data-rich-field' not in html
    assert 'data-timing=' not in html
    assert 'data-op="propose-activity"' in html


def test_block_review_cannot_be_deleted_moved_or_replaced(page_client, m1db):
    plan = _plan_with_internal(m1db, doc=_rich_doc())
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    review = _block(html, 'data-block-review="1"')
    assert 'data-op="del-activity"' not in review
    assert 'data-op="up"' not in review and 'data-op="down"' not in review
    assert 'data-op="propose-activity"' not in review
    assert html.count('data-op="propose-activity"') == 6
    assert html.count('data-op="add-activity"') == 3


def test_internal_print_includes_support_and_timing_without_private_notes(page_client, m1db):
    plan = _plan_with_internal(m1db, doc=_rich_doc())
    plan = pstore.save_personal(plan['id'], plan['rev'], '私密原始笔记-不要打印')
    _mentor(page_client, m1db)

    printed = page_client.get('/m1/plans/%d/print' % plan['id']).get_data(as_text=True)
    assert '学生卡住时：</b>support 1' in printed
    assert '学生准备好时：</b>extension 3' in printed
    assert '教学目标与理由：</b>purpose 2' in printed
    assert '上次回顾 5 分钟' in printed
    assert '私密原始笔记-不要打印' not in printed
    assert 'data-path' not in printed


def test_direct_print_uses_confirmed_brief_and_skips_summary(page_client, m1db):
    plan = _direct_plan(m1db)
    plan = pstore.save_brief(plan['id'], plan['rev'], _brief(learning_need='需要练习主动发起对话'))
    plan = pstore.confirm_brief(plan['id'], plan['rev'], m1db.alice_id)
    plan = pstore.save_personal(plan['id'], plan['rev'], '私密原始笔记-不要打印', '需求总结-不要打印')
    doc = _internal_doc()
    version = pstore.add_version(plan['id'], part='internal', kind='ai_draft',
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan['id'], 'internal', version_id=version['id'])
    _mentor(page_client, m1db)

    printed = page_client.get('/m1/plans/%d/print' % plan['id']).get_data(as_text=True)
    assert '学习需要：</b>需要练习主动发起对话' in printed
    assert '个性化需求总结' not in printed
    assert '私密原始笔记-不要打印' not in printed
    assert '需求总结-不要打印' not in printed
    assert '还没有学生资料' not in printed


def test_editor_wires_one_activity_proposal_through_save_and_accept():
    root = Path(__file__).parent
    js = (root / 'static' / 'm1' / 'plan.js').read_text(encoding='utf-8')
    template = (root / 'templates' / 'm1' / 'plan.html').read_text(encoding='utf-8')

    assert "window.addEventListener('m1:plan-rev'" in js
    assert 'flushDirect()' in js
    assert "data-version" in template and 'data-source-mode' in template
    assert 'source_version_id: S.versionId' in js
    assert 'source_version_id: proposal.source_version_id' in js
    assert js.count("'/activity-proposals'") >= 1
    assert "id + '/accept'" in js and "proposalId + '/cancel'" in js
    assert js.index('flushDoc().then') < js.index("API + '/activity-proposals'")
    # 只有明确点击“应用替换”才接受；关闭/取消不写文档
    assert 'proposalOk.addEventListener' in js
    assert 'details.open = true' in js
    assert 'data-rich-field' in template and 'data-placeholder="未填写"' in template


def test_internal_page_uses_unlimited_activity_fields_and_confirmed_direct_brief(page_client, m1db):
    plan = _direct_plan(m1db)
    plan = pstore.save_brief(plan['id'], plan['rev'], _brief(
        learning_need='确认后的学习需要',
        current_situation='确认后的当前情境',
        current_response='确认后的当前反应'))
    plan = pstore.confirm_brief(plan['id'], plan['rev'], m1db.alice_id)
    plan = pstore.save_personal(plan['id'], plan['rev'], '私密原始笔记', '私密总结')
    doc = _rich_doc()
    version = pstore.add_version(plan['id'], part='internal', kind='ai_draft',
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan['id'], 'internal', version_id=version['id'])
    _mentor(page_client, m1db)

    html = page_client.get('/m1/plans/%d' % plan['id']).get_data(as_text=True)
    assert '确认后的学习需要' in html
    assert '确认后的当前情境' in html and '确认后的当前反应' in html
    assert '私密原始笔记' not in html and '私密总结' not in html
    assert '还没有学生资料。' not in html
    assert 'data-limit="100"' not in html
    assert 'data-limit="4000"' not in html
    assert 'data-limit="1500"' not in html
    assert 'data-limit="1000"' not in html
    assert 'data-count="1"' in html
    assert 'data-multiline="1"' in html
    assert 'data-timing-budget="0"' in html


def test_direct_input_profile_copy_matches_teaching_source_contract():
    root = Path(__file__).parent
    html = (root / 'templates' / 'm1' / '_direct_inputs.html').read_text(encoding='utf-8')
    assert '保存后可用于资料提取' in html
    assert '教学内容以导师确认并授权的教学简报为准' in html
