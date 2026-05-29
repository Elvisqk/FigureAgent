from __future__ import annotations

__all__ = ["FigureAgent"]


def __getattr__(name: str):
    if name == "FigureAgent":
        from figure_agent.agent import FigureAgent

        return FigureAgent
    raise AttributeError(f"module 'figure_agent' has no attribute {name!r}")
