# -*- coding: utf-8 -*-
"""B3 验收：三份输入报告的 Y4 v2 渲染、新版 B3 数值、旧版 B3 路径、编辑后重生成。

不调用视觉 API：快照按 fake_data 手工拼装，渲染方式与 test_render_v2_slots.py 一致。
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "new_iteration"))

import b3_gauge  # noqa: E402
import extract  # noqa: E402
import fake_data  # noqa: E402
import render_v2  # noqa: E402

import app_utils  # noqa: E402
import db as _db  # noqa: E402
from blueprints import reports as reports_api  # noqa: E402

# 与 test_render_v2_slots.py 相同：每个槽位独占的内容页
SLOT_PAGES = {"A2": {"情绪稳定性", "依恋关系", "人格", "体质健康"},
              "B3": {"执行功能", "学习动机与策略"},
              "B4": {"自我概念", "内驱力", "认知资源", "认知能力 · 六项子指标"},
              "B6": {"职业兴趣", "能力优势", "职业价值观"}}

PAGE_START_RE = re.compile(r'<div class="page[ "]')


def _code(n):
    return f"{n:03d}"


def _codes(slot):
    """某一槽位的全部编号（与 render_v2.code_slot 同一口径）。"""
    return [c for c in (_code(n) for n in range(1, 134))
            if render_v2.code_slot(c) == slot]


def _item(code, label, value):
    return {"code": code, "label": label, "value": value,
            "type": "number" if isinstance(value, (int, float)) else "string"}


def _snapshot(values=None, blank=()):
    """report_data.json 风格的快照：fake_data 全量数据，按需置空/覆盖。"""
    items = {}
    for section in fake_data.build_fake_report()["sections"]:
        for group in section["groups"]:
            for it in group["items"]:
                items[it["code"]] = _item(it["code"], it["label"], it["value"])
    for c in blank:
        items.setdefault(c, _item(c, "", ""))["value"] = ""
    for c, v in (values or {}).items():
        items.setdefault(c, _item(c, "", ""))["value"] = v
    return {"student": {"name": "测试同学", "grade": "高一"},
            "schema_124": list(items.values())}


def _render(raw):
    d = {it["code"]: it["value"] for it in raw["schema_124"]}
    slots = render_v2.present_slots(raw, d)
    env = Environment(loader=FileSystemLoader(str(BASE_DIR / "new_iteration")),
                      autoescape=select_autoescape(default=True,
                                                   default_for_string=True))
    ctx = render_v2.build_context(raw["student"], d, slots)
    return env.get_template(render_v2.TEMPLATE_NAME).render(**ctx), slots


def _pages(html):
    starts = [m.start() for m in PAGE_START_RE.finditer(html)]
    return [html[s:e] for s, e in zip(starts, starts[1:] + [len(html)])]


def _page(html, title):
    for page in _pages(html):
        if f">{title}<" in page:
            return page
    raise AssertionError(f"没有找到「{title}」页")


def _lm_row(page, zh):
    for chunk in page.split('<div class="lm-row">')[1:]:
        if f'<div class="zh">{zh}' in chunk:
            return chunk.split('<div class="txt">')[0]
    raise AssertionError(f"学习动机与策略页没有「{zh}」行")


class TestThreeReports:
    def test_no_b6(self):
        raw = _snapshot(blank=_codes("B6"))
        html, slots = _render(raw)
        assert slots == {"A2", "B3", "B4"}

        for slot in ("A2", "B3", "B4"):
            for title in SLOT_PAGES[slot]:
                assert f">{title}<" in html, f"{slot} 页缺失：{title}"
        for title in SLOT_PAGES["B6"]:
            assert f">{title}<" not in html, f"不该出现 B6 页：{title}"
        assert "divider dv-sheng" not in html

    def test_no_a2(self):
        raw = _snapshot(blank=_codes("A2") + _codes("B6"))
        html, slots = _render(raw)
        assert slots == {"B3", "B4"}

        for slot in ("B3", "B4"):
            for title in SLOT_PAGES[slot]:
                assert f">{title}<" in html, f"{slot} 页缺失：{title}"
        for title in SLOT_PAGES["A2"]:
            assert f">{title}<" not in html, f"不该出现 A2 页：{title}"
        assert "divider dv-sheng" not in html
        assert "divider dv-jing" not in html

    def test_no_b4(self):
        raw = _snapshot(blank=_codes("B4") + _codes("B6"))
        html, slots = _render(raw)
        assert slots == {"A2", "B3"}

        for slot in ("A2", "B3"):
            for title in SLOT_PAGES[slot]:
                assert f">{title}<" in html, f"{slot} 页缺失：{title}"
        for title in SLOT_PAGES["B4"]:
            assert f">{title}<" not in html, f"不该出现 B4 页：{title}"
        assert "divider dv-sheng" not in html

    def test_new_b3_rows_have_their_own_labels(self):
        # 新版 B3（owner 2026-11-07）：两个新分项存 134/135，用自己的名称，都放在
        # 「学习方法与策略」下；新版没有的 068/071/130/133 为空，页面上不再出现。
        raw = _snapshot(values={"068": "", "071": "", "130": "", "133": "",
                                "134": "8.1", "135": "7.1",
                                "128": "7.4", "129": "4.7",
                                "131": "7.8", "132": "4.7"},
                        blank=_codes("B6"))
        html, slots = _render(raw)
        assert slots == {"A2", "B3", "B4"}

        page = _page(html, "学习动机与策略")
        assert "自我效能感" not in page and "学习自我调节" not in page
        practice = _lm_row(page, "学习方法实践与提升")
        execution = _lm_row(page, "学习策略执行与优化")
        assert "8.1" in practice and "同龄 -" in practice
        assert "7.1" in execution and "同龄 -" in execution
        methods_at = page.index(">学习方法与策略<")
        assert page.index("学习方法实践与提升") > methods_at
        assert page.index("学习策略执行与优化") > methods_at
        assert page.count('<div class="lm-row">') == 6

        # D2：均值为空时不画平均线；有均值的行照常画
        assert "avg-tick" not in practice and "avg-tick" not in execution
        assert 'class="avg-tick" style="left:74.0%"' in _lm_row(page, "深层动机")

    def test_old_b3_layout_unchanged(self):
        raw = _snapshot(values={"068": "6.2", "071": "5.5", "130": "8.1", "133": "6.3",
                                "134": "", "135": ""},
                        blank=_codes("B6"))
        html, _slots = _render(raw)
        page = _page(html, "学习动机与策略")
        assert "6.2" in _lm_row(page, "自我效能感")
        assert "5.5" in _lm_row(page, "学习自我调节")
        assert "学习方法实践与提升" not in page and "学习策略执行与优化" not in page

OLD_B3_FILES = sorted((Path.home() / "Downloads").glob("B3 核心学习能力_*.pdf"))
NEW_B3_SAMPLE = os.environ.get("B3_NEW_SAMPLE", "").strip()


@pytest.mark.skipif(not OLD_B3_FILES,
                    reason="~/Downloads 没有旧版 B3 样本（含学生数据，不入库）")
def test_old_b3_stays_on_old_path():
    for pdf in OLD_B3_FILES:
        assert b3_gauge.is_new_b3(pdf) is False, pdf.name
    old = extract._build_slot_prompt("B3")
    assert "068 学习动机-自我效能感 number（B3）" in old
    assert '134 学习方法与策略-学习方法实践与提升 number（B3，仅新版报告有此页；没有则输出 ""）' in old


@pytest.mark.skipif(not NEW_B3_SAMPLE, reason="未设置 B3_NEW_SAMPLE")
def test_new_b3_sample_is_detected_as_new():
    assert b3_gauge.is_new_b3(Path(NEW_B3_SAMPLE)) is True


@pytest.fixture()
def report_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'b3_three.db'}")

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    _db.Base.metadata.create_all(
        engine, tables=[_db.Student.__table__, _db.Report.__table__])
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)

    with Session(engine) as sess:
        student = _db.Student(student_code="Y4-B303", name="林同学",
                              grade="10", advisor_name="Alice")
        sess.add(student)
        sess.commit()
        report = _db.Report(
            student_id=student.id,
            report_date=date(2026, 11, 7),
            pdf_path="report.pdf",
            data_json=json.dumps(_snapshot(), ensure_ascii=False),
        )
        sess.add(report)
        sess.commit()
        report_id = report.id

    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-secret", TESTING=True)
    app.register_blueprint(reports_api.bp)
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["advisor_name"] = "Alice"
            sess["display_name"] = "测试管理员"
            sess["detail_level"] = "full"
        yield c, report_id, tmp_path

    engine.dispose()


@pytest.mark.skipif(
    not (Path(__file__).resolve().parent / "new_iteration" / "branding").is_dir(),
    reason="new_iteration/branding is git-ignored; copy it in to run this check")
def test_edited_value_reaches_the_pdf(report_client, monkeypatch):
    client, report_id, root = report_client

    saved = client.post(f"/api/reports/{report_id}/values",
                        json={"edits": {"066": "9.9"}})
    assert saved.status_code == 200
    assert saved.get_json()["changed"] == ["066"]

    data_dir = root / "data"
    out_dir = root / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (out_dir / "凭远Y4评测报告_测试同学.pdf").write_bytes(b"%PDF-1.4")
    (out_dir / "凭远Y4评测报告_v2_测试同学.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(reports_api, "DATA_DIR", data_dir)
    monkeypatch.setattr(reports_api, "OUTPUT_DIR", out_dir)
    monkeypatch.setattr(reports_api, "_job_running", lambda: False)
    monkeypatch.setattr(reports_api, "apply_report_data", lambda: {})

    def _render_v2_only():
        render_v2.render_html_to(data_dir / "report_data.json",
                                 out_dir / "regenerated.html")

    monkeypatch.setattr(reports_api._generate_module, "main", _render_v2_only)

    regen = client.post(f"/api/reports/{report_id}/regenerate")
    assert regen.status_code == 200, regen.get_data(as_text=True)

    html = (out_dir / "regenerated.html").read_text(encoding="utf-8")
    row = _lm_row(_page(html, "学习动机与策略"), "深层动机")
    assert "9.9" in row
