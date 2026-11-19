from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import NativePlanRequest, report_native, run_native  # noqa: E402
from tsbench.assets import ContractError, content_id, load_json  # noqa: E402
from tsbench.contracts import load_contract  # noqa: E402
from tsbench.planner.native import PLAN_SCHEMA, SUITE, _by_name, _resolve_groups, _resolve_test  # noqa: E402


class NativePreflightTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.build = self.root / "build"
        self.build.mkdir()
        self.request = NativePlanRequest(self.build)
        self.results = self.root / "results"
        self.suite = load_json(ROOT / SUITE)

    def test_group_closure_includes_all_and_refuses_truncation(self):
        inventory = load_json(ROOT / "catalog/selections/first_batch_native.json")
        tests = _by_name(self.suite["tests"], "name")
        self.assertEqual(len(_resolve_groups(inventory, self.suite, tests)), 36)
        self.suite["groups"][0]["routes"].pop()
        with self.assertRaisesRegex(ContractError, "route closure"):
            _resolve_groups(inventory, self.suite, tests)

    def test_suite_is_fail_closed_on_policy_changes(self):
        contract = load_contract(ROOT, "native-preflight-suite")
        contract.validate(self.suite, "suite")
        self.suite["policies"]["max_workers"] = 2
        with self.assertRaisesRegex(ContractError, "violates native-preflight-suite"):
            contract.validate(self.suite, "suite")

    def test_output_redirection_and_unsupported_ctest_behavior(self):
        (self.build / "machine").write_text("frozen executable")
        spec = {"name": "probe", "output_arg": "audit.json", "evidence": ["audit.json"]}
        configured = {"properties": [{"name": "WORKING_DIRECTORY", "value": str(self.build)}],
                      "command": [str(self.build / "machine"), str(self.build / "audit.json")]}
        assets = {}
        entry = _resolve_test(spec, configured, self.root, self.build, Path(sys.executable).resolve(), assets)
        self.assertEqual(entry["command"], [{"asset": "build:machine"}, {"output": "audit.json"}])
        self.assertEqual(set(assets), {"build:machine"})
        configured["properties"].append({"name": "WILL_FAIL", "value": True})
        with self.assertRaisesRegex(ContractError, "unsupported CTest execution properties"):
            _resolve_test(spec, configured, self.root, self.build, Path(sys.executable).resolve(), {})

    def fixture(self, script, *, evidence=True, skip=None):
        worker = self.build / "probe"
        worker.write_text(f"#!{sys.executable}\n{script}\n")
        worker.chmod(0o700)
        command = [{"asset": "build:probe"}] + ([{"output": "control.json"}] if evidence else [])
        slot = {"test": "t", "command": command, "timeout_seconds": 5, "skip_returncode": skip,
                "smoke_export": False, "evidence": ["control.json"] if evidence else []}
        body = {"schema": PLAN_SCHEMA, "target_stage": "M0", "evidence_scope": "development_preflight", "runnable": True,
                "qualification_granted": False, "coverage": {"native_groups": 1, "slots": 1},
                "bindings": {"command_inputs": {"build:probe": {"root": "build", "path": "probe"}}},
                "slots": [{"slot_id": content_id(slot), **slot}],
                "groups": [{"selection": 9, "operation": {"route": "test"}, "test": "t"}]}
        return {**body, "plan_content_id": content_id(body)}

    def run_fixture(self, plan, **kwargs):
        with patch("tsbench.application.native.plan_native", return_value=plan):
            result = run_native(self.root, self.request, plan, self.results, **kwargs)
        return result, self.results / result["run_id"]

    def test_recompute_without_build_or_derived_report_and_refuse_tampering(self):
        plan = self.fixture('import sys\nopen(sys.argv[1], "w").write(\'{"ok":true}\')')
        result, run = self.run_fixture(plan)
        self.assertTrue(result["all_probes_passed"])
        self.assertFalse(result["stage_accepted"])
        self.assertEqual(result["operations"][0]["qualification"], "not_run")
        (run / "report.json").unlink()
        (self.build / "probe").unlink()
        self.assertEqual(report_native(run), result)
        next((run / "slots").glob("*/control.json")).write_text("{}")
        with self.assertRaisesRegex(ContractError, "SHA-256 mismatch"):
            report_native(run)

    def test_missing_diagnostic_does_not_pass_even_on_zero_exit(self):
        result, _ = self.run_fixture(self.fixture("pass"))
        self.assertEqual(result["probe_statuses"], {"evidence_failed": 1})
        self.assertFalse(result["all_probes_passed"])

    def test_required_binary_is_not_a_json_diagnostic_and_must_be_present(self):
        plan = self.fixture('import sys\nopen(sys.argv[1], "w").write(\'{"ok":true}\')')
        slot = plan["slots"][0]
        del slot["slot_id"]
        slot["binary_evidence"] = ["frame.bmk"]
        slot["slot_id"] = content_id(slot)
        del plan["plan_content_id"]
        plan["plan_content_id"] = content_id(plan)
        result, _ = self.run_fixture(plan)
        self.assertEqual(result["probe_statuses"], {"evidence_failed": 1})
        with (self.build / "probe").open("a") as stream:
            stream.write('from pathlib import Path\nPath(sys.argv[1]).with_name("frame.bmk").write_bytes(bytes([0,255]))\n')
        result, run = self.run_fixture(plan)
        self.assertTrue(result["all_probes_passed"])
        next((run / "slots").glob("*/frame.bmk")).unlink()
        with self.assertRaisesRegex(ContractError, "unavailable local asset"):
            report_native(run)

    def test_skip_counts_against_preflight_green(self):
        result, _ = self.run_fixture(self.fixture("raise SystemExit(77)", skip=77))
        self.assertEqual(result["probe_statuses"], {"skipped": 1})
        self.assertFalse(result["all_probes_passed"])

    def test_cancelled_slot_and_unsealed_run(self):
        result, run = self.run_fixture(self.fixture("pass", evidence=False), cancelled=lambda: True)
        self.assertEqual(result["probe_statuses"], {"cancelled": 1})
        self.assertIsNone(result["observations"][0]["session_id"])
        (run / "completion.json").unlink()
        with self.assertRaisesRegex(ContractError, "unsealed"):
            report_native(run)

    def test_resealed_stale_plan_refused_before_launch(self):
        plan = self.fixture("raise SystemExit(1)", evidence=False)
        revised = deepcopy(plan)
        del revised["plan_content_id"]
        revised["coverage"]["slots"] = 2
        revised["plan_content_id"] = content_id(revised)
        with patch("tsbench.application.native.plan_native", return_value=plan):
            with self.assertRaisesRegex(ContractError, "bindings changed"):
                run_native(self.root, self.request, revised, self.results)
        self.assertFalse(self.results.exists())

    def test_ledger_cannot_be_shortened_and_reopened(self):
        result, run = self.run_fixture(self.fixture("pass", evidence=False))
        self.assertTrue(result["complete"])
        ledger = run / "observations.jsonl"
        row = json.loads(ledger.read_text())
        ledger.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
        with self.assertRaisesRegex(ContractError, "seal mismatch"):
            report_native(run)
