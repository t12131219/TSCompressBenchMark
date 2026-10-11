from __future__ import annotations

import copy
from html.parser import HTMLParser

import pytest
from test_comparison_analysis_extensions import add_quality, experiment

from tscompbench.comparison.analysis import analyze_comparison
from tscompbench.comparison.analysis_extensions import augment_analysis
from tscompbench.comparison.report_renderer import render_comparison_report


class ParsedReport(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.elements = []
        self.links = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        self.elements.append(tag)
        if tag == "a":
            self.links.append(dict(attributes)["href"])

    def handle_data(self, data):
        self.text.append(data)


def report(*, missing=False, quality=False):
    plan, trials, policy, corpus = experiment()
    if missing:
        trials = [t for t in trials if t["cell_id"] != "ad2"]
    if quality:
        add_quality(plan, trials)
    analysis = analyze_comparison(plan, trials, policy)
    extension = augment_analysis(analysis, plan, trials, corpus)
    bundle = {
        "contract": {"name": "G-TEST", "fidelity": {"kind": "QUALITY_CURVE"}},
        "corpus": corpus,
    }
    return analysis, plan, bundle, extension


def test_report_shows_full_denominators_actual_metrics_and_evidence_without_mutation():
    analysis, plan, bundle, extension = report()
    originals = copy.deepcopy((analysis, plan, bundle, extension))
    source = render_comparison_report(
        analysis,
        plan=plan,
        bundle=bundle,
        extensions=extension,
        raw_links={
            "原始试次": "comparison_trials.jsonl",
            "审查": "https://example.org/review?a=1&b=2",
        },
    )
    parsed = ParsedReport(source)
    text = "".join(parsed.text)
    assert "4 / 4" in text
    assert "FinalBits" in text and "PROCESS RSS bytes" in text
    assert "LOSSLESS · 精确参考" in text
    assert "CORE_COMPLETE" in text
    assert "SourceCapabilityMatrix" in text
    assert "StandalonePortMatrix" in text
    assert "BenchProfileMatrix" in text
    assert "PipelineCoverageMatrix" in text
    assert "UNKNOWN" in text
    assert "external_side_information_bits" in text
    assert "300" in text
    assert "comparison_trials.jsonl" in parsed.links
    assert "https://example.org/review?a=1&b=2" in parsed.links
    assert "RATIO_OF_MEAN_PROCESS_TIMES_FIRST_OVER_SECOND" in text
    assert (analysis, plan, bundle, extension) == originals


def test_missing_cells_never_vanish_or_create_partial_core_aggregates():
    analysis, plan, bundle, extension = report(missing=True)
    source = render_comparison_report(analysis, plan=plan, bundle=bundle, extensions=extension)
    text = "".join(ParsedReport(source).text)
    assert "CORE_INCOMPLETE" in text
    assert "3 / 4" in text
    assert "NOT_RUN" in text
    assert "PARTIAL_OBSERVED_FRONTIER" in text
    assert "N/A" in text
    assert "ad2" in text
    assert extension["source_balanced"]["aggregates"][0]["source_balanced_size_ratio"] is None


def test_unbounded_points_keep_guarantees_and_original_channel_quality():
    analysis, plan, bundle, extension = report(quality=True)
    source = render_comparison_report(analysis, plan=plan, bundle=bundle, extensions=extension)
    text = "".join(ParsedReport(source).text)
    assert "RMSE 0.0353553 / MaxAE 0.06" in text
    assert '"kind": "UNBOUNDED"' in text
    assert '"fixed_error_ranking_eligible": false' in text
    assert "RMSE_V1:value/000000" in text
    assert "PER_CHANNEL_ORIGINAL_UNITS_NO_COMPOSITE_QUALITY_SCORE" in text


def test_report_escapes_titles_identity_fields_parameters_and_link_labels():
    analysis, plan, bundle, extension = report()
    injection = '<script>alert("unexpected")</script>'
    bundle["contract"]["name"] = injection
    analysis["matrix"][0]["parameters"] = {"label": injection}
    analysis["matrix"][0]["member_id"] = injection
    source = render_comparison_report(
        analysis, bundle=bundle, raw_links={injection: "trials.jsonl"}
    )
    parsed = ParsedReport(source)
    assert "script" not in parsed.elements
    assert injection in "".join(parsed.text)
    assert injection not in source
    assert "&lt;script&gt;" in source


@pytest.mark.parametrize(
    "unsafe",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "%6aavascript:alert(1)",
        "//example.org/trials",
        "\\example.org\\trials",
        "artifacts/%0aevil",
    ],
)
def test_active_or_ambiguous_artifact_links_are_rejected(unsafe):
    analysis, *_ = report()
    with pytest.raises(ValueError, match="unsupported URL"):
        render_comparison_report(analysis, raw_links={"trials": unsafe})


@pytest.mark.parametrize("invalid", [None, "NaN", "Infinity"])
def test_missing_nonfinite_quality_and_resource_metrics_display_na(invalid):
    analysis, plan, bundle, extension = report(quality=True)
    point = extension["quality_curve"]["points"][0]
    point["quality"]["original_domain_rmse"] = invalid
    point["metrics"]["observations"]["process_rss_bytes"] = {"max": invalid}
    source = render_comparison_report(analysis, plan=plan, bundle=bundle, extensions=extension)
    text = "".join(ParsedReport(source).text)
    assert "RMSE N/A / MaxAE 0.06" in text


def test_report_rejects_different_plan_raw_identity_and_missing_matrix_rows():
    analysis, plan, bundle, extension = report()
    bad_plan = copy.deepcopy(plan)
    bad_plan["comparison_id"] = "different"
    with pytest.raises(ValueError, match="plan differs"):
        render_comparison_report(analysis, plan=bad_plan)
    extension["audited_trials_sha256"] = "different"
    with pytest.raises(ValueError, match="extensions differ"):
        render_comparison_report(analysis, extensions=extension)
    analysis["matrix"].pop()
    with pytest.raises(ValueError, match="full fixed analysis matrix"):
        render_comparison_report(analysis)


def test_extension_evidence_recheck_failure_changes_report_status():
    analysis, plan, bundle, extension = report()
    extension["audit_issues"] = [{"cell_id": "ad1", "issues": ["RAW_BITS_MISMATCH"]}]
    source = render_comparison_report(analysis, plan=plan, bundle=bundle, extensions=extension)
    text = "".join(ParsedReport(source).text)
    assert "EVIDENCE_RECHECK_FAILED" in text
    assert "RAW_BITS_MISMATCH" in text
    assert "RATIO_OF_MEAN_PROCESS_TIMES_FIRST_OVER_SECOND" not in text


def test_saved_job_disclosures_show_actual_input_recipe_build_runtime_and_isa():
    analysis, plan, bundle, extension = report()
    disclosure = {
        "path": "COLUMN_INDEPENDENT",
        "actual_input_schema_id": "original-f64-mts",
        "recipe_id": "charged-column-assembly-v1",
        "build_id": "actual-build-sha",
        "runtime_id": "actual-runtime-id",
        "isa": ["AVX2"],
    }
    source = render_comparison_report(
        analysis,
        plan=plan,
        bundle=bundle,
        extensions=extension,
        disclosures={"ad1": disclosure},
    )
    text = "".join(ParsedReport(source).text)
    assert "COLUMN_INDEPENDENT" in text
    assert "charged-column-assembly-v1" in text
    assert "actual-build-sha" in text and "actual-runtime-id" in text
    assert "AVX2" in text
    with pytest.raises(ValueError, match="unplanned cell"):
        render_comparison_report(analysis, disclosures={"unknown": disclosure})
