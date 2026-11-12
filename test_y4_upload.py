# -*- coding: utf-8 -*-
"""S4-U1：Y4 单文件上传 —— 单槽位读取、合并、队列、生成。

不做任何真实 AI 调用：读取函数 y4_upload.extract_slot 在大多数用例里被替换；
一个用例走真实的 extract.main()（A2），其视觉调用同样被替换。
"""
from __future__ import annotations

import io
import itertools
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import select
from sqlalchemy.orm import Session

import app_utils
import db as _db
import y4_upload as y4
from blueprints import reports as reports_bp
from blueprints import students as students_bp

PDF = b"%PDF-1.4\n%fake\n"
REAL_EXTRACT_SLOT = y4.extract_slot  # 夹具会替换它；真实读取用例要用原函数
_counter = itertools.count(1)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture()
def env(tmp_path, monkeypatch):
    _db.Base.metadata.create_all(_db.engine)
    with Session(_db.engine) as sess:
        sess.query(y4.Y4Job).delete()
        sess.query(y4.Y4Round).delete()
        sess.commit()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(y4, "DATA_DIR", data)
    monkeypatch.setattr(y4, "JOB_FILE", data / "_job.json")
    monkeypatch.setattr(y4, "_WORKER_LOCK", data / "_y4worker.lock")
    monkeypatch.setattr(reports_bp, "UPLOAD_DIR", data / "_uploads")
    monkeypatch.setattr(y4, "_sleep", lambda s: None)
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: True)
    spawned = []
    monkeypatch.setattr(y4, "spawn_worker", lambda: spawned.append(1) or True)
    # 以下读取调用的记录与可控返回
    calls = []
    plan = {"name": None, "fail": set()}

    def fake_extract(pdf, slot, workdir, file_name=""):
        calls.append(slot)
        assert Path(pdf).exists()
        if slot in plan["fail"]:
            raise RuntimeError("视觉读取失败(模拟)")
        values = {c: str(10 + i) for i, c in enumerate(y4.slot_codes(slot))}
        return {"values": values,
                "student": {"name": plan["name"] or env.student_name,
                            "school": "测试中学"},
                "b3_detail": ({"motivation_type": "深层", "method_type": "实践",
                               "practice_dims": [], "practice_items": [],
                               "exec_dims": [], "exec_items": [], "checks": []}
                              if slot == "B3" else None),
                "vision": {"model": "mock"}}

    monkeypatch.setattr(y4, "extract_slot", fake_extract)
    monkeypatch.setattr(y4, "_six_am", lambda rid: None)

    class Env:
        pass

    env = Env()
    env.data = data
    env.calls = calls
    env.plan = plan
    env.spawned = spawned
    env.student_name = "林同学"
    env.app = Flask(__name__)
    env.app.config.update(SECRET_KEY="t", TESTING=True)
    env.app.register_blueprint(students_bp.bp)
    env.app.register_blueprint(reports_bp.bp)
    return env


def new_student(name="林同学", advisor="Alice"):
    n = next(_counter)
    with Session(_db.engine) as sess:
        s = _db.Student(student_code=f"Y4-U{n:04d}", name=name, grade="10",
                        advisor_name=advisor)
        sess.add(s)
        sess.commit()
        return {"id": s.id, "student_code": s.student_code, "name": name}


def client(env, role="admin", advisor="Alice"):
    c = env.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = role
        s["advisor_name"] = advisor
        s["display_name"] = "测试员"
    return c


def upload(c, slot, upload_id, data=PDF, parts=1):
    size = max(1, len(data) // parts)
    chunks = [data[i:i + size] for i in range(0, len(data), size)][:parts]
    chunks[-1] += data[size * parts:]
    for i, ch in enumerate(chunks):
        r = c.post("/api/upload/chunk", data={
            "key": slot, "upload_id": upload_id, "chunk_index": i,
            "total_chunks": len(chunks), "chunk": (io.BytesIO(ch), "x.pdf")},
            content_type="multipart/form-data")
        assert r.status_code == 200, r.get_json()


def read(c, st, slot, upload_id=None, data=PDF, file_name=""):
    uid = upload_id or f"u{next(_counter)}"
    upload(c, slot, uid, data)
    return c.post(f"/students/{st['student_code']}/api/y4/read",
                  json={"slot": slot, "upload_id": uid, "file_name": file_name})


def status(c, st):
    r = c.get(f"/students/{st['student_code']}/api/y4/status")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def run_all():
    y4.run_worker(poll_seconds=0)


def raw_of(report_id):
    with Session(_db.engine) as sess:
        return json.loads(sess.get(_db.Report, report_id).data_json)


def values(raw):
    return {it["code"]: it["value"] for it in raw["schema_124"]}


# ---------------------------------------------------------------------------
# 读取与合并
# ---------------------------------------------------------------------------
def test_read_fills_only_that_slot(env):
    st = new_student()
    c = client(env)
    r = read(c, st, "A2")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] and body["position"] == 1 and env.spawned
    s0 = status(c, st)
    assert s0["slots"]["A2"]["state"] == "queued"
    assert s0["slots"]["B3"]["state"] == "empty"

    run_all()
    s1 = status(c, st)
    assert s1["slots"]["A2"]["state"] == "done"
    assert s1["slots"]["A2"]["read_at"]
    assert s1["slots"]["A2"]["name_mismatch"] is False
    for other in ("B3", "B4", "B6"):
        assert s1["slots"][other]["state"] == "empty"
    vals = values(raw_of(s1["report_id"]))
    for code in y4.slot_codes("A2"):
        assert vals[code] is not None
    for slot in ("B3", "B4", "B6"):
        for code in y4.slot_codes(slot):
            assert vals[code] is None, code  # 未上传是 null，不是 0 也不是空串
    # 原文件已保存，可取回
    assert c.get(f"/students/{st['student_code']}/api/y4/slots/A2/file").data == PDF
    assert c.get(f"/students/{st['student_code']}/api/y4/slots/B3/file").status_code == 404


def test_second_slot_merges_without_touching_first(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    first = {k: v for k, v in values(raw_of(rid)).items() if k in y4.slot_codes("A2")}
    read(c, st, "B4")
    run_all()
    s = status(c, st)
    assert s["report_id"] == rid  # 同一条当前记录
    raw = raw_of(rid)
    vals = values(raw)
    assert {k: vals[k] for k in first} == first
    assert all(vals[c_] is not None for c_ in y4.slot_codes("B4"))
    assert all(vals[c_] is None for c_ in y4.slot_codes("B6"))
    assert raw["pdf_titles"] == ["A2", "B4"]


def test_reupload_replaces_hand_edits_and_logs_them(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    _db.update_report_values(rid, {"009": "99"}, "王老师")
    assert status(c, st)["edited_codes_by_slot"]["A2"] == ["009"]

    read(c, st, "A2")
    run_all()
    s = status(c, st)
    raw = raw_of(rid)
    assert values(raw)["009"] != "99"
    last = raw["edits"][-1]
    assert (last["code"], last["old"], last["by"]) == ("009", "99", "upload:A2")
    assert last["new"] == values(raw)["009"]
    # 手改记录里王老师那条仍在
    assert any(e["by"] == "王老师" and e["new"] == "99" for e in raw["edits"])
    # 已被新读取覆盖，不再算「手改」
    assert s["edited_codes_by_slot"]["A2"] == []


def test_name_mismatch_flagged_and_does_not_block(env):
    st = new_student()
    c = client(env)
    env.plan["name"] = "另一个人"
    read(c, st, "B4")
    run_all()
    s = status(c, st)["slots"]["B4"]
    assert s["state"] == "done"
    assert s["name_mismatch"] is True and s["name_in_pdf"] == "另一个人"


def test_b3_detail_replaced_by_b3_read(env):
    st = new_student()
    c = client(env)
    read(c, st, "B3")
    run_all()
    rid = status(c, st)["report_id"]
    assert raw_of(rid)["b3_detail"]["motivation_type"] == "深层"


# ---------------------------------------------------------------------------
# 队列
# ---------------------------------------------------------------------------
def test_two_queued_reads_run_in_order_and_never_409(env):
    a, b = new_student("甲"), new_student("乙")
    c = client(env)
    r1 = read(c, a, "A2")
    r2 = read(c, b, "B6")
    r3 = read(c, a, "B4")
    assert [r.status_code for r in (r1, r2, r3)] == [200, 200, 200]
    assert [r.get_json()["position"] for r in (r1, r2, r3)] == [1, 2, 3]
    assert status(c, b)["slots"]["B6"]["position"] == 2
    run_all()
    assert env.calls == ["A2", "B6", "B4"]
    sa, sb = status(c, a), status(c, b)
    assert sa["slots"]["A2"]["state"] == sa["slots"]["B4"]["state"] == "done"
    assert sb["slots"]["B6"]["state"] == "done" and sb["slots"]["A2"]["state"] == "empty"
    assert sa["report_id"] != sb["report_id"]


def test_questionnaire_hook_runs_after_read_and_failure_is_nonfatal(env, monkeypatch):
    import questionnaire_store as qs
    hits = []
    monkeypatch.setattr(qs, "recognize_for_report", lambda rid: hits.append(rid) or {})
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    assert hits == [rid]

    def boom(rid):
        raise RuntimeError("hook down")

    monkeypatch.setattr(qs, "recognize_for_report", boom)
    read(c, st, "B4")
    run_all()
    assert status(c, st)["slots"]["B4"]["state"] == "done"


def test_same_slot_twice_while_pending_is_rejected(env):
    st = new_student()
    c = client(env)
    assert read(c, st, "A2").status_code == 200
    assert read(c, st, "A2").status_code == 409


def test_worker_waits_while_batch_job_holds_lock(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    y4.JOB_FILE.write_text(json.dumps({"status": "running", "updated_at": time.time()}))
    waits = []

    def fake_sleep(_s):
        waits.append(list(env.calls))
        if len(waits) == 3:  # 批量任务结束
            y4.JOB_FILE.write_text(json.dumps({"status": "done", "filename": "x.pdf",
                                               "updated_at": time.time()}))

    y4._sleep = fake_sleep
    run_all()
    assert len(waits) == 3 and all(w == [] for w in waits)  # 等待期间没有读取
    assert env.calls == ["A2"]
    s = status(c, st)
    assert s["slots"]["A2"]["state"] == "done"
    # 批量任务留下的状态原样还回去
    assert json.loads(y4.JOB_FILE.read_text())["filename"] == "x.pdf"


def test_worker_holds_job_lock_while_running(env, monkeypatch):
    monkeypatch.setattr(reports_bp, "JOB_FILE", y4.JOB_FILE)
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    seen = {}
    real = y4.extract_slot

    def spy(*a, **k):
        job = json.loads(y4.JOB_FILE.read_text())
        seen["running"] = job["status"] == "running"
        seen["old_route_would_409"] = reports_bp._job_running()
        return real(*a, **k)

    monkeypatch.setattr(y4, "extract_slot", spy)
    run_all()
    assert seen["running"] is True and seen["old_route_would_409"] is True
    assert json.loads(y4.JOB_FILE.read_text())["status"] == "idle"


def test_stale_running_job_counts_as_failed(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    job = y4.claim_next()
    assert job and y4.claim_next() is None  # 已有 running，不会再领
    with Session(_db.engine) as sess:
        j = sess.get(y4.Y4Job, job["id"])
        j.started_at = datetime.utcnow() - timedelta(minutes=25)
        sess.commit()
    s = status(c, st)
    assert s["slots"]["A2"]["state"] == "failed"
    assert s["slots"]["A2"]["job_id"] == job["id"]
    assert y4.get_job(job["id"])["status"] == "failed"
    # 失败后队列不再被它卡住
    read(c, st, "B4")
    run_all()
    assert status(c, st)["slots"]["B4"]["state"] == "done"


def test_failed_read_exposes_job_and_can_retry(env):
    st = new_student()
    c = client(env)
    env.plan["fail"] = {"B3"}
    read(c, st, "B3")
    run_all()
    s = status(c, st)["slots"]["B3"]
    assert s["state"] == "failed" and s["error"] == y4.MSG_UNEXPECTED and s["job_id"]
    env.plan["fail"] = set()
    r = c.post(f"/students/{st['student_code']}/api/y4/jobs/{s['job_id']}/retry")
    assert r.status_code == 200
    run_all()
    assert status(c, st)["slots"]["B3"]["state"] == "done"
    # 已完成的任务不能重试
    old = c.post(f"/students/{st['student_code']}/api/y4/jobs/{r.get_json()['job_id']}/retry")
    assert old.status_code == 409


def test_failed_reread_keeps_old_values(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    before = values(raw_of(rid))
    env.plan["fail"] = {"A2"}
    read(c, st, "A2")
    run_all()
    s = status(c, st)
    assert s["slots"]["A2"]["state"] == "failed"
    assert values(raw_of(rid)) == before
    assert raw_of(rid)["pdf_titles"] == ["A2"]


def test_worker_exclusive_lock_and_atomic_claim(env):
    fh = y4._try_lock()
    assert y4.worker_alive() is True
    y4._unlock(fh)
    assert y4.worker_alive() is False
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    read(c, st, "B4")
    first = y4.claim_next()
    assert first and first["slot"] == "A2"
    assert y4.claim_next() is None


# ---------------------------------------------------------------------------
# 新一轮 / 权限
# ---------------------------------------------------------------------------
def report_ids(st):
    with Session(_db.engine) as sess:
        return [r.id for r in sess.execute(
            select(_db.Report).where(_db.Report.student_id == st["id"])).scalars()]


def stage_of(st):
    import pipeline
    return pipeline.compute_stages(None).get(st["id"])


def test_new_round_creates_no_report_and_old_stays_latest(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    old_id = status(c, st)["report_id"]
    with Session(_db.engine) as sess:
        before = sess.get(_db.Report, old_id).data_json
    r = c.post(f"/students/{st['student_code']}/api/y4/new-round")
    assert r.status_code == 200 and r.get_json()["report_id"] is None
    rnd = r.get_json()["round_id"]
    s = status(c, st)
    assert s["round_id"] == rnd and s["report_id"] is None
    assert all(v["state"] == "empty" for v in s["slots"].values())
    assert report_ids(st) == [old_id]
    # 新一轮第一次读取失败：旧报告仍是学生的最新报告
    env.plan["fail"] = {"B4"}
    read(c, st, "B4")
    run_all()
    assert status(c, st)["slots"]["B4"]["state"] == "failed"
    assert report_ids(st) == [old_id]
    assert _db.get_latest_report_raw(st["id"])["report_id"] == old_id
    with Session(_db.engine) as sess:
        assert sess.get(_db.Report, old_id).data_json == before
    # 第一次成功才建出新行
    env.plan["fail"] = set()
    j = status(c, st)["slots"]["B4"]["job_id"]
    c.post(f"/students/{st['student_code']}/api/y4/jobs/{j}/retry")
    run_all()
    ids = report_ids(st)
    assert len(ids) == 2 and status(c, st)["report_id"] == max(ids)
    assert all(v is None for k, v in values(raw_of(max(ids))).items()
               if k in y4.slot_codes("A2"))


def test_failed_or_queued_read_leaves_no_report_row(env):
    st = new_student()
    c = client(env)
    stage0 = stage_of(st)
    env.plan["fail"] = {"A2"}
    read(c, st, "A2")
    assert report_ids(st) == [] and stage_of(st) == stage0  # 排队中
    s = status(c, st)
    assert s["report_id"] is None and s["slots"]["A2"]["state"] == "queued"
    run_all()
    s = status(c, st)
    assert s["slots"]["A2"]["state"] == "failed" and s["report_id"] is None
    assert report_ids(st) == [] and stage_of(st) == stage0
    assert _db.get_latest_report_raw(st["id"]) is None
    # 失败后重试、原文件下载、仍然可用
    env.plan["fail"] = set()
    assert c.get(f"/students/{st['student_code']}/api/y4/slots/A2/file").data == PDF
    c.post(f"/students/{st['student_code']}/api/y4/jobs/{s['slots']['A2']['job_id']}/retry")
    run_all()
    assert status(c, st)["slots"]["A2"]["state"] == "done"


def test_first_successful_read_creates_exactly_one_row(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    ids = report_ids(st)
    assert len(ids) == 1
    read(c, st, "B4")
    run_all()
    read(c, st, "A2")
    run_all()
    assert report_ids(st) == ids and status(c, st)["report_id"] == ids[0]


def test_staff_facing_errors_have_no_class_names_or_setup_text(env, capsys):
    st = new_student()
    c = client(env)
    boom = {"A2": RuntimeError("未设置视觉 API Key。请在环境变量中配置 export DASHSCOPE_API_KEY=x"),
            "B4": ValueError("secret internal detail 42"),
            "B6": y4.ReadError("没有这份数据")}
    real = y4.extract_slot

    def raising(pdf, slot, workdir, file_name=""):
        if slot in boom:
            raise boom[slot]
        return real(pdf, slot, workdir, file_name)

    y4.extract_slot = raising
    for slot in boom:
        read(c, st, slot)
    run_all()
    sl = status(c, st)["slots"]
    assert sl["A2"]["error"] == "读取服务暂时不可用，请联系管理员"
    assert sl["B4"]["error"] == "读取失败，请重试；如果仍然失败，请联系管理员"
    assert sl["B6"]["error"] == "没有这份数据"
    for v in sl.values():
        assert "Error" not in v["error"] and "DASHSCOPE" not in v["error"]
    cap = capsys.readouterr()
    log = cap.out + cap.err
    assert "secret internal detail 42" in log and "ValueError" in log  # 完整信息进日志
    # 空读取是有意的中文提示，不带异常前缀
    y4.extract_slot = real
    env.plan["fail"] = set()
    y4.extract_slot = lambda *a, **k: {"values": {}, "student": {}}
    read(c, st, "B3")
    run_all()
    assert status(c, st)["slots"]["B3"]["error"].startswith("没有从这份资料里读到任何数据")


def test_non_admin_gets_403_and_anonymous_redirected(env, monkeypatch):
    st = new_student()
    viewer = client(env, role="viewer")
    code = st["student_code"]
    for path in (f"/students/{code}/api/y4/read", f"/students/{code}/api/y4/build",
                 f"/students/{code}/api/y4/new-round",
                 f"/students/{code}/api/y4/jobs/1/retry"):
        assert viewer.post(path, json={}).status_code == 403, path
    assert env.spawned == [] and y4.pending_jobs() == []
    monkeypatch.setattr(app_utils, "is_authenticated", lambda: False)
    anon = env.app.test_client()
    # /students/... 下的接口沿用既有约定：未登录跳 /login（不是 /api/ 前缀，所以不是 401）
    for r in (anon.post(f"/students/{code}/api/y4/build"),
              anon.get(f"/students/{code}/api/y4/status")):
        assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert y4.pending_jobs() == []


def test_advisor_cannot_touch_other_advisors_student(env):
    st = new_student(advisor="Bob")
    c = client(env, role="advisor", advisor="Alice")
    with c.session_transaction() as s:
        s["student_scope"] = "own"
    assert c.get(f"/students/{st['student_code']}/api/y4/status").status_code == 403
    assert read(c, st, "A2").status_code == 403
    assert y4.pending_jobs() == []


def test_bad_inputs_rejected(env):
    st = new_student()
    c = client(env)
    base = f"/students/{st['student_code']}/api/y4/read"
    assert c.post(base, json={"slot": "Z9", "upload_id": "u1"}).status_code == 400
    assert c.post(base, json={"slot": "A2", "upload_id": "../x"}).status_code == 400
    assert c.post(base, json={"slot": "A2", "upload_id": "nothing"}).status_code == 400
    r = read(c, st, "A2", data=b"not a pdf at all")
    assert r.status_code == 400 and "PDF" in r.get_json()["error"]
    assert y4.pending_jobs() == []
    assert c.post(f"/students/{st['student_code']}/api/y4/build").status_code == 400


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def test_build_uses_only_read_slots_and_sets_pdf_path(env, monkeypatch):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    seen = {}

    def fake_render(snapshot):
        seen["snap"] = snapshot
        out = env.data / "out"
        out.mkdir(exist_ok=True)
        (out / "v1.pdf").write_bytes(b"%PDF-1 v1")
        (out / "v2.pdf").write_bytes(b"%PDF-1 v2")
        return out / "v1.pdf", out / "v2.pdf"

    monkeypatch.setattr(y4, "_render_pdfs", fake_render)
    r = c.post(f"/students/{st['student_code']}/api/y4/build")
    assert r.status_code == 200 and r.get_json()["position"] == 1
    assert status(c, st)["build"]["state"] == "queued"
    run_all()
    s = status(c, st)
    assert s["build"]["state"] == "done" and s["build"]["pdf_ready"] is True
    assert s["build"]["stale"] is False
    snap = seen["snap"]
    assert snap["pdf_titles"] == ["A2"]
    assert all(it["value"] is not None for it in snap["schema_124"])  # null → ""
    with Session(_db.engine) as sess:
        assert sess.get(_db.Report, s["report_id"]).pdf_path.endswith("v2.pdf")
    dl = c.get(f"/students/{st['student_code']}/api/y4/build/file")
    assert dl.status_code == 200 and dl.data == b"%PDF-1 v2"
    assert c.get(f"/students/{st['student_code']}/api/y4/build/file?legacy=1").data == b"%PDF-1 v1"
    # 之后再读一份新资料，已生成的 PDF 标为过期
    time.sleep(1.1)
    read(c, st, "B4")
    run_all()
    assert status(c, st)["build"]["stale"] is True
    # 库里存的值没被快照的 ""（原本是 null）改写
    assert values(raw_of(s["report_id"]))[y4.slot_codes("B6")[0]] is None


def test_build_twice_while_pending_returns_same_job(env):
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    a = c.post(f"/students/{st['student_code']}/api/y4/build").get_json()
    b = c.post(f"/students/{st['student_code']}/api/y4/build").get_json()
    assert a["job_id"] == b["job_id"]


def test_v2_leaves_out_pages_of_unread_slots_and_never_zero(env, tmp_path):
    """真实的 v2 渲染（只到 HTML）：只读了 A2 → B3/B4/B6 的页整页不出。"""
    import sys
    sys.path.insert(0, str(y4.BASE_DIR / "new_iteration"))
    import render_v2
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    def render_html(path, _out):
        """与 render_v2.render_html_to 相同，只去掉拷贝 branding/ 的那步（该目录不进 git）。"""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        d = {i["code"]: i["value"] for i in raw["schema_124"]}
        ctx = render_v2.build_context(raw["student"], d, render_v2.present_slots(raw, d))
        env_ = Environment(loader=FileSystemLoader(str(y4.BASE_DIR / "new_iteration")),
                           autoescape=select_autoescape(default=True, default_for_string=True))
        return env_.get_template(render_v2.TEMPLATE_NAME).render(**ctx)

    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    snap = y4.build_snapshot(y4.load_raw(rid), y4.current_round(st["id"])["state"])
    data_path = tmp_path / "snap.json"
    data_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    html_a2 = render_html(data_path, None)
    assert "page divider dv-xin" in html_a2 and "page divider dv-jing" in html_a2      # A2 的两个分隔页
    assert "page divider dv-xue" not in html_a2 and "page divider dv-sheng" not in html_a2  # B3/B4/B6 的没有

    read(c, st, "B6")
    run_all()
    snap = y4.build_snapshot(y4.load_raw(rid), y4.current_round(st["id"])["state"])
    data_path.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    html_b6 = render_html(data_path, None)
    assert "page divider dv-sheng" in html_b6 and "page divider dv-xue" not in html_b6
    assert html_b6.count('class="page') > html_a2.count('class="page') - 1


def test_null_record_works_in_existing_readers(env):
    """全是 null 的新记录（以及只读了一份）不能让既有的读取端点出错。"""
    st = new_student()
    c = client(env)
    read(c, st, "A2")
    run_all()
    rid = status(c, st)["report_id"]
    code = st["student_code"]
    assert c.get(f"/students/{code}/api/profile").status_code == 200
    for path in (f"/api/reports/{rid}/raw", f"/api/reports/{rid}/qualification",
                 f"/api/reports/{rid}/y4-signals"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.get_data(as_text=True)[:300])


def test_legacy_batch_record_is_adopted(env):
    """批量流程生成的旧记录（没有 slots）：按 pdf_titles 推断，没有的槽位改 null。"""
    st = new_student()
    raw = {"student": {"name": "林同学"}, "pdf_titles": ["A2", "B4"],
           "schema_124": [{"code": c_, "label": "x", "value": "5", "type": "number",
                           "source_pdf": "A2"} for c_ in y4.slot_codes("A2")[:3]]
           + [{"code": c_, "label": "x", "value": "", "type": "number",
               "source_pdf": "B3"} for c_ in y4.slot_codes("B3")[:2]]}
    with Session(_db.engine) as sess:
        r = _db.Report(student_id=st["id"], report_date=datetime.now().date(),
                       pdf_path="old.pdf", data_json=json.dumps(raw))
        sess.add(r)
        sess.commit()
        old_id = r.id
    c = client(env)
    s = status(c, st)
    assert s["report_id"] == old_id
    assert s["slots"]["A2"]["state"] == "done" and s["slots"]["B3"]["state"] == "empty"
    read(c, st, "B3")
    run_all()
    assert status(c, st)["slots"]["B3"]["state"] == "done"


# ---------------------------------------------------------------------------
# 真实的 extract.main()（A2），视觉调用被替换；确认只在临时目录里读、全局目录不变
# ---------------------------------------------------------------------------
def test_real_extract_reads_one_slot_in_its_own_folder(env, tmp_path, monkeypatch):
    import extract
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "A2.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "姓名：林同学", fontname="china-s", fontsize=12)
    page.insert_text((72, 130), "总得分是 32.5 分", fontname="china-s", fontsize=12)
    doc.save(str(pdf))
    doc.close()

    asked = []

    def fake_vision(slot, b64_images, prompt, **kw):
        asked.append(slot)
        return {"data": [{"code": "009", "value": "32.5"}, {"code": "010", "value": "中"}]}

    monkeypatch.setattr(extract, "_call_vision_with_retry", fake_vision)
    monkeypatch.setattr(extract, "_refresh_vision_env", lambda: None)
    monkeypatch.setattr(extract, "VISION_ACTIVE_KEY", "test-key")
    monkeypatch.setattr(extract, "HAS_VISION_API", False)
    before = (extract.INPUT_DIR, extract.DATA_DIR, extract.PAGES_DIR)
    import _vision_values_bar
    bar_before = _vision_values_bar.main

    work = tmp_path / "work"
    res = REAL_EXTRACT_SLOT(pdf, "A2", work)

    assert asked == ["A2"]  # 只问了这一个槽位
    assert res["values"]["009"] == "32.5" and res["values"]["010"] == "中"
    assert set(res["values"]) == set(y4.slot_codes("A2"))
    assert res["student"]["name"] == "林同学"
    assert (work / "input" / "report_A2.pdf").exists()
    assert (work / "data" / "report_data.json").exists()
    assert (extract.INPUT_DIR, extract.DATA_DIR, extract.PAGES_DIR) == before
    assert _vision_values_bar.main is bar_before
