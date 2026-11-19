"""Static plugin discovery and strict per-plugin option resolution.

This module performs no native loading. Manifest discovery is not admission.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
import tomllib

from .assets import ContractError, content_id, digest, load_json, local_file, require
from .contracts import Contract, load_contract


_ID = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_TYPES = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}


def _definition(root: Path, name: str, relative: str, contract: Contract) -> tuple[dict, dict[str, str]]:
    manifest = load_json(local_file(root, relative))
    contract.validate(manifest, relative)
    require(manifest["id"] == name, f"plugin binding mismatch: {name}")
    require(type(manifest["abi_version"]) is int, f"unsupported plugin ABI: {name}")
    source_hashes = {asset: digest(local_file(root, asset)) for asset in manifest["source_files"]}
    return manifest, source_hashes


def registrations(root: Path) -> dict:
    index = local_file(root, "catalog/plugins.toml")
    try:
        text = tomllib.loads(index.read_text(encoding="utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"invalid plugin registry: {exc}") from exc
    require(text.keys() == {"schema", "plugins"} and text["schema"] == "bmk.plugin-registry/1"
            and isinstance(text["plugins"], dict), "invalid plugin registry schema")
    for name, entry in text["plugins"].items():
        require(_ID.fullmatch(name) is not None and isinstance(entry, dict) and
                entry.keys() == {"enabled", "manifest"} and type(entry["enabled"]) is bool and
                type(entry["manifest"]) is str,
                f"invalid plugin registration: {name}")
    return text["plugins"]


def discover(root: Path, *, selected: set[str] | None = None) -> dict:
    index = registrations(root)
    result = {}
    contract = load_contract(root, "plugin")
    for name, entry in index.items():
        if selected is not None and name not in selected:
            continue
        if not entry["enabled"]:
            result[name] = {"enabled": False, "status": "disabled"}
            continue
        manifest, source_hashes = _definition(root, name, entry["manifest"], contract)
        options = load_json(local_file(root, manifest["options_schema"]))
        _resolve_options(options, {}, validate_only=True)
        result[name] = {"enabled": True, "status": "declared_only", "manifest": manifest,
                        "manifest_id": content_id({"manifest": manifest, "source_hashes": source_hashes,
                                                   "contract_schema_id": contract.document_id}),
                        "source_hashes": source_hashes, "options_schema_id": content_id(options),
                        "options_schema": options}
    return result


def _option_value(name: str, spec: dict, value, *, check_enum: bool = True):
    kind = spec["type"]
    if kind == "array":
        require(type(value) is list, f"wrong type for plugin option: {name}")
        require(spec["minItems"] <= len(value) <= spec["maxItems"], f"plugin option array length: {name}")
        result = [_option_value(f"{name}[{i}]", spec["items"], item) for i, item in enumerate(value)]
        if spec.get("x-order") == "strictly-decreasing":
            require(all(left > right for left, right in zip(result, result[1:])),
                    f"plugin option must be strictly decreasing: {name}")
        return result
    require(type(value) in _TYPES[kind], f"wrong type for plugin option: {name}")
    if type(value) is float:
        require(math.isfinite(value), f"non-finite plugin option: {name}")
    if check_enum and "enum" in spec:
        require(any(type(match) is type(value) and match == value for match in spec["enum"]),
                f"unknown enum value for plugin option: {name}")
    for bound, within in (("minimum", lambda x, y: x >= y), ("maximum", lambda x, y: x <= y),
                          ("exclusiveMinimum", lambda x, y: x > y)):
        if bound in spec:
            require(within(value, spec[bound]), f"plugin option outside {bound}: {name}")
    return value


def _validate_spec(name: str, spec: dict, *, array_allowed: bool = True) -> None:
    require(isinstance(spec, dict), f"unsupported option schema: {name}")
    kind = spec.get("type")
    if kind == "array" and array_allowed:
        require({"type", "minItems", "maxItems", "items"} <= spec.keys() <=
                {"type", "minItems", "maxItems", "items", "default", "x-order"}
                and type(spec["minItems"]) is int and type(spec["maxItems"]) is int
                and 0 <= spec["minItems"] <= spec["maxItems"] <= 1024, f"invalid option array bounds: {name}")
        _validate_spec(f"{name}[]", spec["items"], array_allowed=False)
        require("default" not in spec["items"], f"array items may not have defaults: {name}")
        if "x-order" in spec:
            require(spec["x-order"] == "strictly-decreasing" and spec["items"]["type"] in ("integer", "number"),
                    f"unsupported option array order: {name}")
        return
    require(isinstance(kind, str) and kind in _TYPES and
            spec.keys() <= {"type", "enum", "minimum", "maximum", "exclusiveMinimum", "default"},
            f"unsupported option schema: {name}")
    for key in {"minimum", "maximum", "exclusiveMinimum"} & spec.keys():
        require(kind in {"integer", "number"} and type(spec[key]) in _TYPES[kind]
                and (type(spec[key]) is int or math.isfinite(spec[key])),
                f"invalid numeric bound for plugin option: {name}")
    if "maximum" in spec:
        require(("minimum" not in spec or spec["minimum"] <= spec["maximum"])
                and ("exclusiveMinimum" not in spec or spec["exclusiveMinimum"] < spec["maximum"]),
                f"invalid range for plugin option: {name}")
    if "enum" in spec:
        require(isinstance(spec["enum"], list) and bool(spec["enum"]), f"invalid enum: {name}")
        for possible in spec["enum"]:
            _option_value(name, spec, possible, check_enum=False)


def _resolve_options(options: dict, overrides: dict, *, validate_only: bool = False) -> dict:
    require(isinstance(options, dict) and options.get("type") == "object" and
            options.get("additionalProperties") is False and
            options.keys() == {"type", "additionalProperties", "properties", "required"} and
            isinstance(options["properties"], dict), "unsupported plugin options schema")
    properties = options["properties"]
    required = options["required"]
    require(isinstance(required, list) and len(required) == len(set(required)) and set(required) <= properties.keys(),
            "invalid required plugin options")
    require(isinstance(overrides, dict) and overrides.keys() <= properties.keys(), "unknown plugin option(s)")
    resolved = {}
    for name, spec in properties.items():
        _validate_spec(name, spec)
        if "default" in spec:
            resolved[name] = _option_value(name, spec, spec["default"])
        if name in overrides:
            resolved[name] = _option_value(name, spec, overrides[name])
    if not validate_only:
        missing = set(required) - resolved.keys()
        require(not missing, f"missing required plugin option(s): {', '.join(sorted(missing))}")
    return resolved


def resolve(root: Path, plugin_id: str, overrides: dict, *, registry: dict | None = None) -> dict:
    if registry is None:
        registry = discover(root, selected={plugin_id})
    require(plugin_id in registry, f"unknown plugin: {plugin_id}")
    route = registry[plugin_id]
    require(route["enabled"], f"disabled plugin: {plugin_id}")
    values = _resolve_options(route["options_schema"], overrides)
    return {"id": plugin_id, "manifest_id": route["manifest_id"],
            "options_schema_id": route["options_schema_id"], "options": values,
            "configuration_id": content_id([route["manifest_id"], route["options_schema_id"], values])}
