from __future__ import annotations

from typing import Any

from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient
from figure_agent.common.validators import validate_payload
from figure_agent.request_builder.models import FigureCandidate, ResolvedCandidate, ResolvedEvidence


class EvidenceResolver:
    METRIC_HINTS = ["dataset", "method", "model", "series", "score", "score_mean", "rank", "cost", "apgr", "cpt", "cpt50_percent", "cpt80_percent", "improvement_percent"]

    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None) -> None:
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def resolve(
        self,
        context: dict[str, Any],
        candidate: FigureCandidate,
    ) -> tuple[ResolvedCandidate | None, dict[str, Any] | None]:
        resolved = self._try_llm_resolve(context, candidate)
        if resolved is not None:
            return resolved, None
        return self._rule_resolve(context, candidate)

    def _rule_resolve(
        self,
        context: dict[str, Any],
        candidate: FigureCandidate,
    ) -> tuple[ResolvedCandidate | None, dict[str, Any] | None]:
        catalog = {item["evidence_id"]: item for item in context.get("evidence_catalog", [])}
        evidence_refs: list[dict[str, Any]] = []
        missing: list[str] = []

        for evidence_id in candidate.evidence_ids:
            evidence = catalog.get(evidence_id)
            if not evidence:
                missing.append(evidence_id)
                continue
            resolved = self._resolve_one(evidence, candidate)
            evidence_refs.append(resolved.to_evidence_ref())

        if not evidence_refs:
            reason = "No resolvable evidence found"
            if missing:
                reason += f"; missing evidence ids: {', '.join(missing)}"
            return None, {
                "candidate_id": candidate.candidate_id,
                "source_id": candidate.source_id,
                "reason": reason,
                "severity": "error",
            }

        return ResolvedCandidate(candidate=candidate, evidence_refs=evidence_refs), None

    def _try_llm_resolve(self, context: dict[str, Any], candidate: FigureCandidate) -> ResolvedCandidate | None:
        try:
            catalog = {item["evidence_id"]: item for item in context.get("evidence_catalog", [])}
            payload = self.llm_client.json_completion(
                self._resolver_prompt(),
                {
                    "candidate": {
                        "candidate_id": candidate.candidate_id,
                        "source_type": candidate.source_type,
                        "source_id": candidate.source_id,
                        "figure_kind": candidate.figure_kind,
                        "target_section": candidate.target_section,
                        "goal": candidate.goal,
                        "suggested_chart_type": candidate.suggested_chart_type,
                        "suggested_diagram_type": candidate.suggested_diagram_type,
                        "evidence_ids": candidate.evidence_ids,
                        "result_summary": candidate.result_summary,
                        "method_summary": candidate.method_summary,
                    },
                    "candidate_evidence": [self._evidence_summary(catalog[evidence_id]) for evidence_id in candidate.evidence_ids if evidence_id in catalog],
                    "all_evidence": [self._evidence_summary(item) for item in context.get("evidence_catalog", [])],
                    "rules": [
                        "Return only evidence ids that appear in all_evidence.",
                        "For chart candidates, select table_file or json_file evidence and relevant columns.",
                        "For diagram candidates, select text_block or section_excerpt evidence when available.",
                        "Do not invent paths, columns, row selectors, evidence ids, or content.",
                        "Prefer the evidence ids already attached to the candidate unless another catalog item is clearly better.",
                    ],
                },
            )
            if payload is None:
                return None
            evidence_refs = self._parse_llm_evidence_refs(payload, catalog, candidate)
            if not evidence_refs:
                raise ValueError("LLM returned no usable evidence refs")
            return ResolvedCandidate(candidate=candidate, evidence_refs=evidence_refs)
        except (LLMClientError, ValueError, TypeError, KeyError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _resolver_prompt(self) -> str:
        return (
            "You are the request_builder evidence resolver for FigureAgent. "
            "Return only one JSON object with top-level key 'evidence_refs'. "
            "Each evidence_ref must contain evidence_id, kind, path, content, sheet, table_name, row_selector, column_selector, paragraph_ref, and sha256. "
            "Use null for unknown optional values. column_selector may be null or an array of existing column names. "
            "Do not include markdown, prose, or extra top-level keys."
        )

    def _evidence_summary(self, evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            "evidence_id": evidence.get("evidence_id"),
            "kind": evidence.get("kind"),
            "path": evidence.get("path"),
            "description": evidence.get("description"),
            "columns": evidence.get("columns"),
            "row_count": evidence.get("row_count"),
            "sheet": evidence.get("sheet"),
            "table_name": evidence.get("table_name"),
            "paragraph_ref": evidence.get("paragraph_ref"),
            "sha256": evidence.get("sha256"),
            "content_preview": str(evidence.get("content") or "")[:800],
        }

    def _parse_llm_evidence_refs(
        self,
        payload: dict[str, Any],
        catalog: dict[str, dict[str, Any]],
        candidate: FigureCandidate,
    ) -> list[dict[str, Any]]:
        raw_refs = payload.get("evidence_refs")
        if not isinstance(raw_refs, list):
            raise ValueError("LLM evidence resolver payload must contain evidence_refs")
        refs: list[dict[str, Any]] = []
        for item in raw_refs:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("evidence_id")
            evidence = catalog.get(evidence_id)
            if not evidence:
                continue
            resolved = self._resolve_one(evidence, candidate)
            columns = evidence.get("columns") or []
            column_selector = item.get("column_selector")
            if isinstance(column_selector, list) and columns:
                selected = [column for column in column_selector if column in columns]
                if selected:
                    resolved.column_selector = selected
            elif column_selector is None:
                resolved.column_selector = evidence.get("column_selector") or self._column_selector(evidence, candidate)
            if item.get("row_selector") is not None:
                resolved.row_selector = item.get("row_selector")
            if item.get("paragraph_ref"):
                resolved.paragraph_ref = str(item["paragraph_ref"])
            ref = resolved.to_evidence_ref()
            validate_payload(ref, "evidence_ref.schema.json")
            refs.append(ref)
        return refs

    def _resolve_one(self, evidence: dict[str, Any], candidate: FigureCandidate) -> ResolvedEvidence:
        return ResolvedEvidence(
            evidence_id=evidence["evidence_id"],
            kind=evidence["kind"],
            path=evidence.get("path"),
            content=evidence.get("content"),
            sheet=evidence.get("sheet"),
            table_name=evidence.get("table_name"),
            row_selector=evidence.get("row_selector"),
            column_selector=evidence.get("column_selector") or self._column_selector(evidence, candidate),
            paragraph_ref=evidence.get("paragraph_ref") or candidate.target_section,
            sha256=evidence.get("sha256"),
        )

    def _column_selector(self, evidence: dict[str, Any], candidate: FigureCandidate) -> list[str] | None:
        if evidence["kind"] not in {"table_file", "json_file"}:
            return None
        columns = evidence.get("columns") or []
        if not columns:
            return None
        lowered = {column.lower(): column for column in columns}
        selected: list[str] = []
        for hint in self.METRIC_HINTS:
            for key, original in lowered.items():
                if hint == key or hint in key:
                    if original not in selected:
                        selected.append(original)
        return selected or columns[: min(5, len(columns))]
