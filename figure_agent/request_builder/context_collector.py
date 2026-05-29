from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any

from figure_agent.request_builder.validators import validate_research_context


class ContextCollector:
    def collect(self, context: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        normalized = deepcopy(context)
        normalized.setdefault("target_stage", "experiment_analysis")
        normalized.setdefault("section_plan", [])
        normalized.setdefault("analysis_claims", [])
        normalized.setdefault("method_summaries", [])
        normalized.setdefault("evidence_catalog", [])
        normalized.setdefault("style_profile", "academic_default")
        normalized.setdefault("output_formats", ["png", "pdf"])
        normalized.setdefault("max_revision_rounds", 2)

        validate_research_context(normalized)
        warnings = self._enrich_evidence_catalog(normalized)
        return normalized, warnings

    def _enrich_evidence_catalog(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for evidence in context["evidence_catalog"]:
            if evidence.get("sha256") is None and evidence.get("path"):
                evidence["sha256"] = self._sha256(evidence["path"])
            if evidence["kind"] == "table_file" and evidence.get("path"):
                fields, row_count = self._inspect_csv(evidence["path"])
                if fields:
                    evidence.setdefault("columns", fields)
                if row_count is not None:
                    evidence.setdefault("row_count", row_count)
                if not fields:
                    warnings.append({
                        "severity": "warning",
                        "code": "table_not_inspected",
                        "message": f"Table evidence {evidence['evidence_id']} could not be inspected locally.",
                        "candidate_id": None,
                    })
        return warnings

    def _inspect_csv(self, path_text: str) -> tuple[list[str], int | None]:
        path = Path(path_text)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or path.suffix.lower() != ".csv":
            return [], None
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            row_count = sum(1 for _ in reader)
        return fields, row_count

    def _sha256(self, path_text: str) -> str | None:
        path = Path(path_text)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
