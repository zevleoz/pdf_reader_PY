"""报告完成后置钩子测试：Six A.M. v0.6 作为后台更新，失败不改动 job 状态。"""
import blueprints.reports as reports
import six_am


def test_six_am_hook_swallows_errors(monkeypatch, capsys):
    monkeypatch.setattr(six_am, "run_v06_for_report",
                        lambda rid: (_ for _ in ()).throw(RuntimeError("boom")))
    reports._run_six_am_hook(9)
    assert "生成失败" in capsys.readouterr().out


def test_six_am_hook_runs_for_report(monkeypatch):
    calls = []
    monkeypatch.setattr(six_am, "run_v06_for_report", lambda rid: calls.append(rid))
    reports._run_six_am_hook(9)
    assert calls == [9]


def test_six_am_hook_skips_without_report_id():
    reports._run_six_am_hook(None)  # 不应抛异常


def test_save_report_to_db_no_longer_calls_six_am_directly():
    """顺序约束：归档函数内不再直接调用 6AM 生成。"""
    src = open("blueprints/reports.py", encoding="utf-8").read()
    archive = src.split("def _save_report_to_db", 1)[1].split("\ndef _find_generated_pdf", 1)[0]
    assert "six_am.run_v06_for_report" not in archive
    assert "six_am.run_for_report" not in archive
    assert "recognize_for_report" in archive


def test_pipeline_job_updates_six_am_after_job_done():
    src = open("blueprints/reports.py", encoding="utf-8").read()
    job = src.split("def _run_pipeline_job", 1)[1]
    done_at = job.index('_write_job(status="done"')
    hook_at = job.index("_run_six_am_hook(report_id)")
    assert done_at < hook_at
