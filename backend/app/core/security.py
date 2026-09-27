"""Password hashing and access-token primitives.

Tokens are short-lived, held in frontend memory only, and bound to a server-side `auth_sessions`
row through the required `sid` claim so logout/revocation takes effect on the next request.
Role/assignment are never read from claims.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
# Decoding only accepts this fixed list; never read the algorithm from the token header.
ALLOWED_JWT_ALGORITHMS = [JWT_ALGORITHM]

_password_hash = PasswordHash.recommended()  # Argon2id


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


ACCESS_TOKEN_TYPE = "access"  # noqa: S105 — the JWT `typ` claim value, not a secret


def create_access_token(
    subject: str, settings: Settings, session_id: str, now: datetime | None = None
) -> str:
    now = now or datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "typ": ACCESS_TOKEN_TYPE,
        "sub": subject,
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(claims, settings.JWT_SECRET.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError on any invalid/expired token."""
    claims = jwt.decode(
        token,
        settings.JWT_SECRET.get_secret_value(),
        algorithms=ALLOWED_JWT_ALGORITHMS,
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={"require": ["exp", "iat", "iss", "aud", "sub", "sid", "typ"]},
    )
    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("not an access token")
    return claims
