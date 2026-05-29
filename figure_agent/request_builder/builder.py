from __future__ import annotations

from typing import Any

from figure_agent.request_builder.context_collector import ContextCollector
from figure_agent.request_builder.evidence_resolver import EvidenceResolver
from figure_agent.request_builder.opportunity_detector import FigureOpportunityDetector
from figure_agent.request_builder.request_composer import RequestComposer
from figure_agent.request_builder.request_critic import RequestCritic
from figure_agent.request_builder.validators import validate_figure_request_bundle


class FigureRequestBuilder:
    def __init__(
        self,
        context_collector: ContextCollector | None = None,
        opportunity_detector: FigureOpportunityDetector | None = None,
        evidence_resolver: EvidenceResolver | None = None,
        request_composer: RequestComposer | None = None,
        request_critic: RequestCritic | None = None,
    ) -> None:
        self.context_collector = context_collector or ContextCollector()
        self.opportunity_detector = opportunity_detector or FigureOpportunityDetector()
        self.evidence_resolver = evidence_resolver or EvidenceResolver()
        self.request_composer = request_composer or RequestComposer()
        self.request_critic = request_critic or RequestCritic()

    def build(self, context: dict[str, Any], max_figures: int | None = None, include_low_priority: bool = False) -> dict[str, Any]:
        normalized, warnings = self.context_collector.collect(context)
        candidates = self.opportunity_detector.detect(normalized)
        if not include_low_priority:
            candidates = [candidate for candidate in candidates if candidate.priority != "low"]
        if max_figures is not None:
            candidates = candidates[:max_figures]

        requests: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        all_warnings = list(warnings)

        for candidate in candidates:
            resolved, skip = self.evidence_resolver.resolve(normalized, candidate)
            if skip:
                skipped.append(skip)
                continue
            request = self.request_composer.compose(normalized, resolved, len(requests) + 1)
            issues = self.request_critic.review(request)
            if self.request_critic.has_errors(issues):
                skipped.append({
                    "candidate_id": candidate.candidate_id,
                    "source_id": candidate.source_id,
                    "reason": "; ".join(issue["message"] for issue in issues if issue["severity"] == "error"),
                    "severity": "error",
                })
                all_warnings.extend(issue for issue in issues if issue["severity"] == "warning")
                continue
            all_warnings.extend(issues)
            requests.append(request)

        status = self._status(requests, skipped)
        bundle = {
            "paper_id": normalized["paper_id"],
            "builder_version": "v1",
            "status": status,
            "requests": requests,
            "skipped_candidates": skipped,
            "warnings": all_warnings,
        }
        validate_figure_request_bundle(bundle)
        return bundle

    def _status(self, requests: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
        if requests and skipped:
            return "partial_ready"
        if requests:
            return "ready"
        return "empty"
