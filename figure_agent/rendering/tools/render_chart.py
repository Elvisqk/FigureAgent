from __future__ import annotations

from typing import Any

from figure_agent.rendering.renderers.matplotlib_chart_renderer import MatplotlibChartRenderer
from figure_agent.common.validators import validate_payload


def render_chart(request: dict[str, Any]) -> dict[str, Any]:
    validate_payload(request, "render_chart_request.schema.json")
    renderer = MatplotlibChartRenderer()
    result = renderer.render(
        request_id=request["request_id"],
        figure_id=request["figure_id"],
        attempt=request["attempt"],
        spec=request["chart_spec"],
    )
    validate_payload(result, "render_result.schema.json")
    return result

