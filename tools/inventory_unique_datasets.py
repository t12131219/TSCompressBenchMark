#!/usr/bin/env python3
"""Explicitly inventory Unique dataset source files before any corpus adoption.

Presence in Unique is not evidence of publication/redistribution permission or a
canonical schema. This tool does not import data or make it eligible for plans.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tsbench.assets import ContractError, digest, local_file, require  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--from-unique", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        unique = args.from_unique.resolve(strict=True)
        dataset_dir = unique / "datasets"
        require(dataset_dir.is_dir() and dataset_dir.resolve().is_relative_to(unique), "missing Unique datasets directory")
        files = []
        for member in sorted(dataset_dir.rglob("*")):
            if member.suffix.lower() not in {".csv", ".npy", ".txt"}:
                continue
            rel = member.relative_to(unique).as_posix()
            path = local_file(unique, rel)
            files.append({"origin_relative_path": rel, "source_bytes": path.stat().st_size, "source_sha256": digest(path),
                          "eligibility": "candidate_not_adopted", "provenance_status": "upstream_and_license_unverified",
                          "parser_contract": "not_frozen"})
        output = {"schema": "bmk.dataset-intake-inventory/1", "origin": "Unique_Selected_Compression_Rewrite",
                  "dataset_count": len(files), "source_bytes": sum(row["source_bytes"] for row in files),
                  "used_by_planner": False, "files": files}
        with args.out.open("x", encoding="utf-8") as out:
            json.dump(output, out, ensure_ascii=False, indent=2)
            out.write("\n")
    except (ContractError, OSError) as exc:
        print(f"dataset inventory rejected: {exc}", file=sys.stderr)
        return 2
    print(f"Inventoried {len(files)} dataset candidates; no files have been adopted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
