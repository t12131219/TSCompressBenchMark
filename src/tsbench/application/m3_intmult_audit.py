"""Audit the IntMult rows of one sealed M3 corpus run (not stage acceptance)."""
from collections import Counter
import json
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.m3_intmult import KEY
from ..planner.m3_real_corpus import check_m3_real_corpus_plan
from .m3_intmult import audit_intmult


def audit_m3_intmult_run(root: Path, plan: dict, run: Path, *, replay: bool = False) -> dict:
    check_m3_real_corpus_plan(root, plan)
    run = run.resolve(strict=True)
    report_path, ledger_path = (local_file(run, p) for p in ("report.json", "ledger.jsonl"))
    report = load_json(report_path)
    load_contract(root, "m3-real-corpus-run").validate(report, "report")
    seal = load_json(local_file(run, "completion.json"))
    body = {"schema": "bmk.m3-real-corpus-run-seal/1", "run_id": report["run_id"],
            "plan_content_id": plan["plan_content_id"], "report_sha256": digest(report_path),
            "ledger_sha256": digest(ledger_path)}
    require(seal == {**body, "seal_id": content_id(body)} and report["plan_content_id"] == plan["plan_content_id"],
            "M3 report or ledger differs from run seal")
    corpus, obligations = report["rows"], report["obligations"]
    fixtures = report['specialized']['pcodec_intmult']['fixtures']
    products = [{'entry_kind': 'specialized_product', 'selection': KEY[0], 'route': KEY[1], **row}
                for row in fixtures.values()]
    with ledger_path.open(encoding="utf-8") as ledger:
        actual_ledger = [json.loads(line) for line in ledger]
        # Historical IntMult-only runs predate moving the product terminals into the main ledger.
        allowed_legacy = 'pcodec_auto_pages' not in plan.get('specialized', {})
        require(actual_ledger == [*corpus, *products, *obligations] or
                (allowed_legacy and actual_ledger == [*corpus, *obligations]), "M3 ledger differs from its report")
    require(report["statuses"] == dict(Counter(r["status"] for r in corpus)) and
            report["obligation_statuses"] == dict(Counter(r["status"] for r in obligations)),
            "M3 report status totals differ from ledger")
    expected = [x for x in plan["work_items"] if (x["selection"], x["route"]) == KEY]
    actual = [x for x in corpus if (x["selection"], x["route"]) == KEY]
    require(len(expected) == len(actual) == 23 and [r["work_item_id"] for r in actual] == [r["work_item_id"] for r in expected],
            "M3 IntMult real-input decisions are incomplete")
    for row, source in zip(actual, expected, strict=True):
        require((row["status"], row["applicability"], source["applicability"]) == ("outside_declared_domain",) * 3 and
                all(row[k] == source[k] for k in ("dataset_id", "selection", "route", "operation")) and
                row["reason"] == "; ".join(source["reasons"]) and row["evidence"] is None,
                "M3 IntMult floating-point input was not recorded as an excluded decision")
    fields = ("obligation_id", "selection", "route", "check", "kind")
    observed = [o for o in obligations if (o["selection"], o["route"]) == KEY]
    targets = [o for o in plan["obligations"] if (o["selection"], o["route"]) == KEY]
    require(len(observed) == len(targets) == 4 and [tuple(r[k] for k in fields) for r in observed] ==
            [tuple(r[k] for k in fields) for r in targets], "M3 IntMult obligation identities differ from the frozen plan")
    result = audit_intmult(run, plan["specialized"]["pcodec_intmult"], observed,
                           report["specialized"]["pcodec_intmult"], replay=replay)
    return {"schema": "bmk.m3-intmult-audit/1", "run_id": report["run_id"], "plan_content_id": plan["plan_content_id"],
            "run_seal_id": seal["seal_id"], "outside_declared_domain": len(actual), **result,
            "stage_accepted": False, "qualification_granted": False, "timing_admitted": False}
