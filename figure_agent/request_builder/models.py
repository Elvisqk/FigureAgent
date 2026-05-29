from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


FigureKind = Literal["chart", "diagram"]
Priority = Literal["high", "medium", "low"]
SourceType = Literal["analysis_claim", "method_summary"]


@dataclass
class BuildIssue:
    severity: Literal["warning", "error"]
    code: str
    message: str
    candidate_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "candidate_id": self.candidate_id,
        }


@dataclass
class FigureCandidate:
    candidate_id: str
    source_type: SourceType
    source_id: str
    figure_kind: FigureKind
    target_section: str
    goal: str
    priority: Priority
    suggested_chart_type: str | None = None
    suggested_diagram_type: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    result_summary: str | None = None
    method_summary: str | None = None
    rationale: str | None = None


@dataclass
class ResolvedEvidence:
    evidence_id: str
    kind: Literal["table_file", "json_file", "text_block", "section_excerpt"]
    path: str | None = None
    content: str | None = None
    sheet: str | None = None
    table_name: str | None = None
    row_selector: Any = None
    column_selector: Any = None
    paragraph_ref: str | None = None
    sha256: str | None = None

    def to_evidence_ref(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "path": self.path,
            "content": self.content,
            "sheet": self.sheet,
            "table_name": self.table_name,
            "row_selector": self.row_selector,
            "column_selector": self.column_selector,
            "paragraph_ref": self.paragraph_ref,
            "sha256": self.sha256,
        }


@dataclass
class ResolvedCandidate:
    candidate: FigureCandidate
    evidence_refs: list[dict[str, Any]]
