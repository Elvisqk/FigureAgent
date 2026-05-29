from __future__ import annotations

from typing import Any

from figure_agent.request_builder.models import ResolvedCandidate
from figure_agent.request_builder.validators import slugify


class RequestComposer:
    def compose(self, context: dict[str, Any], resolved: ResolvedCandidate, index: int) -> dict[str, Any]:
        candidate = resolved.candidate
        request = {
            "request_id": f"figreq_{slugify(context['paper_id'])}_{index:03d}",
            "paper_id": context["paper_id"],
            "figure_id": self._figure_id(candidate),
            "figure_kind": candidate.figure_kind,
            "goal": candidate.goal,
            "target_section": candidate.target_section,
            "context": {
                "result_summary": candidate.result_summary if candidate.figure_kind == "chart" else None,
                "method_summary": candidate.method_summary if candidate.figure_kind == "diagram" else None,
                "style_profile": context.get("style_profile", "academic_default"),
                "output_formats": context.get("output_formats", ["png", "pdf"]),
                "max_revision_rounds": context.get("max_revision_rounds", 2),
            },
            "evidence_refs": resolved.evidence_refs,
        }
        if candidate.figure_kind == "chart":
            request["context"]["chart_type"] = candidate.suggested_chart_type or "grouped_bar"
        else:
            request["context"]["diagram_type"] = candidate.suggested_diagram_type or "pipeline"
        return request

    def _figure_id(self, candidate) -> str:
        section = slugify(candidate.target_section, max_length=48)
        source = slugify(candidate.source_id, max_length=48)
        return f"fig_{section}_{source}"
