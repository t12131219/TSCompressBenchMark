from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id
from tscompbench.statistics import AnalysisBundle, analyze_run_set

_STATISTIC_PREFIXES = (
    "encode_ns",
    "decode_ns",
    "e2e_ns",
    "rmse",
    "mae",
    "max_ae",
    "psnr_range_db",
    "process_cpu_seconds",
    "peak_memory_bytes",
    "incremental_peak_memory_bytes",
    "cpu_core_seconds_per_gb",
)
_STATISTIC_SUFFIXES = ("median", "p25", "p75", "mean", "sd", "cv", "ci_low", "ci_high")
_TABLE_FIELDS = {
    "eligibility.csv": (
        "schema_version",
        "run_id",
        "task_id",
        "dataset_id",
        "algorithm_id",
        "config_id",
        "execution_path_hash",
        "analysis",
        "comparison_key",
        "eligible",
        "reason_codes",
    ),
    "summary.csv": (
        "schema_version",
        "summary_id",
        "run_set_id",
        "dataset_id",
        "algorithm_id",
        "config_id",
        "execution_path_hash",
        "profile_id",
        "run_record_schema",
        "track",
        "object_level",
        "loss_mode",
        "semantic_comparability_key",
        "execution_comparability_key",
        "resource_profile_key",
        "n",
        "repetition_indices",
        "run_ids",
        "input_sha256s",
        "bitstream_sha256s",
        "source_artifact_id",
        "adapter_id",
        "binary_artifact_sha256",
        "environment_id",
        "source_sha256",
        "canonical_artifact_sha256",
        "canonical_content_sha256",
        "canonical_raw_bits",
        "serialized_bits",
        "external_side_information_bits",
        "final_bits",
        "final_physical_bytes",
        "size_ratio",
        "compression_factor",
        "semantic_encode_mb_per_second_micro",
        "semantic_decode_mb_per_second_micro",
        "resource_observation_count",
        *(f"{prefix}_{suffix}" for prefix in _STATISTIC_PREFIXES for suffix in _STATISTIC_SUFFIXES),
    ),
    "corpus_summary.csv": (
        "schema_version",
        "corpus_summary_id",
        "algorithm_id",
        "config_id",
        "execution_path_hash",
        "profile_id",
        "semantic_comparability_key",
        "execution_comparability_key",
        "resource_profile_key",
        "dataset_count",
        "dataset_ids",
        "summary_ids",
        "micro_size_ratio",
        "micro_compression_factor",
        "geometric_mean_compression_factor",
        "micro_encode_mb_per_second",
        "micro_decode_mb_per_second",
        "corpus_peak_memory_bytes_max",
        "corpus_peak_memory_bytes_p95",
        "corpus_cpu_core_seconds_per_gb",
    ),
    "coverage.csv": (
        "schema_version",
        "task_id",
        "dataset_id",
        "algorithm_id",
        "config_id",
        "track",
        "profile_id",
        "planned_status",
        "planned_reason_code",
        "final_status",
        "coverage_category",
        "record_count",
        "expected_repetitions",
        "pass_repetitions",
        "failed_repetitions",
        "status_counts",
        "run_ids",
    ),
    "comparability.csv": (
        "schema_version",
        "semantic_comparability_key",
        "execution_comparability_key",
        "resource_profile_key",
        "semantic_document",
        "execution_document",
        "resource_document",
        "semantic_context",
        "execution_context",
        "resource_context",
        "task_ids",
        "task_count",
    ),
    "pareto.csv": (
        "schema_version",
        "view",
        "dataset_id",
        "comparison_key_type",
        "comparison_key",
        "profile_id",
        "summary_id",
        "objectives",
        "directions",
        "pareto_optimal",
        "dominated_by_summary_ids",
    ),
    "ranking.csv": (
        "schema_version",
        "dataset_id",
        "comparison_key_type",
        "comparison_key",
        "profile_id",
        "metric",
        "direction",
        "summary_id",
        "value",
        "rank",
        "tie_method",
        "coverage_used_as_score",
    ),
}


@dataclass(frozen=True)
class ReportResult:
    report_id: str
    report_directory: Path
    summary_count: int
    eligible_run_count: int
    task_count: int
    output_hashes: dict[str, str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_json(path: Path, document: Any) -> None:
    encoded = (
        json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    _atomic_bytes(path, encoded)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return value


def _atomic_csv(path: Path, rows: tuple[dict[str, Any], ...], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: _csv_value(row.get(field)) for field in fields})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _dataset_evidence(run_path: Path) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for path in sorted((run_path / "datasets").glob("*/preparation-record.json")):
        document = _optional_json(path)
        if document is None:
            continue
        evidence.append(
            {
                "dataset_id": document.get("dataset_id"),
                "dataset_key": document.get("dataset_key", path.parent.name),
                "source_sha256": document.get("source_sha256"),
                "canonical_artifact_sha256": document.get("canonical_artifact_sha256"),
                "canonical_content_sha256": document.get("canonical_content_sha256"),
                "preparation_record": str(path.relative_to(run_path)),
            }
        )
    return evidence


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _coverage_counts(bundle: AnalysisBundle) -> dict[str, int]:
    counts = Counter(str(item["coverage_category"]) for item in bundle.coverage)
    return {name: counts.get(name, 0) for name in ("PASS", "UNSUPPORTED", "FAIL", "OOM", "TIMEOUT")}


def _coverage_svg(counts: dict[str, int]) -> str:
    width, height = 720, 280
    labels = ("PASS", "UNSUPPORTED", "FAIL", "OOM", "TIMEOUT")
    colors = ("#238636", "#6e7781", "#cf222e", "#8250df", "#bf8700")
    maximum = max(1, *(counts[label] for label in labels))
    bars: list[str] = []
    for index, (label, color) in enumerate(zip(labels, colors, strict=True)):
        x = 55 + index * 130
        bar_height = 170 * counts[label] / maximum
        y = 220 - bar_height
        bars.append(
            f'<rect x="{x}" y="{y:.2f}" width="82" height="{bar_height:.2f}" '
            f'fill="{color}"/><text x="{x + 41}" y="{y - 8:.2f}" text-anchor="middle">'
            f'{counts[label]}</text><text x="{x + 41}" y="245" text-anchor="middle">'
            f"{label}</text>"
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Coverage counts">'
        '<rect width="100%" height="100%" fill="white"/><g font-family="system-ui" '
        'font-size="13" fill="#18202a"><text x="20" y="25" font-size="17">'
        "Frozen task coverage</text>" + "".join(bars) + "</g></svg>"
    )


def _pareto_svg(summaries: tuple[dict[str, Any], ...], speed_field: str, title: str) -> str:
    width = 720
    groups: dict[tuple[str, str, str], list[tuple[float, float, str]]] = {}
    for row in summaries:
        if row.get(speed_field) is None or row.get("compression_factor") is None:
            continue
        key = (
            str(row["dataset_id"]),
            str(row["execution_comparability_key"]),
            str(row["profile_id"]),
        )
        groups.setdefault(key, []).append(
            (
                float(row[speed_field]),
                float(row["compression_factor"]),
                str(row["algorithm_id"]),
            )
        )
    if not groups:
        height = 360
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<text x="24" y="32" font-family="system-ui" font-size="17">'
            f"{html.escape(title)}</text>"
            '<text x="360" y="185" text-anchor="middle" font-family="system-ui" '
            'font-size="15" fill="#57606a">No performance-eligible points</text></svg>'
        )
    panel_height = 300
    height = 55 + panel_height * len(groups)
    panels: list[str] = []
    for panel_index, (key, points) in enumerate(sorted(groups.items())):
        top = 45 + panel_index * panel_height
        baseline = top + 220
        max_x = max(value[0] for value in points) or 1.0
        max_y = max(value[1] for value in points) or 1.0
        marks: list[str] = []
        for x_value, y_value, algorithm in points:
            x = 75 + 570 * x_value / max_x
            y = baseline - 175 * y_value / max_y
            label = html.escape(algorithm.rsplit(":", 1)[-1][:16])
            marks.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#0969da">'
                f"<title>{html.escape(algorithm)}</title></circle>"
                f'<text x="{x + 7:.2f}" y="{y - 7:.2f}" font-size="10">{label}</text>'
            )
        context = html.escape(f"Dataset={key[0]}  ExecutionKey={key[1]}  Profile={key[2]}")
        panels.append(
            f'<text x="75" y="{top}" font-size="11">{context}</text>'
            f'<path d="M75 {top + 15}V{baseline}H660" stroke="#57606a" fill="none"/>'
            f'<text x="368" y="{baseline + 32}" text-anchor="middle" font-size="12">'
            "Throughput (MB/s)</text>" + "".join(marks)
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        '<rect width="100%" height="100%" fill="white"/>'
        f'<g font-family="system-ui" fill="#18202a"><text x="24" y="25" font-size="17">'
        f'{html.escape(title)}</text><text x="18" y="{height / 2:.2f}" text-anchor="middle" '
        f'font-size="13" transform="rotate(-90 18 {height / 2:.2f})">CompressionFactor</text>'
        + "".join(panels)
        + "</g></svg>"
    )


def _markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage_counts"]
    environment = report.get("environment") or {}
    operating_system = environment.get("os") or {}
    cpu = environment.get("cpu") or {}
    python = environment.get("python") or {}
    sources = (report.get("source_registry") or {}).get("sources") or []
    rejection_counts: Counter[str] = Counter()
    for item in report["eligibility"]:
        if not item["eligible"]:
            rejection_counts.update(str(reason) for reason in item["reason_codes"])
    comparison_lines = [
        "| Semantic context | Execution context | Resource context | Tasks |",
        "|---|---|---|---:|",
    ]
    comparison_lines.extend(
        f"| {row['semantic_context']} | {row['execution_context']} | "
        f"{row['resource_context']} | {row['task_count']} |"
        for row in report["comparability_groups"]
    )
    lines = [
        "# Time-Series Compression Benchmark V2 Report",
        "",
        f"Report ID: `{report['report_id']}`  ",
        f"Run set: `{report['run_set_id']}`  ",
        f"Generated (UTC): `{report['generated_at_utc']}`",
        "",
        "> Compression is shown both as SizeRatio = FinalBits / CanonicalRawBits "
        "(lower is better) and CompressionFactor = CanonicalRawBits / FinalBits "
        "(higher is better). Throughput uses decimal MB/s. Timing scope, thread budget, "
        "model/index accounting, and cold-start policy are comparison-key fields and must "
        "not be mixed across direct rankings.",
        "",
        "## Reproducibility context",
        "",
        f"- EnvironmentID: `{environment.get('environment_id', 'UNAVAILABLE')}`",
        f"- OS: `{operating_system.get('system', 'UNAVAILABLE')} "
        f"{operating_system.get('release', '')}`",
        f"- CPU: `{cpu.get('model', 'UNAVAILABLE')}`; logical CPUs: "
        f"`{cpu.get('logical_cpu_count', 'UNAVAILABLE')}`",
        f"- Python: `{python.get('implementation', 'UNAVAILABLE')} "
        f"{python.get('version', '')}`; Conda environment: "
        f"`{python.get('conda_environment', 'UNAVAILABLE')}`",
        "",
        "### Dataset evidence",
        "",
        "| Dataset | Source SHA-256 | Canonical artifact SHA-256 | Canonical content SHA-256 |",
        "|---|---|---|---|",
        *(
            f"| {item['dataset_key']} (`{item['dataset_id']}`) | "
            f"`{item['source_sha256']}` | `{item['canonical_artifact_sha256']}` | "
            f"`{item['canonical_content_sha256']}` |"
            for item in report["dataset_evidence"]
        ),
        "",
        "### Source artifacts",
        "",
        "| SourceArtifactID | Key/kind | Frozen identity (commit/revision when applicable) |",
        "|---|---|---|",
        *(
            f"| `{item.get('source_artifact_id', 'UNAVAILABLE')}` | "
            f"{item.get('key', item.get('kind', 'UNAVAILABLE'))} | "
            f"`{_compact_json(item.get('identity', {}))}` |"
            for item in sources
        ),
        "",
        "## Eligibility and coverage",
        "",
        f"Frozen task universe: **{report['task_count']}**; per-dataset summaries: "
        f"**{report['summary_count']}**; performance-eligible raw repetitions: "
        f"**{report['eligible_run_count']}**.",
        "",
        "| PASS | UNSUPPORTED | FAIL | OOM | TIMEOUT |",
        "|---:|---:|---:|---:|---:|",
        f"| {coverage['PASS']} | {coverage['UNSUPPORTED']} | {coverage['FAIL']} | "
        f"{coverage['OOM']} | {coverage['TIMEOUT']} |",
        "",
        "Eligibility is analysis-specific. Every rejection is retained in `eligibility.csv`; "
        "coverage is computed from `task_plan.jsonl`, including tasks that produced no PASS run.",
        "",
        "### Exclusions and abnormal outcomes",
        "",
        *(
            [f"- `{reason}`: {count}" for reason, count in sorted(rejection_counts.items())]
            or ["- No eligibility exclusions."]
        ),
        "",
        "## Per-dataset results",
        "",
        "| Dataset | Track | Algorithm | n | SizeRatio | CF | Encode MB/s | Decode MB/s |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    if report["summaries"]:
        for row in report["summaries"]:
            lines.append(
                "| {dataset_id} | {track} | {algorithm_id} | {n} | {size_ratio} | "
                "{compression_factor} | {semantic_encode_mb_per_second_micro} | "
                "{semantic_decode_mb_per_second_micro} |".format(**row)
            )
    else:
        lines.append("| — | — | — | 0 | — | — | — | — |")
    lines.extend(
        [
            "",
            "## Cross-dataset aggregates",
            "",
            "Cross-dataset values are secondary to per-dataset results. Micro size uses "
            "`sum(FinalBits) / sum(CanonicalRawBits)`; micro throughput uses "
            "`sum(CanonicalBytes) / sum(per-dataset median time)`; compression-factor "
            "GeoMean is reported separately.",
            "",
            "## Comparability and ranking",
            "",
            "Space/quality views use SemanticComparabilityKey. Speed views additionally "
            "require ExecutionComparabilityKey. Resource views additionally require "
            "ResourceProfileKey. Rankings are dense per-metric rankings within those groups; "
            "coverage is published separately and is never converted into a weighted score.",
            "",
            *comparison_lines,
            "",
            "Pareto rows and domination evidence are in `pareto.csv`; no cross-Track, "
            "cross-LossMode, cross-ObjectLevel, or CPU/GPU total ranking is produced.",
            "",
            "## Traceability",
            "",
            "Each summary carries all contributing RunIDs, input and bitstream hashes, "
            "Dataset canonical hashes, SourceArtifactID, adapter/binary hash, EnvironmentID, "
            "ConfigID, ExecutionPathHash, and all three comparison keys. Raw evidence remains "
            "append-only in `run_components.jsonl`.",
            "",
            "## Generated artifacts",
            "",
        ]
    )
    for name, digest in report["derived_artifact_hashes"].items():
        lines.append(f"- `{name}` — `{digest}`")
    return "\n".join(lines) + "\n"


def _html(markdown_report: str, report: dict[str, Any]) -> str:
    coverage = report["coverage_counts"]
    summary_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(field, '')))}</td>"
            for field in (
                "dataset_id",
                "track",
                "algorithm_id",
                "n",
                "size_ratio",
                "compression_factor",
                "semantic_encode_mb_per_second_micro",
                "semantic_decode_mb_per_second_micro",
            )
        )
        + "</tr>"
        for row in report["summaries"]
    )
    if not summary_rows:
        summary_rows = '<tr><td colspan="8">No performance-eligible summary rows.</td></tr>'
    comparison_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['semantic_context'])}</td>"
        f"<td>{html.escape(row['execution_context'])}</td>"
        f"<td>{html.escape(row['resource_context'])}</td>"
        f"<td>{row['task_count']}</td>"
        "</tr>"
        for row in report["comparability_groups"]
    )
    report_id = html.escape(report["report_id"])
    run_set_id = html.escape(report["run_set_id"])
    environment = report.get("environment") or {}
    operating_system = environment.get("os") or {}
    cpu = environment.get("cpu") or {}
    python = environment.get("python") or {}
    environment_text = html.escape(
        f"{operating_system.get('system', 'UNAVAILABLE')} "
        f"{operating_system.get('release', '')}; {cpu.get('model', 'UNAVAILABLE')}; "
        f"{python.get('implementation', 'UNAVAILABLE')} {python.get('version', '')}"
    )
    environment_id = html.escape(str(environment.get("environment_id", "UNAVAILABLE")))
    dataset_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['dataset_key']))}</td>"
        f"<td><code>{html.escape(str(item['source_sha256']))}</code></td>"
        f"<td><code>{html.escape(str(item['canonical_content_sha256']))}</code></td>"
        "</tr>"
        for item in report["dataset_evidence"]
    )
    source_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(str(item.get('source_artifact_id', 'UNAVAILABLE')))}</code></td>"
        f"<td>{html.escape(str(item.get('key', item.get('kind', 'UNAVAILABLE'))))}</td>"
        f"<td><code>{html.escape(_compact_json(item.get('identity', {})))}</code></td>"
        "</tr>"
        for item in (report.get("source_registry") or {}).get("sources", [])
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TSCompBench V2 Report</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #ccd3da;padding:.45rem}}
th{{background:#eef2f5}} code{{background:#f3f5f7;padding:.1rem .25rem}}
.notice{{border-left:4px solid #b36b00;padding:.8rem;background:#fff7e8}}
</style></head>
<body><h1>Time-Series Compression Benchmark V2 Report</h1>
<p>Report <code>{report_id}</code>; run set <code>{run_set_id}</code>.</p>
<p class="notice">SizeRatio = FinalBits / CanonicalRawBits (lower is better);
CompressionFactor is the inverse (higher is better). Throughput is decimal MB/s.
Timing scope, threads, model/index accounting, and cold-start policy must match.</p>
<h2>Reproducibility context</h2>
<p>Environment <code>{environment_id}</code>: {environment_text}.</p>
<h3>Datasets</h3><table><thead><tr><th>Dataset</th><th>Source SHA-256</th>
<th>Canonical content SHA-256</th></tr></thead><tbody>{dataset_rows}</tbody></table>
<h3>Source artifacts</h3><table><thead><tr><th>SourceArtifactID</th><th>Key</th>
<th>Frozen identity</th></tr></thead><tbody>{source_rows}</tbody></table>
<h2>Coverage</h2>
<p>Frozen tasks: {report["task_count"]}; summaries: {report["summary_count"]}.</p>
<table><thead><tr><th>PASS</th><th>UNSUPPORTED</th><th>FAIL</th><th>OOM</th>
<th>TIMEOUT</th></tr></thead><tbody><tr><td>{coverage["PASS"]}</td>
<td>{coverage["UNSUPPORTED"]}</td><td>{coverage["FAIL"]}</td><td>{coverage["OOM"]}</td>
<td>{coverage["TIMEOUT"]}</td></tr></tbody></table>
<h2>Per-dataset results</h2><table><thead><tr><th>Dataset</th><th>Track</th>
<th>Algorithm</th><th>n</th><th>SizeRatio</th><th>CF</th><th>Encode MB/s</th>
<th>Decode MB/s</th></tr></thead><tbody>{summary_rows}</tbody></table>
<h2>Charts</h2><img src="coverage.svg" alt="Coverage chart">
<img src="space-encode.svg" alt="Compression factor versus encode throughput">
<img src="space-decode.svg" alt="Compression factor versus decode throughput">
<h2>Method</h2><p>Per-dataset summaries precede corpus aggregation. Space,
performance, and resources use nested Semantic → Execution → Resource keys.
Coverage is not a score. See the CSV files and <code>report.json</code>.</p>
<h2>Comparability profiles</h2><table><thead><tr><th>Semantic</th><th>Execution</th>
<th>Resource</th><th>Tasks</th></tr></thead><tbody>{comparison_rows}</tbody></table>
<details><summary>Plain-text report</summary>
<pre>{html.escape(markdown_report)}</pre></details></body></html>"""


def generate_report(run_path: Path, policy: dict[str, Any]) -> ReportResult:
    """Generate derived Layer-5 artifacts; raw run/task evidence is never rewritten."""

    run_path = run_path.resolve()
    bundle = analyze_run_set(run_path, policy)
    table_paths = {
        "eligibility.csv": run_path / "eligibility.csv",
        "summary.csv": run_path / "summary.csv",
        "corpus_summary.csv": run_path / "corpus_summary.csv",
        "coverage.csv": run_path / "coverage.csv",
        "comparability.csv": run_path / "comparability.csv",
        "pareto.csv": run_path / "pareto.csv",
        "ranking.csv": run_path / "ranking.csv",
    }
    rows_by_name = {
        "eligibility.csv": bundle.eligibility,
        "summary.csv": bundle.summaries,
        "corpus_summary.csv": bundle.corpus_summaries,
        "coverage.csv": bundle.coverage,
        "comparability.csv": bundle.comparability_groups,
        "pareto.csv": bundle.pareto,
        "ranking.csv": bundle.rankings,
    }
    for name, path in table_paths.items():
        _atomic_csv(path, rows_by_name[name], _TABLE_FIELDS[name])
    table_hashes = {name: _sha256_file(path) for name, path in table_paths.items()}
    package_root = Path(__file__).resolve().parents[1]
    source_hashes = {
        **bundle.source_hashes,
        "implementation/statistics/core.py": _sha256_file(package_root / "statistics" / "core.py"),
        "implementation/statistics/engine.py": _sha256_file(
            package_root / "statistics" / "engine.py"
        ),
        "implementation/reporting/generator.py": _sha256_file(Path(__file__).resolve()),
    }
    run_set_document = _optional_json(run_path / "run-set.json") or {}
    run_set_id = str(run_set_document.get("run_set_id", run_path.name))
    report_identity = {
        "run_set_id": run_set_id,
        "source_hashes": source_hashes,
        "policy": policy,
    }
    report_id = stable_id("report", report_identity)
    eligible_runs = {
        item["run_id"]
        for item in bundle.eligibility
        if item["analysis"] == "PERFORMANCE" and item["eligible"]
    }
    generated_at = datetime.now(UTC).isoformat()
    report_directory = run_path / "report"
    chart_paths = {
        "report/coverage.svg": report_directory / "coverage.svg",
        "report/space-encode.svg": report_directory / "space-encode.svg",
        "report/space-decode.svg": report_directory / "space-decode.svg",
    }
    chart_content = {
        "report/coverage.svg": _coverage_svg(_coverage_counts(bundle)),
        "report/space-encode.svg": _pareto_svg(
            bundle.summaries,
            "semantic_encode_mb_per_second_micro",
            "Compression factor vs encode throughput",
        ),
        "report/space-decode.svg": _pareto_svg(
            bundle.summaries,
            "semantic_decode_mb_per_second_micro",
            "Compression factor vs decode throughput",
        ),
    }
    for name, path in chart_paths.items():
        _atomic_bytes(path, chart_content[name].encode("utf-8"))
        table_hashes[name] = _sha256_file(path)
    report = {
        "schema_version": "tscb.report.v2",
        "report_id": report_id,
        "run_set_id": run_set_id,
        "generated_at_utc": generated_at,
        "policy": policy,
        "methodology": {
            "input_contract": "APPEND_ONLY_RUN_COMPONENTS_AND_FROZEN_TASK_UNIVERSE",
            "per_dataset_first": True,
            "micro_size_ratio_formula": "sum(FinalBits)/sum(CanonicalRawBits)",
            "micro_throughput_formula": "sum(CanonicalBytes)/sum(Time)",
            "compression_factor_geomean": True,
            "bootstrap_interval": "DETERMINISTIC_PERCENTILE_INTERVAL_FOR_MEDIAN",
            "comparison_key_order": [
                "SemanticComparabilityKey",
                "ExecutionComparabilityKey",
                "ResourceProfileKey",
            ],
            "coverage_as_score": False,
        },
        "notices": {
            "size_ratio_direction": "LOWER_IS_BETTER",
            "compression_factor_direction": "HIGHER_IS_BETTER",
            "throughput_unit": "DECIMAL_MB_PER_SECOND",
            "timing_scope_must_match": True,
            "thread_budget_must_match": True,
            "model_and_index_bits_in_final_bits": True,
            "cold_start_must_match": True,
        },
        "source_hashes": source_hashes,
        "derived_artifact_hashes": table_hashes,
        "task_count": len(bundle.coverage),
        "summary_count": len(bundle.summaries),
        "eligible_run_count": len(eligible_runs),
        "coverage_counts": _coverage_counts(bundle),
        "environment": _optional_json(run_path / "environment.json"),
        "dataset_evidence": _dataset_evidence(run_path),
        "run_set": run_set_document,
        "source_registry": _optional_json(run_path / "source_registry_snapshot.json"),
        "codec_registry": _optional_json(run_path / "codec_registry_snapshot.json"),
        "eligibility": list(bundle.eligibility),
        "summaries": list(bundle.summaries),
        "corpus_summaries": list(bundle.corpus_summaries),
        "coverage": list(bundle.coverage),
        "comparability_groups": list(bundle.comparability_groups),
        "pareto": list(bundle.pareto),
        "rankings": list(bundle.rankings),
    }
    report_json = report_directory / "report.json"
    _atomic_json(report_json, report)
    markdown = _markdown(report)
    _atomic_bytes(report_directory / "report.md", markdown.encode("utf-8"))
    _atomic_bytes(report_directory / "report.html", _html(markdown, report).encode("utf-8"))
    output_hashes = {
        **table_hashes,
        "report/report.json": _sha256_file(report_json),
        "report/report.md": _sha256_file(report_directory / "report.md"),
        "report/report.html": _sha256_file(report_directory / "report.html"),
    }
    _atomic_json(
        run_path / "layer5-statistics.json",
        {
            "schema_version": "tscb.layer5-statistics.v2",
            "report_id": report_id,
            "run_set_id": run_set_id,
            "generated_at_utc": generated_at,
            "source_hashes": source_hashes,
            "output_hashes": output_hashes,
            "task_count": len(bundle.coverage),
            "summary_count": len(bundle.summaries),
            "eligible_run_count": len(eligible_runs),
        },
    )
    output_hashes["layer5-statistics.json"] = _sha256_file(run_path / "layer5-statistics.json")
    return ReportResult(
        report_id=report_id,
        report_directory=report_directory,
        summary_count=len(bundle.summaries),
        eligible_run_count=len(eligible_runs),
        task_count=len(bundle.coverage),
        output_hashes=output_hashes,
    )
