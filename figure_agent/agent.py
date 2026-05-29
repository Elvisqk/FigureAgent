from __future__ import annotations

from typing import Any

from figure_agent.common.constants import ensure_artifact_dirs
from figure_agent.common.validators import validate_payload
from figure_agent.figure_request_runner import FigureRequestRunner
from figure_agent.request_builder import FigureRequestBuilder


class FigureAgent:
    """End-to-end context -> figure asset workflow."""

    def __init__(
        self,
        request_builder: FigureRequestBuilder | None = None,
        request_runner: FigureRequestRunner | None = None,
    ) -> None:
        self.request_builder = request_builder or FigureRequestBuilder()
        self.request_runner = request_runner or FigureRequestRunner()

    def build(
        self,
        context: dict[str, Any],
        *,
        max_figures: int | None = None,
        include_low_priority: bool = False,
    ) -> dict[str, Any]:
        ensure_artifact_dirs()
        bundle = self.request_builder.build(
            context,
            max_figures=max_figures,
            include_low_priority=include_low_priority,
        )
        manifests = []
        for request in bundle["requests"]:
            manifests.append(self.request_runner.run(request))
        result = {
            "paper_id": bundle["paper_id"],
            "status": self._status(bundle, manifests),
            "request_bundle": bundle,
            "manifests": manifests,
        }
        validate_payload(bundle, "figure_request_bundle.schema.json")
        return result

    def _status(self, bundle: dict[str, Any], manifests: list[dict[str, Any]]) -> str:
        if not bundle["requests"]:
            return "empty"
        completed = [manifest for manifest in manifests if manifest["status"] == "completed"]
        if len(completed) == len(bundle["requests"]) and not bundle["skipped_candidates"]:
            return "completed"
        if completed:
            return "partial_completed"
        return "failed"
