"""Write docs/release_manifest.json (guide 07 §2, §11.1). No credentials are read or written.

    python3 deploy/release_manifest.py --release r07-local-20260927 \
        --showcase deploy/local-workspace/data/synthetic/showcase/showcase-hosted-v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, cwd=ROOT).stdout.strip()


def tree_hash(paths: list[str]) -> str:
    """Content hash of tracked-source trees (the repo has no commits yet)."""
    digest = hashlib.sha256()
    for base in paths:
        for file in sorted((ROOT / base).rglob("*")):
            if file.is_file() and not any(p in file.parts for p in ("node_modules", ".venv", "__pycache__", "dist", "data", "artifacts", ".auth", "test-results")):
                digest.update(str(file.relative_to(ROOT)).encode())
                digest.update(sha256(file).encode())
    return digest.hexdigest()


def image(ref: str) -> dict[str, str | None]:
    out = sh("docker", "image", "inspect", ref, "--format", "{{.Id}}|{{.Architecture}}|{{.Size}}")
    if not out:
        return {"ref": ref, "id": None}
    image_id, arch, size = out.split("|")
    return {"ref": ref, "id": image_id, "architecture": arch, "size_bytes": size}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True)
    parser.add_argument("--showcase", type=Path, required=True, help="showcase dataset dir (manifest + verification)")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "release_manifest.json")
    args = parser.parse_args()

    commit = sh("git", "rev-parse", "--verify", "-q", "HEAD") or None
    bundle = ROOT / "backend" / "artifacts" / "forecast-run-v1-gru"
    showcase = json.loads((args.showcase / "manifest.json").read_text())
    verification_path = args.showcase / "verification.json"
    verification = json.loads(verification_path.read_text()) if verification_path.exists() else {}
    featured = verification.get("featured", {})
    manifest = {
        "release": args.release,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "git_commit": commit or "uncommitted (repository has no commits)",
            "working_tree_sha256": tree_hash(["backend/app", "backend/alembic", "frontend/src", "deploy", "compose.deploy.yaml"]),
            "lockfiles": {
                "backend/uv.lock": sha256(ROOT / "backend" / "uv.lock"),
                "frontend/package-lock.json": sha256(ROOT / "frontend" / "package-lock.json"),
            },
        },
        "images": {
            "api": image(f"cognuance-api:{args.release}"),
            "web": image(f"cognuance-web:{args.release}"),
            "db": "postgres:17.11@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f",
        },
        "schema": {"alembic_head": "5f30ee0bced4"},
        "api_contract": {"version": "backend_contract_v1", "openapi_sha256": sha256(ROOT / "docs" / "openapi.json")},
        "model": {
            "model_version": "forecast-run-v1-gru",
            "kind": "GRU",
            "policy_version": "policy-v1",
            "bundle_manifest_sha256": sha256(bundle / "manifest.json"),
            "weights_sha256": sha256(bundle / "weights.pt"),
            "policy_sha256": sha256(bundle / "policies" / "policy-v1" / "policy.json"),
        },
        "cognitive_index": "cognitive_index_v1",
        "showcase": {
            "dataset_id": showcase["dataset_id"],
            "seed": showcase["seed"],
            "as_of": showcase["as_of"],
            "presentation_window": showcase["presentation_window"],
            "files": showcase["files"],
            "manifest_sha256": sha256(args.showcase / "manifest.json"),
            "featured": {k: {"patient_id": v["patient_id"], "display_name": v["display_name"]} for k, v in featured.items()},
            "verification": {k: verification.get(k) for k in ("problems", "rescored", "chronology_violations", "alerts", "model_binding")},
        },
        "credentials": "not recorded here (private credential files only)",
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
