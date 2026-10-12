"""Freeze current-source revisions of the exact historical 16-lane decisions.

Only plan construction and file hashing run here. No qualification, codec,
pilot or performance observations are transferred from the earlier runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from rebind_v32_comparison_sources import rebind_document, semantic_projection  # noqa: E402

from tscompbench.ids import canonical_json_bytes  # noqa: E402


def ref(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def save(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(canonical_json_bytes(document) + b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="20261011-closure-formal-r1")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        parser.error("choose a new project output directory and retain old evidence")
    historical_root = ROOT / "build/v32-evidence-20261010/current-r2"
    declaration_path = historical_root / "declaration-release-r4.json"
    declaration = json.loads(declaration_path.read_text())
    protocols = {
        "stream": "configs/comparisons/g-stream-ll-v32-20261010-v4-protocol.json",
        "query-warm": "configs/comparisons/g-query-ll-variants-v32-20261010-v4-protocol.json",
        "query-fresh": (
            "configs/comparisons/g-query-ll-variants-v32-20261010-v4-fresh-protocol.json"
        ),
    }
    lanes, receipts = [], []
    # The timestamp profile retains its complete 10800-second development budget.
    order = [
        "byte",
        "f64",
        "i16",
        "abs",
        "f32",
        "quality",
        "model",
        "cold",
        "api",
        "entropy",
        "u8",
        "timestamp",
    ]
    for kind, names in (
        ("comparison", order),
        ("workload", ["stream", "query-warm", "query-fresh"]),
    ):
        table = declaration["comparisons" if kind == "comparison" else "workloads"]
        for name in names:
            base = historical_root / table[name] / "bundle.json"
            old = json.loads(base.read_text())
            bundle, proof = rebind_document(ROOT, old, args.revision)
            if semantic_projection(old) != semantic_projection(bundle):
                raise ValueError("non-source decisions changed: " + name)
            bundle_path = output / "bundles" / (name + ".json")
            proof_path = output / "proofs" / (name + ".json")
            save(bundle_path, bundle)
            proof.update(
                base_bundle=ref(base),
                output_bundle=ref(bundle_path),
                preparation_driver=ref(Path(__file__)),
            )
            save(proof_path, proof)
            lane = {"kind": kind, "run_set_id": name, "bundle": str(bundle_path.relative_to(ROOT))}
            if kind == "workload":
                protocol_path = ROOT / protocols[name]
                copied = output / "protocols" / (name + ".json")
                copied.parent.mkdir(parents=True, exist_ok=True)
                with copied.open("xb") as handle:
                    handle.write(protocol_path.read_bytes())
                lane["protocol"] = str(copied.relative_to(ROOT))
                lane["historical_protocol"] = ref(protocol_path)
            lanes.append(lane)
            receipts.append(
                {
                    "lane": name,
                    "base": ref(base),
                    "bundle": ref(bundle_path),
                    "proof": ref(proof_path),
                }
            )
    lanes.append(
        {
            "kind": "pipeline",
            "run_set_id": "pipeline",
            "cpu": 0,
            "historical_plan": ref(historical_root / declaration["pipeline"] / "plan.json"),
        }
    )
    save(
        output / "release_plan.json",
        {
            "schema_version": "tscb.current-closure-formal-plan.v1",
            "lanes": lanes,
            "historical_declaration": ref(declaration_path),
            "receipts": receipts,
            "new_algorithms_added": False,
            "historical_observations_transferred": False,
            "non_source_comparison_decisions_preserved": True,
            "formal_granted_by_preparation": False,
            "driver": ref(Path(__file__)),
            "rebind_driver": ref(ROOT / "tools/rebind_v32_comparison_sources.py"),
        },
    )
    print(
        json.dumps(
            {
                "status": "PLANNED_CURRENT_CLOSURE_ONLY",
                "lanes": len(lanes),
                "plan": str(output / "release_plan.json"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
