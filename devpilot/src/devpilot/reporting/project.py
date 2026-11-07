"""Sanitized project-level templates: shared context plus independent component results.

Only structural categories were taken from private reference documents. No source
names, text, thresholds, historic measurements or customer artwork is packaged.
"""

import hashlib
import json

from devpilot.reporting import ReportFacts, ReportValidationError, build_preview, get_template


def project_templates():
    return [
        {"id": "project-evaluation-" + language, "version": "1.0.0", "language": language, "name": "项目级多组件测试报告" if language == "zh" else "Multi-component evaluation report", "schema_version": "project-report.v1"}
        for language in ("zh", "en")
    ]


def build_project_preview(components, template_id, template_version, *, generated_by, generated_at):
    template = next((t for t in project_templates() if t["id"] == template_id and t["version"] == template_version), None)
    if template is None:
        raise ReportValidationError("Unknown project template version")
    if not isinstance(components, list) or not 1 <= len(components) <= 30:
        raise ReportValidationError("A project report requires 1 to 30 component snapshots")
    facts = [ReportFacts.from_dict(item) for item in components]
    first = facts[0]
    if any((item.project_name, item.tester, item.test_period, item.evaluation_mode) != (first.project_name, first.tester, first.test_period, first.evaluation_mode) for item in facts):
        raise ReportValidationError("All components must have the same project, tester, period and evaluation mode")
    keys = [(item.component_name, item.component_version) for item in facts]
    if len(set(keys)) != len(keys):
        raise ReportValidationError("Duplicate component/version in project report")
    zh = template["language"] == "zh"
    detail_template = get_template("component-evaluation-" + template["language"], "1.0.0")
    previews = [build_preview(item, template=detail_template, generated_by=generated_by, generated_at=generated_at) for item in facts]

    # Escaping of all user data is owned by the component renderer.
    def safe(value):
        import html

        return (
            html.escape(value)
            .replace("|", "&#124;")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace("`", "&#96;")
            .replace("*", "&#42;")
            .replace("_", "&#95;")
            .replace("[", "&#91;")
            .replace("]", "&#93;")
            .replace("\\", "&#92;")
            .replace("#", "&#35;")
        )

    heading = "项目级 AI 组件测试报告（未核验草稿）" if zh else "Project AI component evaluation (unverified draft)"
    lines = [
        "# " + heading,
        "",
        ("项目：" if zh else "Project: ") + safe(first.project_name),
        "",
        "## " + ("1. 测试目的与范围" if zh else "1. Purpose and scope"),
        safe(first.scope),
        "",
        "## " + ("2. 测试依据与方法" if zh else "2. Basis and methodology"),
        safe(first.methodology),
        "",
        "## " + ("3. 测试环境与对象清单" if zh else "3. Environment and component inventory"),
        safe(first.environment),
        "",
        "| Component | Version | Effect cases | Case pass rate | Requests | Mean latency (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for item, preview in zip(facts, previews):
        rate = preview["derived"]["case_pass_rate"]
        lines.append(
            "| "
            + " | ".join(
                [
                    safe(item.component_name),
                    safe(item.component_version),
                    str(item.effect.total) if item.effect else "N/A",
                    f"{rate:.2%}" if rate is not None else "N/A",
                    str(item.performance.requests) if item.performance else "N/A",
                    str(item.performance.latency_mean_ms) if item.performance and item.performance.latency_mean_ms is not None else "N/A",
                ]
            )
            + " |"
        )
    lines.extend(["", "## " + ("4. 各组件效果与性能结果" if zh else "4. Per-component effect and performance results")])
    for preview in previews:
        # Nest component section headings without injecting markup from facts.
        lines.extend(["", "\n".join("#" + line if line.startswith("#") else line for line in preview["markdown"].splitlines())])
    lines.extend(
        [
            "",
            "## " + ("5. 结论、限制与复核" if zh else "5. Conclusions, limitations and review"),
            "本报告为人工录入草稿，不自动给出项目验收结论。不跨组件平均准确率或性能指标；正式出具前须核对证据、验收标准与人工复核。"
            if zh
            else "Manual unverified draft: no automatic project acceptance verdict, cross-component average accuracy or pooled latency. Verify evidence, acceptance criteria and human review before issuance.",
            "",
            "## " + ("6. 附录与版本清单" if zh else "6. Appendices and version manifest"),
            "Template: " + template_id + "@" + template_version,
        ]
    )

    def digest(data):
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    return {
        "status": "DRAFT",
        "source": "manual_unverified",
        "template": template,
        "components": previews,
        "manifest": {
            "schema_version": "project-report.v1",
            "template_id": template_id,
            "template_version": template_version,
            "template_sha256": digest(template),
            "facts_sha256": digest([p["facts"] for p in previews]),
            "renderer_version": "project-preview.v1",
            "generated_by": generated_by,
            "generated_at": generated_at,
        },
        "markdown": "\n".join(lines),
    }
