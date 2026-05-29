from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from figure_agent.common.constants import ARTIFACT_ROOT

ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(ARTIFACT_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ARTIFACT_ROOT / "cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from figure_agent.common.constants import FIGURE_DIR, TOL_MUTED
from figure_agent.figure_request_runner.models import InvalidDataMapping, UnsupportedChartType


class MatplotlibChartRenderer:
    renderer_name = "chart_matplotlib"
    encoding_keys = {"x", "y", "value", "series", "error_y"}

    def render(self, request_id: str, figure_id: str, attempt: int, spec: dict[str, Any]) -> dict[str, Any]:
        try:
            rows = self._load_rows(spec["data_ref"])
            rows = self._apply_derived_fields(rows, spec)
            self._validate_mapping(rows, spec["data_mapping"])
            fig, ax = self._build_canvas(spec)
            chart_type = spec["chart_type"]
            if chart_type == "line":
                self._render_line(ax, rows, spec)
            elif chart_type == "bar":
                self._render_bar(ax, rows, spec)
            elif chart_type == "grouped_bar":
                self._render_grouped_bar(ax, rows, spec)
            elif chart_type == "scatter":
                self._render_scatter(ax, rows, spec)
            elif chart_type == "heatmap":
                self._render_heatmap(ax, rows, spec)
            else:
                raise UnsupportedChartType(chart_type)

            self._apply_labels(ax, spec)
            output_files = self._save_outputs(fig, spec["output"], attempt)
            width, height = fig.get_size_inches()
            dpi = int(spec["style"]["dpi"])
            plt.close(fig)
            return {
                "request_id": request_id,
                "figure_id": figure_id,
                "attempt": attempt,
                "status": "success",
                "renderer": self.renderer_name,
                "output_files": output_files,
                "metadata": {
                    "width_px": int(width * dpi),
                    "height_px": int(height * dpi),
                    "dpi": dpi,
                    "renderer_version": matplotlib.__version__,
                },
                "logs": [],
                "error": None,
            }
        except FileNotFoundError as exc:
            return self._error(request_id, figure_id, attempt, "DATA_NOT_FOUND", "data file not found", {"path": str(exc)})
        except UnsupportedChartType as exc:
            return self._error(request_id, figure_id, attempt, "UNSUPPORTED_CHART_TYPE", str(exc), {})
        except InvalidDataMapping as exc:
            return self._error(request_id, figure_id, attempt, "INVALID_DATA_MAPPING", str(exc), {})
        except Exception as exc:
            return self._error(request_id, figure_id, attempt, "RENDER_FAILED", str(exc), {})

    def _load_rows(self, data_ref: dict[str, str]) -> list[dict[str, Any]]:
        path = Path(data_ref["path"])
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(path)

        if data_ref["format"] == "csv":
            with path.open("r", encoding="utf-8", newline="") as handle:
                return [self._coerce_row(row) for row in csv.DictReader(handle)]
        if data_ref["format"] == "json":
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                return [self._coerce_row(row) for row in payload]
            raise InvalidDataMapping("json data must be a list of records")
        raise InvalidDataMapping(f"unsupported data format: {data_ref['format']}")

    def _coerce_row(self, row: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (int, float)) or value is None:
                result[key] = value
                continue
            text = str(value).strip()
            try:
                result[key] = float(text)
            except ValueError:
                result[key] = text
        return result

    def _validate_mapping(self, rows: list[dict[str, Any]], mapping: dict[str, str]) -> None:
        if not rows:
            raise InvalidDataMapping("data is empty")
        fields = set(rows[0].keys())
        mapped_fields = {
            field
            for key, field in mapping.items()
            if key in self.encoding_keys and isinstance(field, str)
        }
        missing = sorted(mapped_fields - fields)
        if missing:
            raise InvalidDataMapping(f"missing mapped fields: {', '.join(missing)}")

    def _apply_derived_fields(self, rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
        mapping = spec.get("data_mapping", {})
        value_field = mapping.get("value")
        source_metric = mapping.get("source_metric")
        if value_field == "rank_within_dataset_by_score_mean_descending" and source_metric:
            return self._derive_rank(rows, group_field=mapping.get("x"), rank_field=value_field, metric_field=source_metric)
        return rows

    def _derive_rank(self, rows: list[dict[str, Any]], group_field: str | None, rank_field: str, metric_field: str) -> list[dict[str, Any]]:
        if not group_field:
            raise InvalidDataMapping("rank derivation requires data_mapping.x as group field")
        if not rows or group_field not in rows[0] or metric_field not in rows[0]:
            raise InvalidDataMapping(f"rank derivation missing fields: {group_field}, {metric_field}")
        result = [dict(row) for row in rows]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in result:
            grouped[str(row[group_field])].append(row)
        for group in grouped.values():
            group.sort(key=lambda row: float(row[metric_field]), reverse=True)
            for idx, row in enumerate(group, start=1):
                row[rank_field] = idx
        return result

    def _build_canvas(self, spec: dict[str, Any]):
        scale = float(spec["style"].get("font_scale", 1.0))
        dpi = int(spec["style"].get("dpi", 300))
        plt.rcParams.update({
            "font.size": 9 * scale,
            "axes.titlesize": 10 * scale,
            "axes.labelsize": 9 * scale,
            "legend.fontsize": 8 * scale,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        })
        fig, ax = plt.subplots(figsize=(6.8, 4.2), dpi=dpi)
        if spec.get("title"):
            ax.set_title(spec["title"])
        return fig, ax

    def _render_line(self, ax, rows: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        mapping = spec["data_mapping"]
        x_field, y_field = mapping["x"], mapping["y"]
        series_field = mapping.get("series")
        grouped = self._group_rows(rows, series_field)
        for idx, (series, group) in enumerate(grouped.items()):
            group = sorted(group, key=lambda row: row[x_field])
            ax.plot([row[x_field] for row in group], [row[y_field] for row in group], marker="o", label=series, color=TOL_MUTED[idx % len(TOL_MUTED)])
        if series_field:
            ax.legend(loc=self._legend_loc(spec))

    def _render_bar(self, ax, rows: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        mapping = spec["data_mapping"]
        x_field, y_field = mapping["x"], mapping["y"]
        labels = [str(row[x_field]) for row in rows]
        values = [float(row[y_field]) for row in rows]
        errors = [float(row[mapping["error_y"]]) for row in rows] if "error_y" in mapping else None
        ax.bar(labels, values, yerr=errors, capsize=4, color=TOL_MUTED[0])
        ax.tick_params(axis="x", rotation=25)

    def _render_grouped_bar(self, ax, rows: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        mapping = spec["data_mapping"]
        x_field, y_field, series_field = mapping["x"], mapping["y"], mapping["series"]
        x_values = list(dict.fromkeys(str(row[x_field]) for row in rows))
        series_values = list(dict.fromkeys(str(row[series_field]) for row in rows))
        lookup = {(str(row[x_field]), str(row[series_field])): row for row in rows}
        width = 0.8 / max(len(series_values), 1)
        centers = list(range(len(x_values)))
        highlight = self._highlight_config(spec)
        for s_idx, series in enumerate(series_values):
            offsets = [center - 0.4 + width / 2 + s_idx * width for center in centers]
            values = [float(lookup[(x_val, series)][y_field]) for x_val in x_values]
            errors = None
            if "error_y" in mapping:
                errors = [float(lookup[(x_val, series)][mapping["error_y"]]) for x_val in x_values]
            edgecolor = "#111827" if highlight and highlight.get("field") == series_field and str(highlight.get("value")) == series else "none"
            linewidth = 1.8 if edgecolor != "none" else 0
            ax.bar(offsets, values, width=width, yerr=errors, capsize=3, label=series, color=TOL_MUTED[s_idx % len(TOL_MUTED)], edgecolor=edgecolor, linewidth=linewidth)
        ax.set_xticks(centers)
        ax.set_xticklabels(x_values, rotation=0)
        ax.legend(loc=self._legend_loc(spec), ncols=min(len(series_values), 4))

    def _render_scatter(self, ax, rows: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        mapping = spec["data_mapping"]
        grouped = self._group_rows(rows, mapping.get("series"))
        for idx, (series, group) in enumerate(grouped.items()):
            ax.scatter([float(row[mapping["x"]]) for row in group], [float(row[mapping["y"]]) for row in group], label=series, color=TOL_MUTED[idx % len(TOL_MUTED)])
        if mapping.get("series"):
            ax.legend(loc=self._legend_loc(spec))

    def _render_heatmap(self, ax, rows: list[dict[str, Any]], spec: dict[str, Any]) -> None:
        mapping = spec["data_mapping"]
        x_values = list(dict.fromkeys(str(row[mapping["x"]]) for row in rows))
        y_values = list(dict.fromkeys(str(row[mapping["y"]]) for row in rows))
        lookup = {(str(row[mapping["x"]]), str(row[mapping["y"]])): float(row[mapping["value"]]) for row in rows}
        matrix = [[lookup.get((x, y), 0.0) for x in x_values] for y in y_values]
        image = ax.imshow(matrix, aspect="auto", cmap="viridis")
        ax.set_xticks(range(len(x_values)))
        ax.set_xticklabels(x_values, rotation=30, ha="right")
        ax.set_yticks(range(len(y_values)))
        ax.set_yticklabels(y_values)
        ax.figure.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        for y_idx, row in enumerate(matrix):
            for x_idx, value in enumerate(row):
                ax.text(x_idx, y_idx, f"{value:g}", ha="center", va="center", color="white" if value > 5 else "#111827", fontsize=7)

    def _apply_labels(self, ax, spec: dict[str, Any]) -> None:
        labels = spec["labels"]
        ax.set_xlabel(labels["x_label"])
        ax.set_ylabel(labels["y_label"])
        ax.grid(axis="y", alpha=0.2)
        ax.figure.tight_layout()

    def _save_outputs(self, fig, output: dict[str, Any], attempt: int) -> list[dict[str, str]]:
        FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        files = []
        for fmt in output["formats"]:
            path = FIGURE_DIR / f"{output['basename']}_attempt_{attempt}.{fmt}"
            fig.savefig(path, format=fmt, bbox_inches="tight")
            files.append({"path": str(path), "format": fmt})
        return files

    def _group_rows(self, rows: list[dict[str, Any]], series_field: str | None) -> dict[str, list[dict[str, Any]]]:
        if not series_field:
            return {"series": rows}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row[series_field])].append(row)
        return dict(grouped)

    def _legend_loc(self, spec: dict[str, Any]) -> str:
        return {
            "top": "upper center",
            "right": "best",
            "upper_right_outside": "best",
        }.get(spec["style"].get("legend_position", "best"), "best")

    def _highlight_config(self, spec: dict[str, Any]) -> dict[str, Any] | None:
        style = spec.get("style", {})
        highlight = style.get("highlight")
        if isinstance(highlight, dict):
            return highlight
        mapping = spec.get("data_mapping", {})
        if "highlight_field" in mapping and "highlight_value" in mapping:
            return {"field": mapping["highlight_field"], "value": mapping["highlight_value"]}
        return None

    def _error(self, request_id: str, figure_id: str, attempt: int, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "figure_id": figure_id,
            "attempt": attempt,
            "status": "error",
            "renderer": self.renderer_name,
            "output_files": [],
            "metadata": {},
            "logs": [],
            "error": {"code": code, "message": message, "details": details},
        }
