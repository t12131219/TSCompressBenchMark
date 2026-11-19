"""Developer build binding for the CPU worker, separate from qualification.

Only lock trusted local build products. SHA-256 binding detects stale or changed
artifacts, not malicious code or concurrent writes between hashing and execution.
The delivery must run workers from a read-only or privately staged build tree.
"""
from pathlib import Path, PurePosixPath

from .assets import content_id, digest, local_file, require, verify_asset
from .plugins import discover, resolve

SCHEMA = "bmk.worker-build-lock/2"


def _ref(root: Path, relative: str) -> dict:
    return {"path": relative, "sha256": digest(local_file(root, relative))}


def _dependency_paths(relative: str, entry: dict) -> list[str]:
    return [(PurePosixPath(relative).parent / name).as_posix()
            for name in entry["manifest"].get("runtime_dependencies", [])]


def create_build_lock(root: Path, worker: str, libraries: dict[str, str]) -> dict:
    """Bind trusted build outputs explicitly; never discover DSOs by search path."""
    require(isinstance(libraries, dict) and bool(libraries), "no build artifacts to bind")
    registry = discover(root, selected=set(libraries))
    items = {}
    for plugin_id, relative in sorted(libraries.items()):
        require(plugin_id in registry and registry[plugin_id]["enabled"], f"plugin not enabled: {plugin_id}")
        entry = registry[plugin_id]
        items[plugin_id] = {"manifest_id": entry["manifest_id"], "options_schema_id": entry["options_schema_id"],
                            "library": _ref(root, relative), "dependencies": [
                                _ref(root, path) for path in _dependency_paths(relative, entry)]}
    payload = {"schema": SCHEMA, "worker": _ref(root, worker), "plugins": items}
    return {**payload, "build_id": content_id(payload)}


def resolve_worker(root: Path, lock: dict, plugin_id: str, options: dict, *, registry: dict | None = None) -> dict:
    require(isinstance(lock, dict) and lock.keys() == {"schema", "worker", "plugins", "build_id"} and
            lock["schema"] == SCHEMA and isinstance(lock["plugins"], dict), "invalid worker build lock")
    require(lock["build_id"] == content_id({k: v for k, v in lock.items() if k != "build_id"}),
            "worker build lock identity mismatch")
    require(plugin_id in lock["plugins"], f"missing built plugin: {plugin_id}")
    bound = lock["plugins"][plugin_id]
    require(isinstance(bound, dict) and bound.keys() == {"manifest_id", "options_schema_id", "library", "dependencies"},
            "invalid plugin binding in build lock")
    if registry is None:
        registry = discover(root, selected={plugin_id})
    resolved = resolve(root, plugin_id, options, registry=registry)
    for field in ("manifest_id", "options_schema_id"):
        require(resolved[field] == bound[field], f"plugin {field} differs from build lock: {plugin_id}")
    require(isinstance(bound["dependencies"], list), "invalid dependency list in build lock")
    for ref in (lock["worker"], bound["library"], *bound["dependencies"]):
        require(isinstance(ref, dict) and ref.keys() == {"path", "sha256"}, "invalid build file reference")
    expected = _dependency_paths(bound["library"]["path"], registry[plugin_id])
    require([asset["path"] for asset in bound["dependencies"]] == expected, "plugin dependency paths differ from manifest")
    dependencies = [verify_asset(root, asset) for asset in bound["dependencies"]]
    return {**resolved, "dependencies": dependencies, "build_id": lock["build_id"], "worker": verify_asset(root, lock["worker"]),
            "library": verify_asset(root, bound["library"])}
