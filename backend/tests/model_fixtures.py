"""Test-only model bundles and weekly check-in helpers (not app code).

Bundles are written with the real registry functions into a temporary artifact root. Their
activatable flag is a property of these test documents only; the fixture policy uses guide 04 §13
constants (r=2, scales 10/5/50), which are not a deployable calibrated policy.
"""

import math
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ml.data import exports
from app.ml.data.preprocessing import X_CHANNELS, Y_CHANNELS
from app.ml.models import calibration, gru, registry
from app.ml.models.runs import baseline_config
from app.schemas.assessments import AssessmentSubmission, StartSessionRequest
from app.services.analyses import analyze_after_commit
from app.services.assessment_sessions import start_session
from app.services.assessment_submissions import submit_assessment
from tests.factories import build_payload, default_context

FIXTURE_SCALES = {"memory": 10.0, "attention": 5.0, "reaction_time_ms": 50.0}


def fake_params() -> dict[str, Any]:
    def s(mean: float, scale: float) -> dict[str, Any]:
        return {"mean": mean, "scale": scale, "constant": False, "count": 100}

    return {
        "preprocessing_version": "preprocessing_v1",
        "x_channels": list(X_CHANNELS),
        "y_channels": list(Y_CHANNELS),
        "imputation": {"sleep_hours_median": 7.0, "mood_score_median": 7.0},
        "input_stats": {
            "memory_score": s(60.0, 20.0),
            "attention_score": s(85.0, 10.0),
            "log_reaction_time": s(math.log(500.0), 0.2),
            "sleep_hours": s(7.0, 1.0),
            "mood_score": s(7.0, 1.5),
        },
        "target_stats": {
            "memory_score": s(60.0, 20.0),
            "attention_score": s(85.0, 10.0),
            "log_reaction_time": s(math.log(500.0), 0.2),
        },
    }


def make_bundle(
    root: Path,
    kind: str = "LAST_VALUE",
    *,
    version: str = "test-model",
    policy_versions: tuple[str, ...] = ("test-policy",),
    r: float = 2.0,
    activatable: bool = True,
    seed: int = 0,
) -> Path:
    src = root / f".src-{version}"
    src.mkdir(parents=True, exist_ok=True)
    exports.write_json(src / "preprocessing.json", fake_params())
    exports.write_json(src / "training_report.json", {"test_fixture": True})
    exports.write_json(src / "forecast_evaluation.json", {"test_fixture": True})
    sources = {n: src / n for n in ("preprocessing.json", "training_report.json", "forecast_evaluation.json")}
    if kind == "GRU":
        import torch

        torch.manual_seed(seed)
        exports.write_json(src / "model_config.json", {"kind": "GRU", **gru.architecture_config()})
        torch.save(gru.CognitiveForecaster().state_dict(), src / "weights.pt")
        sources["weights.pt"] = src / "weights.pt"
    else:
        exports.write_json(src / "model_config.json", baseline_config(kind))
    sources["model_config.json"] = src / "model_config.json"
    bundle, _ = registry.write_model_bundle(
        model_version=version,
        kind=kind,
        sources=sources,
        provenance={"test_fixture": True},
        activatable=activatable,
        root=root,
    )
    for pv in policy_versions:
        doc = calibration.policy_document(
            policy_version=pv,
            model_version=version,
            model_kind=kind,
            engine_version="forecast_engine_v1",
            preprocessing_version="preprocessing_v1",
            postprocessing_version="prediction_postprocess_v1",
            scales={
                d: {
                    "scale": v,
                    "raw_rmse": v,
                    "floor": 1.0,
                    "mean_residual": 0.0,
                    "n": 0,
                    "floor_applied": False,
                }
                for d, v in FIXTURE_SCALES.items()
            },
            r=r,
            provenance={"test_fixture": True, "activatable": activatable},
        )
        exports.write_json(src / f"{pv}.json", doc)
        exports.write_json(
            src / f"{pv}-report.json",
            {"activatable": activatable, "decision": "SELECTED", "mode": "TEST_FIXTURE", "selected_r": r},
        )
        meta = registry.write_policy(bundle, pv, src / f"{pv}.json", src / f"{pv}-report.json")
        exports.write_json(bundle / f"policies/{pv}/.meta.json", meta)
    return bundle


def register_bundle(db: Session, root: Path, bundle: Path) -> None:
    model, _ = registry.register_model(db, bundle, root)
    for pdir in sorted((bundle / "policies").iterdir()):
        registry.register_policy(db, model, bundle, pdir.name, exports.read_json(pdir / ".meta.json"))
    db.flush()


WORDS = 6


def payload_for(
    protocol: dict[str, Any],
    *,
    words: int = 4,
    attention_misses: int = 0,
    rt_ms: float = 390.0,
    context: dict[str, Any] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """memory = words/6; attention = 50·(hits/10 + 1); RT median = rt_ms."""
    missed = {"n": 0}

    def press(spec: dict[str, Any]) -> list[float]:
        if not spec["is_target"]:
            return []
        if missed["n"] < attention_misses:
            missed["n"] += 1
            return []
        return [450.0]

    return build_payload(
        protocol,
        memory_entries=list(protocol["memory"]["words"][:words]),
        attention_press=press,
        reaction=[rt_ms - 45 + 10 * i for i in range(10)],  # median = rt_ms
        context=context or default_context(),
        **kw,
    )


def checkin(
    db: Session,
    patient_id: uuid.UUID,
    when: datetime,
    *,
    allow_unscheduled: bool = False,
    analyze: bool = True,
    **payload_kw: Any,
):
    req = StartSessionRequest(
        start_key=uuid.uuid4(),
        input_mode="keyboard",
        device_changed=False,
        navigation_assistance=False,
        allow_unscheduled=allow_unscheduled,
    )
    session, _ = start_session(db, patient_id, req, when, rng=random.Random(7))
    db.commit()
    payload = AssessmentSubmission.model_validate(payload_for(session.protocol_snapshot, **payload_kw))
    done = when + timedelta(minutes=10)
    assessment, _ = submit_assessment(db, patient_id, session.id, payload, done)
    db.commit()
    if analyze and assessment.analysis_state in ("PENDING", "ANALYSIS_ERROR"):
        analyze_after_commit(db, assessment.id, done)
    db.refresh(assessment)
    return session, assessment


def week(anchor: datetime, k: int) -> datetime:
    return anchor + timedelta(days=7 * k, minutes=5)
