"""Partner-specific service credentials for the Y4 booking and result API."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from functools import wraps
from urllib.parse import urlsplit

from flask import g, jsonify, request

_LOG = logging.getLogger(__name__)
_SCOPES = frozenset({"booking", "results"})
_MAX_CONFIG_CHARS = 262_144
_PARTNER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_DIGEST = re.compile(r"[a-f0-9]{64}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")


def _scopes(values):
    if not isinstance(values, list) or any(not isinstance(s, str) or s not in _SCOPES for s in values):
        raise ValueError("invalid partner scopes")
    return frozenset(values)


def _is_https_callback(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        return (
            parsed.scheme == "https" and bool(host)
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
        )
    except ValueError:
        return False


def _configuration():
    """Read one config snapshot. Replacing the config file also revokes cached access across workers."""
    raw = os.environ.get("Y4_PARTNERS_JSON")
    file_path = os.environ.get("Y4_PARTNERS_FILE")
    if raw and file_path:
        raise ValueError("multiple partner sources")
    if file_path:
        with open(file_path, encoding="utf-8") as stream:
            raw = stream.read(_MAX_CONFIG_CHARS + 1)
        if not raw:
            raise ValueError("missing partner configuration")
    if raw and len(raw) > _MAX_CONFIG_CHARS:
        raise ValueError("partner configuration is too large")

    rows = json.loads(raw) if raw else []
    if not isinstance(rows, list):
        raise ValueError("partner configuration must contain a list")
    partners = {}
    credentials = {}
    global_token = os.environ.get("Y4_API_KEY", "")
    global_digest = hashlib.sha256(global_token.encode()).hexdigest() if global_token else None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid partner record")
        partner_id, enabled = row.get("id"), row.get("enabled")
        if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id) or partner_id in partners:
            raise ValueError("invalid or duplicate partner ID")
        if not isinstance(enabled, bool):
            raise ValueError("invalid partner state")
        name = row.get("name", partner_id)
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("invalid partner name")
        allowed = _scopes(row.get("scopes"))
        callback, secret = row.get("callback_url"), row.get("webhook_secret")
        if callback is not None or secret is not None:
            if (
                "results" not in allowed or not _is_https_callback(callback)
                or not isinstance(secret, str) or not 32 <= len(secret) <= 256
            ):
                raise ValueError("invalid partner callback")
        partner = {
            "id": partner_id,
            "name": name,
            "enabled": enabled,
            "scopes": allowed,
            "callback_url": callback,
            "webhook_secret": secret,
        }
        partners[partner_id] = partner

        keys = row.get("credentials")
        if not isinstance(keys, list):
            raise ValueError("invalid partner credentials")
        for key in keys:
            if not isinstance(key, dict):
                raise ValueError("invalid partner credential")
            digest = key.get("sha256")
            scopes = _scopes(key.get("scopes"))
            if (
                not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
                or digest in credentials or digest == global_digest
                or not scopes or not scopes <= allowed
            ):
                raise ValueError("invalid or duplicate partner credential")
            credentials[digest] = (partner_id, scopes)
    return partners, credentials


def get_partner(partner_id: str):
    """Resolve current operator-approved partner settings for outbound processing."""
    try:
        partners, _ = _configuration()
    except (ValueError, OSError):
        _LOG.warning("Y4 partner configuration is unavailable")
        return None
    partner = partners.get(partner_id)
    return partner if partner and partner["enabled"] else None


def require_partner(*allowed_scopes: str):
    """Require at least one allowed scope on a current, enabled partner credential."""
    def decorator(view):
        @wraps(view)
        def guarded(*args, **kwargs):
            if not request.is_secure:
                return jsonify(error="https_required"), 400
            try:
                partners, credentials = _configuration()
            except (ValueError, OSError):
                _LOG.warning("Y4 partner configuration is unavailable")
                return jsonify(error="partner_api_unavailable"), 503
            if not partners:
                return jsonify(error="partner_api_unavailable"), 503

            scheme, _, token = request.headers.get("Authorization", "").partition(" ")
            identity = None
            if scheme.lower() == "bearer" and _TOKEN.fullmatch(token):
                identity = credentials.get(hashlib.sha256(token.encode("ascii")).hexdigest())
            if identity is None or not partners[identity[0]]["enabled"]:
                response = jsonify(error="partner_auth_required")
                response.headers["WWW-Authenticate"] = 'Bearer realm="y4-partners"'
                return response, 401

            partner_id, scopes = identity
            if scopes.isdisjoint(allowed_scopes):
                return jsonify(error="partner_scope_required"), 403
            g.partner_id = partner_id
            g.partner_scopes = scopes
            return view(*args, **kwargs)
        return guarded
    return decorator
