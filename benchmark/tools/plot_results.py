#!/usr/bin/env python3
"""Rebuild descriptive CPU figures from saved raw records, without running codecs.

Requires the optional ``analysis`` dependency. The JSON and CSV traces identify
every requested case and every measurement row contributing to a plotted number.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from tsbench.trial_analysis import analysis_dependency_hash, case_coverage, scheduled_rows

DEFAULT_COVERAGE = (
    "all-lossless-explicit-runtime-final-20261013", "timestamps-integer-affine-final-20261013",
    "bounded-quality-final-20261013", "empirical-quality-final-20261013",
    "records-composite-final-20261013",
)
HISTORICAL_COVERAGE = (
    "all-lossless-20261013", "bounded-quality-20261013",
    "empirical-quality-20261013", "timestamps-20261013",
)
STATUSES = ("complete", "unsupported", "unavailable", "error", "partial/not_run")
COLORS = {
    "complete": "#188775", "unsupported": "#d7dde1", "unavailable": "#dca432",
    "error": "#bd4e54", "partial/not_run": "#8270aa",
}
PRIMARY_RULE = (
    "For each scheduled (session, round), use the earliest terminal attempt that "
    "actually executed; if none executed, retain the earliest not_run attempt. "
    "A successful later retry never replaces an earlier executed failure."
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[min(low + 1, len(ordered) - 1)] * weight


def distribution(values: list[float]) -> dict[str, Any]:
    finite = [float(v) for v in values if math.isfinite(v)]
    if not finite:
        return {"n": 0, "median": None, "q1": None, "q3": None}
    return {"n": len(finite), "median": statistics.median(finite),
            "q1": percentile(finite, .25), "q3": percentile(finite, .75)}


def load_run(path: Path, root: Path) -> dict[str, Any]:
    path = path.resolve()
    manifest_bytes = (path / "manifest.json").read_bytes()
    observation_bytes = (path / "observations.jsonl").read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = []
    interrupted_tail = None
    lines = observation_bytes.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1 and not line.endswith(b"\n"):
                interrupted_tail = {"line": index + 1, "sha256": sha(line), "bytes": len(line)}
                continue
            raise
        row["_line"] = index + 1
        row["_line_sha256"] = sha(line)
        rows.append(row)
    try:
        location = str(path.relative_to(root))
    except ValueError:
        location = str(path)
    source = {
        "path": location, "run_id": manifest["run_id"], "state": manifest["state"],
        "manifest_sha256": sha(manifest_bytes), "observations_sha256": sha(observation_bytes),
        "configuration_id": manifest.get("configuration_id"),
        "environment": manifest.get("environment"), "interrupted_tail": interrupted_tail,
    }
    return {"manifest": manifest, "rows": rows, "source": source}


def row_identity(row: dict[str, Any]) -> dict[str, Any]:
    fields = ("run_id", "case_id", "session", "round", "attempt", "status", "phase",
              "qualification_kind", "encode_ns", "decode_ns", "stored_bytes", "payload_bytes",
              "header_bytes", "artifact_hash", "raw_object_id", "codec_input_id",
              "implementation_id", "verification", "reason")
    return {**{field: row.get(field) for field in fields},
            "observation_line": row["_line"], "observation_line_sha256": row["_line_sha256"]}


def aggregate_cases(run: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = run["manifest"]
    selected, planned = scheduled_rows(manifest, run["rows"])
    by_case = defaultdict(list)
    for row in run["rows"]:
        if row.get("event") == "terminal":
            by_case[row["case_id"]].append(row)
    result = []
    for case in manifest["cases"]:
        terminal = [row for row in by_case[case["case_id"]] if row.get("phase") == "measurement"]
        primary = [selected[key] for key in sorted(planned.get(case["case_id"], set())) if key in selected]
        coverage = case_coverage(manifest, case, selected, planned)
        admission = case.get("status")
        if admission in ("unsupported", "unavailable"):
            category = admission
        elif (not coverage["execution_source_valid"] or admission == "error"
              or any(row["status"] not in ("ok", "not_run") for row in primary)):
            category = "error"
        else:
            category = "complete" if coverage["complete"] else "partial/not_run"
        result.append({
            "source_path": run["source"]["path"], "run_id": manifest["run_id"],
            "case_id": case["case_id"], "dataset_id": case.get("dataset_id"),
            "method_id": case.get("method_id"), "codec": case.get("codec"),
            "profile_id": case.get("profile_id"), "fidelity": manifest["resolved_config"]["task"]["fidelity"],
            "admission_status": admission, "reason": case.get("reason"), "category": category,
            "raw_bytes": case.get("raw_bytes"), "planned_trials": coverage["requested_trials"],
            **coverage,
            "primary_trials": [row_identity(row) for row in primary],
            "all_terminal_attempts": [row_identity(row) for row in terminal],
            "qualification_terminals": [row_identity(row) for row in by_case[case["case_id"]] if row.get("phase") == "qualification"],
            "source_hash": case.get("lineage", {}).get("source_hash"),
            "raw_object_id": case.get("raw_object_id"), "implementation_id": case.get("implementation_id"),
            "components": case.get("components"), "method": case.get("method"),
            "boundary": case.get("boundary"), "lifecycle": case.get("lifecycle"),
            "cache_policy": case.get("cache_policy"), "effective_profile": case.get("effective_profile"),
        })
    return result


def coverage_plot(cases: list[dict[str, Any]], cards: dict[str, Any], output: Path, plt: Any) -> dict[str, Any]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        counts[case["codec"]][case["category"]] += 1
    def group(codec: str) -> str:
        if codec == "raw-store":
            return "ref"
        mode = cards[codec]["semantics"]["loss_modes"][0]
        return "L" if mode == "LOSSLESS" else "ABS" if codec in {"serf-qt", "serf-xor", "zfp-accuracy-1d"} else "E"
    group_order = {"ref": 0, "L": 1, "ABS": 2, "E": 3}
    codecs = sorted(counts, key=lambda codec: (group_order[group(codec)], codec))
    fig, ax = plt.subplots(figsize=(10.7, 13.8))
    left = [0] * len(codecs)
    positions = list(range(len(codecs)))
    for status in STATUSES:
        widths = [counts[codec][status] for codec in codecs]
        ax.barh(positions, widths, left=left, color=COLORS[status], label=status, height=.72)
        for index, width in enumerate(widths):
            if width:
                ax.text(left[index] + width / 2, index, str(width), va="center", ha="center", fontsize=8,
                        color="white" if status in ("complete", "error", "partial/not_run") else "#26313a")
        left = [start + width for start, width in zip(left, widths)]
    ax.set_yticks(positions, [f"{codec}  [{group(codec)}]" for codec in codecs], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(left) + .7)
    ax.set_xticks(range(0, max(left) + 1, 2))
    ax.set_xlabel("Requested cases (dataset × method × resource profile)")
    ax.grid(axis="x", alpha=.18)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    complete_codecs = sum(any(case["codec"] == codec and case["category"] == "complete" for case in cases) for codec in cards)
    fig.suptitle(f"Recorded CPU coverage: {complete_codecs}/{len(cards)} real codecs with a complete case",
                 x=.29, y=.975, ha="left", fontsize=14)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(.29, .952),
               ncol=3, frameon=False, fontsize=9)
    historical_failures = any(case["category"] in {"error", "unavailable"} for case in cases)
    last_line = ("NeaTS/LeaTS timestamp errors and original DZip runtime unavailability remain visible."
                 if historical_failures else
                 "Historical errors/unavailability remain in the history figure; integer-affine routes are distinct schemes.")
    fig.text(.03, .019,
             "L: bitwise; ABS: bounded absolute error; E: empirical quality; ref: raw-store.\n"
             "Different groups have different requested inputs. Counts describe recorded coverage, not speed or a universal domain guarantee.\n"
             "Composite cases are grouped by their primary route codec; every component binding remains in the trace.\n" + last_line,
             fontsize=9, color="#394650", linespacing=1.45)
    fig.subplots_adjust(left=.29, right=.97, top=.895, bottom=.11)
    for suffix in ("svg", "png"):
        fig.savefig(output / f"codec_coverage.{suffix}", dpi=170, metadata={"Creator": "tsbench plot_results.py"} if suffix == "svg" else None)
    plt.close(fig)
    return {"requested_cases": len(cases), "case_counts": dict(Counter(case["category"] for case in cases)),
            "real_codecs_with_complete_case": complete_codecs, "registered_real_codecs": len(cards),
            "codec_grouping": "Primary route codec for composite schemes; full route bindings are retained per case",
            "counts_by_codec": {codec: dict(counts[codec]) for codec in codecs}, "cases": cases}


def pilot_plot(cases: list[dict[str, Any]], output: Path, plt: Any) -> dict[str, Any]:
    datasets = list(dict.fromkeys(case["dataset_id"] for case in cases))
    labels = {"etth1-transformer-temperature": "ETTh1 / OT", "weather-temperature": "Weather / T (degC)",
              "national-illness-counts": "Illness / ILITOTAL"}
    metrics = ("stored_fraction", "encode_MiB_s", "decode_MiB_s")
    titles = ("Complete wire / raw bytes", "Encode throughput (MiB/s)", "Decode throughput (MiB/s)")
    methods = list(dict.fromkeys(case["method_id"] for case in cases))
    if any(case["category"] != "complete" for case in cases):
        raise ValueError("Pilot figure requires all planned primary trials to pass for every displayed case")
    points = []
    for case in cases:
        raw = case["raw_bytes"]
        if not raw or any(not row.get("encode_ns") or not row.get("decode_ns") for row in case["primary_trials"]):
            raise ValueError("Pilot figure requires nonempty objects and positive encode/decode wall times")
        summaries = {
            "stored_fraction": distribution([row["stored_bytes"] / raw for row in case["primary_trials"]]),
            "encode_MiB_s": distribution([raw * 1e9 / row["encode_ns"] / 2**20 for row in case["primary_trials"]]),
            "decode_MiB_s": distribution([raw * 1e9 / row["decode_ns"] / 2**20 for row in case["primary_trials"]]),
        }
        points.append({**case, "metrics": summaries})
    fig, axes = plt.subplots(len(datasets), 3, figsize=(12.5, 9.5), squeeze=False)
    palette = ("#70828e", "#247d9e", "#c27a2c", "#19866b", "#8164a1")
    for row_index, dataset in enumerate(datasets):
        data = {point["method_id"]: point for point in points if point["dataset_id"] == dataset}
        for col_index, metric in enumerate(metrics):
            ax = axes[row_index][col_index]
            for index, method in enumerate(methods):
                item = data[method]["metrics"][metric]
                ax.errorbar(item["median"], index,
                            xerr=[[item["median"] - item["q1"]], [item["q3"] - item["median"]]],
                            fmt="o", color=palette[index % len(palette)], markersize=6, capsize=3, linewidth=1.5)
            ax.set_yticks(range(len(methods)), methods, fontsize=9)
            ax.invert_yaxis()
            ax.set_ylim(len(methods) - .45, -.55)
            ax.set_xlim(left=0)
            if metric == "stored_fraction":
                ax.axvline(1, color="#a2a9ae", linestyle="--", linewidth=1)
            ax.grid(axis="x", alpha=.22)
            ax.spines[["top", "right", "left"]].set_visible(False)
            ax.tick_params(axis="y", length=0)
            if row_index == 0:
                ax.set_title(titles[col_index], fontsize=11, loc="left", pad=18)
            if col_index == 0:
                ax.text(0, 1.07, labels.get(dataset, dataset), transform=ax.transAxes, fontsize=10, weight="bold")
    fig.suptitle("Three-source CPU pilot · 512 float64 values per object", x=.07, ha="left", fontsize=15)
    fig.text(.07, .035,
             "Points: median of 7 rounds in 1 session; bars: Q1–Q3 round dispersion, not confidence intervals.\n"
             "Full standalone wire includes descriptor and payload. Dashed line: bare raw bytes; raw-store includes its envelope.\n"
             "object_memory / independent_object / natural · cpu-single · loops=1 · source identity/license remain unverified.",
             fontsize=9, color="#394650", linespacing=1.4)
    fig.subplots_adjust(left=.14, right=.97, bottom=.145, top=.885, wspace=.58, hspace=.65)
    for suffix in ("svg", "png"):
        fig.savefig(output / f"three_source_pilot.{suffix}", dpi=170, metadata={"Creator": "tsbench plot_results.py"} if suffix == "svg" else None)
    plt.close(fig)
    return {"scope": "Complete primary cases only; no cross-source inference", "cases": points,
            "formula": {"stored_fraction": "stored_bytes / raw_bytes for each round",
                        "encode_MiB_s": "raw_bytes * 1e9 / encode_ns / 2**20 for each round",
                        "decode_MiB_s": "raw_bytes * 1e9 / decode_ns / 2**20 for each round"},
            "quantiles": "Linear interpolation; median/Q1/Q3 of each metric across scheduled primary trials"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--historical", action="store_true", help="Use original runs, including saved correctness/runtime failures")
    parser.add_argument("--coverage-run", action="append", type=Path,
                        help="Replace default coverage runs; repeat for each run")
    parser.add_argument("--extra-coverage-run", action="append", type=Path, default=[],
                        help="Append a later run while keeping original failures visible")
    parser.add_argument("--pilot-run", type=Path, help="Override the pilot run; defaults to current, or original with --historical")
    parser.add_argument("--output", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()
    root = args.root.resolve()
    def resolve(path: Path) -> Path:
        return path.resolve() if path.is_absolute() else (root / path).resolve()
    default_coverage = HISTORICAL_COVERAGE if args.historical else DEFAULT_COVERAGE
    coverage_paths = [resolve(path) for path in (args.coverage_run or [Path("runs") / name for name in default_coverage]) + args.extra_coverage_run]
    if len(set(coverage_paths)) != len(coverage_paths):
        raise ValueError("The same coverage run cannot be counted twice")
    coverage_runs = [load_run(path, root) for path in coverage_paths]
    default_pilot = "three-source-values-pilot-validated-20261013" if args.historical else "three-source-values-pilot-final-20261013"
    pilot = load_run(resolve(args.pilot_run or Path("runs") / default_pilot), root)
    output = resolve(args.output)
    source_paths = {path for run in coverage_runs + [pilot] for path in (root / run["source"]["path"] / "manifest.json", root / run["source"]["path"] / "observations.jsonl")}
    if output in source_paths or any(output == path.parent for path in source_paths):
        raise ValueError("Figure output must be separate from raw run records")
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/tsbench-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "axes.labelsize": 10,
                         "xtick.labelsize": 9, "figure.facecolor": "white", "axes.facecolor": "white"})
    cards = {}
    card_sources = []
    for path in sorted((root / "registry/codecs").glob("*.json")):
        content = path.read_bytes()
        document = json.loads(content)
        if document.get("identity", {}).get("family") != "HARNESS_ORACLE":
            cards[document["key"]] = document
            card_sources.append({"path": str(path.relative_to(root)), "sha256": sha(content), "codec": document["key"]})
    trace = {
        "schema": "tsbench.figures/1", "plot_code_sha256": sha(Path(__file__).read_bytes()),
        "trial_analysis_hash": analysis_dependency_hash(),
        "matplotlib_version": matplotlib.__version__, "primary_rule": PRIMARY_RULE,
        "source_runs": [run["source"] for run in coverage_runs] + [pilot["source"]],
        "codec_cards": card_sources,
        "coverage": coverage_plot([case for run in coverage_runs for case in aggregate_cases(run)], cards, output, plt),
        "pilot": pilot_plot(aggregate_cases(pilot), output, plt),
    }
    trace["output_files"] = [{"path": path.name, "sha256": sha(path.read_bytes())}
                             for path in sorted(output.glob("*.svg")) + sorted(output.glob("*.png"))
                             if path.stem in {"codec_coverage", "three_source_pilot"}]
    (output / "trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    with (output / "pilot_points.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["run_id", "case_id", "dataset_id", "method_id", "codec", "metric", "n", "median", "q1", "q3"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in trace["pilot"]["cases"]:
            for metric, stats in case["metrics"].items():
                writer.writerow({**{key: case[key] for key in fields[:5]}, "metric": metric, **stats})
    print(json.dumps({"output": str(output), "coverage": {key: value for key, value in trace["coverage"].items() if key not in {"cases", "counts_by_codec"}},
                      "pilot_cases": len(trace["pilot"]["cases"])}))


if __name__ == "__main__":
    main()
