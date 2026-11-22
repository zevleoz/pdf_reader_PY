"""Permission-aware actions shared by the M1 roster and student pages."""
from datetime import date

from m1.plan_store import report_ready


def meeting_label(value, today=None):
    if not value:
        return "日期待定"
    if value < (today or date.today()).isoformat():
        return "日期已过 · 待确认"
    return "已安排"


def _task(kind, label, href, *, owner="", actionable=True, finished=False):
    return {"kind": kind, "label": label, "href": href, "owner": owner,
            "actionable": actionable, "finished": finished, "primary": actionable}


def _meeting_tasks(prep, report, report_allowed, today):
    base = f"/m1/preps/{prep['id']}"
    owner = prep.get("mentor_name") or "负责导师"
    can_edit = prep.get("can_edit", False)
    report_edit = can_edit and report_allowed
    if report.get("started"):
        status = report["status"]
        if status == "published":
            label, step = "查看正式报告（家长）", "review"
        elif not report_edit:
            label, step = "查看会后报告（只读）", "review"
        elif status == "generating":
            label, step = "查看报告生成进度", "sources"
        elif status == "draft":
            label, step = "继续会后报告", "sources"
        else:
            label, step = "核对发布", "review"
        yield _task("report", label, f"{base}/report#step={step}", owner=owner,
                    actionable=report_edit and status != "published", finished=status == "published")
    status = prep["status"]
    if status == "final":
        if not report.get("started") and report_edit and prep.get("meeting_date", "") <= today:
            yield _task("report", "上传逐字稿", base + "/report#step=sources", owner=owner)
        return
    if not can_edit:
        yield _task("prep", "查看会前准备（只读）", base + "/prep", owner=owner, actionable=False)
    elif status == "generating":
        yield _task("prep", "查看准备生成进度", base + "/prep", owner=owner)
    elif prep.get("current_version_id"):
        yield _task("prep", "去定稿", base + "/prep#step=review", owner=owner)
    else:
        yield _task("prep", "开始会前准备", base + "/prep#step=sources", owner=owner)


def _plan_task(plan):
    status = plan["status"]
    parent = plan.get("parent_status")
    step = {"generating": "internal", "review": "internal", "approved": "parent"}.get(status, "inputs")
    done = status == "approved" and parent == "exported" and not plan.get("parent_stale")
    editable = plan.get("can_edit", False)
    if not editable:
        label = "查看发展计划（只读）"
    elif status == "generating" or parent == "generating":
        label = "查看计划生成进度"
    elif status == "review":
        label = "审阅内部教案"
    elif status != "approved":
        label = "继续发展计划"
    elif done:
        label = "查看家长版发展计划"
    elif parent in ("draft", "confirmed") and not plan.get("can_approve"):
        return _task("plan", "查看家长版（待负责导师处理）",
                     f"/m1/plans/{plan['id']}#step=parent", owner="负责导师", actionable=False)
    elif plan.get("parent_stale"):
        label = "更新家长版发展计划"
    else:
        label = {"draft": "确认家长版发展计划", "confirmed": "导出家长版发展计划"}.get(
            parent, "生成家长版发展计划")
    return _task("plan", label, f"/m1/plans/{plan['id']}#step={step}",
                 owner="负责导师", actionable=editable and not done, finished=done)


def summarize(preps, plans, reports, *, report_allowed, today=None):
    today = (today or date.today()).isoformat()
    meetings = [task for prep in preps for task in _meeting_tasks(
        prep, reports.get(prep["id"], {}), report_allowed, today)]
    tasks = [t for t in meetings if t["kind"] == "report"] + [
        t for t in meetings if t["kind"] == "prep"]
    tasks.extend(_plan_task(plan) for plan in plans)
    ready_prep = next((prep for prep in preps if prep.get("can_edit")
                       and report_ready(reports.get(prep["id"]))), None)
    if ready_prep:
        tasks.append(_task("plan_create", "从会后报告创建发展计划",
                           f"/m1/plans?new={ready_prep['id']}", actionable=False))
    actionable = [task for task in tasks if task["actionable"]]
    alternatives = [task for task in tasks if task["kind"] in ("plan_create", "plan")]
    next_task = next(iter(actionable or alternatives or tasks), None)
    status = "todo" if actionable else "done" if any(task["finished"] for task in tasks) else "idle"
    return {"tasks": tasks, "next": next_task, "workflow_state": status}
