"""M1P-P7：平台名从 M1 改为 心有灵析。

只改用户看得到的文字；证据来源代码 ``"M1"``、URL、文件名、Python 名称保持原样。
"""
from __future__ import annotations

import re

import pytest
from flask import Flask, session

import app_utils
from app_utils import BASE_DIR
from test_m1_api import login_as
from test_login_platforms import _client, app, world  # noqa: F401  真实入口 + 临时库
from test_m1_report_core import fake, generate, rdb  # noqa: F401  虚构模型 + 生成夹具
from test_m1_store import m1db  # noqa: F401  临时库 + 学生/用户/Y4 数据

ASSETS = BASE_DIR / "static" / "app" / "assets"


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


def visible_text(html: str) -> str:
    """去掉脚本、样式和标签，只留用户实际读到的文字。"""
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    return re.sub(r"(?s)<[^>]+>", " ", html)


# ---------------------------------------------------------------------------
# 1. 四个 M1 页面都显示新名字，可见文字里没有旧名字
# ---------------------------------------------------------------------------
def test_m1_pages_show_the_new_name(client, m1db):
    login_as(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()
    for url in ("/m1",
                "/m1/preps/%d" % prep["id"],
                "/m1/preps/%d/prep" % prep["id"],
                "/m1/preps/%d/report" % prep["id"]):
        resp = client.get(url)
        assert resp.status_code == 200, url
        html = resp.get_data(as_text=True)
        assert "心有灵析" in html, url
        assert "M1" not in visible_text(html), url


# ---------------------------------------------------------------------------
# 2. 平台卡片与「其他平台」导航都用新名字
# ---------------------------------------------------------------------------
def test_platform_card_and_nav_link_use_the_new_name(monkeypatch):
    from blueprints import auth

    monkeypatch.setattr(app_utils, "can_use_m1", lambda: True)
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context():
        session["role"] = "admin"
        card = next(c for c in auth._platform_cards() if c["key"] == "m1")
        assert card["title"] == "心有灵析"
        link = next(it for it in app_utils._other_platform_links() if it["key"] == "m1")
        assert link["label"] == "心有灵析"


# ---------------------------------------------------------------------------
# 3. 会前准备文档里的固定称呼
# ---------------------------------------------------------------------------
def test_prep_document_labels_use_the_new_name():
    js = (BASE_DIR / "static" / "m1" / "m1_doc.js").read_text(encoding="utf-8")
    assert "心有灵析 Mentor" in js
    assert "心有灵析 FM会前准备" in js
    assert not re.search(r"""['"]M1 """, js)


# ---------------------------------------------------------------------------
# 4. 证据来源标签改名，但证据条目的 source 代码仍是 "M1"
# ---------------------------------------------------------------------------
def test_report_source_label_renamed_but_evidence_code_kept(rdb, fake):  # noqa: F811
    _report, version = generate(rdb)
    assert "心有灵析 First Meeting 逐字稿" in version["manifest"]["sources"]
    assert "M1 First Meeting 逐字稿" not in version["manifest"]["sources"]
    assert any(item.get("source") == "M1" for item in version["evidence"])


# ---------------------------------------------------------------------------
# 5. React 产物已重建
# ---------------------------------------------------------------------------
def test_built_react_app_uses_the_new_name():
    js = "".join(p.read_text(encoding="utf-8")
                 for p in sorted(ASSETS.glob("index-*.js")))
    assert "打开心有灵析" in js
    assert "打开 M1" not in js


# ---------------------------------------------------------------------------
# 6. 发给模型的提示词里没有旧名字
# ---------------------------------------------------------------------------
def _prompt_strings(module) -> dict:
    return {name: value for name, value in vars(module).items()
            if name.endswith("_PROMPT") and isinstance(value, str)}


def test_prompts_sent_to_the_model_use_the_new_name():
    from m1 import report_prompts, speakers
    from m1 import prompts as prep_prompts

    texts = {
        "SOURCE_ITEMS_PROMPT": prep_prompts.SOURCE_ITEMS_PROMPT,
        "SOURCE_SUMMARY_PROMPT": prep_prompts.SOURCE_SUMMARY_PROMPT,
        "MEETING_PLAN_PROMPT": prep_prompts.MEETING_PLAN_PROMPT,
    }
    texts.update({"report_prompts." + k: v for k, v in _prompt_strings(report_prompts).items()})
    texts.update({"speakers." + k: v for k, v in _prompt_strings(speakers).items()})
    assert "M1" not in "".join(texts.values()), [
        name for name, text in texts.items() if "M1" in text]


# ---------------------------------------------------------------------------
# 7. 选择平台卡片的图案不再写旧名字
# ---------------------------------------------------------------------------
def test_platform_card_artwork_has_no_old_name(app, world):  # noqa: F811
    html = _client(app, world.admin_id, "admin").get("/platforms").get_data(as_text=True)
    assert ">M1<" not in html
    assert ">心有<" in html and ">灵析<" in html
