"""M1R-P3：三步审阅流程与一键导出 PDF。

页面跑在临时库上；不调用真实模型，不读写真实学生数据。
"""
from __future__ import annotations

import json
import re

from app_utils import BASE_DIR
from test_m1_report_screen import SAMPLE, _login, _seed_report, client, m1db  # noqa: F401

REPORT_JS = BASE_DIR / "static" / "m1" / "report_workspace.js"
STUDENT = json.loads(SAMPLE.read_text(encoding="utf-8"))["meta"]["student_name"]


def _page(client, m1db):  # noqa: F811
    _login(client, m1db.admin_id, "admin")
    prep = _seed_report(m1db)
    resp = client.get(f"/m1/preps/{prep['id']}/report")
    assert resp.status_code == 200
    return prep, resp.get_data(as_text=True)


def _tag(html: str, element_id: str) -> str:
    match = re.search(r'<[^>]*id="%s"[^>]*>' % element_id, html)
    assert match, element_id
    return match.group(0)


def test_step_nav(client, m1db):  # noqa: F811
    _, html = _page(client, m1db)
    assert 'id="r4StepNav"' in html
    nav = html.split('id="r4StepNav"', 1)[1].split("</nav>", 1)[0]
    for label in ("① 资料", "② 核对", "③ 导出"):
        assert label in nav


def test_sections_tagged(client, m1db):  # noqa: F811
    _, html = _page(client, m1db)
    for element_id, step in (
        ("r4Sources", "sources"),
        ("r4Cover", "sources"),
        ("r4GenerateCard", "sources"),
        ("r4Speakers", "review"),
        ("r4Todo", "review"),
        ("r4Content", "review"),
        ("r4Export", "export"),
    ):
        assert 'data-step="%s"' % step in _tag(html, element_id)


def test_no_save_buttons(client, m1db):  # noqa: F811
    _, html = _page(client, m1db)
    for element_id in ("r4TranscriptSave", "r4TranscriptUpload", "r4Download"):
        assert 'id="%s"' % element_id not in html


def test_export_link(client, m1db):  # noqa: F811
    _, html = _page(client, m1db)
    export = html.split('id="r4Export"', 1)[1].split("</section>", 1)[0]
    assert 'id="r4Print"' in export
    tag = re.search(r'<a[^>]*id="r4Print"[^>]*>', export).group(0)
    assert re.search(r'href="[^"]+/report/print\?print=1"', tag)
    text = export.split(tag, 1)[1].split("</a>", 1)[0]
    assert text.strip() == "导出 PDF"


def test_print_autostart_and_title(client, m1db):  # noqa: F811
    _login(client, m1db.admin_id, "admin")
    prep = _seed_report(m1db)
    resp = client.get(f"/m1/preps/{prep['id']}/report/print")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "get('print') === '1'" in html
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert title.startswith(STUDENT)
    assert "_首次情绪力分析报告_" in title


def test_js_has_flow_functions():
    js = REPORT_JS.read_text(encoding="utf-8")
    for name in ("function showStep(", "function loadSpeakers(", "function renderSpeakers(",
                 "function renderExportState("):
        assert name in js
    assert "/report/speakers" in js
    body = js.split("function renderSpeakers(", 1)[1].split("\n  function ", 1)[0]
    assert "innerHTML" not in body


def test_js_guards_transcript_replace():
    js = REPORT_JS.read_text(encoding="utf-8")
    for text in ("function transcriptExists(", "r4TranscriptReplace",
                 "将用新内容替换现有逐字稿", "saveTranscript(true)"):
        assert text in js


def test_js_print_shown_when_published():
    js = REPORT_JS.read_text(encoding="utf-8")
    line = next(item for item in js.splitlines() if item.strip().startswith("show(refs.print,"))
    assert "published" in line


def test_js_generate_flushes_transcript():
    js = REPORT_JS.read_text(encoding="utf-8")
    body = js.split("function generate(", 1)[1].split("\n  function ", 1)[0]
    assert "clearTimeout(transcriptTimer)" in body
