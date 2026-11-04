"""S4-GL2：Profiling 流程 出现在每个角色的导航里，指向 /app/flow。"""
import app_utils


def test_flow_link_for_every_role():
    for role in ("admin", "advisor", "viewer"):
        hrefs = [link["href"] for group in app_utils.nav_for_role(role) for link in group["links"]]
        assert "/app/flow" in hrefs, role


def test_flow_link_sits_after_students():
    group = next(g for g in app_utils.ADMIN_NAV if g["key"] == "students")
    assert [link["key"] for link in group["links"]] == ["students", "flow"]
