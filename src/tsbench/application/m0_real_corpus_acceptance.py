"""Accept the updated M0 real-corpus binding without granting native qualification."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.native_corpus import verify_native_corpus_plan

SCHEMA = "bmk.m0-real-corpus-stage-receipt/1"
RECEIPT_CONTRACT = "m0-real-corpus-stage-receipt"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def audit_m0_real_corpus(root: Path, *, predecessor: str, corpus_check: str,
                         native_definition: str, binding: str) -> dict:
    """Recompute the new M0 input-binding gate from local evidence.

    The predecessor proves the original M0 skeleton and source/plugin closure.
    This receipt adds the 23-file corpus lock and the fully rederived 36-route
    applicability definition; it deliberately does not execute a codec.
    """
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    previous = load_json(local_file(root, predecessor))
    require(previous.get("stage") == "M0" and previous.get("stage_accepted") is True and
            previous.get("qualification_granted") is False,
            "M0 predecessor is not an accepted freeze/skeleton receipt")

    corpus = load_json(local_file(root, corpus_check))
    require(corpus.get("schema") == "bmk.full-corpus-check/1" and
            corpus.get("datasets") == 23 and corpus.get("source_clusters") == 10 and
            corpus.get("rows") == 434493 and corpus.get("partitions") == 69 and
            corpus.get("raw_hashes_verified") is True and
            corpus.get("canonical_audit_performed") is True and
            corpus.get("execution_performed") is False and
            corpus.get("stage_accepted") is False,
            "updated M0 full-corpus lock is incomplete")

    definition = load_json(local_file(root, native_definition))
    verified = verify_native_corpus_plan(root, definition)
    coverage = verified["coverage"]
    require(coverage == {
        "datasets": 23, "routes": 36, "selections": 12,
        "file_route_decisions": 828,
        "decision_states": {
            "condition_not_triggered": 30,
            "input_domain_matches": 724,
            "outside_declared_domain": 74,
        },
        "required_obligations": 180, "conditional_obligations": 6,
        "executed": 0, "qualified": 0,
        "selections_with_input_domain_match": 12,
    }, "updated M0 native applicability denominator differs")

    bound = load_json(local_file(root, binding))
    require(bound.get("schema") == "bmk.m0-real-corpus-binding/1" and
            bound.get("binding_id") == content_id({k: v for k, v in bound.items() if k != "binding_id"}) and
            bound.get("manifest", {}).get("manifest_id") == corpus.get("manifest_id") and
            bound.get("native_definition", {}).get("plan_content_id") == verified["plan_content_id"],
            "M0 input binding is stale or not content-bound")

    body = {
        "schema": SCHEMA,
        "stage": "M0",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "freeze_contracts_and_real_corpus_binding",
        "evidence": {
            "predecessor": _file_ref(root, predecessor),
            "corpus_check": _file_ref(root, corpus_check),
            "native_definition": _file_ref(root, native_definition),
            "binding": _file_ref(root, binding),
        },
        "coverage": coverage,
        "open_items": [
            "M0 只接纳 23 个原件和 36 条路线的输入适用性定义，不执行 codec",
            "724 个输入域匹配决定和 180/6 项义务仍待 M3 同一计划实际执行",
            "M1–M4 必须绑定本收据，不能继续沿用未绑定新版输入锁的历史收据",
            "ALP AVX512BW、CORAD 质量门和硬件条件仍按真实运行结果记录",
        ],
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "updated M0 real-corpus stage receipt")
    return document
