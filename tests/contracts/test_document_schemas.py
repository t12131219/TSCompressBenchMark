from pathlib import Path
import copy
import json
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.api import PlanRequest, load_request, plan  # noqa: E402
from tsbench.assets import ContractError, load_json  # noqa: E402
from tsbench.contracts import load_contract  # noqa: E402
from tsbench.plugins import discover  # noqa: E402


class DocumentSchemaTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("schemas", "catalog", "configs", "datasets", "third_party", "plugins", "include", "cmake", "tools"):
            shutil.copytree(ROOT / name, self.root / name,
                            ignore=shutil.ignore_patterns("unique") if name == "datasets" else None)

    def rewrite(self, relative, key, value):
        file = self.root / relative
        document = load_json(file)
        document[key] = value
        file.write_text(json.dumps(document), encoding="utf-8")

    def test_suite_rejects_unknown_policy_before_planning(self):
        suite = "configs/suites/first_batch_service_v3/suite.json"
        policies = load_json(self.root / suite)["policies"]
        policies["typo_policy"] = True
        self.rewrite(suite, "policies", policies)
        with self.assertRaisesRegex(ContractError, "violates suite schema at /policies"):
            plan(self.root, PlanRequest())

    def test_toml_integer_is_not_float(self):
        (self.root / "request.toml").write_text("schema=1\nmax_workers=2.0\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "experiment schema at /max_workers"):
            load_request(self.root, "request.toml")

    def test_plugin_dependencies_are_not_paths(self):
        self.rewrite("plugins/codecs/zstd/plugin.json", "runtime_dependencies", ["../liblzbench_native.so"])
        with self.assertRaisesRegex(ContractError, "plugin schema at /runtime_dependencies/0"):
            discover(self.root)

    def test_output_cannot_claim_execution_or_qualification(self):
        doc = plan(self.root, PlanRequest()).document
        contract = load_contract(self.root, "matrix")
        for field in ("executed", "qualified"):
            forged = copy.deepcopy(doc)
            forged["coverage"][field] = 1
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, f"/coverage/{field}"):
                contract.validate(forged, "forged draft")

    def test_schema_content_is_bound_into_plan(self):
        base = plan(self.root, PlanRequest()).document
        self.rewrite("schemas/matrix.schema.json", "$comment", "deliberate contract revision")
        revised = plan(self.root, PlanRequest()).document
        self.assertNotEqual(base["bindings"]["contract_schemas"], revised["bindings"]["contract_schemas"])
        self.assertNotEqual(base["plan_content_id"], revised["plan_content_id"])
        self.assertEqual(base["coverage"], revised["coverage"])

    def test_corpus_policy_is_bound_and_cannot_silently_drop_a_dataset(self):
        policy = "catalog/capabilities/corpus_features_v3.json"
        base = plan(self.root, PlanRequest()).document
        lags = load_json(self.root / policy)["seasonal_lag_ticks"]
        lags["uci-electricity-pt"] *= 2
        self.rewrite(policy, "seasonal_lag_ticks", lags)
        revised = plan(self.root, PlanRequest()).document
        self.assertNotEqual(base["bindings"]["corpus_feature_policy"], revised["bindings"]["corpus_feature_policy"])
        self.assertEqual(base["bindings"]["real_corpus"], revised["bindings"]["real_corpus"])
        self.assertEqual(base["coverage"], revised["coverage"])
        del lags["uci-electricity-pt"]
        self.rewrite(policy, "seasonal_lag_ticks", lags)
        with self.assertRaisesRegex(ContractError, "seasonal lag map"):
            plan(self.root, PlanRequest())

    def test_external_schema_reference_is_rejected_offline(self):
        self.rewrite("schemas/experiment.schema.json", "$ref", "https://example.invalid/no-schema.json")
        with self.assertRaisesRegex(ContractError, "unresolved schema reference \\(offline\\)"):
            plan(self.root, PlanRequest())
