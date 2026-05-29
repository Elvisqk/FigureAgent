from __future__ import annotations

import re
from typing import Any

from figure_agent.common.constants import REPORT_DIR
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.persistence import append_jsonl, write_json
from figure_agent.common.validators import validate_payload


class DiagramPlanner:
    HUB_KEYWORDS = [
        "router",
        "gateway",
        "controller",
        "encoder",
        "decoder",
        "service",
        "model",
        "query processor",
        "master",
        "root server",
    ]
    STORAGE_KEYWORDS = [
        "database",
        "cache",
        "memory",
        "gfs",
        "bigtable",
        "file",
        "storage",
        "column-striped",
        "cloud",
    ]
    FRAMEWORK_KEYWORDS = [
        "framework",
        "architecture",
        "system",
        "module",
        "component",
        "serving tree",
        "overall framework",
    ]
    LOOP_KEYWORDS = [
        "loop back",
        "feedback",
        "retry",
        "repeat",
        "revise",
        "rerender",
        "re-run",
        "rerun",
    ]

    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def plan(self, request: dict[str, Any], bound_intent: dict[str, Any]) -> dict[str, Any]:
        plan = self._try_llm_plan(request, bound_intent)
        source = "llm"
        error = None
        if plan is None:
            plan = self._rule_plan(request, bound_intent)
            source = "fallback"
            error = self.last_llm_error
        validate_payload(plan, "diagram_plan.schema.json")
        self._validate_plan_semantics(plan)
        write_json(REPORT_DIR / f"{request['figure_id']}_diagram_plan.json", plan)
        append_jsonl(REPORT_DIR / f"{request['figure_id']}_llm_trace.jsonl", {
            "component": "diagram_planner",
            "source": source,
            "error": error,
        })
        return plan

    def _try_llm_plan(self, request: dict[str, Any], bound_intent: dict[str, Any]) -> dict[str, Any] | None:
        try:
            method_text = request["context"].get("method_summary") or self._inline_evidence_text(request) or request["goal"]
            plan = self.llm_client.json_completion(
                schema_guard_prompt("diagram_plan.schema.json", "Plan a readable academic diagram layout with explicit branches, merges, and feedback loops"),
                {
                    "figure_request": request,
                    "bound_figure_intent": bound_intent,
                    "method_text": method_text,
                    "rules": [
                        "The root object must be the DiagramPlan itself.",
                        "Use compact node labels and stable ids n1, n2, ... in reading order.",
                        "For parallel branches, give branch nodes group='parallel_branches' and add a cluster covering those nodes.",
                        "Represent retries or failed validations as feedback edges with kind='feedback'.",
                        "Do not invent claims, evidence, systems, metrics, or stages not present in the input.",
                        "For complex branch-loop workflows, prefer grid or swimlane_tb over a long single-row layout.",
                        "Keep primary_flow readable and include the main path from input to final output.",
                    ],
                },
            )
            if plan is None:
                return None
            validate_payload(plan, "diagram_plan.schema.json")
            self._validate_plan_semantics(plan)
            return plan
        except (LLMClientError, ValueError, TypeError, KeyError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _validate_plan_semantics(self, plan: dict[str, Any]) -> None:
        node_ids = {str(node["id"]) for node in plan["nodes"]}
        if not node_ids:
            raise ValueError("diagram plan must include nodes")
        for edge in plan["edges"]:
            if edge["source"] not in node_ids or edge["target"] not in node_ids:
                raise ValueError("diagram plan edge references an unknown node")
        for node_id in plan.get("primary_flow", []):
            if node_id not in node_ids:
                raise ValueError("diagram plan primary_flow references an unknown node")
        for cluster in plan.get("clusters", []):
            for node_id in cluster["members"]:
                if node_id not in node_ids:
                    raise ValueError("diagram plan cluster references an unknown node")
        for lane in plan.get("lanes", []):
            for node_id in lane["members"]:
                if node_id not in node_ids:
                    raise ValueError("diagram plan lane references an unknown node")

    def _rule_plan(self, request: dict[str, Any], bound_intent: dict[str, Any]) -> dict[str, Any]:
        method_text = request["context"].get("method_summary") or self._inline_evidence_text(request) or request["goal"]
        context_text = self._context_text(request, bound_intent, method_text)
        diagram_type = bound_intent["recommended_visualization"]
        framework_like = self._is_framework_like(request, bound_intent, context_text)

        nodes, segments, loop_specs = self._nodes_from_text(method_text, framework_like)
        layout_mode = self._layout_mode(diagram_type, context_text, nodes, segments, framework_like)
        primary_flow = self._primary_flow(nodes, segments, layout_mode, framework_like)
        edges = self._augment_edges(self._edges(segments), nodes, layout_mode, framework_like)
        edges = self._add_feedback_edges(edges, nodes, segments, loop_specs)
        clusters = self._clusters(nodes, layout_mode, framework_like)
        lanes = self._lanes(context_text, nodes, layout_mode)

        return {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "diagram_type": diagram_type,
            "layout_mode": layout_mode,
            "nodes": nodes,
            "edges": edges,
            "clusters": clusters,
            "lanes": lanes,
            "primary_flow": primary_flow,
            "routing_hints": {
                "prefer_orthogonal_edges": True,
                "separate_primary_and_secondary_edges": True,
            },
            "label_policy": {
                "max_chars_per_line": 18,
                "max_lines_per_node": 3,
            },
        }

    def _context_text(self, request: dict[str, Any], bound_intent: dict[str, Any], method_text: str) -> str:
        context = request.get("context", {})
        parts = [
            request.get("goal"),
            request.get("target_section"),
            method_text,
            context.get("diagram_type"),
            context.get("result_summary"),
            bound_intent.get("recommended_visualization"),
            bound_intent.get("claim"),
        ]
        return " ".join(str(part) for part in parts if part)

    def _inline_evidence_text(self, request: dict[str, Any]) -> str | None:
        for evidence in request.get("evidence_refs", []):
            content = evidence.get("content")
            if content:
                return str(content)
        return None

    def _is_framework_like(self, request: dict[str, Any], bound_intent: dict[str, Any], context_text: str) -> bool:
        context = request.get("context", {})
        lower = context_text.lower()
        if bound_intent.get("recommended_visualization") == "module_architecture":
            return True
        if context.get("diagram_type") == "module_architecture":
            return True
        return any(token in lower for token in self.FRAMEWORK_KEYWORDS)

    def _nodes_from_text(self, text: str, framework_like: bool = False) -> tuple[list[dict[str, str | None]], list[list[str]], list[dict[str, Any]]]:
        parts = self._split_steps(text)
        if len(parts) < 2:
            parts = ["Input", "Process", "Output"]

        label_segments, loop_specs = self._label_segments(parts, framework_like)
        nodes: list[dict[str, str | None]] = []
        node_segments: list[list[str]] = []
        for segment_idx, labels in enumerate(label_segments):
            if len(nodes) >= 12:
                break
            segment_ids: list[str] = []
            for label in labels:
                if len(nodes) >= 12:
                    break
                node_id = f"n{len(nodes) + 1}"
                role = self._role_for_label(label, segment_idx, len(label_segments))
                group = self._group_for_label(label)
                if len(labels) > 1 and not group:
                    group = "parallel_branches"
                nodes.append({
                    "id": node_id,
                    "label": label[:72],
                    "role": role,
                    "group": group,
                })
                segment_ids.append(node_id)
            if segment_ids:
                node_segments.append(segment_ids)
        return nodes, node_segments, loop_specs

    def _label_segments(self, parts: list[str], framework_like: bool) -> tuple[list[list[str]], list[dict[str, Any]]]:
        segments: list[list[str]] = []
        loop_specs: list[dict[str, Any]] = []
        for part in parts[:12]:
            loop_spec = self._loop_spec(part, len(segments))
            if loop_spec:
                loop_specs.append(loop_spec)
                continue
            branches = self._parallel_branches(part)
            segments.append(branches if branches else [self._clean_label(part)])
        if framework_like:
            segments = self._merge_consecutive_alternatives(segments)
        return segments, loop_specs

    def _loop_spec(self, label: str, source_segment_idx: int) -> dict[str, Any] | None:
        lower = label.lower()
        if not any(keyword in lower for keyword in self.LOOP_KEYWORDS):
            return None
        target_phrase = self._loop_target_phrase(label)
        return {
            "source_segment_idx": max(0, source_segment_idx - 1),
            "target_phrase": target_phrase,
            "label": self._loop_edge_label(label),
        }

    def _loop_target_phrase(self, label: str) -> str | None:
        patterns = [
            r"loop back to\s+(.+)$",
            r"feedback to\s+(.+)$",
            r"retry\s+(.+)$",
            r"repeat\s+(.+?)\s+until",
            r"revise(?:\s+and\s+rerender)?\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, label, flags=re.IGNORECASE)
            if match:
                phrase = self._clean_label(match.group(1))
                phrase = re.sub(r"\b(branch|stage|step|node)\b$", "", phrase, flags=re.IGNORECASE).strip()
                return phrase or None
        if "rerender" in label.lower() or "revise" in label.lower():
            return "SpecGenerator"
        return None

    def _loop_edge_label(self, label: str) -> str:
        lower = label.lower()
        if "fail" in lower or "failed" in lower:
            return "if failed"
        if "incomplete" in lower or "missing" in lower:
            return "if incomplete"
        if "until" in lower:
            return "repeat until pass"
        if "revise" in lower or "rerender" in lower:
            return "revise"
        if "retry" in lower:
            return "retry"
        return "feedback"

    def _parallel_branches(self, label: str) -> list[str]:
        lower = label.lower()
        if not re.search(r",|/|\band\b", lower):
            return []
        branch_trigger = "parallel" in lower or any(
            token in lower
            for token in ["head", "heads", "branch", "branches", "module", "modules", "component", "components", "expert", "experts"]
        )
        if not branch_trigger:
            return []

        body = re.sub(r"\bparallel\b", "", label, flags=re.IGNORECASE).strip(" .")
        suffix = self._branch_suffix(body)
        body = re.sub(r"\b(prediction|processing|routing)?\s*(heads?|branches?|modules?|components?|experts?)\b\.?$", "", body, flags=re.IGNORECASE).strip(" .")
        pieces = [part.strip(" .") for part in re.split(r",|/|\band\b", body) if part.strip(" .")]
        if len(pieces) < 2:
            return []

        branches: list[str] = []
        for piece in pieces[:4]:
            piece = self._clean_label(piece)
            if suffix and suffix not in piece.lower():
                piece = f"{piece} {suffix}"
            branches.append(piece[:72])
        return branches if len(branches) >= 2 else []

    def _branch_suffix(self, label: str) -> str | None:
        lower = label.lower()
        if "head" in lower:
            return "head"
        if "branch" in lower:
            return "branch"
        if "module" in lower:
            return "module"
        if "component" in lower:
            return "component"
        if "expert" in lower:
            return "expert"
        return None

    def _merge_consecutive_alternatives(self, segments: list[list[str]]) -> list[list[str]]:
        merged: list[list[str]] = []
        idx = 0
        while idx < len(segments):
            if idx + 1 < len(segments) and len(segments[idx]) == 1 and len(segments[idx + 1]) == 1 and self._are_alternatives(segments[idx][0], segments[idx + 1][0]):
                alternatives = [segments[idx][0], segments[idx + 1][0]]
                idx += 2
                while idx < len(segments) and len(segments[idx]) == 1 and self._are_alternatives(alternatives[-1], segments[idx][0]):
                    alternatives.append(segments[idx][0])
                    idx += 1
                merged.append(alternatives[:4])
            else:
                merged.append(segments[idx])
                idx += 1
        return merged

    def _are_alternatives(self, left: str, right: str) -> bool:
        left_lower = left.lower()
        right_lower = right.lower()
        route_tokens = ["route to", "send to", "dispatch to", "call", "select"]
        if any(token in left_lower for token in route_tokens) and any(token in right_lower for token in route_tokens):
            return True
        paired_tokens = [("weak", "strong"), ("simple", "complex"), ("fast", "accurate"), ("small", "large")]
        return any((a in left_lower and b in right_lower) or (b in left_lower and a in right_lower) for a, b in paired_tokens)

    def _split_steps(self, text: str) -> list[str]:
        if "->" in text:
            parts = [part.strip(" .") for part in text.split("->") if part.strip(" .")]
        elif "=>" in text:
            parts = [part.strip(" .") for part in text.split("=>") if part.strip(" .")]
        else:
            normalized = text.replace(" then ", "; ").replace("\n", "; ")
            parts = [part.strip(" .") for part in re.split(r";|•", normalized) if part.strip(" .")]
        return parts

    def _layout_mode(
        self,
        diagram_type: str,
        text: str,
        nodes: list[dict[str, str | None]],
        segments: list[list[str]],
        framework_like: bool,
    ) -> str:
        lower = text.lower()
        node_count = len(nodes)
        has_parallel = any(len(segment) > 1 for segment in segments)
        has_hub = self._hub_node_id(nodes) is not None
        has_storage = any(node.get("role") == "store" for node in nodes)

        if "offline" in lower and "online" in lower:
            return "swimlane_tb"
        if diagram_type == "decision_flow":
            return "layered_tb"
        if framework_like:
            if any(token in lower for token in ["frontend", "backend", "client", "api gateway"]):
                return "swimlane_tb"
            if has_hub and (node_count >= 4 or has_storage):
                return "hub_spoke"
            if has_parallel or has_storage or node_count >= 5:
                return "grid"
            return "hub_spoke" if node_count >= 3 else "grid"
        if diagram_type == "module_architecture":
            return "hub_spoke" if has_hub or node_count >= 5 else "grid"
        if any(token in lower for token in ["frontend", "backend", "database", "client", "service"]):
            return "swimlane_tb"
        return "layered_lr"

    def _primary_flow(
        self,
        nodes: list[dict[str, str | None]],
        segments: list[list[str]],
        layout_mode: str,
        framework_like: bool,
    ) -> list[str]:
        if layout_mode == "hub_spoke":
            hub_id = self._hub_node_id(nodes)
            ordered = [str(node["id"]) for node in nodes]
            if hub_id:
                return [hub_id] + [node_id for node_id in ordered if node_id != hub_id]
            return ordered

        flow = [segment[0] for segment in segments if segment]
        if framework_like and len(flow) < max(2, len(nodes) // 2):
            represented = set(flow)
            flow.extend(str(node["id"]) for node in nodes if str(node["id"]) not in represented)
        return flow

    def _edges(self, segments: list[list[str]]) -> list[dict[str, str | None]]:
        edges: list[dict[str, str | None]] = []
        for idx in range(len(segments) - 1):
            sources = segments[idx]
            targets = segments[idx + 1]
            if not sources or not targets:
                continue
            if len(sources) == 1 and len(targets) == 1:
                edges.append({"source": sources[0], "target": targets[0], "kind": "primary", "label": None})
            elif len(sources) == 1:
                for target_idx, target in enumerate(targets):
                    edges.append({
                        "source": sources[0],
                        "target": target,
                        "kind": "primary" if target_idx == 0 else "secondary",
                        "label": None if target_idx == 0 else "branch",
                    })
            elif len(targets) == 1:
                for source_idx, source in enumerate(sources):
                    edges.append({
                        "source": source,
                        "target": targets[0],
                        "kind": "primary" if source_idx == 0 else "secondary",
                        "label": None if source_idx == 0 else "merge",
                    })
            else:
                for pair_idx, (source, target) in enumerate(zip(sources, targets, strict=False)):
                    edges.append({
                        "source": source,
                        "target": target,
                        "kind": "primary" if pair_idx == 0 else "secondary",
                        "label": None,
                    })
        return edges

    def _augment_edges(
        self,
        edges: list[dict[str, str | None]],
        nodes: list[dict[str, str | None]],
        layout_mode: str,
        framework_like: bool,
    ) -> list[dict[str, str | None]]:
        augmented = list(edges)
        if layout_mode == "hub_spoke" or framework_like:
            hub_id = self._hub_node_id(nodes)
            if hub_id:
                for node in nodes:
                    node_id = str(node["id"])
                    if node_id == hub_id:
                        continue
                    if node.get("role") in {"input", "store", "output"} or node.get("group") in {"routing_core", "serving_tree", "storage"}:
                        if not self._has_edge_between(augmented, hub_id, node_id):
                            augmented.append({
                                "source": hub_id,
                                "target": node_id,
                                "kind": "secondary",
                                "label": "uses" if node.get("role") == "store" else "coordinates",
                            })

        storage_nodes = [str(node["id"]) for node in nodes if node.get("role") == "store"]
        if framework_like and storage_nodes:
            core_nodes = [
                str(node["id"])
                for node in nodes
                if node.get("group") in {"routing_core", "serving_tree", "proposal_alignment"} and node.get("role") != "store"
            ]
            for storage_id in storage_nodes:
                for core_id in core_nodes[:2]:
                    if not self._has_edge_between(augmented, core_id, storage_id):
                        augmented.append({"source": core_id, "target": storage_id, "kind": "secondary", "label": "data"})
        return self._dedupe_edges(augmented)

    def _add_feedback_edges(
        self,
        edges: list[dict[str, str | None]],
        nodes: list[dict[str, str | None]],
        segments: list[list[str]],
        loop_specs: list[dict[str, Any]],
    ) -> list[dict[str, str | None]]:
        augmented = list(edges)
        for loop_spec in loop_specs:
            source = self._feedback_source(nodes, segments, int(loop_spec["source_segment_idx"]))
            target = self._feedback_target(nodes, str(loop_spec.get("target_phrase") or ""))
            if not source or not target or source == target:
                continue
            if self._has_edge_between(augmented, source, target):
                continue
            augmented.append({
                "source": source,
                "target": target,
                "kind": "feedback",
                "label": str(loop_spec.get("label") or "feedback"),
            })
        return self._dedupe_edges(augmented)

    def _feedback_source(self, nodes: list[dict[str, str | None]], segments: list[list[str]], source_segment_idx: int) -> str | None:
        if not nodes or not segments:
            return None
        source_segment_idx = min(max(0, source_segment_idx), len(segments) - 1)
        for idx in range(source_segment_idx, -1, -1):
            for node_id in reversed(segments[idx]):
                node = self._node_by_id(nodes, node_id)
                if node and node.get("role") == "decision":
                    return node_id
        return segments[source_segment_idx][-1]

    def _feedback_target(self, nodes: list[dict[str, str | None]], target_phrase: str) -> str | None:
        if not nodes:
            return None
        lower_phrase = target_phrase.lower()
        if "parallel" in lower_phrase or "branch" in lower_phrase:
            branch_node = next((node for node in nodes if node.get("group") == "parallel_branches"), None)
            if branch_node:
                return str(branch_node["id"])

        phrase_tokens = self._label_tokens(target_phrase)
        if phrase_tokens:
            best_id: str | None = None
            best_score = 0
            for node in nodes:
                label_tokens = self._label_tokens(str(node["label"]))
                overlap = phrase_tokens & label_tokens
                if not overlap:
                    continue
                score = len(overlap) * 2
                if target_phrase.lower() in str(node["label"]).lower():
                    score += 3
                if score > best_score:
                    best_score = score
                    best_id = str(node["id"])
            if best_id:
                return best_id

        for node in reversed(nodes):
            if str(node.get("role")) in {"process", "decision"}:
                return str(node["id"])
        return str(nodes[0]["id"])

    def _node_by_id(self, nodes: list[dict[str, str | None]], node_id: str) -> dict[str, str | None] | None:
        return next((node for node in nodes if node["id"] == node_id), None)

    def _label_tokens(self, label: str) -> set[str]:
        stopwords = {"to", "the", "and", "or", "if", "is", "are", "back", "loop", "retry", "repeat", "branch", "stage", "step", "node"}
        return {
            token
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]*", label.lower())
            if len(token) >= 3 and token not in stopwords
        }

    def _dedupe_edges(self, edges: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
        seen: set[tuple[str, str, str | None]] = set()
        deduped: list[dict[str, str | None]] = []
        for edge in edges:
            key = (str(edge["source"]), str(edge["target"]), edge.get("label"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(edge)
        return deduped

    def _has_edge_between(self, edges: list[dict[str, str | None]], source: str, target: str) -> bool:
        return any(edge["source"] == source and edge["target"] == target for edge in edges)

    def _clusters(self, nodes: list[dict[str, str | None]], layout_mode: str, framework_like: bool) -> list[dict[str, Any]]:
        if layout_mode.startswith("swimlane"):
            return []
        if layout_mode not in {"hub_spoke", "grid"} and not framework_like:
            return []
        groups: dict[str, list[str]] = {}
        for node in nodes:
            group = node.get("group")
            if group:
                groups.setdefault(group, []).append(str(node["id"]))
        return [
            {"cluster_id": f"cluster_{group}", "label": group.replace("_", " ").title(), "role": "group", "members": members}
            for group, members in groups.items()
            if len(members) >= 2
        ]

    def _lanes(self, text: str, nodes: list[dict[str, str | None]], layout_mode: str) -> list[dict[str, Any]]:
        lower = text.lower()
        if layout_mode.startswith("swimlane") and "offline" in lower and "online" in lower:
            offline = [str(node["id"]) for node in nodes if self._is_offline_label(str(node["label"]))]
            offline_set = set(offline)
            online = [str(node["id"]) for node in nodes if str(node["id"]) not in offline_set]
            lanes: list[dict[str, Any]] = []
            if offline:
                lanes.append({"lane_id": "lane_offline", "label": "Offline", "role": "swimlane", "members": offline})
            if online:
                lanes.append({"lane_id": "lane_online", "label": "Online", "role": "swimlane", "members": online})
            return lanes
        if layout_mode.startswith("swimlane") and any(token in lower for token in ["frontend", "backend", "database", "client", "service"]):
            external = [str(node["id"]) for node in nodes if self._is_external_label(str(node["label"]))]
            storage = [str(node["id"]) for node in nodes if node.get("role") == "store"]
            assigned = set(external) | set(storage)
            core = [str(node["id"]) for node in nodes if str(node["id"]) not in assigned]
            lanes = []
            if external:
                lanes.append({"lane_id": "lane_external", "label": "External", "role": "swimlane", "members": external})
            if core:
                lanes.append({"lane_id": "lane_core", "label": "Core System", "role": "swimlane", "members": core})
            if storage:
                lanes.append({"lane_id": "lane_storage", "label": "Storage", "role": "swimlane", "members": storage})
            return lanes
        if layout_mode.startswith("swimlane"):
            midpoint = max(1, len(nodes) // 2)
            return [
                {"lane_id": "lane_stage_a", "label": "Stage A", "role": "swimlane", "members": [str(node["id"]) for node in nodes[:midpoint]]},
                {"lane_id": "lane_stage_b", "label": "Stage B", "role": "swimlane", "members": [str(node["id"]) for node in nodes[midpoint:]]},
            ]
        return []

    def _hub_node_id(self, nodes: list[dict[str, str | None]]) -> str | None:
        best_id: str | None = None
        best_score = 0
        for node in nodes:
            label = str(node["label"]).lower()
            score = 0
            for keyword in self.HUB_KEYWORDS:
                if keyword in label:
                    score += 3 if keyword in {"router", "root server", "gateway", "controller", "query processor"} else 2
            if "decision" in label or "threshold" in label:
                score += 2
            if node.get("role") == "decision":
                score += 1
            if score > best_score:
                best_score = score
                best_id = str(node["id"])
        return best_id

    def _role_for_label(self, label: str, idx: int, count: int) -> str:
        lower = label.lower()
        if any(token in lower for token in self.STORAGE_KEYWORDS):
            return "store"
        if any(token in lower for token in ["decision", "route", "threshold", "if "]):
            return "decision"
        if idx == 0 or any(token in lower for token in ["api", "client", "user", "query", "input", "nested records"]):
            return "input"
        if idx == count - 1 or any(token in lower for token in ["result", "response", "output", "answer"]):
            return "output"
        return "process"

    def _group_for_label(self, label: str) -> str | None:
        lower = label.lower()
        if any(token in lower for token in ["train", "label", "data construction", "preference", "annotation"]):
            return "training"
        if any(token in lower for token in ["backbone", "feature pyramid", "convolutional", "fpn"]):
            return "feature_extraction"
        if any(token in lower for token in ["region proposal", "rpn", "roialign", "roi align"]):
            return "proposal_alignment"
        if any(token in lower for token in ["classification", "bounding-box", "bbox", "mask", "head"]):
            return "prediction_heads"
        if any(token in lower for token in ["leaf server", "intermediate server", "root server", "serving tree"]):
            return "serving_tree"
        if any(token in lower for token in self.STORAGE_KEYWORDS):
            return "storage"
        if any(token in lower for token in ["router", "gateway", "service", "model", "encoder", "decoder", "threshold", "probability", "decision"]):
            return "routing_core"
        if any(token in lower for token in ["response", "output", "result", "answer"]):
            return "output"
        return None

    def _is_offline_label(self, label: str) -> bool:
        lower = label.lower()
        return any(token in lower for token in ["train", "data construction", "preference", "label", "annotation", "calibration", "dataset"])

    def _is_external_label(self, label: str) -> bool:
        lower = label.lower()
        return any(token in lower for token in ["user", "client", "frontend", "query", "request"])

    def _clean_label(self, label: str) -> str:
        return re.sub(r"\s+", " ", label.strip(" ."))
