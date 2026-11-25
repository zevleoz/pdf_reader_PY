"""幂等配置某办公室的默认测评师（按稳定用户 ID 落库，不按姓名或角色推断）。

用法：
    python scripts/configure_office_default_assessor.py --office 上海 --user-id 1
    python scripts/configure_office_default_assessor.py --office 上海 --username admin --grant-access

--username 只在本次解析用户 ID；落库仍是用户 ID，之后改显示名或登录名外的资料不受影响。
默认要求目标账号已启用测评师身份并获得该办公室授权；加 --grant-access 会为这个显式指定
的账号补上测评师身份和办公室授权，适合线上首次部署或历史账号尚未配置的情况。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
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
    parser.add_argument("--grant-access", action="store_true",
                        help="为该显式账号启用测评师身份并授予该办公室")
    args = parser.parse_args()

    office_id = _resolve_office(args.office)
    user_id = _resolve_user(args.user_id, args.username)
    try:
        result = _db.set_office_default_assessor(office_id, user_id,
                                                 grant_access=args.grant_access)
    except ValueError as exc:
        raise SystemExit(str(exc))
    user = _db.get_user_by_id(user_id) or {}
    print(f"已配置办公室 {office_id} 的默认测评师为用户 {user_id}"
          f"（{user.get('display_name') or user.get('username') or '未知账号'}）")
    if result["granted_assessor"]:
        print("已启用该账号的测评师身份")
    if result["granted_office"]:
        print("已授予该办公室")
    print("该办公室排班起点已设为 legacy；其他办公室与已有预约不变")

    start = date.today()
    cap = _db.slot_capacity_range(start, start + timedelta(days=6), office_id)
    values = sorted({v for slots in cap.values() for v in slots.values()})
    if values and max(values) > 0:
        print(f"未来 7 天该办公室可约容量：{values[0]} 至 {values[-1]}")
    else:
        print("警告：未来 7 天该办公室仍无可用容量，请检查账号启用状态与办公室授权")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
