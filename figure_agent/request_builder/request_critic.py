from __future__ import annotations

from typing import Any

from figure_agent.common.constants import CHART_TYPES, DIAGRAM_TYPES, OUTPUT_FORMATS
from figure_agent.request_builder.validators import validate_figure_request


class RequestCritic:
    def review(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        try:
            validate_figure_request(request)
        except ValueError as exc:
            issues.append(self._issue("error", "schema_invalid", str(exc)))
            return issues

        context = request["context"]
        if request["figure_kind"] == "chart":
            if not context.get("result_summary"):
                issues.append(self._issue("error", "missing_result_summary", "Chart requests require context.result_summary."))
            chart_type = context.get("chart_type")
            if chart_type not in CHART_TYPES:
                issues.append(self._issue("error", "unsupported_chart_type", f"Unsupported chart_type: {chart_type}"))
            if not any(item["kind"] in {"table_file", "json_file"} for item in request["evidence_refs"]):
                issues.append(self._issue("error", "missing_table_evidence", "Chart requests require table_file or json_file evidence."))
        else:
            if not context.get("method_summary"):
                issues.append(self._issue("error", "missing_method_summary", "Diagram requests require context.method_summary."))
            diagram_type = context.get("diagram_type")
            if diagram_type not in DIAGRAM_TYPES:
                issues.append(self._issue("error", "unsupported_diagram_type", f"Unsupported diagram_type: {diagram_type}"))

        unsupported_formats = [item for item in context["output_formats"] if item not in OUTPUT_FORMATS]
        if unsupported_formats:
            issues.append(self._issue("error", "unsupported_output_format", f"Unsupported output format(s): {unsupported_formats}"))
        if context["max_revision_rounds"] > 2:
            issues.append(self._issue("error", "too_many_revision_rounds", "max_revision_rounds must be <= 2."))

        for evidence in request["evidence_refs"]:
            if evidence["kind"] in {"table_file", "json_file"} and not evidence.get("path"):
                issues.append(self._issue("error", "missing_table_path", f"Evidence {evidence['evidence_id']} requires path."))
            if evidence["kind"] in {"text_block", "section_excerpt"} and not any([evidence.get("content"), evidence.get("path"), evidence.get("paragraph_ref")]):
                issues.append(self._issue("error", "missing_text_locator", f"Evidence {evidence['evidence_id']} requires content, path, or paragraph_ref."))

        return issues

    def has_errors(self, issues: list[dict[str, Any]]) -> bool:
        return any(issue["severity"] == "error" for issue in issues)

    def _issue(self, severity: str, code: str, message: str) -> dict[str, Any]:
        return {
            "severity": severity,
            "code": code,
            "message": message,
            "candidate_id": None,
        }
