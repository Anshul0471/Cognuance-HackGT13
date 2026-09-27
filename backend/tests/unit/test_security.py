from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_argon2_hash_and_verify():
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_round_trip():
    settings = get_settings()
    token = create_access_token("user-123", settings, "session-1")
    claims = decode_access_token(token, settings)
    assert claims["sub"] == "user-123" and claims["sid"] == "session-1"
    assert "role" not in claims  # authority is never carried in the token


def test_jwt_rejects_expired_token():
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(minutes=5)
    token = jwt.encode(
        {"sub": "u", "sid": "s", "iat": past - timedelta(minutes=30), "exp": past},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.PyJWTError):  # expired (and, being hand-made, also lacks iss/aud)
        decode_access_token(token, settings)


def test_jwt_rejects_other_algorithms_and_wrong_secret():
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {"sub": "u", "sid": "s", "iat": now, "exp": now + timedelta(minutes=5)}
    unsigned = jwt.encode(claims, None, algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(unsigned, settings)
    wrong_secret = jwt.encode(claims, "a-different-secret-of-sufficient-length-000", algorithm=JWT_ALGORITHM)
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(wrong_secret, settings)  # signature is checked before any claim


def test_jwt_requires_session_claim():
    settings = get_settings()
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": "u", "iat": now, "exp": now + timedelta(minutes=5)},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token, settings)


def _signed(settings, **overrides):
    now = datetime.now(UTC)
    claims = {
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "typ": "access",
        "sub": "u",
        "sid": "s",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, settings.JWT_SECRET.get_secret_value(), algorithm=JWT_ALGORITHM)


def test_jwt_issuer_audience_and_type_are_enforced():
    settings = get_settings()
    assert decode_access_token(_signed(settings), settings)["typ"] == "access"
    with pytest.raises(jwt.InvalidIssuerError):
        decode_access_token(_signed(settings, iss="someone-else"), settings)
    with pytest.raises(jwt.InvalidAudienceError):
        decode_access_token(_signed(settings, aud="another-app"), settings)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(_signed(settings, typ="refresh"), settings)
    for claim in ("iss", "aud", "typ", "sub", "exp", "iat"):
        with pytest.raises(jwt.MissingRequiredClaimError):
            decode_access_token(_signed(settings, **{claim: None}), settings)
