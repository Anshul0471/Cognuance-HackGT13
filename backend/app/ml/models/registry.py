"""Versioned artifact bundles, DB registration and atomic activation (guide 04 §16).

Bundle layout (`artifacts/<model_version>/`): manifest.json, model_config.json, preprocessing.json,
weights.pt (GRU only), training_report.json, forecast_evaluation.json, policies/<pv>/{policy.json,
calibration_report.json}, reports/<eval>/test_report.json. The model manifest hashes the model files
only; policies and reports are versioned independently and never alter the model manifest.
Existing files are never overwritten: a different payload under an existing version is an error.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.ml.data import exports
from app.ml.data.config import PREPROCESSING_VERSION, DatasetError, dataset_dir
from app.ml.data.preprocessing import X_CHANNELS, Y_CHANNELS
from app.ml.models import ENGINE_VERSION
from app.ml.models.anomaly import POLICY_SCHEMA_VERSION, PolicyError, PolicyRules
from app.ml.models.postprocessing import POSTPROCESSING_VERSION
from app.ml.models.runs import RunError, artifact_root, load_run, model_version_for
from app.models import AnomalyPolicy, ModelKind, ModelVersion

MANIFEST_SCHEMA = "model_bundle_manifest_v1"
ACTIVATION_LOCK_KEY = 404_004  # pg advisory lock serializing activations


class RegistryError(RuntimeError):
    """Artifact/registry verification failure. `code` is safe to expose in status output."""

    def __init__(self, message: str, code: str = "ARTIFACT_INVALID") -> None:
        super().__init__(message)
        self.code = code


def bundle_dir(model_version: str, root: Path | None = None) -> Path:
    try:
        return dataset_dir(model_version, artifact_root(root))
    except DatasetError:
        raise RegistryError("model version must match [a-z0-9][a-z0-9._-]{0,63}") from None


def _inside(base: Path, rel: str) -> Path:
    path = (base / rel).resolve()
    if base.resolve() not in path.parents and path != base.resolve():
        raise RegistryError("artifact path escapes the artifact root")
    return path


def model_files(kind: str) -> list[str]:
    files = ["model_config.json", "preprocessing.json", "training_report.json", "forecast_evaluation.json"]
    return files + (["weights.pt"] if kind == "GRU" else [])


def _copy_new(src: Path, dest: Path) -> None:
    """Copy unless an identical file exists; a different existing file is an immutability violation."""
    if dest.exists():
        if exports.sha256_file(dest) != exports.sha256_file(src):
            raise RegistryError(f"{dest.name} already exists with different content; use a new version")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def write_model_bundle(
    *,
    model_version: str,
    kind: str,
    sources: dict[str, Path],
    provenance: dict[str, Any],
    activatable: bool,
    root: Path | None = None,
) -> tuple[Path, str]:
    """Create (or verify identical) model content + manifest. Returns (bundle dir, created|reused)."""
    if kind not in ModelKind.__members__:
        raise RegistryError(f"unknown model kind {kind}")
    names = model_files(kind)
    if sorted(sources) != sorted(names):
        raise RegistryError(f"bundle for {kind} needs exactly {names}")
    params = exports.read_json(sources["preprocessing.json"])
    if (
        params.get("x_channels") != list(X_CHANNELS)
        or params.get("preprocessing_version") != PREPROCESSING_VERSION
    ):
        raise RegistryError(
            "preprocessing does not match the preprocessing_v1 feature schema", "FEATURE_SCHEMA_MISMATCH"
        )
    final = bundle_dir(model_version, root)
    hashes = {n: exports.sha256_file(sources[n]) for n in sorted(names)}
    if (final / "manifest.json").exists():
        manifest = exports.read_json(final / "manifest.json")
        if manifest.get("files") != hashes or manifest.get("kind") != kind:
            raise RegistryError(f"model version {model_version} already exists with different content")
        verify_bundle_files(final, manifest)
        return final, "reused"
    for n in names:
        _copy_new(sources[n], final / n)
    manifest = {
        "manifest_schema": MANIFEST_SCHEMA,
        "model_version": model_version,
        "kind": kind,
        "engine_version": ENGINE_VERSION,
        "preprocessing_version": params["preprocessing_version"],
        "postprocessing_version": POSTPROCESSING_VERSION,
        "feature_order": list(X_CHANNELS),
        "target_order": list(Y_CHANNELS),
        "sequence_length": 6,
        "files": hashes,
        "content_hash": exports.content_hash(hashes),
        "provenance": provenance,
        "activatable": activatable,
        "status": "COMPLETE",
        "created_at": exports.now_iso(),
        "note": "Policies and reports live in subdirectories and are versioned independently "
        "of this manifest.",
    }
    exports.write_json(final / "manifest.json", manifest)
    return final, "created"


def write_policy(bundle: Path, policy_version: str, policy_file: Path, report_file: Path) -> dict[str, Any]:
    pdir = dataset_dir(policy_version, bundle / "policies")
    _copy_new(policy_file, pdir / "policy.json")
    _copy_new(report_file, pdir / "calibration_report.json")
    return {
        "policy_file": f"policies/{policy_version}/policy.json",
        "policy_sha256": exports.sha256_file(pdir / "policy.json"),
        "calibration_report_file": f"policies/{policy_version}/calibration_report.json",
        "calibration_report_sha256": exports.sha256_file(pdir / "calibration_report.json"),
    }


def verify_bundle_files(bundle: Path, manifest: dict[str, Any]) -> None:
    for name, digest in manifest["files"].items():
        path = _inside(bundle, name)
        if not path.exists() or exports.sha256_file(path) != digest:
            raise RegistryError(f"checksum mismatch for {name}", "ARTIFACT_CHECKSUM_MISMATCH")


def verify_model_row(row: ModelVersion, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Manifest digest == DB, file hashes, schema and versions. Returns (bundle dir, manifest)."""
    base = artifact_root(root)
    manifest_path = _inside(base, row.artifact_relative_path)
    if not manifest_path.exists():
        raise RegistryError("model bundle manifest is missing", "ARTIFACT_MISSING")
    if exports.sha256_file(manifest_path) != row.artifact_sha256:
        raise RegistryError("model manifest digest does not match the registry", "ARTIFACT_CHECKSUM_MISMATCH")
    manifest = exports.read_json(manifest_path)
    bundle = manifest_path.parent
    expected = {
        "manifest_schema": MANIFEST_SCHEMA,
        "model_version": row.version,
        "kind": row.kind,
        "engine_version": row.engine_version,
        "preprocessing_version": row.preprocessing_version,
        "postprocessing_version": row.postprocessing_version,
        "feature_order": list(X_CHANNELS),
        "sequence_length": row.sequence_length,
        "status": "COMPLETE",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            code = "FEATURE_SCHEMA_MISMATCH" if key == "feature_order" else "ARTIFACT_VERSION_MISMATCH"
            raise RegistryError(f"manifest {key} does not match the registry", code)
    if sorted(manifest["files"]) != sorted(model_files(row.kind)):
        raise RegistryError("bundle file list does not match the model kind")
    verify_bundle_files(bundle, manifest)
    if exports.read_json(bundle / "preprocessing.json").get("x_channels") != list(X_CHANNELS):
        raise RegistryError("preprocessing channel order mismatch", "FEATURE_SCHEMA_MISMATCH")
    return bundle, manifest


def verify_policy_row(policy: AnomalyPolicy, model: ModelVersion, root: Path | None = None) -> PolicyRules:
    if policy.model_version_id != model.id:
        raise RegistryError("policy is bound to a different model", "POLICY_MODEL_MISMATCH")
    bundle, _ = verify_model_row(model, root)
    meta = policy.calibration_metadata
    for key in ("policy", "calibration_report"):
        path = _inside(bundle, meta[f"{key}_file"])
        if not path.exists() or exports.sha256_file(path) != meta[f"{key}_sha256"]:
            raise RegistryError(f"{key} file checksum mismatch", "POLICY_CHECKSUM_MISMATCH")
    doc = exports.read_json(_inside(bundle, meta["policy_file"]))
    if doc != policy.configuration:
        raise RegistryError("policy file and registered configuration disagree", "POLICY_MISMATCH")
    if doc.get("model_version") != model.version or doc.get("policy_schema_version") != POLICY_SCHEMA_VERSION:
        raise RegistryError("policy identity does not match its model", "POLICY_MODEL_MISMATCH")
    if (
        doc.get("postprocessing_version") != model.postprocessing_version
        or doc.get("preprocessing_version") != model.preprocessing_version
    ):
        raise RegistryError("policy was calibrated for different pre/postprocessing", "POLICY_MODEL_MISMATCH")
    try:
        return PolicyRules.from_configuration(doc)
    except PolicyError as exc:
        raise RegistryError(str(exc), "POLICY_INVALID") from None


def register_model(db: Session, bundle: Path, root: Path | None = None) -> tuple[ModelVersion, str]:
    manifest_path = bundle / "manifest.json"
    manifest = exports.read_json(manifest_path)
    verify_bundle_files(bundle, manifest)
    digest = exports.sha256_file(manifest_path)
    rel = str(manifest_path.resolve().relative_to(artifact_root(root)))
    row = db.scalar(select(ModelVersion).where(ModelVersion.version == manifest["model_version"]))
    if row is not None:
        if row.artifact_sha256 != digest or row.artifact_relative_path != rel:
            raise RegistryError("model version already registered with different content")
        return row, "reused"
    row = ModelVersion(
        version=manifest["model_version"],
        kind=manifest["kind"],
        engine_version=manifest["engine_version"],
        preprocessing_version=manifest["preprocessing_version"],
        postprocessing_version=manifest["postprocessing_version"],
        artifact_relative_path=rel,
        artifact_sha256=digest,
        feature_order=manifest["feature_order"],
        sequence_length=manifest["sequence_length"],
        provenance=manifest["provenance"],
        activatable=bool(manifest["activatable"]),
        is_active=False,
    )
    db.add(row)
    db.flush()
    return row, "created"


def register_policy(
    db: Session, model: ModelVersion, bundle: Path, policy_version: str, file_meta: dict[str, Any]
) -> tuple[AnomalyPolicy, str]:
    doc = exports.read_json(bundle / file_meta["policy_file"])
    report = exports.read_json(bundle / file_meta["calibration_report_file"])
    activatable = (
        bool(report.get("activatable")) and bool(doc["provenance"].get("activatable")) and model.activatable
    )
    meta = {
        **file_meta,
        "decision": report.get("decision"),
        "selected_r": report.get("selected_r"),
        "mode": report.get("mode"),
        "activatable": activatable,
    }
    row = db.scalar(select(AnomalyPolicy).where(AnomalyPolicy.version == policy_version))
    if row is not None:
        if row.model_version_id != model.id or row.configuration != doc or row.calibration_metadata != meta:
            raise RegistryError("policy version already registered with different content")
        return row, "reused"
    if doc.get("policy_version") != policy_version or doc.get("model_version") != model.version:
        raise RegistryError("policy document identity mismatch", "POLICY_MODEL_MISMATCH")
    PolicyRules.from_configuration(doc)  # validates positive finite scales etc.
    row = AnomalyPolicy(
        version=policy_version,
        model_version_id=model.id,
        policy_schema_version=doc["policy_schema_version"],
        configuration=doc,
        calibration_metadata=meta,
        activatable=activatable,
        is_active=False,
    )
    db.add(row)
    db.flush()
    return row, "created"


def _baseline_training_report(run: Path, kind: str, run_id: str) -> dict[str, Any]:
    gru_report = exports.read_json(run / "candidates/GRU/training_report.json")
    return {
        "kind": kind,
        "run_id": run_id,
        "learned_parameters": False,
        "note": "Deterministic baseline: no training. The GRU trained in the same run was kept and evaluated "
        "(see forecast_evaluation.json and the run directory).",
        "compared_gru": {
            k: gru_report[k]
            for k in (
                "settings",
                "selected_epoch",
                "selected_tune_selection_metric",
                "epochs_run",
                "runtime_seconds",
                "environment",
            )
        },
        "limitations": ["Ignores sleep, mood and medication; uses the six raw domain values only."],
    }


def register_run(db: Session, run_id: str, root: Path | None = None) -> dict[str, Any]:
    """Build/verify the bundle for a run's selected candidate and register it and its policies (inactive)."""
    run, manifest = load_run(run_id, root)
    sel = manifest["stages"].get("select", {})
    if sel.get("status") != "COMPLETE":
        raise RunError("select stage is not COMPLETE; run select_forecaster first")
    kind = sel["selected_kind"]
    version = model_version_for(run_id, kind)
    staged = run / f".register-{kind}"
    staged.mkdir(exist_ok=True)
    if kind == "GRU":
        training_report = run / "candidates/GRU/training_report.json"
    else:
        training_report = staged / "training_report.json"
        exports.write_json(training_report, _baseline_training_report(run, kind, run_id))
    sources = {
        "model_config.json": run / f"candidates/{kind}/model_config.json",
        "preprocessing.json": run / "preprocessing.json",
        "training_report.json": training_report,
        "forecast_evaluation.json": run / "forecast_evaluation.json",
    }
    if kind == "GRU":
        sources["weights.pt"] = run / "candidates/GRU/weights.pt"
    bundle, model_status = write_model_bundle(
        model_version=version,
        kind=kind,
        sources=sources,
        provenance={
            "run_id": run_id,
            "dataset": manifest["dataset"],
            "source_revision": manifest.get("source_revision"),
            "selection": "forecast_evaluation.json",
        },
        activatable=bool(manifest["activatable_profile"]),
        root=root,
    )
    model_row, model_db = register_model(db, bundle, root)
    policies = {}
    for pv, st in manifest["stages"].get("calibrate", {}).items():
        if st.get("status") != "COMPLETE":
            policies[pv] = f"not registered ({st.get('decision')})"
            continue
        meta = write_policy(
            bundle, pv, run / f"policies/{pv}/policy.json", run / f"policies/{pv}/calibration_report.json"
        )
        prow, pstatus = register_policy(db, model_row, bundle, pv, meta)
        policies[pv] = f"{pstatus} (activatable={prow.activatable}, decision={st.get('decision')})"
    reports = []
    for eval_id in manifest["stages"].get("evaluate", {}):
        for f in (run / "reports" / eval_id).iterdir():
            _copy_new(f, bundle / "reports" / eval_id / f.name)
        reports.append(eval_id)
    shutil.rmtree(staged, ignore_errors=True)
    return {
        "model_version": version,
        "kind": kind,
        "bundle": str(bundle),
        "bundle_status": model_status,
        "db": model_db,
        "model_activatable": model_row.activatable,
        "policies": policies,
        "reports": reports,
    }


def activate(
    db: Session, model_version: str, policy_version: str, root: Path | None = None
) -> dict[str, Any]:
    """Verify and atomically switch the active model/policy pair (caller commits)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ACTIVATION_LOCK_KEY})
    model = db.scalar(select(ModelVersion).where(ModelVersion.version == model_version))
    policy = db.scalar(select(AnomalyPolicy).where(AnomalyPolicy.version == policy_version))
    if model is None or policy is None:
        raise RegistryError("model or policy version is not registered", "NOT_REGISTERED")
    if not model.activatable or not policy.activatable:
        raise RegistryError(
            "model or policy is not activatable (fixture/smoke run or failed calibration)", "NOT_ACTIVATABLE"
        )
    verify_policy_row(policy, model, root)
    from app.ml.serving import load_model  # full load (incl. weights) before switching

    load_model(model, root)
    now = datetime.now(UTC)
    db.execute(
        update(AnomalyPolicy)
        .where(AnomalyPolicy.is_active.is_(True), AnomalyPolicy.id != policy.id)
        .values(is_active=False, deactivated_at=now)
    )
    db.execute(
        update(ModelVersion)
        .where(ModelVersion.is_active.is_(True), ModelVersion.id != model.id)
        .values(is_active=False, deactivated_at=now)
    )
    db.flush()
    if not model.is_active:
        model.is_active, model.activated_at = True, now
    if not policy.is_active:
        policy.is_active, policy.activated_at = True, now
    db.flush()
    return {
        "model_version": model.version,
        "kind": model.kind,
        "policy_version": policy.version,
        "threshold_r": policy.configuration["rules"]["r"],
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
