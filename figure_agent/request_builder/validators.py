from __future__ import annotations

import re
from typing import Any

from figure_agent.common.validators import validate_payload


def slugify(value: str, max_length: int = 64) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        normalized = "item"
    return normalized[:max_length].strip("_") or "item"


def validate_research_context(context: dict[str, Any]) -> None:
    validate_payload(context, "research_figure_context.schema.json")


def validate_figure_request(request: dict[str, Any]) -> None:
    validate_payload(request, "figure_request.schema.json")


def validate_figure_request_bundle(bundle: dict[str, Any]) -> None:
    validate_payload(bundle, "figure_request_bundle.schema.json")
