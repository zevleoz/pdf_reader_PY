"""Growth Talk 子进程作业与状态文件测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from app_utils import BASE_DIR
from growth_talk import jobs


@pytest.fixture()
def job_dir(tmp_path, monkeypatch):
    directory = tmp_path / "_gt_jobs"
    monkeypatch.setattr(jobs, "JOB_DIR", directory)
    return directory


def test_write_and_read_job_atomically(job_dir):
    jobs.write_gt_job(7, status="running", message="分析任务运行中")
    data = jobs.read_gt_job(7)
    assert data["status"] == "running"
    assert data["updated_at"]
    assert not list(job_dir.glob("*.tmp"))


def test_read_missing_job_returns_none(job_dir):
    assert jobs.read_gt_job(999) is None


def test_run_analysis_job_marks_done(job_dir, monkeypatch):
    calls = []
    monkeypatch.setattr("growth_talk.runs.create_and_run_analysis",
                        lambda run_id: calls.append(run_id))
    jobs.run_analysis_job(3)
    assert calls == [3]
    assert jobs.read_gt_job(3)["status"] == "done"


def test_run_analysis_job_marks_error(job_dir, monkeypatch):
    def boom(_run_id):
        raise RuntimeError("模型不可用")

    monkeypatch.setattr("growth_talk.runs.create_and_run_analysis", boom)
    with pytest.raises(RuntimeError, match="模型不可用"):
        jobs.run_analysis_job(4)
    data = jobs.read_gt_job(4)
    assert data["status"] == "error"
    assert "模型不可用" in data["message"]


def test_launch_analysis_uses_detached_subprocess(job_dir, monkeypatch):
    monkeypatch.setattr(jobs.time, "sleep", lambda _seconds: None)
    process = mock.MagicMock()
    process.poll.return_value = None
    with mock.patch.object(jobs.subprocess, "Popen",
                           return_value=process) as popen:
        jobs.launch_analysis(9)

    args, kwargs = popen.call_args
    assert args[0] == [sys.executable, str(Path(BASE_DIR) / "app.py"),
                       "gtjob", "9"]
    assert kwargs["cwd"] == str(BASE_DIR)
    assert kwargs["stdin"] is jobs.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert (job_dir / "9.log").exists()


def test_launch_analysis_reports_immediate_exit(job_dir, monkeypatch):
    monkeypatch.setattr(jobs.time, "sleep", lambda _seconds: None)
    process = mock.MagicMock()
    process.poll.return_value = 1
    process.returncode = 1
    with mock.patch.object(jobs.subprocess, "Popen", return_value=process):
        with pytest.raises(jobs.JobLaunchError, match="启动失败"):
            jobs.launch_analysis(11)
    assert jobs.read_gt_job(11)["status"] == "error"
