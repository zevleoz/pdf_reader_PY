"""DP16-B-b：独立复现的三个回归点。

1. SQLite 读快照必须是真的 DBAPI 读事务，不能在并发就地更新时混合修订。
2. 导出屏障必须排空目标和资料输入的 700ms 防抖，而不只是已排队的 section。
3. 打印模板必须保留作者输入的多行段落，导出按钮要有可区分的无障碍名称。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import m1.plan_store as pstore
from test_dp16_session_pdf import (_make_plan, _rich_doc, ROOT,
                                   plan_client, m1db)  # noqa: F401
from test_m1_pipeline import _login
from test_m1dp_store import _goal

pytestmark = pytest.mark.usefixtures("m1db")


# ---------------------------------------------------------------------------
# 真实 SQLite 读事务
# ---------------------------------------------------------------------------
def _bump_plan_and_doc(sess, plan_id, version_id, title):
    """同一写入方事务里同时改 rev、当前内部文档和 document epoch。"""
    from m1.plan_collaboration import PlanCollabState
    from m1.plan_store import M1Plan, M1PlanVersion
    plan = sess.get(M1Plan, int(plan_id))
    plan.rev = int(plan.rev) + 1
    version = sess.get(M1PlanVersion, int(version_id))
    doc = json.loads(version.doc or "{}")
    doc["sessions"][0]["title"] = {"text": title, "src": "mentor"}
    version.doc = json.dumps(doc, ensure_ascii=False)
    state = sess.get(PlanCollabState, int(plan_id))
    if state is not None:
        state.document_version = int(state.document_version or 0) + 1


def test_snapshot_is_real_sqlite_read_transaction_in_wal(monkeypatch, m1db):
    """WAL：计划头读出后另一连接提交 rev+文档，本事务仍读到整份旧快照。"""
    pstore.ensure_tables(m1db.engine)
    plan, version = _make_plan(m1db, doc=_rich_doc())
    old_rev = int(plan["rev"])
    old_epoch = pstore.internal_print_snapshot(plan["id"])["document_version"]
    old_title = _rich_doc()["sessions"][0]["title"]["text"]

    with m1db.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()
        conn.commit()
    assert str(mode).lower() == "wal"

    state = {"injected": False, "dbapi_in_transaction": None}
    real_plan_row = pstore._plan_row

    def interleaved_plan_row(sess, row):
        result = real_plan_row(sess, row)
        if not state["injected"]:
            state["injected"] = True
            dbapi = sess.connection().connection.dbapi_connection
            state["dbapi_in_transaction"] = bool(dbapi.in_transaction)
            with Session(m1db.engine) as other:
                _bump_plan_and_doc(other, plan["id"], version["id"], "NEW-TITLE")
                other.commit()
        return result

    monkeypatch.setattr(pstore, "_plan_row", interleaved_plan_row)
    snapshot = pstore.internal_print_snapshot(plan["id"])

    assert state["injected"] is True
    assert state["dbapi_in_transaction"] is True, "SELECT 前必须已有真实读事务"
    assert snapshot["plan"]["rev"] == old_rev
    assert snapshot["document_version"] == old_epoch
    assert snapshot["internal"]["doc"]["sessions"][0]["title"]["text"] == old_title

    # 事务已释放；下一次读取看到完整的新修订，而不是旧-新混合。
    after = pstore.internal_print_snapshot(plan["id"])
    assert after["plan"]["rev"] == old_rev + 1
    assert after["internal"]["doc"]["sessions"][0]["title"]["text"] == "NEW-TITLE"
    assert after["document_version"] == old_epoch + 1


def test_snapshot_releases_rollback_journal_reader_without_deadlock(monkeypatch, m1db):
    """rollback-journal：写入线程等待读事务结束，读结果保持旧修订。"""
    pstore.ensure_tables(m1db.engine)
    plan, version = _make_plan(m1db, doc=_rich_doc())
    old_rev = int(plan["rev"])

    with m1db.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode=DELETE").scalar()
        conn.commit()
    assert str(mode).lower() == "delete"

    started = threading.Event()
    finished = threading.Event()
    errors = []
    path = m1db.engine.url.database
    writer_engine = create_engine(
        "sqlite:///%s" % path, connect_args={"check_same_thread": False})

    def writer():
        started.wait(5)
        try:
            with Session(writer_engine) as other:
                _bump_plan_and_doc(other, plan["id"], version["id"], "NEW-TITLE")
                other.commit()
            finished.set()
        except Exception as exc:  # pragma: no cover - assertion reports it
            errors.append(exc)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()

    real_plan_row = pstore._plan_row

    def interleaved_plan_row(sess, row):
        result = real_plan_row(sess, row)
        started.set()
        return result

    monkeypatch.setattr(pstore, "_plan_row", interleaved_plan_row)
    snapshot = pstore.internal_print_snapshot(plan["id"])
    thread.join(10)
    writer_engine.dispose()

    assert finished.is_set(), "读事务未释放，写入方被阻塞：%r" % (errors or "timeout")
    assert not errors, errors
    assert snapshot["plan"]["rev"] == old_rev
    assert snapshot["internal"]["doc"]["sessions"][0]["title"]["text"] == \
        _rich_doc()["sessions"][0]["title"]["text"]


# ---------------------------------------------------------------------------
# 真实客户端保存屏障（Node）
# ---------------------------------------------------------------------------
def _run_node(script: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                            cwd=str(ROOT), timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


_JS_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync('static/m1/plan.js', 'utf8');

function slice(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('missing ' + name);
  let i = src.indexOf('{', start);
  let depth = 0, quote = null, comment = null;
  for (; i < src.length; i += 1) {
    const ch = src[i], next = src[i + 1];
    if (comment === 'line') { if (ch === '\n') comment = null; continue; }
    if (comment === 'block') { if (ch === '*' && next === '/') { comment = null; i += 1; } continue; }
    if (quote) {
      if (ch === '\\') { i += 1; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '/' && next === '/') { comment = 'line'; i += 1; continue; }
    if (ch === '/' && next === '*') { comment = 'block'; i += 1; continue; }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    else if (ch === '}') { depth -= 1; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error('unterminated ' + name);
}

const names = [
  'clonePatch', 'isPlainObject', 'composePatch', 'ensurePending', 'rememberPath',
  'scheduleFlush', 'buildSectionPatch', 'stagePatch', 'stageField', 'updateSaveState',
  'sendPatch', 'acceptPatch', 'dropWrite', 'patchSection', 'isStaleError',
  'flushSection', 'hasUnresolved', 'flushAll', 'flushDebouncedEdits', 'flushSections',
  'settleWrites', 'handlePatchError', 'goalPayload', 'saveGoals', 'dropGoalWrite',
  'markGoalEdited', 'saveInputs', 'dropInputWrite', 'markInputsEdited',
  'sessionPrintUrl', 'sessionExportBlockedReason', 'runSessionExport'
];
const body = names.map(slice).join('\n');

function makeEngine(overrides) {
  const log = [];
  const toasts = [];
  let seq = 0;
  const S = {
    rev: 4, versionId: 9, status: 'review', offline: false, revoked: false,
    canEdit: true, step1: true, step2: false, goals: [], doc: {}, parentDoc: null,
    sections: {}, knownVersions: {}, observedDocVersion: 1, docVersion: 1,
    pending: {}, conflicts: {}, leases: {}, leasePromises: {}, locked: {}, writes: [],
    goalDirty: false, inputsDirty: false, goalEdit: 0, inputEdit: 0,
    goalWrites: [], inputWrites: [], parentBlocking: []
  };
  const CORE = {
    dependencyParent: function () { return null; },
    get: function () { return undefined; },
    internalPatch: function () { return null; },
    parentPatch: function () { return null; },
    internalSection: function () { return null; },
    parentSection: function () { return null; }
  };
  const request = function (method, url, payload) {
    log.push({type: 'request', method: method, url: url, body: payload});
    const custom = overrides && overrides.onRequest
      ? overrides.onRequest(method, url, payload, S) : null;
    if (custom) return custom;
    if (url.indexOf('/leases/acquire') >= 0) return Promise.resolve({token: 'lease'});
    if (url.indexOf('/leases/release') >= 0) return Promise.resolve({});
    if (url.indexOf('/sections/') >= 0) {
      const section = url.split('/sections/')[1].split('?')[0];
      return Promise.resolve({
        section_version: (S.sections[section] || 0) + 1,
        document_version: (S.docVersion || 1) + 1,
        version_id: S.versionId,
        rev: S.rev + 1,
        checks: []
      });
    }
    return Promise.resolve({});
  };
  const factory = new Function(
    'S', 'CORE', 'API', 'TAB_ID', 'INPUT_SRC', 'document',
    'setSave', 'toast', 'renderConflicts', 'renderPresence', 'applyLocks',
    'notifyPresence', 'applyRevoked', 'setPlanRev', 'releaseLease',
    'refreshFamilyState', 'refreshFamilyAdvice', 'request', 'ensureLease',
    'queue', 'idemKey', 'fieldValue', 'window', 'navigator',
    body + '\nreturn {S: S, ' + names.map(function (name) {
      return name + ': ' + name;
    }).join(', ') + '};'
  );
  const api = factory(
    S, CORE, '/api/m1/plans', 'tab', {}, {querySelectorAll: function () { return []; }},
    function () {}, function (m) { toasts.push(m); }, function () {}, function () {},
    function () {}, function () {}, function () {},
    function (rev) { if (rev != null) S.rev = Number(rev); },
    function () { return Promise.resolve(); }, function () {}, function () {
      return Promise.resolve();
    }, request, function () { return Promise.resolve('lease'); },
    function (fn) { return fn(); }, function (section) {
      seq += 1; return 'idem-' + section + '-' + seq;
    }, function (field) { return field.textContent || ''; }, {}, {onLine: true}
  );
  api.log = log;
  api.toasts = toasts;
  return api;
}

function assert(ok, message) {
  if (!ok) { console.error('FAIL: ' + message); process.exit(1); }
}

function goal(code, text) {
  return {code: code, goal: {text: text, src: 'mentor'},
          start: {text: '', src: 'mentor'}, expected: {text: '', src: 'mentor'},
          locked: false};
}

function exportOpts(engine, overrides) {
  const log = engine.log;
  const tab = {
    location: {replace: function (url) { log.push({type: 'nav', url: url}); }},
    close: function () { log.push({type: 'close'}); }
  };
  return Object.assign({
    state: engine.S, planId: 7, online: true,
    openTab: function () { log.push({type: 'open'}); return tab; },
    flushDirect: function () { log.push({type: 'direct'}); return Promise.resolve(); },
    flushAll: engine.flushAll,
    toast: function (message) { engine.toasts.push(message); },
    navigate: function (url) { log.push({type: 'nav', url: url}); }
  }, overrides || {});
}

function aims(log) { return log.filter(function (row) { return row.type === 'request'; }); }
function indexOfRequest(log, section) {
  return log.findIndex(function (row) {
    return row.type === 'request' && row.url.indexOf('/sections/' + section) >= 0;
  });
}
function indexOfNav(log) {
  return log.findIndex(function (row) { return row.type === 'nav'; });
}

async function main() {
  // 1) 立即编辑目标 → 切到内部版 → 导出：700ms 防抖必须先落盘。
  {
    const e = makeEngine();
    e.S.goals = [goal('R2.2', 'NEW_GOAL')];
    e.markGoalEdited();
    e.S.step2 = true;
    const ok = await e.runSessionExport(1, exportOpts(e));
    assert(ok === true, 'export succeeds');
    assert(e.S.goalDirty === false, 'goal dirty cleared after acknowledged save');
    const goals = aims(e.log).filter(function (r) { return r.url.indexOf('/sections/goals') >= 0; });
    assert(goals.length === 1, 'exactly one goals patch, got ' + goals.length);
    assert(goals[0].body.patch.goals[0].goal.text === 'NEW_GOAL', 'pending goal text persisted');
    assert(indexOfRequest(e.log, 'goals') < indexOfNav(e.log), 'navigation waits for goals ack');
    const nav = e.log[indexOfNav(e.log)];
    assert(nav && nav.url.indexOf('expected_rev=5') >= 0, 'navigation uses acknowledged rev: ' + (nav && nav.url));
    assert(nav && nav.url.indexOf('version_id=9') >= 0, 'navigation uses acknowledged version');
  }

  // 2) 延迟目标保存失败：保留正文、关闭预览、不导航。
  {
    const e = makeEngine({onRequest: function (method, url) {
      if (url.indexOf('/sections/goals') >= 0) {
        const err = new Error('保存失败');
        err.status = 500;
        err.payload = {};
        return Promise.reject(err);
      }
      return null;
    }});
    e.S.goals = [goal('R2.2', 'NEW_GOAL')];
    e.markGoalEdited();
    const ok = await e.runSessionExport(1, exportOpts(e));
    assert(ok === false, 'export blocked on failed deferred save');
    assert(indexOfNav(e.log) < 0, 'no navigation on failed save');
    assert(e.log.some(function (row) { return row.type === 'close'; }), 'loading tab closed');
    assert(e.S.goals[0].goal.text === 'NEW_GOAL', 'draft text retained');
    assert(e.S.goalDirty === true, 'dirty retained for retry');
  }

  // 3) 在途目标保存 + 等待期间的新编辑：等旧写入，再用最新正文补一轮。
  {
    let releaseFirst = null;
    let goalsCalls = 0;
    const e = makeEngine({onRequest: function (method, url) {
      if (url.indexOf('/sections/goals') >= 0) {
        goalsCalls += 1;
        if (goalsCalls === 1) {
          return new Promise(function (resolve) { releaseFirst = resolve; });
        }
      }
      return null;
    }});
    e.S.goals = [goal('R2.2', 'OLD_GOAL')];
    e.markGoalEdited();
    const inFlight = e.saveGoals();
    e.S.goals[0].goal = {text: 'NEWER_GOAL', src: 'mentor'};
    e.markGoalEdited();
    const exporting = e.runSessionExport(1, exportOpts(e));
    await new Promise(function (resolve) { setTimeout(resolve, 0); });
    assert(indexOfNav(e.log) < 0, 'no navigation while goal write is in flight');
    releaseFirst({section_version: 2, document_version: 2, version_id: 9, rev: 5, checks: []});
    await inFlight;
    const ok = await exporting;
    assert(ok === true, 'export completes after follow-up save');
    const goals = aims(e.log).filter(function (r) { return r.url.indexOf('/sections/goals') >= 0; });
    assert(goals.length === 2, 'follow-up goals patch sent, got ' + goals.length);
    assert(goals[1].body.patch.goals[0].goal.text === 'NEWER_GOAL', 'latest text persisted');
    const nav = e.log[indexOfNav(e.log)];
    assert(nav && nav.url.indexOf('expected_rev=6') >= 0, 'navigation uses follow-up rev: ' + (nav && nav.url));
  }

  // 4) 干净状态不重放旧目标。
  {
    const e = makeEngine();
    e.S.goals = [goal('R2.2', 'CLEAN_GOAL')];
    const ok = await e.runSessionExport(1, exportOpts(e));
    assert(ok === true, 'clean export succeeds');
    assert(aims(e.log).length === 0, 'clean state writes nothing');
    const nav = e.log[indexOfNav(e.log)];
    assert(nav && nav.url.indexOf('expected_rev=4') >= 0, 'clean state uses persisted rev');
  }

  // 5) 活跃教案正文与目标一起在导航前落盘。
  {
    const e = makeEngine();
    e.S.goals = [goal('R2.2', 'NEW_GOAL')];
    e.markGoalEdited();
    e.stagePatch('sessions.1.content',
      {content: {mindsets: {text: 'ACTIVE-LESSON-TEXT', src: 'edited'}}}, false);
    const ok = await e.runSessionExport(1, exportOpts(e));
    assert(ok === true, 'export with active lesson text succeeds');
    const lesson = aims(e.log).filter(function (r) {
      return r.url.indexOf('/sections/sessions.1.content') >= 0;
    });
    assert(lesson.length === 1, 'active lesson patch sent');
    assert(lesson[0].body.patch.content.mindsets.text === 'ACTIVE-LESSON-TEXT',
           'active lesson text included');
    assert(indexOfRequest(e.log, 'goals') < indexOfNav(e.log), 'goals before navigation');
    const lessonIndex = e.log.findIndex(function (row) {
      return row.type === 'request' && row.url.indexOf('/sections/sessions.1.content') >= 0;
    });
    assert(lessonIndex < indexOfNav(e.log), 'lesson text before navigation');
  }

  console.log('PASS');
}

main().catch(function (err) {
  console.error(err && err.stack || err);
  process.exit(1);
});
"""


def test_export_barrier_drains_pending_goal_debounce():
    _run_node(_JS_HARNESS)


# ---------------------------------------------------------------------------
# 打印段落保留与无障碍名称（真实 Chrome）
# ---------------------------------------------------------------------------
def test_chrome_preserves_authored_paragraphs(plan_client, m1db, tmp_path):  # noqa: F811
    from test_dp16_session_pdf import (_pdf_texts, _print_pdf)

    doc = _rich_doc(paragraphs=True)
    goals = [_goal(text="GOAL_LINE_A\n\nGOAL_LINE_B")]
    goals[0]["start"]["text"] = "START_LINE_A\nSTART_LINE_B"
    goals[0]["expected"]["text"] = "EXPECT_LINE_A\n\nEXPECT_LINE_B"
    plan, _version = _make_plan(m1db, doc=doc, goals=goals)
    _login(plan_client, m1db.alice_id, "advisor", "Alice")

    body = plan_client.get(f"/m1/plans/{plan['id']}/sessions/1/print").get_data(as_text=True)
    assert body.count('class="pp-pre"') >= 8
    reader = _print_pdf(body, tmp_path / "session-paragraphs.pdf")
    texts = _pdf_texts(reader)
    lines = [line.strip() for page in texts for line in page.splitlines()]
    joined = "\n".join(lines)

    for first, second in (
            ("GOAL_LINE_A", "GOAL_LINE_B"),
            ("START_LINE_A", "START_LINE_B"),
            ("EXPECT_LINE_A", "EXPECT_LINE_B"),
            ("QUESTION_LINE_A", "QUESTION_LINE_B"),
            ("MATERIAL_LINE_A", "MATERIAL_LINE_B"),
            ("PURPOSE_LINE_A", "PURPOSE_LINE_B"),
            ("MINDSETS_LINE_A", "MINDSETS_LINE_B"),
            ("EVIDENCE_LINE_A", "EVIDENCE_LINE_B")):
        assert first in joined and second in joined, (first, second)
        assert not any(first in line and second in line for line in lines), \
            "paragraph collapsed: %s / %s" % (first, second)

    # Session 3 的固定 KB Block Review 问题同样保留换行。
    body3 = plan_client.get(f"/m1/plans/{plan['id']}/sessions/3/print").get_data(as_text=True)
    reader3 = _print_pdf(body3, tmp_path / "session3-paragraphs.pdf")
    lines3 = [line.strip() for page in _pdf_texts(reader3) for line in page.splitlines()]
    assert not any("BR_QUESTION_LINE_A" in line and "BR_QUESTION_LINE_B" in line
                   for line in lines3), "Block Review questions collapsed"


def test_export_buttons_have_distinct_accessible_names_at_375(plan_client, m1db, tmp_path):  # noqa: F811
    playwright = pytest.importorskip("playwright.sync_api")
    import re as _re

    from test_dp16_session_pdf import _inline_assets

    plan, _version = _make_plan(m1db, doc=_rich_doc())
    _login(plan_client, m1db.alice_id, "advisor", "Alice")
    body = plan_client.get(f"/m1/plans/{plan['id']}").get_data(as_text=True)
    body = _re.sub(r"<script\b[^>]*>.*?</script>", "", body, flags=_re.S)
    page_path = tmp_path / "plan-375.html"
    page_path.write_text(_inline_assets(body), encoding="utf-8")

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 900})
        page.goto(page_path.as_uri(), wait_until="load")
        buttons = page.locator(".sess-export")
        assert buttons.count() == 3
        for n in (1, 2, 3):
            button = page.get_by_role("button", name=f"导出 Session {n} PDF")
            assert button.is_visible()
            assert button.evaluate("el => el.tagName") == "BUTTON"
            assert button.evaluate("el => el.tabIndex") >= 0
            box = button.bounding_box()
            assert box is not None
            assert box["x"] >= 0 and box["x"] + box["width"] <= 375.5, box
        buttons.nth(1).focus()
        assert page.evaluate(
            "document.activeElement.getAttribute('data-session')") == "2"
        browser.close()


# ---------------------------------------------------------------------------
# 真实浏览器走查：防抖未落盘的目标必须进入打印投影
# ---------------------------------------------------------------------------
def _goal_text_in_store(db, plan_id):
    return ((pstore.get_plan(plan_id)["goals"][0].get("goal") or {}).get("text") or "")


def test_browser_pending_goal_reaches_printed_projection(plan_client, m1db):  # noqa: F811
    """目标输入后立刻切到内部版并导出：打印页显示新目标，而不是旧修订。"""
    playwright = pytest.importorskip("playwright.sync_api")
    from flask import Flask
    from werkzeug.serving import make_server

    from app_utils import BASE_DIR
    from blueprints import m1 as m1_api
    from blueprints import m1_plan

    plan, _version = _make_plan(
        m1db, doc=_rich_doc(), goals=[_goal(text="OLD-GOAL-BROWSER")])
    _login(plan_client, m1db.alice_id, "advisor", "Alice")

    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
                static_folder=str(BASE_DIR / "static"), static_url_path="/static")
    app.secret_key = os.urandom(24)
    app.register_blueprint(m1_api.bp)
    app.register_blueprint(m1_plan.bp)
    cookie = app.session_interface.get_signing_serializer(app).dumps(
        {"user_id": m1db.alice_id, "role": "advisor", "advisor_name": "Alice"})

    server = make_server("127.0.0.1", 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_port
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            context.add_cookies([{"name": "session", "value": cookie, "url": base}])
            page = context.new_page()
            # 冻结页面定时器：700ms 防抖在点击导出前一定还没有触发。
            page.clock.install()
            page.goto(base + "/m1/plans/%d#step=inputs" % plan["id"],
                      wait_until="load")
            page.locator('[data-panel="inputs"]').wait_for(state="visible")
            field = page.locator('[data-goal-text="R2.2"]')
            field.click()
            field.fill("GOAL-FROM-PENDING-DEBOUNCE")
            assert _goal_text_in_store(m1db, plan["id"]) == "OLD-GOAL-BROWSER"
            assert field.inner_text() == "GOAL-FROM-PENDING-DEBOUNCE"

            page.locator('[data-step="internal"]').click()
            export = page.locator('.sess-export[data-session="1"]')
            export.wait_for(state="visible")
            with context.expect_page() as opened:
                export.click()
            popup = opened.value
            popup.wait_for_url(re.compile(r"/sessions/1/print\?expected_rev=\d+"))
            html = popup.content()

            assert "GOAL-FROM-PENDING-DEBOUNCE" in html, \
                "pending goal missing from printed projection"
            assert "OLD-GOAL-BROWSER" not in html, "stale goal leaked into print"
            assert _goal_text_in_store(m1db, plan["id"]) == "GOAL-FROM-PENDING-DEBOUNCE"
            nav_rev = int(re.search(r"expected_rev=(\d+)", popup.url).group(1))
            assert nav_rev == int(pstore.get_plan(plan["id"])["rev"])
            browser.close()
    finally:
        server.shutdown()

