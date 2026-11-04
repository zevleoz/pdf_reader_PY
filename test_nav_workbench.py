"""S4-GL3：工作台 指向新页面；问卷任务 出现在 工具 里，每个角色都能看到。"""
import app_utils


def _links(role):
    return {link["key"]: link["href"] for group in app_utils.nav_for_role(role) for link in group["links"]}


def test_workbench_link_points_to_new_page():
    for role in ("admin", "advisor", "viewer"):
        assert _links(role)["workspace"] == "/app/workbench", role


def test_questionnaire_tasks_link_for_every_role():
    for role in ("admin", "advisor", "viewer"):
        assert _links(role)["tools.tasks"] == "/app/questionnaires", role
