"""Authentication and cross-patient authorization against a real (rolled-back) PostgreSQL database."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import JWT_ALGORITHM, create_access_token, decode_access_token
from app.models import AuditEvent, DoctorPatientAssignment, PatientProfile, User
from app.scripts.seed_demo import DOCTORS, PATIENTS, seed_demo
from tests.conftest import DEMO_PASSWORD as PASSWORD

RIVERA = "dr.rivera@demo.test"
OKAFOR = "dr.okafor@demo.test"
ELEANOR = "eleanor.park@demo.test"  # Rivera's patient
WALTER = "walter.hughes@demo.test"
IRIS = "iris.novak@demo.test"  # Okafor's patient


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth_headers(client, email):
    response = login(client, email)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def patient_id(db, email) -> uuid.UUID:
    return db.scalar(select(PatientProfile.id).join(User).where(User.email == email))


# --- seed ---------------------------------------------------------------------------------------


def test_seed_is_idempotent(seeded):
    summary = seed_demo(seeded, PASSWORD)
    assert summary.created == []
    assert summary.assignments_created == 0
    assert len(seeded.scalars(select(User)).all()) == len(DOCTORS) + len(PATIENTS)
    assert len(seeded.scalars(select(DoctorPatientAssignment)).all()) == len(PATIENTS)


def test_passwords_are_stored_hashed(seeded):
    user = seeded.scalar(select(User).where(User.email == RIVERA))
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


# --- login --------------------------------------------------------------------------------------


def test_login_returns_token_and_server_derived_identity(client, seeded):
    response = login(client, ELEANOR.upper())  # email lookup is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["role"] == "patient"
    assert body["user"]["patient_id"] == str(patient_id(seeded, ELEANOR))
    assert body["user"]["doctor_id"] is None and body["user"]["display_name"] == "Eleanor Park"
    assert set(body["user"]) == {"id", "email", "display_name", "role", "patient_id", "doctor_id"}
    doctor = login(client, RIVERA).json()["user"]
    assert doctor["patient_id"] is None and doctor["doctor_id"] == doctor["id"]


@pytest.mark.parametrize("email,password", [(ELEANOR, "wrong-password"), ("nobody@demo.test", PASSWORD)])
def test_login_failure_is_generic(client, seeded, email, password):
    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.json()["error"]["message"] == "Incorrect email or password."
    assert password not in response.text


def test_inactive_user_cannot_login_or_use_existing_token(client, seeded):
    headers = auth_headers(client, ELEANOR)
    user = seeded.scalar(select(User).where(User.email == ELEANOR))
    user.is_active = False
    seeded.flush()
    assert login(client, ELEANOR).status_code == 401
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_me_requires_valid_token(client, seeded):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    settings = get_settings()
    user = seeded.scalar(select(User).where(User.email == ELEANOR))
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = jwt.encode(
        {"sub": str(user.id), "sid": str(uuid.uuid4()), "iat": past - timedelta(minutes=30), "exp": past},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_role_comes_from_database_not_token_claims(client, seeded):
    token = login(client, ELEANOR).json()["access_token"]
    settings = get_settings()
    claims = decode_access_token(token, settings)
    forged = jwt.encode(
        {**claims, "role": "doctor", "patient_id": None},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    headers = {"Authorization": f"Bearer {forged}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "patient"
    assert client.get("/api/v1/doctor/patients", headers=headers).status_code == 403


def test_token_without_server_session_is_rejected(client, seeded):
    user = seeded.scalar(select(User).where(User.email == ELEANOR))
    orphan = create_access_token(str(user.id), get_settings(), str(uuid.uuid4()))
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {orphan}"}).status_code == 401


def test_logout_revokes_only_that_session(client, seeded):
    first = auth_headers(client, ELEANOR)
    second = auth_headers(client, ELEANOR)
    response = client.post("/api/v1/auth/logout", headers=first)
    assert response.status_code == 204 and response.content == b""
    assert client.get("/api/v1/auth/me", headers=first).status_code == 401
    assert client.post("/api/v1/auth/logout", headers=first).status_code == 401
    assert client.get("/api/v1/auth/me", headers=second).status_code == 200
    actions = [a for (a,) in seeded.execute(select(AuditEvent.action).order_by(AuditEvent.created_at))]
    assert actions.count("LOGIN") == 2 and actions.count("LOGOUT") == 1


def test_failed_logins_are_rate_limited(client, seeded, monkeypatch):
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    get_settings.cache_clear()
    try:
        for _ in range(3):
            assert login(client, WALTER, "wrong").status_code == 401
        limited = login(client, WALTER)  # even the right password waits out the window
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
        assert limited.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
        # The client address also reached its failure budget, so other accounts wait too.
        assert login(client, RIVERA).status_code == 429
    finally:
        get_settings.cache_clear()
