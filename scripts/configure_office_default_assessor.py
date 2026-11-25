"""幂等配置某办公室的默认测评师（按稳定用户 ID 落库，不按姓名或角色推断）。

用法：
    python scripts/configure_office_default_assessor.py --office 上海 --user-id 1
    python scripts/configure_office_default_assessor.py --office 上海 --username admin

--username 只在本次解析用户 ID；落库仍是用户 ID，之后改显示名或登录名外的资料不受影响。
要求目标账号已在用户管理中启用测评师身份并获得该办公室授权。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as _db  # noqa: E402


def _resolve_office(raw: str) -> int:
    raw = (raw or "").strip()
    locations = _db.list_locations(active_only=True)
    if raw.isdigit():
        office_id = int(raw)
        if any(loc["id"] == office_id for loc in locations):
            return office_id
        raise SystemExit(f"办公室 id {office_id} 不存在或已停用")
    matched = [loc for loc in locations if loc["name"] == raw]
    if len(matched) != 1:
        raise SystemExit(f"找不到唯一匹配的办公室：{raw}")
    return int(matched[0]["id"])


def _resolve_user(raw_id: str | None, raw_name: str | None) -> int:
    if raw_id:
        return int(raw_id)
    user = _db.get_user_by_username(raw_name or "")
    if not user:
        raise SystemExit(f"找不到登录名为 {raw_name} 的账号")
    return int(user["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="配置办公室默认测评师")
    parser.add_argument("--office", required=True, help="办公室名称或 id，例如 上海")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", help="目标账号的稳定用户 ID")
    group.add_argument("--username", help="目标账号登录名（仅用于本次解析）")
    args = parser.parse_args()

    office_id = _resolve_office(args.office)
    user_id = _resolve_user(args.user_id, args.username)
    try:
        _db.set_office_default_assessor(office_id, user_id)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f"已配置办公室 {office_id} 的默认测评师为用户 {user_id}")
    print("该办公室排班起点已设为 legacy；其他办公室与已有预约不变")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
