"""Directional deviations, exhaustive categories and persistence (guide 04 §10, §11, §13).

Pure float64 functions over persisted raw values. No rounding happens before classification.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any

from app.ml.models.postprocessing import DOMAINS

POLICY_SCHEMA_VERSION = "deviation_policy_v1"
AGGREGATE_METHOD = "mean_top_two_v1"
PERSISTENCE_RULE = "consecutive_weekly_representatives_v1"
THRESHOLD_GRID = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0)
SCALE_FLOORS = {"memory": 1.0, "attention": 1.0, "reaction_time_ms": 1.0}
MODERATE_AGGREGATE_MULTIPLIER = 0.8
HIGH_MAX_MULTIPLIER = 2.0
HIGH_MIN_DOMAINS = 2
PERSISTENT_MIN_COUNT = 2


class PolicyError(ValueError):
    """Malformed policy: produces ANALYSIS_ERROR, never NORMAL."""


@dataclass(frozen=True)
class PolicyRules:
    scales: dict[str, float]
    r: float
    moderate_aggregate_multiplier: float = MODERATE_AGGREGATE_MULTIPLIER
    high_max_multiplier: float = HIGH_MAX_MULTIPLIER
    high_min_domains: int = HIGH_MIN_DOMAINS
    persistent_min_count: int = PERSISTENT_MIN_COUNT
    aggregate_method: str = AGGREGATE_METHOD

    def __post_init__(self) -> None:
        if set(self.scales) != set(DOMAINS):
            raise PolicyError("policy scales must cover memory, attention and reaction_time_ms")
        for d, s in self.scales.items():
            if not isinstance(s, int | float) or isinstance(s, bool) or not math.isfinite(s) or s <= 0:
                raise PolicyError(f"scale for {d} must be a positive finite number")
        if not math.isfinite(self.r) or self.r <= 0:
            raise PolicyError("threshold r must be positive and finite")
        if self.aggregate_method != AGGREGATE_METHOD:
            raise PolicyError("unsupported aggregate method")

    @classmethod
    def from_configuration(cls, cfg: dict[str, Any]) -> "PolicyRules":
        try:
            rules = cfg["rules"]
            return cls(
                scales={d: float(cfg["scales"][d]["scale"]) for d in DOMAINS},
                r=float(rules["r"]),
                moderate_aggregate_multiplier=float(rules["moderate_aggregate_multiplier"]),
                high_max_multiplier=float(rules["high_max_multiplier"]),
                high_min_domains=int(rules["high_min_domains"]),
                persistent_min_count=int(rules["persistent_min_count"]),
                aggregate_method=str(rules["aggregate_method"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, PolicyError):
                raise
            raise PolicyError(f"malformed policy configuration: {exc}") from None


@dataclass(frozen=True)
class DomainDeviation:
    observed: float
    predicted: float
    residual: float  # actual - predicted (signed)
    worsening: float  # positive = worse than forecast
    scale: float
    z: float  # max(0, worsening / scale)


@dataclass(frozen=True)
class Evaluation:
    domains: dict[str, DomainDeviation]
    max_deviation: float  # M
    aggregate_deviation: float  # A = mean of the two largest z
    moderate_signal: bool
    high_signal: bool
    domains_at_or_above_r: list[str]
    conditions_met: list[str]
    persistent_count: int
    level: str

    def domain_json(self) -> dict[str, Any]:
        return {d: asdict(v) for d, v in self.domains.items()}


def _finite(values: tuple[float, float, float], what: str) -> tuple[float, float, float]:
    out = tuple(float(v) for v in values)
    if len(out) != 3 or not all(math.isfinite(v) for v in out):
        raise PolicyError(f"{what} must be three finite values")
    return out  # type: ignore[return-value]


def deviations(
    predicted: tuple[float, float, float], observed: tuple[float, float, float], rules: PolicyRules
) -> dict[str, DomainDeviation]:
    p = _finite(predicted, "predicted values")
    a = _finite(observed, "observed values")
    worsening = {
        "memory": p[0] - a[0],
        "attention": p[1] - a[1],
        "reaction_time_ms": a[2] - p[2],  # slower is worse
    }
    out = {}
    for i, d in enumerate(DOMAINS):
        scale = rules.scales[d]
        out[d] = DomainDeviation(
            observed=a[i],
            predicted=p[i],
            residual=a[i] - p[i],
            worsening=worsening[d],
            scale=scale,
            z=max(0.0, worsening[d] / scale),
        )
    return out


def signals(z: dict[str, float], rules: PolicyRules) -> tuple[float, float, bool, bool, list[str], list[str]]:
    values = sorted((z[d] for d in DOMAINS), reverse=True)
    m = values[0]
    a = (values[0] + values[1]) / 2.0
    r = rules.r
    at_r = [d for d in DOMAINS if z[d] >= r]
    conditions = []
    if m >= r:
        conditions.append("MAX_AT_OR_ABOVE_R")
    if a >= rules.moderate_aggregate_multiplier * r:
        conditions.append("AGGREGATE_AT_OR_ABOVE_0.8R")
    if m >= rules.high_max_multiplier * r:
        conditions.append("MAX_AT_OR_ABOVE_2R")
    if len(at_r) >= rules.high_min_domains:
        conditions.append("TWO_OR_MORE_DOMAINS_AT_OR_ABOVE_R")
    moderate = m >= r or a >= rules.moderate_aggregate_multiplier * r
    high = m >= rules.high_max_multiplier * r or len(at_r) >= rules.high_min_domains
    return m, a, moderate or high, high, at_r, conditions


def next_persistent_count(moderate: bool, prior_count: int) -> int:
    """`prior_count` is the qualifying previous-slot streak (0 when the chain is broken)."""
    if not moderate:
        return 0
    return prior_count + 1 if prior_count > 0 else 1


def classify(moderate: bool, high: bool, persistent_count: int, rules: PolicyRules) -> str:
    if high:
        return "HIGH_DEVIATION"
    if moderate and persistent_count >= rules.persistent_min_count:
        return "PERSISTENT_DEVIATION"
    if moderate:
        return "REVIEW"
    return "NORMAL"


def evaluate_z(
    z: dict[str, float], rules: PolicyRules, prior_count: int
) -> tuple[float, float, bool, bool, int, str]:
    m, a, moderate, high, _, _ = signals(z, rules)
    count = next_persistent_count(moderate, prior_count)
    return m, a, moderate, high, count, classify(moderate, high, count, rules)


def evaluate(
    predicted: tuple[float, float, float],
    observed: tuple[float, float, float],
    rules: PolicyRules,
    prior_count: int,
) -> Evaluation:
    doms = deviations(predicted, observed, rules)
    z = {d: v.z for d, v in doms.items()}
    m, a, moderate, high, at_r, conditions = signals(z, rules)
    count = next_persistent_count(moderate, prior_count)
    return Evaluation(
        domains=doms,
        max_deviation=m,
        aggregate_deviation=a,
        moderate_signal=moderate,
        high_signal=high,
        domains_at_or_above_r=at_r,
        conditions_met=conditions,
        persistent_count=count,
        level=classify(moderate, high, count, rules),
    )
