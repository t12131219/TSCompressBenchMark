#!/usr/bin/env python3
"""Execute frozen common-task stages; resume validates and reuses saved evidence.

An existing failed or invalid qualification/pilot is preserved and rejected.
Changed implementation requires a new execution identity and output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import (  # noqa: E402
    execute_comparison,
    pilot_comparison,
    prepare_comparison,
    qualify_comparison,
    report_comparison,
    validate_comparison_pilots,
    validate_qualification_evidence,
)
from tscompbench.datasets import DatasetRegistry  # noqa: E402


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def qualification(run) -> dict:
    document = read(run.path / "qualification.json")
    validate_qualification_evidence(run, document)
    return document


def pilot(run) -> dict:
    qualification(run)
    document = read(run.path / "pilot.json")
    validate_comparison_pilots(run, document)
    return document


def stage_evidence(run, datasets, stage: str, *, resume: bool) -> tuple[dict, bool]:
    """Saved evidence is never silently replaced by a repeat measurement."""
    if stage not in {"qualify", "pilot"}:
        raise ValueError("stage_evidence is only for qualification or development pilot")
    path = run.path / ("qualification.json" if stage == "qualify" else "pilot.json")
    validator = qualification if stage == "qualify" else pilot
    if path.exists():
        if not resume:
            raise ValueError("saved stage exists; use --resume to validate and reuse it")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        document = validator(run)
        if hashlib.sha256(path.read_bytes()).hexdigest() != before:
            raise ValueError("saved evidence changed during read-only resume validation")
        return document, True
    if stage == "pilot":
        qualification(run)
    operation = qualify_comparison if stage == "qualify" else pilot_comparison
    document = operation(run, datasets)
    validator(run)
    return document, False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "qualify", "pilot", "formal", "report"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-set-id", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.stage == "report":
        response = report_comparison(args.output_root / args.run_set_id)
    else:
        datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
        codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        run = prepare_comparison(
            args.bundle,
            args.output_root,
            ROOT,
            datasets,
            codecs,
            run_set_id=args.run_set_id,
            resume=args.resume,
        )
        if args.stage in {"qualify", "pilot"}:
            document, reused = stage_evidence(run, datasets, args.stage, resume=args.resume)
            response = {
                key: document[key]
                for key in (
                    ("status", "failure_count", "qualification_id")
                    if args.stage == "qualify"
                    else ("status", "pilot_id")
                )
            }
            response.update(evidence_reused=reused, path=str(run.path))
        elif args.stage == "formal":
            response = execute_comparison(run, pilot(run))
        else:
            response = {
                "status": "PLANNED",
                "comparison_id": run.plan["comparison_id"],
                "path": str(run.path),
                "cells": len(run.cells),
                "schedule_trials": len(run.schedule.trials),
            }
    print(json.dumps(response, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
