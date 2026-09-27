"""Opaque, integrity-protected keyset cursors (guide 05 §14).

A cursor carries: version, endpoint, filter fingerprint, caller ID, the first page's upper-bound
time, issue time, and the last sort tuple. It is HMAC-signed with a key derived from JWT_SECRET for
this purpose only, and holds no names, notes or tokens. It never replaces authorization: every
page re-applies the caller's current assignment scope.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.core.errors import ApiError

CURSOR_VERSION = 1


def _key() -> bytes:
    secret = get_settings().JWT_SECRET.get_secret_value().encode()
    return hmac.new(secret, b"pagination-cursor-signing-v1", hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def fingerprint(filters: dict[str, Any]) -> str:
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def invalid_cursor() -> ApiError:
    return ApiError(400, "INVALID_CURSOR", "This page link is no longer valid. Refresh to start again.")


@dataclass(frozen=True)
class CursorState:
    upper_bound: datetime
    last: list[str]


def encode(
    endpoint: str, filters: dict[str, Any], caller_id: uuid.UUID, upper_bound: datetime, last: list[str]
) -> str:
    body = {
        "v": CURSOR_VERSION,
        "ep": endpoint,
        "fp": fingerprint(filters),
        "uid": str(caller_id),
        "ub": upper_bound.isoformat(),
        "iat": int(time.time()),
        "k": last,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def decode(token: str, endpoint: str, filters: dict[str, Any], caller_id: uuid.UUID) -> CursorState:
    """Validate signature first, then version/endpoint/filters/caller/age. Never echoes contents."""
    try:
        payload, sig = token.split(".", 1)
        expected = _b64(hmac.new(_key(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("signature")
        body = json.loads(_unb64(payload))
        ok = (
            body["v"] == CURSOR_VERSION
            and body["ep"] == endpoint
            and body["fp"] == fingerprint(filters)
            and body["uid"] == str(caller_id)
            and time.time() - int(body["iat"]) <= get_settings().CURSOR_TTL_SECONDS
            and isinstance(body["k"], list)
        )
        if not ok:
            raise ValueError("mismatch")
        return CursorState(upper_bound=datetime.fromisoformat(body["ub"]), last=[str(v) for v in body["k"]])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise invalid_cursor() from None
