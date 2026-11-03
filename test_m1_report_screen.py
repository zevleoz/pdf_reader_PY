"""会后报告审阅页、部分条与内部证据记录（S2-P3）。

页面与 API 都跑在临时库上；不调用真实模型，不读写真实学生数据。
"""
from __future__ import annotations

import copy
import json

import pytest
from flask import Flask

import app_utils
import m1.report_store as report_store
from app_utils import BASE_DIR
from blueprints.m1 import M1_PARTS
from test_m1_api import login_as
from test_m1_store import m1db  # noqa: F401  临时库 + 学生/用户/Y4 数据

REPORT_JS = BASE_DIR / "static" / "m1" / "report_workspace.js"
REPORT_TEMPLATE = BASE_DIR / "templates" / "m1" / "report_workspace.html"
SAMPLE = BASE_DIR / "fixtures" / "m1_report_doc_sample.json"


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp
    from blueprints import m1_report
    from blueprints import students as students_bp

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app.register_blueprint(m1_report.bp)
    app.register_blueprint(students_bp.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _login(client, user_id, role, **settings):
    login_as(client, user_id, role)
    with client.session_transaction() as sess:
        for key, value in settings.items():
            sess[key] = value


def _seed_report(m1db):
    """把虚构样例当作已生成的当前版本（不调用 AI）。"""
    report_store.ensure_tables(m1db.engine)
    prep = m1db.prep()
    report = report_store.get_or_create_report(prep["id"], m1db.alice_id)
    raw = json.loads(SAMPLE.read_text(encoding="utf-8"))
    doc = raw.get("doc") if isinstance(raw.get("doc"), dict) else raw
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
    ratings = raw.get("y4_ratings") if isinstance(raw.get("y4_ratings"), dict) else {}
    report_store.add_version(
        report["id"], y4_ratings=ratings, evidence=evidence, ai_doc=doc,
        doc=copy.deepcopy(doc), checks=[],
        manifest={"sources": ["样例文档"], "fixture": SAMPLE.name},
        status="needs_check")
    return prep


# ---------------------------------------------------------------------------
# 1. 审阅页
# ---------------------------------------------------------------------------
def test_report_page_renders_for_admin(client, m1db):
    _login(client, m1db.admin_id, "admin")
    prep = m1db.prep()
    resp = client.get(f"/m1/preps/{prep['id']}/report")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="m1-platform"' in html
    assert 'id="r4TranscriptFile"' in html
    for label in ("导出 PDF", "内部证据记录", "审核通过", "正式发布", "重新打开"):
        assert label in html
    assert "暂不支持音频，请上传转写文字（txt、docx、pdf）。" in html


# ---------------------------------------------------------------------------
# 2. 概要账号与 viewer
# ---------------------------------------------------------------------------
def test_report_page_is_403_for_summary_and_viewer(client, m1db):
    prep = m1db.prep()
    _login(client, m1db.alice_id, "advisor", detail_level="summary")
    assert client.get(f"/m1/preps/{prep['id']}/report").status_code == 403
    _login(client, m1db.viewer_id, "viewer")
    assert client.get(f"/m1/preps/{prep['id']}/report").status_code == 403


# ---------------------------------------------------------------------------
# 3. 工作台的部分条
# ---------------------------------------------------------------------------
def test_workspace_links_to_report(client, m1db):
    _login(client, m1db.admin_id, "admin")
    prep = m1db.prep()
    html = client.get(f"/m1/preps/{prep['id']}").get_data(as_text=True)
    assert f'href="/m1/preps/{prep["id"]}/report"' in html
    assert 'title="即将上线">会后报告' not in html


# ---------------------------------------------------------------------------
# 4. 部分定义
# ---------------------------------------------------------------------------
def test_report_part_is_enabled():
    parts = {part["key"]: part for part in M1_PARTS}
    assert parts["report"]["enabled"] is True
    assert parts["report"]["href_suffix"] == "/report"
    assert parts["prep"]["href_suffix"] == ""


# ---------------------------------------------------------------------------
# 5. 内部证据记录
# ---------------------------------------------------------------------------
def test_evidence_page_has_protocol_fields(client, m1db):
    _login(client, m1db.admin_id, "admin")
    prep = _seed_report(m1db)
    resp = client.get(f"/m1/preps/{prep['id']}/report/evidence")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "内部证据审核记录（不对家庭发布）" in html
    for field in ("R4 能力编号", "来源文件", "证据位置", "发言人", "原始证据",
                  "AI 解释", "证据局限", "审核状态"):
        assert field in html
    assert "发言人待确认" in html


# ---------------------------------------------------------------------------
# 6. 前端约定
# ---------------------------------------------------------------------------
def test_screen_javascript_and_template_contract():
    js = REPORT_JS.read_text(encoding="utf-8")
    template = REPORT_TEMPLATE.read_text(encoding="utf-8")
    assert "innerHTML" not in js
    assert "http://" not in template
    assert "https://" not in template
