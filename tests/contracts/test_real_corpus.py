import gzip
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import PlanRequest, check_corpus, plan
from tsbench.assets import ContractError, digest, load_json
from tsbench.corpus import DOMAINS, INTAKE_V1, INTAKE_V2, MANIFEST, MANIFEST_V1, MANIFEST_V3, audit_asset, civil_seconds, f64
from tsbench.planner.corpus_windows import bind_training_window, bind_window, read_labeled_tv_window, read_tv_window, read_window


class RealCorpusTests(unittest.TestCase):
    def test_real_corpus_is_local_and_scope_stays_unqualified(self):
        actual = check_corpus(ROOT, parse=True)
        self.assertEqual(actual["rows"], 222574)
        self.assertEqual((actual["source_clusters"], actual["partitions"]), (6, 18))
        self.assertEqual(actual["included_domains"], list(DOMAINS))
        self.assertEqual(actual["missing_domains"], [])
        matrix = plan(ROOT, PlanRequest()).document
        self.assertEqual(matrix["bindings"]["real_corpus"], actual["corpus_id"])
        self.assertFalse(matrix["runnable"])
        self.assertFalse(matrix["corpus"]["canonical_audit_performed"])
        self.assertEqual(matrix["coverage"]["qualified"], 0)
        audit = load_json(ROOT / MANIFEST)["datasets"][1]["audit"]
        self.assertEqual(audit["timestamp_steps"]["duplicates"], 1)
        self.assertEqual(audit["timestamp_steps"]["positive_non_nominal"], 1)
        self.assertGreater(audit["literal_minus_9999"], 0)

    def test_versioned_extension_preserves_v1_and_windows(self):
        legacy = check_corpus(ROOT, MANIFEST_V1)
        self.assertEqual(legacy["corpus_id"], "110d2ee7a39eda51a9780f0c848e7f2b6e5a3614d84255b53a75b2950857a4e8")
        self.assertEqual(load_json(ROOT / MANIFEST)["datasets"][:2], load_json(ROOT / MANIFEST_V1)["datasets"])
        current = check_corpus(ROOT, MANIFEST)
        self.assertEqual(current["corpus_id"], "a9904b1ce2068186e1c3e47eccf406e030d9e73973defe50d0508c91334929b3")
        for dataset, column, offset, values in (
            ("unique-forecast-traffic", "channel_0", 0, (0.012000, 0.006400)),
            ("unique-forecast-exchange", "rate_OT", 0, (0.800064, 0.805088)),
            ("unique-forecast-exchange", "rate_OT", 1743, (0.692689,)),
        ):
            with self.subTest(dataset=dataset, offset=offset):
                request = dict(dataset=dataset, column=column, partition="test", offset=offset, count=len(values))
                bound = bind_window(ROOT, MANIFEST, current["corpus_id"], request)
                self.assertEqual(read_window(ROOT, bound), struct.pack("<" + "d" * len(values), *values))
                with self.assertRaisesRegex(ContractError, "held-out"):
                    bind_window(ROOT, MANIFEST, current["corpus_id"], {**request, "partition": "development"})
        request["count"] = 2
        with self.assertRaisesRegex(ContractError, "crosses its frozen partition"):
            bind_window(ROOT, MANIFEST, current["corpus_id"], request)

    def test_v3_offline_import_rebuild_and_axis_roundtrip(self):
        manifest = load_json(ROOT / MANIFEST_V3)
        self.assertEqual(manifest["datasets"][:4], load_json(ROOT / MANIFEST)["datasets"])
        corpus_id = check_corpus(ROOT)["corpus_id"]
        for name, column, unit, ticks in (
            ("westermo-system1", "cpu-user", "second", (86400, 86430)),
            ("ceda-cmip6-gsat", "ACCESS-CM2", "year", (1964, 1965)),
        ):
            with self.subTest(name=name):
                ref = bind_window(ROOT, MANIFEST_V3, corpus_id, dict(dataset=name, column=column, partition="test", offset=0, count=2))
                axis, t, v = read_labeled_tv_window(ROOT, ref)
                self.assertEqual(axis["unit"], unit)
                self.assertIsNone(axis["timezone"])
                self.assertEqual(struct.unpack("<qq", t), ticks)
                self.assertEqual(read_window(ROOT, ref), v)
                with self.assertRaisesRegex(ContractError, "not a civil-second window"):
                    read_tv_window(ROOT, ref)
                with self.assertRaisesRegex(ContractError, "time-axis binding"):
                    read_labeled_tv_window(ROOT, {**ref,"time_axis":{**axis,"timezone":"UTC"}})
        with tempfile.TemporaryDirectory() as temp:
            staged = Path(temp)
            subprocess.run([sys.executable, "-B", str(ROOT / "tools/import_domain_corpus.py"), "--out", temp],
                           check=True, cwd="/", capture_output=True)
            for filename in (MANIFEST_V3, *(d["asset"]["path"] for d in manifest["datasets"][4:])):
                self.assertEqual(digest(ROOT / filename), digest(staged / filename))

    def test_v2_requires_bound_base_and_does_not_use_the_raw_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            for name in ("datasets", "schemas"):
                shutil.copytree(ROOT / name, sandbox / name, ignore=shutil.ignore_patterns("unique"))
            self.assertEqual(check_corpus(sandbox, MANIFEST), check_corpus(ROOT, MANIFEST))
            target = sandbox / MANIFEST
            manifest = load_json(target)
            path = sandbox / INTAKE_V2
            intake = load_json(path)
            intake["base_intake"]["sha256"] = "0" * 64
            path.write_text(json.dumps(intake))
            manifest["intake"]["sha256"] = digest(path)
            target.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError, "SHA-256 mismatch.*first-batch-real-intake.json"):
                check_corpus(sandbox, MANIFEST)
            # A fully matching V1 reference must still be rejected in a V2 manifest.
            manifest["intake"] = {"path": INTAKE_V1, "sha256": digest(sandbox / INTAKE_V1)}
            target.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError, "violates corpus schema at /intake/path"):
                check_corpus(sandbox, MANIFEST)

    def test_training_always_stops_before_held_out_data(self):
        frozen = check_corpus(ROOT, MANIFEST)
        spec = load_json(ROOT / MANIFEST)["datasets"][1]
        training = spec["audit"]["partitions"]["train"]
        request = dict(dataset=spec["id"], column="co2", partition="train", offset=training["rows"]-1, count=1)
        ref = bind_training_window(ROOT, MANIFEST, frozen["corpus_id"], request)
        stamp, values = read_tv_window(ROOT, ref)
        self.assertEqual(struct.unpack("<q", stamp), (civil_seconds(training["last_timestamp"]),))
        self.assertEqual(len(values), 8)
        with self.assertRaisesRegex(ContractError, "crosses its frozen partition"):
            bind_training_window(ROOT, MANIFEST, frozen["corpus_id"], {**request, "count": 2})
        with self.assertRaisesRegex(ContractError, "length differs"):
            read_window(ROOT, {**ref, "count": 2})
        with self.assertRaisesRegex(ContractError, "requires a frozen train"):
            bind_training_window(ROOT, MANIFEST, frozen["corpus_id"], {**request, "partition": "test"})
        with self.assertRaisesRegex(ContractError, "held-out"):
            bind_window(ROOT, MANIFEST, frozen["corpus_id"], request)

    def test_original_copy_and_wrong_split_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            for name in ("datasets", "schemas"):
                shutil.copytree(ROOT / name, sandbox / name,
                                ignore=shutil.ignore_patterns("unique") if name == "datasets" else None)
            target = sandbox / MANIFEST
            doc = load_json(target)
            doc["datasets"][0]["audit"]["partitions"]["train"]["last_timestamp"] = "2013-01-01 00:00:00"
            target.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ContractError, "chronological bounds"):
                check_corpus(sandbox, MANIFEST)
            shutil.copyfile(ROOT / MANIFEST, target)
            with (sandbox / "datasets/raw/original/weather.csv").open("ab") as out:
                out.write(b"tampered\n")
            with self.assertRaisesRegex(ContractError, "SHA-256 mismatch.*weather.csv"):
                check_corpus(sandbox, MANIFEST)

    def test_canonical_parser_preserves_bits_and_rejects_implicit_coercion(self):
        self.assertEqual(f64("-0,0", ","), struct.pack("<Q", 1 << 63))
        self.assertEqual(f64("1,25", ","), struct.pack("<d", 1.25))
        self.assertEqual(civil_seconds("1969-12-31 23:59:59"), -1)
        for token in ("", "1.2", "nan", "+Inf", " 1", "1e2"):
            with self.subTest(token=token), self.assertRaises(ContractError):
                f64(token, ",")
        with self.assertRaises(ContractError):
            civil_seconds("1970-01-01 00:00:00Z")
        spec = load_json(ROOT / MANIFEST)["datasets"][0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.gz"
            path.write_bytes(gzip.compress(b"timestamp;wrong\n1997-01-01T00:00:00;7\n"))
            with self.assertRaisesRegex(ContractError, "header mismatch"):
                audit_asset(path, spec)
