"""Browser coverage for revision-bound report actions using synthetic reports."""
import threading

import pytest
from werkzeug.serving import make_server

import app_utils
from m1 import report_store
from test_m1_report_core import Q_BODY, fake, generate, rdb  # noqa: F401
from test_m1_report_screen import client  # noqa: F401
from test_m1_store import m1db  # noqa: F401


@pytest.fixture()
def chrome_report(client):
    playwright = pytest.importorskip("playwright.sync_api")
    app = client.application
    app.context_processor(lambda: {"csrf_token": app_utils.get_csrf_token})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    with playwright.sync_playwright() as p:
        try:
            with p.chromium.launch(channel="chrome", headless=True) as browser:
                def open_page(prep_id, user_id, role="admin", *, preview=True, **settings):
                    cookie = app.session_interface.get_signing_serializer(app).dumps({
                        "user_id": user_id, "role": role, **settings,
                    })
                    context = browser.new_context()
                    context.add_cookies([{"name": "session", "value": cookie, "url": base}])
                    context.add_init_script("window.print = () => { window.didPrint = true; };")
                    page = context.new_page()
                    page.on("dialog", lambda dialog: dialog.accept())
                    page.goto(f"{base}/m1/preps/{prep_id}/report")
                    if preview:
                        page.locator("#r4PreviewToggle").click()
                    return page

                yield open_page
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def edit_field(page):
    return page.frame_locator("#r4Preview").locator('[data-path=\'["portrait", "R1"]\']')


def assert_printed(popup, content, report):
    suffix = f"expected_rev={report['rev']}&version_id={report['current_version_id']}"
    popup.wait_for_url(f"**/report/print?print=1&{suffix}")
    popup.wait_for_function("window.didPrint === true")
    assert content in popup.content()


def test_section_review_resolves_required_issue_and_exports_at_phone_width(chrome_report, rdb, fake):
    from playwright.sync_api import expect

    generate(rdb)
    prep_id = rdb.prep_row["id"]
    report = report_store.get_report(prep_id)
    doc = report_store.current_version(report["id"])["doc"]
    doc["dims"]["R1"]["abilities"]["R1.1"]["meeting"]["text"] = ""
    report_store.save_version(report["id"], report["rev"], doc=doc)
    page = chrome_report(prep_id, rdb.admin_id, preview=False)
    page.set_viewport_size({"width": 320, "height": 760})

    expect(page.locator("#r4Content")).to_be_visible()
    expect(page.locator("#r4PreviewPane")).to_be_hidden()
    tabs = page.get_by_role("tablist", name="报告内容").get_by_role("tab")
    tabs.nth(0).focus()
    tabs.nth(0).press("ArrowRight")
    expect(tabs.nth(1)).to_be_focused()
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
    required = page.locator("#r4Checks").get_by_role("button", name="阻断 R1.1 首次会议核实情况 为空")
    required.focus()
    required.press("Enter")
    field = page.locator('[data-path=\'["dims","R1","abilities","R1.1","meeting"]\']')
    expect(field).to_be_focused()
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    page.set_viewport_size({"width": 375, "height": 812})
    evidence = field.locator("xpath=ancestor::section[contains(@class, 'r4-ab')]").locator("details.r4-ev")
    if not evidence.evaluate("(node) => node.open"):
        evidence.locator("summary").press("Enter")
    expect(evidence.get_by_text(Q_BODY, exact=True)).to_be_visible()
    expect(evidence.get_by_label("发言人").first).to_have_value("学生")
    text = "合成演练：学生能清楚描述情绪。"
    field.fill(text)
    with page.expect_popup() as opened:
        page.locator("#r4Print").click()
    assert_printed(opened.value, text, report_store.get_report(prep_id))
    expect(page.locator("#r4NeedCount")).to_have_text("0")
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")


def click_twice(button):
    button.evaluate("button => { button.click(); button.click(); }")


@pytest.mark.parametrize("action", ["export", "publish"])
def test_review_action_waits_for_delayed_iframe_write(chrome_report, rdb, fake, monkeypatch, action):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    original = report_store.get_report(prep_id)
    began = threading.Event()
    release = threading.Event()
    save_version = report_store.save_version

    def delay(*args, **kwargs):
        began.set()
        assert release.wait(12)
        return save_version(*args, **kwargs)

    monkeypatch.setattr(report_store, "save_version", delay)
    page = chrome_report(prep_id, rdb.admin_id)
    edited = "Synthetic delayed report revision"
    field = edit_field(page)
    published = []
    popups = []
    page.on("request", lambda req: published.append(req) if req.url.endswith("/report/publish") else None)
    page.on("popup", lambda popup: popups.append(popup))
    try:
        field.fill(edited, timeout=6000)
        field.evaluate("node => node.blur()")
        assert began.wait(8)
        if action == "export":
            with page.expect_popup() as opened:
                click_twice(page.locator("#r4Print"))
            popup = opened.value
            popup.get_by_text("正在保存并准备打印预览…").wait_for()
            assert popup.locator(".sheet").count() == 0
            assert report_store.get_report(prep_id)["rev"] == original["rev"]
            with page.expect_response(lambda res: res.url.endswith("/report/doc")) as saved:
                release.set()
            assert saved.value.status == 200
            report = report_store.get_report(prep_id)
            assert report["rev"] == original["rev"] + 1 and report["status"] == "reviewing"
            assert_printed(popup, edited, report)
            assert len(popups) == 1
        else:
            click_twice(page.locator("#r4Publish"))
            page.locator("#r4Publish:disabled").wait_for()
            assert published == []
            assert report_store.get_report(prep_id)["rev"] == original["rev"]
            with page.expect_response(lambda res: res.url.endswith("/report/publish")) as response:
                release.set()
            assert response.value.status == 200
            report = report_store.get_report(prep_id)
            assert report["rev"] == original["rev"] + 2 and report["status"] == "published"
            assert len(published) == 1
            page.frame_locator("#r4Preview").get_by_text(edited, exact=True).wait_for()
            assert page.frame_locator("#r4Preview").locator("[contenteditable]").count() == 0
            with page.expect_popup() as opened:
                page.locator("#r4Print").click()
            assert_printed(opened.value, edited, report)
    finally:
        release.set()


@pytest.mark.parametrize("action", ["export", "publish"])
@pytest.mark.parametrize("committed", [False, True])
def test_failed_save_stops_action_and_retry_reconciles(
        chrome_report, rdb, fake, action, committed):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    original = report_store.get_report(prep_id)
    page = chrome_report(prep_id, rdb.admin_id)
    attempted = []

    def fail_once(route):
        attempted.append(route.request.post_data_json)
        if len(attempted) == 1:
            if committed:
                assert route.fetch().status == 200
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/report/doc", fail_once)
    text = "Synthetic text after lost save response"
    field = edit_field(page)
    field.fill(text, timeout=6000)
    if action == "export":
        with page.expect_popup() as opened:
            page.locator("#r4Print").click()
        popup = opened.value
        if not popup.is_closed():
            popup.wait_for_event("close", timeout=6000)
    else:
        page.locator("#r4Publish").click()
    page.locator("#r4Retry").wait_for()
    assert field.inner_text() == text
    after_failure = report_store.get_report(prep_id)
    assert after_failure["status"] != "published"
    assert after_failure["rev"] == original["rev"] + int(committed)
    with page.expect_response(lambda response: "/report?write_id=" in response.url):
        page.locator("#r4Retry").click()
    page.locator("#r4Retry").wait_for(state="hidden")
    page.locator("#r4Saved").get_by_text("已保存", exact=True).wait_for()
    assert len(attempted) == (1 if committed else 2)
    assert attempted[0] == attempted[-1]
    report = report_store.get_report(prep_id)
    assert report["rev"] == original["rev"] + 1
    if action == "publish":
        with page.expect_response(lambda res: res.url.endswith("/report/publish")) as response:
            page.locator("#r4Publish").click()
        assert response.value.status == 200
        report = report_store.get_report(prep_id)
        assert report["status"] == "published" and report["rev"] == original["rev"] + 2
    with page.expect_popup() as opened:
        page.locator("#r4Print").click()
    assert_printed(opened.value, text, report)


@pytest.mark.parametrize("action", ["export", "publish"])
def test_review_action_rejects_a_second_tab_revision(chrome_report, rdb, fake, action):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    original = report_store.get_report(prep_id)
    page = chrome_report(prep_id, rdb.admin_id)
    edit_field(page).wait_for()
    second = chrome_report(prep_id, rdb.admin_id)
    text = "Synthetic edit from the second tab"
    edit_field(second).fill(text, timeout=6000)
    with second.expect_response(lambda res: res.url.endswith("/report/doc")) as saved:
        edit_field(second).evaluate("node => node.blur()")
    assert saved.value.status == 200
    current = report_store.get_report(prep_id)
    assert current["rev"] == original["rev"] + 1
    if action == "export":
        with page.expect_popup() as opened:
            page.locator("#r4Print").click()
        popup = opened.value
        popup.locator("#print-error").wait_for()
        assert popup.evaluate("window.didPrint") is None
        assert text not in popup.content()
    else:
        with page.expect_response(lambda res: res.url.endswith("/report/publish")) as response:
            page.locator("#r4Publish").click()
        assert response.value.status == 409
        assert response.value.request.post_data_json["expected_rev"] == original["rev"]
    assert report_store.get_report(prep_id)["rev"] == current["rev"]
    with second.expect_popup() as opened:
        second.locator("#r4Print").click()
    assert_printed(opened.value, text, current)


@pytest.mark.parametrize("embedded", [True, False])
def test_inline_export_flushes_focused_field(chrome_report, rdb, fake, embedded):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    before = report_store.get_report(prep_id)
    page = chrome_report(prep_id, rdb.admin_id)
    if embedded:
        editor = page.frame_locator("#r4Preview")
    else:
        page.goto(page.url.split("#", 1)[0] + "/print?edit=1")
        editor = page
    text = "Synthetic draft from inline export"
    field = editor.locator('[data-path=\'["portrait", "R1"]\']')
    field.fill(text, timeout=6000)
    assert field.evaluate("node => document.activeElement === node")
    with page.expect_popup(timeout=8000) as opened:
        editor.locator("#editExport").click()
    opened.value.wait_for_function("window.didPrint === true")
    after = report_store.get_report(prep_id)
    assert after["rev"] == before["rev"] + 1 and after["status"] == "reviewing"
    assert_printed(opened.value, text, after)


def test_validation_failure_can_be_corrected_in_place(chrome_report, rdb, fake):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    original = report_store.get_report(prep_id)
    page = chrome_report(prep_id, rdb.admin_id)
    attempts = []

    def reject_first_value(route):
        value = route.request.post_data_json["changes"][0]["value"]
        attempts.append(value)
        if value == "REJECTED":
            route.fulfill(status=400, json={"ok": False, "error": "测试：请修正文案"})
        else:
            route.continue_()

    page.route("**/report/doc", reject_first_value)
    field = edit_field(page)
    field.fill("REJECTED", timeout=6000)
    field.evaluate("node => node.blur()")
    page.locator("#r4Saved").get_by_text("测试：请修正文案", exact=True).wait_for()
    assert field.inner_text() == "REJECTED"
    text = "Synthetic corrected draft"
    field.fill(text)
    with page.expect_popup() as opened:
        page.locator("#r4Print").click()
    popup = opened.value
    popup.wait_for_function("window.didPrint === true")
    report = report_store.get_report(prep_id)
    assert report["rev"] == original["rev"] + 1
    assert attempts == ["REJECTED", text]
    assert_printed(popup, text, report)


def test_cover_save_and_focused_iframe_edit_share_one_revision_queue(
        chrome_report, rdb, fake, monkeypatch):
    generate(rdb)
    prep_id = rdb.prep_row["id"]
    original = report_store.get_report(prep_id)
    began = threading.Event()
    release = threading.Event()
    save_version = report_store.save_version

    def delay_cover(*args, **kwargs):
        if kwargs["doc"]["meta"]["school"] == "Synthetic revised school" and not began.is_set():
            began.set()
            assert release.wait(12)
        return save_version(*args, **kwargs)

    monkeypatch.setattr(report_store, "save_version", delay_cover)
    page = chrome_report(prep_id, rdb.admin_id)
    edit_field(page).wait_for()
    try:
        page.locator('#r4StepNav [data-step="sources"]').click()
        page.locator("#r4Cover summary").click()
        page.locator('#r4Cover [data-meta="school"]').fill("Synthetic revised school")
        page.locator('#r4StepNav [data-step="review"]').click()
        assert began.wait(8)
        text = "Synthetic iframe draft during cover save"
        edit_field(page).fill(text)
        with page.expect_popup() as opened:
            page.locator("#r4Print").click()
        popup = opened.value
        popup.get_by_text("正在保存并准备打印预览…").wait_for()
        release.set()
        popup.wait_for_function("window.didPrint === true")
        result = report_store.get_report(prep_id)
        assert result["rev"] == original["rev"] + 2
        assert_printed(popup, text, result)
        assert "Synthetic revised school" in popup.content()
        page.frame_locator("#r4Preview").get_by_text("Synthetic revised school", exact=True).wait_for()
        assert edit_field(page).inner_text() == text
    finally:
        release.set()
