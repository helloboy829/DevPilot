import copy

import pytest
from devpilot.reporting import ReportValidationError
from devpilot.reporting.project import build_project_preview, project_templates
from test_reports_router import payload


def test_project_preserves_per_component_denominators_and_template():
    first = payload()["facts"]
    second = copy.deepcopy(first)
    second["component_name"] = "Synthetic second"
    second["effect"] = dict(total=3, passed=1, failed=2, errors=0, pending=0, not_run=0)
    result = build_project_preview([first, second], "project-evaluation-zh", "1.0.0", generated_by="synthetic", generated_at="synthetic")
    assert len(result["components"]) == 2
    assert result["components"][1]["derived"]["case_pass_rate"] == 1 / 3
    assert "overall_accuracy" not in result
    assert result["manifest"]["template_version"] == "1.0.0"
    assert result["status"] == "DRAFT"
    assert result["manifest"]["facts_sha256"]
    assert "Synthetic second" in result["markdown"]


def test_mismatched_projects_or_duplicate_components_cannot_merge():
    first = payload()["facts"]
    other = copy.deepcopy(first)
    other["project_name"] = "Different"
    with pytest.raises(ReportValidationError):
        build_project_preview([first, other], "project-evaluation-zh", "1.0.0", generated_by="x", generated_at="x")
    with pytest.raises(ReportValidationError):
        build_project_preview([first, first], "project-evaluation-zh", "1.0.0", generated_by="x", generated_at="x")
    assert {t["language"] for t in project_templates()} == {"zh", "en"}
