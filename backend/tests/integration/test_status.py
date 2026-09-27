"""Infrastructure endpoints and the shared HTTP conventions (guide 05 §3, §5)."""

import uuid

from app.api.v1.status import get_readiness_checker
from app.main import app
from app.services.readiness import CheckResult, MigrationCheckResult, ReadinessResult


def _readiness(db_ok: bool, migrations_ok: bool) -> ReadinessResult:
    return ReadinessResult(
        database=CheckResult(ok=db_ok, detail="x"),
        migrations=MigrationCheckResult(ok=migrations_ok, detail="x", current="a", head="a"),
    )


def _error(response):
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "request_id", "details"}
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    return body["error"]


def test_health_is_minimal_and_has_request_id(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    uuid.UUID(response.headers["x-request-id"])
    assert response.headers["cache-control"] == "no-store"


def test_client_request_id_is_not_trusted(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "attacker-chosen"})
    assert response.headers["x-request-id"] != "attacker-chosen"


def test_ready_200_and_503_codes(client):
    app.dependency_overrides[get_readiness_checker] = lambda: lambda: _readiness(True, True)
    assert client.get("/api/v1/ready").json() == {"status": "ready"}
    app.dependency_overrides[get_readiness_checker] = lambda: lambda: _readiness(False, False)
    response = client.get("/api/v1/ready")
    assert response.status_code == 503 and _error(response)["code"] == "DATABASE_UNAVAILABLE"
    app.dependency_overrides[get_readiness_checker] = lambda: lambda: _readiness(True, False)
    assert _error(client.get("/api/v1/ready"))["code"] == "MIGRATIONS_NOT_CURRENT"


def test_ready_with_unreachable_database_is_sanitized(client):
    # Real check against 127.0.0.1:1 (conftest): must fail fast without leaking credentials.
    response = client.get("/api/v1/ready")
    assert response.status_code == 503 and _error(response)["code"] == "DATABASE_UNAVAILABLE"
    assert "test-password-should-not-leak" not in response.text and "test_user" not in response.text


def test_model_status_stable_schema_when_unconfigured(client):
    response = client.get("/api/v1/model/status")
    assert response.status_code == 200
    assert response.json() == {
        "model_kind": None,
        "model_version": None,
        "policy_version": None,
        "model_loaded": False,
        "policy_ready": False,
        "forecast_ready": False,
        "reason_code": "MODEL_NOT_CONFIGURED",
    }


def test_error_envelope_for_framework_errors(client):
    assert _error(client.get("/api/v1/nope"))["code"] == "NOT_FOUND"
    assert _error(client.delete("/api/v1/health"))["code"] == "METHOD_NOT_ALLOWED"
    unauth = client.get("/api/v1/auth/me")
    assert unauth.status_code == 401 and unauth.headers["www-authenticate"] == "Bearer"
    assert _error(unauth)["code"] == "NOT_AUTHENTICATED"


def test_malformed_json_415_413_and_validation_do_not_echo_input(client):
    bad = client.post(
        "/api/v1/auth/login", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert bad.status_code == 400 and _error(bad)["code"] == "MALFORMED_JSON"
    form = client.post("/api/v1/auth/login", data={"username": "a", "password": "b"})
    assert form.status_code == 415 and _error(form)["code"] == "UNSUPPORTED_MEDIA_TYPE"
    big = client.post("/api/v1/auth/login", json={"email": "a@b.c", "password": "x" * 20000})
    assert big.status_code == 413 and _error(big)["code"] == "PAYLOAD_TOO_LARGE"
    invalid = client.post(
        "/api/v1/auth/login", json={"email": "a@b.c", "password": "secret-value", "extra": 1}
    )
    err = _error(invalid)
    assert invalid.status_code == 422 and err["code"] == "VALIDATION_ERROR"
    assert {"path": "extra", "type": "extra_forbidden"} in err["details"]["fields"]
    assert "secret-value" not in invalid.text


def test_openapi_docs_available_in_development_and_test(client):
    assert client.get("/docs").status_code == 200
