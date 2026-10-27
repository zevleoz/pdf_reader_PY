"""洞察蓝图：Dashboard、Y4 研判页、6AM 档案与规则。"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, render_template, request, send_file

import db as _db
from app_utils import (admin_required, page_login_required, report_scoped,
                       role_required)
from ai_client import _dashscope_chat

bp = Blueprint("insights", __name__)


@bp.route("/dashboard")
@bp.route("/insights/dashboard")
@page_login_required
def dashboard_page():
    return render_template("dashboard.html", nav_active="insights.dashboard")


@bp.route("/api/dashboard/stats")
@admin_required
def api_dashboard_stats():
    stats = _db.get_dashboard_stats()
    stats["indicators"] = _db.get_indicator_aggregates()
    stats["indicator_distributions"] = _db.get_indicator_distributions()
    stats["student_profiles"] = _db.get_student_profiles()
    stats["dimension_correlations"] = _db.get_dimension_correlations()
    stats["indicator_trends"] = _db.get_indicator_trends()
    stats["cluster_patterns"] = _db.get_cluster_patterns()
    stats["dimension_balance"] = _db.get_dimension_balance()
    return jsonify({"ok": True, "stats": stats})


@bp.route("/api/dashboard/ai-analysis")
@admin_required
def api_dashboard_ai_analysis():
    """AI 跨维度关联分析:基于分布、对比、关联三个维度,生成面向学生/家长的呈现式洞察。

    输出 JSON:dimension_summary + insights[{headline, detail, type}]
    """
    indicators = _db.get_indicator_aggregates()
    stats = _db.get_dashboard_stats()
    total_reports = stats["headline"]["total_reports"]
    total_students = stats["headline"]["total_students"]

    dim_summary = indicators.get("dimension_summary", {})
    distributions = _db.get_indicator_distributions()
    profiles = _db.get_student_profiles()
    correlations = _db.get_dimension_correlations()
    indicator_trends = _db.get_indicator_trends()
    cluster_patterns = _db.get_cluster_patterns()
    dimension_balance = _db.get_dimension_balance()

    # 1. 维度分布数据
    lines = [f"共 {total_reports} 份报告, {total_students} 名学生\n"]
    lines.append("【维度指标分布】")
    for dim in ["心力", "精力", "学习力", "生涯力"]:
        ds = dim_summary.get(dim, {})
        dist = distributions.get(dim, {})
        weak_names = ds.get("weak_names", [])
        line = f"{dim}: {dist.get('evaluated', 0)}/{dist.get('total', 0)} 个指标有评价"
        dist_dict = dist.get("distribution", {})
        if dist_dict:
            line += f", 评价分布: {dist_dict}"
        if weak_names:
            line += f", 常见偏弱项: {', '.join(weak_names)}"
        lines.append(line)
        # 补充该维度有评价的具体指标及其档位
        strong_inds = dist.get("strong_indicators", [])
        weak_inds = dist.get("weak_indicators", [])
        if strong_inds or weak_inds:
            ind_list = []
            for si in strong_inds[:5]:
                ind_list.append(f"{si['label']}(强项)")
            for wi in weak_inds[:5]:
                ind_list.append(f"{wi['label']}(偏弱 {wi.get('weak_pct', 0)}%)")
            lines.append(f"  - {dim} 具体指标: {', '.join(ind_list)}")

    # 2. 学生对比数据
    if profiles:
        lines.append("\n【学生对比】")
        for p in profiles:
            dims_str = ", ".join(
                f"{d}={p['dimensions'].get(d, {}).get('healthy', 0)}%" for d in ["心力", "精力", "学习力", "生涯力"]
            )
            tag = ""
            if p.get("is_healthiest"):
                tag = " (最健康)"
            elif p.get("is_needs_attention"):
                tag = " (需关注)"
            lines.append(f"{p['student_name']} ({p['grade']}){tag}: 整体健康度 {p['overall_health']}%, {dims_str}")

    # 3. 维度关联数据
    pairs = correlations.get("pairs", [])
    if pairs:
        lines.append("\n【维度间关联】")
        for pair in pairs:
            if pair["correlation"] > 0:
                lines.append(
                    f"{pair['dim_a']} 与 {pair['dim_b']}: 关联强度 {pair['correlation']} ({pair['strength']}), "
                    f"同时偏弱 {pair['co_weak']} 人"
                )

    # 4. 指标级趋势(具体指标,非维度汇总)
    weak_inds = indicator_trends.get("most_frequently_weak", [])[:5]
    if weak_inds:
        lines.append("\n【指标级趋势 — 最常偏弱的 5 个具体指标】")
        for ind in weak_inds:
            lines.append(
                f"{ind['label']} ({ind['dim']}): {ind['weak_count']}/{ind['total_count']} 人偏弱, "
                f"涉及学生: {', '.join(ind['weak_students'][:5])}"
            )

    # 5. 学生聚类画像
    clusters = cluster_patterns.get("clusters", [])
    if clusters:
        lines.append("\n【学生聚类画像 — 按弱项维度签名分组】")
        for c in clusters[:5]:
            lines.append(
                f"弱项组合「{c['signature']}」: {c['count']} 人, 平均健康度 {c['overall_health_avg']}%, "
                f"成员: {', '.join(c['students'][:5])}"
            )
    balanced = cluster_patterns.get("balanced_count", 0)
    if balanced > 0:
        lines.append(f"无弱项(均衡型): {balanced} 人")

    # 6. 维度平衡度
    bal_students = dimension_balance.get("students", [])
    if bal_students:
        lines.append("\n【维度平衡度】")
        lines.append(f"平均平衡度 {dimension_balance.get('avg_balance_score', 0)}, "
                     f"严重失衡学生 {dimension_balance.get('imbalanced_count', 0)} 人")
        for s in bal_students:
            if s.get("is_imbalanced"):
                lines.append(
                    f"{s['student_name']}: 平衡度 {s['balance_score']}, "
                    f"最弱维度 {s['weakest_dim']}, 最强维度 {s['strongest_dim']}, 差距 {s['gap']}"
                )

    data_summary = "\n".join(lines)

    system = f"""你是 Y4 测评项目的负责人,正在向学生和家长做成果汇报。基于聚合测评数据,提炼有价值的洞察。

【硬规则】
1. 禁止创造新术语、新标签、新分类,只用 Y4 已有词汇(心力/精力/学习力/生涯力)。
2. 禁止出现指标编号(如 009、063 等),只用指标的中文名称。
3. 禁止使用 markdown 格式(无 ### 标题、无 bullet 符号、无 ** 加粗)。
4. 用平实中文,面向非专业受众(学生和家长),语气自然,像一位老师在解读数据。
5. 每条洞察必须有数据依据,但不暴露原始编号。数据中不存在的结论不得编造。
6. 禁止心理学/治疗术语,禁止连字符组合造词。
7. 正确示例:"精力维度表现较弱的学生,在学习动机上也普遍偏低,说明身体状态直接影响学习投入"
8. 错误示例:"009 情绪稳定性总分偏低与 063 执行功能偏低同时出现"
9. 每条 insight 的 detail 必须至少引用一个数据中出现过的具体指标中文名称(如"睡眠习惯""焦虑安详""执行功能-工作记忆"),禁止只用维度名概括。
10. 禁止将多个指标打包成数据中不存在的组合名(如"情绪耗竭""认知负荷"),只能用"XX 维度的 XX 指标"这种指代方式。

【输出格式】
只输出一个 JSON 对象,不要输出其他文字。格式如下:
```json
{{
  "dimension_summary": "一段话(2-3句)总结四维整体健康度,指出哪个维度最强、哪个需要关注",
  "insights": [
    {{"headline": "一句话标题(10-20字)", "detail": "2-3句解释", "type": "distribution"}},
    {{"headline": "...", "detail": "...", "type": "comparison"}},
    {{"headline": "...", "detail": "...", "type": "correlation"}}
  ]
}}
```
type 取值:
- "distribution": 关于指标分布的洞察(某维度哪些指标普遍高/低)
- "comparison": 关于学生间差异的洞察(不同学生群体或个体差异)
- "correlation": 关于维度间关联的洞察(哪些维度经常一起弱/强)
- "indicator": 关于具体指标的洞察(哪个指标最常弱,影响哪些学生,为什么重要)
- "cluster": 关于学生群体结构的洞察(某类弱项组合的共性,这群学生有何特征)
- "leverage": 关于杠杆点的洞察(改善哪个维度/指标最能提升整体健康度)
生成 4-6 条 insights,尽量覆盖至少 4 种 type。"""

    user = f"【聚合数据】\n{data_summary}"

    model = os.environ.get("DASHBOARD_AI_MODEL", "qwen-turbo")
    timeout = int(os.environ.get("DASHBOARD_AI_TIMEOUT", "60"))

    try:
        r = _dashscope_chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            model=model, timeout=timeout, max_tokens=2000,
        )
        content = r["content"].strip()
        # 提取 JSON 代码块
        import re, json as _json
        m = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if not m:
            m = re.search(r"(\{.*\})", content, re.DOTALL)
        if m:
            parsed = _json.loads(m.group(1))
            return jsonify({
                "ok": True,
                "analysis": parsed,
                "stats": {"tokens": r["tokens"], "time_ms": r["time_ms"], "model": model},
            })
        else:
            return jsonify({
                "ok": True,
                "analysis": {"dimension_summary": content[:300], "insights": []},
                "stats": {"tokens": r["tokens"], "time_ms": r["time_ms"], "model": model},
            })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})
@bp.route("/y4-signals")
@bp.route("/insights/y4-signals")
@page_login_required
def y4_signals_page():
    """Y4 原生问题研判页（潜能/干预四名单，与 E4 平行的独立系统）。"""
    return render_template("y4_signals.html", nav_active="insights.y4-signals")
import six_am as _six_am
from six_am.export_json import build_six_am_json as _build_six_am_json
from six_am.render_docx import build_six_am_docx as _build_six_am_docx
from six_am import presentation as _six_am_presentation
from six_am import rules as _six_am_rules


def _six_am_profile_payload(rec: Dict) -> Dict:
    """DB 行 → 前端 payload（解析 profile_json，附版本时间线、上一版与团队评议）。"""
    from app_utils import current_user
    from six_am import history as _six_am_history

    try:
        prof = json.loads(rec.get("profile_json") or "{}")
    except Exception:
        prof = {}
    report_id = rec.get("report_id")
    versions: List[Dict] = []
    try:
        rows = [row for row in _db.get_six_am_profiles_by_student(rec.get("student_id"))
                if row.get("report_id") == report_id]
        versions = _six_am_history.timeline(rows)
    except Exception:
        versions = []
    previous_states = None
    try:
        prev = _db.get_previous_six_am_profile(rec.get("id"))
        if prev:
            prev_prof = json.loads(prev.get("profile_json") or "{}")
            prev_dims = prev_prof.get("dimensions") or {}
            previous_states = {dim: (prev_dims.get(dim) or {}).get("state")
                               for dim in ("A1", "A2", "A3", "A4", "A5")}
    except Exception:
        previous_states = None
    report_date = None
    try:
        for row in _db.get_student_reports(rec.get("student_id")):
            if row.get("id") == report_id:
                report_date = row.get("report_date")
                break
    except Exception:
        report_date = None
    try:
        reviews = _db.latest_six_am_reviews(rec.get("id"))
    except Exception:
        reviews = {}
    return {
        "profile_id": rec.get("id"),
        "version": rec.get("version"),
        "created_at": rec.get("created_at"),
        "report_id": report_id,
        "report_date": report_date,
        "student_id": rec.get("student_id"),
        "can_write": current_user().get("role") != "viewer",
        "profile": prof,
        "versions": versions,
        "previous_states": previous_states,
        "reviews": reviews,
        "view_model": _six_am_presentation.build_view_model(prof),
    }


def _six_am_pick_profile(report_id: int) -> Optional[Dict]:
    pid = request.args.get("profile_id")
    if pid:
        try:
            return _db.get_six_am_profile(int(pid))
        except (TypeError, ValueError):
            return None
    return _db.get_latest_six_am_profile(report_id)


def _six_am_rule_specs() -> List[Dict]:
    """规则条件声明（面板展示与覆盖编辑的锚点，含 X 规则）。"""
    specs = []
    for rid in _six_am_rules.RULE_IDS:
        r = _six_am_rules.RULES.get(rid) or {}
        specs.append({"id": rid, "dim": r.get("dim") or "", "title": r.get("title") or "",
                      "when": r.get("when") or [], "then": r.get("then") or {},
                      "questions": r.get("questions") or [], "text": r.get("text") or ""})
    for rid in _six_am_rules.CROSS_RULE_IDS:
        r = _six_am_rules.CROSS_RULES.get(rid) or {}
        specs.append({"id": rid, "dim": "X", "title": r.get("title") or "",
                      "when": [], "then": {}, "questions": [],
                      "text": r.get("action") or "", "cross": True})
    return specs


@bp.route("/six-am")
@bp.route("/insights/six-am")
@page_login_required
def six_am_page():
    return render_template("six_am.html", nav_active="insights.six-am")


@bp.route("/six-am/rules")
@bp.route("/insights/six-am/rules")
@role_required('admin')
def six_am_rules_page():
    return render_template("six_am_rules.html", nav_active="insights.six-am")


@bp.route("/api/reports/<int:report_id>/six-am")
@admin_required
@report_scoped
def api_report_six_am(report_id):
    """取档案（?profile_id= 指定版本，默认最新）。"""
    rec = _six_am_pick_profile(report_id)
    if not rec:
        return jsonify({"ok": False, "error": "尚无 6AM 档案"}), 404
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


@bp.route("/api/reports/<int:report_id>/six-am/generate", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_generate(report_id):
    """手动重跑（body {rule_version_id?, profile_id?}，沿用旧档案录入数据）。"""
    data = request.get_json(silent=True) or {}
    source_profile = None
    if data.get("profile_id"):
        try:
            prec = _db.get_six_am_profile(int(data["profile_id"]))
            if prec:
                source_profile = json.loads(prec.get("profile_json") or "{}")
        except (TypeError, ValueError):
            source_profile = None
    try:
        prof = _six_am.run_for_report(report_id, rule_version_id=data.get("rule_version_id"),
                                      source_profile=source_profile)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"6AM 生成失败: {exc}"}), 500
    if prof is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    rec = _db.get_six_am_profile(prof.get("profile_id"))
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


@bp.route("/api/reports/<int:report_id>/six-am/answers", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_answers(report_id):
    """保存追问答案 + 四类缺口字段 → 重跑 → 返回新档案（版本 +1）。"""
    data = request.get_json(force=True) or {}
    prev = _db.get_latest_six_am_profile(report_id)
    prev_prof = None
    if prev:
        try:
            prev_prof = json.loads(prev.get("profile_json") or "{}")
        except Exception:
            prev_prof = None
    base = _six_am.recover_evidence(prev_prof)
    evidence = _six_am.merge_evidence(base, _six_am.evidence_from_payload(data))
    answers = data.get("answers")
    if not isinstance(answers, list):
        answers = None  # 未提交答案时沿用旧档案
    try:
        prof = _six_am.run_for_report(report_id, evidence=evidence, answers=answers)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"6AM 重跑失败: {exc}"}), 500
    if prof is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    rec = _db.get_six_am_profile(prof.get("profile_id"))
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


# ── 概览 / 预览 / 团队评议（6AM 2.0）────────────────────────────
_COHORT_DIMS = ("A1", "A2", "A3", "A4", "A5")
_COHORT_STATES = ("Secure", "Watch", "At-Risk", "Blocked")
_REVIEW_VERDICTS = ("agree", "adjust", "evidence")


@bp.route("/api/six-am/cohort")
@admin_required
def api_six_am_cohort():
    """概览：当前可见学生的最新档案摘要 + 五维状态分布（advisor 仅限名下）。"""
    from app_utils import _advisor_scope

    students: List[Dict] = []
    distribution = {dim: {state: 0 for state in _COHORT_STATES} for dim in _COHORT_DIMS}
    for rec in _db.list_latest_six_am_profiles(_advisor_scope()):
        try:
            prof = json.loads(rec.get("profile_json") or "{}")
        except Exception:
            prof = {}
        vm = _six_am_presentation.build_view_model(prof)
        cards = {c.get("dim"): c for c in (vm.get("cards") or [])}
        dims = prof.get("dimensions") or {}
        states: Dict[str, Optional[str]] = {}
        evidence: Dict[str, Optional[str]] = {}
        missing: List[str] = []
        for dim in _COHORT_DIMS:
            rec_dim = dims.get(dim) or {}
            state = str(rec_dim.get("state") or "Secure")
            states[dim] = state
            evidence[dim] = rec_dim.get("confidence")
            if "Y4 数据缺失" in (rec_dim.get("flags") or []):
                missing.append(dim)
            if state in distribution[dim]:
                distribution[dim][state] += 1
        subtypes = {dim: (cards.get(dim) or {}).get("subtype_display")
                    for dim in _COHORT_DIMS}
        plan = prof.get("support_plan") or (dims.get("A6") or {}).get("support_ranking") or {}
        ranked = [e for e in (plan.get("ranked") or [])
                  if isinstance(e, dict) and e.get("direction")]
        a6_top = next((str(e["direction"]) for e in ranked
                       if str(e.get("fit_label") or "") == "优先"), None)
        if a6_top is None and ranked:
            a6_top = str(ranked[0]["direction"])
        previous_states = None
        prev = _db.get_previous_six_am_profile(rec.get("id"))
        if prev:
            try:
                prev_dims = json.loads(prev.get("profile_json") or "{}").get("dimensions") or {}
            except Exception:
                prev_dims = {}
            previous_states = {dim: (prev_dims.get(dim) or {}).get("state")
                               for dim in _COHORT_DIMS}
        reviews = _db.latest_six_am_reviews(rec.get("id"))
        at_risk = [dim for dim in _COHORT_DIMS
                   if states.get(dim) in ("At-Risk", "Blocked")]
        if not at_risk:
            review_status = "none"
        elif all(dim in reviews for dim in at_risk):
            review_status = "reviewed"
        else:
            review_status = "pending"
        students.append({
            "student_id": rec.get("student_id"),
            "name": rec.get("name") or "",
            "grade": rec.get("grade") or "",
            "report_id": rec.get("report_id"),
            "report_date": rec.get("report_date"),
            "profile_id": rec.get("id"),
            "version": rec.get("version"),
            "states": states,
            "evidence": evidence,
            "subtypes": subtypes,
            "previous_states": previous_states,
            "safety": bool(prof.get("safety_review")),
            "missing": missing,
            "order": prof.get("priority_order") or (vm.get("summary") or {}).get(
                "priority_order") or [],
            "a6_top": a6_top,
            "reviews": reviews,
            "review_status": review_status,
        })
    return jsonify({"ok": True, "students": students, "distribution": distribution})


@bp.route("/api/reports/<int:report_id>/six-am/preview", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_preview(report_id):
    """演练：与 answers 同输入，调用 build_profile 只重算、不落库。"""
    from six_am import history as _six_am_history

    data = request.get_json(force=True) or {}
    prev = _db.get_latest_six_am_profile(report_id)
    prev_prof = None
    if prev:
        try:
            prev_prof = json.loads(prev.get("profile_json") or "{}")
        except Exception:
            prev_prof = None
    evidence = _six_am.merge_evidence(_six_am.recover_evidence(prev_prof),
                                      _six_am.evidence_from_payload(data))
    answers = data.get("answers")
    if not isinstance(answers, list):
        answers = None
    try:
        prof = _six_am.build_profile(report_id, evidence=evidence, answers=answers,
                                     source_profile=prev_prof)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"6AM 预览失败: {exc}"}), 500
    if prof is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    return jsonify({"ok": True,
                    "view_model": _six_am_presentation.build_view_model(prof),
                    "changes": _six_am_history.diff_profiles(prev_prof, prof)})


@bp.route("/api/reports/<int:report_id>/six-am/reviews", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_reviews(report_id):
    """记录团队评议（只追加：不改模型判定、不新增档案版本）。"""
    import datetime as _dt

    import app_utils as _app_utils

    data = request.get_json(silent=True) or {}
    try:
        profile_id = int(data.get("profile_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "缺少有效的档案 ID"}), 400
    rec = _db.get_six_am_profile(profile_id)
    if not rec or int(rec.get("report_id") or 0) != int(report_id):
        return jsonify({"ok": False, "error": "档案不属于该报告"}), 400
    dim = str(data.get("dim") or "").strip()
    if dim not in _COHORT_DIMS:
        return jsonify({"ok": False, "error": "维度必须是 A1–A5"}), 400
    verdict = str(data.get("verdict") or "").strip()
    if verdict not in _REVIEW_VERDICTS:
        return jsonify({"ok": False, "error": "结论必须是 agree、adjust 或 evidence"}), 400
    adjusted_state = data.get("adjusted_state")
    if verdict == "adjust":
        if adjusted_state not in _COHORT_STATES:
            return jsonify({"ok": False, "error": "调整为 X 时必须给出有效状态"}), 400
    else:
        adjusted_state = None
    note = "" if data.get("note") is None else str(data.get("note"))
    if len(note) > 500:
        return jsonify({"ok": False, "error": "备注最多 500 字"}), 400
    owner = "" if data.get("owner") is None else str(data.get("owner"))
    if len(owner) > 50:
        return jsonify({"ok": False, "error": "负责人最多 50 字"}), 400
    due_date = "" if data.get("due_date") is None else str(data.get("due_date")).strip()
    if due_date:
        try:
            _dt.datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "截止日期格式必须是 YYYY-MM-DD"}), 400
    user = _app_utils.current_user()
    author = user.get("display_name") or str(user.get("user_id") or "")
    review = _db.add_six_am_review(
        profile_id=profile_id, report_id=int(report_id), dim=dim, verdict=verdict,
        adjusted_state=adjusted_state, note=note, owner=owner,
        due_date=due_date, author=author)
    return jsonify({"ok": True, "review": review})


# ── 人工行动修订（不新增版本，就地更新当前档案）───────────────────
_OVERRIDE_DIMS = ("A1", "A2", "A3", "A4", "A5", "A6")
_OVERRIDE_MAX_ITEMS = 8
_OVERRIDE_MAX_LEN = 300


def _validate_action_list(value, field: str):
    """校验行动数组：None → []；≤8 条、每条为 ≤300 字的非空字符串。

    返回 (items, error)；error 非 None 时 items 为 None。
    """
    if value is None:
        return [], None
    if not isinstance(value, list):
        return None, f"{field} 必须是字符串数组"
    if len(value) > _OVERRIDE_MAX_ITEMS:
        return None, f"{field} 最多 {_OVERRIDE_MAX_ITEMS} 条"
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None, f"{field} 含空或非字符串条目"
        if len(item) > _OVERRIDE_MAX_LEN:
            return None, f"{field} 单条最多 {_OVERRIDE_MAX_LEN} 字"
        items.append(item.strip())
    return items, None


@bp.route("/api/reports/<int:report_id>/six-am/action-overrides", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_action_overrides(report_id):
    """保存某维度的人工行动修订：就地更新当前档案，版本号不变，不写修订日志。"""
    data = request.get_json(silent=True) or {}
    try:
        profile_id = int(data.get("profile_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "profile_id 必填"}), 400
    rec = _db.get_six_am_profile(profile_id)
    if not rec or rec.get("report_id") != report_id:
        return jsonify({"ok": False, "error": "档案不存在或不属于该报告"}), 404
    dim = str(data.get("dim") or "").strip()
    if dim not in _OVERRIDE_DIMS:
        return jsonify({"ok": False, "error": "dim 必须是 A1–A6 之一"}), 400
    next_actions, err = _validate_action_list(data.get("next_actions"), "next_actions")
    if err:
        return jsonify({"ok": False, "error": err}), 400
    avoid_actions, err = _validate_action_list(data.get("avoid_actions"), "avoid_actions")
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        prof = json.loads(rec.get("profile_json") or "{}")
    except Exception:
        prof = {}
    overrides = prof.get("action_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    # 空数组保留为空 override：展示层回退到生成结果（Task 3 既定语义）
    overrides[dim] = {"next_actions": next_actions, "avoid_actions": avoid_actions}
    prof["action_overrides"] = overrides
    if not _db.update_six_am_profile_json(profile_id,
                                          json.dumps(prof, ensure_ascii=False)):
        return jsonify({"ok": False, "error": "档案更新失败"}), 500
    rec = _db.get_six_am_profile(profile_id)
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


@bp.route("/api/reports/<int:report_id>/six-am/docx")
@admin_required
@report_scoped
def api_report_six_am_docx(report_id):
    """下载 Word 档案（紧凑摘要 / 六维行动卡 / 待确认问题 / 规则审计附录）。"""
    import io as _io
    rec = _six_am_pick_profile(report_id)
    if not rec:
        return jsonify({"ok": False, "error": "尚无 6AM 档案"}), 404
    try:
        prof = json.loads(rec.get("profile_json") or "{}")
        blob = _build_six_am_docx(prof)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"DOCX 生成失败: {exc}"}), 500
    name = str((prof.get("student") or {}).get("name") or "学生")
    name = name.replace("/", "_").replace("\\", "_").replace(" ", "")
    return send_file(_io.BytesIO(blob),
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     as_attachment=True, download_name=f"6AM启动档案_{name}.docx")


@bp.route("/api/reports/<int:report_id>/six-am/json")
@admin_required
@report_scoped
def api_report_six_am_json(report_id):
    """下载 JSON 档案（机器可读，锚点=规则 ID）。"""
    rec = _six_am_pick_profile(report_id)
    if not rec:
        return jsonify({"ok": False, "error": "尚无 6AM 档案"}), 404
    prof = json.loads(rec.get("profile_json") or "{}")
    payload = _build_six_am_json(prof)
    name = str((prof.get("student") or {}).get("name") or "学生")
    name = name.replace(" ", "").replace("/", "_")
    return jsonify({"ok": True, "json": payload, "filename": f"6AM数据_{name}.json"})


@bp.route("/api/six-am/rule-versions")
@role_required('admin')
def api_six_am_rule_versions():
    """版本列表 + 参数默认值 + 规则声明（规则面板数据源）。"""
    targets = []
    for rid in _db.get_six_am_report_ids():
        latest = _db.get_latest_six_am_profile(rid)
        if not latest:
            continue
        try:
            prof = json.loads(latest.get("profile_json") or "{}")
        except Exception:
            prof = {}
        targets.append({"report_id": rid,
                        "student_name": (prof.get("student") or {}).get("name") or "",
                        "version": latest.get("version")})
    return jsonify({
        "ok": True,
        "versions": _db.list_six_am_rule_versions(),
        "defaults": _six_am.default_params(),
        "rule_ids": list(_six_am_rules.RULE_IDS),
        "cross_rule_ids": list(_six_am_rules.CROSS_RULE_IDS),
        "question_ids": list(_six_am_rules.QUESTION_IDS),
        "rule_specs": _six_am_rule_specs(),
        "targets": targets,
    })


@bp.route("/api/six-am/rule-versions", methods=["POST"])
@role_required('admin')
def api_six_am_rule_versions_save():
    """保存 draft 版本（body：params + rule_overrides + label）。"""
    data = request.get_json(force=True) or {}
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    overrides = data.get("rule_overrides") if isinstance(data.get("rule_overrides"), dict) else {}
    label = str(data.get("label") or "").strip()
    if not label:
        label = time.strftime("draft-%Y%m%d-%H%M%S")
    vid = _db.save_six_am_rule_version(
        label, json.dumps({"params": params, "rule_overrides": overrides}, ensure_ascii=False))
    return jsonify({"ok": True, "version_id": vid, "versions": _db.list_six_am_rule_versions()})


@bp.route("/api/six-am/rule-versions/<int:vid>/publish", methods=["POST"])
@role_required('admin')
def api_six_am_rule_version_publish(vid):
    """draft → published（旧 published → archived）。"""
    if not _db.get_six_am_rule_version(vid):
        return jsonify({"ok": False, "error": "版本不存在"}), 404
    _db.publish_six_am_rule_version(vid)
    return jsonify({"ok": True, "versions": _db.list_six_am_rule_versions()})


@bp.route("/api/six-am/sandbox", methods=["POST"])
@role_required('admin')
def api_six_am_sandbox():
    """沙盒：用指定版本逐份只读重跑，与最新已存档案对比；不落库。"""
    data = request.get_json(force=True) or {}
    vid = data.get("rule_version_id")
    rv = None
    if vid:
        try:
            rv = _db.get_six_am_rule_version(int(vid))
        except (TypeError, ValueError):
            rv = None
    if not rv:
        return jsonify({"ok": False, "error": "规则版本不存在"}), 404
    try:
        payload = json.loads(rv.get("params_json") or "{}")
    except Exception:
        payload = {}
    params = payload.get("params") or {}
    overrides = payload.get("rule_overrides") or {}
    meta = {"id": rv.get("id"), "label": rv.get("label"), "status": rv.get("status")}

    target = data.get("report_ids")
    if target in (None, "all"):
        report_ids = _db.get_six_am_report_ids()
    else:
        report_ids = [int(x) for x in target if str(x).strip().isdigit()]

    results = []
    for rid in report_ids:
        prev = _db.get_latest_six_am_profile(rid)
        prev_prof = None
        if prev:
            try:
                prev_prof = json.loads(prev.get("profile_json") or "{}")
            except Exception:
                prev_prof = None
        try:
            prof = _six_am.build_profile(rid, params=params, rule_overrides=overrides,
                                         rule_version=meta, source_profile=prev_prof)
        except Exception as exc:
            results.append({"report_id": rid, "error": str(exc)})
            continue
        if prof is None:
            continue
        old_dims = (prev_prof or {}).get("dimensions") or {}
        new_dims = prof.get("dimensions") or {}
        old_states, new_states, changed, details = {}, {}, [], {}
        for dim in ("A1", "A2", "A3", "A4", "A5"):
            os_ = str((old_dims.get(dim) or {}).get("state") or "Secure")
            ns_ = str((new_dims.get(dim) or {}).get("state") or "Secure")
            old_states[dim] = os_
            new_states[dim] = ns_
            if os_ != ns_:
                changed.append(dim)
                details[dim] = {
                    "old_rules": [t.get("id") for t in
                                  ((old_dims.get(dim) or {}).get("triggered_rules") or [])],
                    "new_rules": [t.get("id") for t in
                                  ((new_dims.get(dim) or {}).get("triggered_rules") or [])],
                }
        results.append({
            "report_id": rid,
            "student_name": (prof.get("student") or {}).get("name") or "",
            "old_states": old_states, "new_states": new_states,
            "changed_dims": changed, "details": details,
        })
    return jsonify({"ok": True, "rule_version": meta, "results": results})


# ─── 6AM 规则板（Q4）────────────────────────────────────────────
_BOARD_PARAM_META = {
    "top_n_values": ("职业价值观前 N 位", 1, 15),
    "top_n_safety": ("安全稳定前 N 位", 1, 15),
    "control_low_max": ("掌控感低端上限", 0, 100),
    "control_high_min": ("掌控感高端下限", 0, 100),
    "mindset_low_max": ("思维模式阈值", 0, 100),
    "cog_pct_min": ("认知能力百分位阈值", 0, 100),
    "schedule_free_hours_max": ("每周自由时间下限（小时）", 0, 100),
}


def _board_spec_of(version: Optional[Dict]) -> Optional[Dict]:
    """版本 params_json 里的 params.spec；缺失/损坏返回 None。"""
    if not version:
        return None
    try:
        payload = json.loads(version.get("params_json") or "{}")
    except Exception:
        payload = {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    spec = params.get("spec")
    return spec if isinstance(spec, dict) else None


def _board_versions():
    """返回 (全部版本, 当前 published, 全部 draft)。"""
    versions = _db.list_six_am_rule_versions()
    published = next((v for v in versions if v.get("status") == "published"), None)
    drafts = [v for v in versions if v.get("status") == "draft"]
    return versions, published, drafts


def _board_base_spec(base_version_id=None) -> Dict:
    """合并基准：指定版本 → 当前 published → DEFAULT_SPEC。"""
    from six_am.spec import DEFAULT_SPEC

    if base_version_id:
        try:
            base = _board_spec_of(_db.get_six_am_rule_version(int(base_version_id)))
        except (TypeError, ValueError):
            base = None
        if base:
            return base
    _versions, published, _drafts = _board_versions()
    base = _board_spec_of(published)
    return base or json.loads(json.dumps(DEFAULT_SPEC))


@bp.route("/insights/six-am/board")
@page_login_required
def six_am_board_page():
    return render_template("six_am_board.html", nav_active="insights.six-am")


@bp.route("/api/six-am/board")
@admin_required
def api_six_am_board():
    """规则板数据源：当前 spec、信号库、参数元信息、版本列表。读操作对所有角色开放。"""
    from flask import session
    from six_am.spec import DEFAULT_SPEC
    from six_am.signals import SIGNALS

    _versions, published, drafts = _board_versions()
    chosen = None
    vid = request.args.get("version_id")
    if vid:
        try:
            chosen = _db.get_six_am_rule_version(int(vid))
        except (TypeError, ValueError):
            chosen = None
    if not chosen:
        chosen = published
    spec = _board_spec_of(chosen) or _board_spec_of(published)
    if not spec:
        spec = json.loads(json.dumps(DEFAULT_SPEC))

    return jsonify({
        "ok": True,
        "can_edit": session.get("role") == "admin",
        "published": ({"id": published["id"], "label": published["label"]}
                      if published else None),
        "drafts": [{"id": v["id"], "label": v["label"], "created_at": v.get("created_at")}
                   for v in drafts],
        "version": ({"id": chosen["id"], "label": chosen["label"],
                     "status": chosen["status"]} if chosen else None),
        "spec": spec,
        "signals": [dict(SIGNALS[sid]) for sid in SIGNALS],
        "param_meta": {name: {"label": label, "min": lo, "max": hi, "step": 1}
                       for name, (label, lo, hi) in _BOARD_PARAM_META.items()},
    })


@bp.route("/api/six-am/board", methods=["POST"])
@role_required('admin')
def api_six_am_board_save():
    """保存规则板编辑为 draft 版本（只合入可编辑字段）。"""
    from six_am.spec import merge_edit, validate

    data = request.get_json(force=True) or {}
    edited = data.get("spec") if isinstance(data.get("spec"), dict) else {}
    base = _board_base_spec(data.get("base_version_id"))
    merged = merge_edit(base, edited)
    errors = validate(merged)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    label = str(data.get("label") or "").strip() or time.strftime("board-%Y%m%d-%H%M%S")
    vid = _db.save_six_am_rule_version(
        label,
        json.dumps({"params": {"spec": merged, "engine": "v0.5"}, "rule_overrides": {}},
                   ensure_ascii=False))
    return jsonify({"ok": True, "version_id": vid})


@bp.route("/api/six-am/board/preview", methods=["POST"])
@role_required('admin')
def api_six_am_board_preview():
    """规则板预览：逐份只读重跑，对比 published 分布；不落库。"""
    from six_am.spec import merge_edit, validate

    data = request.get_json(force=True) or {}
    edited = data.get("spec") if isinstance(data.get("spec"), dict) else {}
    base = _board_base_spec()
    merged = merge_edit(base, edited)
    errors = validate(merged)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    dims = ("A1", "A2", "A3", "A4", "A5")
    levels = ("Secure", "Watch", "At-Risk", "Blocked")
    distribution = {dim: {lv: 0 for lv in levels} for dim in dims}
    published_distribution = {dim: {lv: 0 for lv in levels} for dim in dims}
    changed = []
    for rid in _db.get_six_am_report_ids():
        try:
            new_prof = _six_am.build_profile(rid, params={"spec": merged, "engine": "v0.5"})
            old_prof = _six_am.build_profile(rid, params={"spec": base, "engine": "v0.5"})
        except Exception:
            continue
        if new_prof is None or old_prof is None:
            continue
        new_dims = new_prof.get("dimensions") or {}
        old_dims = old_prof.get("dimensions") or {}
        diff = {}
        for dim in dims:
            new_state = str((new_dims.get(dim) or {}).get("state") or "Secure")
            old_state = str((old_dims.get(dim) or {}).get("state") or "Secure")
            distribution[dim][new_state] = distribution[dim].get(new_state, 0) + 1
            published_distribution[dim][old_state] = \
                published_distribution[dim].get(old_state, 0) + 1
            if new_state != old_state:
                diff[dim] = [old_state, new_state]
        if diff:
            changed.append({"report_id": rid,
                            "name": (new_prof.get("student") or {}).get("name") or "",
                            "dims": diff})

    return jsonify({"ok": True,
                    "distribution": distribution,
                    "published_distribution": published_distribution,
                    "changed": changed})
