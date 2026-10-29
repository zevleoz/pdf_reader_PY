"""6 A.M. 六维启动模型（v0.2 落地）

对外入口：
    run_for_report(report_id, ...)   装配数据 → 跑引擎 → 落库（版本 +1）
    build_profile(report_id, ...)    只读重算（沙盒 / 预览，不落库）
    evidence_from_payload / recover_evidence / merge_evidence   录入闭环
    default_params()                 参数默认值（规则面板展示）

依赖约定（实施计划 §3）：包内其他模块不导入 Flask、不访问数据库；
DB 访问只出现在本模块（集成胶水）。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple


# ── 数据装配 ──────────────────────────────────────────────────
def _assemble(report_id: int) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]]:
    """与 app.py /api/reports/<id>/y4-signals 相同的装配链（不导入 Flask）。

    返回 (report_record, eval_items, student)；报告不存在返回 None。
    """
    import db
    import evaluation_rules as _eval_rules

    record = db.get_report_raw(int(report_id))
    if not record:
        return None
    raw = record.get("raw") or {}
    schema_items = [it for it in (raw.get("schema_124") or [])
                    if not _eval_rules.is_hidden_raw(it)]
    items, _summary = _eval_rules.build_evaluation_view(schema_items)
    student = raw.get("student") or {}
    if not str(student.get("name") or "").strip():
        student = {
            "name": record.get("student_name") or "",
            "grade": student.get("grade") or record.get("grade") or "",
        }
    return record, items, student


def load_eval_items(report_id: int) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]]:
    """公开的装配入口（沙盒页需要自行取 items 时可复用）。"""
    return _assemble(report_id)


# ── 规则版本解析 ──────────────────────────────────────────────
def _resolve_rule_version(rule_version_id: Optional[int] = None):
    """返回 (params 覆盖, rule_overrides, rule_version_meta)。

    优先指定版本；否则当前 published；没有版本时用 DEFAULT_PARAMS（meta 为 default）。
    """
    import db
    rv = None
    if rule_version_id:
        rv = db.get_six_am_rule_version(int(rule_version_id))
    if not rv:
        for v in db.list_six_am_rule_versions():
            if v.get("status") == "published":
                rv = v
                break
    if not rv:
        return None, None, {"id": None, "label": "default", "status": None}
    try:
        payload = json.loads(rv.get("params_json") or "{}")
    except Exception:
        payload = {}
    meta = {"id": rv.get("id"), "label": rv.get("label"), "status": rv.get("status")}
    return payload.get("params") or {}, payload.get("rule_overrides") or {}, meta


def default_params() -> Dict[str, Any]:
    """DEFAULT_PARAMS 深拷贝（规则面板/沙盒展示用）。"""
    from . import rules
    return rules.merge_params(None)


# ── 档案构建（落库 / 只读）────────────────────────────────────
def _latest_profile_dict(report_id: int) -> Optional[Dict[str, Any]]:
    import db
    rec = db.get_latest_six_am_profile(int(report_id))
    if not rec:
        return None
    try:
        return json.loads(rec.get("profile_json") or "{}")
    except Exception:
        return None


def _build(record: Dict[str, Any], items: List[Dict[str, Any]], student: Dict[str, Any], *,
           rule_version_id: Optional[int] = None,
           evidence: Optional[Dict[str, Any]] = None,
           answers: Optional[List[Dict[str, Any]]] = None,
           source_profile: Optional[Dict[str, Any]] = None,
           params: Optional[Dict[str, Any]] = None,
           rule_overrides: Optional[Dict[str, Any]] = None,
           rule_version: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from . import engine

    prev = source_profile if source_profile is not None else _latest_profile_dict(record.get("report_id"))
    if evidence is None:
        evidence = recover_evidence(prev)
    if answers is None:
        answers = (prev or {}).get("answers") or []
    if params is None:
        params, rule_overrides, rule_version = _resolve_rule_version(rule_version_id)
    elif rule_version is None:
        rule_version = {"id": None, "label": "sandbox", "status": "draft"}

    profile = engine.run(items, student=student, evidence=evidence, params=params,
                         rule_version=rule_version, report_id=record.get("report_id"),
                         answers=answers, rule_overrides=rule_overrides)
    # 人工行动修订跟随档案版本继承：无论 prev 来自显式 source_profile
    # 还是 _latest_profile_dict fallback，新版本都深拷贝旧 overrides。
    prev_overrides = (prev or {}).get("action_overrides")
    if isinstance(prev_overrides, dict) and prev_overrides:
        profile["action_overrides"] = copy.deepcopy(prev_overrides)
    return profile


def build_profile(report_id: int, *,
                  rule_version_id: Optional[int] = None,
                  evidence: Optional[Dict[str, Any]] = None,
                  answers: Optional[List[Dict[str, Any]]] = None,
                  source_profile: Optional[Dict[str, Any]] = None,
                  params: Optional[Dict[str, Any]] = None,
                  rule_overrides: Optional[Dict[str, Any]] = None,
                  rule_version: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """只读重算（不落库）：沙盒与预览用。报告不存在返回 None。"""
    ctx = _assemble(report_id)
    if ctx is None:
        return None
    record, items, student = ctx
    return _build(record, items, student, rule_version_id=rule_version_id,
                  evidence=evidence, answers=answers, source_profile=source_profile,
                  params=params, rule_overrides=rule_overrides, rule_version=rule_version)


def run_for_report(report_id: int, *,
                   rule_version_id: Optional[int] = None,
                   evidence: Optional[Dict[str, Any]] = None,
                   answers: Optional[List[Dict[str, Any]]] = None,
                   source_profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """生成档案并落库（每次插入新行，version = 该学生档案数 + 1）。

    返回 profile（附 profile_id / version）；报告不存在返回 None。
    """
    import db
    ctx = _assemble(report_id)
    if ctx is None:
        return None
    record, items, student = ctx
    prof = _build(record, items, student, rule_version_id=rule_version_id,
                  evidence=evidence, answers=answers, source_profile=source_profile)
    version = len(db.get_six_am_profiles_by_student(record["student_id"])) + 1
    pid = db.add_six_am_profile(record["student_id"], int(report_id),
                                json.dumps(prof, ensure_ascii=False), version)
    prof["profile_id"] = pid
    prof["version"] = version
    return prof


# ── 提问闭环：证据载荷 ↔ engine evidence 结构 ─────────────────
# engine evidence 结构（实施计划 §3.4 / §7）：
#   {ft: {schedule, subject_status, standard_task, notes, prior_engagement_same_domain},
#    parent: {complaint: {tags, text, source}, cannot_relinquish},
#    observation: {first_failure_quit, prior_engagement_same_domain, team_behavior_verified},
#    task: {mismatch, adult_arranged, student_chosen, direction_undecided, connect_values},
#    answers: [{q, result, text, at}]}

def evidence_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """录入表单（answers + gaps 四类缺口 + observation/task）→ engine evidence。"""
    payload = payload or {}
    ev: Dict[str, Any] = {}
    gaps = payload.get("gaps") or {}

    fam = gaps.get("family_complaint")
    if isinstance(fam, dict) and (fam.get("tags") or str(fam.get("text") or "").strip()):
        ev["parent"] = {"complaint": fam}

    ft: Dict[str, Any] = {}
    sch = gaps.get("schedule")
    if isinstance(sch, dict) and any(
            str(sch.get(k) if sch.get(k) is not None else "").strip()
            for k in ("overview", "free_hours_per_week", "load_level")):
        ft["schedule"] = sch
    subj = gaps.get("subject_status")
    if isinstance(subj, list):
        rows = [r for r in subj if isinstance(r, dict) and str(r.get("subject") or "").strip()]
        if rows:
            ft["subject_status"] = rows
    st = gaps.get("standard_task")
    if isinstance(st, dict) and st.get("can_split") is not None:
        ft["standard_task"] = st
    goal = gaps.get("goal")
    if isinstance(goal, dict):
        judgement = str(goal.get("judgement") or "").strip()
        text = str(goal.get("text") or "").strip()
        if judgement or text:
            ft["goal"] = {"text": text, "judgement": judgement}
    if ft:
        ev["ft"] = ft

    for key in ("observation", "task", "parent_extra"):
        val = payload.get(key)
        if key == "parent_extra":
            if isinstance(val, dict) and val:
                ev.setdefault("parent", {}).update(val)
        elif isinstance(val, dict) and val:
            ev[key] = val

    answers = payload.get("answers")
    if isinstance(answers, list) and answers:
        ev["answers"] = answers
    return ev


def recover_evidence(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从旧档案还原 evidence（evidence_log / gaps / answers 的反向映射）。"""
    if not profile:
        return None
    ev: Dict[str, Any] = {}
    for item in profile.get("evidence_log") or []:
        src = item.get("source")
        kind = item.get("kind")
        detail = item.get("detail")
        if src == "FT" and kind in ("schedule", "standard_task", "subject_status", "notes", "goal"):
            ev.setdefault("ft", {})[kind] = detail
        elif src == "FT" and kind == "task":
            ev["task"] = detail
        elif src == "家长" and kind == "complaint":
            # engine 的 detail 即 evidence["parent"] 整体（{"complaint": {...}} 等）
            parent = ev.setdefault("parent", {})
            if isinstance(detail, dict):
                parent.update(detail)
            else:
                parent["complaint"] = detail
        elif src == "观察" and kind == "record":
            ev["observation"] = detail
    answers = profile.get("answers") or []
    if answers:
        ev["answers"] = answers
    return ev or None


def merge_evidence(base: Optional[Dict[str, Any]],
                   new: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """旧证据 ← 新证据 深合并（新值覆盖同键）。"""
    if not base:
        return dict(new or {}) or None
    if not new:
        return dict(base)
    out = dict(base)
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_evidence(out[k], v) or {}
        else:
            out[k] = v
    return out


# ── v0.6 输入闭环与档案构建 ───────────────────────────────────
def inputs_from_profile(prev: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """档案 → v0.6 inputs。

    v0.6 档案：inputs 深拷贝；旧档案：从 evidence_log 还原 ft / parent
    （丢弃 answers / observation / task），talks 为空。
    """
    if not prev:
        return {"talks": {}}
    if prev.get("schema") == "6am.v0.6":
        inputs = copy.deepcopy(prev.get("inputs") or {})
        if not isinstance(inputs.get("talks"), dict):
            inputs["talks"] = {}
        return inputs
    ev = recover_evidence(prev) or {}
    out: Dict[str, Any] = {}
    if ev.get("ft"):
        out["ft"] = copy.deepcopy(ev["ft"])
    if ev.get("parent"):
        out["parent"] = copy.deepcopy(ev["parent"])
    out["talks"] = {}
    return out


def merge_inputs(base: Optional[Dict[str, Any]],
                 new: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """旧输入 ← 新输入：ft / parent 深合并；talks[dim] 整体替换（null = 删除）。"""
    out = copy.deepcopy(base or {})
    for key, value in (new or {}).items():
        if key == "talks":
            if not isinstance(out.get("talks"), dict):
                out["talks"] = {}
            for dim, record in (value or {}).items():
                if record is None:
                    out["talks"].pop(dim, None)
                else:
                    out["talks"][dim] = copy.deepcopy(record)
        elif isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_evidence(out[key], value) or {}
        else:
            out[key] = copy.deepcopy(value)
    return out


def build_v06_profile(report_id: int,
                      inputs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """只读重算 v0.6 档案（不落库）：测试与预览。报告不存在返回 None。"""
    from . import evaluator_v06
    from .model import load_model

    ctx = _assemble(int(report_id))
    if ctx is None:
        return None
    _record, items, student = ctx
    if inputs is None:
        inputs = inputs_from_profile(_latest_profile_dict(int(report_id)))
    return evaluator_v06.run(items, student, inputs, int(report_id), model=load_model())


def run_v06_for_report(report_id: int,
                       inputs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """按 v0.6 重算并落库（每次插入新行，version = 该学生档案数 + 1）。

    inputs 为空时继承最新档案（旧档案则回填 ft / parent）。返回 profile
    （附 profile_id / version）；报告不存在返回 None。
    """
    import db

    from . import evaluator_v06
    from .model import load_model

    ctx = _assemble(int(report_id))
    if ctx is None:
        return None
    record, items, student = ctx
    if inputs is None:
        inputs = inputs_from_profile(_latest_profile_dict(int(report_id)))
    profile = evaluator_v06.run(items, student, inputs, int(report_id), model=load_model())
    version = len(db.get_six_am_profiles_by_student(record["student_id"])) + 1
    pid = db.add_six_am_profile(record["student_id"], int(report_id),
                                json.dumps(profile, ensure_ascii=False), version)
    profile["profile_id"] = pid
    profile["version"] = version
    return profile