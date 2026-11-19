from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import ContractError
from tsbench.plugins import discover, resolve


class RegistryContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "catalog").mkdir()
        shutil.copytree(ROOT / "schemas", self.root / "schemas")
        self.registry = self.root / "catalog/plugins.toml"
        self.registry.write_text('schema="bmk.plugin-registry/1"\n[plugins]\n')
        self.package = self.root / "example"
        self.package.mkdir()
        self.manifest = {"schema": "bmk.plugin/1", "id": "test.example", "kind": "codec",
                         "abi_version": 1, "implementation_version": "v1", "format_id": "example.v1",
                         "roles": ["value"], "options_schema": "example/options.json",
                         "source_files": ["example/adapter.c"]}
        self.options = {"type": "object", "additionalProperties": False,
                        "properties": {"level": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5}},
                        "required": ["level"]}
        (self.package / "adapter.c").write_text("/* static discovery fixture, not a runnable codec */")
        self.write_package()

    def write_package(self):
        (self.package / "plugin.json").write_text(json.dumps(self.manifest))
        (self.package / "options.json").write_text(json.dumps(self.options))

    def enable(self, value=True, path="example/plugin.json"):
        self.registry.write_text('schema="bmk.plugin-registry/1"\n[plugins."test.example"]\n'
                                 f'enabled={str(value).lower()}\nmanifest={json.dumps(path)}\n')

    def test_add_remove_disable_without_core_change(self):
        self.assertEqual({}, discover(self.root))
        self.enable()
        self.assertEqual("declared_only", discover(self.root)["test.example"]["status"])
        self.assertEqual({"level": 3}, resolve(self.root, "test.example", {})["options"])
        self.enable(False, "missing.json")
        self.assertEqual("disabled", discover(self.root)["test.example"]["status"])
        with self.assertRaisesRegex(ContractError, "disabled plugin"):
            resolve(self.root, "test.example", {})
        self.registry.write_text('schema="bmk.plugin-registry/1"\n[plugins]\n')
        with self.assertRaisesRegex(ContractError, "unknown plugin"):
            resolve(self.root, "test.example", {})

    def test_replace_and_extend_options_change_identity(self):
        self.enable()
        earlier = copy.deepcopy(resolve(self.root, "test.example", {}))
        (self.package / "adapter.c").write_text("/* changed source; manifest name and path do not change */")
        changed_source = resolve(self.root, "test.example", {})
        self.assertNotEqual(earlier["configuration_id"], changed_source["configuration_id"])
        self.manifest.update(implementation_version="v2", format_id="example.v2")
        self.options["properties"]["mode"] = {"type": "string", "enum": ["default", "narrow"], "default": "default"}
        self.write_package()
        changed = resolve(self.root, "test.example", {"mode": "narrow"})
        self.assertEqual({"level": 3, "mode": "narrow"}, changed["options"])
        self.assertNotEqual(changed_source["configuration_id"], changed["configuration_id"])
        for override in ({"level": True}, {"level": 6}, {"mode": "typo"}, {"unknown": 1}):
            with self.subTest(override=override), self.assertRaises(ContractError):
                resolve(self.root, "test.example", override)

    def test_options_path_cannot_escape(self):
        self.enable()
        self.manifest["options_schema"] = "../options.json"
        self.write_package()
        with self.assertRaisesRegex(ContractError, "asset path"):
            discover(self.root)

    def test_bounded_ordered_array_options(self):
        self.enable()
        self.options["properties"]["thresholds"] = {"type": "array", "minItems": 1, "maxItems": 3,
            "items": {"type": "number", "exclusiveMinimum": 0, "maximum": 20}, "x-order": "strictly-decreasing"}
        self.options["required"].append("thresholds")
        self.write_package()
        first = resolve(self.root, "test.example", {"thresholds": [2, 0.125]})
        second = resolve(self.root, "test.example", {"thresholds": [2, 0.25]})
        self.assertEqual(first["options"]["thresholds"], [2, 0.125])
        self.assertNotEqual(first["configuration_id"], second["configuration_id"])
        for value in ([], True, [True], [0], [21], [2, 2], [1, 2], [4, 3, 2, 1], [float("inf")]):
            with self.subTest(value=value), self.assertRaises(ContractError):
                resolve(self.root, "test.example", {"thresholds": value})
        with self.assertRaisesRegex(ContractError, "missing required"):
            resolve(self.root, "test.example", {})
