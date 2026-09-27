"""Frozen, versioned generator configuration and dataset path handling (guide 03 §4, §5, §17).

Every number here is an engineering choice to exercise the app, not a clinical assumption.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION

GENERATOR_VERSION = "synthetic_generator_v1"
# v2: raw submissions use the guide-05 contract (v1 datasets are read via legacy_payload).
DATASET_SCHEMA_VERSION = "dataset_schema_v2"
PREPROCESSING_VERSION = "preprocessing_v1"
PARTITIONS = ("train", "validation_tune", "validation_calibration", "test")

_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class DatasetError(RuntimeError):
    """A pipeline contract failed; the message says which one."""


@dataclass(frozen=True)
class Range:
    low: float
    high: float


@dataclass(frozen=True)
class GeneratorConfig:
    profile: str
    root_seed: int = 42
    patient_count: int = 500
    slots_per_patient: int = 32
    cadence_days: int = 7
    history_length: int = 6
    partition_counts: dict[str, int] = field(
        default_factory=lambda: {"train": 300, "validation_tune": 75, "validation_calibration": 50, "test": 75}
    )
    missing_context_probability_per_field: float = 0.10
    missing_slot_probability: float = 0.02
    technical_issue_probability: float = 0.03
    # Retake after an unreliable attempt, extra attempt after a valid one, input-mode switch per patient.
    retake_probability: float = 0.5
    extra_attempt_probability: float = 0.01
    input_mode_switch_probability: float = 0.05
    # §6.1 latent task parameters (toy ranges, stored with every dataset).
    initial_recall_p: Range = Range(0.40, 0.95)
    initial_hit_p: Range = Range(0.55, 0.98)
    initial_false_alarm_p: Range = Range(0.02, 0.30)
    initial_rt_median_ms: Range = Range(350, 1000)
    weekly_recall_hit_trend: Range = Range(-0.008, 0.002)
    weekly_false_alarm_trend: Range = Range(-0.001, 0.005)
    weekly_log_rt_trend: Range = Range(-0.002, 0.008)
    ar1_coefficient: float = 0.5
    innovation_sd_probability: float = 0.02
    innovation_sd_log_rt: float = 0.03
    innovation_multiplier: Range = Range(0.5, 1.5)
    within_trial_log_rt_sd: float = 0.12
    trajectory_mix: dict[str, float] = field(
        default_factory=lambda: {"stable": 0.4, "linear": 0.4, "nonlinear": 0.2}
    )
    # §6.2 context.
    sleep_center_hours: Range = Range(5, 9)
    sleep_weekly_sd: float = 0.8
    mood_center: Range = Range(4, 8)
    mood_weekly_sd: float = 1.5
    medication_change_probability: float = 0.05
    shared_shock_weight: float = 0.3
    # §7 scenario families and toy event magnitudes.
    scenario_mix: dict[str, float] = field(
        default_factory=lambda: {
            "background": 0.45,
            "isolated_worsening": 0.15,
            "persistent_worsening": 0.15,
            "single_domain_worsening": 0.10,
            "context_only_change": 0.10,
            "improvement": 0.05,
        }
    )
    event_start_slot: Range = Range(8, 27)
    recall_hit_drop: Range = Range(0.10, 0.30)
    false_alarm_rise: Range = Range(0.05, 0.20)
    log_rt_rise: Range = Range(0.10, 0.35)
    # Stress-set knobs (§15): heavier tails, correlated missingness.
    noise_distribution: Literal["normal", "student_t"] = "normal"
    student_t_df: float = 3.0
    correlated_missingness: bool = False
    anchor_epoch: str = "2025-01-06T15:00:00+00:00"

    def validate(self) -> None:
        if set(self.partition_counts) != set(PARTITIONS):
            raise DatasetError(f"partition_counts must name exactly {PARTITIONS}")
        if any(not isinstance(v, int) or v <= 0 for v in self.partition_counts.values()):
            raise DatasetError("every partition needs a positive integer count (no empty calibration/test)")
        if sum(self.partition_counts.values()) != self.patient_count:
            raise DatasetError("partition_counts must sum to patient_count")
        start, end = int(self.event_start_slot.low), int(self.event_start_slot.high)
        if not (self.history_length <= start <= end and end + 3 <= self.slots_per_patient):
            raise DatasetError("event_start_slot must leave full history before and 3 slots after the event")
        for name, mix in (("scenario_mix", self.scenario_mix), ("trajectory_mix", self.trajectory_mix)):
            if abs(sum(mix.values()) - 1) > 1e-9:
                raise DatasetError(f"{name} must sum to 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "config": self.to_dict(),
                "generator_version": GENERATOR_VERSION,
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "scoring_version": SCORING_VERSION,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def profile(name: str, seed: int = 42) -> GeneratorConfig:
    """Named profiles. `smoke` checks mechanics only; never report its metrics as the evaluation."""
    full = GeneratorConfig(profile="full", root_seed=seed)
    smoke = replace(
        full,
        profile="smoke",
        patient_count=40,
        slots_per_patient=16,
        partition_counts={"train": 24, "validation_tune": 6, "validation_calibration": 4, "test": 6},
        event_start_slot=Range(7, 12),
    )
    stress_changes = dict(
        noise_distribution="student_t",
        correlated_missingness=True,
        trajectory_mix={"stable": 0.2, "linear": 0.3, "nonlinear": 0.5},
        recall_hit_drop=Range(0.05, 0.40),
        log_rt_rise=Range(0.05, 0.50),
        innovation_multiplier=Range(0.8, 2.0),
    )
    profiles = {
        "full": full,
        "smoke": smoke,
        # Disjoint families come from a different root namespace (see generator.PROFILE_NAMESPACE).
        "stress": replace(full, profile="stress", event_start_slot=Range(6, 28), **stress_changes),
        "stress-smoke": replace(smoke, profile="stress-smoke", event_start_slot=Range(6, 13), **stress_changes),
    }
    if name not in profiles:
        raise DatasetError(f"unknown profile {name!r}; choose from {sorted(profiles)}")
    config = profiles[name]
    config.validate()
    return config


def config_from_dict(data: dict[str, Any]) -> GeneratorConfig:
    ranges = {k: Range(**v) for k, v in data.items() if isinstance(v, dict) and set(v) == {"low", "high"}}
    return GeneratorConfig(**{**data, **ranges})


def synthetic_root() -> Path:
    return get_settings().SYNTHETIC_DATA_DIR


def dataset_dir(dataset_id: str, root: Path | None = None) -> Path:
    """Resolve a dataset ID beneath the synthetic data directory; rejects path traversal."""
    if not _DATASET_ID.match(dataset_id):
        raise DatasetError("dataset id must match [a-z0-9][a-z0-9._-]{0,63}")
    base = (root or synthetic_root()).resolve()
    path = (base / dataset_id).resolve()
    if path.parent != base:
        raise DatasetError("dataset id resolves outside the synthetic data directory")
    return path
