"""Source-aware context shared by extraction, goals and internal generation."""
from m1 import report_store, plan_store

BRIEF_FIELDS = (
    'student_wish', 'student_willingness', 'topics_to_avoid', 'parent_priority',
    'strengths', 'learning_need', 'current_situation', 'current_response', 'interests',
    'preferences', 'constraints', 'teaching_implications',
)
PROVENANCE = ('mentor', 'student', 'parent', 'report', 'file', 'unknown')


def validate_brief(value):
    if not isinstance(value, dict) or set(value) - set(BRIEF_FIELDS):
        raise ValueError('teaching_brief 必须是已定义字段的对象')
    clean = {}
    for key, item in value.items():
        if not isinstance(item, dict) or set(item) - {'text', 'provenance', 'source_ref', 'use_for_teaching', 'disclosure'}:
            raise ValueError(key + ' 字段格式不正确')
        text = item.get('text', '')
        ref = item.get('source_ref', '')
        if not isinstance(text, str) or len(text) > 4000 or not isinstance(ref, str) or len(ref) > 300:
            raise ValueError(key + ' 文字或来源超出限制')
        provenance = item.get('provenance', 'unknown')
        disclosure = item.get('disclosure', 'internal_only')
        use = item.get('use_for_teaching', False)
        if provenance not in PROVENANCE or disclosure not in ('internal_only', 'parent_safe') or type(use) is not bool:
            raise ValueError(key + ' 来源、披露或教学授权不正确')
        if text.strip() and provenance == 'unknown':
            raise ValueError(key + ' 有内容时必须注明来源')
        clean[key] = {'text': text.strip(), 'provenance': provenance, 'source_ref': ref.strip(),
                      'use_for_teaching': use, 'disclosure': disclosure}
    return clean


def approved_brief(plan):
    if not plan.get('brief_revision') or plan.get('brief_confirmed_revision') != plan.get('brief_revision'):
        return {}
    return {key: value for key, value in (plan.get('teaching_brief') or {}).items()
            if value.get('use_for_teaching') and value.get('text')}


def build_context(plan, *, extraction=False):
    direct = plan.get('source_mode') == 'mentor_inputs'
    brief = approved_brief(plan)
    context = {'source_mode': plan.get('source_mode', 'report'), 'teaching_brief': brief,
               'session_durations': plan.get('session_durations', [60, 60, 60])}
    if direct:
        # Extraction is the sole operation allowed to read unconfirmed notes/files.
        if extraction:
            context['mentor_inputs'] = plan.get('inputs') or {}
            context['draft_brief'] = plan.get('teaching_brief') or {}
            context['notes'] = (plan.get('personal') or {}).get('notes') or ''
            context['files'] = [{'id': f['id'], 'text': (plan_store.get_file(f['id']) or {}).get('text', '')}
                                for f in plan_store.list_files(plan['id'])]
        context['report_doc'] = {}
    else:
        version = report_store.get_version(plan.get('report_version_id')) if plan.get('report_version_id') else None
        if not version:
            raise ValueError('会后报告还没有生成内容，请先完成会后报告')
        context['report_doc'] = version.get('doc') or {}
    return context


def teaching_payload(plan):
    context = build_context(plan)
    context.pop('report_doc', None)
    return context
