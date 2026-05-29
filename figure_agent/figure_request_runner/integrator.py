from __future__ import annotations

from pathlib import Path
from typing import Any

from figure_agent.common.constants import MANIFEST_DIR
from figure_agent.common.persistence import write_json
from figure_agent.common.validators import validate_payload


class FigureIntegrator:
    def build_label(self, figure_id: str) -> str:
        return f"fig:{figure_id.replace('_', '-')}"

    def build_latex_snippet(self, image_path: str, caption: str, label: str) -> str:
        return (
            "\\begin{figure}[t]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.9\\linewidth]{{{image_path}}}\n"
            f"\\caption{{{caption}}}\n"
            f"\\label{{{label}}}\n"
            "\\end{figure}"
        )

    def build_manifest(
        self,
        request: dict[str, Any],
        spec_path: str,
        render_result: dict[str, Any],
        caption: dict[str, Any],
        critic_report_path: str,
        provenance: dict[str, Any],
        attempt_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        render_outputs = [item["path"] for item in render_result["output_files"]]
        primary = self._primary_render_output(render_result)
        label = self.build_label(request["figure_id"])
        manifest = {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "status": "completed",
            "final_attempt": render_result["attempt"],
            "final_spec_path": spec_path,
            "render_outputs": render_outputs,
            "caption": caption["full_caption"],
            "label": label,
            "latex": self.build_latex_snippet(primary, caption["full_caption"], label),
            "critic_report_path": critic_report_path,
            "provenance": provenance,
            "attempt_history": attempt_history,
        }
        validate_payload(manifest, "figure_asset_manifest.schema.json")
        write_json(MANIFEST_DIR / f"{request['figure_id']}_manifest.json", manifest)
        return manifest

    def build_failed_manifest(
        self,
        request: dict[str, Any],
        provenance: dict[str, Any],
        attempt_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        manifest = {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "status": "failed",
            "final_attempt": attempt_history[-1]["attempt"] if attempt_history else 0,
            "final_spec_path": attempt_history[-1]["spec_path"] if attempt_history else None,
            "render_outputs": [],
            "caption": None,
            "label": None,
            "latex": None,
            "critic_report_path": attempt_history[-1]["critic_report_path"] if attempt_history else None,
            "provenance": provenance,
            "attempt_history": attempt_history,
        }
        validate_payload(manifest, "figure_asset_manifest.schema.json")
        write_json(MANIFEST_DIR / f"{request['figure_id']}_manifest.json", manifest)
        return manifest

    def _primary_render_output(self, render_result: dict[str, Any]) -> str:
        for preferred in ("pdf", "png", "svg"):
            for item in render_result["output_files"]:
                if item["format"] == preferred:
                    return item["path"]
        return render_result["output_files"][0]["path"]

