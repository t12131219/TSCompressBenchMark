"""M3 IntMult fixtures are a separate denominator from the floating-point corpus."""
import json
from pathlib import Path

import pytest

from tsbench.application import m3_real_corpus_execution as execution
from tsbench.assets import ContractError, content_id, digest, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "results/m3-real-r15-20261119/plan.json"
pytestmark = pytest.mark.skipif(not PLAN.exists(), reason="requires local M3 plan with the new IntMult binding")


def test_plan_rejects_resealed_fixture_substitution():
    plan = load_json(PLAN)
    load_contract(ROOT, "m3-real-corpus-plan").validate(plan, "plan")
    binding = plan["specialized"]["pcodec_intmult"]
    positive = next(s for s in binding["slots"].values() if s["name"] == "wide-base")
    assert positive["base"] > 2**53
    positive["base"] = int(float(positive["base"]))
    plan["plan_content_id"] = content_id({k: v for k, v in plan.items() if k != "plan_content_id"})
    with pytest.raises(ContractError, match="IntMult execution binding differs"):
        check_m3_real_corpus_plan(ROOT, plan)


def test_one_ledger_covers_domain_exclusions_and_specialized_rows(tmp_path, monkeypatch):
    plan = load_json(PLAN)
    # Run orchestration branches with no native or corpus stage. The actual
    # isolation and result validators are exercised by the new IntMult preflight.
    monkeypatch.setattr(execution, "check_m3_real_corpus_plan", lambda _, p: None)
    monkeypatch.setattr(execution, "_entry_map", lambda *args: {})

    def fail_to_setup(_root, _run, binding, rows):
        assert {r["obligation_id"] for r in rows} == binding["obligation_slots"].keys()
        for row in rows:
            row.update(status="dependency_failed", reason="test setup failure")
        return {"fixtures": {}, "statuses": {}, "files": {}}

    monkeypatch.setattr(execution, "run_intmult", fail_to_setup)
    report = execution.run_m3_real_corpus(ROOT, plan, tmp_path, route_filter={"intmult"})
    load_contract(ROOT, "m3-real-corpus-run").validate(report, "report")
    assert report["partial_preflight"] and not report["stage_accepted"]
    assert report["selected_work_items"] == 0 and report["selected_corpus_decisions"] == 23
    assert report["statuses"] == {"outside_declared_domain": 23}
    assert report["obligation_statuses"] == {"dependency_failed": 4}
    run = tmp_path / report["run_id"]
    ledger = run / "ledger.jsonl"
    assert [json.loads(line) for line in ledger.read_text().splitlines()] == [*report["rows"], *report["obligations"]]
    seal = load_json(run / "completion.json")
    assert seal["ledger_sha256"] == digest(ledger)
    assert seal["report_sha256"] == digest(run / "report.json")


def test_unfiltered_dispatch_does_not_drop_unbound_obligations_or_outside_domain_decisions(tmp_path, monkeypatch):
    plan = load_json(PLAN)
    # Emulate an executor with no available native drivers to exercise only the
    # report denominator, without consuming real input or granting acceptance.
    plan["specialized"] = {}
    plan["build"] = {k: v for k, v in plan["build"].items() if k not in ("pcodec_pages", "titchy_access", "titchy_stream")}
    monkeypatch.setattr(execution, "check_m3_real_corpus_plan", lambda *_: None)
    monkeypatch.setattr(execution, "_entry_map", lambda *_: {})
    monkeypatch.setattr(execution, "_relevant", lambda _: False)
    report = execution.run_m3_real_corpus(ROOT, plan, tmp_path)
    assert report["selected_corpus_decisions"] == 828 and report["selected_work_items"] == 724
    assert report["statuses"] == {"condition_not_triggered": 30, "outside_declared_domain": 74, "pending_driver": 724}
    assert report["obligation_statuses"] == {"not_run": 186}
    assert not report["stage_accepted"] and not report["qualification_granted"]
    assert len((tmp_path / report["run_id"] / "ledger.jsonl").read_text().splitlines()) == 828 + 186
