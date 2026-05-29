from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChartInference:
    chart_type: str
    data_mapping: dict[str, str]
    column_selector: list[str]
    reason: str


class ChartStructureInferer:
    TIME_HINTS = ["step", "epoch", "iteration", "round", "time", "date", "year"]
    X_HINTS = ["dataset", "condition", "category", "task", "benchmark", "x"]
    SERIES_HINTS = ["method", "model", "series", "group", "variant", "system"]
    VALUE_HINTS = ["score_mean", "mean", "score", "accuracy", "value", "apgr", "improvement_percent", "rank"]
    ERROR_HINTS = ["score_std", "std", "stderr", "error", "ci"]
    SCATTER_X_HINTS = ["x", "cost", "cpt", "cpt50_percent", "cpt80_percent", "strong_call_percent", "latency"]
    HEATMAP_HINTS = ["rank", "ranking", "heatmap", "matrix"]

    def infer(self, evidence: dict[str, Any] | None, requested_chart_type: str | None, goal: str = "") -> ChartInference | None:
        if not evidence or evidence.get("kind") not in {"table_file", "json_file"}:
            return None
        columns = [str(column) for column in evidence.get("columns") or [] if str(column)]
        if not columns:
            selector = evidence.get("column_selector")
            if isinstance(selector, list):
                columns = [str(column) for column in selector if str(column)]
        if not columns:
            return None

        lower_goal = goal.lower()
        x = self._first_match(columns, self.X_HINTS)
        time_x = self._first_match(columns, self.TIME_HINTS)
        series = self._first_match(columns, self.SERIES_HINTS)
        y = self._first_match(columns, self.VALUE_HINTS) or self._last_numeric_like(columns)
        error_y = self._first_match(columns, self.ERROR_HINTS)
        chart_type = self._chart_type(columns, requested_chart_type, lower_goal, time_x, series)

        if chart_type == "scatter":
            x = self._first_match(columns, self.SCATTER_X_HINTS) or x or columns[0]
        elif chart_type == "line":
            x = time_x or x or columns[0]
        else:
            x = x or time_x or columns[0]

        if chart_type == "heatmap":
            value = y or columns[-1]
            mapping = {
                "x": x,
                "y": series or self._first_other(columns, {x, value}) or x,
                "value": value,
            }
        else:
            mapping = {"x": x, "y": y or columns[-1]}
            if series and chart_type in {"line", "grouped_bar", "scatter"}:
                mapping["series"] = series
            if error_y:
                mapping["error_y"] = error_y

        selected = [field for field in [mapping.get("x"), mapping.get("series"), mapping.get("y"), mapping.get("value"), mapping.get("error_y")] if field]
        return ChartInference(
            chart_type=chart_type,
            data_mapping=mapping,
            column_selector=list(dict.fromkeys(selected)),
            reason=self._reason(chart_type, mapping),
        )

    def _chart_type(
        self,
        columns: list[str],
        requested_chart_type: str | None,
        lower_goal: str,
        time_x: str | None,
        series: str | None,
    ) -> str:
        if requested_chart_type and requested_chart_type != "grouped_bar":
            return requested_chart_type
        if any(token in lower_goal for token in ["scatter", "trade-off", "tradeoff", "correlation", "cost"]):
            return "scatter"
        if any(token in lower_goal for token in self.HEATMAP_HINTS):
            return "heatmap"
        if any(self._contains(column, self.HEATMAP_HINTS) for column in columns) and series:
            return "heatmap"
        if time_x:
            return "line"
        if series:
            return "grouped_bar"
        if requested_chart_type == "grouped_bar":
            return "bar"
        return requested_chart_type or "bar"

    def _first_match(self, columns: list[str], hints: list[str]) -> str | None:
        for hint in hints:
            for column in columns:
                if self._contains(column, [hint]):
                    return column
        return None

    def _first_other(self, columns: list[str], excluded: set[str]) -> str | None:
        for column in columns:
            if column not in excluded:
                return column
        return None

    def _last_numeric_like(self, columns: list[str]) -> str | None:
        for column in reversed(columns):
            lower = column.lower()
            if any(token in lower for token in ["score", "value", "mean", "rate", "percent", "accuracy", "rank", "cost"]):
                return column
        return columns[-1] if columns else None

    def _contains(self, value: str, hints: list[str]) -> bool:
        lower = value.lower()
        return any(hint == lower or hint in lower for hint in hints)

    def _reason(self, chart_type: str, mapping: dict[str, str]) -> str:
        pieces = [f"{chart_type}"]
        if mapping.get("series"):
            pieces.append(f"series={mapping['series']}")
        if mapping.get("error_y"):
            pieces.append(f"uncertainty={mapping['error_y']}")
        return "inferred " + ", ".join(pieces)
