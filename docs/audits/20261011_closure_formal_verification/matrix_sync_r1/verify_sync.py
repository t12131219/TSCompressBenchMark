"""Bind the current matrix revision to retained inputs and actual evidence.

No codec, qualification or performance runs here. This document check verifies
the fixed entry denominator, row order, literal SHA citations and manifest IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
NAME = "current_algorithm_data_function_matrix_20261011.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def ref(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def entry_tables(text: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        match = re.match(r"\| \[([^]]+)\]\(registry/codecs/[^)]+\) \|", line)
        if match:
            current.append(match[1])
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "preserve previous sync receipts")
    before, after = HERE / "before" / NAME, ROOT / NAME
    receipt = json.loads((HERE / "before_receipt.json").read_text())
    require(ref(before)["sha256"] == receipt["before"]["sha256"], "before snapshot drift")
    old_tables, new_tables = entry_tables(before.read_text()), entry_tables(after.read_text())
    require(len(old_tables) == len(new_tables) == 6, "six per-entry tables required")
    require(new_tables == old_tables, "algorithm denominator or row order changed")
    active = json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
    require(all(len(t) == 33 and set(t) == set(active) for t in new_tables), "active33 mismatch")
    references = []
    for line in after.read_text().splitlines():
        match = re.search(r"\[([^]]+)\]\(([^)]+)\) \| `([0-9a-f]{64})` \|$", line)
        if not match:
            continue
        path = (ROOT / match[2]).resolve()
        require(path.is_relative_to(ROOT) and path.is_file(), "literal SHA citation missing")
        value = ref(path)
        require(value["sha256"] == match[3], "literal SHA citation drift: " + match[2])
        references.append(value)
    require(references, "nonempty SHA citation denominator required")
    manifests = [
        {"key": key, "path": "registry/codecs/" + key + ".json", **{
            "sha256": ref(ROOT / "registry/codecs" / (key + ".json"))["sha256"]
        }}
        for key in sorted(active)
    ]
    manifest_sha = hashlib.sha256(
        json.dumps(manifests, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    require(manifest_sha in after.read_text(), "matrix manifest snapshot differs")
    result = {
        "schema_version": "tscb.algorithm-matrix-document-sync.v2",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "DOCUMENT_SYNC_AND_LITERAL_EVIDENCE_BINDINGS_VERIFIED",
        "before": ref(before),
        "after": ref(after),
        "driver": ref(Path(__file__)),
        "active_entry_count": 33,
        "six_per_entry_table_order_unchanged": True,
        "per_entry_table_order": new_tables[0],
        "literal_SHA_citation_count": len(references),
        "literal_SHA_citations": references,
        "current_declared_manifest_snapshot_sha256": manifest_sha,
        "current_declared_manifest_snapshot": manifests,
        "previous_sync_receipt_preserved": ref(
            ROOT / "docs/audits/20261011_porting_standard/matrix_sync_r1/receipt.json"
        ),
        "document_verification_executes_codec_or_performance": False,
        "claim_boundary": "Document bindings do not grant qualification beyond referenced reports.",
    }
    with args.output.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {k: result[k] for k in ("status", "active_entry_count", "literal_SHA_citation_count")}
        )
    )


if __name__ == "__main__":
    main()
