from __future__ import annotations

from typing import Any

from figure_agent.common.constants import CHART_TYPES, DIAGRAM_TYPES
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient
from figure_agent.request_builder.models import FigureCandidate
from figure_agent.request_builder.validators import slugify


class FigureOpportunityDetector:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None) -> None:
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def detect(self, context: dict[str, Any]) -> list[FigureCandidate]:
        candidates = self._try_llm_detect(context)
        if candidates is not None:
            return candidates
        return self._rule_detect(context)

    def _rule_detect(self, context: dict[str, Any]) -> list[FigureCandidate]:
        candidates: list[FigureCandidate] = []
        for claim in context.get("analysis_claims", []):
            figure_kind = claim.get("suggested_figure_kind")
            if figure_kind not in {None, "chart"}:
                continue
            source_id = claim["claim_id"]
            candidates.append(FigureCandidate(
                candidate_id=f"cand_{slugify(source_id)}",
                source_type="analysis_claim",
                source_id=source_id,
                figure_kind="chart",
                target_section=claim["target_section"],
                goal=self._chart_goal(claim),
                priority=self._priority(claim),
                suggested_chart_type=claim.get("suggested_chart_type") or self._chart_type(claim.get("text", "")),
                evidence_ids=list(claim.get("evidence_ids", [])),
                result_summary=claim.get("text"),
                rationale="Generated from an analysis claim with chart-compatible evidence.",
            ))

        for summary in context.get("method_summaries", []):
            source_id = summary["summary_id"]
            candidates.append(FigureCandidate(
                candidate_id=f"cand_{slugify(source_id)}",
                source_type="method_summary",
                source_id=source_id,
                figure_kind="diagram",
                target_section=summary["target_section"],
                goal=self._diagram_goal(summary),
                priority="high" if summary.get("importance") == "high" else "medium",
                suggested_diagram_type=summary.get("suggested_diagram_type") or self._diagram_type(summary.get("text", "")),
                evidence_ids=list(summary.get("evidence_ids", [])),
                method_summary=summary.get("text"),
                rationale="Generated from a method summary.",
            ))

        return sorted(candidates, key=self._sort_key)

    def _try_llm_detect(self, context: dict[str, Any]) -> list[FigureCandidate] | None:
        try:
            payload = self.llm_client.json_completion(
                self._candidate_prompt(),
                {
                    "research_context": {
                        "paper_id": context.get("paper_id"),
                        "paper_title": context.get("paper_title"),
                        "target_stage": context.get("target_stage"),
                        "section_plan": context.get("section_plan", []),
                        "analysis_claims": context.get("analysis_claims", []),
                        "method_summaries": context.get("method_summaries", []),
                        "evidence_catalog": self._evidence_catalog_summary(context),
                    },
                    "allowed_chart_types": sorted(CHART_TYPES),
                    "allowed_diagram_types": sorted(DIAGRAM_TYPES),
                    "rules": [
                        "Return only candidates supported by source ids in analysis_claims or method_summaries.",
                        "Chart candidates must come from analysis_claim sources.",
                        "Diagram candidates must come from method_summary sources.",
                        "Use evidence ids from the source object whenever possible.",
                        "Prefer line charts for trends over ordered time, epoch, iteration, or size variables.",
                        "Prefer scatter charts for trade-offs and correlations.",
                        "Prefer grouped_bar for method-by-dataset comparisons.",
                        "Do not invent evidence ids, metrics, datasets, methods, or claims.",
                    ],
                },
            )
            if payload is None:
                return None
            candidates = self._parse_llm_candidates(payload, context)
            if not candidates:
                raise ValueError("LLM returned no usable figure candidates")
            return sorted(candidates, key=self._sort_key)
        except (LLMClientError, ValueError, TypeError, KeyError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _candidate_prompt(self) -> str:
        return (
            "You are the request_builder opportunity detector for FigureAgent. "
            "Return only one JSON object with a top-level 'candidates' array. "
            "Each candidate must contain candidate_id, source_type, source_id, figure_kind, target_section, goal, "
            "priority, evidence_ids, result_summary, method_summary, rationale, suggested_chart_type, and suggested_diagram_type. "
            "Allowed source_type values: analysis_claim, method_summary. "
            "Allowed figure_kind values: chart, diagram. "
            "Allowed priority values: high, medium, low. "
            "Use null for inapplicable optional fields. Do not include markdown or prose."
        )

    def _evidence_catalog_summary(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for evidence in context.get("evidence_catalog", []):
            result.append({
                "evidence_id": evidence.get("evidence_id"),
                "kind": evidence.get("kind"),
                "description": evidence.get("description"),
                "columns": evidence.get("columns"),
                "row_count": evidence.get("row_count"),
                "paragraph_ref": evidence.get("paragraph_ref"),
                "has_path": bool(evidence.get("path")),
                "content_preview": str(evidence.get("content") or "")[:500],
            })
        return result

    def _parse_llm_candidates(self, payload: dict[str, Any], context: dict[str, Any]) -> list[FigureCandidate]:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ValueError("LLM candidate payload must contain a candidates array")

        claim_by_id = {claim["claim_id"]: claim for claim in context.get("analysis_claims", [])}
        summary_by_id = {summary["summary_id"]: summary for summary in context.get("method_summaries", [])}
        evidence_ids = {item["evidence_id"] for item in context.get("evidence_catalog", [])}
        candidates: list[FigureCandidate] = []
        seen: set[str] = set()

        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            source_type = item.get("source_type")
            source_id = item.get("source_id")
            figure_kind = item.get("figure_kind")
            if source_type == "analysis_claim":
                source = claim_by_id.get(source_id)
                expected_kind = "chart"
            elif source_type == "method_summary":
                source = summary_by_id.get(source_id)
                expected_kind = "diagram"
            else:
                continue
            if not source or figure_kind != expected_kind:
                continue

            chart_type = item.get("suggested_chart_type")
            diagram_type = item.get("suggested_diagram_type")
            if figure_kind == "chart" and chart_type not in CHART_TYPES:
                chart_type = source.get("suggested_chart_type") or self._chart_type(source.get("text", ""))
            if figure_kind == "diagram" and diagram_type not in DIAGRAM_TYPES:
                diagram_type = source.get("suggested_diagram_type") or self._diagram_type(source.get("text", ""))

            candidate_id = str(item.get("candidate_id") or f"cand_{slugify(str(source_id))}")
            candidate_id = f"cand_{slugify(candidate_id.removeprefix('cand_'))}"
            if candidate_id in seen:
                continue
            seen.add(candidate_id)

            raw_evidence_ids = item.get("evidence_ids")
            if not isinstance(raw_evidence_ids, list):
                raw_evidence_ids = source.get("evidence_ids", [])
            selected_evidence = [evidence_id for evidence_id in raw_evidence_ids if evidence_id in evidence_ids]
            if not selected_evidence:
                selected_evidence = [evidence_id for evidence_id in source.get("evidence_ids", []) if evidence_id in evidence_ids]

            if item.get("goal"):
                goal = str(item["goal"])
            elif figure_kind == "chart":
                goal = self._chart_goal(source)
            else:
                goal = self._diagram_goal(source)
            target_section = str(item.get("target_section") or source.get("target_section") or "Results")
            priority = item.get("priority") if item.get("priority") in {"high", "medium", "low"} else self._priority(source)
            candidates.append(FigureCandidate(
                candidate_id=candidate_id,
                source_type=source_type,
                source_id=str(source_id),
                figure_kind=figure_kind,
                target_section=target_section,
                goal=goal,
                priority=priority,
                suggested_chart_type=chart_type if figure_kind == "chart" else None,
                suggested_diagram_type=diagram_type if figure_kind == "diagram" else None,
                evidence_ids=selected_evidence,
                result_summary=str(item.get("result_summary") or source.get("text") or "") if figure_kind == "chart" else None,
                method_summary=str(item.get("method_summary") or source.get("text") or "") if figure_kind == "diagram" else None,
                rationale=str(item.get("rationale") or "Generated by LLM opportunity detection."),
            ))
        return candidates

    def _priority(self, claim: dict[str, Any]) -> str:
        if claim.get("importance") == "high":
            return "high"
        if claim.get("evidence_ids"):
            return "medium"
        return "low"

    def _sort_key(self, candidate: FigureCandidate) -> tuple[int, str]:
        rank = {"high": 0, "medium": 1, "low": 2}[candidate.priority]
        return rank, candidate.candidate_id

    def _chart_goal(self, claim: dict[str, Any]) -> str:
        text = claim.get("text", "").strip()
        chart_type = claim.get("suggested_chart_type") or self._chart_type(text)
        if chart_type == "line":
            return f"Show the trend described by this claim: {text}"
        if chart_type == "scatter":
            return f"Show the trade-off described by this claim: {text}"
        if chart_type == "heatmap":
            return f"Visualize the ranking pattern described by this claim: {text}"
        return f"Compare the result pattern described by this claim: {text}"

    def _diagram_goal(self, summary: dict[str, Any]) -> str:
        target = summary.get("target_section", "the target section")
        return f"Summarize the method workflow for {target}."

    def _chart_type(self, text: str) -> str:
        lower = text.lower()
        if any(token in lower for token in ["trend", "trajectory", "curve", "over time", "step", "epoch", "iteration", "时间", "趋势"]):
            return "line"
        if any(token in lower for token in ["rank", "ranking", "heatmap", "排名"]):
            return "heatmap"
        if any(token in lower for token in ["tradeoff", "trade-off", "cost", "cpt", "scatter", "accuracy", "apgr"]):
            return "scatter"
        if any(token in lower for token in ["compare", "comparison", "across", "对比", "比较"]):
            return "grouped_bar"
        return "grouped_bar"

    def _diagram_type(self, text: str) -> str:
        lower = text.lower()
        if any(token in lower for token in ["decision", "threshold", "route"]):
            return "decision_flow"
        if any(token in lower for token in ["architecture", "framework", "module", "框架"]):
            return "module_architecture"
        return "pipeline"
