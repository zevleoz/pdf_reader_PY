"""S2-P2：家庭版 PDF 模板（打印页）的渲染契约。

只测服务端 Jinja 输出，不依赖 R1 的路由。固定文案一律取自 r4_report_fixed.json，
样例内容取自 fixtures/m1_report_doc_sample.json。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask, render_template

from app_utils import BASE_DIR

R4_DIRS = [
    BASE_DIR / "m1" / "kb",
    BASE_DIR / "docs" / "audits" / "plans-hub" / "r4-report",
    BASE_DIR.parents[1] / "docs" / "audits" / "plans-hub" / "r4-report",
]


def _load(name: str) -> dict:
    for folder in R4_DIRS:
        path = Path(folder) / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError(name)


FIXED = _load("r4_report_fixed.json")
SCENES = _load("r4_report_scenes.json")["scenes"]
FIXTURE = json.loads(
    (BASE_DIR / "fixtures" / "m1_report_doc_sample.json").read_text(encoding="utf-8")
)

ABILITY_NAMES = {
    ability["code"]: ability["name"]
    for dim in FIXED["dims"]
    for ability in dim["abilities"]
}

Y4_LINES = {
    code: ["情绪稳定性：7.2，较好（均分 5.8）", "自我概念：6.4，一般（均分 5.5）"]
    for code in ABILITY_NAMES
}


@pytest.fixture()
def app():
    test_app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    test_app.secret_key = "test-secret"
    return test_app


def _render(app, *, doc=None, appendix=None, draft=False, status_label="AI 草稿") -> str:
    with app.test_request_context("/m1/preps/1/report/print"):
        return render_template(
            "m1/report_print.html",
            fixed=FIXED,
            doc=FIXTURE if doc is None else doc,
            y4_lines=Y4_LINES,
            appendix=[] if appendix is None else appendix,
            draft=draft,
            status_label=status_label,
        )


def _appendix(*codes: str) -> list:
    rows = []
    for code in codes:
        dim = next(d for d in FIXED["dims"] if d["id"] == code.split(".")[0])
        tags = FIXTURE["dims"][dim["id"]]["abilities"][code]["tags"]
        rows.append({
            "code": code,
            "name": ABILITY_NAMES[code],
            "tags": tags,
            "scene": SCENES[code],
        })
    return rows


# ---------------------------------------------------------------------------
# 1. 固定能力文案完整出现
# ---------------------------------------------------------------------------
def test_all_18_ability_names_and_descriptions(app):
    html = _render(app)
    for dim in FIXED["dims"]:
        for ability in dim["abilities"]:
            assert ability["name"] in html
            assert ability["description"] in html


# ---------------------------------------------------------------------------
# 2. 不得残留模板占位符
# ---------------------------------------------------------------------------
def test_no_ai_placeholder_left(app):
    html = _render(app)
    assert "[ai填入]" not in html


# ---------------------------------------------------------------------------
# 3. 每个标签都带固定配色
# ---------------------------------------------------------------------------
def test_every_fixture_tag_uses_fixed_colours(app):
    html = _render(app)
    used = {
        tag
        for dim in FIXTURE["dims"].values()
        for ability in dim["abilities"].values()
        for tag in ability["tags"]
    }
    assert used == {tag["key"] for tag in FIXED["tags"]}

    for tag in FIXED["tags"]:
        assert tag["key"] in html
        assert "background:%s;border-color:%s;color:%s;" % (
            tag["bg"], tag["border"], tag["ink"],
        ) in html


# ---------------------------------------------------------------------------
# 4. 家庭版不出现指标编号、内部备注或证据编号
# ---------------------------------------------------------------------------
def test_no_indicator_codes_or_internal_evidence(app):
    html = _render(app)
    assert "013" not in html
    assert "internal_note" not in html
    assert "evidence_ids" not in html
    # 证据条目的编号值也不应出现在家庭版
    assert "e24" not in html
    # 但 Y4 的家庭版文字必须在
    assert Y4_LINES["R1.1"][0] in html


# ---------------------------------------------------------------------------
# 5. 附录按有无内容出现或整块省略
# ---------------------------------------------------------------------------
def test_appendix_omitted_when_empty(app):
    html = _render(app)
    assert FIXED["appendix"]["title_b"] not in html
    assert FIXED["appendix"]["title_a"] not in html
    assert FIXED["appendix"]["note"] not in html


def test_appendix_lists_each_ability_once(app):
    rows = _appendix("R1.2", "R2.2")
    html = _render(app, appendix=rows)
    assert FIXED["appendix"]["title_b"] in html
    for row in rows:
        assert row["scene"] in html
        assert html.count(row["scene"]) == 1
        assert row["name"] in html


# ---------------------------------------------------------------------------
# 6. 草稿标记
# ---------------------------------------------------------------------------
def test_draft_mark_present_only_for_draft(app):
    draft_html = _render(app, draft=True)
    final_html = _render(app, draft=False, status_label="审核通过")
    assert "draftmark" in draft_html
    assert "draftmark" not in final_html
    assert "审核通过" in final_html


# ---------------------------------------------------------------------------
# 7. 转义：任何字段都不许原样输出脚本
# ---------------------------------------------------------------------------
def test_script_in_doc_field_is_escaped(app):
    doc = json.loads(json.dumps(FIXTURE, ensure_ascii=False))
    doc["meta"]["student_name"] = "<script>alert(1)</script>"
    doc["dims"]["R1"]["core_finding"]["text"] = "<script>alert(2)</script>"
    html = _render(app, doc=doc)

    assert "<script>alert(1)</script>" not in html
    assert "<script>alert(2)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html


# ---------------------------------------------------------------------------
# 静态资源经 m1_asset 可达
# ---------------------------------------------------------------------------
def test_print_assets_served_through_m1_asset():
    from blueprints import m1 as m1_bp

    asset_app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    asset_app.secret_key = "test-secret"
    asset_app.register_blueprint(m1_bp.bp)
    client = asset_app.test_client()

    css = client.get("/m1/assets/report_print.css")
    assert css.status_code == 200
    assert "text/css" in css.content_type
    crest = client.get("/m1/assets/report_crest.png")
    assert crest.status_code == 200
    assert "image/png" in crest.content_type
