from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from figure_agent.common.constants import REPORT_DIR
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.persistence import append_jsonl, write_json
from figure_agent.common.validators import validate_payload


class FigureCritic:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def review(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        bound_intent: dict[str, Any],
        spec: dict[str, Any],
        render_result: dict[str, Any],
        caption: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report = self._try_llm_review(request, intent, bound_intent, spec, render_result, caption)
        if report is None:
            report = self._rule_review(request, intent, bound_intent, spec, render_result, caption)
            self._trace(request, render_result["attempt"], "fallback", self.last_llm_error)
        else:
            self._trace(request, render_result["attempt"], "llm", None)
        report = self._normalize_report(report, render_result)
        validate_payload(report, "critic_report.schema.json")
        write_json(REPORT_DIR / f"{request['figure_id']}_attempt_{render_result['attempt']}_critic.json", report)
        return report

    def _normalize_report(self, report: dict[str, Any], render_result: dict[str, Any]) -> dict[str, Any]:
        if render_result["status"] != "success" or report.get("pass"):
            return report
        issue_groups = [
            report.get("factual_issues", []),
            report.get("semantic_issues", []),
            report.get("visual_issues", []),
            report.get("academic_issues", []),
        ]
        non_integration = any(issue_groups)
        integration_text = " ".join(str(item) for item in report.get("integration_issues", []))
        caption_only = "caption" in integration_text.lower() and not non_integration
        if caption_only and not report.get("proposed_patch"):
            report["pass"] = True
            report["severity"] = "none"
            report["integration_issues"] = []
            report["repair_decision"] = {"repairable": False, "requires_human": False, "reason": None}
        return report

    def _trace(self, request: dict[str, Any], attempt: int, source: str, error: str | None) -> None:
        append_jsonl(REPORT_DIR / f"{request['figure_id']}_llm_trace.jsonl", {
            "component": "critic",
            "attempt": attempt,
            "source": source,
            "error": error,
        })

    def _try_llm_review(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        bound_intent: dict[str, Any],
        spec: dict[str, Any],
        render_result: dict[str, Any],
        caption: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        try:
            report = self.llm_client.json_completion(
                schema_guard_prompt("critic_report.schema.json", "Review a rendered figure and propose safe spec-only repairs"),
                {
                    "figure_request": request,
                    "figure_intent": intent,
                    "bound_figure_intent": bound_intent,
                    "figure_spec": spec,
                    "render_result": render_result,
                    "caption": caption,
                    "rules": [
                        "The root object must be the CriticReport itself.",
                        "Only propose patches that do not change claim, evidence, or figure_kind.",
                        "If a render error exists, mark requires_human unless the fix is a safe spec patch.",
                        "Patch paths should be limited to style, labels, output formats, data_mapping.error_y, or layout.direction.",
                        "For diagrams with many nodes, prefer /layout/direction = GRID over toggling LR and TB.",
                        "For branch-loop diagrams, check that feedback labels have enough canvas margin and that debug role text is hidden.",
                        "proposed_patch items must use op add or replace and must include path, value, and reason.",
                        "Do not remove required uncertainty fields when the request asks for standard deviation.",
                        "Do not invent new data or conclusions.",
                    ],
                },
            )
            if report is None:
                return None
            validate_payload(report, "critic_report.schema.json")
            return report
        except (LLMClientError, ValueError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _rule_review(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        bound_intent: dict[str, Any],
        spec: dict[str, Any],
        render_result: dict[str, Any],
        caption: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issues: dict[str, list[dict[str, Any]]] = {
            "factual_issues": [],
            "semantic_issues": [],
            "visual_issues": [],
            "academic_issues": [],
            "integration_issues": [],
        }
        patch: list[dict[str, Any]] = []

        if render_result["status"] != "success":
            issues["integration_issues"].append(self._issue(
                "integration_render_failed",
                f"Render failed with {render_result.get('error', {}).get('code')}.",
                "manual",
            ))

        for output in render_result.get("output_files", []):
            if not Path(output["path"]).exists():
                issues["integration_issues"].append(self._issue("integration_output_missing", f"Output file is missing: {output['path']}", "manual"))

        if not caption or not caption.get("full_caption"):
            issues["integration_issues"].append(self._issue("integration_caption_missing", "Caption is missing.", "manual"))

        if spec["figure_kind"] == "chart":
            self._review_chart(bound_intent, spec, issues, patch)
        else:
            self._review_diagram(request, spec, issues, patch)

        if spec["figure_kind"] == "chart" and spec["style"].get("legend_position") == "top" and spec["data_mapping"].get("series"):
            # A conservative first repair case: move dense legends out of the plot area.
            patch.append({
                "op": "replace",
                "path": "/style/legend_position",
                "value": "upper_right_outside",
                "reason": "Move grouped-series legend to a less intrusive position.",
            })
            issues["visual_issues"].append(self._issue("visual_legend_position", "Grouped-series legend may reduce readability in the top position.", "spec_patch"))

        passed = all(not value for value in issues.values())
        repairable = bool(patch) and not any(issue.get("suggested_fix_type") == "manual" for group in issues.values() for issue in group)
        report = {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "attempt": render_result["attempt"],
            "pass": passed,
            "severity": "none" if passed else "major",
            **issues,
            "repair_decision": {
                "repairable": repairable,
                "requires_human": (not passed and not repairable),
                "reason": None if passed or repairable else "No safe automatic spec patch is available.",
            },
            "proposed_patch": patch if repairable else [],
        }
        return report

    def _review_chart(self, bound: dict[str, Any], spec: dict[str, Any], issues: dict[str, list[dict[str, Any]]], patch: list[dict[str, Any]]) -> None:
        trace_ids = {item["element_id"] for item in spec["traceability"]["visual_element_map"]}
        required_ids = {item["element_id"] for item in bound["visual_elements"]}
        missing = sorted(required_ids - trace_ids)
        if missing:
            issues["factual_issues"].append(self._issue("fact_traceability_missing", f"Spec traceability misses elements: {', '.join(missing)}.", "manual"))

        mapping = spec["data_mapping"]
        uncertainty = next((item for item in bound["visual_elements"] if item["element_role"] == "uncertainty"), None)
        if uncertainty and mapping.get("error_y") != uncertainty["data_slice"]["value"]:
            issues["factual_issues"].append(self._issue("fact_error_mapping_mismatch", "Uncertainty channel is not mapped to the bound evidence field.", "spec_patch"))
            patch.append({
                "op": "replace" if "error_y" in mapping else "add",
                "path": "/data_mapping/error_y",
                "value": uncertainty["data_slice"]["value"],
                "reason": "Bind error bars to the field selected during evidence binding.",
            })

    def _review_diagram(self, request: dict[str, Any], spec: dict[str, Any], issues: dict[str, list[dict[str, Any]]], patch: list[dict[str, Any]]) -> None:
        node_ids = {node["id"] for node in spec["nodes"]}
        for edge in spec["edges"]:
            if edge["source"] not in node_ids or edge["target"] not in node_ids:
                issues["factual_issues"].append(self._issue("fact_invalid_edge", "Diagram edge references an unknown node.", "manual"))
        node_count = len(spec["nodes"])
        layout_mode = spec.get("layout", {}).get("mode")
        primary_count = len(spec.get("primary_flow", []))
        has_lanes = bool(spec.get("lanes"))
        has_feedback = any(edge.get("kind") == "feedback" for edge in spec["edges"])
        has_branch_edges = any(edge.get("label") == "branch" for edge in spec["edges"])
        long_label = any(max((len(line) for line in str(node["label"]).split("\n")), default=0) > 18 for node in spec["nodes"])

        if node_count >= 7 and layout_mode in {"layered_lr", "layered_tb"}:
            issues["visual_issues"].append(self._issue("visual_layout_mode_dense", "Dense diagrams need a more compact layout mode.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/layout/mode",
                "value": "grid",
                "reason": "Use grid mode for dense diagrams to improve page integration.",
            })
            patch.append({
                "op": "replace",
                "path": "/layout/direction",
                "value": "GRID",
                "reason": "Align direction with grid layout mode.",
            })

        if node_count >= 7 and spec["style"].get("show_node_roles", True):
            issues["visual_issues"].append(self._issue("visual_debug_role_labels", "Dense paper diagrams should hide debug role labels inside nodes.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/show_node_roles",
                "value": False,
                "reason": "Hide node role labels to reduce visual clutter in the final paper figure.",
            })

        if has_feedback and spec["style"].get("feedback_margin", 0) < 64:
            issues["visual_issues"].append(self._issue("visual_feedback_margin", "Feedback loops need enough margin so labels and loop edges do not touch the canvas boundary.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/feedback_margin",
                "value": 80,
                "reason": "Increase feedback loop margin to keep loop labels away from the canvas edge.",
            })

        if (has_feedback or has_branch_edges) and spec["style"].get("canvas_margin", 0) < 56:
            issues["visual_issues"].append(self._issue("visual_canvas_margin", "Complex branch-loop diagrams need more outer margin for edge labels and loop routing.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/canvas_margin",
                "value": 64,
                "reason": "Increase outer canvas margin for branch and feedback edge readability.",
            })

        if node_count >= 5 and not has_lanes and any(node.get("cluster_id") for node in spec["nodes"]) and spec["style"].get("cluster_padding", 0) < 36:
            issues["visual_issues"].append(self._issue("visual_missing_lane_separation", "Grouped diagrams benefit from more separation between logical regions.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/cluster_padding",
                "value": 36,
                "reason": "Increase cluster padding to strengthen visual grouping.",
            })

        if has_lanes and spec["style"].get("lane_spacing", 0) < 64:
            issues["visual_issues"].append(self._issue("visual_lane_spacing", "Swimlane diagrams need larger lane spacing for readability.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/lane_spacing",
                "value": 72,
                "reason": "Increase spacing between lanes to avoid cramped layouts.",
            })

        if long_label:
            issues["visual_issues"].append(self._issue("visual_label_density", "Some diagram labels are too dense for the current wrapping policy.", "spec_patch"))
            patch.append({
                "op": "replace",
                "path": "/style/node_min_width",
                "value": 210,
                "reason": "Increase minimum node width for longer labels.",
            })
            patch.append({
                "op": "replace",
                "path": "/label_policy/max_chars_per_line",
                "value": 16,
                "reason": "Wrap labels earlier to reduce overflow and improve balance.",
            })

        if primary_count < max(2, node_count // 2):
            issues["semantic_issues"].append(self._issue("semantic_primary_flow_weak", "Primary flow coverage is too weak for a readable method diagram.", "manual"))

        request_text = " ".join([
            str(request.get("goal") or ""),
            str(request.get("target_section") or ""),
            str(request.get("context", {}).get("method_summary") or ""),
            str(request.get("evidence_refs", [{}])[0].get("content") or ""),
        ]).lower()
        asks_for_loop = bool(re.search(r"\b(loop back|feedback|retry|repeat|revise|rerender|re-run|rerun)\b", request_text))
        if asks_for_loop and not has_feedback:
            issues["semantic_issues"].append(self._issue("semantic_feedback_edge_missing", "Loop or retry semantics require an explicit feedback edge.", "manual"))

    def _issue(self, issue_id: str, message: str, suggested_fix_type: str) -> dict[str, Any]:
        return {
            "issue_id": issue_id,
            "message": message,
            "suggested_fix_type": suggested_fix_type,
        }
