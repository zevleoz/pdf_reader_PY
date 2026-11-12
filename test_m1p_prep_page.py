"""M1P-P3：会前准备页按原型重排为两步。

用例对应 M1P-P3-prep-page.md 第 6 节；夹具复用 test_m1p_api / test_m1_store。
"""
from __future__ import annotations

import m1.store as store
from test_m1_pipeline import _login
from test_m1p_api import client  # noqa: F401  应用与登录
from test_m1_store import _doc, m1db  # noqa: F401  临时库与文档构造


def test_prep_page_uses_the_two_step_shell(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()
    html = client.get("/m1/preps/%d/prep" % prep["id"]).get_data(as_text=True)

    assert 'data-platform="m1"' in html
    assert 'class="track k2"' in html
    assert 'data-step="sources"' in html
    assert 'data-step="review"' in html
    assert 'id="genBox"' in html
    assert 'id="genGo"' in html
    assert 'id="factCard"' in html
    assert 'id="warnFold"' in html
    assert 'id="finConfirm"' in html
    assert "只用于会前准备" in html

    assert "m1-parts" not in html
    assert "admin_v2.css" not in html
    assert 'id="stepGen"' not in html


def test_review_panel_order_matches_the_reference(client, m1db):
    _login(client, m1db.alice_id, "advisor", "Alice")
    prep = m1db.prep()
    html = client.get("/m1/preps/%d/prep" % prep["id"]).get_data(as_text=True)

    finalize = html.index('id="finalizeCard"')
    facts = html.index('id="factCard"')
    priority = html.index('id="priList"')
    question = html.index('id="myQ"')
    assert finalize < facts < priority < question


def test_js_lets_the_mentor_finalize_with_open_flags(client):
    js = client.get("/m1/assets/m1_workspace.js").get_data(as_text=True)

    assert "还有 " in js
    assert "处需要核对，可以先定稿" in js

    start = js.index("function renderFinalizeState")
    end = js.index("function ", start + len("function renderFinalizeState"))
    body = js[start:end]
    assert "facts" not in body
    assert "openFactFlags" not in body


def test_js_does_not_block_finalize_on_safety(client):
    js = client.get("/m1/assets/m1_workspace.js").get_data(as_text=True)

    assert "先处理顶部的安全提示，才能定稿。" not in js
    assert "条安全提示还没确认" in js


def test_js_follows_hash_steps(client):
    js = client.get("/m1/assets/m1_workspace.js").get_data(as_text=True)

    assert "hashchange" in js


def test_a_draft_with_an_open_flag_still_finalizes(client, m1db):
    prep = m1db.prep()
    doc = _doc()
    doc["fact_flags"] = [{"id": "ff1", "kind": "unsupported",
                          "sentence": "待核对：某一句。", "block_id": "b1",
                          "acked": False}]
    store.save_doc(prep["id"], store.get_prep(prep["id"])["rev"], doc)
    _login(client, m1db.alice_id, "advisor", "Alice")

    res = client.post("/api/m1/preps/%d/finalize" % prep["id"])
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["open_flags"] == 1
