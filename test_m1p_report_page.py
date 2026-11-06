"""M1P-P4：会后报告页套用新外壳，拆成 ① 逐字稿 / ② 核对并发布。"""
from __future__ import annotations

import re

import pytest
from flask import Flask

import app_utils
from app_utils import BASE_DIR
from test_m1_api import login_as
from test_m1_report_screen import _seed_report
from test_m1_store import m1db  # noqa: F401  临时库 + 学生/用户/Y4 数据

REPORT_JS = BASE_DIR / "static" / "m1" / "report_workspace.js"
REPORT_CSS = BASE_DIR / "static" / "m1" / "report_workspace.css"


@pytest.fixture()
def client(m1db, monkeypatch):  # noqa: F811
    from blueprints import m1 as m1_bp
    from blueprints import m1_report

    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    app.register_blueprint(m1_bp.bp)
    app.register_blueprint(m1_report.bp)
    app_utils.register_admin_context(app)
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    app.add_template_filter(app_utils.dt_short, "dt_short")
    return app.test_client()


def _page(client, m1db):  # noqa: F811
    login_as(client, m1db.admin_id, "admin")
    prep = _seed_report(m1db)
    resp = client.get(f"/m1/preps/{prep['id']}/report")
    assert resp.status_code == 200
    return prep, resp.get_data(as_text=True)


def _tag(html: str, element_id: str) -> str:
    match = re.search(r'<[^>]*id="%s"[^>]*>' % element_id, html)
    assert match, element_id
    return match.group(0)


def test_report_page_uses_new_shell(client, m1db):  # noqa: F811
    prep, html = _page(client, m1db)

    assert 'class="app"' in html
    assert 'data-platform="m1"' in html
    assert "/m1/assets/ark.css" in html
    assert "/m1/assets/report_workspace.css" in html
    assert "admin_v2" not in html
    assert "/m1/assets/m1.css" not in html

    assert 'class="cr"' in html
    assert f'href="/m1/preps/{prep["id"]}"' in html
    assert 'class="head th"' in html
    assert 'id="r4Tag"' in html


def test_two_step_wrappers(client, m1db):  # noqa: F811
    prep, html = _page(client, m1db)

    assert 'data-step="sources"' in _tag(html, "r4StepSources")
    assert 'data-step="review"' in _tag(html, "r4StepReview")
    assert re.search(r'<div class="wk2 wide" id="r4StepReview"', html)
    assert "③" not in html

    sources = html.split('id="r4StepSources"', 1)[1].split('id="r4StepReview"', 1)[0]
    review = html.split('id="r4StepReview"', 1)[1].split('id="r4Legacy"', 1)[0]
    for element_id in ("r4TranscriptLine", "r4TranscriptReplace", "r4OtherDrop",
                       "r4GenerateBody", "r4GenBox"):
        assert 'id="%s"' % element_id in sources, element_id
    for element_id in ("r4Preview", "r4Export", "r4NeedCard", "r4NeedCount",
                       "r4NeedText", "r4TipCount", "r4Speakers"):
        assert 'id="%s"' % element_id in review, element_id
    assert f'href="/m1/preps/{prep["id"]}/report/print?print=1"' in html


def test_export_card_keeps_links(client, m1db):  # noqa: F811
    prep, html = _page(client, m1db)
    export = html.split('id="r4Export"', 1)[1].split("</div>", 1)[0]
    assert f'/m1/preps/{prep["id"]}/report/print?print=1' in export
    assert f'/m1/preps/{prep["id"]}/report/evidence' in export
    assert 'id="r4Print"' in export and 'id="r4Evidence"' in export


def test_report_page_js_step_logic():
    js = REPORT_JS.read_text(encoding="utf-8")
    assert "var STEPS = ['sources', 'review']" in js
    assert "querySelectorAll('#r4StepNav a[data-step]')" in js
    assert "if (name === 'review' && !state.doc) name = 'sources'" in js
    assert "aria-disabled" in js
    assert "refs.genOpen" in js
    assert "hashchange" in js


def test_report_page_js_need_and_generation():
    js = REPORT_JS.read_text(encoding="utf-8")
    for text in (
        "function renderNeed(blockCount, tipCount)",
        "renderNeed(blocks.length, reviews.length)",
        "在报告的黄色框里补全。",
        "showGenPanel()",
        "renderSteps(job.steps",
        "报告已生成",
        "report_other",
        "transcript_filename",
    ):
        assert text in js, text


def test_report_page_css_scoped():
    css = REPORT_CSS.read_text(encoding="utf-8")
    assert "#r4Review .r4-preview" in css
    assert "width: 100%" in css
    assert "#r4Review .r4-spk-row" in css
