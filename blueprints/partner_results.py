"""Partner result reads and administrator-only release controls."""
from functools import wraps
from hmac import compare_digest

import click
from flask import Blueprint, g, jsonify, request, session

from app_utils import role_required
from partner_auth import require_partner
from partner_results import ReleaseError, deliver_due, read_result, release_result, revoke_result

bp = Blueprint("partner_results", __name__, cli_group=None)
_PUBLIC = "/api/partners/v1/y4/reservations/<reservation_id>/results/<version>"
_RELEASES = "/api/internal/partners/v1/y4/reservations/<reservation_id>/releases"


def _error(code, message, status):
    return jsonify({"ok": False, "code": code, "error": message}), status


def _csrf_required(view):
    @wraps(view)
    def checked(*args, **kwargs):
        expected = session.get("_csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not compare_digest(expected.encode("utf-8"), supplied.encode("utf-8")):
            return _error("FORBIDDEN", "Missing or invalid CSRF token", 403)
        return view(*args, **kwargs)
    return checked


@bp.get(_PUBLIC)
@require_partner("results")
def result(reservation_id, version):
    snapshot = read_result(g.partner_id, reservation_id, version)
    if snapshot is None:
        response, status = _error("NOT_FOUND", "Result not found", 404)
    else:
        response, status = jsonify({"ok": True, "result": snapshot}), 200
    response.headers["Cache-Control"] = "no-store"
    return response, status


@bp.post(_RELEASES)
@role_required("admin")
@_csrf_required
def approve_release(reservation_id):
    body = request.get_json(silent=True)
    required = {"partner_id", "round_id", "report_id", "approval_reference", "fields"}
    optional = {"include_assessment_date"}
    if not isinstance(body, dict) or not required <= body.keys() or body.keys() - required - optional:
        return _error("BAD_REQUEST", "Invalid release approval", 400)
    try:
        version, created = release_result(reservation_id=reservation_id,
                                          actor=session["user_id"], **body)
    except ReleaseError as exc:
        return _error(exc.code, str(exc), exc.status)
    return jsonify({"ok": True, "version": version}), 201 if created else 200


@bp.delete(_RELEASES + "/<version>")
@role_required("admin")
@_csrf_required
def withdraw_release(reservation_id, version):
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or body.keys() != {"partner_id"}
            or not isinstance(body["partner_id"], str) or not 0 < len(body["partner_id"]) <= 64):
        return _error("BAD_REQUEST", "Invalid partner ID", 400)
    if not revoke_result(body["partner_id"], reservation_id, version, actor=session["user_id"]):
        return _error("NOT_FOUND", "Result not found", 404)
    return jsonify({"ok": True})


@bp.cli.command("partner-y4-deliver")
@click.option("--limit", type=click.IntRange(1, 1000), default=25, show_default=True)
def deliver_partner_y4(limit):
    """Process eligible partner Y4 webhook events."""
    click.echo(f"Processed {deliver_due(limit=limit)} event(s).")
