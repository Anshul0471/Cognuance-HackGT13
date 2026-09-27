"""Append-only audit events (allow-listed details only: IDs and codes, never answers or notes)."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.request_context import current_request_id
from app.models import AuditEvent


def audit(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    actor_user_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    rid = current_request_id()
    db.add(
        AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            patient_id=patient_id,
            request_id=uuid.UUID(rid) if rid else None,
            details=details or {},
        )
    )
