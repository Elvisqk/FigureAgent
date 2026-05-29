from __future__ import annotations

from typing import Any

from figure_agent.request_builder.chart_inference import ChartStructureInferer
from figure_agent.request_builder.models import ResolvedCandidate
from figure_agent.request_builder.validators import slugify


class RequestComposer:
    def __init__(self, chart_inferer: ChartStructureInferer | None = None) -> None:
        self.chart_inferer = chart_inferer or ChartStructureInferer()

    def compose(self, context: dict[str, Any], resolved: ResolvedCandidate, index: int) -> dict[str, Any]:
        candidate = resolved.candidate
        evidence = resolved.evidence_refs[0] if resolved.evidence_refs else None
        chart_inference = self.chart_inferer.infer(evidence, candidate.suggested_chart_type, candidate.goal) if candidate.figure_kind == "chart" else None
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
        self._copy_figure_text(context, request["context"])
        if candidate.figure_kind == "chart":
            request["context"]["chart_type"] = chart_inference.chart_type if chart_inference else candidate.suggested_chart_type or "grouped_bar"
            if chart_inference:
                request["context"]["data_mapping"] = chart_inference.data_mapping
                request["context"]["builder_hints"] = {
                    "chart_inference": chart_inference.reason,
                }
        else:
            request["context"]["diagram_type"] = candidate.suggested_diagram_type or "pipeline"
            diagram_structure = self._diagram_structure(candidate)
            if diagram_structure:
                request["context"]["diagram_structure"] = diagram_structure
        return request

    def _figure_id(self, candidate) -> str:
        section = slugify(candidate.target_section, max_length=48)
        source = slugify(candidate.source_id, max_length=48)
        return f"fig_{section}_{source}"

    def _copy_figure_text(self, source: dict[str, Any], target: dict[str, Any]) -> None:
        for key in ["figure_title", "figure_subtitle", "figure_notes", "figure_footer"]:
            if source.get(key) is not None:
                target[key] = source[key]

    def _diagram_structure(self, candidate) -> dict[str, Any] | None:
        text = candidate.method_summary or ""
        parts = self._split_steps(text)
        if len(parts) < 2:
            return None
        lower_text = text.lower()
        has_feedback = any(token in lower_text for token in ["feedback", "retry", "revise", "rerun", "loop back", "if failed"])
        has_parallel_signal = any(token in lower_text for token in ["parallel", "branch", "fan out", "merge"])
        has_lane_signal = "offline" in lower_text and "online" in lower_text
        if not (has_feedback or has_parallel_signal or has_lane_signal):
            return None
        feedback_label = None
        if parts and self._is_feedback_step(parts[-1]):
            feedback_label = self._feedback_label(parts.pop())
        if len(parts) < 2:
            return None
        node_count = min(len(parts), 10)
        nodes = []
        for idx, label in enumerate(parts[:node_count], start=1):
            lower = label.lower()
            role = "input" if idx == 1 else "output" if idx == node_count else "decision" if any(token in lower for token in ["gate", "decision", "check", "if ", "whether", "threshold"]) else "process"
            group = "parallel_branches" if any(token in lower for token in ["parallel", "branch", "retrieval", "profiling", "analysis"]) and idx not in {1, node_count} else None
            nodes.append({"id": f"n{idx}", "label": label[:72], "role": role, "group": group})

        branch_members = [node["id"] for node in nodes if node.get("group") == "parallel_branches"]
        primary_flow = [node["id"] for node in nodes]
        if len(branch_members) >= 2 and node_count >= 4:
            branch_indices = [int(node_id[1:]) for node_id in branch_members]
            first_branch = min(branch_indices)
            last_branch = max(branch_indices)
            branch_source = f"n{max(1, first_branch - 1)}"
            merge_target = f"n{min(node_count, last_branch + 1)}"
            edges = [{"source": f"n{idx}", "target": f"n{idx + 1}", "kind": "primary", "label": None} for idx in range(1, max(1, first_branch - 1))]
            for idx, member in enumerate(branch_members):
                edges.append({"source": branch_source, "target": member, "kind": "primary" if idx == 0 else "secondary", "label": "branch"})
                edges.append({"source": member, "target": merge_target, "kind": "primary" if idx == 0 else "secondary", "label": "merge"})
            for idx in range(last_branch + 1, node_count):
                edges.append({"source": f"n{idx}", "target": f"n{idx + 1}", "kind": "primary", "label": None})
            primary_flow = [node["id"] for node in nodes[: first_branch - 1]]
            primary_flow.append(branch_members[0])
            primary_flow.extend(node["id"] for node in nodes[last_branch:])
        else:
            edges = [{"source": f"n{idx}", "target": f"n{idx + 1}", "kind": "primary", "label": None} for idx in range(1, node_count)]
        if has_feedback and node_count >= 4:
            feedback_source = self._feedback_source(nodes)
            edges.append({"source": feedback_source, "target": "n2", "kind": "feedback", "label": feedback_label or "revise"})
        clusters = []
        if len(branch_members) >= 2:
            clusters.append({"cluster_id": "cluster_parallel_branches", "label": "Parallel Branches", "role": "group", "members": branch_members})
        lanes = self._lanes(nodes, lower_text) if has_lane_signal else []
        return {
            "layout_mode": "swimlane_tb" if lanes else "branch_merge" if clusters or has_feedback else "layered_lr",
            "nodes": nodes,
            "edges": edges,
            "clusters": clusters,
            "lanes": lanes,
            "primary_flow": list(dict.fromkeys(primary_flow)),
            "routing_hints": {
                "prefer_orthogonal_edges": True,
                "separate_primary_and_secondary_edges": True,
            },
            "label_policy": {
                "max_chars_per_line": 16,
                "max_lines_per_node": 3,
            },
        }

    def _lanes(self, nodes: list[dict[str, Any]], lower_text: str) -> list[dict[str, Any]]:
        if "offline" not in lower_text or "online" not in lower_text:
            return []
        midpoint = max(1, len(nodes) // 2)
        return [
            {"lane_id": "lane_offline", "label": "Offline", "role": "swimlane", "members": [node["id"] for node in nodes[:midpoint]]},
            {"lane_id": "lane_online", "label": "Online", "role": "swimlane", "members": [node["id"] for node in nodes[midpoint:]]},
        ]

    def _split_steps(self, text: str) -> list[str]:
        normalized = text.replace("=>", "->").replace("\n", " -> ")
        if "->" in normalized:
            return [part.strip(" .") for part in normalized.split("->") if part.strip(" .")]
        for separator in [";", "."]:
            if separator in normalized:
                parts = [part.strip(" .") for part in normalized.split(separator) if part.strip(" .")]
                if len(parts) >= 2:
                    return parts
        return []

    def _is_feedback_step(self, text: str) -> bool:
        lower = text.lower()
        return any(token in lower for token in ["feedback", "retry", "revise", "rerun", "loop back", "if failed"])

    def _feedback_label(self, text: str) -> str:
        lower = text.lower()
        if "retry" in lower:
            return "retry"
        if "revise" in lower:
            return "revise"
        if "failed" in lower:
            return "if failed"
        return "feedback"

    def _feedback_source(self, nodes: list[dict[str, Any]]) -> str:
        for node in reversed(nodes):
            if node["role"] == "decision":
                return node["id"]
        return nodes[-1]["id"]
