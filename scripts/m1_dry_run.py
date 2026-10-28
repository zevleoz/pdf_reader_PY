"""M1 生成 dry run：在临时库副本上用真实模型跑一次 ``pipeline.generate``。

用法（仓库根目录）::

    python3 scripts/m1_dry_run.py --student 12 \\
        --parent 家长反馈.txt --case-review 案例讨论.txt --other 其他资料.md

    python3 scripts/m1_dry_run.py --prep 8 --out /tmp/m1_doc.json --keep

- 只读取 ``data/y4_students.db`` 并复制到临时目录，``DATABASE_URL`` 指向副本；
- 资料用 ``--parent/--case-review/--other/--first-touch-extra`` 传入文件（txt/md/pdf/docx）；
- 需要真实模型：设置 ``DASHSCOPE_API_KEY``（或 ``FT_LLM_API_KEY``）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

CATEGORY_FLAGS = (
    ("parent", "parent", "家长初始反馈"),
    ("case_review", "case_review", "Case Review"),
    ("other", "other", "其他资料"),
    ("first_touch_extra", "first_touch_extra", "补充 First Touch"),
)


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="M1 生成 dry run（临时库副本）")
    parser.add_argument("--student", type=int, help="学生 id；与 --prep 二选一")
    parser.add_argument("--prep", type=int, help="已有会前准备 id")
    parser.add_argument("--db", default=str(BASE_DIR / "data" / "y4_students.db"),
                        help="真实库路径（只读复制）")
    parser.add_argument("--duration", type=int, default=60, choices=(60, 75, 90))
    parser.add_argument("--out", help="把生成的 doc JSON 写到这个路径")
    parser.add_argument("--keep", action="store_true", help="保留临时库目录")
    for key, _category, label in CATEGORY_FLAGS:
        parser.add_argument("--%s" % key.replace("_", "-"), action="append",
                            default=[], metavar="FILE", help="%s文件" % label)
    return parser.parse_args(argv)


def _copy_db(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit("找不到数据库：%s" % source)
    shutil.copy2(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix.lower() in (".txt", ".md", ".markdown", ".text"):
        return data.decode("utf-8", errors="replace")
    from growth_talk.upload import extract_upload
    return extract_upload(path.name, data)


def main(argv=None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.student and not args.prep:
        raise SystemExit("请给 --student 或 --prep")

    source_db = Path(args.db).resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="m1_dry_run_"))
    target_db = temp_dir / "dryrun.db"
    _copy_db(source_db, target_db)
    os.environ["DATABASE_URL"] = "sqlite:///%s" % target_db

    import db
    import m1.pipeline as pipeline
    import m1.sources as sources
    import m1.store as store

    db.init_db()  # 导入 m1.store 后建表；只作用于临时副本

    prep = store.get_prep(args.prep) if args.prep else None
    if prep is None and args.prep:
        raise SystemExit("找不到 prep：%s" % args.prep)
    if prep is None:
        existing = [row for row in store.list_preps(
                        user={"user_id": None, "role": "admin",
                              "advisor_name": "", "display_name": ""},
                        student_id=args.student)
                    if row["status"] != "final"]
        prep = existing[0] if existing else store.create_prep(
            args.student, duration=args.duration, meeting_date="")
    print("prep #%s 学生 #%s 状态 %s" % (prep["id"], prep["student_id"], prep["status"]))
    print("临时库：%s" % target_db)

    for flag, category, label in CATEGORY_FLAGS:
        for name in getattr(args, flag):
            path = Path(name)
            try:
                text = _read_text(path)
            except Exception as exc:
                raise SystemExit("无法读取 %s：%s" % (path, exc))
            sources.add_text(prep["id"], text, category)
            print("已加入%s：%s（%d 字）" % (label, path.name, len(text)))

    def progress(step, state, seconds):
        print("  [%s] %s %.1fs" % (step, state, seconds))

    try:
        version_id = pipeline.generate(prep["id"], progress=progress)
    except Exception as exc:
        print("生成失败：%s" % exc, file=sys.stderr)
        print("临时库保留在：%s" % temp_dir, file=sys.stderr)
        return 1

    version = store.get_version(version_id) or {}
    doc = version.get("doc") or {}
    print("ai_draft 版本 #%s；状态 %s" % (version_id, store.get_prep(prep["id"])["status"]))
    print("证据 %d 条；优先能力 %d 项；事件 %d 个；备用问题 %d 条" % (
        len(version.get("evidence") or []), len(doc.get("priority") or []),
        len(doc.get("events") or []), len(doc.get("backups") or [])))
    print("flags：%s" % json.dumps(doc.get("flags") or {}, ensure_ascii=False))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print("doc 已写出：%s" % out_path.resolve())
    else:
        fallback = temp_dir / "m1_doc.json"
        fallback.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print("doc：%s" % fallback)

    if args.keep:
        print("临时库保留在：%s" % temp_dir)
    else:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
