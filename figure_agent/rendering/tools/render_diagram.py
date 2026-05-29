from __future__ import annotations

from typing import Any

from figure_agent.rendering.renderers.graphviz_diagram_renderer import SimpleSvgDiagramRenderer
from figure_agent.common.validators import validate_payload


def render_diagram(request: dict[str, Any]) -> dict[str, Any]:
    validate_payload(request, "render_diagram_request.schema.json")
    renderer = SimpleSvgDiagramRenderer()
    result = renderer.render(
        request_id=request["request_id"],
        figure_id=request["figure_id"],
        attempt=request["attempt"],
        spec=request["diagram_spec"],
    )
    validate_payload(result, "render_result.schema.json")
    return result

