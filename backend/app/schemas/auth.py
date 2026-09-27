import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(min_length=3, max_length=320, strict=True)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256, strict=True)]


class UserSummary(BaseModel):
    """Safe current-account summary. Role and profile IDs come from the database, never the client."""

    id: uuid.UUID
    email: str
    display_name: str
    role: Literal["patient", "doctor"]
    patient_id: uuid.UUID | None = Field(description="Patient profile ID; null for doctors")
    doctor_id: uuid.UUID | None = Field(
        description="Doctor identifier (the doctor's account ID); null for patients"
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  # OAuth2 token type, not a secret
    expires_in: int = Field(description="Seconds until the bearer token expires")
    user: UserSummary
