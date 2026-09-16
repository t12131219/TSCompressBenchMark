from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tscompbench.codecs import (
    CodecRegistry,
    SourceRegistry,
    classify_logical_entries,
)
from tscompbench.datasets import CharacterizationProfile, DatasetRegistry
from tscompbench.datasets.prepare import prepare_dataset
from tscompbench.runner import (
    execute_run_set,
    initialize_run_set,
    plan_run_set,
    prepare_run_set,
    report_run_set,
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _registry(root: Path, manifest_root: Path | None = None) -> DatasetRegistry:
    return DatasetRegistry(manifest_root or root / "registry" / "datasets", root)


def _codec_registry(root: Path) -> CodecRegistry:
    sources = SourceRegistry(root / "registry" / "sources")
    return CodecRegistry(root / "registry" / "codecs", sources)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tscompbench")
    parser.add_argument("--project-root", type=Path, default=_project_root())
    groups = parser.add_subparsers(dest="group", required=True)

    datasets = groups.add_parser("datasets", help="Dataset registry and Layer 1 operations")
    dataset_commands = datasets.add_subparsers(dest="command", required=True)
    dataset_commands.add_parser("list")
    dataset_commands.add_parser("verify")
    prepare = dataset_commands.add_parser("prepare")
    prepare.add_argument("key")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--mode", choices=("exact", "sampled"), default="exact")
    prepare.add_argument("--sample-rows", type=int)
    prepare.add_argument("--seed", type=int, default=20260910)

    codecs = groups.add_parser("codecs", help="Codec/source registry and Layer 2 contracts")
    codec_commands = codecs.add_subparsers(dest="command", required=True)
    codec_commands.add_parser("list")
    codec_commands.add_parser("verify")
    codec_commands.add_parser("classify-sources")

    run = groups.add_parser(
        "run", help="Initialize, prepare, plan, or validate a benchmark run set"
    )
    run_commands = run.add_subparsers(dest="command", required=True)
    for name in ("init", "prepare", "plan", "validate", "report"):
        command = run_commands.add_parser(name)
        command.add_argument("config", type=Path)
        command.add_argument("--output-root", type=Path, required=True)
        command.add_argument("--run-set-id")
        command.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    registry = _registry(root)
    try:
        if args.group == "datasets" and args.command == "list":
            _print_json({"datasets": list(registry.keys())})
        elif args.group == "datasets" and args.command == "verify":
            manifests = registry.verify_all()
            _print_json(
                {
                    "status": "PASS",
                    "dataset_count": len(manifests),
                    "datasets": [
                        {"key": item.key, "dataset_id": item.dataset_id} for item in manifests
                    ],
                }
            )
        elif args.group == "datasets" and args.command == "prepare":
            profile = CharacterizationProfile(
                mode=args.mode,
                sample_rows=args.sample_rows,
                seed=args.seed,
            )
            result = prepare_dataset(
                registry,
                args.key,
                args.output,
                characterization_profile=profile,
            )
            _print_json(
                {
                    "status": "PASS",
                    "dataset_id": result.dataset_id,
                    "canonical_sha256": result.canonical.sha256,
                    "output": str(result.preparation_record_path.parent),
                }
            )
        elif args.group == "codecs":
            codec_registry = _codec_registry(root)
            if args.command == "list":
                _print_json(
                    {
                        "codecs": [
                            {
                                "key": key,
                                "algorithm_id": codec_registry.get(key).algorithm_id,
                                "source_artifact_id": codec_registry.get(key).source_artifact_id,
                            }
                            for key in codec_registry.keys()
                        ]
                    }
                )
            elif args.command == "verify":
                manifests = codec_registry.verify_all()
                _print_json(
                    {
                        "status": "PASS",
                        "codec_count": len(manifests),
                        "source_artifact_count": len(codec_registry.sources),
                    }
                )
            else:
                report = classify_logical_entries(
                    codec_registry.sources.catalog,
                    codec_registry.root / "logical_classification_rules.json",
                )
                _print_json(
                    {
                        "status": "PASS",
                        "entry_count": report["entry_count"],
                        "classification_report_id": report["classification_report_id"],
                    }
                )
        elif args.group == "run":
            run_set = initialize_run_set(
                args.config,
                args.output_root,
                run_set_id=args.run_set_id,
                resume=args.resume,
            )
            response: dict[str, object] = {
                "status": "PASS",
                "run_set_id": run_set.run_set_id,
                "path": str(run_set.path),
                "experiment_config_id": run_set.config.experiment_config_id,
                "environment_id": run_set.environment["environment_id"],
            }
            if args.command == "prepare":
                results = prepare_run_set(run_set, registry)
                response["datasets"] = [
                    {
                        "key": item.dataset_key,
                        "dataset_id": item.dataset_id,
                        "canonical_sha256": item.canonical.sha256,
                    }
                    for item in results
                ]
            elif args.command == "plan":
                tasks = plan_run_set(run_set, registry, _codec_registry(root))
                response["task_count"] = len(tasks)
                response["task_plan"] = str(run_set.path / "task_plan.jsonl")
            elif args.command == "validate":
                results = execute_run_set(
                    run_set,
                    registry,
                    _codec_registry(root),
                )
                response["executed_task_count"] = len(results)
                response["runs_csv"] = str(run_set.path / "runs.csv")
            elif args.command == "report":
                result = report_run_set(run_set)
                response.update(
                    {
                        "report_id": result.report_id,
                        "task_count": result.task_count,
                        "summary_count": result.summary_count,
                        "eligible_run_count": result.eligible_run_count,
                        "report": str(result.report_directory / "report.html"),
                    }
                )
            _print_json(response)
        else:
            parser.error("unsupported command")
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
