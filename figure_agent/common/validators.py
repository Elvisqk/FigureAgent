from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from figure_agent.common.constants import SCHEMA_DIR


@lru_cache(maxsize=32)
def load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _inline_local_refs(value: Any, seen: set[str] | None = None) -> Any:
    seen = seen or set()
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.endswith(".schema.json") and ref not in seen:
            return _inline_local_refs(load_schema(ref), seen | {ref})
        return {key: _inline_local_refs(item, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_inline_local_refs(item, seen) for item in value]
    return value


def validate_payload(payload: dict[str, Any], schema_name: str) -> None:
    schema = _inline_local_refs(load_schema(schema_name), {schema_name})
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: item.path)
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(part) for part in first.path)
        raise ValueError(f"{schema_name} validation failed at {location}: {first.message}")


def schema_for_spec(spec: dict[str, Any]) -> str:
    if spec.get("figure_kind") == "chart":
        return "chart_spec.schema.json"
    if spec.get("figure_kind") == "diagram":
        return "diagram_spec.schema.json"
    raise ValueError("unknown figure_kind in spec")
