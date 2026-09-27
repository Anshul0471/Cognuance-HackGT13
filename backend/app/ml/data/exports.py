"""Deterministic file I/O, checksums and manifest handling (guide 03 §5, §8).

JSON is written with sorted keys and fixed separators; gzip uses mtime=0 so identical content
produces identical bytes. `.npz` reproducibility is judged by a logical hash of array contents,
not ZIP container bytes. Missing values are JSON null (NaN is rejected).
"""

import gzip
import hashlib
import io
import json
import os
import platform
import subprocess
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import BACKEND_DIR


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], compress: bool = False) -> None:
    data = "".join(dumps(r) + "\n" for r in rows).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if compress:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, filename="") as gz:
            gz.write(data)
        data = buf.getvalue()
    path.write_bytes(data)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
        for line in fh:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_npz(path: Path, arrays: dict[str, np.ndarray]) -> str:
    """Write arrays; return the logical content hash (names, dtypes, shapes, bytes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    return npz_logical_hash(arrays)


def npz_logical_hash(arrays: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    for name in sorted(arrays):
        arr = np.ascontiguousarray(arrays[name])
        h.update(f"{name}|{arr.dtype.str}|{arr.shape}".encode())
        h.update(arr.tobytes())
    return h.hexdigest()


def load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def file_hashes(root: Path, names: Iterable[str]) -> dict[str, str]:
    out = {}
    for name in sorted(names):
        path = root / name
        out[name] = npz_logical_hash(load_npz(path)) if path.suffix == ".npz" else sha256_file(path)
    return out


def content_hash(hashes: dict[str, str]) -> str:
    return hashlib.sha256(dumps(hashes).encode()).hexdigest()


def environment() -> dict[str, Any]:
    import pandas
    import sklearn

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pandas.__version__,
        "scikit_learn": sklearn.__version__,
    }


def source_revision() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    write_json(tmp, obj)
    os.replace(tmp, path)
