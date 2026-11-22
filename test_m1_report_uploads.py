"""Flash B：会后报告上传控件的键盘可达性。

页面与 API 跑在临时库上；不调用真实模型，不读写真实学生数据。
"""
from __future__ import annotations

import re

from app_utils import BASE_DIR
from m1 import report_store
from test_m1_report_revision_browser import chrome_report  # noqa: F401
from test_m1_report_screen import _login, _seed_report, client, m1db  # noqa: F401

REPORT_JS = BASE_DIR / "static" / "m1" / "report_workspace.js"


def _tag(html: str, element_id: str) -> str:
    match = re.search(r'<[^>]*id="%s"[^>]*>' % element_id, html)
    assert match, element_id
    return match.group(0)


def test_upload_controls_are_named_buttons(client, m1db):  # noqa: F811
    _login(client, m1db.admin_id, "admin")
    prep = m1db.prep()
    response = client.get(f"/m1/preps/{prep['id']}/report")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    sources = html.split('id="r4StepSources"', 1)[1].split('id="r4StepReview"', 1)[0]

    transcript = _tag(sources, "r4TranscriptPick")
    assert transcript.startswith('<button type="button"')
    assert 'aria-describedby="r4TranscriptFormats r4TranscriptError"' in transcript
    assert 'id="r4TranscriptFormats"' in sources
    assert "暂不支持音频，请先转成文字。" in sources
    error = _tag(sources, "r4TranscriptError")
    assert 'role="alert"' in error and "hidden" in error
    # 保留现有可接受类型。
    assert 'accept=".txt,.md,.docx,.pdf"' in _tag(sources, "r4TranscriptFile")

    other = _tag(sources, "r4OtherPick")
    assert other.startswith('<button type="button"')
    assert 'aria-describedby="r4OtherFormats r4OtherError"' in other
    assert 'id="r4OtherFormats"' in sources
    assert 'role="alert"' in _tag(sources, "r4OtherError")
    assert ('accept=".txt,.md,.docx,.pdf,.csv,.xlsx,.png,.jpg,.jpeg"'
            in _tag(sources, "r4OtherFile"))


def test_upload_bindings_keep_drop_and_inline_error_hooks():
    js = REPORT_JS.read_text(encoding="utf-8")
    for needle in (
        "refs.transcriptPick.addEventListener('click'",
        "refs.otherPick.addEventListener('click'",
        "refs.transcriptFile.addEventListener('cancel'",
        "refs.otherFile.addEventListener('cancel'",
        "showUploadError('transcript'",
        "showUploadError('other'",
        "focusUploadControl('transcript')",
        "focusUploadControl('other')",
        "refs.transcriptDrop.addEventListener('drop'",
        "refs.otherDrop.addEventListener('drop'",
        "toast('逐字稿已上传')",
        "toast('已上传')",
    ):
        assert needle in js, needle


def _choose_by_keyboard(page, selector, path):
    page.locator(selector).focus()
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Enter")
    chooser.value.set_files(str(path))


def test_keyboard_cancel_retry_replace_pointer_and_drop(chrome_report, client, m1db,  # noqa: F811
                                                         tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text("导师：你好\n学生：你好", encoding="utf-8")
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("导师：新的逐字稿", encoding="utf-8")
    other = tmp_path / "note.txt"
    other.write_text("补充资料", encoding="utf-8")

    prep = _seed_report(m1db)
    page = chrome_report(prep["id"], m1db.admin_id, preview=False)
    page.locator('#r4StepNav [data-step="sources"]').click()
    page.locator("#r4TranscriptPick").wait_for()

    # 取消文件对话框后，焦点回到对应的选择控件。
    page.locator("#r4TranscriptPick").focus()
    with page.expect_file_chooser() as chooser:
        page.keyboard.press("Enter")
    chooser.value.set_files([])
    page.wait_for_timeout(200)
    assert page.evaluate("document.activeElement.id") == "r4TranscriptPick"

    # 失败上传：错误显示在控件旁，焦点回到控件。
    _choose_by_keyboard(page, "#r4TranscriptPick", empty)
    error = page.locator("#r4TranscriptError")
    error.wait_for(state="visible")
    assert "文件不能为空" in error.inner_text()
    assert page.evaluate("document.activeElement.id") == "r4TranscriptPick"

    # 重试成功后保留成功播报。
    _choose_by_keyboard(page, "#r4TranscriptPick", transcript)
    page.locator("#r4TranscriptLine").wait_for(state="visible")
    page.get_by_text("逐字稿已上传", exact=True).wait_for()
    assert error.is_hidden()

    # 指针点击上传其他资料。
    with page.expect_file_chooser() as chooser:
        page.locator("#r4OtherPick").click()
    chooser.value.set_files(str(other))
    page.locator("#r4Others").get_by_text("note", exact=True).wait_for()
    page.get_by_text("已上传", exact=True).wait_for()

    # 替换现有逐字稿：先取消，确认原文件不变且焦点回到替换按钮。
    page.evaluate("window.confirm = () => false")
    _choose_by_keyboard(page, "#r4TranscriptReplace", replacement)
    page.wait_for_timeout(200)
    assert page.locator("#r4TranscriptName").inner_text() == "transcript.txt"
    assert page.evaluate("document.activeElement.id") == "r4TranscriptReplace"

    # 再次确认替换，文件名更新。
    page.evaluate("window.confirm = () => true")
    _choose_by_keyboard(page, "#r4TranscriptReplace", replacement)
    page.wait_for_function(
        "document.getElementById('r4TranscriptName').textContent.includes('replacement.txt')"
    )

    # 拖放上传一次，拖动状态正确收起。
    page.evaluate(
        """() => {
          const zone = document.getElementById('r4OtherDrop');
          const data = new DataTransfer();
          data.items.add(new File(['拖入资料'], 'dragged.txt', {type: 'text/plain'}));
          zone.dispatchEvent(new DragEvent('dragenter', {bubbles: true, cancelable: true, dataTransfer: data}));
          zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: data}));
        }"""
    )
    page.locator("#r4Others").get_by_text("dragged", exact=True).wait_for()
    assert "over" not in page.locator("#r4OtherDrop").get_attribute("class")


def _open_sources(chrome_report, m1db):
    prep = _seed_report(m1db)
    page = chrome_report(prep["id"], m1db.admin_id, preview=False)
    page.locator('#r4StepNav [data-step="sources"]').click()
    page.locator("#r4TranscriptPick").wait_for()
    return prep, page


def test_pending_transcript_does_not_display_an_earlier_cover_error(chrome_report, m1db, tmp_path):
    from playwright.sync_api import expect

    transcript = tmp_path / "queued.txt"
    transcript.write_text("导师：你好\n学生：你好", encoding="utf-8")
    _, page = _open_sources(chrome_report, m1db)
    document_route = "**/report/doc"
    held = []
    page.route(document_route, lambda route: held.append(route))
    page.locator("#r4Cover summary").click()
    page.locator('[data-meta="grade"]').fill("九年级")
    with page.expect_request(lambda request: request.url.endswith("/report/doc")):
        page.locator("#r4TranscriptPick").focus()
    _choose_by_keyboard(page, "#r4TranscriptPick", transcript)
    expect(page.locator("#r4TranscriptPick")).to_be_disabled()

    held[0].fulfill(status=503, json={"ok": False, "error": "封面暂时无法保存"})
    expect(page.locator("#r4SourceRetry")).to_be_visible()
    expect(page.locator("#r4TranscriptError")).to_be_hidden()
    expect(page.locator("#r4TranscriptPick")).to_be_disabled()
    page.unroute(document_route)
    page.locator("#r4SourceRetry").click()
    expect(page.locator("#r4TranscriptName")).to_have_text("queued.txt")


def test_transcript_retry_reconciles_a_committed_upload(
    chrome_report, client, m1db, monkeypatch, tmp_path,
):
    from playwright.sync_api import expect

    transcript = tmp_path / "uploaded.txt"
    transcript.write_text("导师：你好\n学生：你好", encoding="utf-8")
    app = client.application
    endpoint = next(name for name in app.view_functions if name.endswith(".api_report_transcript"))
    upload = app.view_functions[endpoint]
    writes = []

    def lose_response(**kwargs):
        response = app.make_response(upload(**kwargs))
        writes.append(response.status_code)
        return {"ok": False, "error": "尚未确认上传结果"}, 503

    monkeypatch.setitem(app.view_functions, endpoint, lose_response)
    prep, page = _open_sources(chrome_report, m1db)
    _choose_by_keyboard(page, "#r4TranscriptPick", transcript)
    expect(page.locator("#r4TranscriptError")).to_have_text("尚未确认上传结果")
    assert writes == [200]
    expect(page.locator("#r4TranscriptPick")).to_be_disabled()
    expect(page.locator("#r4SourceRetry")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#r4TranscriptName")).to_have_text("uploaded.txt")
    expect(page.locator("#r4TranscriptError")).to_be_hidden()
    assert writes == [200]
    assert report_store.get_report(prep["id"])["transcript_filename"] == "uploaded.txt"


def test_supplementary_upload_shows_saved_file_without_a_followup_fetch(
    chrome_report, m1db, tmp_path,
):
    from playwright.sync_api import expect

    note = tmp_path / "confirmed.txt"
    note.write_text("补充资料", encoding="utf-8")
    prep, page = _open_sources(chrome_report, m1db)
    page.set_viewport_size({"width": 375, "height": 812})
    page.route(f"**/api/m1/preps/{prep['id']}/report",
               lambda route: route.fulfill(status=503, json={"ok": False, "error": "列表暂时无法刷新"}))
    _choose_by_keyboard(page, "#r4OtherPick", note)
    expect(page.locator("#r4Others").get_by_text("confirmed", exact=True)).to_be_visible(timeout=5000)
    expect(page.locator("#r4OtherError")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
