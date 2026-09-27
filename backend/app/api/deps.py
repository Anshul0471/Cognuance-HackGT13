"""Shared FastAPI dependencies: settings, DB session, authenticated user/session, role checks.

Role and patient identity always come from the database row for the token's subject, never from
token claims or request input. Every protected request also checks the server-side auth session
(logout/revocation) and the account's active status.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, unauthenticated
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import AuthSession, PatientProfile, User, UserRole
from app.services.auth import active_session, get_active_user

bearer_scheme = HTTPBearer(auto_error=False, description="Bearer token from POST /auth/login")

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def get_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbDep,
    settings: SettingsDep,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated("Sign in to continue.")
    try:
        claims = decode_access_token(credentials.credentials, settings)
        user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise unauthenticated() from None
    session = active_session(db, session_id, user_id)
    user = get_active_user(db, user_id) if session is not None else None
    if session is None or user is None:
        raise unauthenticated()
    return AuthContext(user=user, session=session)


AuthDep = Annotated[AuthContext, Depends(get_auth)]


def get_current_user(auth: AuthDep) -> User:
    return auth.user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole) -> Callable[[User], User]:
    def dependency(user: CurrentUserDep) -> User:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "This account cannot perform that action.")
        return user

    return dependency


DoctorDep = Annotated[User, Depends(require_role(UserRole.DOCTOR))]


def get_current_patient(user: Annotated[User, Depends(require_role(UserRole.PATIENT))]) -> PatientProfile:
    """The signed-in patient's own profile. Patient identity is never taken from the request."""
    if user.patient_profile is None:
        raise ApiError(403, "FORBIDDEN", "This account has no patient profile.")
    return user.patient_profile


PatientDep = Annotated[PatientProfile, Depends(get_current_patient)]
