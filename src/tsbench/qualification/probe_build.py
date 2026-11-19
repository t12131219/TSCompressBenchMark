"""Match a staged worker, adapter and DSO lock to the preflight command."""
from ..assets import content_id, require
from ..runtime import SCHEMA as BUILD_LOCK_SCHEMA


def verify_probe_build_lock(lock, build, plugin_id, *, dependency_count):
    require(isinstance(lock, dict) and lock.keys() == {"build_id", "schema", "worker", "plugins"} and
            lock["schema"] == BUILD_LOCK_SCHEMA and
            lock["build_id"] == content_id({k: v for k, v in lock.items() if k != "build_id"}) and
            isinstance(lock["plugins"], dict) and lock["plugins"].keys() == {plugin_id}, "invalid probe build lock")
    plugin = lock["plugins"][plugin_id]
    require(isinstance(plugin, dict) and plugin.keys() == {"library", "dependencies", "manifest_id", "options_schema_id"} and
            isinstance(plugin["dependencies"], list) and len(plugin["dependencies"]) == dependency_count, "invalid probe build closure")
    refs = [lock["worker"], plugin["library"], *plugin["dependencies"]]
    require(all(isinstance(r, dict) and r.keys() == {"path", "sha256"} and isinstance(r["path"], str) for r in refs) and
            len(build) == len(refs) and {r["path"]: r["sha256"] for r in refs} == build,
            "worker build differs from probe bindings")
