from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuthDep, DbDep, SettingsDep
from app.core.errors import ApiError, error_responses
from app.core.request_context import current_request_id
from app.schemas.auth import LoginRequest, TokenResponse, UserSummary
from app.services.auth import authenticate, normalize_email, open_session, revoke_session, to_user_summary
from app.services.login_limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _bad_credentials() -> ApiError:
    return ApiError(
        401, "INVALID_CREDENTIALS", "Incorrect email or password.", headers={"WWW-Authenticate": "Bearer"}
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    operation_id="login",
    responses=error_responses(401, 413, 415, 422, 429),
)
def login(body: LoginRequest, request: Request, db: DbDep, settings: SettingsDep) -> TokenResponse:
    """JSON email/password login. Returns a short-lived bearer token (keep it in memory only).

    Failed attempts are limited per email and per client address (429 + Retry-After).
    """
    email_key = f"email:{normalize_email(body.email)}"
    keys = [email_key, f"addr:{request.client.host if request.client else 'unknown'}"]
    wait = limiter.retry_after(keys)
    if wait is not None:
        raise ApiError(
            429,
            "TOO_MANY_ATTEMPTS",
            "Too many sign-in attempts. Please wait and try again.",
            headers={"Retry-After": str(wait)},
        )
    user = authenticate(db, body.email, body.password)
    if user is None:
        limiter.record_failure(keys)
        raise _bad_credentials()
    limiter.clear(email_key)
    token, ttl = open_session(db, user, settings, current_request_id())
    db.commit()
    return TokenResponse(access_token=token, expires_in=ttl, user=to_user_summary(user))


@router.get("/me", response_model=UserSummary, operation_id="getCurrentUser", responses=error_responses(401))
def me(auth: AuthDep) -> UserSummary:
    return to_user_summary(auth.user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="logout",
    responses=error_responses(401),
)
def logout(auth: AuthDep, db: DbDep) -> Response:
    """Revoke the current bearer session. The same token is rejected afterwards."""
    revoke_session(db, auth.session, current_request_id())
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
