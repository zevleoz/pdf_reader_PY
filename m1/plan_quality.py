"""DP12 rich authoring schema and deterministic/advisory review (no quality claims)."""
import json
from m1 import plan_kb
from m1.plan_context import approved_brief


def text(value):
    return str(value.get('text') or '') if isinstance(value, dict) else str(value or '')


def grounding_refs(plan):
    refs = {'brief.' + key: value for key, value in approved_brief(plan).items()}
    if plan.get('source_mode') != 'mentor_inputs':
        refs.update({'inputs.' + key: {'text': text(value), 'provenance': 'report',
                                     'source_ref': str(plan.get('report_version_id') or '')}
                     for key, value in (plan.get('inputs') or {}).items() if text(value)})
    return refs


def validate_additions(doc):
    """Optional additive fields are type checked, never retro-required on old docs."""
    for session in doc.get('sessions', []):
        if 'teaching_schema' in session and (type(session['teaching_schema']) is not int or session['teaching_schema'] != 2):
            raise ValueError('teaching_schema 必须为 2')
        if 'timing' in session:
            timing = session['timing']
            if not isinstance(timing, dict) or set(timing) != {'review_minutes', 'transition_minutes'}:
                raise ValueError('timing 需要 review_minutes/transition_minutes')
            if any(type(v) is not int or v < 0 for v in timing.values()):
                raise ValueError('timing 必须为非负整数分钟')
        for activity in session.get('activities', []):
            for key in plan_kb.RICH_ACTIVITY_FIELDS:
                if key in activity:
                    value = activity[key]
                    if not (isinstance(value, str) or (isinstance(value, dict) and
                            isinstance(value.get('text'), str) and value.get('src') in ('ai', 'edited', 'mentor'))):
                        raise ValueError(key + ' 必须为文字字段')
            if 'input_refs' in activity and (not isinstance(activity['input_refs'], list) or
                    any(not isinstance(ref, str) for ref in activity['input_refs'])):
                raise ValueError('input_refs 必须为字符串数组')


def review(plan, doc):
    invalid = structure_issues(doc)
    if invalid:
        return invalid
    items = []
    refs = grounding_refs(plan)
    names = {}
    seen_ids = set()
    def add(key, path, message, level='review'):
        items.append({'id': 'dp12-' + key, 'level': level, 'path': path,
                      'label': '教学草稿核对', 'text': message})
    if len(json.dumps(doc, ensure_ascii=False)) > plan_kb.INTERNAL_RESPONSE_LIMIT:
        add('response-long', [], '内部版超过50000字符预算，请精简；内容未截断')
    for si, session in enumerate(doc.get('sessions') or []):
        sp = ['sessions', si]
        rich = session.get('teaching_schema') == 2
        activities = session.get('activities') or []
        if rich or 'timing' in session:
            timing = session.get('timing')
            valid = isinstance(timing, dict) and set(timing) == {'review_minutes', 'transition_minutes'} and all(
                type(v) is int and v >= 0 for v in timing.values())
            mins = [a.get('minutes') for a in activities if isinstance(a, dict)]
            if not valid or any(type(v) is not int or v <= 0 for v in mins):
                add('timing-invalid-%d' % si, sp + ['timing'], '分钟数无效；活动为正整数，回顾/转换为非负整数')
            else:
                total = sum(mins) + sum(timing.values())
                duration = (plan.get('session_durations') or [60, 60, 60])[si]
                if total != duration:
                    add('timing-total-%d' % si, sp + ['timing'], '总时长%d分钟，应为%d；活动（含最终总结）、前次实践回顾、转换各计一次' % (total, duration))
                if si == 0 and timing['review_minutes'] != 0 or si > 0 and not 5 <= timing['review_minutes'] <= 10:
                    add('timing-review-%d' % si, sp + ['timing', 'review_minutes'], '第1节不回顾前次实践；第2/3节预留5至10分钟')
            summaries = [i for i, a in enumerate(activities) if a.get('block_review')]
            if summaries != ([len(activities)-1] if si == 2 else []):
                add('summary-%d' % si, sp + ['activities'], 'Block Review只在第3节末尾出现一次')
        for ai, activity in enumerate(activities):
            ap = sp + ['activities', ai]
            aid = activity.get('id')
            if aid:
                if aid in seen_ids:
                    add('id-%d-%d' % (si, ai), ap + ['id'], '活动编号重复')
                seen_ids.add(aid)
            if activity.get('block_review'):
                continue
            if rich or any(key in activity for key in plan_kb.RICH_ACTIVITY_FIELDS):
                for key in plan_kb.RICH_ACTIVITY_FIELDS:
                    if not text(activity.get(key)).strip():
                        add('missing-%d-%d-%s' % (si, ai, key), ap + [key], '缺少可教学字段：' + key)
                used = activity.get('input_refs')
                if not isinstance(used, list) or not used or any(not isinstance(r, str) or r not in refs for r in used):
                    add('refs-%d-%d' % (si, ai), ap + ['input_refs'], '个性化引用必须指向已授权简报/已读报告资料；不能编造引用')
                add('fit-%d-%d' % (si, ai), ap + ['personalization'], '请人工评估：所引情境是否实际改变步骤、目标与可观察尝试是否相连；引用有效不代表内容真实或教学有效', 'hint')
            for key, limit in plan_kb.ACTIVITY_LIMITS.items():
                if len(text(activity.get(key))) > limit:
                    add('long-%d-%d-%s' % (si, ai, key), ap + [key], '%s超过%d字符；请精简，内容未截断' % (key, limit))
            if activity.get('source_issue'):
                add('source-%d-%d' % (si, ai), ap + ['source'], '生成来源不在提供候选中或类型无效，请人工核对（原始值保留在source_issue）')
            name = ''.join(text(activity.get('name')).split()).lower()
            steps = ''.join(text(activity.get('steps')).split()).lower()
            # Exact duplicates are detectable; semantic variety remains advisory.
            signature = (name, steps)
            if signature in names and name and steps:
                add('duplicate-%d-%d' % (si, ai), ap, '活动名称和步骤与另一活动完全重复，请核对递进与差异', 'hint')
            names[signature] = ap
    return items


def structure_issues(doc):
    """Keep check endpoints total on malformed user/model JSON."""
    problem = None
    if not isinstance(doc, dict) or not isinstance(doc.get('sessions'), list) or len(doc['sessions']) != 3:
        problem = '内部版必须为对象且包含恰好三节课'
    else:
        for n, session in enumerate(doc['sessions'], 1):
            if not isinstance(session, dict) or type(session.get('n')) is not int or session['n'] != n:
                problem = '课程编号/结构无效'
                break
            if not isinstance(session.get('activities'), list) or any(not isinstance(a, dict) for a in session['activities']):
                problem = '活动必须为对象数组'
                break
            if not isinstance(session.get('practice'), list) or any(not isinstance(a, dict) for a in session['practice']):
                problem = '实践必须为对象数组'
                break
        if not problem:
            try:
                validate_additions(doc)
            except (ValueError, TypeError) as exc:
                problem = str(exc)
    return [{'id': 'dp12-structure', 'level': 'review', 'path': ['sessions'],
             'label': '教学草稿核对', 'text': problem}] if problem else []


def require_teachable_budget(plan):
    for n, duration in enumerate(plan.get('session_durations') or [60, 60, 60], 1):
        budget = plan_kb.timing_budget(n, duration)
        if budget['teaching_minutes'] < 5:
            raise ValueError('第%d节%d分钟不足以教学：需包含%d分钟上次实践回顾、%d分钟转换、%d分钟阶段总结，并至少保留5分钟教学；请增加本节时长' % (
                n, duration, budget['review_minutes'], budget['transition_minutes'], budget['block_review_minutes']))
