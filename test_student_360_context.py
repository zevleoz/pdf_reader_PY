"""学生 360° 页头部上下文测试（生命周期进度视图）。"""
import blueprints.students as students
from blueprints.students import _student_progress_context


def _stub(monkeypatch, stage, **extra):
    info = {"stage": stage, "days": 0, "since_label": "今天", "six_am": None}
    info.update(extra)
    monkeypatch.setattr(students, "compute_progress", lambda sid: info)


def test_student_progress_context_ready_has_no_suggestion(monkeypatch):
    _stub(monkeypatch, "ready")
    ctx = _student_progress_context(1)
    assert ctx["stage"] == "ready"
    assert ctx["suggestion"] is None


def test_student_progress_context_report_points_to_generate(monkeypatch):
    _stub(monkeypatch, "report")
    ctx = _student_progress_context(1)
    assert ctx["label"] == "生成报告"
    assert ctx["suggestion"]["action_href"] == "/generate"


def test_student_progress_context_minutes_points_to_transcript(monkeypatch):
    _stub(monkeypatch, "minutes")
    ctx = _student_progress_context(1)
    assert ctx["label"] == "会议纪要"
    assert ctx["suggestion"]["action_href"] == "/tools/transcript"


def test_student_progress_context_pending_approval_points_to_workspace(monkeypatch):
    _stub(monkeypatch, "pending_approval")
    ctx = _student_progress_context(1)
    assert ctx["suggestion"]["action_href"] == "/workspace"


def test_student_progress_context_awaiting_student_uses_package_action(monkeypatch):
    _stub(monkeypatch, "awaiting_student")
    ctx = _student_progress_context(1)
    assert ctx["suggestion"]["action_kind"] == "package"


def test_student_progress_context_exposes_six_am_state(monkeypatch):
    _stub(monkeypatch, "minutes",
          six_am={"status": "pending", "label": "后台更新中", "version": None})
    ctx = _student_progress_context(1)
    assert ctx["six_am"]["status"] == "pending"


def test_student_360_route_uses_progress_stage_meta():
    src = open("blueprints/students.py", encoding="utf-8").read()
    assert "stage_meta=PROGRESS_STAGES" in src
