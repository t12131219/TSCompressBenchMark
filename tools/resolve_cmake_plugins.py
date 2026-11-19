#!/usr/bin/env python3
"""Resolve enabled or explicitly selected local codec build declarations."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import ContractError, local_file, require  # noqa: E402
from tsbench.plugins import discover, registrations  # noqa: E402


def resolve_plugins(root: Path, selection: str) -> dict:
    index = registrations(root)
    names = ([name for name, entry in index.items() if entry["enabled"]] if selection == "@enabled"
             else selection.split(";") if selection else [])
    require(len(set(names)) == len(names), "duplicate selected plugin")
    for name in names:
        require(name in index, f"unknown plugin: {name}")
        require(index[name]["enabled"], f"disabled plugin: {name}")
    routes = discover(root, selected=set(names))
    packages = {}
    declared_targets = set()
    watch = {"catalog/plugins.toml", "schemas/plugin.schema.json"}
    for name in names:
        item = routes[name]
        manifest = item["manifest"]
        require("build" in manifest, f"no local CMake build declaration for plugin: {name}")
        decl = manifest["build"]
        package = decl["cmake_dir"]
        target = decl["target"]
        recipe = f"{package}/CMakeLists.txt"
        require(recipe in item["source_hashes"], f"CMake entry not bound in plugin source_files: {name}")
        require(local_file(root, recipe) == root / recipe,
                f"CMake entry must be a local package file, not symlinked: {name}")
        require(target not in declared_targets, f"multiple plugin IDs declare CMake target: {target}")
        declared_targets.add(target)
        packages.setdefault(package, []).append({"id": name, "target": target})
        paths = (index[name]["manifest"], manifest["options_schema"], *item["source_hashes"])
        for path in paths:
            require(re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path) is not None,
                    f"unsupported path in CMake configure dependencies: {path!r}")
            watch.add(path)
    # CMake runs one package once even if it supplies multiple codec IDs.
    return {"packages": [{"directory": path, "plugins": values} for path, values in packages.items()],
            "watch": sorted(watch)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--selection", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(resolve_plugins(ROOT, args.selection), ensure_ascii=True))
    except (ContractError, OSError) as exc:
        print(f"plugin build selection rejected: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
