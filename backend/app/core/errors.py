"""The single error contract for every API response (guide 05 §3).

`{"error": {"code", "message", "request_id", "details"}}`. `details` is allow-listed: field paths,
the caller's own recovery identifiers, current lock versions. Never raw input values, SQL, stack
traces, or whether another user's record exists.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

log = logging.getLogger("app.errors")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code")
    message: str = Field(description="Safe human-readable text")
    request_id: str | None = Field(description="Server-generated request UUID (also in X-Request-ID)")
    details: dict[str, Any] = Field(default_factory=dict, description="Allow-listed safe context")


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code, self.code, self.message = status_code, code, message
        self.details = details or {}
        self.headers = headers or {}


def not_found() -> ApiError:
    """Missing and inaccessible records are indistinguishable."""
    return ApiError(404, "NOT_FOUND", "The requested record was not found.")


def unauthenticated(message: str = "Sign in again to continue.") -> ApiError:
    return ApiError(401, "NOT_AUTHENTICATED", message, headers={"WWW-Authenticate": "Bearer"})


def error_json(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=current_request_id(), details=details or {})
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


_HTTP_CODES = {
    400: ("BAD_REQUEST", "The request could not be understood."),
    401: ("NOT_AUTHENTICATED", "Sign in again to continue."),
    403: ("FORBIDDEN", "This account cannot perform that action."),
    404: ("NOT_FOUND", "The requested record was not found."),
    405: ("METHOD_NOT_ALLOWED", "That method is not allowed here."),
    413: ("PAYLOAD_TOO_LARGE", "Request body is too large."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Send the request body as application/json."),
    429: ("TOO_MANY_REQUESTS", "Too many attempts. Please wait and try again."),
}


def _validation_details(exc: RequestValidationError) -> tuple[int, str, str, dict[str, Any]]:
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return 400, "MALFORMED_JSON", "The request body is not valid JSON.", {}
    # Field paths and error types only; never the submitted values or pydantic's message text
    # (which can quote input).
    fields = [
        {"path": ".".join(str(p) for p in e.get("loc", ()) if p != "body"), "type": e.get("type", "invalid")}
        for e in errors[:20]
    ]
    return 422, "VALIDATION_ERROR", "Some fields are missing or invalid.", {"fields": fields}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_json(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_json(*_validation_details(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("HTTP_ERROR", "The request failed."))
        headers = dict(exc.headers or {})
        if exc.status_code == 401:
            headers.setdefault("WWW-Authenticate", "Bearer")
        return error_json(exc.status_code, code, message, headers=headers or None)

    @app.exception_handler(OperationalError)
    async def _database(_: Request, exc: OperationalError) -> JSONResponse:
        # Connection loss, lock/statement timeout: nothing was committed by this request.
        log.warning("database unavailable (%s) request %s", type(exc.orig).__name__, current_request_id())
        return error_json(
            503,
            "DATABASE_UNAVAILABLE",
            "The service is temporarily unavailable. Please retry.",
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s (request %s)", type(exc).__name__, current_request_id())
        return error_json(
            500, "INTERNAL_ERROR", "Something went wrong. Nothing new was saved by this request."
        )


_DOC = {
    400: "Malformed JSON, cursor or query combination",
    401: "Missing, invalid, expired or revoked bearer credentials",
    403: "Authenticated caller has the wrong role",
    404: "Record missing or not accessible to this caller",
    409: "Idempotency mismatch, invalid state/transition or stale version",
    413: "Request body exceeds the limit",
    415: "Request body is not application/json",
    422: "Field or protocol validation failed",
    429: "Too many attempts; see Retry-After",
    503: "Infrastructure unavailable",
}


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` entries declaring the shared error schema."""
    return {c: {"model": ErrorResponse, "description": _DOC.get(c, "Error")} for c in codes}
