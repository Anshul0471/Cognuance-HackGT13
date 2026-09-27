"""Family-level partitioning, fixed before any window or statistic is built (guide 03 §9)."""

from typing import Any

from app.ml.data.config import PARTITIONS, DatasetError, GeneratorConfig
from app.ml.data.generator import C_SPLIT, stream


def assign_partitions(config: GeneratorConfig, population: str, family_ids: list[str]) -> dict[str, str]:
    """family_id → partition. Deterministic: sort IDs, permute with a dedicated seeded stream."""
    families = sorted(set(family_ids))
    if len(families) != config.patient_count:
        raise DatasetError(f"expected {config.patient_count} families, found {len(families)}")
    order = stream(config.root_seed, population, 0, C_SPLIT).permutation(len(families))
    assignment: dict[str, str] = {}
    cursor = 0
    for partition in PARTITIONS:
        for i in order[cursor : cursor + config.partition_counts[partition]]:
            assignment[families[int(i)]] = partition
        cursor += config.partition_counts[partition]
    return assignment


def check_isolation(patients: list[dict[str, Any]]) -> None:
    """Every family lives in exactly one partition and every patient has one."""
    seen: dict[str, str] = {}
    for p in patients:
        if p.get("partition") not in PARTITIONS:
            raise DatasetError(f"patient {p['patient_id']} has no valid partition")
        prior = seen.setdefault(p["family_id"], p["partition"])
        if prior != p["partition"]:
            raise DatasetError(f"family {p['family_id']} spans partitions {prior} and {p['partition']}")
