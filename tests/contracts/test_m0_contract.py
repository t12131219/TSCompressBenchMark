from __future__ import annotations

import ast
import csv
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import PlanRequest, check_sources, load_request, plan
from tsbench.assets import ContractError, content_id, load_json, local_file, verify_asset


class ScopePlanTests(unittest.TestCase):
    def test_exact_denominator_and_no_fake_qualification(self):
        result = plan(ROOT, PlanRequest()).document
        self.assertFalse(result["runnable"])
        self.assertEqual(result["coverage"], {
            "selections": 12, "groups": 17, "atomic_requirements": 22,
            "display_cells": 204, "atomic_relations": 264,
            "executed": 0, "qualified": 0, "unverified_atomic_relations": 264,
        })
        self.assertEqual({9, 11, 19, 85, 7, 31, 40, 39, 4, 29, 87, 80},
                         {row["number"] for row in result["selection_rows"]})
        slots = {slot["slot_id"]: slot for slot in result["required_slots"]}
        self.assertEqual(264, len(slots))
        self.assertEqual(204, len(result["display_cells"]))
        self.assertCountEqual(slots.keys(), [slot for cell in result["display_cells"] for slot in cell["slots"]])
        self.assertTrue(all(s["status"] == "not_run" and s["reasons"] and s["draft_cases"] for s in slots.values()))
        self.assertEqual(content_id({k: v for k, v in result.items() if k != "plan_content_id"}),
                         result["plan_content_id"])

    def test_cli_and_api_and_portable_scope(self):
        result = plan(ROOT, PlanRequest(max_workers=2)).document
        cli = subprocess.run([sys.executable, str(ROOT / "bmk"), "plan", "--max-workers", "2"],
                             cwd="/", check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(cli.stdout), result)
        with tempfile.TemporaryDirectory() as temp:
            relocated = Path(temp) / "repo renamed"
            for name in ("catalog", "schemas", "configs", "datasets", "third_party", "plugins", "include", "cmake", "tools"):
                shutil.copytree(ROOT / name, relocated / name,
                                ignore=shutil.ignore_patterns("unique") if name == "datasets" else None)
            self.assertEqual(json.dumps(plan(relocated, PlanRequest(max_workers=2)).document), json.dumps(result))
            archive = next((relocated / "third_party/archives").iterdir())
            archive.unlink()
            with self.assertRaisesRegex(ContractError, "unavailable local asset"):
                plan(relocated, PlanRequest(max_workers=2))

    def test_valid_resource_override_does_not_change_required_scope(self):
        base = plan(ROOT, PlanRequest()).document
        concurrent_validation = plan(ROOT, PlanRequest(max_workers=4)).document
        self.assertEqual(base["required_slots"], concurrent_validation["required_slots"])
        self.assertNotEqual(base["plan_content_id"], concurrent_validation["plan_content_id"])
        self.assertFalse(concurrent_validation["resolved_execution"]["performance_candidates_concurrent"])

    def test_invalid_overrides_and_unknown_suite(self):
        for request in (PlanRequest(max_workers=True), PlanRequest(max_workers=0), PlanRequest(max_workers=5),
                        PlanRequest(max_workers=1.0), PlanRequest(suite="../escaped"), PlanRequest(suite="unknown")):
            with self.subTest(request=request), self.assertRaises(ContractError):
                plan(ROOT, request)
        cli = subprocess.run([sys.executable, str(ROOT / "bmk"), "plan", "--max-worker", "2"],
                             capture_output=True, text=True)
        self.assertEqual(2, cli.returncode)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            shutil.copytree(ROOT / "schemas", base / "schemas")
            config = base / "plan.toml"
            config.write_text("schema=1\nmax_workers=2\n")
            self.assertEqual(PlanRequest(max_workers=2), load_request(base, "plan.toml"))
            for text in ("schema=1\nselections=[9]\n", "schema=1\nmax_workers=2\nmax_workers=3\n"):
                config.write_text(text)
                with self.assertRaises(ContractError):
                    load_request(base, "plan.toml")

    def test_cli_does_not_overwrite_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "plan.json"
            cmd = [sys.executable, str(ROOT / "bmk"), "plan", "--out", str(file)]
            subprocess.run(cmd, check=True, capture_output=True)
            before = file.read_bytes()
            duplicate = subprocess.run([*cmd, "--max-workers", "2"], capture_output=True)
            self.assertEqual(2, duplicate.returncode)
            self.assertEqual(before, file.read_bytes())


class AssetTests(unittest.TestCase):
    def test_selected_frozen_source_never_reads_unrelated_archive(self):
        lock_path = Path("third_party/sources.lock.json")
        lock = load_json(ROOT / lock_path)
        package = "lzbench-native"
        paths = [lock_path, *(Path(lock[key]["path"]) for key in ("selection_csv", "selection_manifest")),
                 *(Path(lock["sources"][package][key]["path"])
                   for key in ("archive", "source_manifest", "historical_validation"))]
        with tempfile.TemporaryDirectory() as temp:
            stage = Path(temp)
            for relative in paths:
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            selected = check_sources(stage, source_ids={package})
            self.assertEqual({package}, selected["sources"].keys())
            self.assertEqual({39, 40}, {s["number"] for s in selected["selections"]})
            self.assertEqual(5, selected["verified_assets"])
            self.assertEqual(content_id(lock), selected["sources_lock_id"])
            with self.assertRaisesRegex(ContractError, "unavailable local asset"):
                check_sources(stage)

    def test_lexical_and_realpath_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            outside = Path(temp) / "private.txt"
            outside.write_text("external")
            local = root / "owned.txt"
            local.write_text("local")
            (root / "outside-link").symlink_to(outside)
            (root / "local-link").symlink_to("owned.txt")
            self.assertEqual(local, local_file(root, "local-link"))
            for bad in (str(outside), "../private.txt", "./owned.txt", "a//b", "outside-link", "missing"):
                with self.subTest(bad=bad), self.assertRaises(ContractError):
                    local_file(root, bad)
            with self.assertRaisesRegex(ContractError, "SHA-256 mismatch"):
                verify_asset(root, {"path": "owned.txt", "sha256": "0" * 64})

    def test_json_rejects_duplicate_nonfinite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e10000}'):
                path.write_text(raw)
                with self.assertRaises(ContractError):
                    load_json(path)

    def test_native_route_members_bound_to_local_archives(self):
        sources = check_sources(ROOT)["sources"]
        lock = load_json(ROOT / "third_party/sources.lock.json")
        selection_of = {r["number"]: r for r in lock["selections"]}
        data = load_json(ROOT / "catalog/selections/first_batch_native.json")
        self.assertEqual(12, len(data["entries"]))
        for entry in data["entries"]:
            source = sources[selection_of[entry["selection"]]["source_id"]]
            with tarfile.open(verify_asset(ROOT, source["archive"])) as archive:
                self.assertTrue(entry["operations"])
                for op in entry["operations"]:
                    self.assertEqual("not_run", op["qualification"])
                    with archive.extractfile(op["source_member"]) as file:
                        text = file.read().decode("utf-8")
                    for token in op["declaration_tokens"]:
                        self.assertRegex(text, r"\b" + re.escape(token) + r"\b")

    def test_cross_format_fixture_has_equal_values_and_bits(self):
        def npy_data(filename, descr):
            raw = (ROOT / "datasets/fixtures" / filename).read_bytes()
            self.assertEqual(b"\x93NUMPY\x01\x00", raw[:8])
            n = int.from_bytes(raw[8:10], "little")
            header = ast.literal_eval(raw[10:10+n].decode("ascii"))
            self.assertEqual(descr, header["descr"])
            self.assertFalse(header["fortran_order"])
            self.assertEqual(header["shape"][0] * 8, len(raw) - 10 - n)
            return raw[10+n:]

        t = npy_data("t.npy", "<i8")
        v = npy_data("v.npy", "<f8")
        for suffix, delimiter in [("csv", ","), ("txt", "\t")]:
            raw = (ROOT / "datasets/fixtures" / f"t-v.{suffix}").read_text()
            lines = list(csv.DictReader(io.StringIO(raw), delimiter=delimiter))
            self.assertEqual(t, b"".join(struct.pack("<q", int(line["T"])) for line in lines))
            self.assertEqual(v, b"".join(struct.pack("<d", float(line["V"])) for line in lines))


if __name__ == "__main__":
    unittest.main()
