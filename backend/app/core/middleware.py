"""ASGI middleware: request ID + no-store + structured access log, and body/content-type limits.

Pure ASGI (no BaseHTTPMiddleware) so bodies stream through untouched. Body limits are enforced
while streaming, not only from Content-Length (guide 05 §3): 256 KiB for assessment submissions,
16 KiB for every other write body.
"""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_context import current_request_id, set_request_id

log = logging.getLogger("app.access")

SUBMISSION_PATH = re.compile(r"/patient/assessment-sessions/[^/]+/submissions$")
SUBMISSION_MAX_BYTES = 256 * 1024
DEFAULT_MAX_BYTES = 16 * 1024
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def body_limit_for(path: str) -> int:
    return SUBMISSION_MAX_BYTES if SUBMISSION_PATH.search(path) else DEFAULT_MAX_BYTES


async def _send_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps(
        {"error": {"code": code, "message": message, "request_id": current_request_id(), "details": {}}}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-request-id", (current_request_id() or "").encode()),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


class RequestContextMiddleware:
    """Outermost app middleware: assigns the request ID, adds headers, logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        set_request_id(request_id)
        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"x-request-id", b"cache-control")
                ]
                headers += [(b"x-request-id", request_id.encode()), (b"cache-control", b"no-store")]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            route = scope.get("route")
            log.info(
                "request_id=%s method=%s route=%s status=%s latency_ms=%.1f",
                request_id,
                scope.get("method"),
                getattr(route, "path", "unmatched"),  # template, never the concrete path with IDs
                status_holder["status"],
                (time.perf_counter() - started) * 1000,
            )


class BodyLimitMiddleware:
    """413 over the per-route limit (declared or streamed); 415 for non-JSON write bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        limit = body_limit_for(scope["path"])
        length = headers.get(b"content-length")
        declared = int(length) if length is not None and length.isdigit() else None
        if declared is not None and declared > limit:
            await _send_error(send, 413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
            return
        has_body = (declared or 0) > 0 or b"transfer-encoding" in headers
        content_type = headers.get(b"content-type", b"").split(b";")[0].strip().lower()
        if has_body and content_type != b"application/json":
            await _send_error(
                send, 415, "UNSUPPORTED_MEDIA_TYPE", "Send the request body as application/json."
            )
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await _send_error(send, 413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
