"""洞察蓝图：Dashboard、Y4 研判页、6AM 档案与规则。"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, List, Optional

from flask import Blueprint, Response, jsonify, redirect, render_template, request

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
from six_am.model import export_md as _six_am_export_md
from six_am.model import load_model as _six_am_load_model

_COHORT_DIMS = ("A1", "A2", "A3", "A4", "A5")
_LEGACY_LEVELS = {"Secure": "稳固", "Watch": "关注", "At-Risk": "风险", "Blocked": "阻塞"}
_TALK_RESULTS = ("confirm", "deny", "set")
_TALK_LEVELS = ("稳固", "关注", "风险", "阻塞")


def _six_am_profile_payload(rec: Dict) -> Dict:
    """DB 行 → 前端 payload（v0.6：档案 + 版本时间线 + 报告日期 + 旧规则标记）。"""
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
    report_date = None
    try:
        for row in _db.get_student_reports(rec.get("student_id")):
            if row.get("id") == report_id:
                report_date = row.get("report_date")
                break
    except Exception:
        report_date = None
    return {
        "profile_id": rec.get("id"),
        "version": rec.get("version"),
        "report_id": report_id,
        "report_date": report_date,
        "legacy": prof.get("schema") != "6am.v0.6",
        "profile": prof,
        "versions": versions,
    }


def _six_am_pick_profile(report_id: int) -> Optional[Dict]:
    pid = request.args.get("profile_id")
    if pid:
        try:
            return _db.get_six_am_profile(int(pid))
        except (TypeError, ValueError):
            return None
    return _db.get_latest_six_am_profile(report_id)


@bp.route("/six-am")
@bp.route("/insights/six-am")
@page_login_required
def six_am_page():
    return render_template("six_am.html", nav_active="insights.six-am")


@bp.route("/six-am/rules")
@bp.route("/insights/six-am/rules")
@bp.route("/insights/six-am/board")
@page_login_required
def six_am_rules_redirect():
    """规则板 / 规则页退役：统一回到总览的规则视图。"""
    return redirect("/insights/six-am?view=rules")


@bp.route("/api/six-am/model")
@admin_required
def api_six_am_model():
    """v0.6 模型 JSON（页面规则视图的数据源）。"""
    return jsonify({"ok": True, "model": _six_am_load_model()})


@bp.route("/api/six-am/model.md")
@admin_required
def api_six_am_model_md():
    """下载思维导图 Markdown。"""
    resp = Response(_six_am_export_md(_six_am_load_model()), mimetype="text/markdown")
    resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
    resp.headers["Content-Disposition"] = \
        "attachment; filename*=UTF-8''6am-mindmap-v0.6.md"
    return resp


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
    """按 v0.6 重跑（沿用已存 inputs；旧档案回填 ft / parent）。"""
    try:
        prof = _six_am.run_v06_for_report(report_id)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"6AM 生成失败: {exc}"}), 500
    if prof is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    rec = _db.get_six_am_profile(prof.get("profile_id"))
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


def _validate_talks(raw, model: Dict) -> Dict:
    """校验并规范化会谈记录；返回 (talks, error)。"""
    if raw is None:
        return {}, None
    if not isinstance(raw, dict):
        return None, "talks 必须是对象"
    cause_ids: Dict[str, set] = {}
    for dim in model.get("dims") or []:
        cause_ids[str(dim.get("id"))] = {
            str((cause or {}).get("id"))
            for cause in ((dim.get("blocked") or {}).get("causes") or [])}
    today = _dt.date.today().isoformat()
    out: Dict[str, Dict] = {}
    for key, record in raw.items():
        dim = str(key)
        if dim not in _COHORT_DIMS:
            return None, "会谈记录的维度必须是 A1–A5"
        if record is None:
            out[dim] = None  # null 删除该维会谈记录
            continue
        if not isinstance(record, dict):
            return None, f"{dim} 的会谈记录必须是对象"
        result = str(record.get("result") or "").strip()
        if result not in _TALK_RESULTS:
            return None, f"{dim} 的会谈结论必须是 confirm、deny 或 set"
        clean: Dict = {"result": result}
        if result == "set":
            set_level = str(record.get("set_level") or "").strip()
            if set_level not in _TALK_LEVELS:
                return None, f"{dim} 调整为某级时必须给出有效级别"
            clean["set_level"] = set_level
        causes = record.get("causes")
        if causes is None:
            causes = []
        if not isinstance(causes, list):
            return None, f"{dim} 的归因必须是数组"
        picked: List[str] = []
        for cid in causes:
            cid = str(cid)
            if cid not in cause_ids.get(dim, set()):
                return None, f"{dim} 的归因无效：{cid}"
            picked.append(cid)
        clean["causes"] = picked
        note = "" if record.get("note") is None else str(record.get("note"))
        if len(note) > 500:
            return None, f"{dim} 的会谈备注最多 500 字"
        clean["note"] = note
        clean["at"] = today
        out[dim] = clean
    return out, None


@bp.route("/api/reports/<int:report_id>/six-am/inputs", methods=["POST"])
@admin_required
@report_scoped
def api_report_six_am_inputs(report_id):
    """合并 First Touch / 家长 / 会谈输入 → 重跑 → 返回新档案（版本 +1）。"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体必须是对象"}), 400
    talks, err = _validate_talks(data.get("talks"), _six_am_load_model())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    new_inputs: Dict = {"talks": talks}
    for key in ("ft", "parent"):
        if data.get(key) is not None:
            if not isinstance(data[key], dict):
                return jsonify({"ok": False, "error": f"{key} 必须是对象"}), 400
            new_inputs[key] = data[key]
    prev = None
    latest = _db.get_latest_six_am_profile(report_id)
    if latest:
        try:
            prev = json.loads(latest.get("profile_json") or "{}")
        except Exception:
            prev = None
    merged = _six_am.merge_inputs(_six_am.inputs_from_profile(prev), new_inputs)
    try:
        prof = _six_am.run_v06_for_report(report_id, inputs=merged)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"6AM 重跑失败: {exc}"}), 500
    if prof is None:
        return jsonify({"ok": False, "error": "报告不存在"}), 404
    rec = _db.get_six_am_profile(prof.get("profile_id"))
    return jsonify({"ok": True, **_six_am_profile_payload(rec)})


# ── 概览（6AM v0.6）────────────────────────────────────────────
def _legacy_level(prof: Dict, dim: str) -> str:
    state = ((prof.get("dimensions") or {}).get(dim) or {}).get("state")
    return _LEGACY_LEVELS.get(str(state or "Secure"), "稳固")


@bp.route("/api/six-am/cohort")
@admin_required
def api_six_am_cohort():
    """概览：当前可见学生的最新档案摘要（advisor 仅限名下）。"""
    from app_utils import _advisor_scope

    model_version = str(_six_am_load_model().get("version") or "")
    students: List[Dict] = []
    for rec in _db.list_latest_six_am_profiles(_advisor_scope()):
        try:
            prof = json.loads(rec.get("profile_json") or "{}")
        except Exception:
            prof = {}
        legacy = prof.get("schema") != "6am.v0.6"
        levels: Dict[str, Optional[str]] = {}
        types: Dict[str, Optional[str]] = {}
        needs_talk: List[str] = []
        blocked: List[str] = []
        if legacy:
            for dim in _COHORT_DIMS:
                levels[dim] = _legacy_level(prof, dim)
                types[dim] = None
            a6_top: List[str] = []
            safety = bool(prof.get("safety_review"))
        else:
            dims = prof.get("dims") or {}
            talks = (prof.get("inputs") or {}).get("talks") or {}
            for dim in _COHORT_DIMS:
                record = dims.get(dim) or {}
                level = record.get("level")
                levels[dim] = level
                names = [str(name) for name in (record.get("types") or []) if name]
                types[dim] = "、".join(names) if names else None
                if level == "阻塞":
                    blocked.append(dim)
                if level in ("风险", "阻塞") and dim not in talks:
                    needs_talk.append(dim)
            ranked = (prof.get("a6") or {}).get("ranked") or []
            a6_top = [str(entry.get("name") or "") for entry in ranked
                      if entry.get("top")][:4]
            safety = bool((prof.get("flags") or {}).get("safety"))
        students.append({
            "student_id": rec.get("student_id"),
            "name": rec.get("name") or "",
            "grade": rec.get("grade") or "",
            "report_id": rec.get("report_id"),
            "report_date": rec.get("report_date"),
            "profile_id": rec.get("id"),
            "version": rec.get("version"),
            "legacy": legacy,
            "levels": levels,
            "types": types,
            "needs_talk": needs_talk,
            "blocked": blocked,
            "a6_top": a6_top,
            "safety": safety,
        })
    return jsonify({"ok": True, "model_version": model_version, "students": students})


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


@bp.route("/api/six-am/rerun-all", methods=["POST"])
@role_required('admin')
def api_six_am_rerun_all():
    """管理员：对每个已有 6AM 档案的报告按 v0.6 重算（失败集中返回）。"""
    count = 0
    failed: List[int] = []
    for report_id in _db.get_six_am_report_ids():
        try:
            if _six_am.run_v06_for_report(int(report_id)) is None:
                failed.append(int(report_id))
            else:
                count += 1
        except Exception:
            failed.append(int(report_id))
    return jsonify({"ok": True, "count": count, "failed": failed})


