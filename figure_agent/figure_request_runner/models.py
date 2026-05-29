from __future__ import annotations

from enum import Enum


class FigureTaskStatus(str, Enum):
    RECEIVED = "received"
    PLANNING = "planning"
    SKIPPED = "skipped"
    INTENT_READY = "intent_ready"
    EVIDENCE_BOUND = "evidence_bound"
    SPEC_READY = "spec_ready"
    RENDERING = "rendering"
    RENDERED = "rendered"
    CRITIC_FAILED = "critic_failed"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"


class FigureAgentError(RuntimeError):
    """Base exception for expected FigureAgent failures."""


class UnsupportedChartType(FigureAgentError):
    pass


class UnsupportedDiagramType(FigureAgentError):
    pass


class InvalidSpec(FigureAgentError):
    pass


class InvalidDataMapping(FigureAgentError):
    pass

