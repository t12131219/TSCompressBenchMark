"""Check the prepared Conda prefix against the project-local development lock."""
from pathlib import Path
import sys

from ..assets import content_id, load_json, local_file, require

LOCK = "environment/tsbench-linux-64.lock.json"


def check_tsbench(root: Path) -> str:
    lock = load_json(local_file(root, LOCK))
    require(lock.get("schema") == "bmk.conda-environment/1" and lock.get("environment") == "tsbench" and
            lock.get("platform") == "linux-64", "invalid tsbench environment lock")
    keys = ("name", "version", "build", "subdir", "url", "sha256")
    actual = []
    for path in (Path(sys.prefix) / "conda-meta").glob("*.json"):
        package = load_json(path)
        require(all(key in package for key in keys), f"incomplete Conda metadata: {path.name}")
        actual.append({key: package[key] for key in keys})
    require(sorted(actual, key=lambda p: p["name"]) == lock["packages"], "tsbench package lock mismatch")
    return content_id(lock)
