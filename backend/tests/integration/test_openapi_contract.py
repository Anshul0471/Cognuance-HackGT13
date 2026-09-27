"""The exported contract is the real one (guide 05 §17, §18 check 14)."""

import json

from app.main import app
from app.scripts.export_openapi import OUTPUT, render

PUBLIC = {"getHealth", "getReadiness", "getModelStatus", "login"}


def test_exported_openapi_matches_the_application():
    assert OUTPUT.exists(), "run: uv run --extra ml python -m app.scripts.export_openapi"
    assert OUTPUT.read_text() == render(), "backend/openapi.json is out of date: re-export it"


def test_every_operation_is_documented_consistently():
    schema = app.openapi()
    assert schema["info"]["version"] == "backend_contract_v1"
    assert "HTTPValidationError" not in json.dumps(schema["paths"])  # all errors use ErrorResponse
    ids = []
    for path, ops in schema["paths"].items():
        for op in ops.values():
            ids.append(op["operationId"])
            assert path.startswith("/api/v1/")
            if op["operationId"] in PUBLIC:
                assert not op.get("security")
            else:
                assert op.get("security") == [{"HTTPBearer": []}], op["operationId"]
            for code, response in op["responses"].items():
                if code.startswith(("4", "5")):
                    ref = response["content"]["application/json"]["schema"]["$ref"]
                    assert ref.endswith("/ErrorResponse"), (op["operationId"], code)
    # The guide 05 §4 inventory (21) plus refinement 01's doctor insights read endpoint.
    assert len(ids) == len(set(ids)) == 22
    assert "getPatientInsights" in ids
    no_content = schema["paths"]["/api/v1/auth/logout"]["post"]["responses"]["204"]
    assert "content" not in no_content
    start = schema["paths"]["/api/v1/patient/assessment-sessions"]["post"]["responses"]
    assert {"200", "201"} <= set(start)


def test_live_responses_match_declared_schemas(client):
    # Unauthenticated error shapes are the declared ErrorResponse envelope.
    body = client.get("/api/v1/doctor/summary").json()
    assert set(body["error"]) == {"code", "message", "request_id", "details"}
