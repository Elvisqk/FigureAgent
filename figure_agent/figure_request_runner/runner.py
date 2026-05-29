from __future__ import annotations

from typing import Any

from figure_agent.figure_request_runner.caption_writer import CaptionWriter
from figure_agent.common.constants import REPORT_DIR, REQUEST_DIR, SPEC_DIR, ensure_artifact_dirs
from figure_agent.figure_request_runner.critic import FigureCritic
from figure_agent.figure_request_runner.evidence_binder import EvidenceBinder
from figure_agent.figure_request_runner.integrator import FigureIntegrator
from figure_agent.common.persistence import write_json
from figure_agent.figure_request_runner.planner import FigurePlanner
from figure_agent.figure_request_runner.repairer import FigureRepairer
from figure_agent.figure_request_runner.spec_generator import FigureSpecGenerator
from figure_agent.common.validators import validate_payload


class FigureRequestRunner:
    def __init__(
        self,
        planner: FigurePlanner | None = None,
        evidence_binder: EvidenceBinder | None = None,
        spec_generator: FigureSpecGenerator | None = None,
        caption_writer: CaptionWriter | None = None,
        critic: FigureCritic | None = None,
        repairer: FigureRepairer | None = None,
        integrator: FigureIntegrator | None = None,
    ):
        self.planner = planner or FigurePlanner()
        self.evidence_binder = evidence_binder or EvidenceBinder()
        self.spec_generator = spec_generator or FigureSpecGenerator()
        self.caption_writer = caption_writer or CaptionWriter()
        self.critic = critic or FigureCritic()
        self.repairer = repairer or FigureRepairer()
        self.integrator = integrator or FigureIntegrator()

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        ensure_artifact_dirs()
        validate_payload(request, "figure_request.schema.json")
        request_path = write_json(REQUEST_DIR / f"{request['request_id']}.json", request)

        intent = self.planner.plan(request)
        bound_intent = self.evidence_binder.bind(request, intent)
        spec = self.spec_generator.generate(request, bound_intent)

        max_attempts = request["context"]["max_revision_rounds"] + 1
        attempt = 1
        attempt_history: list[dict[str, Any]] = []
        latest_caption: dict[str, Any] | None = None
        latest_render: dict[str, Any] | None = None
        latest_critic_path: str | None = None
        latest_spec_path: str | None = None

        while attempt <= max_attempts:
            latest_spec_path = write_json(SPEC_DIR / f"{request['figure_id']}_attempt_{attempt}.json", spec)
            latest_render = self._render(request, spec, attempt)
            render_path = write_json(REPORT_DIR / f"{request['figure_id']}_attempt_{attempt}_render.json", latest_render)
            latest_caption = self.caption_writer.build(request, intent, spec, latest_render)
            caption_path = str(REPORT_DIR / f"{request['figure_id']}_attempt_{attempt}_caption.json")
            critic_report = self.critic.review(request, intent, bound_intent, spec, latest_render, latest_caption)
            latest_critic_path = str(REPORT_DIR / f"{request['figure_id']}_attempt_{attempt}_critic.json")

            history_item = {
                "attempt": attempt,
                "spec_path": latest_spec_path,
                "render_result_path": render_path,
                "caption_path": caption_path,
                "critic_report_path": latest_critic_path,
                "repair_patch_path": None,
            }
            attempt_history.append(history_item)

            if critic_report["pass"]:
                return self.integrator.build_manifest(
                    request=request,
                    spec_path=latest_spec_path,
                    render_result=latest_render,
                    caption=latest_caption,
                    critic_report_path=latest_critic_path,
                    provenance=self._provenance(request, request_path),
                    attempt_history=attempt_history,
                )

            if not critic_report["repair_decision"]["repairable"] or attempt >= max_attempts:
                return self.integrator.build_failed_manifest(
                    request=request,
                    provenance=self._provenance(request, request_path),
                    attempt_history=attempt_history,
                )

            try:
                repair_patch = self.repairer.build_patch(critic_report, spec, attempt)
                repair_patch_path = str(REPORT_DIR / f"{request['figure_id']}_attempt_{attempt}_repair_patch.json")
                history_item["repair_patch_path"] = repair_patch_path
                spec = self.repairer.apply_patch(spec, repair_patch)
            except Exception:
                return self.integrator.build_failed_manifest(
                    request=request,
                    provenance=self._provenance(request, request_path),
                    attempt_history=attempt_history,
                )
            attempt += 1

        return self.integrator.build_failed_manifest(
            request=request,
            provenance=self._provenance(request, request_path),
            attempt_history=attempt_history,
        )

    def _render(self, request: dict[str, Any], spec: dict[str, Any], attempt: int) -> dict[str, Any]:
        if spec["figure_kind"] == "chart":
            from figure_agent.rendering.tools.render_chart import render_chart

            return render_chart({
                "request_id": request["request_id"],
                "figure_id": request["figure_id"],
                "attempt": attempt,
                "chart_spec": spec,
            })
        from figure_agent.rendering.tools.render_diagram import render_diagram

        return render_diagram({
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "attempt": attempt,
            "diagram_spec": spec,
        })

    def _provenance(self, request: dict[str, Any], request_path: str) -> dict[str, Any]:
        figure_id = request["figure_id"]
        return {
            "request_path": request_path,
            "intent_path": str((REQUEST_DIR.parent / "intents" / f"{figure_id}_intent.json")),
            "bound_intent_path": str((REQUEST_DIR.parent / "intents" / f"{figure_id}_bound_intent.json")),
        }
