"""Pipeline stages: generate → (validate) → prepare → report (guide 03 §8, §10–§14, §17).

`generate` writes raw sessions, observations, truth, patients and splits into a temporary
directory, validates, then renames it into place and marks the manifest stage COMPLETE.
`prepare` never regenerates raw data: it builds windows, fits preprocessing on train_clean only,
and writes named tensor views. Existing COMPLETE stages are verified and reused, or rejected on
any mismatch — never silently overwritten.
"""

import os
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.ml.data import exports
from app.ml.data.config import (
    DATASET_SCHEMA_VERSION,
    GENERATOR_VERSION,
    PARTITIONS,
    DatasetError,
    GeneratorConfig,
    config_from_dict,
    dataset_dir,
)
from app.ml.data.generator import PROFILE_POPULATION, fixture_plans, generate_population
from app.ml.data.preprocessing import build_tensors, fit
from app.ml.data.splits import assign_partitions, check_isolation
from app.ml.data.validation import check_generated, check_prepared, require
from app.ml.data.windows import build_windows
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION

GENERATE_FILES = (
    "patients.jsonl",
    "raw_sessions.jsonl.gz",
    "observations.jsonl",
    "truth.jsonl",
    "splits.json",
    "fixtures/raw_sessions.jsonl.gz",
    "fixtures/observations.jsonl",
    "fixtures/truth.jsonl",
)
VIEWS = {
    "train_clean": ("train", True),
    "validation_tune_clean": ("validation_tune", True),
    "validation_tune_all": ("validation_tune", False),
    "validation_calibration_clean": ("validation_calibration", True),
    "validation_calibration_all": ("validation_calibration", False),
    "test_all": ("test", False),
}


def identity_for(config: GeneratorConfig) -> str:
    """Dataset identity used in UUIDv5 names: changes whenever config/versions change."""
    return config.config_hash()[:16]


def _sort_obs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda o: (o["patient_id"], o["slot_index"], o["attempt"]))


def generate(dataset_id: str, config: GeneratorConfig, root: Path | None = None) -> tuple[Path, str]:
    """Returns (dataset path, 'created' | 'reused')."""
    config.validate()
    final = dataset_dir(dataset_id, root)
    if final.exists():
        manifest = exports.read_json(final / "manifest.json") if (final / "manifest.json").exists() else None
        if not manifest or manifest["stages"].get("generate", {}).get("status") != "COMPLETE":
            raise DatasetError(f"{final} exists but is not a completed dataset; remove it deliberately")
        if manifest["config_hash"] != config.config_hash():
            raise DatasetError("dataset id already used with a different configuration; choose a new id")
        verify_stage(final, manifest, "generate")
        return final, "reused"

    identity = identity_for(config)
    population = PROFILE_POPULATION[config.profile]
    main = generate_population(config, identity, population)
    fixtures = generate_population(config, identity, "fixtures", fixture_plans(config, identity))

    families = sorted({t["family_id"] for t in main.truth if t["kind"] == "patient"})
    split = assign_partitions(config, population, families)
    patients = sorted(
        (
            {"patient_id": t["patient_id"], "family_id": t["family_id"], "population": population,
             "partition": split[t["family_id"]], "fictional": True}
            for t in main.truth
            if t["kind"] == "patient"
        ),
        key=lambda p: p["patient_id"],
    )
    check_isolation(patients)

    tmp = final.parent / f".{dataset_id}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        exports.write_jsonl(tmp / "patients.jsonl", patients)
        exports.write_jsonl(tmp / "raw_sessions.jsonl.gz", sorted(main.raw_sessions, key=lambda r: r["observation_id"]), compress=True)
        exports.write_jsonl(tmp / "observations.jsonl", _sort_obs(main.observations))
        exports.write_jsonl(tmp / "truth.jsonl", sorted(main.truth, key=lambda t: (t["kind"], t.get("observation_id") or t["patient_id"])))
        exports.write_json(
            tmp / "splits.json",
            {"rule": "sort family_id, permute with SeedSequence(root_seed, spawn_key=(population, 0, 99)), slice by partition_counts",
             "partition_counts": config.partition_counts, "families": dict(sorted(split.items()))},
        )
        exports.write_jsonl(tmp / "fixtures/raw_sessions.jsonl.gz", sorted(fixtures.raw_sessions, key=lambda r: r["observation_id"]), compress=True)
        exports.write_jsonl(tmp / "fixtures/observations.jsonl", _sort_obs(fixtures.observations))
        exports.write_jsonl(tmp / "fixtures/truth.jsonl", sorted(fixtures.truth, key=lambda t: (t["kind"], t.get("observation_id") or t["patient_id"])))
        hashes = exports.file_hashes(tmp, GENERATE_FILES)
        manifest = {
            "dataset_id": dataset_id,
            "status": "GENERATED",
            "synthetic": True,
            "clock": "SIMULATED observed_at/available_at; real wall-clock only in stages.*.completed_at",
            "versions": {"generator": GENERATOR_VERSION, "dataset_schema": DATASET_SCHEMA_VERSION,
                         "protocol": PROTOCOL_VERSION, "scoring": SCORING_VERSION},
            "config": config.to_dict(),
            "config_hash": config.config_hash(),
            "identity": identity,
            "population": population,
            "seed_convention": "PCG64(SeedSequence(root_seed, spawn_key=(population_id, patient_index, component)))",
            "id_convention": "uuid5(ID_NAMESPACE, '<identity>/<kind>/<population>/<patient>/<slot>/<attempt>')",
            "source_revision": exports.source_revision(),
            "environment": exports.environment(),
            "counts": {
                "patients": len(patients),
                "partitions": {p: sum(1 for x in patients if x["partition"] == p) for p in PARTITIONS},
                "sessions": len(main.observations),
                "fixture_patients": sum(1 for t in fixtures.truth if t["kind"] == "patient"),
                "fixture_sessions": len(fixtures.observations),
                "probability_clip_rate": round(main.clip_count / max(1, main.clip_total), 6),
            },
            "stages": {"generate": {"status": "VALIDATING", "files": hashes,
                                    "content_hash": exports.content_hash(hashes)}},
        }
        exports.write_json(tmp / "manifest.json", manifest)
        checks = check_generated(tmp)
        require(checks)
        manifest["stages"]["generate"].update(
            status="COMPLETE", completed_at=exports.now_iso(), checks={c.name: c.detail for c in checks}
        )
        exports.write_json(tmp / "manifest.json", manifest)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final, "created"


def verify_stage(path: Path, manifest: dict[str, Any], stage: str) -> None:
    recorded = manifest["stages"][stage]["files"]
    actual = exports.file_hashes(path, recorded)
    bad = [name for name in recorded if recorded[name] != actual[name]]
    if bad:
        raise DatasetError(f"checksum mismatch in {stage} files: {bad}")


def load_manifest(dataset_id: str, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = dataset_dir(dataset_id, root)
    if not (path / "manifest.json").exists():
        raise DatasetError(f"no dataset {dataset_id!r} under {path.parent}")
    return path, exports.read_json(path / "manifest.json")


def performance_slots(truth: list[dict[str, Any]]) -> dict[str, set[int]]:
    slots: dict[str, set[int]] = defaultdict(set)
    for t in truth:
        if t["kind"] == "patient" and t["event"] and t["event"]["is_performance_event"]:
            e = t["event"]
            slots[t["patient_id"]].update(range(e["event_start_slot"], e["event_start_slot"] + e["event_duration"]))
    return slots


def prepare(dataset_id: str, preprocessing_version: str, root: Path | None = None) -> tuple[Path, str]:
    path, manifest = load_manifest(dataset_id, root)
    if manifest["stages"].get("generate", {}).get("status") != "COMPLETE":
        raise DatasetError("generate stage is not COMPLETE; run generate_synthetic first")
    verify_stage(path, manifest, "generate")
    existing = manifest["stages"].get("prepare")
    if existing and existing.get("status") == "COMPLETE":
        if existing["preprocessing_version"] != preprocessing_version:
            raise DatasetError("prepare already COMPLETE with a different preprocessing version; use a new dataset id")
        verify_stage(path, manifest, "prepare")
        return path, "reused"

    config = config_from_dict(manifest["config"])
    identity = manifest["identity"]
    patients = list(exports.read_jsonl(path / "patients.jsonl"))
    partitions = {p["patient_id"]: p["partition"] for p in patients}
    observations = list(exports.read_jsonl(path / "observations.jsonl"))
    truth = list(exports.read_jsonl(path / "truth.jsonl"))
    windows = build_windows(
        observations, partitions, performance_slots(truth), config.slots_per_patient, config.history_length,
        identity, preprocessing_version,
    )
    obs_by_id = {o["observation_id"]: o for o in observations}

    view_windows = {
        name: [w for w in windows if w["kind"] == "slot" and w["supervised"] and w["partition"] == part and (w["clean"] or not clean_only)]
        for name, (part, clean_only) in VIEWS.items()
    }
    empty = [name for name, rows in view_windows.items() if not rows]
    if empty:
        raise DatasetError(f"empty tensor views {empty}: not training-ready (revise a named config deliberately)")
    params = fit(obs_by_id, view_windows["train_clean"])

    # Fixture windows share the population's fitted preprocessing but never enter a partition.
    fixture_obs = list(exports.read_jsonl(path / "fixtures/observations.jsonl"))
    fixture_truth = list(exports.read_jsonl(path / "fixtures/truth.jsonl"))
    fixture_windows = build_windows(
        fixture_obs, {o["patient_id"]: "fixtures" for o in fixture_obs}, performance_slots(fixture_truth),
        config.slots_per_patient, config.history_length, identity, preprocessing_version,
    )

    tmp = path / f".prepare.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    names: list[str] = []
    try:
        for part in PARTITIONS:
            exports.write_jsonl(tmp / f"windows/{part}.jsonl", [w for w in windows if w["partition"] == part])
            names.append(f"windows/{part}.jsonl")
        exports.write_jsonl(tmp / "windows/fixtures.jsonl", fixture_windows)
        names.append("windows/fixtures.jsonl")
        view_counts = {}
        for name, rows in view_windows.items():
            exports.write_npz(tmp / f"tensors/{name}.npz", build_tensors(rows, obs_by_id, params))
            names.append(f"tensors/{name}.npz")
            view_counts[name] = len(rows)
        exports.write_json(tmp / "preprocessing.json", params)
        names.append("preprocessing.json")
        hashes = exports.file_hashes(tmp, names)
        for name in names:
            dest = path / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp / name, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    checks = check_prepared(path)
    require(checks)  # the manifest is only updated after the prepared outputs validate

    manifest["stages"]["prepare"] = {
        "status": "COMPLETE",
        "completed_at": exports.now_iso(),
        "preprocessing_version": preprocessing_version,
        "files": hashes,
        "content_hash": exports.content_hash(hashes),
        "view_counts": view_counts,
        "checks": {c.name: c.detail for c in checks},
        "view_rule": "supervised slot windows of the partition; *_clean excludes any window whose history or target "
        "overlaps an injected performance event (truth used for offline selection only)",
    }
    manifest["status"] = "PREPARED"
    exports.atomic_write_json(path / "manifest.json", manifest)
    return path, "created"
