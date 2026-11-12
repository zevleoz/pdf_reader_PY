"""DP6：家长版（步③ 编辑/确认/导出 + 两页 PDF 打印）。"""
from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess

import pytest
from flask import Flask

import m1.plan_kb as plan_kb
import m1.plan_store as pstore
from app_utils import BASE_DIR
from test_m1_pipeline import _login
from test_m1_store import m1db  # noqa: F401  pytest fixture
from test_m1dp_pages_internal import _internal_doc
from test_m1dp_store import _create, _goal, _published_prep

_BLOCK = [0]


def _plan_with_internal(db, wb_grade=9):
    _BLOCK[0] += 1
    prep, report = _published_prep(db)
    plan = _create(db, prep, report, block_no=_BLOCK[0], wb_grade=wb_grade)
    plan = pstore.save_goals(plan["id"], plan["rev"], [_goal()])
    doc = _internal_doc()
    version = pstore.add_version(plan["id"], part="internal", kind="ai_draft",
                                 ai_doc=doc, doc=doc, checks=[])
    pstore.finish_generation(plan["id"], "internal", version_id=version["id"])
    return pstore.get_plan(plan["id"])


@pytest.fixture()
def page_client(m1db, monkeypatch):  # noqa: F811
    import app_utils
    from blueprints import m1 as m1_api
    from blueprints import m1_plan

    pstore.ensure_tables(m1db.engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_plan.bp)
    return app.test_client()


def _field(text):
    return {"text": text, "src": "ai"}


def _parent_doc(*, goals=1, picks=("s1p1",), reviews=2, seen=(False, False)):
    options = [{"ref": "s%dp1" % n, "title": _field("Practice %d" % n),
                "text": _field("Task %d" % n), "frequency": _field("每天"),
                "platform": "StoryMap"} for n in (1, 2, 3)]
    review = [{"label": _field("观察 %d" % (i + 1)),
               "text": _field("观察说明 %d。" % (i + 1))} for i in range(reviews)]
    return {
        "intro": _field("这一阶段的介绍。"),
        "goals": [{"code": "R2.2", "text": _field("目标说明 %d。" % (i + 1))}
                  for i in range(goals)],
        "sessions": [{"n": n, "title": _field("Session %d 主题" % n),
                      "summary": _field("这一节在学什么 %d。" % n)} for n in (1, 2, 3)],
        "transition": _field("从方法到练习的过渡。"),
        "practice_options": options,
        "practice": list(picks),
        "family": [_field("家庭建议一。"), _field("家庭建议二。")],
        "family_seen": list(seen),
        "review": review,
    }


def _approved(db, wb_grade=9):
    plan = _plan_with_internal(db, wb_grade=wb_grade)
    pstore.approve(plan["id"], db.alice_id)
    return pstore.get_plan(plan["id"])


def _with_parent(db, doc=None, *, stale=False, wb_grade=9):
    plan = _approved(db, wb_grade=wb_grade)
    version = pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                                 doc=doc or _parent_doc(),
                                 source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent", version_id=version["id"])
    if stale:
        pstore.reopen(plan["id"], db.alice_id)
    return pstore.get_plan(plan["id"])


def _mentor(client, db):
    _login(client, db.alice_id, "advisor", "Alice")


def test_parent_step_disabled_until_internal_approved(page_client, m1db):
    plan = _plan_with_internal(m1db)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'data-step="parent" aria-disabled="true"' in body
    assert 'data-panel="parent"' in body
    assert "批准内部版后才能生成家长版" in body


def test_parent_empty_state_then_editor(page_client, m1db):
    plan = _approved(m1db)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'data-avail="1"' in body
    assert "生成家长版" in body
    assert 'id="parentDoc"' not in body

    plan = _with_parent(m1db)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert 'id="parentDoc"' in body
    assert "确认家长版" in body
    assert "导出 PDF" in body
    assert "这一阶段的介绍。" in body
    assert "目标说明 1。" in body
    assert "家庭建议一。" in body
    assert 'aria-label="Practice 1 · Session 01"' in body


_LABEL_RE = re.compile(r"<label\b[^>]*>(.*?)</label>", re.I | re.S)
_CONTROL_RE = {
    "input": re.compile(r"<input\b([^>]*)>", re.I),
    "textarea": re.compile(r"<textarea\b([^>]*)>", re.I),
    "select": re.compile(r"<select\b([^>]*)>(.*?)</select>", re.I | re.S),
    "button": re.compile(r"<button\b([^>]*)>(.*?)</button>", re.I | re.S),
}


def _visible(fragment):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()


def _attr(attrs, name):
    match = re.search(r'\b%s\s*=\s*"([^"]*)"' % name, attrs)
    return match.group(1).strip() if match else ""


def _id_text(html, target):
    match = re.search(r'id="%s"[^>]*>([^<]*)<' % re.escape(target), html)
    return match.group(1).strip() if match else ""


def _unnamed_controls(html):
    """没有名字的表单控件：input/textarea/select/button 都要有 aria-label、
    aria-labelledby、外层 label 或自身文字（button、select 的选项）。"""
    labels = [(m.start(), m.end(), _visible(m.group(1))) for m in _LABEL_RE.finditer(html)]
    problems = []
    for tag, pattern in _CONTROL_RE.items():
        for match in pattern.finditer(html):
            attrs = match.group(1)
            inner = _visible(match.group(2)) if match.lastindex and match.lastindex >= 2 else ""
            name = _attr(attrs, "aria-label")
            if not name:
                target = _attr(attrs, "aria-labelledby")
                name = _id_text(html, target) if target else ""
            if not name:
                name = next((text for start, end, text in labels
                             if start < match.start() < end and text), "")
            if not name and tag in ("select", "button"):
                name = inner
            if not name:
                problems.append(match.group(0)[:100])
    return problems


def test_all_controls_in_three_steps_have_names(page_client, m1db):
    plan = _plan_with_internal(m1db)  # status review：①②可编辑
    version = pstore.add_version(plan["id"], part="parent", kind="ai_draft",
                                 doc=_parent_doc(), source_version_id=plan["current_version_id"])
    pstore.finish_generation(plan["id"], "parent", version_id=version["id"])
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)

    for marker in ('data-panel="inputs"', 'data-panel="internal"', 'id="parentDoc"'):
        assert marker in body
    assert _unnamed_controls(body) == []


def test_practice_checkbox_names_include_session(page_client, m1db):
    doc = _parent_doc(seen=(True, True))
    doc["practice_options"] = [
        {"ref": "s%dp1" % n, "title": _field("家庭三句话"), "text": _field("任务"),
         "frequency": _field("每天"), "platform": "无"} for n in (2, 3)]
    doc["practice"] = ["s2p1"]
    plan = _with_parent(m1db, doc)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)

    names = re.findall(r'data-pp-pick="[^"]+" aria-label="([^"]+)"', body)
    assert len(names) == 2
    assert len(set(names)) == 2
    assert names[0].startswith("家庭三句话 · Session 02")
    assert names[1].startswith("家庭三句话 · Session 03")


def test_parent_stale_banner(page_client, m1db):
    plan = _with_parent(m1db, stale=True)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    assert "家长版已过期" in body
    assert "内部版已更改，请先重新生成家长版" in body


def test_parent_step_counters_use_shared_limits(page_client, m1db):
    doc = _parent_doc(goals=3, picks=("s1p1", "s2p1", "s3p1"), reviews=4, seen=(True, True))
    plan = _with_parent(m1db, doc)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d" % plan["id"]).get_data(as_text=True)
    found = {path: int(limit) for path, limit in re.findall(
        r'<span[^>]*data-ppath="([^"]+)"[^>]*data-limit="(\d+)"', body)}

    limits = plan_kb.PARENT_LIMITS
    expected = {"intro": limits["intro"], "transition": limits["transition"],
                "family.0": limits["family"], "family.1": limits["family"]}
    for index in range(3):
        expected["goals.%d.text" % index] = limits["goal"]
        expected["sessions.%d.title" % index] = limits["session_title"]
        expected["sessions.%d.summary" % index] = limits["session_summary"]
        expected["practice_options.%d.title" % index] = limits["practice_title"]
        expected["practice_options.%d.text" % index] = limits["practice_text"]
        expected["practice_options.%d.frequency" % index] = limits["practice_frequency"]
    for index in range(4):
        expected["review.%d.label" % index] = limits["review_label"]
        expected["review.%d.text" % index] = limits["review_text"]
    assert found == expected

    source = (BASE_DIR / "templates" / "m1" / "plan.html").read_text(encoding="utf-8")
    assert not re.search(r'data-limit="\d', source)


def test_parent_confirm_blocked_by_over_limit_family(page_client, m1db):
    doc = _parent_doc(seen=(True, True))
    doc["family"][0] = _field("练" * (plan_kb.PARENT_LIMITS["family"] + 1))
    plan = _with_parent(m1db, doc)
    _mentor(page_client, m1db)
    response = page_client.post("/api/m1/plans/%d/parent/confirm" % plan["id"])
    assert response.status_code == 409
    assert any(item["text"] == "04 家庭协作与支持 · 第 1 项 · 超过 %d 字，请缩短"
               % plan_kb.PARENT_LIMITS["family"]
               for item in response.get_json()["blocking"])


def _worst_parent_doc():
    def fill(limit):
        return _field("练" * limit)

    limits = plan_kb.PARENT_LIMITS
    return {
        "intro": fill(limits["intro"]),
        "goals": [{"code": code, "text": fill(limits["goal"])}
                  for code in ("R2.2", "R3.3", "R4.1")],
        "sessions": [{"n": n, "title": fill(limits["session_title"]),
                      "summary": fill(limits["session_summary"])} for n in (1, 2, 3)],
        "transition": fill(limits["transition"]),
        "practice_options": [{"ref": "s%dp1" % n, "title": fill(limits["practice_title"]),
                              "text": fill(limits["practice_text"]),
                              "frequency": fill(limits["practice_frequency"]),
                              "platform": "StoryMap"} for n in (1, 2)],
        "practice": ["s1p1", "s2p1"],
        "family": [fill(limits["family"]), fill(limits["family"])],
        "family_seen": [True, True],
        "review": [{"label": fill(limits["review_label"]),
                    "text": fill(limits["review_text"])} for _ in range(4)],
    }


def test_parent_worst_case_prints_two_pages(page_client, m1db, tmp_path):
    chrome = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"))
    browser = next((path for path in chrome if path and shutil.which(path)), None)
    fitz = pytest.importorskip("fitz")
    if not browser:
        pytest.skip("Chrome 不可用")

    plan = _with_parent(m1db, _worst_parent_doc())
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d/parent/print" % plan["id"]).get_data(as_text=True)
    for name in ("m1.css", "plan_parent.css"):
        css = page_client.get("/m1/assets/%s" % name).get_data(as_text=True)
        body = re.sub(r'<link rel="stylesheet" href="[^"]*%s[^"]*">' % re.escape(name),
                      "<style>%s</style>" % css, body)
    page = tmp_path / "worst.html"
    page.write_text(body, encoding="utf-8")
    pdf = tmp_path / "worst.pdf"
    subprocess.run([browser, "--headless=new", "--no-pdf-header-footer",
                    "--print-to-pdf=%s" % pdf, page.as_uri()],
                   check=True, capture_output=True)

    doc = fitz.open(pdf)
    assert doc.page_count == 2
    for index, sheet in enumerate(doc):
        # 底部 70px 留白 + 24px 余量，按 A4 高度换算成 pt；页脚文字不参与。
        limit = (1123 - 70 - 24) * 72 / 96
        bottoms = [block[3] for block in sheet.get_text("blocks")
                   if block[3] <= 800]
        assert bottoms and max(bottoms) <= limit, "第 %d 页内容离底部太近" % (index + 1)


def test_parent_print_has_no_placeholders(page_client, m1db):
    doc = _parent_doc(goals=2, picks=("s1p1",), reviews=3, seen=(True, True))
    plan = _with_parent(m1db, doc)
    _mentor(page_client, m1db)
    response = page_client.get("/m1/plans/%d/parent/print" % plan["id"])
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "示意" not in body
    assert "AI " not in body and "AI新写" not in body
    assert "字段" not in body
    assert "指引" not in body
    assert "占位" not in body
    assert body.count('class="goal c') == 2
    assert body.count('class="prac"') == 1
    assert body.count('class="rv"') == 3


def test_parent_print_header_and_footer_are_fixed(page_client, m1db):
    plan = _with_parent(m1db)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d/parent/print" % plan["id"]).get_data(as_text=True)
    assert "APP · ARK" in body
    assert "EMOTIONAL &amp; RELATIONAL" in body
    assert "GROW THROUGH PRACTICE" in body
    assert "心有灵析 · PERSONALIZED DEVELOPMENT" in body
    assert "ONE STEP AT A TIME · TOGETHER WE GROW" in body
    assert "01 / 02" in body and "02 / 02" in body
    assert "草稿" in body


def test_parent_print_without_a_grade_shows_the_grade_text_alone(page_client, m1db):
    plan = _with_parent(m1db, wb_grade=None)
    _mentor(page_client, m1db)
    body = page_client.get("/m1/plans/%d/parent/print" % plan["id"]).get_data(as_text=True)
    assert "GNone" not in body and "（G）" not in body
    assert "初二" in body


def test_parent_print_404_without_parent(page_client, m1db):
    plan = _approved(m1db)
    _mentor(page_client, m1db)
    assert page_client.get("/m1/plans/%d/parent/print" % plan["id"]).status_code == 404


def test_parent_css_keeps_a4_layout_in_print():
    css = (BASE_DIR / "static" / "m1" / "plan_parent.css").read_text(encoding="utf-8")
    assert "@media (max-width" not in css
    assert "height:296.5mm" in css


def test_parent_overflow_names_the_section(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不可用")
    script = tmp_path / "measure.js"
    script.write_text(
        "global.window = {};\n"
        "window.getComputedStyle = function () { return {paddingTop: '0px', paddingBottom: '0px'}; };\n"
        "require(%s);\n"
        "function pg(marks, scrollHeight) {\n"
        "  return {scrollHeight: scrollHeight,\n"
        "    getBoundingClientRect: function () { return {top: 0}; },\n"
        "    querySelectorAll: function () {\n"
        "      return marks.map(function (m) {\n"
        "        return {getBoundingClientRect: function () { return {top: m[1]}; },\n"
        "                getAttribute: function () { return m[0]; }};\n"
        "      });\n"
        "    }};\n"
        "}\n"
        "function run(marks, scrollHeight) {\n"
        "  var root = {querySelectorAll: function () { return [pg(marks, scrollHeight)]; }};\n"
        "  return window.M1ParentFit.measure(root);\n"
        "}\n"
        "var goal = run([['学生信息', 0], ['开场介绍', 120], ['01 阶段成长目标', 300],\n"
        "                ['02 成长支持路径', 1200]], 1200);\n"
        "var intro = run([['学生信息', 0], ['开场介绍', 200]], 1160);\n"
        "var unknown = run([], 1300);\n"
        "console.log(JSON.stringify({goal: goal, intro: intro, unknown: unknown}));\n"
        % json.dumps(str(BASE_DIR / "static" / "m1" / "plan_parent.js")),
        encoding="utf-8")
    output = subprocess.run([node, str(script)], capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    assert result["goal"]["fits"] is False
    assert result["goal"]["section"] == "01 阶段成长目标"
    assert result["intro"]["section"] == "开场介绍"
    assert result["unknown"]["section"] == ""


def test_edit_after_confirm_returns_to_draft_and_keeps_internal(page_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    _mentor(page_client, m1db)
    internal_before = pstore.current_version(plan["id"], "internal")

    confirm = page_client.post("/api/m1/plans/%d/parent/confirm" % plan["id"])
    assert confirm.status_code == 200
    assert confirm.get_json()["plan"]["parent_status"] == "confirmed"

    plan = pstore.get_plan(plan["id"])
    doc = dict(pstore.current_version(plan["id"], "parent")["doc"])
    doc["intro"] = {"text": "改过的介绍。", "src": "edited"}
    saved = page_client.put("/api/m1/plans/%d/parent" % plan["id"],
                            json={"rev": plan["rev"], "doc": doc})
    assert saved.status_code == 200
    assert saved.get_json()["plan"]["parent_status"] == "draft"
    assert pstore.current_version(plan["id"], "internal") == internal_before


def test_export_is_refused_for_each_reason(page_client, m1db):
    _mentor(page_client, m1db)

    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={})
    assert response.status_code == 409
    assert "超过两页" in response.get_json()["error"]

    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={"fits": True})
    assert response.status_code == 409
    assert "请先确认" in response.get_json()["error"]

    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={"fits": False})
    assert response.status_code == 409
    assert "超过两页" in response.get_json()["error"]

    plan = _with_parent(m1db, _parent_doc(seen=(False, False)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={"fits": True})
    assert response.status_code == 409
    assert "还有" in response.get_json()["error"]
    assert any(item["path"][0] == "family_seen"
               for item in response.get_json()["blocking"])

    plan = _with_parent(m1db, _parent_doc(picks=(), seen=(True, True)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    assert page_client.post("/api/m1/plans/%d/parent/export" % plan["id"],
                            json={"fits": True}).status_code == 409

    plan = _with_parent(m1db, _parent_doc(picks=("s1p1", "s2p1", "s3p1"),
                                          seen=(True, True)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    assert page_client.post("/api/m1/plans/%d/parent/export" % plan["id"],
                            json={"fits": True}).status_code == 409

    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    pstore.confirm_parent(plan["id"], m1db.alice_id)
    pstore.reopen(plan["id"], m1db.alice_id)
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={"fits": True})
    assert response.status_code == 409
    stale = [item for item in response.get_json()["blocking"] if item["id"] == "parent-stale"]
    assert stale and "重新生成" in stale[0]["text"]


def test_export_success_marks_exported(page_client, m1db):
    plan = _with_parent(m1db, _parent_doc(seen=(True, True)))
    _mentor(page_client, m1db)
    page_client.post("/api/m1/plans/%d/parent/confirm" % plan["id"])
    response = page_client.post("/api/m1/plans/%d/parent/export" % plan["id"], json={"fits": True})
    assert response.status_code == 200
    assert response.get_json()["plan"]["parent_status"] == "exported"
    assert response.get_json()["print_url"].endswith("/parent/print")
