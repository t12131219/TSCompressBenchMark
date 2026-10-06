"""Reproduce the registered rewrite profiles through all five benchmark layers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    **{
        key: ("rewrite_float_mts", "VALUE")
        for key in [
            "abba",
            "fabba",
            "tristan",
            "corad",
            "chimp",
            "chimp128",
            "elf",
            "elf-plus",
            "elf-star",
            "self-star",
        ]
    },
    "influxdb-tsm-adaptive-timestamp": ("rewrite_float_mts", "TIMESTAMP"),
    **{
        key: ("rewrite_float_mts", "SYSTEM")
        for key in ["prometheus-xor2-chunk", "prometheus-xor-chunk"]
    },
    **{key: ("rewrite_byte_uts", "VALUE") for key in ["deepzip", "dzip"]},
    "walloc-1d": ("rewrite_audio_stereo", "VALUE"),
    "prometheus-histogram-st": ("rewrite_histogram_int", "SYSTEM"),
    "prometheus-float-histogram-st": ("rewrite_histogram_float", "SYSTEM"),
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def configuration(name, mode, repetitions=20):
    dataset, track = PROFILES[name]
    text = (ROOT / "configs/experiments/snappy-raw-formal.toml").read_text().split("[sweep]")[0]
    text = text.replace('["national_illness"]', f'["{dataset}"]').replace(
        '["snappy-raw"]', f'["{name}"]'
    )
    text = text.replace('tracks = ["VALUE"]', f'tracks = ["{track}"]')
    text = text.replace("timeout_seconds = 120", "timeout_seconds = 900").replace(
        "memory_limit_bytes = 1073741824", "memory_limit_bytes = 8589934592"
    )
    if name == "dzip":
        text = text.replace("threads = 1", "threads = 3")
    if mode == "QUALIFICATION":
        text = text.replace('measurement_mode = "FORMAL"', 'measurement_mode = "QUALIFICATION"')
        text = text.replace("warmup_min_count = 3", "warmup_min_count = 1").replace(
            'warmup_min_seconds = "0.5"', 'warmup_min_seconds = "0"'
        )
        text = text.replace("repetitions = 10", "repetitions = 1").replace(
            'min_repetition_seconds = "1"', 'min_repetition_seconds = "0"'
        )
    else:
        text = text.replace("repetitions = 10", f"repetitions = {repetitions}")
    if name in {
        "chimp",
        "chimp128",
        "elf",
        "elf-plus",
        "elf-star",
        "self-star",
        "prometheus-xor-chunk",
    }:
        text += '[sweep]\nblock_size = [1000]\nisa = ["SCALAR"]\n'
    path = ROOT / "configs/experiments" / f"completed-rewrites-{name}-{mode.lower()}.toml"
    path.write_text(text)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["QUALIFICATION", "FORMAL"], default="QUALIFICATION")
    parser.add_argument("--algorithms", nargs="+", choices=PROFILES, default=list(PROFILES))
    parser.add_argument("--suffix", default="20261006")
    parser.add_argument("--configs-only", action="store_true")
    parser.add_argument("--repetitions", type=int, default=20)
    args = parser.parse_args()
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    groups = []
    for name in args.algorithms:
        if args.mode == "FORMAL" and args.repetitions < 10:
            raise ValueError("FORMAL requires at least ten repetitions")
        config = configuration(name, args.mode, args.repetitions)
        if args.configs_only:
            continue
        run = initialize_run_set(
            config, ROOT / "runs", run_set_id=f"completed-{name}-{args.mode.lower()}-{args.suffix}"
        )
        results = execute_run_set(run, datasets, codecs)
        report_run_set(run)
        components = [
            json.loads(line)
            for line in (run.path / "run_components.jsonl").read_text().splitlines()
        ]
        expected = args.repetitions if args.mode == "FORMAL" else 1
        status = (
            "PASS"
            if len(components) == expected
            and all(
                c["status"] in {"PASS", "RESOURCE_PRESSURE"}
                and c["correctness"]["status"] == "PASS"
                for c in components
            )
            and all(r.preflight.eligible_for_formal_repetitions for r in results)
            else "FAIL"
        )
        excluded = sum(c["status"] == "RESOURCE_PRESSURE" for c in components)
        eligible = sum(bool(c.get("eligibility")) for c in components)
        with (run.path / "summary.csv").open() as stream:
            summaries = list(csv.DictReader(stream))
        summary_count = min((int(row["n"]) for row in summaries), default=0)
        if status == "PASS" and args.mode == "FORMAL" and eligible < 10:
            status = "FAIL_INSUFFICIENT_ELIGIBLE_FORMAL_OBSERVATIONS"
        elif status == "PASS" and excluded:
            status = "PASS_WITH_RESOURCE_EXCLUSIONS"
        if status.startswith("PASS") and args.mode == "FORMAL" and summary_count < 10:
            status = "FAIL_INSUFFICIENT_STATISTICAL_OBSERVATIONS"
        group = {
            "algorithm": name,
            "status": status,
            "measurement_mode": args.mode,
            "run_path": str(run.path.relative_to(ROOT)),
            "config_sha256": sha(config),
            "record_count": len(components),
            "formal_eligible_count": sum(bool(c.get("eligibility")) for c in components),
            "resource_pressure_excluded_count": excluded,
            "summary_observation_count": summary_count,
            "preflight": [r.preflight.to_document() for r in results],
            "artifacts": [
                {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
                for p in sorted(run.path.rglob("*"))
                if p.is_file() and ("canonical" not in p.parts)
            ],
        }
        groups.append(group)
        destination = ROOT / "docs/completed_rewrites" / f"{name}-{args.mode.lower()}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(group, indent=2) + "\n")
        print(
            name,
            args.mode,
            status,
            "records",
            len(components),
            "eligible",
            group["formal_eligible_count"],
            flush=True,
        )
        if not status.startswith("PASS"):
            for r in results:
                print(
                    r.preflight.status, r.preflight.reason_code, r.preflight.diagnostics, flush=True
                )
                if r.preflight.boundary:
                    print(
                        sorted(
                            {
                                q.reason
                                for q in r.preflight.boundary.observations
                                if q.status != "PASS"
                            }
                        ),
                        flush=True,
                    )
    if not args.configs_only:
        raise SystemExit(any(not g["status"].startswith("PASS") for g in groups))


if __name__ == "__main__":
    main()
