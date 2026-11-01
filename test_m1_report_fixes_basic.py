"""S2-P5 修复 6、7：家庭版 PDF 版式（用无头 Chrome 渲染后读回）与样例文档。

不调用真实 AI，不连接服务器，不读写 data/y4_students.db；PDF 写在 pytest 的临时目录。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import fitz
import pytest
from flask import Flask, render_template
from playwright.sync_api import sync_playwright

import test_m1_report_print as P
from app_utils import BASE_DIR
from m1 import report_jobs, report_store, report_y4
from test_m1_store import m1db  # noqa: F401  临时库与虚构学生
from test_m1_report_core import rdb  # noqa: F401  沙盒库，与 test_m1_report_core 相同

FIXTURE_PATH = BASE_DIR / "fixtures" / "m1_report_doc_sample.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
MAPPING = json.loads((BASE_DIR / "m1" / "kb" / "r4_report_mapping.json").read_text(encoding="utf-8"))
PAPER = (254, 253, 251)          # #FEFDFB
QUOTE_MARKS = "“”\"「」‘’"
REQUIRED_EVIDENCE = {"id", "ability_codes", "source", "location", "speaker", "type", "quote",
                     "quote_verified", "interpretation", "limits", "status"}


# ---------------------------------------------------------------------------
# 渲染：裸 Flask 应用渲染模板，再由 Chrome 打印成 PDF
# ---------------------------------------------------------------------------
def _y4_lines(doc):
    lines = {}
    for dim in doc["dims"].values():
        for code, ability in dim["abilities"].items():
            lines[code] = [doc["y4_ratings"][c]["family_line"]
                           for c in ability["y4_selected"] if c in doc["y4_ratings"]]
    return lines


def _html(draft: bool) -> str:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.secret_key = "test-secret"
    codes = [a["code"] for d in P.FIXED["dims"] for a in d["abilities"]]
    with app.test_request_context("/m1/preps/1/report/print"):
        html = render_template("m1/report_print.html", fixed=P.FIXED, doc=FIXTURE,
                               y4_lines=_y4_lines(FIXTURE), appendix=P._appendix(*codes),
                               draft=draft, status_label="AI 草稿" if draft else "审核通过")
    return html.replace("/m1/assets/", (BASE_DIR / "static" / "m1").as_uri() + "/")


def _pdf(tmp_path_factory, draft: bool) -> Path:
    folder = tmp_path_factory.mktemp("print_draft" if draft else "print_final")
    page = folder / "page.html"
    page.write_text(_html(draft), encoding="utf-8")
    out = folder / "report.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        tab = browser.new_page()
        tab.goto(page.as_uri(), wait_until="load")
        tab.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    return out


@pytest.fixture(scope="module")
def draft_pdf(tmp_path_factory):
    return _pdf(tmp_path_factory, draft=True)


@pytest.fixture(scope="module")
def final_pdf(tmp_path_factory):
    return _pdf(tmp_path_factory, draft=False)


# ---------------------------------------------------------------------------
# 修复 6：版式
# ---------------------------------------------------------------------------
def test_draft_mark_is_on_every_page(draft_pdf, final_pdf):
    with fitz.open(draft_pdf) as doc:
        assert len(doc) > 3
        missing = [i + 1 for i, page in enumerate(doc) if "草稿" not in page.get_text()]
    assert missing == []
    with fitz.open(final_pdf) as doc:
        assert all("草稿" not in page.get_text() for page in doc)


def test_draft_margin_rule_only_when_draft():
    assert '@top-center { content: "草稿"' in _html(draft=True)
    assert "草稿" not in _html(draft=False)


def test_paper_colour_matches_page_in_print(draft_pdf):
    """封面与 03 页：没有纯白块，页边与正文底色都在 #FEFDFB 上下 1 级以内。"""
    with fitz.open(draft_pdf) as doc:
        cover = doc[0]
        dim_page = next(p for p in doc if "四维发展分析" in p.get_text())
        for page in (cover, dim_page):
            pix = page.get_pixmap(dpi=40)
            raw = pix.samples
            pixels = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
            assert not any(min(px) >= 255 for px in pixels), "页面出现纯白像素，纸面不一致"
            mode, _count = Counter(pixels).most_common(1)[0]
            assert all(abs(a - b) <= 1 for a, b in zip(mode, PAPER)), mode
            corner = tuple(pix.pixel(1, 1))
            assert all(abs(a - b) <= 1 for a, b in zip(corner, PAPER)), corner


def test_tag_chips_stay_on_one_line(draft_pdf):
    with fitz.open(draft_pdf) as doc:
        hits = [(i + 1, page.search_for("确认发展需求")) for i, page in enumerate(doc)]
        hits = [(n, rects) for n, rects in hits if rects]
        assert hits, "样例 03 页应包含“确认发展需求”标签"
        for number, rects in hits:
            assert all(r.height < 14 for r in rects), (number, rects)
            assert "确认发展需求" in doc[number - 1].get_text()


def test_ability_table_widths_are_510pt():
    css = (BASE_DIR / "static" / "m1" / "report_print.css").read_text(encoding="utf-8")
    widths = [int(w) for w in re.findall(r"\.ability-table col\.c\d \{ width: (\d+)pt", css)]
    assert widths == [66, 100, 100, 172, 72]
    assert sum(widths) == 510


# ---------------------------------------------------------------------------
# 修复 7：样例文档
# ---------------------------------------------------------------------------
def _abilities():
    for dim in FIXTURE["dims"].values():
        yield from dim["abilities"].items()


def test_sample_student_is_fictional():
    assert FIXTURE["meta"]["student_name"] == "示例学生"


def test_family_text_has_no_quotation_marks():
    for step in FIXTURE["plan"]:
        text = step["family"]["text"]
        assert not any(mark in text for mark in QUOTE_MARKS), (step["ability"], text)


def test_y4_selected_only_uses_mapping_codes():
    for code, ability in _abilities():
        assert ability["y4_selected"], code
        assert set(ability["y4_selected"]) <= set(MAPPING["abilities"][code]["indicators"]), code


def test_sample_tags_are_known_tags():
    known = {t["key"] for t in P.FIXED["tags"]}
    for code, ability in _abilities():
        assert set(ability["tags"]) <= known, code


def test_sample_y4_ratings_cover_selected_codes():
    selected = {c for _code, a in _abilities() for c in a["y4_selected"]}
    ratings = FIXTURE["y4_ratings"]
    assert set(ratings) == selected
    for code, entry in ratings.items():
        assert entry["code"] == code
        assert entry["state"] in ("ok", "raw"), (code, entry)


def test_sample_evidence_is_complete_and_linked():
    evidence = {e["id"]: e for e in FIXTURE["evidence"]}
    assert len(FIXTURE["evidence"]) >= 8 and len(evidence) == len(FIXTURE["evidence"])
    for item in FIXTURE["evidence"]:
        assert REQUIRED_EVIDENCE <= set(item), item["id"]
    for code, ability in _abilities():
        for eid in ability["evidence_ids"]:
            assert eid in evidence, (code, eid)
            assert code in evidence[eid]["ability_codes"], (code, eid)


def test_sample_loads_without_a_transcript(rdb):
    version_id = report_jobs.load_fixture(rdb.prep_row["id"], str(FIXTURE_PATH))
    loaded = report_store.get_version(version_id)
    assert len(loaded["evidence"]) == len(FIXTURE["evidence"])
    assert set(loaded["y4_ratings"]) == set(FIXTURE["y4_ratings"])
