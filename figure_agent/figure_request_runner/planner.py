from __future__ import annotations

from typing import Any

from figure_agent.common.constants import INTENT_DIR, REPORT_DIR
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.persistence import append_jsonl, write_json
from figure_agent.common.validators import validate_payload


class FigurePlanner:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        validate_payload(request, "figure_request.schema.json")
        intent = self._try_llm_plan(request)
        if intent is None:
            intent = self._rule_plan(request)
            self._trace(request, "fallback", self.last_llm_error)
        else:
            self._trace(request, "llm", None)
        validate_payload(intent, "figure_intent.schema.json")
        write_json(INTENT_DIR / f"{request['figure_id']}_intent.json", intent)
        return intent

    def _trace(self, request: dict[str, Any], source: str, error: str | None) -> None:
        append_jsonl(REPORT_DIR / f"{request['figure_id']}_llm_trace.jsonl", {
            "component": "planner",
            "source": source,
            "error": error,
        })

    def _try_llm_plan(self, request: dict[str, Any]) -> dict[str, Any] | None:
        try:
            intent = self.llm_client.json_completion(
                schema_guard_prompt("figure_intent.schema.json", "Turn a FigureRequest into a FigureIntent"),
                {
                    "figure_request": request,
                    "allowed_chart_types": ["line", "bar", "grouped_bar", "scatter", "heatmap"],
                    "allowed_diagram_types": ["pipeline", "module_architecture", "agent_workflow", "decision_flow"],
                    "rules": [
                        "The root object must be the FigureIntent itself.",
                        "Use the request goal as the claim unless it is vague.",
                        "Do not invent metrics, methods, or datasets.",
                        "recommended_visualization must be one supported type.",
                    ],
                },
            )
            if intent is None:
                return None
            validate_payload(intent, "figure_intent.schema.json")
            return intent
        except (LLMClientError, ValueError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _rule_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        figure_kind = request["figure_kind"]
        context = request.get("context", {})
        if figure_kind == "chart":
            visualization = context.get("chart_type") or self._choose_chart_type(request["goal"])
            rationale = f"{visualization} is selected for the requested chart comparison."
        else:
            visualization = context.get("diagram_type") or "pipeline"
            rationale = f"{visualization} is selected to communicate the requested method structure."

        intent = {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "claim": request["goal"],
            "figure_kind": figure_kind,
            "recommended_visualization": visualization,
            "target_section": request["target_section"],
            "planning_rationale": rationale,
        }
        return intent

    def _choose_chart_type(self, goal: str) -> str:
        text = goal.lower()
        if "heatmap" in text:
            return "heatmap"
        if "scatter" in text or "correlation" in text:
            return "scatter"
        if "trend" in text or "over time" in text or "trajectory" in text:
            return "line"
        if "method" in text and ("dataset" in text or "standard deviation" in text or "std" in text):
            return "grouped_bar"
        return "bar"
