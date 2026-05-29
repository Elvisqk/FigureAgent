from __future__ import annotations

import copy
from typing import Any

from figure_agent.common.constants import REPORT_DIR
from figure_agent.common.persistence import write_json
from figure_agent.common.validators import schema_for_spec, validate_payload


class FigureRepairer:
    allowed_paths = {
        "/style/legend_position",
        "/data_mapping/error_y",
        "/labels/y_label",
        "/output/formats",
        "/layout/direction",
        "/layout/mode",
        "/style/node_min_width",
        "/style/cluster_padding",
        "/style/lane_spacing",
        "/style/show_node_roles",
        "/style/feedback_margin",
        "/style/canvas_margin",
        "/label_policy/max_chars_per_line",
        "/label_policy/max_lines_per_node",
    }

    def build_patch(self, critic_report: dict[str, Any], old_spec: dict[str, Any], attempt: int) -> dict[str, Any]:
        ops = [
            op
            for op in critic_report["proposed_patch"]
            if op.get("path") in self.allowed_paths
            and op.get("op") in {"add", "replace"}
            and "value" in op
            and "reason" in op
        ]
        if critic_report["proposed_patch"] and not ops:
            raise ValueError("critic proposed patches, but none are allowed or complete")
        patch = {
            "request_id": critic_report["request_id"],
            "figure_id": critic_report["figure_id"],
            "from_attempt": attempt,
            "to_attempt": attempt + 1,
            "patch_ops": ops,
            "patch_summary": "Auto-generated repair patch from structured critic report.",
            "safety_checks": {
                "introduces_new_evidence": False,
                "changes_claim": False,
                "changes_figure_kind": False,
            },
        }
        validate_payload(patch, "repair_patch.schema.json")
        write_json(REPORT_DIR / f"{critic_report['figure_id']}_attempt_{attempt}_repair_patch.json", patch)
        return patch

    def apply_patch(self, spec: dict[str, Any], repair_patch: dict[str, Any]) -> dict[str, Any]:
        new_spec = copy.deepcopy(spec)
        for op in repair_patch["patch_ops"]:
            self._set_json_pointer(new_spec, op["path"], op["value"])
        if new_spec.get("figure_kind") == "diagram":
            if new_spec.get("layout", {}).get("direction") not in {"LR", "TB", "GRID"}:
                raise ValueError("unsupported diagram layout direction")
            if new_spec.get("layout", {}).get("mode") not in {None, "layered_lr", "layered_tb", "grid", "hub_spoke", "swimlane_lr", "swimlane_tb", "branch_merge"}:
                raise ValueError("unsupported diagram layout mode")
        validate_payload(new_spec, schema_for_spec(new_spec))
        return new_spec

    def _set_json_pointer(self, payload: dict[str, Any], pointer: str, value: Any) -> None:
        parts = [part for part in pointer.strip("/").split("/") if part]
        if not parts:
            raise ValueError("empty patch path")
        target: Any = payload
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value
