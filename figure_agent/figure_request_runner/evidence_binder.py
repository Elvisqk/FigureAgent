from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from figure_agent.common.constants import INTENT_DIR, REPORT_DIR
from figure_agent.common.llm_client import LLMClientError, OpenAICompatibleLLMClient, schema_guard_prompt
from figure_agent.common.persistence import append_jsonl, write_json
from figure_agent.common.validators import validate_payload


class EvidenceBinder:
    def __init__(self, llm_client: OpenAICompatibleLLMClient | None = None):
        self.llm_client = llm_client or OpenAICompatibleLLMClient()
        self.last_llm_error: str | None = None

    def bind(self, request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        bound = self._try_llm_bind(request, intent)
        if bound is None:
            bound = self._rule_bind(request, intent)
            self._trace(request, "fallback", self.last_llm_error)
        else:
            self._trace(request, "llm", None)
        validate_payload(bound, "bound_figure_intent.schema.json")
        write_json(INTENT_DIR / f"{request['figure_id']}_bound_intent.json", bound)
        return bound

    def _trace(self, request: dict[str, Any], source: str, error: str | None) -> None:
        append_jsonl(REPORT_DIR / f"{request['figure_id']}_llm_trace.jsonl", {
            "component": "evidence_binder",
            "source": source,
            "error": error,
        })

    def _try_llm_bind(self, request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any] | None:
        try:
            evidence_summary = [self._summarize_evidence(item) for item in request["evidence_refs"]]
            bound = self.llm_client.json_completion(
                schema_guard_prompt("bound_figure_intent.schema.json", "Bind a FigureIntent to concrete evidence fields and allowed transformations"),
                {
                    "figure_request": request,
                    "figure_intent": intent,
                    "evidence_summary": evidence_summary,
                    "rules": [
                        "The root object must be the BoundFigureIntent itself.",
                        "Every visual_element must have at least one backing_evidence_id from the request.",
                        "Use only fields that appear in evidence_summary.fields.",
                        "Do not invent new evidence, metrics, nodes, or claims.",
                        "Use identity transformations unless a concrete transformation is explicitly justified by the input.",
                    ],
                },
            )
            if bound is None:
                return None
            bound = self._normalize_bound_intent(bound, request, intent)
            validate_payload(bound, "bound_figure_intent.schema.json")
            self._validate_bound_semantics(bound)
            return bound
        except (LLMClientError, ValueError, FileNotFoundError) as exc:
            self.last_llm_error = str(exc)
            return None

    def _rule_bind(self, request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        if intent["figure_kind"] == "chart":
            return self._bind_chart(request, intent)
        return self._bind_diagram(request, intent)

    def _bind_chart(self, request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        evidence = request["evidence_refs"][0]
        fields, row_count, digest = self._inspect_table(evidence)
        mapping = self._request_data_mapping(request, fields, intent["recommended_visualization"])
        x = mapping["x"]
        if intent["recommended_visualization"] == "heatmap":
            series = mapping.get("y") or mapping.get("series")
            y = mapping.get("value") or fields[-1]
        else:
            series = mapping.get("series")
            y = mapping.get("y") or mapping.get("value") or fields[-1]
        error_y = mapping.get("error_y")

        visual_elements = [
            {
                "element_id": "primary_values",
                "element_role": "primary_metric",
                "backing_evidence_ids": [evidence["evidence_id"]],
                "data_slice": {"x": x, "series": series, "value": y},
                "allowed_transformations": ["identity"],
            }
        ]
        must_show = ["primary metric"]
        if series:
            must_show.append("series grouping")
        if error_y:
            visual_elements.append({
                "element_id": "uncertainty",
                "element_role": "uncertainty",
                "backing_evidence_ids": [evidence["evidence_id"]],
                "data_slice": {"value": error_y},
                "allowed_transformations": ["identity"],
            })
            must_show.append("uncertainty")

        return self._base_bound(request, intent, visual_elements, must_show, [{
            "evidence_id": evidence["evidence_id"],
            "source_kind": evidence["kind"],
            "source_path": evidence.get("path"),
            "sha256": digest,
            "selected_fields": [field for field in [x, series, y, error_y] if field],
            "row_count": row_count,
            "transformations": ["identity"],
        }])

    def _bind_diagram(self, request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        evidence = request["evidence_refs"][0]
        digest = self._sha256(evidence.get("path")) if evidence.get("path") else None
        visual_elements = [{
            "element_id": "diagram_structure",
            "element_role": "method_structure",
            "backing_evidence_ids": [evidence["evidence_id"]],
            "data_slice": {"source": evidence.get("path") or "inline_text"},
            "allowed_transformations": ["text_to_graph"],
        }]
        return self._base_bound(request, intent, visual_elements, ["key nodes", "key edges"], [{
            "evidence_id": evidence["evidence_id"],
            "source_kind": evidence["kind"],
            "source_path": evidence.get("path"),
            "sha256": digest,
            "selected_fields": [],
            "row_count": None,
            "transformations": ["text_to_graph"],
        }])

    def _base_bound(
        self,
        request: dict[str, Any],
        intent: dict[str, Any],
        visual_elements: list[dict[str, Any]],
        must_show: list[str],
        evidence_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "request_id": request["request_id"],
            "figure_id": request["figure_id"],
            "claim": intent["claim"],
            "figure_kind": intent["figure_kind"],
            "recommended_visualization": intent["recommended_visualization"],
            "target_section": intent["target_section"],
            "visual_elements": visual_elements,
            "must_show": must_show,
            "must_not_do": ["do not invent missing data", "do not change the claim"],
            "evidence_bindings": evidence_bindings,
        }

    def _inspect_table(self, evidence: dict[str, Any]) -> tuple[list[str], int, str | None]:
        path = Path(evidence["path"])
        if not path.is_absolute():
            path = Path.cwd() / path
        digest = self._sha256(str(path))
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            row_count = sum(1 for _ in reader)
        if not fields:
            raise ValueError("table evidence has no header fields")
        return fields, row_count, digest

    def _summarize_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        if evidence["kind"] in {"table_file", "json_file"} and evidence.get("path"):
            fields, row_count, digest = self._inspect_table(evidence)
            return {
                "evidence_id": evidence["evidence_id"],
                "kind": evidence["kind"],
                "path": evidence.get("path"),
                "fields": fields,
                "row_count": row_count,
                "sha256": digest,
            }
        return {
            "evidence_id": evidence["evidence_id"],
            "kind": evidence["kind"],
            "path": evidence.get("path"),
            "fields": [],
            "row_count": None,
            "sha256": self._sha256(evidence.get("path")) if evidence.get("path") else None,
            "content_preview": (evidence.get("content") or "")[:1200],
        }

    def _sha256(self, path_text: str | None) -> str | None:
        if not path_text:
            return None
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

    def _first_existing(self, fields: list[str], candidates: list[str], fallback: str | None) -> str | None:
        lower = {field.lower(): field for field in fields}
        for candidate in candidates:
            if candidate in lower:
                return lower[candidate]
        return fallback

    def _normalize_bound_intent(self, bound: dict[str, Any], request: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        if intent["figure_kind"] != "chart":
            return bound
        evidence = request["evidence_refs"][0]
        fields, _, _ = self._inspect_table(evidence)
        mapping = self._request_data_mapping(request, fields, intent["recommended_visualization"])
        x = mapping["x"]
        if intent["recommended_visualization"] == "heatmap":
            series = mapping.get("y") or mapping.get("series")
            y = mapping.get("value") or fields[-1]
        else:
            series = mapping.get("series")
            y = mapping.get("y") or mapping.get("value") or fields[-1]
        error_y = mapping.get("error_y")

        has_primary = False
        has_uncertainty = False
        normalized = []
        for item in bound.get("visual_elements", []):
            role_text = str(item.get("element_role", "")).lower()
            element_id = str(item.get("element_id", ""))
            if not has_primary and ("primary" in role_text or "bar" in role_text or "mean" in role_text or "score" in role_text):
                item["element_role"] = "primary_metric"
                item["data_slice"] = {"x": x, "series": series, "value": y}
                has_primary = True
            elif not has_uncertainty and ("uncertainty" in role_text or "standard deviation" in role_text or "std" in role_text or "error" in role_text or "error" in element_id):
                item["element_role"] = "uncertainty"
                item["data_slice"] = {"value": error_y}
                has_uncertainty = True
            normalized.append(item)

        if not has_primary:
            normalized.insert(0, {
                "element_id": "primary_values",
                "element_role": "primary_metric",
                "backing_evidence_ids": [evidence["evidence_id"]],
                "data_slice": {"x": x, "series": series, "value": y},
                "allowed_transformations": ["identity"],
            })
        if error_y and not has_uncertainty:
            normalized.append({
                "element_id": "uncertainty",
                "element_role": "uncertainty",
                "backing_evidence_ids": [evidence["evidence_id"]],
                "data_slice": {"value": error_y},
                "allowed_transformations": ["identity"],
            })
        bound["visual_elements"] = normalized
        return bound

    def _validate_bound_semantics(self, bound: dict[str, Any]) -> None:
        if bound["figure_kind"] == "chart":
            primary = next((item for item in bound["visual_elements"] if item["element_role"] == "primary_metric"), None)
            if not primary:
                raise ValueError("chart BoundFigureIntent requires a primary_metric visual element")
            data_slice = primary.get("data_slice", {})
            for key in ["x", "value"]:
                if not data_slice.get(key):
                    raise ValueError(f"primary_metric requires data_slice.{key}")

    def _request_data_mapping(self, request: dict[str, Any], fields: list[str], visualization: str) -> dict[str, str]:
        requested = request.get("context", {}).get("data_mapping")
        if isinstance(requested, dict):
            mapping = {str(key): str(value) for key, value in requested.items() if isinstance(value, str) and value in fields}
            if mapping.get("x") and (mapping.get("y") or mapping.get("value")):
                return mapping
        if visualization == "scatter":
            x = self._first_existing(fields, ["x", "cpt50_percent", "cost", "strong_call_percent"], fields[0])
        else:
            x = self._first_existing(fields, ["dataset", "x", "step", "condition", "category"], fields[0])
        series = self._first_existing(fields, ["method", "series", "model", "group"], None)
        y = self._first_existing(fields, ["score_mean", "mean", "score", "accuracy", "value"], fields[-1])
        error_y = self._first_existing(fields, ["score_std", "std", "stderr", "error", "ci"], None)
        mapping = {"x": x, "y": y}
        if series:
            mapping["series"] = series
        if error_y:
            mapping["error_y"] = error_y
        return mapping
