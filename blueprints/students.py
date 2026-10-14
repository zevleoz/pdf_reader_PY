"""学生蓝图：学生列表 / 报告列表 / 重命名 / 删除。"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

import db as _db
from app_utils import (admin_required, page_login_required, student_scoped,
                       _advisor_scope)

bp = Blueprint("students", __name__)


@bp.route("/students")
@page_login_required
def students_page():
    return render_template("students.html")


@bp.route("/api/students")
@admin_required
def api_students():
    students = _db.get_students(_advisor_scope())
    return jsonify({"ok": True, "students": students})


@bp.route("/api/students/<int:student_id>/reports")
@admin_required
@student_scoped
def api_student_reports(student_id):
    reports = _db.get_student_reports(student_id)
    return jsonify({"ok": True, "reports": reports})
@bp.route("/api/students/<int:student_id>", methods=["PUT"])
@admin_required
@student_scoped
def api_rename_student(student_id):
    """更新学生档案字段（姓名/学校/顾问，均可选，至少提供一项）。"""
    data = request.get_json(silent=True) or {}
    updates = {}
    if "name" in data:
        new_name = (data.get("name") or "").strip()
        if not new_name:
            return jsonify({"ok": False, "error": "姓名不能为空"}), 400
        updates["name"] = new_name
    if "school" in data:
        updates["school"] = (data.get("school") or "").strip()
    if "advisor_name" in data:
        updates["advisor_name"] = (data.get("advisor_name") or "").strip()
    if not updates:
        return jsonify({"ok": False, "error": "未提供任何修改字段"}), 400
    sess = _db.Session(_db.engine)
    try:
        student = sess.get(_db.Student, student_id)
        if not student:
            return jsonify({"ok": False, "error": "学生不存在"}), 404
        for k, v in updates.items():
            setattr(student, k, v)
        sess.commit()
        return jsonify({"ok": True, "student": {
            "id": student.id, "name": student.name,
            "grade": student.grade, "gender": student.gender,
            "school": student.school, "advisor_name": student.advisor_name
        }})
    except Exception as e:
        sess.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        sess.close()


@bp.route("/api/students/<int:student_id>", methods=["DELETE"])
@admin_required
@student_scoped
def api_delete_student(student_id):
    try:
        _db.delete_student(student_id)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
