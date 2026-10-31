"""问卷计分与学生问卷中心的契约测试。

计分口径以 ``Profiling plus questionnaires.xlsx`` 为准；运行在 ``tmp_path`` 下的
独立 SQLite 上，绝不触碰 ``data/y4_students.db``。
"""
import json
import re
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import app_utils
import db as _db
import questionnaire_store as qs
from blueprints import questionnaires as qbp
from blueprints import students as students_bp
from questionnaire_engine.scoring import RULES, band_for, score_response

SEED_DIR = Path(__file__).resolve().parent / "questionnaires_seed"
EXCEL = Path(__file__).resolve().parent / "Profiling plus questionnaires.xlsx"
SHEET_OF = {"抑郁焦虑问卷": ("Q-ANX-01", "Q-DEP-01"), "情绪调节问卷": ("Q-ERQ-CERQ-01",),
            "情绪调节策略CERQ": ("Q-ERQ-CERQ-01",), "社交能力问卷": ("Q-SOC-01",),
            "网络成瘾问卷": ("Q-IAD-01",), "学业压力": ("Q-STRESS-01",)}


def _schema(dims, values=(0, 1, 2, 3)):
    """按 {维度: 题数} 造一份 schema；题号 q1.. 连续。"""
    questions = []
    for dim, count in dims.items():
        for _ in range(count):
            questions.append({"id": f"q{len(questions) + 1}", "type": "single",
                              "required": True, "title": f"{dim}题", "dimension": dim,
                              "options": [{"value": str(v), "label": f"选{v}"} for v in values]})
    return {"version": 1, "questions": questions}


def _answers(schema, value):
    return {q["id"]: str(value) for q in schema["questions"]}


# ---------------------------------------------------------------------------
# 与 Excel 对齐
# ---------------------------------------------------------------------------
def _norm(text):
    return re.sub(r"\s+", "", re.sub(r"^\s*\d+\s*[\.．、]\s*", "", str(text or "")))


def _excel_items():
    openpyxl = pytest.importorskip("openpyxl")
    if not EXCEL.exists():
        pytest.skip("Excel 不在当前目录")
    items = {}
    for ws in openpyxl.load_workbook(EXCEL).worksheets:
        header = next(c.column for c in ws[1] if str(c.value or "").strip() == "题目")
        dims = {c.column: str(c.value).strip() for c in ws[1]
                if c.column > header and c.value}
        for row in ws.iter_rows(min_row=2):
            title = row[header - 1].value
            if title:
                # 部分单元格是空格占位，只有值为 1 才算勾选
                items[_norm(title)] = (ws.title.strip(),
                                       [dims[c.column] for c in row
                                        if c.column in dims and c.value == 1])
    return items


def _seed_schemas():
    if not (SEED_DIR / "Q-ANX-01.json").exists():
        pytest.skip("题库 seed 被 .gitignore 忽略，当前检出没有")
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))["schema"]
            for p in SEED_DIR.glob("Q-*.json")}


def test_seed_question_dimensions_match_excel_item_by_item():
    excel = _excel_items()
    schemas = _seed_schemas()
    assert len(excel) == sum(len(s["questions"]) for s in schemas.values())
    for code, schema in schemas.items():
        for q in schema["questions"]:
            sheet, dims = excel[_norm(q["title"])]
            assert dims == [q["dimension"]], q["title"]
            assert code in SHEET_OF[sheet], q["title"]


def test_rules_cover_every_seed_questionnaire_and_dimension():
    schemas = _seed_schemas()
    assert set(RULES) == set(schemas)
    for code, schema in schemas.items():
        assert ({d["name"] for d in RULES[code]["dimensions"]}
                == {q["dimension"] for q in schema["questions"]}), code


def test_seed_item_counts_and_ranges():
    schemas = _seed_schemas()
    expected_total = {"Q-IAD-01": (20, 100), "Q-STRESS-01": (30, 150),
                      "Q-ERQ-CERQ-01": (-108, 108)}
    for code, (lo, hi) in expected_total.items():
        total = score_response(code, schemas[code], {})["total"]
        assert (total["min"], total["max"]) == (lo, hi), code
    assert score_response("Q-SOC-01", schemas["Q-SOC-01"], {})["total"] is None
    dims = {d["name"]: d for d in score_response("Q-ERQ-CERQ-01", schemas["Q-ERQ-CERQ-01"], {})["dimensions"]}
    assert (dims["认知重评"]["min"], dims["认知重评"]["max"]) == (-18, 18)
    assert (dims["压抑表达"]["min"], dims["压抑表达"]["max"]) == (-12, 12)
    assert (dims["灾难化"]["min"], dims["灾难化"]["max"]) == (-12, 12)
    assert score_response("Q-ANX-01", schemas["Q-ANX-01"], {})["dimensions"][0]["max"] == 21
    assert score_response("Q-DEP-01", schemas["Q-DEP-01"], {})["dimensions"][0]["max"] == 27


def test_every_band_and_advice_is_written_in_the_excel():
    """分档与建议一字不差来自 Excel；不带分档的总分只有负责人确认的 CERQ。"""
    openpyxl = pytest.importorskip("openpyxl")
    if not EXCEL.exists():
        pytest.skip("Excel 不在当前目录")
    cells = " ".join(str(c.value) for ws in openpyxl.load_workbook(EXCEL).worksheets
                     for row in ws.iter_rows() for c in row if c.value is not None)
    for code, rule in RULES.items():
        tables = [d["bands"] for d in rule["dimensions"] if d.get("bands")]
        if rule.get("total"):
            if rule["total"].get("bands"):
                tables.append(rule["total"]["bands"])
            else:
                assert code == "Q-ERQ-CERQ-01"
        for bands in tables:
            for band in bands:
                assert band["label"] in cells, band["label"]
                assert band["advice"] in cells, band["advice"]


def test_self_harm_flag_points_at_the_right_question():
    q9 = next(q for q in _seed_schemas()["Q-DEP-01"]["questions"] if q["id"] == "q9")
    assert "伤害自己" in q9["title"]


# ---------------------------------------------------------------------------
# 分档边界（逐条取自 Excel）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code,dim,score,label", [
    ("Q-ANX-01", 0, 0, "无明显焦虑"), ("Q-ANX-01", 0, 4, "无明显焦虑"),
    ("Q-ANX-01", 0, 5, "轻度焦虑"), ("Q-ANX-01", 0, 9, "轻度焦虑"),
    ("Q-ANX-01", 0, 10, "中度焦虑"), ("Q-ANX-01", 0, 14, "中度焦虑"),
    ("Q-ANX-01", 0, 15, "重度焦虑"), ("Q-ANX-01", 0, 21, "重度焦虑"),
    ("Q-DEP-01", 0, 4, "无明显抑郁"), ("Q-DEP-01", 0, 5, "有抑郁倾向"),
    ("Q-DEP-01", 0, 9, "有抑郁倾向"), ("Q-DEP-01", 0, 10, "轻度抑郁"),
    ("Q-DEP-01", 0, 14, "轻度抑郁"), ("Q-DEP-01", 0, 15, "中度抑郁"),
    ("Q-DEP-01", 0, 19, "中度抑郁"), ("Q-DEP-01", 0, 20, "重度抑郁"),
    ("Q-DEP-01", 0, 27, "重度抑郁"),
])
def test_dimension_bands(code, dim, score, label):
    assert band_for(score, RULES[code]["dimensions"][dim]["bands"])["label"] == label


@pytest.mark.parametrize("code,score,label", [
    ("Q-IAD-01", 20, "正常"), ("Q-IAD-01", 39, "正常"), ("Q-IAD-01", 40, "轻度依赖"),
    ("Q-IAD-01", 59, "轻度依赖"), ("Q-IAD-01", 60, "中度依赖"), ("Q-IAD-01", 79, "中度依赖"),
    ("Q-IAD-01", 80, "重度依赖"), ("Q-IAD-01", 100, "重度依赖"),
    ("Q-STRESS-01", 30, "几乎无压力"), ("Q-STRESS-01", 45, "几乎无压力"),
    ("Q-STRESS-01", 46, "轻度压力"), ("Q-STRESS-01", 75, "轻度压力"),
    ("Q-STRESS-01", 76, "中度压力"), ("Q-STRESS-01", 120, "中度压力"),
    ("Q-STRESS-01", 121, "重度压力"), ("Q-STRESS-01", 150, "重度压力"),
])
def test_total_bands(code, score, label):
    assert band_for(score, RULES[code]["total"]["bands"])["label"] == label


def test_advice_text_is_kept_with_the_band():
    band = band_for(20, RULES["Q-DEP-01"]["dimensions"][0]["bands"])
    assert band["advice"] == "尽快就医，重视第九题得分情况"
    assert band_for(10, RULES["Q-ANX-01"]["dimensions"][0]["bands"])["advice"] == "建议正式评估"


# ---------------------------------------------------------------------------
# 计分
# ---------------------------------------------------------------------------
def test_dimension_scores_sum_each_dimension_separately():
    schema = _schema({"行为失控": 2, "功能损害": 1, "戒断反应": 1}, values=(1, 2, 3, 4, 5))
    result = score_response("Q-IAD-01", schema, {"q1": "5", "q2": "4", "q3": "1", "q4": "2"})
    dims = {d["name"]: d for d in result["dimensions"]}
    assert dims["行为失控"]["score"] == 9
    assert (dims["行为失控"]["min"], dims["行为失控"]["max"]) == (2, 10)
    assert dims["功能损害"]["score"] == 1
    assert dims["戒断反应"]["score"] == 2
    assert result["total"]["score"] == 12
    assert result["complete"] is True


def test_negative_option_values_are_summed_as_is():
    schema = _schema({"认知重评": 2, "压抑表达": 1, "自我责备": 1, "接纳": 2},
                     values=(-3, -2, -1, 0, 1, 2, 3))
    result = score_response("Q-ERQ-CERQ-01", schema,
                            {"q1": "-3", "q2": "1", "q3": "2", "q4": "3", "q5": "-1", "q6": "-1"})
    dims = {d["name"]: d for d in result["dimensions"]}
    assert dims["认知重评"]["score"] == -2
    assert dims["认知重评"]["group"] == "情绪调节（ERQ）"
    assert dims["压抑表达"]["score"] == 2
    # 总分只算 CERQ 的题（q4-q6），不混入 ERQ；没有分档
    total = result["total"]
    assert (total["label"], total["score"], total["item_count"]) == ("CERQ 总分", 1, 3)
    assert total["band"] is None


def test_only_the_grand_total_gets_a_band_on_internet_and_stress():
    schema = _schema({"学习任务": 2, "教师与课堂": 1}, values=(1, 2, 3, 4, 5))
    result = score_response("Q-STRESS-01", schema, {"q1": "5", "q2": "5", "q3": "5"})
    assert result["total"]["band"] is not None
    assert [d["score"] for d in result["dimensions"][:2]] == [10, 5]
    assert all(d["band"] is None for d in result["dimensions"])


def test_incomplete_dimension_has_no_score_rather_than_a_low_score():
    schema = _schema({"焦虑": 3})
    result = score_response("Q-ANX-01", schema, {"q1": "3", "q2": "3"})
    dim = result["dimensions"][0]
    assert dim["score"] is None
    assert dim["answered"] == 2
    assert dim["band"] is None
    assert result["complete"] is False


def test_invalid_answer_value_counts_as_unanswered():
    schema = _schema({"焦虑": 1})
    assert score_response("Q-ANX-01", schema, {"q1": "99"})["dimensions"][0]["score"] is None
    assert score_response("Q-ANX-01", schema, {"q1": True})["dimensions"][0]["score"] is None


def test_unknown_questionnaire_has_no_score():
    assert score_response("Q-OTHER", _schema({"焦虑": 1}), {"q1": "1"}) is None


@pytest.mark.parametrize("value,expected", [("0", False), ("1", True), ("3", True)])
def test_self_harm_flag_fires_on_any_nonzero_even_when_total_is_low(value, expected):
    schema = _schema({"抑郁": 9})
    answers = _answers(schema, 0)
    answers["q9"] = value
    result = score_response("Q-DEP-01", schema, answers)
    assert bool(result["flags"]) is expected
    assert result["dimensions"][0]["band"]["label"] == "无明显抑郁"
    if expected:
        assert result["flags"][0]["answer"] == f"选{value}"


def test_anxiety_questionnaire_has_no_self_harm_flag():
    schema = _schema({"焦虑": 9})
    assert score_response("Q-ANX-01", schema, _answers(schema, 3))["flags"] == []


# ---------------------------------------------------------------------------
# 落库 / 学生中心 / API（独立 SQLite）
# ---------------------------------------------------------------------------
class World:
    def __init__(self, engine):
        self.engine = engine
        with Session(engine) as sess:
            sess.add(_db.User(id=1, username="admin", password_hash="x", role="admin",
                              display_name="管理员"))
            self.student = _db.Student(student_code="Y4-9001", name="测试学生", advisor_name="Mine")
            other = _db.Student(student_code="Y4-9002", name="别的学生", advisor_name="Other")
            sess.add_all([self.student, other])
            sess.flush()
            self.student_id, self.other_id = self.student.id, other.id
            self.q = {}
            for code, schema in (("Q-ANX-01", _schema({"焦虑": 7})),
                                 ("Q-DEP-01", _schema({"抑郁": 9})),
                                 ("Q-TEST-01", _schema({"无规则": 1}))):
                row = qs.Questionnaire(code=code, title=f"{code} 问卷",
                                       schema_json=json.dumps(schema, ensure_ascii=False))
                sess.add(row)
                sess.flush()
                self.q[code] = (row.id, schema)
            sess.commit()

    def assign(self, code, status="sent", delivery="account", student_id=None):
        with Session(self.engine) as sess:
            row = qs.Assignment(student_id=student_id or self.student_id,
                                questionnaire_id=self.q[code][0], status=status,
                                delivery=delivery, source="manual")
            sess.add(row)
            sess.flush()
            aid = row.id
            sess.commit()
        return aid

    def submit(self, code, value, **kw):
        aid = self.assign(code, **kw)
        assert qs.submit_response(aid, _answers(self.q[code][1], value), "account")["ok"]
        return aid


@pytest.fixture
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/q.db")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _db.Base.metadata.create_all(engine)
    qs.ensure_indexes(bind=engine)
    monkeypatch.setattr(qs, "engine", engine)
    monkeypatch.setattr(_db, "engine", engine)
    w = World(engine)
    yield w
    engine.dispose()


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    root = Path(__file__).resolve().parent
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.secret_key = "test"
    app.register_blueprint(qbp.bp)
    app.register_blueprint(students_bp.bp)
    app.jinja_env.filters["dt_short"] = app_utils.dt_short
    app.context_processor(lambda: {"csrf_token": lambda: "tok"})
    return app.test_client()


def _login_admin(client, role="admin", advisor=None):
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["username"] = "admin"
        s["role"] = role
        if advisor:
            s["advisor_name"] = advisor


def _login_student(client, world, student_id=None):
    with client.session_transaction() as s:
        s["student_account_id"] = 1
        s["student_id"] = student_id or world.student_id
        s["student_username"] = "y4-9001"
        s["student_name"] = "测试学生"


def test_submit_stores_scores_on_the_student(world):
    world.submit("Q-ANX-01", 2)
    scores = qs.list_student_scores(world.student_id)
    assert len(scores) == 1
    dim = scores[0]["dimensions"][0]
    assert (dim["name"], dim["score"], dim["band"]["label"]) == ("焦虑", 14, "中度焦虑")
    assert scores[0]["questionnaire_code"] == "Q-ANX-01"


def test_profile_keeps_only_latest_submission_per_questionnaire(world):
    world.submit("Q-ANX-01", 0)
    world.submit("Q-ANX-01", 3)
    world.submit("Q-DEP-01", 1)
    scores = qs.list_student_scores(world.student_id)
    by_code = {s["questionnaire_code"]: s for s in scores}
    assert len(scores) == 2
    assert by_code["Q-ANX-01"]["dimensions"][0]["score"] == 21


def test_questionnaire_without_rule_stores_answers_but_no_score(world):
    world.submit("Q-TEST-01", 1)
    assert qs.list_student_scores(world.student_id) == []
    with Session(world.engine) as sess:
        assert len(sess.execute(select(qs.Response)).scalars().all()) == 1


def test_scoring_failure_does_not_lose_the_students_answers(world, monkeypatch):
    def _boom(_response_id):
        raise RuntimeError("scoring bug")
    monkeypatch.setattr(qs, "score_and_store", _boom)
    aid = world.assign("Q-ANX-01")
    assert qs.submit_response(aid, _answers(world.q["Q-ANX-01"][1], 1), "account")["ok"]
    assert qs.get_response(aid) is not None
    assert qs.list_student_scores(world.student_id) == []
    monkeypatch.undo()


def test_backfill_scores_old_responses_once(world):
    aid = world.assign("Q-ANX-01", status="submitted")
    with Session(world.engine) as sess:
        sess.add(qs.Response(assignment_id=aid, student_id=world.student_id,
                             questionnaire_id=world.q["Q-ANX-01"][0],
                             answers_json=json.dumps(_answers(world.q["Q-ANX-01"][1], 1)),
                             submitted_via="link"))
        sess.commit()
    assert qs.backfill_scores() == 1
    assert qs.list_student_scores(world.student_id)[0]["dimensions"][0]["score"] == 7
    assert qs.backfill_scores() == 0


def test_rescore_keeps_the_review_record(world):
    aid = world.submit("Q-DEP-01", 1)
    assert qs.mark_flag_reviewed(aid, None)
    with Session(world.engine) as sess:
        row = sess.execute(select(qs.QuestionnaireScore)).scalars().one()
        row.scoring_version = 0
        sess.commit()
    assert qs.backfill_scores() == 1
    with Session(world.engine) as sess:
        assert sess.execute(select(qs.QuestionnaireScore)).scalars().one().reviewed_at is not None
    assert qs.list_open_flags(student_id=world.student_id) == []


def test_delete_assignment_removes_its_scores(world):
    aid = world.submit("Q-ANX-01", 1)
    assert qs.delete_assignment(aid) is True
    assert qs.list_student_scores(world.student_id) == []


def test_delete_student_removes_scores_despite_foreign_keys(world):
    world.submit("Q-ANX-01", 1)
    _db.delete_student(world.student_id)
    with Session(world.engine) as sess:
        assert sess.execute(select(qs.QuestionnaireScore)).scalars().all() == []


def test_open_flags_respect_advisor_scope_and_review(world):
    aid = world.submit("Q-DEP-01", 1)
    world.submit("Q-ANX-01", 3)                     # 焦虑问卷没有 flag
    assert [f["assignment_id"] for f in qs.list_open_flags()] == [aid]
    assert qs.list_open_flags(advisor_name="Mine")[0]["student_name"] == "测试学生"
    assert qs.list_open_flags(advisor_name="Other") == []
    assert qs.mark_flag_reviewed(aid, None) is True
    assert qs.list_open_flags() == []
    assert qs.mark_flag_reviewed(aid, None) is False
    by_code = {s["questionnaire_code"]: s for s in qs.list_student_scores(world.student_id)}
    assert by_code["Q-DEP-01"]["reviewed_at"]


# ── 问卷中心 ──
def test_center_lists_all_sent_surveys_whatever_the_delivery(world):
    a = world.assign("Q-ANX-01", delivery="account")
    b = world.assign("Q-DEP-01", delivery="link")
    c = world.assign("Q-TEST-01", delivery="both")
    world.assign("Q-TEST-01", delivery="account", student_id=world.other_id)
    world.assign("Q-ANX-01", status="pending", delivery="account", student_id=world.other_id)
    assert {t["id"] for t in qs.list_student_todos(world.student_id)} == {a, b, c}


def test_center_excludes_unconfirmed_tasks(world):
    world.assign("Q-ANX-01", status="pending", delivery=None)
    assert qs.list_student_todos(world.student_id) == []


def test_center_shows_progress_and_puts_started_surveys_first(world):
    world.assign("Q-ANX-01")
    started = world.assign("Q-DEP-01")
    qs.save_draft(started, {"q1": "0", "q2": "2", "q3": "", "ghost": "1"})
    todos = qs.list_student_todos(world.student_id)
    assert todos[0]["id"] == started
    assert todos[0]["answered_count"] == 2
    assert todos[0]["question_count"] == 9
    assert todos[1]["answered_count"] == 0


def test_both_delivery_stays_open_after_its_link_expires(world):
    from datetime import datetime, timedelta
    both = world.assign("Q-ANX-01", delivery="both")
    link = world.assign("Q-DEP-01", delivery="link")
    with Session(world.engine) as sess:
        for aid, raw in ((both, "a" * 64), (link, "b" * 64)):
            sess.add(qs.AssignmentToken(assignment_id=aid, token=raw,
                                        expires_at=datetime.utcnow() - timedelta(days=1)))
        sess.commit()
    qs.refresh_expired()
    assert qs.get_assignment(both)["status"] == "sent"
    assert qs.get_assignment(link)["status"] == "expired"


def test_send_all_confirms_everything_with_one_login(world):
    a = world.assign("Q-ANX-01", status="pending", delivery=None)
    b = world.assign("Q-DEP-01", status="expired", delivery="link")
    done = world.submit("Q-TEST-01", 1)
    res = qs.confirm_all_for_student(world.student_id, base_url="https://x.test")
    assert res["ok"] and res["sent"] == 2 and res["todo_count"] == 2
    assert res["account"]["created"] is True
    assert "https://x.test/student/login" in res["text"]
    assert res["account"]["password"] in res["text"]
    assert "Q-ANX-01 问卷" in res["text"] and "Q-DEP-01 问卷" in res["text"]
    assert qs.get_assignment(a)["delivery"] == "account"
    assert qs.get_assignment(b)["status"] == "sent"
    assert qs.get_assignment(done)["status"] == "submitted"
    # 第二次没有可发的；账号也不重复创建
    assert qs.confirm_all_for_student(world.student_id)["ok"] is False
    world.assign("Q-TEST-01", status="pending", delivery=None)
    again = qs.confirm_all_for_student(world.student_id)
    assert again["account"]["created"] is False
    assert again["account"]["password"] is None
    assert "初始密码" not in again["text"]


def test_login_ignores_username_case_and_passwords_are_typable(world):
    acc = qs.ensure_student_account(world.student_id)
    assert re.fullmatch(r"[a-hjkmnp-z2-9]{10}", acc["password"])
    assert acc["username"] == "Y4-9001"
    assert qs.verify_student_login("y4-9001", acc["password"])["student_id"] == world.student_id
    assert qs.verify_student_login("y4-9001", "wrong") is None


# ── 路由 ──
def test_student_home_shows_pending_count_and_no_scores(client, world):
    world.submit("Q-ANX-01", 3)
    world.assign("Q-ANX-01")
    world.assign("Q-DEP-01", delivery="link")
    _login_student(client, world)
    html = client.get("/student/home").get_data(as_text=True)
    assert "<b>2</b> 份问卷待完成" in html
    assert "已完成 1 / 3" in html
    for leaked in ("重度焦虑", "建议正式评估", "得分"):
        assert leaked not in html


def test_student_can_open_a_link_delivered_survey_from_the_center(client, world):
    aid = world.assign("Q-ANX-01", delivery="link")
    _login_student(client, world)
    assert client.get(f"/student/q/{aid}").status_code == 200


def test_student_cannot_open_or_submit_another_students_survey(client, world):
    aid = world.assign("Q-ANX-01", student_id=world.other_id)
    _login_student(client, world)
    assert client.get(f"/student/q/{aid}").status_code == 404
    res = client.post(f"/student/q/{aid}/submit", json={"answers": {}})
    assert res.status_code == 404


def test_student_submit_reports_remaining_but_no_score(client, world):
    aid = world.assign("Q-ANX-01")
    world.assign("Q-DEP-01")
    _login_student(client, world)
    res = client.post(f"/student/q/{aid}/submit",
                      json={"answers": _answers(world.q["Q-ANX-01"][1], 3)})
    assert res.get_json() == {"ok": True, "remaining": 1}
    assert qs.list_student_scores(world.student_id)[0]["dimensions"][0]["score"] == 21


def test_link_submission_is_scored_too(client, world):
    aid = world.assign("Q-ANX-01", delivery="link")
    raw = qs.issue_token(aid)
    res = client.post(f"/q/{raw}/submit", json={"answers": _answers(world.q["Q-ANX-01"][1], 1)})
    assert res.get_json() == {"ok": True}
    assert qs.list_student_scores(world.student_id)[0]["dimensions"][0]["score"] == 7


@pytest.mark.parametrize("target", ["//evil.test/x", "/\\evil.test", "https://evil.test"])
def test_login_refuses_offsite_next(client, world, target):
    acc = qs.ensure_student_account(world.student_id)
    res = client.post("/student/login", data={"username": acc["username"],
                                              "password": acc["password"], "next": target})
    assert res.headers["Location"].endswith("/student/home")


def test_admin_apis_expose_scores_and_flags(client, world):
    aid = world.submit("Q-DEP-01", 1)
    _login_admin(client)
    ledger = client.get("/api/questionnaires/assignments").get_json()
    assert ledger["open_flags"][0]["assignment_id"] == aid
    assert ledger["assignments"][0]["flagged"] is True
    resp = client.get(f"/api/questionnaires/assignments/{aid}/response").get_json()
    assert resp["scores"]["dimensions"][0]["score"] == 9
    profile = client.get("/students/Y4-9001/api/profile").get_json()
    assert profile["report"] is None
    assert profile["questionnaire_scores"][0]["dimensions"][0]["band"]["label"] == "有抑郁倾向"
    tab = client.get("/students/Y4-9001/api/questionnaires").get_json()
    assert tab["assignments"][0]["scores"]["flags"][0]["id"] == "self_harm"
    assert client.post(f"/api/questionnaires/assignments/{aid}/flag-review").get_json()["ok"]
    assert client.get("/api/questionnaires/assignments").get_json()["open_flags"] == []
    assert client.get("/students/Y4-9001/api/profile").get_json()[
        "questionnaire_scores"][0]["reviewed_by"] == "管理员"


def test_advisor_cannot_send_or_review_other_advisors_students(client, world):
    aid = world.submit("Q-DEP-01", 1, student_id=world.other_id)
    world.assign("Q-ANX-01", status="pending", delivery=None, student_id=world.other_id)
    _login_admin(client, role="advisor", advisor="Mine")
    assert client.post(f"/api/questionnaires/students/{world.other_id}/send-all").status_code == 403
    assert client.post(f"/api/questionnaires/assignments/{aid}/flag-review").status_code == 403
    assert client.get("/api/questionnaires/assignments").get_json()["open_flags"] == []


def test_viewer_cannot_send_or_review(client, world):
    aid = world.submit("Q-DEP-01", 1)
    _login_admin(client, role="viewer")
    assert client.post(f"/api/questionnaires/students/{world.student_id}/send-all").status_code == 403
    assert client.post(f"/api/questionnaires/assignments/{aid}/flag-review").status_code == 403
