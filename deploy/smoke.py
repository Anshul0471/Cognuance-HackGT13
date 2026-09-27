"""Hosted/local smoke checks for a COGNUANCE deployment (guide 07 §12). Prints results, never secrets.

Read-only checks (safe to rerun):
    python3 deploy/smoke.py --base http://127.0.0.1:8088 --env deploy/local-release.env

Save/review journey on a *dedicated smoke patient* and the secondary doctor (never the presenter's
prepared scenario), run from backend/ so the canonical payload builder is importable:
    cd backend && uv run python ../deploy/smoke.py --base ... --env ../deploy/local-release.env \
        --save-review --showcase-credentials <path to showcase-private/<id>.credentials.json>

The forged-X-Forwarded-For check deliberately trips the login limiter for this client address for
LOGIN_WINDOW_SECONDS; run it last (--rate-limit).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def request(base: str, method: str, path: str, token: str | None = None, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, method=method, data=data, headers=hdrs)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, dict(r.headers), raw, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(), time.perf_counter() - t0


def env_value(env_file: Path, key: str) -> str:
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    raise SystemExit(f"{key} missing from {env_file}")


def login(base: str, email: str, password: str) -> str:
    status, _, raw, _ = request(base, "POST", "/api/v1/auth/login", body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"login failed for {email}: HTTP {status}")
    return json.loads(raw)["access_token"]


def read_only(base: str, env_file: Path) -> None:
    s, h, raw, _ = request(base, "GET", "/api/v1/health")
    check("health JSON", s == 200 and json.loads(raw).get("status") == "ok")
    s, h, raw, _ = request(base, "GET", "/api/v1/ready")
    check("ready JSON", s == 200 and json.loads(raw).get("status") == "ready", raw.decode()[:80])
    s, h, raw, _ = request(base, "GET", "/api/v1/model/status")
    ms = json.loads(raw)
    check("model status names the registered pair", ms.get("forecast_ready") is True,
          f"{ms.get('model_kind')} {ms.get('model_version')} + {ms.get('policy_version')}")
    check("API responses are no-store", "no-store" in h.get("Cache-Control", ""))
    s, h, raw, _ = request(base, "GET", "/api/v1/does-not-exist")
    check("unknown API route is a JSON error, not index.html",
          s == 404 and h.get("Content-Type", "").startswith("application/json") and b"<html" not in raw.lower())
    for path in ("/", "/about", "/login", "/doctor/alerts/00000000-0000-0000-0000-000000000000"):
        s, h, raw, _ = request(base, "GET", path)
        check(f"SPA route {path}", s == 200 and b'<div id="root">' in raw)
    s, h, raw, _ = request(base, "GET", "/assets/definitely-missing.js")
    check("missing asset is 404 (not the SPA shell)", s == 404 and b'<div id="root">' not in raw)
    s, h, raw, _ = request(base, "GET", "/")
    asset = raw.decode().split('src="/assets/')[1].split('"')[0]
    s2, h2, _, _ = request(base, "GET", f"/assets/{asset}")
    check("hashed asset is immutable-cached", s2 == 200 and "immutable" in h2.get("Cache-Control", ""))
    check("security headers", h.get("X-Content-Type-Options") == "nosniff" and h.get("Referrer-Policy") == "no-referrer")
    s, h, raw, _ = request(base, "GET", "/openapi.json")
    check("API schema/docs not exposed", b'"openapi"' not in raw)

    token = login(base, "dr.okafor@demo.test", env_value(env_file, "DEMO_ACCOUNT_PASSWORD"))
    timings = {}
    s, _, raw, t = request(base, "GET", "/api/v1/doctor/summary", token)
    timings["summary"] = t
    summary = json.loads(raw)
    check("presenter summary (real, scoped)", s == 200 and summary["assigned_patient_count"] >= 25,
          f"assigned {summary['assigned_patient_count']}, open {summary['open_alert_count']}, ack {summary['acknowledged_alert_count']}")
    s, _, raw, t = request(base, "GET", "/api/v1/doctor/patients?limit=20", token)
    timings["patients"] = t
    page = json.loads(raw)
    check("patients page 1 of 20 with a cursor", s == 200 and len(page["items"]) == 20 and page["next_cursor"])
    s, _, raw, t = request(base, "GET", "/api/v1/doctor/alerts?limit=20", token)
    timings["alerts"] = t
    alerts = json.loads(raw)["items"]
    check("unresolved alerts listed", s == 200 and len(alerts) > 0, f"{len(alerts)} items")
    oliver = next((p for p in page["items"] if p["display_name"] == "Oliver Grant"), None)
    if oliver is None:
        s, _, raw, _ = request(base, "GET", "/api/v1/doctor/patients?limit=20&q=Oliver", token)
        oliver = json.loads(raw)["items"][0]
    pid = oliver["patient_id"]
    s, _, raw, t = request(base, "GET", f"/api/v1/doctor/patients/{pid}/insights?from=2026-06-01T00:00:00Z&to=2026-09-28T00:00:00Z", token)
    timings["insights"] = t
    ins = json.loads(raw)
    check("Insights complete snapshot", s == 200 and ins["complete"] and ins["assessment_count"] == len(ins["records"]),
          f"{ins['assessment_count']} records")
    s, _, raw, _ = request(base, "GET", f"/api/v1/doctor/patients/{pid}/timeline", token)
    items = json.loads(raw)["items"]
    check("timeline carries cognitive_index_v1", s == 200 and all("cognitive_index" in i for i in items))
    request(base, "POST", "/api/v1/auth/logout", token)
    print("timings (s): " + ", ".join(f"{k} {v:.3f}" for k, v in timings.items()))


def save_review(base: str, env_file: Path, showcase_credentials: Path) -> None:
    sys.path.insert(0, str(Path.cwd()))
    from tests.factories import build_payload  # canonical, protocol-conformant payload (backend/)

    pw = env_value(env_file, "DEMO_ACCOUNT_PASSWORD")
    token = login(base, "eleanor.park@demo.test", pw)  # dedicated smoke patient (not a presenter patient)
    body = {"start_key": str(uuid.uuid4()), "input_mode": "keyboard", "device_changed": False,
            "navigation_assistance": False, "allow_unscheduled": True}
    s, _, raw, t_start = request(base, "POST", "/api/v1/patient/assessment-sessions", token, body)
    start = json.loads(raw)
    if s == 409 and start["error"]["code"] == "ACTIVE_SESSION_EXISTS":
        # An earlier interrupted smoke run: discard it (abandon, 204) and start a fresh session.
        request(base, "POST", f"/api/v1/patient/assessment-sessions/{start['error']['details']['session_id']}/abandon", token)
        body["start_key"] = str(uuid.uuid4())
        s, _, raw, t_start = request(base, "POST", "/api/v1/patient/assessment-sessions", token, body)
        start = json.loads(raw)
    check("smoke patient session start", s in (200, 201), f"{start.get('schedule_purpose')} in {t_start:.3f}s")
    # The public render protocol names trials `trial_id`; the builder reads the snapshot's `id`.
    protocol = json.loads(json.dumps(start["protocol"]))
    for task in ("attention", "reaction"):
        for trial in protocol[task]["trials"]:
            trial.setdefault("id", trial["trial_id"])
    for trial in protocol["attention"]["trials"]:
        trial.setdefault("is_target", trial["shape"] == "circle")  # the client's rule: respond to circles
    payload = build_payload(protocol)
    url = f"/api/v1/patient/assessment-sessions/{start['session_id']}/submissions"
    s, _, raw, t_submit = request(base, "POST", url, token, payload)
    receipt = json.loads(raw)
    check("submission receipt (201, saved)", s == 201 and receipt["saved"], f"{receipt['quality']['status']} / {receipt['analysis']['availability']} in {t_submit:.3f}s")
    s2, _, raw2, _ = request(base, "POST", url, token, payload)
    check("identical retry replays the same receipt", s2 == 200 and json.loads(raw2)["assessment_id"] == receipt["assessment_id"])
    check("patient receipt has no score/level/notes", not any(k in raw.decode() for k in ("deviation_level", "memory_score", "note")))
    request(base, "POST", "/api/v1/auth/logout", token)

    creds = json.loads(showcase_credentials.read_text())
    doctor = next(e for e in creds if e.startswith("dr."))  # the secondary doctor (not the presenter)
    dtoken = login(base, doctor, creds[doctor])
    s, _, raw, _ = request(base, "GET", "/api/v1/doctor/alerts?workflow_status=OPEN", dtoken)
    open_alerts = json.loads(raw)["items"]
    if not open_alerts:
        check("secondary doctor has an open alert to review", False)
        return
    alert = open_alerts[0]
    ack = request(base, "POST", f"/api/v1/doctor/alerts/{alert['alert_id']}/events", dtoken,
                  {"request_key": str(uuid.uuid4()), "expected_lock_version": alert["lock_version"],
                   "action": "ACKNOWLEDGED", "note": None})
    check("review: acknowledge (version-checked)", ack[0] == 200, f"lock {json.loads(ack[2])['alert']['lock_version']}")
    note = request(base, "POST", f"/api/v1/doctor/alerts/{alert['alert_id']}/events", dtoken,
                   {"request_key": str(uuid.uuid4()), "expected_lock_version": alert["lock_version"] + 1,
                    "action": "NOTE_ADDED", "note": "Smoke check: reviewed the recorded evidence."})
    check("review: note", note[0] == 200)
    stale = request(base, "POST", f"/api/v1/doctor/alerts/{alert['alert_id']}/events", dtoken,
                    {"request_key": str(uuid.uuid4()), "expected_lock_version": alert["lock_version"],
                     "action": "NOTE_ADDED", "note": "stale"})
    check("stale version is 409", stale[0] == 409 and json.loads(stale[2])["error"]["code"] == "STALE_ALERT_VERSION")
    Path("/tmp/cognuance-smoke-ids.json").write_text(json.dumps(
        {"assessment_id": receipt["assessment_id"], "alert_id": alert["alert_id"], "doctor": doctor}))
    request(base, "POST", "/api/v1/auth/logout", dtoken)


def rate_limit(base: str) -> None:
    codes = []
    for i in range(6):
        s, h, _, _ = request(base, "POST", "/api/v1/auth/login",
                             body={"email": f"nobody{i}@example.invalid", "password": "wrong-password"},
                             headers={"X-Forwarded-For": f"203.0.113.{i + 1}"})
        codes.append(s)
    check("forged X-Forwarded-For cannot dodge the per-address limiter", codes[-1] == 429, str(codes))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--env", type=Path, required=True, help="private deployment env file (read, never printed)")
    parser.add_argument("--save-review", action="store_true")
    parser.add_argument("--showcase-credentials", type=Path)
    parser.add_argument("--rate-limit", action="store_true")
    parser.add_argument("--skip-read-only", action="store_true")
    args = parser.parse_args()
    if not args.skip_read_only:
        read_only(args.base, args.env)
    if args.save_review:
        save_review(args.base, args.env, args.showcase_credentials)
    if args.rate_limit:
        rate_limit(args.base)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
