from __future__ import annotations

from typing import Any

from figure_agent.common.constants import REPORT_DIR
from figure_agent.figure_request_runner.diagram_planner import DiagramPlanner
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.persistence import append_jsonl
from figure_agent.common.validators import validate_payload


class FigureSpecGenerator:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None, diagram_planner: DiagramPlanner | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.diagram_planner = diagram_planner or DiagramPlanner()
        self.last_llm_error: str | None = None

    def generate(self, request: dict[str, Any], bound_intent: dict[str, Any]) -> dict[str, Any]:
        schema = "chart_spec.schema.json" if bound_intent["figure_kind"] == "chart" else "diagram_spec.schema.json"
        spec = self._try_llm_generate(request, bound_intent, schema)
        if spec is None:
            spec = self._rule_generate(request, bound_intent)
            self._trace(request, "fallback", self.last_llm_error)
        else:
            self._trace(request, "llm", None)
        validate_payload(spec, schema)
        return spec

    def _trace(self, request: dict[str, Any], source: str, error: str | None) -> None:
        append_jsonl(REPORT_DIR / f"{request['figure_id']}_llm_trace.jsonl", {
            "component": "spec_generator",
            "source": source,
            "error": error,
        })

    def _try_llm_generate(self, request: dict[str, Any], bound_intent: dict[str, Any], schema: str) -> dict[str, Any] | None:
        try:
            spec = self.llm_client.json_completion(
                schema_guard_prompt(schema, "Generate a deterministic render spec from a bound figure intent"),
                {
                    "figure_request": request,
                    "bound_figure_intent": bound_intent,
                    "allowed_chart_types": ["line", "bar", "grouped_bar", "scatter", "heatmap"],
                    "allowed_diagram_types": ["pipeline", "module_architecture", "agent_workflow", "decision_flow"],
                    "rules": [
                        "The root object must be the render spec itself.",
                        "Renderer consumes only structured JSON, no natural-language rendering instructions.",
                        "All key visual elements in bound_figure_intent must be covered by traceability.",
                        "Use only data fields selected by EvidenceBinder.",
                        "Use output basename equal to figure_id unless there is a strong reason not to.",
                    ],
                },
            )
            if spec is None:
                return None
            spec = self._apply_request_figure_text(spec, request)
            validate_payload(spec, schema)
            spec = self._normalize_spec(spec)
            self._validate_semantics(spec)
            return spec
        except (LLMClientError, ValueError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _rule_generate(self, request: dict[str, Any], bound_intent: dict[str, Any]) -> dict[str, Any]:
        if bound_intent["figure_kind"] == "chart":
            return self._chart_spec(request, bound_intent)
        return self._diagram_spec(request, bound_intent)

    def _apply_request_figure_text(self, spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        figure_text = self._figure_text(request)
        if any(figure_text.values()):
            spec["figure_text"] = figure_text
        else:
            spec.setdefault("figure_text", figure_text)
        return spec

    def _validate_semantics(self, spec: dict[str, Any]) -> None:
        if spec["figure_kind"] == "chart":
            mapping = spec["data_mapping"]
            chart_type = spec["chart_type"]
            if chart_type == "grouped_bar" and "series" not in mapping:
                raise ValueError("grouped_bar requires data_mapping.series")
            if chart_type == "heatmap" and "value" not in mapping:
                raise ValueError("heatmap requires data_mapping.value")

    def _normalize_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        if spec.get("figure_kind") != "chart":
            return spec
        mapping = spec.get("data_mapping", {})
        highlight_field = mapping.pop("highlight_field", None)
        highlight_value = mapping.pop("highlight_value", None)
        if highlight_field and highlight_value:
            style = spec.setdefault("style", {})
            style["highlight"] = {"field": highlight_field, "value": highlight_value}
        # Renderer ignores these semantic aliases; keeping them in data_mapping confuses validation.
        for key in ["label", "point_id", "color", "group"]:
            mapping.pop(key, None)
        return spec

    def _chart_spec(self, request: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
        evidence = request["evidence_refs"][0]
        primary = next(item for item in bound["visual_elements"] if item["element_role"] == "primary_metric")
        data_slice = primary["data_slice"]
        mapping = {"x": data_slice["x"], "y": data_slice["value"]}
        if data_slice.get("series"):
            mapping["series"] = data_slice["series"]
        uncertainty = next((item for item in bound["visual_elements"] if item["element_role"] == "uncertainty"), None)
        if uncertainty:
            mapping["error_y"] = uncertainty["data_slice"]["value"]
        if bound["recommended_visualization"] == "heatmap":
            mapping.setdefault("value", mapping.pop("y"))
            mapping.setdefault("y", mapping.get("series") or data_slice["x"])

        trace_map = [{
            "element_id": "primary_values",
            "evidence_ids": primary["backing_evidence_ids"],
            "spec_fields": ["data_mapping.x", "data_mapping.y"],
        }]
        if uncertainty:
            trace_map.append({
                "element_id": "uncertainty",
                "evidence_ids": uncertainty["backing_evidence_ids"],
                "spec_fields": ["data_mapping.error_y"],
            })

        return {
            "spec_version": "v1",
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "figure_kind": "chart",
            "chart_type": bound["recommended_visualization"],
            "title": None,
            "figure_text": self._figure_text(request),
            "data_ref": {"path": evidence["path"], "format": "csv" if evidence["path"].endswith(".csv") else "json"},
            "traceability": {"visual_element_map": trace_map},
            "data_mapping": mapping,
            "filters": [],
            "sort": None,
            "aggregation": None,
            "labels": {
                "x_label": self._label(mapping.get("x", "x")),
                "y_label": self._label(mapping.get("y") or mapping.get("value", "value")),
                "legend_title": self._label(mapping["series"]) if mapping.get("series") else None,
            },
            "style": {
                "palette": "tol_muted",
                "theme": request["context"].get("style_profile", "academic_default"),
                "dpi": 300,
                "font_scale": 1.0,
                "legend_position": "top",
            },
            "output": {
                "basename": request["figure_id"],
                "formats": request["context"]["output_formats"],
            },
        }

    def _diagram_spec(self, request: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
        plan = self.diagram_planner.plan(request, bound)
        has_feedback = any(edge.get("kind") == "feedback" for edge in plan["edges"])
        has_complex_grouping = bool(plan["clusters"]) or plan["layout_mode"] == "branch_merge"
        nodes = [
            {
                "id": str(node["id"]),
                "label": self._wrap_label(str(node["label"]), plan["label_policy"]["max_chars_per_line"], plan["label_policy"]["max_lines_per_node"]),
                "role": str(node["role"]),
                "cluster_id": self._cluster_id_for_node(str(node["id"]), plan["clusters"]),
                "lane_id": self._lane_id_for_node(str(node["id"]), plan["lanes"]),
                "priority": "primary" if str(node["id"]) in set(plan["primary_flow"]) else "secondary",
            }
            for node in plan["nodes"]
        ]
        edges = [
            {
                "source": edge["source"],
                "target": edge["target"],
                "label": edge.get("label"),
                "kind": edge.get("kind"),
            }
            for edge in plan["edges"]
        ]
        evidence_id = request["evidence_refs"][0]["evidence_id"]
        return {
            "spec_version": "v1",
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "figure_kind": "diagram",
            "diagram_type": bound["recommended_visualization"],
            "title": None,
            "figure_text": self._figure_text(request),
            "traceability": {
                "node_evidence_map": [{"node_id": node["id"], "evidence_ids": [evidence_id]} for node in nodes],
                "edge_evidence_map": [{"source": edge["source"], "target": edge["target"], "evidence_ids": [evidence_id]} for edge in edges],
            },
            "nodes": nodes,
            "edges": edges,
            "clusters": plan["clusters"],
            "lanes": plan["lanes"],
            "primary_flow": plan["primary_flow"],
            "secondary_edges": [edge for edge in edges if edge.get("kind") in {"secondary", "feedback"}],
            "routing_hints": plan["routing_hints"],
            "label_policy": plan["label_policy"],
            "layout": {
                "direction": self._direction_for_layout_mode(plan["layout_mode"]),
                "cluster_by": "lane_id" if plan["lanes"] else "cluster_id" if plan["clusters"] else None,
                "mode": plan["layout_mode"],
            },
            "style": {
                "theme": request["context"].get("style_profile", "academic_default"),
                "dpi": 300,
                "node_min_width": 170,
                "node_min_height": 64,
                "cluster_padding": 36 if has_complex_grouping else 24,
                "lane_spacing": 72 if plan["lanes"] else 48,
                "show_node_roles": False,
                "feedback_margin": 80 if has_feedback else 64,
                "canvas_margin": 64 if (has_feedback or has_complex_grouping) else 56,
            },
            "output": {"basename": request["figure_id"], "formats": [fmt for fmt in request["context"]["output_formats"] if fmt in {"svg", "png"}] or ["svg"]},
        }

    def _nodes_from_text(self, text: str) -> list[dict[str, str]]:
        separators = ["->", "=>", "\n", ";"]
        parts = [text]
        for separator in separators:
            if separator in text:
                parts = [part.strip() for part in text.split(separator) if part.strip()]
                break
        if len(parts) == 1:
            parts = [part.strip(" .") for part in text.replace(" then ", ";").split(";") if part.strip()]
        if len(parts) < 2:
            parts = ["Input Data", "Processing", "Output"]
        parts = parts[:8]
        nodes = []
        for idx, label in enumerate(parts):
            role = "input" if idx == 0 else "output" if idx == len(parts) - 1 else "process"
            nodes.append({"id": f"n{idx + 1}", "label": label[:60], "role": role})
        return nodes

    def _figure_text(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context", {})
        notes = context.get("figure_notes") or context.get("notes") or []
        if isinstance(notes, str):
            notes = [notes]
        return {
            "title": context.get("figure_title") or context.get("display_title"),
            "subtitle": context.get("figure_subtitle") or context.get("subtitle"),
            "notes": [str(note) for note in notes if str(note).strip()],
            "footer": context.get("figure_footer") or context.get("footer"),
        }

    def _direction_for_layout_mode(self, layout_mode: str) -> str:
        if layout_mode in {"layered_tb", "swimlane_tb"}:
            return "TB"
        if layout_mode == "grid":
            return "GRID"
        return "LR"

    def _cluster_id_for_node(self, node_id: str, clusters: list[dict[str, Any]]) -> str | None:
        for cluster in clusters:
            if node_id in cluster["members"]:
                return cluster["cluster_id"]
        return None

    def _lane_id_for_node(self, node_id: str, lanes: list[dict[str, Any]]) -> str | None:
        for lane in lanes:
            if node_id in lane["members"]:
                return lane["lane_id"]
        return None

    def _wrap_label(self, label: str, max_chars: int, max_lines: int) -> str:
        words = label.split()
        if not words:
            return label
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return "\n".join(lines[:max_lines])

    def _label(self, field: str) -> str:
        return field.replace("_", " ").title()
