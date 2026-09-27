"""Composite display score `cognitive_index_v1` (refinement 01). Pure functions, no DB access.

A descriptive per-assessment summary of the three measured task outcomes — **not** a clinically
validated test, disease stage, probability or new model. Refinement 01 supersedes the guide 02/06
prohibition on a combined score for this versioned, display-only index.

    R = 100 · clamp((3000 − reaction_time_ms) / (3000 − 100), 0, 1)
    index = (memory + attention + R) / 3     (each weight exactly one third)

The 100/3000 ms anchors are the reaction task's response window (display normalization, not
clinical norms). Sleep, mood and medication never contribute points: this project has no
justified conversion from those reports to cognitive ability. The score is never summed across
visits, never imputed from two tasks, and never replaces a missing value with zero.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

COGNITIVE_INDEX_VERSION = "cognitive_index_v1"
SUPPORTED_PROTOCOL_VERSIONS = ("cognitive_tasks_en_v1",)
SUPPORTED_SCORING_VERSIONS = ("cognitive_scoring_v1",)

# Reaction-task response window (services/protocol.py LIMITS): usable latency is [100, 3000) ms.
RT_FLOOR_MS = 100.0
RT_CEILING_MS = 3000.0
SCORE_MIN = 0.0
SCORE_MAX = 100.0
DISPLAY_DECIMALS = 1
DOMAIN_WEIGHT = 1.0 / 3.0

# Reason codes (existing conventions reused where they match).
LOW_QUALITY = "LOW_QUALITY"
INCOMPLETE_ASSESSMENT = "INCOMPLETE_ASSESSMENT"
MISSING_DOMAIN = "MISSING_DOMAIN"
INVALID_DOMAIN_VALUE = "INVALID_DOMAIN_VALUE"
UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
FORECAST_MISSING = "FORECAST_MISSING"


@dataclass(frozen=True)
class Components:
    """Normalized 0–100 values before weighting (response_speed is derived from raw ms)."""

    memory: float
    attention: float
    response_speed: float


@dataclass(frozen=True)
class IndexResult:
    value: float | None
    components: Components | None
    reasons: tuple[str, ...]
    response_speed_clipped: bool


def _float(value: float | Decimal | int | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def response_speed(reaction_time_ms: float) -> tuple[float, bool]:
    """Raw milliseconds → 0–100 response-speed component (faster is higher). Also reports clipping."""
    span = RT_CEILING_MS - RT_FLOOR_MS
    raw = (RT_CEILING_MS - reaction_time_ms) / span
    clamped = min(max(raw, 0.0), 1.0)
    return SCORE_MAX * clamped, clamped != raw


def _supported(protocol_version: str, scoring_version: str) -> bool:
    return protocol_version in SUPPORTED_PROTOCOL_VERSIONS and scoring_version in SUPPORTED_SCORING_VERSIONS


def _score(
    *,
    memory: float | Decimal | int | None,
    attention: float | Decimal | int | None,
    reaction_time_ms: float | Decimal | int | None,
    protocol_version: str,
    scoring_version: str,
    require_rt_in_window: bool,
    extra_reasons: tuple[str, ...] = (),
) -> IndexResult:
    reasons = list(extra_reasons)
    if not _supported(protocol_version, scoring_version):
        reasons.append(UNSUPPORTED_PROTOCOL)
    raw = (memory, attention, reaction_time_ms)
    if any(value is None for value in raw):
        reasons.append(MISSING_DOMAIN)  # missing is never zero and never imputed
    mem, att, rt = (_float(value) for value in raw)
    if None in (mem, att, rt) and MISSING_DOMAIN not in reasons:
        reasons.append(INVALID_DOMAIN_VALUE)  # present but non-finite
    elif mem is not None and att is not None and rt is not None:
        in_score_range = SCORE_MIN <= mem <= SCORE_MAX and SCORE_MIN <= att <= SCORE_MAX
        # Observed values must sit inside the scorer's usable window (a timeout is not a 3000 ms
        # response); forecasts are continuous and only need to be positive before clipping.
        rt_ok = RT_FLOOR_MS <= rt < RT_CEILING_MS if require_rt_in_window else rt > 0
        if not (in_score_range and rt_ok):
            reasons.append(INVALID_DOMAIN_VALUE)
    if reasons:
        return IndexResult(None, None, tuple(dict.fromkeys(reasons)), False)

    assert mem is not None and att is not None and rt is not None
    speed, clipped = response_speed(rt)
    components = Components(memory=mem, attention=att, response_speed=speed)
    value = (components.memory + components.attention + components.response_speed) / 3.0
    return IndexResult(value, components, (), clipped)


def observed_index(
    *,
    quality: str,
    memory_score: float | Decimal | None,
    attention_score: float | Decimal | None,
    reaction_time_ms: float | Decimal | None,
    protocol_version: str,
    scoring_version: str,
) -> IndexResult:
    """Observed composite, or null with reasons. Only quality-VALID assessments get a value."""
    quality_reasons: tuple[str, ...] = ()
    if quality == "INCOMPLETE":
        quality_reasons = (INCOMPLETE_ASSESSMENT,)
    elif quality != "VALID":
        quality_reasons = (LOW_QUALITY,)
    return _score(
        memory=memory_score,
        attention=attention_score,
        reaction_time_ms=reaction_time_ms,
        protocol_version=protocol_version,
        scoring_version=scoring_version,
        require_rt_in_window=True,
        extra_reasons=quality_reasons,
    )


def forecast_index(
    *,
    predicted_memory_score: float | Decimal | None,
    predicted_attention_score: float | Decimal | None,
    predicted_reaction_time_ms: float | Decimal | None,
    protocol_version: str,
    scoring_version: str,
) -> IndexResult:
    """Composite of the *stored* forecast's postprocessed raw-unit predictions.

    A derived projection of existing model outputs, never a separately trained score. The caller
    passes the frozen forecast values only; observed results are never substituted.
    """
    if (
        predicted_memory_score is None
        and predicted_attention_score is None
        and predicted_reaction_time_ms is None
    ):
        return IndexResult(None, None, (FORECAST_MISSING,), False)
    return _score(
        memory=predicted_memory_score,
        attention=predicted_attention_score,
        reaction_time_ms=predicted_reaction_time_ms,
        protocol_version=protocol_version,
        scoring_version=scoring_version,
        require_rt_in_window=False,
    )


def missing_forecast() -> IndexResult:
    return IndexResult(None, None, (FORECAST_MISSING,), False)


def metadata() -> dict[str, object]:
    """Formula metadata for the UI disclosure (identical on every screen)."""
    return {
        "version": COGNITIVE_INDEX_VERSION,
        "supported_protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "supported_scoring_versions": list(SUPPORTED_SCORING_VERSIONS),
        "weights": {"memory": DOMAIN_WEIGHT, "attention": DOMAIN_WEIGHT, "response_speed": DOMAIN_WEIGHT},
        "reaction_time_floor_ms": RT_FLOOR_MS,
        "reaction_time_ceiling_ms": RT_CEILING_MS,
        "scale_min": SCORE_MIN,
        "scale_max": SCORE_MAX,
        "display_decimals": DISPLAY_DECIMALS,
    }
