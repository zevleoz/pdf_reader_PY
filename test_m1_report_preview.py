"""M1R-P6：报告预览显示规则、就地编辑与第②步界面。

页面和 API 跑在临时库上；不调用真实模型，不读写真实学生数据。
"""
from __future__ import annotations

import copy
import json
import re

import m1.report_store as report_store
from app_utils import BASE_DIR
from m1 import report_display, report_kb
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
def test_sources_line_never_generated():
    evidence = [_item("e1", "其他资料：Miranda review"),
                _item("e2", "其他资料：访谈 9/25"),
                _item("e3", "First Touch")]
    assert report_display.sources_line(evidence, "R1.1") == ""


def test_display_removes_generated_source_line_from_existing_draft():
    doc = _doc("", y4=("001",))
    _row(doc)["other_clues"] = {
        "text": "另见：文字记录：个人兴趣与学业情况访谈 2026年9月25日；Miranda review。",
        "src": "ai",
    }
    evidence = [_item("e1", "其他资料：Miranda review")]
    shown = report_display.display_doc(doc, evidence)
    assert _row(shown)["other_clues"]["text"] == ""


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

    assert "另见：" not in html
    assert "Miranda review" not in html
    assert "家长访谈：“我很担心他的情绪。”" not in html
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
def test_print_edit_export_controls(client, m1db):  # noqa: F811
    prep = _seed_report(m1db)
    _login(client, m1db.admin_id, "admin")
    url = f"/m1/preps/{prep['id']}/report/print"
    base = client.get(url).get_data(as_text=True)
    edit = client.get(url + "?edit=1").get_data(as_text=True)

    print_edit = _tag(base, "printEdit")
    assert f'href="{url}?edit=1"' in print_edit
    assert "修改文字" in base.split(print_edit, 1)[1].split("</a>", 1)[0]

    export = _tag(edit, "editExport")
    assert f'data-export-url="{url}?print=1"' in export
    assert "完成并导出 PDF" in edit.split(export, 1)[1].split("</button>", 1)[0]


def test_edit_js_export_contract():
    js = EDIT_JS.read_text(encoding="utf-8")
    assert "getElementById('editExport')" in js
    assert "document.activeElement" in js
    assert "active.blur()" in js
    assert "var pending = queue" in js
    assert "if (json === null)" in js
    assert "window.location.href = exportBtn.getAttribute('data-export-url')" in js


def _edit_data(html):
    node = re.search(r'<script type="application/json" id="editData">(.*?)</script>', html, re.S)
    assert node
    return json.loads(node.group(1))


def test_edit_plan_rows_can_change_add_and_remove(client, m1db):  # noqa: F811
    prep = _seed_report(m1db)
    _login(client, m1db.admin_id, "admin")
    html = client.get(f"/m1/preps/{prep['id']}/report/print?edit=1").get_data(as_text=True)

    assert html.count('class="plan-ability"') == 3
    assert html.count('class="plan-del"') == 3
    assert "disabled" in _tag(html, "planAdd")
    for tag in re.findall(r'<button[^>]*class="plan-del"[^>]*>', html):
        assert "disabled" not in tag
    data = _edit_data(html)
    codes = [item["code"] for item in data["abilities"]]
    assert set(codes) == set(report_kb.ability_map())
    assert all(set(item) == {"code", "name", "dim"} for item in data["abilities"])


def test_edit_plan_single_row_cannot_be_deleted(client, m1db):  # noqa: F811
    doc = copy.deepcopy(FIXTURE)
    doc["plan"] = doc["plan"][:1]
    prep = _seed_custom(m1db, doc)
    _login(client, m1db.admin_id, "admin")
    html = client.get(f"/m1/preps/{prep['id']}/report/print?edit=1").get_data(as_text=True)

    assert 'class="plan-ability"' in html
    assert "disabled" not in _tag(html, "planAdd")
    delete = re.search(r'<button[^>]*class="plan-del"[^>]*>', html)
    assert delete and "disabled" in delete.group(0)


def test_edit_js_plan_contract():
    js = EDIT_JS.read_text(encoding="utf-8")
    for text in ("function savePlan", "function planValue", "planAdd",
                 "plan-del", "data-plan-ability-select"):
        assert text in js, text
    assert js.count("savePlan") >= 4
    assert "innerHTML" not in js
    # 导出仍等待串行队列里的最后一次保存
    assert "var pending = queue" in js


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

    review = html.split('id="r4StepReview"', 1)[1].split('id="r4Legacy"', 1)[0]
    assert 'data-step="review"' in _tag(html, "r4StepReview")
    assert 'id="r4Preview"' in review
    assert 'id="r4Regenerate"' in review
    assert re.search(r'<div id="r4Legacy" hidden>', html)
    assert 'id="r4Safety"' in review


def test_edit_js_contract():
    js = EDIT_JS.read_text(encoding="utf-8")
    for text in ("'/doc'", "报告还不完整", "m1-report-edit"):
        assert text in js, text
    assert "plaintext" not in js
    assert "innerHTML" not in js
