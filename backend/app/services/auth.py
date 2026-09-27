"""Credential verification, server-side auth sessions, and the safe user summary."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import AuditEvent, AuthSession, User, UserRole
from app.schemas.auth import UserSummary

# Verified against when the email is unknown so response timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def authenticate(db: Session, email: str, password: str) -> User | None:
    """Return the active user for these credentials, or None. Never says which part was wrong."""
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def open_session(db: Session, user: User, settings: Settings, request_id: str | None) -> tuple[str, int]:
    """Create an auth session row and its bearer token. Caller commits."""
    now = datetime.now(UTC)
    ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    row = AuthSession(user_id=user.id, expires_at=now + timedelta(seconds=ttl))
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="LOGIN",
            entity_type="auth_session",
            entity_id=row.id,
            request_id=uuid.UUID(request_id) if request_id else None,
        )
    )
    return create_access_token(str(user.id), settings, str(row.id), now), ttl


def active_session(db: Session, session_id: uuid.UUID, user_id: uuid.UUID) -> AuthSession | None:
    row = db.get(AuthSession, session_id)
    if row is None or row.user_id != user_id or row.revoked_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None
    return row


def revoke_session(db: Session, row: AuthSession, request_id: str | None) -> None:
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.add(
            AuditEvent(
                actor_user_id=row.user_id,
                action="LOGOUT",
                entity_type="auth_session",
                entity_id=row.id,
                request_id=uuid.UUID(request_id) if request_id else None,
            )
        )


def get_active_user(db: Session, user_id: uuid.UUID) -> User | None:
    user = db.get(User, user_id)
    return user if user is not None and user.is_active else None


def to_user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,  # type: ignore[arg-type]  # constrained by a DB check constraint
        patient_id=user.patient_profile.id if user.patient_profile else None,
        # Doctors have no separate profile table in this schema; their account ID identifies them.
        doctor_id=user.id if user.role == UserRole.DOCTOR else None,
    )
