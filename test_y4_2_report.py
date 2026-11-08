"""Y4-2 学习力报告：build_context、页数取舍、路由、has_b3。"""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date

import pytest
from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "new_iteration"))

import app_utils  # noqa: E402
import db as _db  # noqa: E402
import render_v2  # noqa: E402
import render_y4_2  # noqa: E402
from blueprints import reports as reports_api  # noqa: E402
from blueprints import students as students_api  # noqa: E402

VALUES = {"063": "87", "064": "87", "065": "79", "066": "8.4", "067": "6.0",
          "069": "7.2", "070": "3.6", "128": "6.4", "129": "5.8", "131": "6.1",
          "132": "5.2", "134": "8.1", "135": "7.1"}
ALL_CODES = ["063", "064", "065", "066", "067", "069", "070", "128", "129", "131", "132", "134", "135"]


def _detail():
    with open(os.path.join(BASE, "fixtures", "b3_detail_sample.json"), encoding="utf-8") as f:
        return json.load(f)


def _raw(values=None, detail=True, titles=("A2", "B3")):
    vals = dict(VALUES if values is None else values)
    raw = {
        "student": {"name": "林同学", "grade": "五年级", "test_date": "2026-11-07"},
        "pdf_titles": list(titles),
        "schema_124": [{"code": c, "label": c, "value": vals.get(c, ""), "type": "number"}
                       for c in ALL_CODES],
    }
    if detail:
        raw["b3_detail"] = _detail()
    return raw


def test_new_b3_pages_and_no_p7():
    ctx = render_y4_2.build_context(_raw())
    assert ctx["pages"] == ["P1", "P2", "P3", "P4", "P5", "P6", "P6b"]
    assert 6 <= len(ctx["pages"]) <= 7
    assert not any(p.startswith("P7") for p in ctx["pages"])
    assert [e["tier"] for e in ctx["ef"]] == ["T2", "T2", "T2"]
    assert ctx["s134"]["tier"] == "T2" and ctx["s135"]["label"] == "较常使用"
    assert sum(len(g["rows"]) for p in ctx["practice_pages"] for g in p) == 20
    assert sum(len(g["rows"]) for p in ctx["exec_pages"] for g in p) == 17


def test_peer_dot_only_with_both_averages():
    ctx = render_y4_2.build_context(_raw())
    assert all(q["peer"] for q in ctx["quads"]) and ctx["quads_peer"]
    vals = {k: v for k, v in VALUES.items() if k not in ("128", "129")}
    ctx = render_y4_2.build_context(_raw(vals))
    mot, met = ctx["quads"]
    assert mot["peer"] is None and met["peer"] is not None
    vals = {k: v for k, v in VALUES.items() if k not in ("129", "132")}
    ctx = render_y4_2.build_context(_raw(vals))
    assert not ctx["quads_peer"]
    html = render_y4_2._env().get_template(render_y4_2.TEMPLATE_NAME).render(**ctx)
    assert "同龄均值" not in html


def test_html_has_data_labels_and_footer():
    ctx = render_y4_2.build_context(_raw())
    html = render_y4_2._env().get_template(render_y4_2.TEMPLATE_NAME).render(**ctx)
    assert html.count("数据来源：B3 核心学习能力报告") == 7
    assert "双高型" in html and "深度理解型" in html and "主动回忆" in html
    assert "习惯清单" not in html


def test_old_b3_only_p1_and_p2():
    vals = {k: v for k, v in VALUES.items() if k in ("063", "064", "065", "066", "067", "069", "070")}
    raw = _raw(vals, detail=False)
    ctx = render_y4_2.build_context(raw)
    assert ctx["pages"] == ["P1", "P2"]
    assert ctx["motivation"] is None and ctx["method"] is None
    assert ctx["s134"] is None and ctx["s135"] is None
    html = render_y4_2._env().get_template(render_y4_2.TEMPLATE_NAME).render(**ctx)
    assert "类型定位" not in html and "双高型" not in html


def test_has_b3_rule():
    assert render_y4_2.has_b3(_raw({}, detail=False, titles=("B3",)))
    r = _raw({}, detail=False, titles=())
    r["schema_124"].append({"code": "071", "value": "5"})
    assert render_y4_2.has_b3(r)
    assert not render_y4_2.has_b3(_raw({}, detail=False, titles=("A2",)))
    assert not render_y4_2.has_b3({})


# ---------------------------------------------------------------- 路由

@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'y42.db'}")

    @event.listens_for(engine, "connect")
    def _fk(conn, _r):
        conn.execute("PRAGMA foreign_keys=ON")

    _db.Base.metadata.create_all(engine, tables=[_db.Student.__table__, _db.Report.__table__])
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    ids = {}
    with Session(engine) as sess:
        st = _db.Student(student_code="Y4-9402", name="林同学", grade="5", advisor_name="Alice")
        sess.add(st)
        sess.commit()
        ids["student"] = st.id
        for key, raw in (("b3", _raw()), ("nob3", _raw({}, detail=False, titles=("A2",)))):
            r = _db.Report(student_id=st.id, report_date=date(2026, 11, 7), pdf_path="x.pdf",
                           data_json=json.dumps(raw, ensure_ascii=False))
            sess.add(r)
            sess.commit()
            ids[key] = r.id
    out = tmp_path / "output"
    monkeypatch.setattr(reports_api, "OUTPUT_DIR", out)
    yield ids
    engine.dispose()


@pytest.fixture()
def client(env):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="t", TESTING=True)
    app.register_blueprint(reports_api.bp)
    app.register_blueprint(students_api.bp)
    with app.test_client() as c:
        with c.session_transaction() as s:
            s.update(user_id=1, role="admin", advisor_name="Alice",
                     display_name="管理员", detail_level="full")
        yield c


def test_route_400_without_b3(client, env):
    resp = client.post(f"/api/reports/{env['nob3']}/y4-2")
    assert resp.status_code == 400


def test_route_returns_pdf_with_renderer_mocked(client, env, monkeypatch):
    def fake(raw, out):
        out.write_bytes(b"%PDF-1.4 fake")
        return out
    monkeypatch.setattr(render_y4_2, "render_pdf", fake)
    resp = client.post(f"/api/reports/{env['b3']}/y4-2")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert "UTF-8''" in resp.headers["Content-Disposition"]
    assert "Y4-2" in resp.headers["Content-Disposition"] or "%" in resp.headers["Content-Disposition"]


def _chrome_ok():
    try:
        render_v2.find_chrome()
    except RuntimeError:
        return False
    return os.path.isdir(os.path.join(BASE, "new_iteration", "branding"))


@pytest.mark.skipif(not _chrome_ok(), reason="需要 Chrome 与 new_iteration/branding")
def test_route_real_pdf(client, env):
    resp = client.post(f"/api/reports/{env['b3']}/y4-2")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")


def test_reports_list_has_b3_flag(client, env):
    resp = client.get(f"/api/students/{env['student']}/reports")
    assert resp.status_code == 200
    flags = {r["id"]: r["has_b3"] for r in resp.get_json()["reports"]}
    assert flags == {env["b3"]: True, env["nob3"]: False}
