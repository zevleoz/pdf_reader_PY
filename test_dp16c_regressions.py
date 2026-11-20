"""DP16 B-c browser coverage for selected-session export permissions."""
import re
import threading

import pytest
from sqlalchemy.orm import Session
from werkzeug.serving import make_server

import m1.plan_collaboration as collab
import m1.plan_store as pstore
from db import User
from test_dp16_session_pdf import _admin, _make_plan, _rich_doc
from test_m1_store import m1db  # noqa: F401
from test_m1dp_api import plan_client  # noqa: F401
from test_m1dp_store import _goal


@pytest.fixture()
def chrome_plan(plan_client):
    playwright = pytest.importorskip("playwright.sync_api")
    app = plan_client.application
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def open_plan(browser, plan, user_id, scope):
        cookie = app.session_interface.get_signing_serializer(app).dumps({
            "user_id": user_id, "role": "advisor", "advisor_name": "Bob",
            "m1_access": 1, "student_scope": scope, "detail_level": "full",
        })
        context = browser.new_context()
        context.add_cookies([{"name": "session", "value": cookie, "url": base}])
        # Confirm the print page invokes Chrome's print action without opening a native dialog.
        context.add_init_script("window.print = () => { window.didPrint = true; };")
        page = context.new_page()
        page.clock.install()
        url = f"{base}/m1/plans/{plan['id']}"
        with page.expect_response(lambda response: response.url == url.replace(
                "/m1/plans/", "/api/m1/plans/") + "/presence"
                and response.request.method == "GET") as poll:
            page.goto(url + "#step=internal", wait_until="load")
        poll.value.finished()
        return page

    try:
        with playwright.sync_playwright() as p:
            with p.chromium.launch(channel="chrome", headless=True) as browser:
                yield lambda plan, user_id, scope: open_plan(browser, plan, user_id, scope)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _set_read_scope(db, user_id):
    with Session(db.engine) as sess:
        user = sess.get(User, user_id)
        user.student_scope = "all"
        user.detail_level = "full"
        user.m1_access = 1
        sess.commit()


def _edit_requests(page):
    writes = []
    page.on("request", lambda req: writes.append(req.url)
            if req.method != "GET" and "/api/m1/plans/" in req.url
            and not req.url.endswith("/presence") else None)
    return writes


def _open_session_preview(page):
    with page.expect_popup(timeout=6000) as opened:
        page.get_by_role("button", name="导出 Session 1 PDF").click()
    popup = opened.value
    popup.wait_for_url(re.compile(r"/sessions/1/print\?"))
    popup.wait_for_function("window.didPrint === true")
    assert popup.get_by_text("S1-A1-STEP", exact=True).is_visible()
    assert popup.get_by_text("S2-A1-STEP", exact=True).count() == 0
    return popup


@pytest.mark.parametrize("source_mode", ["report", "mentor_inputs"])
def test_authorized_read_only_button_opens_saved_snapshot(chrome_plan, plan_client, m1db,
                                                          source_mode):
    plan, _ = _make_plan(m1db, client=plan_client, source_mode=source_mode, doc=_rich_doc())
    _set_read_scope(m1db, m1db.bob_id)
    page = chrome_plan(plan, m1db.bob_id, "all")
    page.get_by_text("当前为只读状态，不能编辑这个计划。", exact=True).wait_for(state="visible")
    assert page.locator("#m1Plan [contenteditable=true], #doc [data-path]:enabled"
                        ":is(input,select,textarea)").count() == 0
    if source_mode == "mentor_inputs":
        page.wait_for_function("window.M1DirectInputs.getActive() !== null")
        assert page.locator("#m1DirectInputs textarea:enabled").count() == 0
        page.evaluate("""() => {
            window.M1DirectInputs.getActive().flush = () => {
                throw new Error('Reader attempted to flush direct input');
            };
        }""")

    # A long-lived reader can print the current saved version after an editor's update.
    pstore.save_goals(plan["id"], plan["rev"], [_goal(text="LATEST-SAVED-GOAL")])
    writes = _edit_requests(page)
    popup = _open_session_preview(page)
    assert popup.get_by_text("LATEST-SAVED-GOAL", exact=True).is_visible()
    assert popup.url.endswith("?print=1")
    assert writes == []


@pytest.mark.parametrize("retain_view", [True, False])
def test_export_after_co_mentor_removal(chrome_plan, m1db, retain_view):
    plan, _ = _make_plan(m1db, doc=_rich_doc(), goals=[_goal(text="SAVED-GOAL")])
    actor = _admin(m1db)
    collab.add_team_member(m1db.student_id, m1db.bob_id, actor)
    if retain_view:
        _set_read_scope(m1db, m1db.bob_id)
    page = chrome_plan(plan, m1db.bob_id, "all" if retain_view else "assigned")
    assert page.locator("#doc [contenteditable=true]").count() > 0
    page.locator('[data-step="inputs"]').click()
    draft = page.locator('[data-goal-text="R2.2"]')
    page.clock.pause_at(page.evaluate("Date.now()") + 100)
    draft.fill("LOCAL-GOAL-DRAFT")
    page.locator('[data-step="internal"]').click()

    collab.remove_team_member(m1db.student_id, m1db.bob_id, actor)
    api_presence = f"/api/m1/plans/{plan['id']}/presence"
    with page.expect_response(lambda response: response.url.endswith(api_presence)
                              and response.request.method == "GET") as poll:
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    if retain_view:
        assert poll.value.json()["permissions"]["can_view"] is True
        assert poll.value.json()["permissions"]["can_edit"] is False
    else:
        assert poll.value.status == 404
    page.locator("#collabOffline:not([hidden])").wait_for(state="visible")
    assert page.locator("#doc [contenteditable=true]").count() == 0
    writes = _edit_requests(page)

    if retain_view:
        popup = _open_session_preview(page)
        assert popup.get_by_text("SAVED-GOAL", exact=True).is_visible()
        assert "LOCAL-GOAL-DRAFT" not in popup.content()
        popup.close()
        page.evaluate("window.open = () => null")
        page.get_by_role("button", name="导出 Session 1 PDF").click()
        page.get_by_text("请允许打开打印预览弹窗，本页未保存的文字仍保留").wait_for()
    else:
        page.get_by_role("button", name="导出 Session 1 PDF").click()
        page.get_by_text("你没有这个计划的访问权限", exact=True).wait_for()
        assert len(page.context.pages) == 1

    page.clock.run_for(750)
    assert draft.text_content() == "LOCAL-GOAL-DRAFT"
    assert writes == []


@pytest.mark.parametrize("approved", [False, True])
def test_co_mentor_can_export_review_and_approved_plans(chrome_plan, m1db, approved):
    plan, version = _make_plan(m1db, doc=_rich_doc(), approve=approved)
    collab.add_team_member(m1db.student_id, m1db.bob_id, _admin(m1db))
    page = chrome_plan(plan, m1db.bob_id, "assigned")
    assert page.locator("#approveBtn").count() == 0
    writes = _edit_requests(page)
    popup = _open_session_preview(page)
    assert popup.url.endswith(f"?expected_rev={plan['rev']}&version_id={version['id']}&print=1")
    assert popup.get_by_text("草稿", exact=True).count() == (0 if approved else 1)
    assert writes == []
