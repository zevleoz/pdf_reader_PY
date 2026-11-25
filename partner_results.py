"""Partner Y4 releases and durable notifications, independent of formal PDFs."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select, update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db
import partner_auth
import partner_reservations
import y4_upload

_ALLOWED_FIELDS = frozenset({"value", "unit", "grade"})
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
_LEASE = timedelta(minutes=5)


class PartnerY4Release(db.Base):
    __tablename__ = "partner_y4_releases"
    __table_args__ = (UniqueConstraint("reservation_id", "approval_reference"),)

    id = Column(Integer, primary_key=True)
    version = Column(String(32), nullable=False, unique=True)
    reservation_id = Column(String(64), ForeignKey("partner_reservations.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    partner_id = Column(String(64), nullable=False)
    student_id = Column(Integer, nullable=False)
    round_id = Column(Integer, nullable=False)
    report_id = Column(Integer, nullable=False)
    approval_reference = Column(String(120), nullable=False)
    approved_by = Column(String(100), nullable=False)
    approved_at = Column(DateTime, nullable=False)
    approved_scope = Column(Text, nullable=False)
    result_json = Column(Text, nullable=False)
    revoked_by = Column(String(100))
    revoked_at = Column(DateTime)


class PartnerY4Event(db.Base):
    __tablename__ = "partner_y4_events"

    id = Column(String(32), primary_key=True)
    release_id = Column(Integer, ForeignKey("partner_y4_releases.id", ondelete="CASCADE"),
                        nullable=False, unique=True)
    body = Column(Text, nullable=False)
    state = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    due_at = Column(DateTime, nullable=False, index=True)
    lease_owner = Column(String(32))


class ReleaseError(ValueError):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code = code
        self.status = status


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":"))


def _partner(partner_id):
    partner = partner_auth.get_partner(partner_id)
    return partner if partner and "results" in partner["scopes"] else None


def _reservation(partner_id, reservation_id, *, sess=None):
    reservation = partner_reservations.get_reservation(partner_id, reservation_id, sess=sess)
    if reservation and reservation["student_id"] and reservation["status"] != "cancelled":
        return reservation
    return None


def _source(sess, student_id, round_id, report_id):
    """Resolve an explicit historical round and check the existing build evidence."""
    row = sess.get(y4_upload.Y4Round, round_id)
    record = sess.get(db.Report, report_id)
    if not row or not record or row.student_id != student_id or record.student_id != student_id:
        return None, False
    if row.report_id != report_id:
        return None, False
    rnd = y4_upload._round_dict(row)
    build = rnd["state"]["build"]
    built_at = build.get("built_at")
    path = build.get("v2_path")
    ready = bool(
        build.get("state") == "done" and built_at and path
        and record.pdf_path == path and y4_upload._abs(path).is_file()
        and any(slot.get("has_data") for slot in rnd["state"]["slots"].values())
        and not any((slot.get("read_at") or "") > built_at
                    for slot in rnd["state"]["slots"].values())
    )
    student = sess.get(db.Student, student_id)
    if not student:
        return None, False
    try:
        raw = json.loads(record.data_json or "{}")
    except (TypeError, ValueError):
        return None, False
    if not isinstance(raw, dict):
        return None, False
    ready = ready and not y4_upload.build_name_is_stale(build, raw, student.name)
    if ready:
        ready = sess.scalar(select(db.MeetingMinutes.id).where(
            db.MeetingMinutes.student_id == student_id,
            db.MeetingMinutes.report_id == report_id,
            func.trim(db.MeetingMinutes.minutes_text) != "",
        ).limit(1)) is not None
    return raw, ready


def _approved_scope(fields, include_assessment_date):
    if not isinstance(fields, dict) or not fields or len(fields) > 124:
        raise ReleaseError("BAD_REQUEST", "fields must map indicator codes to approved fields", 400)
    approved = {}
    for code, names in fields.items():
        if (not isinstance(code, str) or not _CODE.fullmatch(code)
                or not isinstance(names, list) or not names or len(names) > len(_ALLOWED_FIELDS)
                or any(not isinstance(name, str) or name not in _ALLOWED_FIELDS for name in names)
                or len(set(names)) != len(names)):
            raise ReleaseError("BAD_REQUEST", "Invalid indicator or approved field", 400)
        approved[code] = sorted(names)
    if not isinstance(include_assessment_date, bool):
        raise ReleaseError("BAD_REQUEST", "include_assessment_date must be a boolean", 400)
    return {"fields": approved, "include_assessment_date": include_assessment_date}


def _snapshot(raw, scope):
    from ai_client import _build_y4_payload
    from evaluation_rules import build_evaluation_view

    # The same evaluation and Y4 projection functions used by the existing export.
    items, _ = build_evaluation_view(raw.get("schema_124") or [])
    payload = _build_y4_payload(items, "", raw.get("student") or {})
    selected = {}
    for dimension in payload["dimensions"].values():
        for point in dimension["data_points"]:
            code = point["code"]
            if code not in scope["fields"]:
                continue
            if code in selected:
                raise ReleaseError("RESULT_NOT_READY", "Duplicate Y4 indicator", 409)
            fields = {}
            for key in scope["fields"][code]:
                value = point.get(key)
                if isinstance(value, str) and value.strip():
                    fields[key] = value
                elif key == "value" and type(value) in (int, float) and math.isfinite(value):
                    fields[key] = value
            if fields:
                selected[code] = {"code": code, **fields}
    if set(selected) != set(scope["fields"]):
        raise ReleaseError("BAD_REQUEST", "An approved indicator has no deliverable fields", 400)
    result = {"indicators": [selected[code] for code in sorted(selected)]}
    if scope["include_assessment_date"]:
        assessment_date = payload["meta"].get("test_date")
        try:
            result["assessment_date"] = date.fromisoformat(assessment_date).isoformat()
        except (TypeError, ValueError):
            pass
    return result


def _existing_release(sess, reservation_id, approval_reference, round_id, report_id, scope):
    release = sess.scalar(select(PartnerY4Release).filter_by(
        reservation_id=reservation_id, approval_reference=approval_reference))
    if release:
        if (release.revoked_at or release.round_id != round_id or release.report_id != report_id
                or release.approved_scope != scope):
            raise ReleaseError("RELEASE_CONFLICT", "Approval reference already used", 409)
        return release.version, False
    return None


def release_result(partner_id, reservation_id, round_id, report_id, approval_reference, fields,
                   include_assessment_date=False, *, actor):
    """Record an administrator's explicit field grant and enqueue one immutable version."""
    if (not isinstance(partner_id, str) or not partner_id or len(partner_id) > 64
            or type(round_id) is not int or not 0 < round_id <= 2147483647
            or type(report_id) is not int or not 0 < report_id <= 2147483647
            or not isinstance(approval_reference, str) or not approval_reference.strip()
            or len(approval_reference) > 120 or not approval_reference.isprintable()):
        raise ReleaseError("BAD_REQUEST", "Invalid partner, round, report or approval reference", 400)
    approval_reference = approval_reference.strip()
    scope = _approved_scope(fields, include_assessment_date)
    scope_json = _json(scope)
    partner = _partner(partner_id)
    if not partner:
        raise ReleaseError("NOT_FOUND", "Reservation or report not found", 404)
    with Session(db.engine) as sess:
        # Serialize linking and approving against the reservation on SQLite and PostgreSQL.
        locked = sess.execute(update(db.PartnerReservation).where(
            db.PartnerReservation.id == reservation_id,
            db.PartnerReservation.partner_id == partner_id,
        ).values(id=db.PartnerReservation.id)).rowcount
        reservation = _reservation(partner_id, reservation_id, sess=sess) if locked else None
        if not reservation:
            raise ReleaseError("NOT_FOUND", "Reservation or report not found", 404)
        existing = _existing_release(sess, reservation_id, approval_reference, round_id,
                                     report_id, scope_json)
        if existing:
            return existing
        linked = sess.execute(select(PartnerY4Release.round_id, PartnerY4Release.report_id)
                              .where(PartnerY4Release.reservation_id == reservation_id)
                              .order_by(PartnerY4Release.id).limit(1)).first()
        if linked is not None and linked != (round_id, report_id):
            raise ReleaseError("RELEASE_CONFLICT", "Reservation is linked to another assessment", 409)
        raw, ready = _source(sess, reservation["student_id"], round_id, report_id)
        if raw is None:
            raise ReleaseError("NOT_FOUND", "Reservation or report not found", 404)
        if not ready:
            raise ReleaseError("RESULT_NOT_READY", "Round is not ready for release", 409)
        if not partner.get("callback_url") or not partner.get("webhook_secret"):
            raise ReleaseError("RESULT_NOT_READY", "Partner callback is not configured", 409)
        version = uuid4().hex
        now = _now()
        release = PartnerY4Release(
            version=version, reservation_id=reservation_id, partner_id=partner_id,
            student_id=reservation["student_id"], round_id=round_id, report_id=report_id,
            approval_reference=approval_reference, approved_by=str(actor), approved_at=now,
            approved_scope=scope_json, result_json=_json({"version": version, **_snapshot(raw, scope)}),
        )
        event_id = uuid4().hex
        event = PartnerY4Event(id=event_id, due_at=now, body=_json({
            "type": "y4.result.ready", "event_id": event_id,
            "reservation_id": reservation_id,
            "external_reservation_id": reservation["external_reservation_id"], "version": version,
        }))
        try:
            sess.add(release)
            sess.flush()
            event.release_id = release.id
            sess.add(event)
            sess.commit()
        except IntegrityError:
            sess.rollback()
            existing = _existing_release(sess, reservation_id, approval_reference, round_id,
                                         report_id, scope_json)
            if existing:
                return existing
            raise
    return version, True


def revoke_result(partner_id, reservation_id, version, *, actor):
    with Session(db.engine) as sess:
        grant = sess.scalar(select(PartnerY4Release).filter_by(
            partner_id=partner_id, reservation_id=reservation_id, version=version))
        if not grant:
            return False
        sess.execute(update(PartnerY4Release).where(
            PartnerY4Release.id == grant.id, PartnerY4Release.revoked_at.is_(None)
        ).values(revoked_at=_now(), revoked_by=str(actor)))
        sess.execute(update(PartnerY4Event).where(
            PartnerY4Event.release_id == grant.id, PartnerY4Event.state == "pending"
        ).values(state="cancelled", lease_owner=None))
        sess.commit()
        return True


def _authorized(sess, grant, reservation):
    if (not grant or grant.revoked_at or not reservation
            or reservation["student_id"] != grant.student_id):
        return False
    _, ready = _source(sess, grant.student_id, grant.round_id, grant.report_id)
    return ready


def current_result_version(partner_id, reservation_id):
    if not _partner(partner_id):
        return None
    with Session(db.engine) as sess:
        reservation = _reservation(partner_id, reservation_id, sess=sess)
        if not reservation:
            return None
        grants = sess.scalars(select(PartnerY4Release).filter_by(
            partner_id=partner_id, reservation_id=reservation_id, revoked_at=None
        ).order_by(PartnerY4Release.id.desc()))
        return next((grant.version for grant in grants if _authorized(sess, grant, reservation)), None)


def read_result(partner_id, reservation_id, version):
    if not _partner(partner_id):
        return None
    with Session(db.engine) as sess:
        reservation = _reservation(partner_id, reservation_id, sess=sess)
        if not reservation:
            return None
        grant = sess.scalar(select(PartnerY4Release).filter_by(
            partner_id=partner_id, reservation_id=reservation_id, version=version))
        return json.loads(grant.result_json) if _authorized(sess, grant, reservation) else None


def _public_callback_target(url):
    parts = urlsplit(url)
    host = parts.hostname
    if (parts.scheme != "https" or not host or parts.username is not None
            or parts.password is not None or parts.fragment or parts.port not in (None, 443)
            or any(c.isspace() or ord(c) < 32 for c in url)
            or "\\" in url):
        raise ValueError("Invalid HTTPS callback URL")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Callback does not resolve")
    addresses = [ipaddress.ip_address(item[4][0]) for item in addresses]
    # Block translated, multicast and scoped addresses even when labelled global.
    if any(not ip.is_global or ip.is_multicast or ip.is_reserved
           or getattr(ip, "scope_id", None) or getattr(ip, "is_site_local", False)
           or getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
           or getattr(ip, "teredo", None) or ip in ipaddress.ip_network("64:ff9b::/96")
           for ip in addresses):
        raise ValueError("Callback resolves to a non-public address")
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    return host, str(addresses[0]), target


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, address):
        super().__init__(hostname, port=443, timeout=5, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _send_callback(url, secret, body):
    host, address, target = _public_callback_target(url)
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body,
                         hashlib.sha256).hexdigest()
    conn = _PinnedHTTPSConnection(host, address)
    try:
        conn.request("POST", target, body=body, headers={
            "Content-Type": "application/json",
            "X-Y4-Event-Timestamp": timestamp,
            "X-Y4-Event-Signature": f"sha256={signature}",
        })
        with conn.getresponse() as response:
            return 200 <= response.status < 300
    finally:
        conn.close()


def _claim_event():
    now = _now()
    owner = uuid4().hex
    with Session(db.engine) as sess:
        due = (PartnerY4Event.state == "pending", PartnerY4Event.due_at <= now)
        event_id = sess.scalar(select(PartnerY4Event.id).where(*due)
                               .order_by(PartnerY4Event.due_at, PartnerY4Event.id).limit(1))
        if not event_id:
            return None
        claimed = sess.execute(update(PartnerY4Event).where(PartnerY4Event.id == event_id, *due)
                               .values(due_at=now + _LEASE, lease_owner=owner)).rowcount
        sess.commit()
        return (event_id, owner) if claimed else None


def _deliver_event(event_id, owner):
    with Session(db.engine) as sess:
        event = sess.scalar(select(PartnerY4Event).filter_by(
            id=event_id, lease_owner=owner, state="pending"))
        if not event:
            return
        grant = sess.get(PartnerY4Release, event.release_id)
        if not grant or grant.revoked_at:
            return
        partner = _partner(grant.partner_id)
        reservation = _reservation(grant.partner_id, grant.reservation_id, sess=sess)
        authorized = _authorized(sess, grant, reservation)
        body = event.body.encode("utf-8")
        attempts = event.attempts + 1
    sent = False
    if authorized and partner and partner.get("callback_url") and partner.get("webhook_secret"):
        try:
            sent = _send_callback(partner["callback_url"], partner["webhook_secret"], body)
        except (OSError, ValueError, http.client.HTTPException):
            pass
    delay = timedelta(seconds=min(3600, 30 * 2 ** min(attempts - 1, 7)))
    with Session(db.engine) as sess:
        sess.execute(update(PartnerY4Event).where(
            PartnerY4Event.id == event_id, PartnerY4Event.lease_owner == owner,
            PartnerY4Event.state == "pending"
        ).values(state="sent" if sent else "pending", attempts=attempts,
                 due_at=_now() + delay, lease_owner=None))
        sess.commit()


def deliver_due(*, limit=25):
    """Claim and process due outbox items. Unfinished leases expire after five minutes."""
    for processed in range(limit):
        claimed = _claim_event()
        if not claimed:
            return processed
        _deliver_event(*claimed)
    return limit
