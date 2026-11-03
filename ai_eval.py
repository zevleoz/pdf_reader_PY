"""AI 写作真实评测：用虚构资料跑一次真实管道，把结果写到指定目录。

用法::

    python ai_eval.py <surface> --out <dir> [--model qwen-flash]

``prep`` 是 W1 的会前准备；W2、W3、W4 各自在 ``SURFACES`` 里加自己的。

安全约束：
* 每次运行都新建临时 SQLite 库（不是沙盒，更不是 ``data/y4_students.db``）；
  若 ``DATABASE_URL`` 指向真实库，直接拒绝运行。
* 学生、Y4 和全部资料都是虚构的（``fixtures/ai_eval/*.txt``）。
* 默认把所有模型变量设为 ``qwen-flash``。
* 输出只写到 ``--out``，不写进仓库；不打印、不记录生成的文字，只在屏幕上
  报计数、耗时和标记数。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FIXTURES = BASE_DIR / "fixtures" / "ai_eval"
REAL_DB = (BASE_DIR / "data" / "y4_students.db").resolve()
MODEL_VARIABLES = ("FT_LLM_MODEL", "AI_TEXT_MODEL", "ITERATION_MODEL",
                   "DASHBOARD_AI_MODEL")


def _points_at_real_db(url: str) -> bool:
    if not url or not url.startswith("sqlite"):
        return False
    path = url.split("sqlite:///", 1)[-1]
    if not path or path == ":memory:":
        return False
    try:
        return Path(path).resolve() == REAL_DB
    except OSError:
        return False


def _guard_environment(model: str) -> None:
    """Must run before ``db`` is imported: db reads DATABASE_URL at import time."""
    if _points_at_real_db(os.environ.get("DATABASE_URL", "")):
        sys.exit("拒绝运行：DATABASE_URL 指向真实库 data/y4_students.db")
    for name in MODEL_VARIABLES:
        os.environ[name] = model


def _temp_database() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="ai_eval_"))
    path = directory / "eval.db"
    os.environ["DATABASE_URL"] = "sqlite:///%s" % path
    return path


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").strip()


def _full_fictional_y4() -> list:
    """Fictional Y4 covering every R4 indicator plus the norm codes.

    Values are spread across bands, several in concern bands. They avoid
    ``9.5``, ``8.6``, ``7.1`` and ``安全型`` so a leaked prompt example stands out.
    """
    import data_points

    from m1.kb import load_kb
    from m1.y4_evidence import _NORM_CODE

    values = {
        "072": "SAE",  # interest code: required for a complete Y4
        "004": 45,     # 认知能力—注意力
        "011": 3, "012": 6, "013": 4, "014": 12,
        "016": 2.5, "017": 3.6, "019": 4.2,
        "020": "专注型", "021": "轻视型", "022": "混合型",
        "023": 40, "024": 14, "025": 26,
        "026": 33, "027": 9, "028": 20,
        "029": 24, "030": 7, "031": 15,
        "051": 6, "053": 9, "054": 7, "055": 3, "056": 2, "057": 6, "058": 4,
        "059": 4.2,
        "060": 6.0, "061": 4.1, "062": 6.2,
        "063": 52, "065": 88,
        "068": 3.6, "071": 5.4,
        "073": 3, "074": 5, "075": 6, "076": 4, "077": 2, "078": 4,
        "079": 6, "084": 7, "085": 4,
        "096": 6.0, "098": 7.8, "099": 8.2, "100": 4.5,
        # 常模平均数（060-062↔125-127，066-068↔128-130，069-071↔131-133）
        "125": 5.2, "126": 4.8, "127": 5.4,
        "128": 4.1, "129": 5.9, "130": 4.4,
        "131": 4.3, "132": 5.1, "133": 4.6,
    }
    codes = {"072"} | set(_NORM_CODE.values())
    for ability in load_kb().get("abilities") or []:
        codes.update(str(code) for code in ability.get("indicators") or [])
    meta = data_points.POINT_META
    return [
        {"code": code,
         "label": (meta.get(code) or {}).get("label") or code,
         "type": (meta.get(code) or {}).get("type") or "number",
         "value": values[code]}
        for code in sorted(codes, key=int)
    ]


def _build_prep(upload_dir: Path, first_touch: str = "first_meeting.txt"):
    """Fictional student (blank gender), fictional Y4, and the fixture sources."""
    import json as _json
    from datetime import date

    from sqlalchemy.orm import Session

    import db as _db
    import growth_talk_store as _gt
    import m1.sources as sources
    import m1.store as store
    import questionnaire_store as qs

    if _points_at_real_db(str(_db.engine.url)):
        sys.exit("拒绝运行：数据库连接指向真实库")
    tables = [
        _db.Student.__table__, _db.User.__table__, _db.Report.__table__,
        store.M1Prep.__table__, store.M1Source.__table__, store.M1Version.__table__,
        _gt.AuditLog.__table__,
        _gt.CopilotSession.__table__, _gt.CopilotPhaseEvent.__table__,
        _gt.CopilotCareerCalibration.__table__, _gt.CopilotInterestNote.__table__,
        _gt.CopilotTranscriptSupplement.__table__,
        qs.Questionnaire.__table__, qs.Assignment.__table__,
        qs.AssignmentToken.__table__, qs.Response.__table__,
        qs.ResponseDraft.__table__,
    ]
    _db.Base.metadata.create_all(_db.engine, tables=tables)
    sources.UPLOAD_ROOT = upload_dir

    points = _full_fictional_y4()
    with Session(_db.engine) as sess:
        student = _db.Student(student_code="Y4-9001", name="示例学生甲", gender="",
                              grade="初二", school="示例学校", advisor_name="示例顾问")
        sess.add(student)
        mentor = _db.User(username="eval-mentor", password_hash="x", role="admin",
                          advisor_name="", display_name="评测导师")
        sess.add(mentor)
        sess.flush()
        sess.add(_db.Report(student_id=student.id, report_date=date(2026, 9, 2),
                            pdf_path="report.pdf",
                            data_json=_json.dumps({"schema_124": points},
                                                  ensure_ascii=False)))
        sess.commit()
        student_id, mentor_id = student.id, mentor.id

    prep = store.create_prep(student_id, created_by=mentor_id, mentor_user_id=mentor_id)
    sources.add_text(prep["id"], _read(first_touch), "first_touch_extra")
    sources.add_text(prep["id"], _read("parent_note.txt"), "parent")
    sources.add_text(prep["id"], _read("case_review.txt"), "case_review")
    return prep


def _readable(doc: dict) -> str:
    """Plain-text dump of every block, for reading the result."""
    lines = []

    def walk(value, path=""):
        if isinstance(value, dict):
            if isinstance(value.get("id"), str) and isinstance(value.get("text"), str):
                lines.append("[%s] %s" % (value["id"], value["text"]))
            for key, child in value.items():
                if key != "fact_flags":
                    walk(child, path + "/" + key)
        elif isinstance(value, list):
            for child in value:
                walk(child, path)
    walk(doc)
    return "\n".join(lines)


def run_prep(out: Path, first_touch: str = "first_meeting.txt") -> dict:
    upload_dir = out / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    prep = _build_prep(upload_dir, first_touch)

    import growth_talk.analysis as analysis
    import m1.pipeline as pipeline
    import m1.store as store

    counts: dict = {}
    original_ask = pipeline._ask

    def counting_ask(prompt, schema_name):
        counts[schema_name] = counts.get(schema_name, 0) + 1
        return original_ask(prompt, schema_name)
    pipeline._ask = counting_ask

    steps = {}

    def progress(step, state, seconds=0.0):
        if state in ("done", "error"):
            steps[step] = {"state": state, "seconds": seconds}

    started = time.monotonic()
    error = ""
    try:
        pipeline.generate(prep["id"], progress=progress)
    except Exception as exc:  # report the failure; never pretend it worked
        error = "%s: %s" % (exc.__class__.__name__, str(exc)[:300])
    elapsed = time.monotonic() - started

    result = {"surface": "prep", "model": analysis.model_name(),
              "seconds": round(elapsed, 1), "calls": sum(counts.values()),
              "calls_by_step": counts, "steps": steps, "error": error,
              "prep_id": prep["id"]}
    if not error:
        draft = store.get_latest_version(prep["id"], "ai_draft") or {}
        doc = draft.get("doc") or {}
        flags = doc.get("fact_flags") or []
        result["flags"] = len(flags)
        result["flag_kinds"] = sorted({flag.get("kind") for flag in flags})
        (out / "doc.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        (out / "doc.txt").write_text(_readable(doc), encoding="utf-8")
        (out / "flags.json").write_text(json.dumps(flags, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
        (out / "evidence.json").write_text(
            json.dumps(draft.get("evidence") or [], ensure_ascii=False, indent=1),
            encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return result


_INSIGHTS_AGGREGATES = {
    "get_dashboard_stats": {"headline": {"total_reports": 5, "total_students": 3}},
    "get_indicator_aggregates": {
        "dimension_summary": {
            "心力": {"healthy_pct": 60, "weak_names": ["情绪稳定"]},
            "精力": {"healthy_pct": 30, "weak_names": ["睡眠习惯"]},
            "学习力": {"healthy_pct": 70, "weak_names": []},
            "生涯力": {"healthy_pct": 50, "weak_names": ["目标感"]},
        },
    },
    "get_indicator_distributions": {
        "精力": {"evaluated": 8, "total": 10, "distribution": {"高": 2, "较好": 3, "偏低": 3},
                 "strong_indicators": [], "weak_indicators": [
                     {"label": "睡眠习惯", "weak_pct": 30}]},
    },
    "get_student_profiles": [
        {"student_name": "示例学生甲", "grade": "初二", "overall_health": 55,
         "dimensions": {"心力": {"healthy": 60}, "精力": {"healthy": 30},
                        "学习力": {"healthy": 70}, "生涯力": {"healthy": 50}},
         "is_healthiest": False, "is_needs_attention": True},
    ],
    "get_dimension_correlations": {
        "pairs": [{"dim_a": "心力", "dim_b": "精力", "correlation": 0.6,
                   "strength": "中等", "co_weak": 2}],
    },
    "get_indicator_trends": {
        "most_frequently_weak": [{"label": "睡眠习惯", "dim": "精力", "weak_count": 3,
                                  "total_count": 10, "weak_students": ["示例学生甲"]}],
    },
    "get_cluster_patterns": {
        "clusters": [{"signature": "精力", "count": 2, "overall_health_avg": 55,
                      "students": ["示例学生甲", "示例学生乙"]}],
        "balanced_count": 1,
    },
    "get_dimension_balance": {
        "students": [{"student_name": "示例学生甲", "balance_score": 60,
                      "weakest_dim": "精力", "strongest_dim": "学习力", "gap": 20,
                      "is_imbalanced": False}],
        "avg_balance_score": 65, "imbalanced_count": 0,
    },
}


def _insights_source(user_prompt: str) -> str:
    prefix = "【聚合数据】\n"
    return user_prompt.split(prefix, 1)[-1] if prefix in user_prompt else user_prompt


def run_insights(out: Path) -> dict:
    """Fictional aggregates → the real 洞察 AI call; report kept/dropped counts."""
    import re

    from flask import Flask

    import ai_writing
    from blueprints import insights as insights_bp

    for name, value in _INSIGHTS_AGGREGATES.items():
        setattr(insights_bp._db, name, lambda value=value: value)

    calls = {"n": 0, "content": "", "user": ""}
    real_chat = insights_bp._dashscope_chat

    def capture(messages, model, timeout=180, max_tokens=3000, temperature=0.4):
        calls["n"] += 1
        calls["user"] = messages[-1]["content"]
        reply = real_chat(messages, model=model, timeout=timeout,
                          max_tokens=max_tokens, temperature=temperature)
        calls["content"] = reply.get("content") or ""
        return reply

    insights_bp._dashscope_chat = capture
    app = Flask(__name__)
    app.secret_key = "eval-secret"

    started = time.monotonic()
    error = ""
    data = {}
    try:
        with app.app_context():
            data = insights_bp.api_dashboard_ai_analysis.__wrapped__().get_json()
    except Exception as exc:
        error = "%s: %s" % (exc.__class__.__name__, str(exc)[:300])
    elapsed = time.monotonic() - started
    insights_bp._dashscope_chat = real_chat

    match = (re.search(r"```json\s*(\{.*?\})\s*```", calls["content"], re.DOTALL)
             or re.search(r"(\{.*\})", calls["content"], re.DOTALL))
    raw_insights = 0
    if match:
        try:
            raw_insights = len((json.loads(match.group(1)).get("insights") or []))
        except Exception:
            raw_insights = 0

    analysis = (data or {}).get("analysis") or {}
    kept = analysis.get("insights") or []
    source = _insights_source(calls["user"])
    numbers, others = 0, 0
    for insight in kept:
        if not isinstance(insight, dict):
            continue
        text = "%s\n%s" % (insight.get("headline") or "", insight.get("detail") or "")
        for item in ai_writing.lint_facts(text, source):
            if item["kind"] == "number":
                numbers += 1
            else:
                others += 1

    result = {
        "surface": "insights", "model": os.environ.get("DASHBOARD_AI_MODEL", ""),
        "seconds": round(elapsed, 1), "calls": calls["n"],
        "calls_by_step": {"insights": calls["n"]},
        "raw_insights": raw_insights, "kept": len(kept),
        "dropped": max(0, raw_insights - len(kept)),
        "numbers_not_in_data": numbers, "other_findings": others,
        "error": error or ("洞察接口返回失败" if (data or {}).get("ok") is False else ""),
    }
    (out / "insights.json").write_text(
        json.dumps({"analysis": analysis, "counts": result}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# W2: 解读会纪要 / Y4 解读
# ---------------------------------------------------------------------------


def _fictional_world() -> dict:
    """虚构学生 + 虚构 Y4（临时库）。绝不读真实库。"""
    from datetime import date

    from sqlalchemy.orm import Session

    import db as _db

    if _points_at_real_db(str(_db.engine.url)):
        sys.exit("拒绝运行：数据库连接指向真实库")
    tables = [_db.Student.__table__, _db.User.__table__, _db.Report.__table__,
              _db.MeetingMinutes.__table__]
    _db.Base.metadata.create_all(_db.engine, tables=tables)
    with Session(_db.engine) as sess:
        student = _db.Student(student_code="Y4-9002", name="示例学生乙", gender="",
                              grade="初二", school="示例学校", advisor_name="示例顾问")
        sess.add(student)
        mentor = _db.User(username="eval-w2", password_hash="x", role="admin",
                          advisor_name="", display_name="评测账号")
        sess.add(mentor)
        sess.flush()
        report = _db.Report(student_id=student.id, report_date=date(2026, 9, 2),
                            pdf_path="report.pdf",
                            data_json=json.dumps(
                                {"student": {"name": "示例学生乙", "grade": "初二"},
                                 "schema_124": _full_fictional_y4()},
                                ensure_ascii=False))
        sess.add(report)
        sess.commit()
        return {"student_id": student.id, "report_id": report.id,
                "admin_id": mentor.id, "db": _db}


def _app_client(world):
    """最小 app：只注册被测的两个蓝图；用内存 session 以管理员身份访问。"""
    from flask import Flask

    from blueprints import reports as reports_bp
    from blueprints import tools as tools_bp

    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "eval-secret"
    app.register_blueprint(tools_bp.bp)
    app.register_blueprint(reports_bp.bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = world["admin_id"]
        sess["role"] = "admin"
        sess["advisor_name"] = ""
    return client


def run_minutes(out: Path) -> dict:
    """虚构逐字稿 → 真实 /api/transcript（含事实核对）。"""
    import ai_writing

    world = _fictional_world()
    client = _app_client(world)
    transcript = _read("first_meeting.txt")

    started = time.monotonic()
    error = ""
    data: dict = {}
    try:
        res = client.post("/api/transcript", json={
            "transcript": transcript,
            "student_id": world["student_id"],
            "report_id": world["report_id"],
        })
        data = res.get_json() or {}
        if res.status_code != 200 or not data.get("ok"):
            error = "HTTP %s: %s" % (res.status_code, data.get("error") or "接口返回失败")
    except Exception as exc:
        error = "%s: %s" % (exc.__class__.__name__, str(exc)[:300])
    elapsed = time.monotonic() - started

    summary = data.get("summary") or ""
    flags = data.get("fact_flags") or []
    # 另一层检查：代码查最终文字里资料中没有的数字/时间/人物（来源 = 逐字稿）。
    lint = ai_writing.lint_facts(summary, transcript) if summary else []

    result = {
        "surface": "minutes", "model": os.environ.get("ITERATION_MODEL", ""),
        "seconds": round(elapsed, 1), "calls": 2 if data else 0,
        "calls_by_step": {"minutes": 1, "fact_check": 1} if data else {},
        "truncated": data.get("truncated"),
        "fact_status": data.get("fact_status") or "skipped",
        "flags": len(flags), "flag_kinds": sorted({f.get("kind") or "" for f in flags}),
        "lint_vs_transcript": len(lint),
        "lint_kinds": sorted({item["kind"] for item in lint}),
        "minutes_id": data.get("minutes_id"), "error": error,
    }
    (out / "minutes.md").write_text(summary, encoding="utf-8")
    (out / "flags.json").write_text(json.dumps(flags, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (out / "lint.json").write_text(json.dumps(lint, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return result


def run_y4(out: Path) -> dict:
    """虚构 Y4 → 真实 /api/reports/<id>/interpret（含事实核对）。"""
    world = _fictional_world()
    client = _app_client(world)

    started = time.monotonic()
    error = ""
    data: dict = {}
    try:
        res = client.post("/api/reports/%d/interpret" % world["report_id"])
        data = res.get_json() or {}
        if res.status_code != 200 or not data.get("ok"):
            error = "HTTP %s: %s" % (res.status_code, data.get("error") or "接口返回失败")
    except Exception as exc:
        error = "%s: %s" % (exc.__class__.__name__, str(exc)[:300])
    elapsed = time.monotonic() - started

    reply = data.get("reply") or ""
    flags = data.get("fact_flags") or []
    saved = (world["db"].get_report_raw(world["report_id"]) or {}).get("interpretation")

    result = {
        "surface": "y4", "model": os.environ.get("AI_TEXT_MODEL", ""),
        "seconds": round(elapsed, 1), "calls": 2 if data else 0,
        "calls_by_step": {"interpretation": 1, "fact_check": 1} if data else {},
        "fact_status": data.get("fact_status") or "skipped",
        "flags": len(flags), "flag_kinds": sorted({f.get("kind") or "" for f in flags}),
        "chars": len(reply), "stored": saved == reply, "error": error,
    }
    (out / "interpretation.md").write_text(reply, encoding="utf-8")
    (out / "flags.json").write_text(json.dumps(flags, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# W3: First Touch（会谈总结 / 兴趣分型说明 / Y4 职业画像）
# ---------------------------------------------------------------------------
_FIRST_TOUCH_STUDENT = "若曦"
_FIRST_TOUCH_INTERESTS = [
    {"id": "i1", "label": "画画", "topicType": "interest",
     "preferenceScore": 3, "competenceScore": 2, "note": "",
     "evidence": "平时晚上写完作业如果不太晚，也会画二十分钟左右。"},
    {"id": "i2", "label": "随笔写作", "topicType": "interest",
     "preferenceScore": 3, "competenceScore": 2, "note": "",
     "evidence": "我上次写了一篇关于外婆家院子里那棵枣树的"},
    {"id": "i3", "label": "数学", "topicType": "subject",
     "preferenceScore": 1, "competenceScore": 1, "note": "",
     "evidence": "数学我觉得很吃力，尤其是几何证明。"},
    {"id": "i4", "label": "骑车", "topicType": "interest",
     "preferenceScore": 2, "competenceScore": 1, "note": "",
     "evidence": "周末在家的时候会带我去公园骑车。"},
]


def run_first_touch(out: Path) -> dict:
    """虚构会谈 + 虚构兴趣评分 + 虚构 Y4 → 真实 First Touch 三步。"""
    import ai_writing
    import growth_talk.analysis as analysis

    counts: dict = {}
    step = {"name": "meeting"}
    original_call = analysis.call_model

    def counting_call(prompt):
        counts[step["name"]] = counts.get(step["name"], 0) + 1
        return original_call(prompt)

    analysis.call_model = counting_call
    transcript = _read("first_meeting.txt")
    y4_text = _read("y4_report.txt")
    meeting: dict = {}
    quadrant: dict = {}
    career: dict = {}
    error = ""
    started = time.monotonic()
    try:
        step["name"] = "meeting"
        meeting = analysis.analyze_meeting_source(transcript)
        step["name"] = "quadrant"
        quadrant = analysis.run_quadrant_analysis({
            "student": {"name": _FIRST_TOUCH_STUDENT, "grade": "初二"},
            "meetingSummary": meeting.get("summary") or "",
            "interests": [dict(item) for item in _FIRST_TOUCH_INTERESTS],
        })
        step["name"] = "career"
        career = analysis.analyze_career_profile(y4_text)
    except Exception as exc:  # report the failure; never pretend it worked
        error = "%s: %s" % (exc.__class__.__name__, str(exc)[:300])
    finally:
        analysis.call_model = original_call
    elapsed = time.monotonic() - started

    summary = meeting.get("summary") or ""
    summary_valid = False
    if summary:
        try:
            analysis.validate_editable_meeting_summary(summary)
            summary_valid = True
        except ValueError:
            summary_valid = False
    meeting_lint = ai_writing.lint_facts(summary, transcript) if summary else []
    quadrant_lint = []
    if quadrant.get("narrative"):
        source = json.dumps({
            "student": {"name": _FIRST_TOUCH_STUDENT, "grade": "初二"},
            "meetingSummary": summary,
            "interests": _FIRST_TOUCH_INTERESTS,
        }, ensure_ascii=False)
        quadrant_lint = ai_writing.lint_facts(quadrant["narrative"], source)
    career_lint = []
    for key in ("career_interests", "ability_tendencies", "value_preferences"):
        if isinstance(career.get(key), str):
            career_lint.extend(ai_writing.lint_facts(career[key], y4_text))

    statuses = [meeting.get("fact_status"), quadrant.get("fact_status"),
                career.get("fact_status")]
    flags = ((meeting.get("fact_flags") or [])
             + (quadrant.get("fact_flags") or [])
             + (career.get("fact_flags") or []))
    result = {
        "surface": "first_touch", "model": analysis.model_name(),
        "seconds": round(elapsed, 1), "calls": sum(counts.values()),
        "calls_by_step": counts,
        "fact_status": (
            "checked" if all(status == "checked" for status in statuses)
            else "partial" if any(statuses) else "skipped"),
        "fact_status_by_step": {
            "meeting": meeting.get("fact_status"),
            "quadrant": quadrant.get("fact_status"),
            "career": career.get("fact_status"),
        },
        "flags": len(flags),
        "flag_kinds": sorted({flag.get("kind") or "" for flag in flags}),
        "meeting_summary_valid": summary_valid,
        "lint_vs_transcript": len(meeting_lint),
        "lint_kinds": sorted({item["kind"] for item in meeting_lint}),
        "quadrant_lint": len(quadrant_lint),
        "career_lint": len(career_lint),
        "error": error,
    }
    (out / "meeting.json").write_text(
        json.dumps(meeting, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "quadrant.txt").write_text(quadrant.get("narrative") or "",
                                      encoding="utf-8")
    (out / "career.json").write_text(
        json.dumps(career, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "flags.json").write_text(
        json.dumps(flags, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return result


SURFACES = {"prep": run_prep, "insights": run_insights,
            "minutes": run_minutes, "y4": run_y4,
            "first_touch": run_first_touch}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("surface", choices=sorted(SURFACES))
    parser.add_argument("--out", required=True, help="输出目录（不要放进仓库）")
    parser.add_argument("--model", default="qwen-flash")
    parser.add_argument("--first-touch", default="first_meeting.txt",
                        help="First Touch 资料文件名（默认 first_meeting.txt）")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    if BASE_DIR in out.parents or out == BASE_DIR:
        sys.exit("输出目录不能放在仓库里")
    out.mkdir(parents=True, exist_ok=True)
    _guard_environment(args.model)
    db_path = _temp_database()
    sys.path.insert(0, str(BASE_DIR))
    if args.surface == "prep":
        result = run_prep(out, args.first_touch)
    else:
        result = SURFACES[args.surface](out)
    print("surface=%s model=%s db=%s" % (args.surface, result["model"], db_path.name))
    print("seconds=%s calls=%s %s" % (result["seconds"], result["calls"],
                                      json.dumps(result["calls_by_step"], ensure_ascii=False)))
    if result["surface"] == "insights":
        print("insights raw=%s kept=%s dropped=%s numbers_not_in_data=%s other=%s"
              % (result.get("raw_insights", 0), result.get("kept", 0),
                 result.get("dropped", 0), result.get("numbers_not_in_data", 0),
                 result.get("other_findings", 0)))
    else:
        print("flags=%s %s fact_status=%s"
              % (result.get("flags", "n/a"), result.get("flag_kinds", ""),
                 result.get("fact_status", "n/a")))
    if result["error"]:
        print("ERROR: %s" % result["error"])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
