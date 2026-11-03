"""M1R-P6：报告预览显示规则、就地编辑与第②步界面。

页面和 API 跑在临时库上；不调用真实模型，不读写真实学生数据。
"""
from __future__ import annotations

import copy
import json
import re

import m1.report_store as report_store
from app_utils import BASE_DIR
from m1 import report_display
from test_m1_report_screen import SAMPLE, _login, _seed_report, client, m1db  # noqa: F401

EDIT_JS = BASE_DIR / "static" / "m1" / "report_edit.js"
FIXTURE = json.loads(SAMPLE.read_text(encoding="utf-8"))


def _item(item_id, location, *, source="FT", ok=True, code="R1.1"):
    return {"id": item_id, "quote": "引文", "ability_codes": [code], "source": source,
            "location": location, "status": "已确认" if ok else "待核实",
            "quote_verified": ok}


def _sentence(chars, first="一"):
    return first + "字" * (chars - len(first) - 1) + "。"


def _doc(meeting, *, src="ai", tags=("信息不足",), y4=()):
    row = {"meeting": {"text": meeting, "src": src},
           "other_clues": {"text": "", "src": "ai"},
           "tags": list(tags), "y4_selected": list(y4)}
    return {"dims": {"R1": {"abilities": {"R1.1": row}}}}


def _row(doc):
    return doc["dims"]["R1"]["abilities"]["R1.1"]


def _seed_custom(m1db, doc, evidence=None):  # noqa: F811
    report_store.ensure_tables(m1db.engine)
    prep = m1db.prep()
    report = report_store.get_or_create_report(prep["id"], m1db.alice_id)
    report_store.add_version(report["id"], y4_ratings=FIXTURE["y4_ratings"],
                             evidence=FIXTURE["evidence"] if evidence is None else evidence,
                             ai_doc=doc, doc=copy.deepcopy(doc), checks=[],
                             manifest={"sources": ["样例文档"]}, status="needs_check")
    return prep


def _tag(html, element_id):
    match = re.search(r'<[^>]*id="%s"[^>]*>' % element_id, html)
    assert match, element_id
    return match.group(0)


# ---------------------------------------------------------------------------
# 显示规则
# ---------------------------------------------------------------------------
def test_sources_line_names_only():
    evidence = [_item("e1", "其他资料：Miranda review"),
                _item("e2", "其他资料：访谈 9/25"),
                _item("e3", "First Touch")]
    line = report_display.sources_line(evidence, "R1.1")
    assert line == "另见：Miranda review；访谈 9/25等 3 份资料。"
    assert "“" not in line


def test_sources_line_skips_meeting_and_unsupported():
    evidence = [_item("e1", "M1 会议", source="M1"),
                _item("e2", "其他资料：未核实", ok=False)]
    assert report_display.sources_line(evidence, "R1.1") == ""


def test_display_caps_ai_not_edited():
    a, b, c = _sentence(30, "一"), _sentence(30, "二"), _sentence(30, "三")
    doc = _doc(a + b + c)
    before = copy.deepcopy(doc)
    shown = report_display.display_doc(doc, [])
    assert _row(shown)["meeting"]["text"] == a + b
    edited_doc = _doc(a + b + c, src="edited")
    assert _row(report_display.display_doc(edited_doc, []))["meeting"]["text"] == a + b + c
    assert doc == before


def test_display_y4_capped():
    doc = _doc("", y4=("001", "002", "003", "004", "005", "006"))
    shown = report_display.display_doc(doc, [])
    assert _row(shown)["y4_selected"] == ["001", "002", "003"]


def test_display_keeps_edited_clues():
    doc = _doc("", y4=("001",))
    _row(doc)["other_clues"] = {"text": "家长访谈：“嗯”。", "src": "edited"}
    shown = report_display.display_doc(doc, [_item("e1", "其他资料：Miranda review")])
    assert _row(shown)["other_clues"]["text"] == "家长访谈：“嗯”。"


def test_display_drops_flag_on_cut_sentence():
    a, b, c = _sentence(30, "一"), _sentence(30, "二"), _sentence(30, "三")
    path = ["dims", "R1", "abilities", "R1.1", "meeting"]
    doc = _doc(a + b + c)
    doc["guard"] = {"flags": [{"sentence": a, "path": path},
                             {"sentence": c, "path": path}]}
    shown = report_display.display_doc(doc, [])
    assert [flag["sentence"] for flag in shown["guard"]["flags"]] == [a]


# ---------------------------------------------------------------------------
# 打印页
# ---------------------------------------------------------------------------
def test_print_uses_display_rules(client, m1db):  # noqa: F811
    doc = copy.deepcopy(FIXTURE)
    row = _row(doc)
    row["other_clues"] = {"text": "家长访谈：“我很担心他的情绪。”另：“他晚上睡不好。”",
                          "src": "ai"}
    row["y4_selected"] = ["004", "011", "012", "013", "014", "016"]
    evidence = FIXTURE["evidence"] + [_item("e25", "其他资料：Miranda review")]
    prep = _seed_custom(m1db, doc, evidence)
    _login(client, m1db.admin_id, "admin")
    html = client.get(f"/m1/preps/{prep['id']}/report/print").get_data(as_text=True)

    assert "另见：Miranda review。" in html
    cell = re.search(r'<div class="multiline">(.*?)</div>', html, re.S).group(1)
    assert "“" not in cell
    rows = html.split("<tr>")
    assert max(item.count('class="y4-line"') for item in rows) <= 3


def test_print_edit_mode(client, m1db):  # noqa: F811
    prep = _seed_report(m1db)
    _login(client, m1db.admin_id, "admin")
    url = f"/m1/preps/{prep['id']}/report/print"
    base = client.get(url).get_data(as_text=True)
    edit = client.get(url + "?edit=1").get_data(as_text=True)
    for needle in ('id="editData"', 'id="editCsrf"', 'contenteditable="plaintext-only"',
                   "data-tags-path", "/m1/assets/report_edit.js"):
        assert needle in edit, needle
    for needle in ('id="editData"', 'contenteditable=', "data-tags-path",
                   "/m1/assets/report_edit.js"):
        assert needle not in base, needle

    report = report_store.get_report(prep["id"])
    report_store.approve(report["id"])
    report_store.publish(report["id"])
    published = client.get(url + "?edit=1").get_data(as_text=True)
    assert 'id="editData"' not in published


# ---------------------------------------------------------------------------
# 检查与第②步界面
# ---------------------------------------------------------------------------
def test_checks_follow_display(client, m1db):  # noqa: F811
    doc = copy.deepcopy(FIXTURE)
    path = ["dims", "R1", "abilities", "R1.1", "other_clues"]
    _row(doc)["other_clues"] = {"text": "他说“根本没说过的这句话”。", "src": "ai"}
    prep = _seed_custom(m1db, doc)
    _login(client, m1db.admin_id, "admin")
    body = client.get(f"/api/m1/preps/{prep['id']}/report").get_json()
    assert not [c for c in body["checks"]
                if c["code"] == "quote_unverified" and list(c["path"]) == path]


def test_workspace_preview_markup(client, m1db):  # noqa: F811
    prep = _seed_report(m1db)
    _login(client, m1db.admin_id, "admin")
    html = client.get(f"/m1/preps/{prep['id']}/report").get_data(as_text=True)

    assert 'data-step="review"' in _tag(html, "r4PreviewCard")
    assert 'id="r4Preview"' in html
    assert 'id="r4Regenerate"' in html
    assert re.search(r'<div id="r4Legacy" hidden>', html)
    card = html.split('id="r4PreviewCard"', 1)[1].split("</section>", 1)[0]
    assert 'id="r4Safety"' in card


def test_edit_js_contract():
    js = EDIT_JS.read_text(encoding="utf-8")
    for text in ("'/doc'", "报告还不完整", "m1-report-edit"):
        assert text in js, text
    assert "plaintext" not in js
    assert "innerHTML" not in js
