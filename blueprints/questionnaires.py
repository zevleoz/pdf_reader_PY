"""问卷中心蓝图（Agent C，3 指令包 §5.5）。

包含两块：

- 管理端页面：``/questionnaires/bank``（题库）；任务页已并入 ``/workspace``（16 包）
- 管理端 API：前缀 ``/api/questionnaires``
- 学生端：``/q/<token>``（一次性链接）与 ``/student/*``（临时账号），
  使用独立 session key ``student_account_id`` / ``student_id``。

鉴权：管理端沿用 ``app_utils.role_required``；advisor 仅限名下学生（本模块
所有可见/可写操作都过 ``_assignment_guard`` 的归属校验，viewer 只读）。
学生端不依赖管理端 session。
"""
from __future__ import annotations

import json

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session)

import db as _db
import questionnaire_store as qs
from app_utils import (_advisor_scope, rate_fail_check, rate_fail_clear,
                       rate_fail_record, role_required)
from questionnaire_engine import evaluate, validate_answers, validate_rules
from questionnaire_engine.schema import group_by_section, questions_of

bp = Blueprint("questionnaires", __name__)

_ADMIN_ROLES = ("admin", "advisor")
_READ_ROLES = ("admin", "advisor", "viewer")


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def _base_url() -> str:
    """分发链接用的外部基址（Nginx/Cloudflare 前置时由 ProxyFix 还原 Host）。"""
    return (request.url_root or "").rstrip("/")


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _assignment_guard(aid: int):
    """取任务并做 advisor 归属校验。返回 ``(assignment, None)`` 或 ``(None, resp)``。"""
    a = qs.get_assignment(aid)
    if not a:
        return None, _err("任务不存在", 404)
    scope = _advisor_scope()
    if scope is not None:
        st = _db.get_student(a["student_id"])
        if not st or (st.get("advisor_name") or "") != scope:
            return None, _err("无权访问该任务", 403)
    return a, None


def _parse_rules_payload(data: dict):
    """接受 ``rules``（dict）或 ``rules_text``（JSON 字符串）。返回 (rules, error)。"""
    rules = data.get("rules")
    if rules is None and data.get("rules_text") is not None:
        try:
            rules = json.loads(data.get("rules_text") or "")
        except Exception as e:
            return None, f"规则 JSON 解析失败：{e}"
    if not isinstance(rules, dict):
        return None, "rules 必须是 JSON 对象"
    return rules, None


# ===========================================================================
# 管理端页面
# ===========================================================================
@bp.route("/questionnaires")
@role_required(*_READ_ROLES)
def questionnaires_page():
    return redirect("/workspace")


@bp.route("/questionnaires/assignments")
@role_required(*_READ_ROLES)
def assignments_page():
    """已并入工作台（16 包 §B4）：任务台账在 /workspace。"""
    return redirect("/workspace")


@bp.route("/questionnaires/bank")
@role_required(*_ADMIN_ROLES)
def bank_page():
    return render_template("questionnaires/bank.html",
                           nav_active="tools.bank")


# ===========================================================================
# 管理端 API —— 任务
# ===========================================================================
@bp.route("/api/questionnaires/assignments")
@role_required(*_READ_ROLES)
def api_assignments():
    status = (request.args.get("status") or "").strip() or None
    student_id = request.args.get("student_id")
    if student_id:
        try:
            student_id = int(student_id)
        except (TypeError, ValueError):
            return _err("student_id 必须是数字", 400)
    advisor = _advisor_scope()
    rows, counts = qs.list_assignments(status=status,
                                       advisor_name=advisor,
                                       student_id=student_id,
                                       with_counts=True)
    # 在途行的链接有效期（工作台账台「分发」列次信息用；零行时不开查询）
    expiries = qs.token_expiry_map([r["id"] for r in rows
                                    if r.get("status") in ("sent", "expired")])
    for r in rows:
        r["expires_at"] = expiries.get(r["id"]) or ""
    return jsonify({"ok": True, "assignments": rows, "counts": counts})


@bp.route("/api/questionnaires/assignments", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_create_assignment():
    """人工建任务（问卷 4 走这里）：body {student_id, questionnaire_id|code, reason}。"""
    data = _json_body()
    student_id = data.get("student_id")
    if not student_id:
        return _err("缺少 student_id")
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return _err("student_id 必须是数字")
    st = _db.get_student(student_id)
    if not st:
        return _err("学生不存在", 404)
    scope = _advisor_scope()
    if scope is not None and (st.get("advisor_name") or "") != scope:
        return _err("无权为该学生创建任务", 403)
    qid = data.get("questionnaire_id")
    if not qid and data.get("code"):
        q = qs.get_questionnaire_by_code(data["code"])
        qid = q["id"] if q else None
    if not qid:
        return _err("缺少 questionnaire_id（或无效 code）")
    q = qs.get_questionnaire(qid)
    if not q:
        return _err("问卷不存在", 404)
    if not q.get("is_active"):
        return _err("该问卷已停用")
    aid, created = qs.create_assignment(student_id, qid, source="manual",
                                        reason=(data.get("reason") or "").strip())
    return jsonify({"ok": True, "assignment_id": aid, "created": created})


@bp.route("/api/questionnaires/assignments/<int:aid>/confirm", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_confirm_assignment(aid):
    a, denied = _assignment_guard(aid)
    if denied:
        return denied
    data = _json_body()
    delivery = (data.get("delivery") or "").strip()
    if delivery not in qs.DELIVERIES:
        return _err(f"delivery 必须是 {qs.DELIVERIES} 之一")
    res = qs.confirm_assignment(aid, delivery, user_id=session.get("user_id"),
                                base_url=_base_url())
    if not res.get("ok"):
        return _err(res.get("error") or "确认失败")
    return jsonify(res)


@bp.route("/api/questionnaires/assignments/<int:aid>/reject", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_reject_assignment(aid):
    _, denied = _assignment_guard(aid)
    if denied:
        return denied
    ok = qs.reject_assignment(aid)
    if not ok:
        return _err("当前状态不可驳回")
    return jsonify({"ok": True})


@bp.route("/api/questionnaires/assignments/<int:aid>/reissue", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_reissue_assignment(aid):
    _, denied = _assignment_guard(aid)
    if denied:
        return denied
    res = qs.reissue_assignment(aid, base_url=_base_url())
    if not res.get("ok"):
        return _err(res.get("error") or "重新生成失败")
    return jsonify(res)


@bp.route("/api/questionnaires/assignments/<int:aid>/reset-password", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_reset_password(aid):
    a, denied = _assignment_guard(aid)
    if denied:
        return denied
    res = qs.reset_student_password(a["student_id"])
    if not res.get("ok"):
        return _err(res.get("error") or "重置失败")
    return jsonify(res)


@bp.route("/api/questionnaires/assignments/<int:aid>/package")
@role_required(*_READ_ROLES)
def api_assignment_package(aid):
    _, denied = _assignment_guard(aid)
    if denied:
        return denied
    return jsonify(qs.get_package(aid, base_url=_base_url()))


@bp.route("/api/questionnaires/assignments/<int:aid>/response")
@role_required(*_READ_ROLES)
def api_assignment_response(aid):
    _, denied = _assignment_guard(aid)
    if denied:
        return denied
    resp = qs.get_response(aid)
    if not resp:
        return _err("尚未提交答案", 404)
    q = qs.get_questionnaire(resp["questionnaire_id"], with_schema=True)
    return jsonify({"ok": True, "response": resp, "schema": (q or {}).get("schema") or {}})


# ===========================================================================
# 管理端 API —— 题库
# ===========================================================================
@bp.route("/api/questionnaires/bank")
@role_required(*_READ_ROLES)
def api_bank():
    with_schema = request.args.get("with_schema") in ("1", "true")
    items = qs.list_questionnaires()
    if with_schema:
        for it in items:
            q = qs.get_questionnaire(it["id"], with_schema=True)
            it["schema"] = (q or {}).get("schema") or {}
    return jsonify({"ok": True, "questionnaires": items})


@bp.route("/api/questionnaires/bank/<int:qid>/toggle", methods=["POST"])
@role_required("admin")
def api_bank_toggle(qid):
    data = _json_body()
    active = bool(data.get("active"))
    if not qs.set_questionnaire_active(qid, active):
        return _err("问卷不存在", 404)
    return jsonify({"ok": True, "is_active": 1 if active else 0})


# ===========================================================================
# 管理端 API —— 识别规则
# ===========================================================================
@bp.route("/api/questionnaires/rules")
@role_required(*_READ_ROLES)
def api_rules():
    versions = qs.list_rule_versions()
    published = next((v for v in versions if v["status"] == "published"), None)
    return jsonify({"ok": True, "versions": versions,
                    "published_id": published["id"] if published else None,
                    "known_codes": sorted(qs.known_indicator_codes())})


@bp.route("/api/questionnaires/rules/<int:vid>")
@role_required(*_READ_ROLES)
def api_rule_version(vid):
    v = qs.get_rule_version(vid)
    if not v:
        return _err("版本不存在", 404)
    try:
        v["rules"] = json.loads(v.get("rules_json") or "{}")
    except Exception:
        v["rules"] = {}
    return jsonify({"ok": True, "version": v})


@bp.route("/api/questionnaires/rules", methods=["POST"])
@role_required("admin")
def api_rules_save():
    """新建 draft 版本；body {rules|rules_text, note}。返回校验错误（不阻断保存）。"""
    data = _json_body()
    rules, err = _parse_rules_payload(data)
    if err:
        return _err(err)
    errors = validate_rules(rules, known_codes=qs.known_indicator_codes())
    vid = qs.save_rule_version(rules, note=(data.get("note") or "").strip(),
                              created_by=session.get("user_id"))
    return jsonify({"ok": True, "version_id": vid, "errors": errors})


@bp.route("/api/questionnaires/rules/validate", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_rules_validate():
    rules, err = _parse_rules_payload(_json_body())
    if err:
        return _err(err)
    return jsonify({"ok": True, "errors": validate_rules(rules, qs.known_indicator_codes())})


@bp.route("/api/questionnaires/rules/try", methods=["POST"])
@role_required(*_ADMIN_ROLES)
def api_rules_try():
    """试算：用某生最新报告 schema_124 跑给定规则（缺省用当前 draft 或 published）。

    body {student_id, rules|rules_text?}
    """
    data = _json_body()
    student_id = data.get("student_id")
    if not student_id:
        return _err("缺少 student_id")
    scope = _advisor_scope()
    if scope is not None:
        st = _db.get_student(student_id)
        if not st or (st.get("advisor_name") or "") != scope:
            return _err("无权访问该学生", 403)
    rules, err = _parse_rules_payload(data)
    if err:
        return _err(err)
    if rules is None:
        rules = qs.get_published_rules() or {}

    reports = _db.get_student_reports(student_id)
    if not reports:
        return _err("该学生暂无报告，无法试算", 404)
    rec = _db.get_report_raw(reports[0]["id"])
    if not rec:
        return _err("读取报告数据失败", 500)
    items = qs.build_engine_items((rec.get("raw") or {}).get("schema_124") or [])
    hits = evaluate(items, rules)
    warn = validate_rules(rules, qs.known_indicator_codes())
    for h in hits:
        q = qs.get_questionnaire_by_code(h["questionnaire_code"])
        h["questionnaire_title"] = (q or {}).get("title", "")
        h["is_active"] = bool((q or {}).get("is_active"))
    return jsonify({"ok": True, "hits": hits, "items": items,
                    "errors": warn, "report_id": reports[0]["id"]})


@bp.route("/api/questionnaires/rules/<int:vid>/publish", methods=["POST"])
@role_required("admin")
def api_rules_publish(vid):
    v = qs.get_rule_version(vid)
    if not v:
        return _err("版本不存在", 404)
    try:
        rules = json.loads(v.get("rules_json") or "{}")
    except Exception:
        return _err("规则 JSON 损坏，无法发布")
    errors = [e for e in validate_rules(rules, qs.known_indicator_codes())
              if not e.startswith("警告")]
    if errors:
        return jsonify({"ok": False, "error": "规则存在错误，无法发布", "errors": errors}), 400
    qs.publish_rule_version(vid)
    return jsonify({"ok": True, "published_id": vid})


@bp.route("/api/questionnaires/rules/<int:vid>/delete", methods=["POST"])
@role_required("admin")
def api_rules_delete(vid):
    if not qs.delete_rule_version(vid):
        return _err("仅可删除 draft 版本")
    return jsonify({"ok": True})


# ===========================================================================
# 学生端 —— 学生 session 辅助
# ===========================================================================
def _student_session() -> dict:
    return {"account_id": session.get("student_account_id"),
            "student_id": session.get("student_id"),
            "username": session.get("student_username") or "",
            "name": session.get("student_name") or ""}


def _student_required(f):
    from functools import wraps

    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("student_account_id"):
            return redirect("/student/login?next=" + request.path)
        return f(*args, **kwargs)
    return wrapper


def _answers_from_request(schema: dict) -> dict:
    """读取答案：JSON body 的 ``answers``，或原生表单（无 JS 降级）。"""
    if request.is_json:
        return (request.get_json(silent=True) or {}).get("answers") or {}
    answers: dict = {}
    for q in questions_of(schema):
        qid = str(q.get("id") or "")
        if q.get("type") == "multi":
            vals = [v for v in request.form.getlist(qid) if v != ""]
            if vals:
                answers[qid] = vals
        else:
            v = request.form.get(qid)
            if v is not None and v.strip() != "":
                answers[qid] = v
    return answers


def _wizard_steps(schema: dict) -> list:
    """把 schema 摊平成向导步进序列（15 指令包 §5）：分区 intro 页 + 逐题页 + 末尾检查页。

    题号 ``n`` 与 ``validate_answers`` 的枚举顺序一致（1 起），前端据此把服务端
    「第 N 题」错误映射回具体步骤。
    """
    steps: list = []
    n = 0
    for section, questions in group_by_section(schema):
        if section:
            steps.append({"kind": "intro", "title": section.get("title") or "",
                          "intro": section.get("intro") or ""})
        for q in questions:
            n += 1
            steps.append({
                "kind": "q",
                "n": n,
                "id": str(q.get("id") or ""),
                "type": q.get("type") or "single",
                "title": q.get("title") or "",
                "required": bool(q.get("required")),
                "options": [{"value": str(o.get("value")), "label": o.get("label") or ""}
                            for o in (q.get("options") or [])],
                "scale": q.get("scale") or {},
                "max_length": q.get("max_length"),
            })
    steps.append({"kind": "check"})
    return steps


def _render_student_form(assignment, questionnaire, *, draft=None, draft_updated_at=None,
                         token=None, submitted=False, error=None):
    """服务端渲染作答表单（link 模式 token，账号模式 token=None）。"""
    schema = questionnaire.get("schema") or {}
    form_action = (f"/q/{token}/submit" if token
                   else f"/student/q/{assignment['id']}/submit")
    draft_url = (f"/q/{token}/draft" if token
                 else f"/student/q/{assignment['id']}/draft")
    return render_template(
        "student/q_form.html",
        assignment=assignment,
        student=_db.get_student(assignment["student_id"]),
        questionnaire=questionnaire,
        groups=group_by_section(schema),
        question_count=len(schema.get("questions") or []),
        draft=draft or {},
        token=token,
        form_action=form_action,
        draft_url=draft_url,
        submitted=submitted,
        error=error,
        # 向导数据源（Alpine wizard() 消费）：步进序列 + 两源草稿的「较新者」判定材料
        wizard={
            "steps": _wizard_steps(schema),
            "mode": "link" if token else "account",
            "aid": int(assignment["id"]),
            "formAction": form_action,
            "draftUrl": draft_url,
            "draft": draft or {},
            "serverAt": draft_updated_at or "",
            "error": error or "",
            "count": len(schema.get("questions") or []),
        },
    )


@bp.route("/q/<token>")
def link_form(token):
    """一次性链接作答页（无需登录）。"""
    t = qs.get_token_by_raw(token)
    if not t:
        return render_template("student/message.html", title="链接无效",
                               message="该作答链接无效或已被替换，请联系顾问重新获取。",
                               show_login=True), 404
    from datetime import datetime
    if t.get("used_at"):
        return render_template("student/message.html", title="问卷已提交",
                               message="该链接已使用过（问卷已提交），无需重复作答。")
    exp = t.get("expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.utcnow():
        return render_template("student/message.html", title="链接已过期",
                               message="该作答链接已过期，请联系顾问重新生成。",
                               show_login=True)
    a = qs.get_assignment(t["assignment_id"])
    if not a:
        return render_template("student/message.html", title="链接已失效",
                               message="该作答链接已失效，请联系顾问重新获取。",
                               show_login=True), 404
    if a["status"] == "submitted":
        return render_template("student/message.html", title="问卷已提交",
                               message="该问卷已提交，感谢作答。")
    q = qs.get_questionnaire(a["questionnaire_id"], with_schema=True)
    if not q:
        return render_template("student/message.html", title="问卷不存在",
                               message="问卷已下线，请联系顾问。", show_login=True), 404
    d = qs.get_draft(a["id"])
    return _render_student_form(a, q, draft=d.get("answers") or {},
                                draft_updated_at=d.get("updated_at"), token=token)


@bp.route("/q/<token>/draft", methods=["POST"])
def link_draft(token):
    """链接模式云端草稿（15 指令包 §4）。

    token 即凭证（``/q/`` 前缀已 CSRF 豁免，靠不可枚举 token 防伪），
    写入同一张 ``response_drafts``（按 assignment_id 关联），零表结构变更。
    """
    from datetime import datetime
    t = qs.get_token_by_raw(token)
    if not t:
        return jsonify({"ok": False, "error": "链接无效"}), 404
    if t.get("used_at"):
        return jsonify({"ok": False, "error": "该链接已完成作答"}), 400
    exp = t.get("expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.utcnow():
        return jsonify({"ok": False, "error": "链接已过期"}), 400
    a = qs.get_assignment(t["assignment_id"])
    if not a or a["status"] == "submitted":
        return jsonify({"ok": False, "error": "该问卷不可作答"}), 400
    qs.save_draft(a["id"], _json_body().get("answers") or {})
    return jsonify({"ok": True})


@bp.route("/q/<token>/submit", methods=["POST"])
def link_submit(token):
    """链接模式提交（成功后作废 token）。支持 JSON 与原生表单（无 JS 降级）。"""
    t = qs.get_token_by_raw(token)
    if not t:
        return jsonify({"ok": False, "error": "链接无效"}), 404
    if t.get("used_at"):
        return jsonify({"ok": False, "error": "该链接已完成作答，不能重复提交"}), 400
    from datetime import datetime
    exp = t.get("expires_at")
    if exp and datetime.fromisoformat(exp) < datetime.utcnow():
        return jsonify({"ok": False, "error": "链接已过期"}), 400
    a = qs.get_assignment(t["assignment_id"])
    if not a:
        return jsonify({"ok": False, "error": "链接已失效，请联系顾问"}), 404
    q = qs.get_questionnaire(a["questionnaire_id"], with_schema=True)
    if not q:
        return jsonify({"ok": False, "error": "链接已失效，请联系顾问"}), 404
    schema = q.get("schema") or {}
    answers = _answers_from_request(schema)
    errors = validate_answers(schema, answers)
    if errors:
        if request.is_json:
            return jsonify({"ok": False, "error": "还有题目需要完成", "errors": errors}), 400
        return _render_student_form(a, q, token=token, draft=answers,
                                    error="；".join(errors)), 400
    res = qs.submit_response(a["id"], answers, "link")
    if not res.get("ok"):
        if request.is_json:
            return jsonify(res), 400
        return _render_student_form(a, q, token=token, draft=answers,
                                    error=res.get("error") or "提交失败"), 400
    qs.mark_token_used(t["id"])
    if request.is_json:
        return jsonify({"ok": True})
    return render_template("student/message.html", title="提交成功",
                           message="问卷已收到，感谢作答。你可以关闭本页了。")


@bp.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "GET":
        if session.get("student_account_id"):
            return redirect("/student/home")
        return render_template("student/login.html",
                               error=request.args.get("error"),
                               next=request.args.get("next") or "/student/home")
    data = request.form if request.form else _json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    # 登录限流：同一 IP 每分钟 5 次失败，超限 429（独立 scope，与管理端分开计数）
    if not rate_fail_check(5, scope="student-login"):
        if request.is_json:
            return _err("尝试过多，请稍后再试", 429)
        return render_template("student/login.html", error="尝试过多，请稍后再试",
                               next=(data.get("next") or "/student/home")), 429
    acc = qs.verify_student_login(username, password)
    if not acc:
        rate_fail_record(scope="student-login")
        if request.is_json:
            return _err("账号或密码错误", 401)
        return render_template("student/login.html", error="账号或密码错误",
                               next=(data.get("next") or "/student/home"))
    rate_fail_clear(scope="student-login")
    session["student_account_id"] = acc["account_id"]
    session["student_id"] = acc["student_id"]
    session["student_username"] = acc["username"]
    session["student_name"] = acc["student_name"] or acc["username"]
    next_url = (data.get("next") or "/student/home")
    if not next_url.startswith("/"):
        next_url = "/student/home"
    return redirect(next_url) if not request.is_json else jsonify({"ok": True})


@bp.route("/student/logout", methods=["POST"])
def student_logout():
    for k in ("student_account_id", "student_id", "student_username", "student_name"):
        session.pop(k, None)
    return redirect("/student/login")


@bp.route("/student/home")
@_student_required
def student_home():
    sid = session.get("student_id")
    return render_template("student/home.html",
                           student=_student_session(),
                           todos=qs.list_student_todos(sid),
                           done=qs.list_student_done(sid))


def _student_assignment(aid: int):
    """账号模式取任务：必须属于当前学生、delivery ∈ account/both、status=sent。"""
    a = qs.get_assignment(aid)
    if not a or a["student_id"] != session.get("student_id"):
        return None
    if a["delivery"] not in ("account", "both"):
        return None
    if a["status"] not in ("sent", "submitted"):
        return None
    return a


@bp.route("/student/q/<int:aid>")
@_student_required
def student_form(aid):
    a = _student_assignment(aid)
    if not a:
        return render_template("student/message.html", title="任务不可用",
                               message="该问卷任务不存在或不可作答。"), 404
    if a["status"] == "submitted":
        return render_template("student/message.html", title="问卷已提交",
                               message="该问卷已提交，感谢作答。")
    q = qs.get_questionnaire(a["questionnaire_id"], with_schema=True)
    if not q:
        return render_template("student/message.html", title="问卷不存在",
                               message="问卷已下线，请联系顾问。"), 404
    draft = qs.get_draft(aid)
    return _render_student_form(a, q, draft=draft.get("answers") or {},
                                draft_updated_at=draft.get("updated_at"))


@bp.route("/student/q/<int:aid>/draft", methods=["POST"])
@_student_required
def student_draft(aid):
    if not _student_assignment(aid):
        return _err("任务不可用", 404)
    qs.save_draft(aid, _json_body().get("answers") or {})
    return jsonify({"ok": True})


@bp.route("/student/q/<int:aid>/submit", methods=["POST"])
@_student_required
def student_submit(aid):
    a = _student_assignment(aid)
    if not a:
        return _err("任务不可用", 404)
    q = qs.get_questionnaire(a["questionnaire_id"], with_schema=True)
    if not q:
        return _err("问卷不存在", 404)
    schema = q.get("schema") or {}
    answers = _answers_from_request(schema)
    errors = validate_answers(schema, answers)
    if errors:
        if request.is_json:
            return jsonify({"ok": False, "error": "答案校验未通过", "errors": errors}), 400
        return _render_student_form(a, q, draft=answers, error="；".join(errors)), 400
    res = qs.submit_response(aid, answers, "account")
    if not res.get("ok"):
        if request.is_json:
            return jsonify(res), 400
        return _render_student_form(a, q, draft=answers,
                                    error=res.get("error") or "提交失败"), 400
    if request.is_json:
        return jsonify({"ok": True})
    return redirect("/student/home")
