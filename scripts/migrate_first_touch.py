#!/usr/bin/env python3
"""first-touch 历史数据迁移（Neon 导出 JSON → 本平台 SQLite/PG）。

输入契约：``<export_dir>/<Entity>.json``，每个实体一个 JSON 数组文件，
字段沿用 Prisma camelCase。支持 ``Account.json`` / ``account.json`` /
``accounts.json`` 这类大小写与复数差异。脚本内做 camelCase → snake_case。

用法：
    # 1) 生成对照表（默认未匹配 → create；同名多候选 → skip）
    python scripts/migrate_first_touch.py preview <export_dir> --out mapping.csv

    # 2) 人工确认 CSV（可把 create 改成 link/skip、补 y4_student_id）后导入
    python scripts/migrate_first_touch.py run <export_dir> --mapping mapping.csv

幂等：以 ``external_identities(source_system="first-touch-migration",
external_student_id=<first-touch Student.id>)`` 判定；已存在即整学生跳过。
每个学生导入后写一条 ``migration_import`` 审计。

账号密码：源库密码为 bcrypt，本平台用 werkzeug 哈希，二者不兼容。
迁移只保留账号资料，密码置为不可用的随机值，导入后需由管理员重置。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import db as _db  # noqa: E402
import growth_talk_store as store  # noqa: E402

MIGRATION_SYSTEM = "first-touch-migration"

MAPPING_COLUMNS = [
    "ft_student_id", "ft_name", "ft_grade", "y4_student_id",
    "y4_name", "y4_code", "match_confidence", "action",
]

_ENTITY_NAMES = (
    "Account", "Student", "SourceMaterial", "GrowthTalkRun",
    "MeetingUnderstanding", "InterestEvidence", "QuadrantAnalysis",
    "ExplorationSuggestion", "GrowthTalkReport",
    "StudentExternalIdentity", "AuditLog",
)

# 实体名归一化键（去大小写/下划线/连字符），避免手写拼写错误。
_ENTITY_KEYS = {
    "".join(ch for ch in name.lower() if ch.isalnum()): name
    for name in _ENTITY_NAMES
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _norm_stem(stem: str) -> str:
    return "".join(ch for ch in stem.lower() if ch.isalnum())


def _dt(value):
    """Prisma ISO 字符串 → 本地 DateTime 列（naive UTC）。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _iso(value):
    """保留原 ISO 字符串，供 VARCHAR 时间戳列使用。"""
    if value is None:
        return None
    return str(value)[:32]


def _text(value, default: str = "") -> str:
    return default if value is None else str(value)


def _map_role(value) -> str:
    role = _text(value).strip().upper()
    if role == "ADMIN":
        return "admin"
    if role in ("TEACHER", "ADVISOR"):
        return "advisor"
    return "viewer"


# ---------------------------------------------------------------------------
# 读取导出
# ---------------------------------------------------------------------------
def load_export(export_dir) -> dict:
    """读取 export_dir 下全部实体 JSON，返回 {Entity: [row, ...]}。"""
    export_dir = Path(export_dir)
    if not export_dir.is_dir():
        raise SystemExit(f"[migration] 导出目录不存在: {export_dir}")
    data = {name: [] for name in _ENTITY_NAMES}
    seen = set()
    for path in sorted(export_dir.glob("*.json")):
        key = _norm_stem(path.stem)
        entity = _ENTITY_KEYS.get(key)
        if entity is None and key.endswith("s"):
            entity = _ENTITY_KEYS.get(key[:-1])
        if entity is None:
            print(f"[migration] 忽略未知文件: {path.name}", flush=True)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SystemExit(f"[migration] {path.name} 必须是 JSON 数组")
        data[entity].extend(payload)
        seen.add(entity)
    missing = [name for name in _ENTITY_NAMES if name not in seen]
    if missing:
        print(f"[migration] 未提供的实体视为空: {', '.join(missing)}", flush=True)
    return data


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------
def build_preview(export_data: dict) -> list[dict]:
    """按「姓名 + 年级」匹配本平台学生，生成对照行。"""
    with Session(_db.engine) as sess:
        locals_ = sess.execute(select(_db.Student)).scalars().all()
    by_name: dict[str, list] = {}
    for st in locals_:
        by_name.setdefault((st.name or "").strip(), []).append(st)

    rows = []
    for st in export_data.get("Student", []):
        ft_id = str(st.get("id") or "").strip()
        name = (st.get("name") or "").strip()
        grade = (st.get("grade") or "").strip()
        if not ft_id or not name:
            rows.append({
                "ft_student_id": ft_id, "ft_name": name, "ft_grade": grade,
                "y4_student_id": "", "y4_name": "", "y4_code": "",
                "match_confidence": "none", "action": "skip",
            })
            continue
        matches = by_name.get(name, [])
        if grade:
            matches = [m for m in matches if (m.grade or "").strip() == grade]
        if len(matches) == 1:
            hit = matches[0]
            rows.append({
                "ft_student_id": ft_id, "ft_name": name, "ft_grade": grade,
                "y4_student_id": str(hit.id), "y4_name": hit.name or "",
                "y4_code": hit.student_code or "",
                "match_confidence": "high" if grade else "medium",
                "action": "link",
            })
        elif len(matches) > 1:
            rows.append({
                "ft_student_id": ft_id, "ft_name": name, "ft_grade": grade,
                "y4_student_id": "", "y4_name": "", "y4_code": "",
                "match_confidence": "ambiguous", "action": "skip",
            })
        else:
            rows.append({
                "ft_student_id": ft_id, "ft_name": name, "ft_grade": grade,
                "y4_student_id": "", "y4_name": "", "y4_code": "",
                "match_confidence": "none", "action": "create",
            })
    return rows


def write_mapping(out_path, rows: list[dict]) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=MAPPING_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in MAPPING_COLUMNS})


def preview(export_dir, out_path) -> list[dict]:
    rows = build_preview(load_export(export_dir))
    write_mapping(out_path, rows)
    counts = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    print(f"[migration] 对照表已写入 {out_path}: {counts}", flush=True)
    return rows


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def _read_mapping(mapping_path) -> list[dict]:
    with Path(mapping_path).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _import_accounts(accounts: list[dict], summary: dict) -> dict:
    """导入账号资料，返回 first-touch account id → 本地 user id。"""
    mapping: dict[str, int] = {}
    with Session(_db.engine) as sess:
        for acc in accounts:
            ft_id = str(acc.get("id") or "").strip()
            email = (acc.get("email") or "").strip().lower()
            if not ft_id or not email:
                summary["warnings"].append(f"账号字段不完整，跳过: {ft_id or '?'}")
                continue
            existing = sess.execute(
                select(_db.User).where(func.lower(_db.User.email) == email)
            ).scalar_one_or_none()
            if existing:
                mapping[ft_id] = existing.id
                summary["accounts"]["skipped"].append(
                    {"id": ft_id, "email": email, "reason": "email_exists"})
                continue
            if sess.execute(
                select(_db.User.id).where(
                    func.lower(_db.User.username) == email)
            ).first():
                summary["accounts"]["skipped"].append(
                    {"id": ft_id, "email": email, "reason": "username_exists"})
                continue
            name = _text(acc.get("name")).strip() or email
            row = _db.User(
                username=email,
                password_hash=generate_password_hash(os.urandom(24).hex()),
                role=_map_role(acc.get("role")),
                advisor_name=name,
                display_name=name,
                email=email,
                is_active=1 if acc.get("active", True) else 0,
            )
            sess.add(row)
            sess.flush()
            mapping[ft_id] = row.id
            summary["accounts"]["imported"] += 1
        sess.commit()
    if summary["accounts"]["imported"]:
        summary["warnings"].append(
            "导入账号的密码已重置为随机值（源 bcrypt 哈希与本平台不兼容），请管理员重置")
    return mapping


def _create_student(sess, st: dict, account_map: dict) -> int:
    teacher_id = str(st.get("assignedTeacherId") or "")
    teacher = account_map.get(teacher_id)
    advisor = ""
    if teacher:
        user = sess.get(_db.User, teacher)
        advisor = (user.display_name or user.advisor_name or "") if user else ""
    row = _db.Student(
        student_code=_db.next_student_code(sess),
        name=_text(st.get("name")).strip(),
        grade=_text(st.get("grade")),
        school=_text(st.get("school")),
        phone=_text(st.get("phone")),
        advisor_name=advisor,
    )
    sess.add(row)
    sess.flush()
    return row.id


def _insert_source(sess, row: dict, sid: int):
    src = store.GtSource(
        student_id=sid,
        type=_text(row.get("type"), "GROWTH_TALK"),
        purpose=_text(row.get("purpose"), "UNKNOWN"),
        source_kind=_text(row.get("sourceKind"), _text(row.get("type"), "GROWTH_TALK")),
        title=_text(row.get("title"), "未命名资料"),
        content=_text(row.get("content")),
        mime_type=row.get("mimeType"),
        file_name=row.get("fileName"),
        original_path=row.get("originalPath"),
        file_size=row.get("fileSize"),
        source_format=row.get("sourceFormat"),
        external_report_id=row.get("externalReportId"),
        external_student_id=row.get("externalStudentId"),
        external_version=row.get("externalVersion"),
        external_status=row.get("externalStatus"),
        external_confirmed_at=_iso(row.get("externalConfirmedAt")),
        external_confirmed_by=row.get("externalConfirmedBy"),
        structured_payload=row.get("structuredPayload"),
        extracted_text=row.get("extractedText"),
        extraction_status=_text(row.get("extractionStatus"), "EXTRACTED"),
        key_points_draft=row.get("keyPointsDraft"),
        key_points_confirmed=row.get("keyPointsConfirmed"),
        confirmed_at=_iso(row.get("confirmedAt")),
        confirmed_by_name=row.get("confirmedByName"),
        created_at=_dt(row.get("createdAt")),
    )
    sess.add(src)
    sess.flush()
    return src


def _insert_run(sess, row: dict, sid: int, source_id: int):
    run = store.GtRun(
        student_id=sid, source_id=source_id,
        version=int(row.get("version") or 1),
        revision=int(row.get("revision") or 1),
        status=_text(row.get("status"), "DRAFT"),
        error=row.get("error"), model=row.get("model"),
        created_at=_dt(row.get("createdAt")),
        updated_at=_dt(row.get("updatedAt")),
    )
    sess.add(run)
    sess.flush()
    return run


def _import_student(sess, sid: int, ft_id: str, export_data: dict,
                    account_map: dict, summary: dict) -> dict:
    """在调用方事务内写入单个学生的全部历史数据，返回计数。"""
    counts = {"sources": 0, "runs": 0, "reports": 0}
    # 资料
    source_map = {}
    for row in export_data.get("SourceMaterial", []):
        if str(row.get("studentId")) != ft_id:
            continue
        src = _insert_source(sess, row, sid)
        source_map[str(row.get("id"))] = src.id
    counts["sources"] = len(source_map)

    # 分析运行（版本冲突则跳过该 run 及其子表/报告）
    run_map = {}
    existing_versions = set(sess.execute(
        select(store.GtRun.version).where(store.GtRun.student_id == sid)
    ).scalars())
    for row in export_data.get("GrowthTalkRun", []):
        if str(row.get("studentId")) != ft_id:
            continue
        version = int(row.get("version") or 1)
        source_id = source_map.get(str(row.get("sourceId")))
        if source_id is None:
            summary["warnings"].append(
                f"run {row.get('id')} 找不到资料，跳过")
            continue
        if version in existing_versions:
            summary["warnings"].append(
                f"run {row.get('id')} 版本 {version} 已存在，跳过")
            continue
        run = _insert_run(sess, row, sid, source_id)
        run_map[str(row.get("id"))] = run.id
        existing_versions.add(version)
        counts["runs"] += 1

    # 子表
    for row in export_data.get("MeetingUnderstanding", []):
        local_run = run_map.get(str(row.get("runId")))
        if local_run is None:
            continue
        sess.add(store.GtUnderstanding(
            run_id=local_run,
            summary=_text(row.get("summary"), "（无摘要）"),
            topics=_text(row.get("topics"), "[]"),
            keywords=_text(row.get("keywords"), "[]"),
            model=row.get("model"),
            status=_text(row.get("status"), "PENDING_REVIEW"),
            created_at=_dt(row.get("createdAt")),
            updated_at=_dt(row.get("updatedAt")),
        ))
    for row in export_data.get("InterestEvidence", []):
        local_run = run_map.get(str(row.get("runId")))
        if local_run is None:
            continue
        sess.add(store.GtInterest(
            run_id=local_run,
            label=_text(row.get("label"), "（未命名）"),
            subtopic=row.get("subtopic"),
            evidence=_text(row.get("evidence")),
            source_round=row.get("sourceRound"),
            evidence_strength=row.get("evidenceStrength"),
            uncertainty=row.get("uncertainty"),
            preference_score=row.get("preferenceScore"),
            competence_score=row.get("competenceScore"),
            special_focus=bool(row.get("specialFocus")),
            status=_text(row.get("status"), "PENDING_REVIEW"),
            confirmed_at=_iso(row.get("confirmedAt")),
            confirmed_by=row.get("confirmedBy"),
            created_at=_dt(row.get("createdAt")),
            updated_at=_dt(row.get("updatedAt")),
        ))
    for row in export_data.get("QuadrantAnalysis", []):
        local_run = run_map.get(str(row.get("runId")))
        if local_run is None:
            continue
        sess.add(store.GtQuadrant(
            run_id=local_run,
            points=_text(row.get("points"), "[]"),
            narrative=_text(row.get("narrative")),
            status=_text(row.get("status"), "DRAFT"),
            model=row.get("model"),
            created_at=_dt(row.get("createdAt")),
            updated_at=_dt(row.get("updatedAt")),
        ))
    for row in export_data.get("ExplorationSuggestion", []):
        local_run = run_map.get(str(row.get("runId")))
        if local_run is None:
            continue
        sess.add(store.GtSuggestion(
            run_id=local_run,
            title=_text(row.get("title"), "（未命名建议）"),
            introduction=_text(row.get("introduction")),
            growth_value=_text(row.get("growthValue")),
            possible_outputs=_text(row.get("possibleOutputs"), "[]"),
            recommendation_basis=row.get("recommendationBasis"),
            interest_refs=_text(row.get("interestRefs"), "[]"),
            exploration_tags=_text(row.get("explorationTags"), "[]"),
            status=_text(row.get("status"), "DRAFT"),
            created_at=_dt(row.get("createdAt")),
            updated_at=_dt(row.get("updatedAt")),
        ))

    # 报告
    existing_report_versions = set(sess.execute(
        select(store.GtReport.version)
        .where(store.GtReport.student_id == sid)
    ).scalars())
    for row in export_data.get("GrowthTalkReport", []):
        if str(row.get("studentId")) != ft_id:
            continue
        local_run = run_map.get(str(row.get("runId")))
        if local_run is None:
            summary["warnings"].append(
                f"报告 {row.get('id')} 找不到对应 run，跳过")
            continue
        version = int(row.get("version") or 1)
        if version in existing_report_versions:
            summary["warnings"].append(
                f"报告 {row.get('id')} 版本 {version} 已存在，跳过")
            continue
        sess.add(store.GtReport(
            student_id=sid, run_id=local_run, version=version,
            status=_text(row.get("status"), "DRAFT"),
            payload=_text(row.get("payload"), "{}"),
            confirmed_at=_iso(row.get("confirmedAt")),
            confirmed_by=row.get("confirmedBy"),
            created_at=_dt(row.get("createdAt")),
        ))
        existing_report_versions.add(version)
        counts["reports"] += 1

    # 外部身份（源系统自带）
    for row in export_data.get("StudentExternalIdentity", []):
        if str(row.get("studentId")) != ft_id:
            continue
        system = _text(row.get("sourceSystem")).strip()
        external_id = _text(row.get("externalStudentId")).strip()
        if not system or not external_id:
            continue
        exists = sess.execute(
            select(store.ExternalIdentity.id).where(
                store.ExternalIdentity.source_system == system,
                store.ExternalIdentity.external_student_id == external_id,
            )
        ).first()
        if exists:
            continue
        sess.add(store.ExternalIdentity(
            student_id=sid, source_system=system,
            external_student_id=external_id,
        ))

    # 历史审计
    for row in export_data.get("AuditLog", []):
        if str(row.get("studentId")) != ft_id:
            continue
        actor = account_map.get(str(row.get("actorId") or ""))
        sess.add(store.AuditLog(
            actor_id=actor, student_id=sid,
            action=_text(row.get("action"), "unknown"),
            details=_text(row.get("details"), "{}"),
            created_at=_dt(row.get("createdAt")),
        ))

    # 迁移幂等标记 + 本次审计
    sess.add(store.ExternalIdentity(
        student_id=sid, source_system=MIGRATION_SYSTEM,
        external_student_id=ft_id,
        details=json.dumps({"source": "first-touch",
                            "exportedAt": datetime.utcnow().isoformat()}),
    ))
    sess.add(store.AuditLog(
        actor_id=None, student_id=sid, action="migration_import",
        details=json.dumps({
            "source": "first-touch", "externalStudentId": ft_id,
            "sources": len(source_map), "runs": len(run_map),
        }, ensure_ascii=False),
    ))
    return counts


def run(export_dir, mapping_path) -> dict:
    export_data = load_export(export_dir)
    mapping_rows = _read_mapping(mapping_path)

    summary = {
        "accounts": {"imported": 0, "skipped": []},
        "students": {"linked": 0, "created": 0, "skipped": 0},
        "sources": 0, "runs": 0, "reports": 0,
        "warnings": [],
    }
    account_map = _import_accounts(export_data.get("Account", []), summary)

    students_by_ft = {}
    for st in export_data.get("Student", []):
        ft_id = str(st.get("id") or "").strip()
        if ft_id:
            students_by_ft[ft_id] = st
    mapping_by_ft = {}
    for row in mapping_rows:
        ft_id = (row.get("ft_student_id") or "").strip()
        if ft_id and ft_id not in mapping_by_ft:
            mapping_by_ft[ft_id] = row

    for ft_id, st in students_by_ft.items():
        mapped = mapping_by_ft.get(ft_id)
        if mapped is None:
            summary["warnings"].append(f"对照表缺少学生 {ft_id}，跳过")
            continue
        action = (mapped.get("action") or "skip").strip().lower()
        if action == "skip":
            summary["students"]["skipped"] += 1
            continue
        if store.find_student_by_external(MIGRATION_SYSTEM, ft_id):
            summary["students"]["skipped"] += 1
            continue
        if action not in ("link", "create"):
            summary["warnings"].append(
                f"学生 {ft_id} action 非法: {action}，跳过")
            continue

        raw_sid = (mapped.get("y4_student_id") or "").strip()
        if action == "link" and not raw_sid.isdigit():
            summary["warnings"].append(
                f"学生 {ft_id} link 缺少合法 y4_student_id，跳过")
            print(f"[migration] 学生 {ft_id} link 缺少合法 y4_student_id，跳过",
                  flush=True)
            continue

        # 建档与数据导入同一事务：失败则整体回滚，重跑不会产生重复学生。
        try:
            with Session(_db.engine) as sess:
                if action == "link":
                    sid = int(raw_sid)
                    if sess.get(_db.Student, sid) is None:
                        summary["warnings"].append(
                            f"学生 {ft_id} 指向的本地学生 {sid} 不存在，跳过")
                        continue
                else:
                    sid = _create_student(sess, st, account_map)
                counts = _import_student(sess, sid, ft_id, export_data,
                                         account_map, summary)
                sess.commit()
        except Exception as exc:  # 单学生失败不影响其余学生
            summary["warnings"].append(f"学生 {ft_id} 导入失败: {exc}")
            print(f"[migration] 学生 {ft_id} 导入失败: {exc}", flush=True)
            continue

        summary["students"]["linked" if action == "link" else "created"] += 1
        for key in ("sources", "runs", "reports"):
            summary[key] += counts[key]

    print("[migration] 导入完成: " + json.dumps({
        "accounts": summary["accounts"]["imported"],
        "linked": summary["students"]["linked"],
        "created": summary["students"]["created"],
        "skipped": summary["students"]["skipped"],
        "sources": summary["sources"], "runs": summary["runs"],
        "reports": summary["reports"],
        "warnings": len(summary["warnings"]),
    }, ensure_ascii=False), flush=True)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="first-touch 历史数据迁移")
    sub = parser.add_subparsers(dest="command", required=True)

    p_preview = sub.add_parser("preview", help="生成学生对照 CSV")
    p_preview.add_argument("export_dir")
    p_preview.add_argument("--out", required=True)

    p_run = sub.add_parser("run", help="按确认后的 CSV 导入数据")
    p_run.add_argument("export_dir")
    p_run.add_argument("--mapping", required=True)

    args = parser.parse_args(argv)
    if args.command == "preview":
        preview(args.export_dir, args.out)
    else:
        run(args.export_dir, args.mapping)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
