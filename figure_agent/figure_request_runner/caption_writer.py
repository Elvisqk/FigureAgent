from __future__ import annotations

from typing import Any

from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.constants import REPORT_DIR
from figure_agent.common.persistence import write_json
from figure_agent.common.validators import validate_payload


class CaptionWriter:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def build(self, request: dict[str, Any], intent: dict[str, Any], spec: dict[str, Any], render_result: dict[str, Any]) -> dict[str, Any]:
        caption = self._try_llm_build(request, intent, spec, render_result)
        if caption is None:
            caption = self._rule_build(request, intent, spec, render_result)
        validate_payload(caption, "caption_draft.schema.json")
        write_json(REPORT_DIR / f"{request['figure_id']}_attempt_{render_result['attempt']}_caption.json", caption)
        return caption

    def _try_llm_build(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        spec: dict[str, Any],
        render_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            caption = self.llm_client.json_completion(
                schema_guard_prompt("caption_draft.schema.json", "Write a concise academic figure caption grounded in the request, intent, spec, and render result"),
                {
                    "figure_request": request,
                    "figure_intent": intent,
                    "figure_spec": spec,
                    "render_result": {
                        "status": render_result.get("status"),
                        "renderer": render_result.get("renderer"),
                        "output_files": render_result.get("output_files", []),
                        "metadata": render_result.get("metadata", {}),
                        "error": render_result.get("error"),
                    },
                    "rules": [
                        "The root object must be the CaptionDraft itself.",
                        "Do not introduce claims, metrics, methods, or datasets not present in the inputs.",
                        "short_caption should be suitable for a figure list.",
                        "full_caption should explain what is plotted or diagrammed and how to read it.",
                        "claim_alignment must state how the caption remains grounded in the request and evidence.",
                    ],
                },
            )
            if caption is None:
                return None
            caption["request_id"] = request["request_id"]
            caption["figure_id"] = request["figure_id"]
            validate_payload(caption, "caption_draft.schema.json")
            return caption
        except (LLMClientError, ValueError, TypeError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _rule_build(self, request: dict[str, Any], intent: dict[str, Any], spec: dict[str, Any], render_result: dict[str, Any]) -> dict[str, Any]:
        if spec["figure_kind"] == "chart":
            mapping = spec["data_mapping"]
            uncertainty = " Error bars denote uncertainty from the mapped source column." if mapping.get("error_y") else ""
            full = f"{intent['claim']} The chart maps {mapping.get('x')} to {mapping.get('y')}.{uncertainty}"
            short = f"{spec['chart_type'].replace('_', ' ').title()} for {request['target_section']}."
        else:
            full = f"{intent['claim']} The diagram summarizes the ordered structure and information flow."
            short = f"{spec['diagram_type'].replace('_', ' ').title()} for {request['target_section']}."
        caption = {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "short_caption": short,
            "full_caption": full,
            "claim_alignment": "Caption is derived from the request claim and rendered spec without adding new claims.",
        }
        return caption
