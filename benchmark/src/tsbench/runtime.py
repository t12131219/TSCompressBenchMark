"""Explicit worker loader settings and evidence from the running Linux process."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .records import file_hash


def preload_identity(paths: list[str]) -> list[dict[str, str]]:
    return [{'requested_path': value, 'resolved_path': str(Path(value).resolve(strict=True)),
             'sha256': file_hash(Path(value))} for value in paths]


def worker_environment(base: dict[str, str], profile: dict[str, Any]) -> dict[str, str]:
    environment = base.copy()
    requested = profile.get("runtime_preload", [])
    for value in requested:
        path = Path(value)
        if not path.is_absolute() or not path.is_file() or any(c.isspace() for c in value) or ":" in value:
            raise ValueError("runtime_preload requires existing absolute library paths without loader separators")
    inherited = environment.get("LD_PRELOAD", "")
    if requested:
        environment["LD_PRELOAD"] = " ".join(requested) + (" " + inherited if inherited else "")
    return environment


def loaded_runtime(dependencies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Bind runtime identity to mapped files, rather than an ldd subprocess's choice."""
    preload = os.environ.get("LD_PRELOAD", "")
    requested = preload.replace(":", " ").split()
    requested_targets = {Path(value).resolve(strict=True) for value in requested if Path(value).is_absolute()}
    names = {"libstdc++", "libgcc_s"}
    names.update(Path(item["path"]).name.split(".so")[0] for item in dependencies or [])
    names.update(Path(value).name.split(".so")[0] for value in requested)
    maps = Path("/proc/self/maps")
    if not maps.is_file():
        return {"ld_preload": preload, "implemented": False, "reason": "/proc/self/maps unavailable", "libraries": []}
    paths = set()
    for line in maps.read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith("/"):
            path = Path(fields[5])
            if path.name.split(".so")[0] in names or path.resolve() in requested_targets:
                if not path.is_file():
                    raise RuntimeError(f"loaded runtime file is missing or deleted: {path}")
                paths.add(path.resolve())
    libraries = [{"path": str(path), "sha256": file_hash(path)} for path in sorted(paths)]
    for value in requested:
        if Path(value).is_absolute() and Path(value).resolve() not in paths:
            raise RuntimeError(f"requested runtime preload was not mapped: {value}")
    return {"ld_preload": preload, "implemented": True, "mechanism": "/proc/self/maps", "libraries": libraries}
