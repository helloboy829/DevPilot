"""Synthetic reporting fixtures: no customer material or historical metrics."""

from dataclasses import replace

import pytest
from devpilot.reporting import EffectResults, PerformanceResults, ReportFacts, ReportValidationError, build_preview, get_template, list_templates


def facts(**overrides):
    fields = dict(
        title="Synthetic report",
        project_name="Fictional project",
        component_name="Demo component",
        component_version="demo-version",
        tester="Demo operator",
        test_period="Synthetic test window",
        environment="Isolated mock",
        scope="Synthetic cases only",
        methodology="Manual entry from fictional evidence",
        evidence_notes="Fictional evidence reference",
        limitations="Unverified input; not an acceptance decision",
        evaluation_mode="BASELINE",
        effect=EffectResults(total=7, passed=3, failed=1, errors=1, pending=1, not_run=1),
    )
    return ReportFacts(**(fields | overrides))


def preview(data=None, template=None):
    return build_preview(data or facts(), template=template or get_template("component-evaluation-zh", "1.0.0"), generated_by="synthetic-user", generated_at="synthetic-clock")


def test_rates_use_frozen_total_and_preserve_unfinished_cases():
    result = preview()
    assert result["facts"]["effect"]["total"] == 7
    assert result["derived"]["case_pass_rate"] == pytest.approx(3 / 7)
    assert result["facts"]["effect"]["pending"] == 1
    assert result["facts"]["effect"]["not_run"] == 1
    assert result["status"] == "DRAFT"
    assert result["source"] == "manual_unverified"
    assert "人工填报" in result["markdown"]
    assert "不构成验收结论" in result["markdown"]


@pytest.mark.parametrize("changes", [{"total": 0}, {"total": True}, {"total": 7.5}, {"passed": -1}, {"passed": 8}, {"pending": 0}])
def test_effect_rejects_inconsistent_or_noninteger_counts(changes):
    values = dict(total=7, passed=3, failed=1, errors=1, pending=1, not_run=1)
    with pytest.raises(ReportValidationError):
        EffectResults(**(values | changes))


def performance(**overrides):
    return PerformanceResults(**(dict(requests=9, successful_requests=6, concurrency=2) | overrides))


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_nonfinite_negative_or_boolean_measurements_are_rejected(value):
    with pytest.raises(ReportValidationError):
        performance(latency_mean_ms=value, latency_sample_count=6)


@pytest.mark.parametrize(
    "changes",
    [
        {"successful_requests": 10},
        {"concurrency": 0},
        {"latency_mean_ms": 23.0},
        {"latency_mean_ms": 23.0, "latency_sample_count": 7},
        {"metric_population": "unknown"},
        {"ttft_mean_ms": 2.0, "ttft_sample_count": 6},
        {"content_streaming": True, "ttft_mean_ms": 2.0, "ttft_sample_count": 7},
        {"throughput_tokens_per_s": 12.0},
    ],
)
def test_performance_coverage_population_streaming_and_token_source(changes):
    with pytest.raises(ReportValidationError):
        performance(**changes)


def test_missing_metrics_are_unavailable_not_zero_and_no_acceptance_is_inferred():
    result = preview(facts(evaluation_mode="ACCEPTANCE", effect=None, performance=performance()))
    assert result["derived"]["success_rate"] == pytest.approx(6 / 9)
    assert result["facts"]["performance"]["latency_mean_ms"] is None
    assert result["facts"]["performance"]["ttft_mean_ms"] is None
    assert "未测量" in result["markdown"]
    assert "未经审批" in result["markdown"]
    assert "verdict" not in result


def test_valid_streaming_and_all_attempt_latency_are_reported_with_population():
    perf = performance(metric_population="all_attempts", latency_sample_count=9, latency_mean_ms=23.0, content_streaming=True, ttft_mean_ms=2.0, ttft_sample_count=6, throughput_tokens_per_s=12.0, token_source="provider_usage")
    result = preview(facts(performance=perf))
    assert r"all\_attempts" in result["markdown"]
    assert r"provider\_usage" in result["markdown"]
    assert result["facts"]["performance"]["ttft_sample_count"] == 6


def test_template_version_is_explicit_and_unknown_version_is_not_latest():
    assert list_templates()
    with pytest.raises(ReportValidationError, match="template"):
        get_template("component-evaluation-zh", "latest")
    with pytest.raises(ReportValidationError):
        get_template("../../private", "1.0.0")


def test_template_and_fact_snapshots_do_not_change_when_new_revision_is_rendered():
    old = preview()
    template = get_template("component-evaluation-zh", "1.0.0")
    new = preview(facts(title="New draft"), replace(template, version="2.0.0"))
    assert old["template"]["version"] == "1.0.0"
    assert old["facts"]["title"] == "Synthetic report"
    assert old["manifest"]["facts_sha256"] != new["manifest"]["facts_sha256"]
    assert old["manifest"]["template_sha256"] != new["manifest"]["template_sha256"]
    assert old["manifest"]["renderer_version"]
    assert preview() == old


def test_markup_and_table_cells_cannot_inject_report_sections_or_html():
    result = preview(facts(title="<script>alert(1)</script>", project_name="x|y\n# forged"))
    assert "<script>" not in result["markdown"]
    assert "\n# forged" not in result["markdown"]
    assert "x\\|y" in result["markdown"]


@pytest.mark.parametrize("changes", [{"effect": None}, {"title": " "}, {"title": "x" * 201}, {"evaluation_mode": "PASS"}])
def test_required_facts_and_mode_are_validated(changes):
    with pytest.raises(ReportValidationError):
        facts(**changes)


def test_english_template_is_independent_and_preserves_manual_draft_warning():
    result = preview(template=get_template("component-evaluation-en", "1.0.0"))
    assert "DRAFT" in result["markdown"]
    assert "unverified" in result["markdown"]
    assert "not an acceptance decision" in result["markdown"]


def test_new_template_does_not_mutate_facts_or_old_artifact():
    old = preview()
    new = preview(template=replace(get_template("component-evaluation-zh", "1.0.0"), version="2.0.0"))
    assert old["manifest"]["facts_sha256"] == new["manifest"]["facts_sha256"]
    assert old["manifest"]["template_sha256"] != new["manifest"]["template_sha256"]
    assert old["manifest"]["template_version"] == "1.0.0"
    assert new["manifest"]["template_version"] == "2.0.0"
    assert '"template_version": "1.0.0"' in old["markdown"]


@pytest.mark.parametrize(
    "changes",
    [
        {"effect": {"total": True}},
        {"effect": {"unexpected": "unsupported"}},
        {"performance": []},
        {"source": "platform_verified"},
        {"schema_version": "unknown"},
    ],
)
def test_raw_facts_reject_unsupported_shapes_without_echoing_values(changes):
    from dataclasses import asdict

    with pytest.raises(ReportValidationError) as exc:
        ReportFacts.from_dict(asdict(facts()) | changes)
    assert "platform_verified" not in str(exc.value)


def test_extreme_measurements_are_validation_errors_not_server_errors():
    with pytest.raises(ReportValidationError):
        performance(latency_mean_ms=10**1000, latency_sample_count=6)


def test_all_failed_run_and_partial_ttft_coverage_remain_explicit():
    failed = preview(facts(effect=None, performance=performance(successful_requests=0, metric_population="failed_attempts", latency_mean_ms=12, latency_sample_count=9)))
    assert failed["derived"]["success_rate"] == 0
    assert failed["facts"]["performance"]["ttft_mean_ms"] is None
    partial = preview(facts(performance=performance(content_streaming=True, ttft_mean_ms=1, ttft_sample_count=2)))
    assert partial["facts"]["performance"]["successful_requests"] == 6
    assert partial["facts"]["performance"]["ttft_sample_count"] == 2


def test_advisory_is_escaped_separate_and_bound_to_exact_facts_and_template():
    from devpilot.reporting import ReportAdvisory, facts_digest

    data = facts()
    attachment = ReportAdvisory(
        summary="<script>unsafe</script> | # note",
        findings=("Pending synthetic cases",),
        recommendations=(),
        model_name="synthetic",
        facts_sha256=facts_digest(data),
        template_id="component-evaluation-zh",
        template_version="1.0.0",
        human_confirmed=True,
    )
    result = build_preview(data, template=get_template("component-evaluation-zh", "1.0.0"), generated_by="synthetic-user", generated_at="synthetic-clock", advisory=attachment)
    assert result["facts"] == preview()["facts"]
    assert result["derived"] == preview()["derived"]
    assert result["template"] == preview()["template"]
    assert "<script>" not in result["markdown"]
    assert "&lt;script&gt;" in result["markdown"]
    assert "来源未经认证" in result["markdown"]
    assert result["manifest"]["renderer_version"] == "advisory-preview.v1"
    assert result["manifest"]["advisory_sha256"]
    with pytest.raises(ReportValidationError, match="does not match"):
        build_preview(replace(data, title="Revised"), template=get_template("component-evaluation-zh", "1.0.0"), generated_by="x", generated_at="x", advisory=attachment)
    with pytest.raises(ReportValidationError, match="does not match"):
        build_preview(data, template=get_template("component-evaluation-en", "1.0.0"), generated_by="x", generated_at="x", advisory=attachment)
