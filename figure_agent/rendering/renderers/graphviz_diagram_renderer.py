from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

from figure_agent.common.constants import FIGURE_DIR
from figure_agent.figure_request_runner.models import InvalidSpec, UnsupportedDiagramType


class SimpleSvgDiagramRenderer:
    renderer_name = "diagram_svg"

    def render(self, request_id: str, figure_id: str, attempt: int, spec: dict[str, Any]) -> dict[str, Any]:
        try:
            if spec["diagram_type"] not in {"pipeline", "module_architecture", "agent_workflow", "decision_flow"}:
                raise UnsupportedDiagramType(spec["diagram_type"])
            self._validate_graph(spec)
            layout = self._layout(spec)
            svg = self._build_svg(spec, layout)
            output_files = self._save_outputs(svg, spec, layout, spec["output"], attempt)
            return {
                "request_id": request_id,
                "figure_id": figure_id,
                "attempt": attempt,
                "status": "success",
                "renderer": self.renderer_name,
                "output_files": output_files,
                "metadata": {
                    "width_px": layout["width"],
                    "height_px": layout["height"],
                    "dpi": int(spec["style"]["dpi"]),
                    "renderer_version": "simple-svg-v2",
                },
                "logs": [],
                "error": None,
            }
        except UnsupportedDiagramType as exc:
            return self._error(request_id, figure_id, attempt, "UNSUPPORTED_DIAGRAM_TYPE", str(exc), {})
        except InvalidSpec as exc:
            return self._error(request_id, figure_id, attempt, "INVALID_GRAPH_STRUCTURE", str(exc), {})
        except Exception as exc:
            return self._error(request_id, figure_id, attempt, "RENDER_FAILED", str(exc), {})

    def _validate_graph(self, spec: dict[str, Any]) -> None:
        node_ids = [node["id"] for node in spec["nodes"]]
        if len(node_ids) != len(set(node_ids)):
            raise InvalidSpec("duplicate node ids")
        node_set = set(node_ids)
        for edge in spec["edges"]:
            if edge["source"] not in node_set or edge["target"] not in node_set:
                raise InvalidSpec(f"edge references unknown node: {edge['source']} -> {edge['target']}")

    def _layout(self, spec: dict[str, Any]) -> dict[str, Any]:
        margin = int(spec["style"].get("canvas_margin", 40))
        title_offset = 36 if spec.get("title") else 0
        mode = spec.get("layout", {}).get("mode")
        direction = spec["layout"]["direction"]
        node_sizes = self._node_sizes(spec)
        gap_x = max(54, int(spec["style"].get("cluster_padding", 24)) + 30)
        gap_y = max(46, int(spec["style"].get("lane_spacing", 48)))
        if mode == "hub_spoke":
            positions = self._layout_hub_spoke(spec, node_sizes, margin, title_offset, gap_x, gap_y)
        elif mode in {"swimlane_lr", "swimlane_tb"} and spec.get("lanes"):
            positions = self._layout_swimlanes(spec, node_sizes, margin, title_offset, gap_x, gap_y, mode)
        elif direction == "TB":
            positions = self._layout_vertical(spec, node_sizes, margin, title_offset, gap_y)
        elif direction == "GRID":
            positions = self._layout_grid(spec, node_sizes, margin, title_offset, gap_x, gap_y)
        else:
            positions = self._layout_horizontal(spec, node_sizes, margin, title_offset, gap_x)
        cluster_boxes = self._cluster_boxes(spec, positions, node_sizes)
        lane_boxes = self._lane_boxes(spec, positions, node_sizes)
        width, height = self._canvas_bounds(spec, positions, node_sizes, cluster_boxes, lane_boxes, margin, title_offset)
        return {
            "width": width,
            "height": height,
            "positions": positions,
            "node_sizes": node_sizes,
            "direction": direction,
            "mode": mode,
            "feedback_margin": int(spec["style"].get("feedback_margin", 48)),
            "cluster_boxes": cluster_boxes,
            "lane_boxes": lane_boxes,
        }

    def _layout_horizontal(
        self,
        spec: dict[str, Any],
        node_sizes: dict[str, tuple[int, int]],
        margin: int,
        title_offset: int,
        gap_x: int,
    ) -> dict[str, tuple[int, int]]:
        ordered_nodes = self._ordered_nodes(spec)
        y = margin + title_offset + 28
        x = margin
        positions: dict[str, tuple[int, int]] = {}
        for node in ordered_nodes:
            positions[node["id"]] = (x, y)
            x += node_sizes[node["id"]][0] + gap_x
        return positions

    def _layout_vertical(
        self,
        spec: dict[str, Any],
        node_sizes: dict[str, tuple[int, int]],
        margin: int,
        title_offset: int,
        gap_y: int,
    ) -> dict[str, tuple[int, int]]:
        ordered_nodes = self._ordered_nodes(spec)
        max_width = max(node_sizes[node["id"]][0] for node in ordered_nodes)
        x = margin + 20
        y = margin + title_offset
        positions: dict[str, tuple[int, int]] = {}
        for node in ordered_nodes:
            width, height = node_sizes[node["id"]]
            positions[node["id"]] = (x + (max_width - width) // 2, y)
            y += height + gap_y
        return positions

    def _layout_grid(
        self,
        spec: dict[str, Any],
        node_sizes: dict[str, tuple[int, int]],
        margin: int,
        title_offset: int,
        gap_x: int,
        gap_y: int,
    ) -> dict[str, tuple[int, int]]:
        ordered_nodes = self._ordered_nodes(spec)
        cols = 3 if len(ordered_nodes) > 6 else 2
        col_widths = [0] * cols
        row_heights: list[int] = []
        for idx, node in enumerate(ordered_nodes):
            col = idx % cols
            row = idx // cols
            width, height = node_sizes[node["id"]]
            col_widths[col] = max(col_widths[col], width)
            while len(row_heights) <= row:
                row_heights.append(0)
            row_heights[row] = max(row_heights[row], height)
        positions: dict[str, tuple[int, int]] = {}
        y = margin + title_offset
        for row, row_height in enumerate(row_heights):
            x = margin
            for col in range(cols):
                idx = row * cols + col
                if idx >= len(ordered_nodes):
                    break
                node = ordered_nodes[idx]
                width, height = node_sizes[node["id"]]
                positions[node["id"]] = (x + (col_widths[col] - width) // 2, y + (row_height - height) // 2)
                x += col_widths[col] + gap_x
            y += row_height + gap_y
        return positions

    def _layout_hub_spoke(
        self,
        spec: dict[str, Any],
        node_sizes: dict[str, tuple[int, int]],
        margin: int,
        title_offset: int,
        gap_x: int,
        gap_y: int,
    ) -> dict[str, tuple[int, int]]:
        ordered_nodes = self._ordered_nodes(spec)
        if len(ordered_nodes) <= 2:
            return self._layout_horizontal(spec, node_sizes, margin, title_offset, gap_x)
        primary = ordered_nodes[0]
        secondary = ordered_nodes[1:]
        center_x = margin + 280
        center_y = margin + title_offset + 150
        positions: dict[str, tuple[int, int]] = {
            primary["id"]: (center_x, center_y)
        }
        top: list[dict[str, Any]] = []
        bottom: list[dict[str, Any]] = []
        left: list[dict[str, Any]] = []
        right: list[dict[str, Any]] = []
        buckets = [top, right, bottom, left]
        for idx, node in enumerate(secondary):
            buckets[idx % 4].append(node)
        positions.update(self._linear_bucket(top, node_sizes, center_x, center_y - 150, gap_x, horizontal=True, above=True))
        positions.update(self._linear_bucket(bottom, node_sizes, center_x, center_y + 150, gap_x, horizontal=True, above=False))
        positions.update(self._linear_bucket(left, node_sizes, center_x - 250, center_y, gap_y, horizontal=False, above=True))
        positions.update(self._linear_bucket(right, node_sizes, center_x + 250, center_y, gap_y, horizontal=False, above=False))
        return positions

    def _linear_bucket(
        self,
        nodes: list[dict[str, Any]],
        node_sizes: dict[str, tuple[int, int]],
        anchor_x: int,
        anchor_y: int,
        gap: int,
        *,
        horizontal: bool,
        above: bool,
    ) -> dict[str, tuple[int, int]]:
        positions: dict[str, tuple[int, int]] = {}
        if not nodes:
            return positions
        if horizontal:
            total_width = sum(node_sizes[node["id"]][0] for node in nodes) + gap * (len(nodes) - 1)
            x = anchor_x - total_width // 2
            for node in nodes:
                width, height = node_sizes[node["id"]]
                y = anchor_y - height if above else anchor_y
                positions[node["id"]] = (x, y)
                x += width + gap
        else:
            total_height = sum(node_sizes[node["id"]][1] for node in nodes) + gap * (len(nodes) - 1)
            y = anchor_y - total_height // 2
            for node in nodes:
                width, height = node_sizes[node["id"]]
                x = anchor_x - width if above else anchor_x
                positions[node["id"]] = (x, y)
                y += height + gap
        return positions

    def _layout_swimlanes(
        self,
        spec: dict[str, Any],
        node_sizes: dict[str, tuple[int, int]],
        margin: int,
        title_offset: int,
        gap_x: int,
        gap_y: int,
        mode: str,
    ) -> dict[str, tuple[int, int]]:
        lanes = spec["lanes"]
        node_map = {node["id"]: node for node in spec["nodes"]}
        positions: dict[str, tuple[int, int]] = {}
        if mode == "swimlane_tb":
            y = margin + title_offset + 34
            max_width = 0
            for lane in lanes:
                x = margin + 24
                lane_height = 0
                for node_id in lane["members"]:
                    width, height = node_sizes[node_id]
                    positions[node_id] = (x, y + 24)
                    x += width + gap_x
                    lane_height = max(lane_height, height)
                max_width = max(max_width, x)
                y += lane_height + gap_y + 52
            remaining = [node for node in self._ordered_nodes(spec) if node["id"] not in positions]
            if remaining:
                y += 12
                x = margin + 24
                for node in remaining:
                    width, _ = node_sizes[node["id"]]
                    positions[node["id"]] = (x, y)
                    x += width + gap_x
                    max_width = max(max_width, x)
        else:
            x = margin + 24
            max_height = 0
            for lane in lanes:
                y = margin + title_offset + 34
                lane_width = 0
                for node_id in lane["members"]:
                    width, height = node_sizes[node_id]
                    positions[node_id] = (x + 24, y)
                    y += height + gap_y
                    lane_width = max(lane_width, width)
                    max_height = max(max_height, y)
                x += lane_width + gap_x + 52
            remaining = [node for node in self._ordered_nodes(spec) if node["id"] not in positions]
            if remaining:
                y = max_height + 24
                x = margin + 24
                for node in remaining:
                    width, _ = node_sizes[node["id"]]
                    positions[node["id"]] = (x, y)
                    x += width + gap_x
        for node in self._ordered_nodes(spec):
            if node["id"] not in positions:
                positions[node["id"]] = (margin, margin + title_offset)
        return positions

    def _cluster_boxes(
        self,
        spec: dict[str, Any],
        positions: dict[str, tuple[int, int]],
        node_sizes: dict[str, tuple[int, int]],
    ) -> list[dict[str, Any]]:
        padding = int(spec["style"].get("cluster_padding", 24))
        boxes: list[dict[str, Any]] = []
        for cluster in spec.get("clusters", []):
            members = [member for member in cluster["members"] if member in positions]
            if not members:
                continue
            x1 = min(positions[item][0] for item in members) - padding
            y1 = min(positions[item][1] for item in members) - padding
            x2 = max(positions[item][0] + node_sizes[item][0] for item in members) + padding
            y2 = max(positions[item][1] + node_sizes[item][1] for item in members) + padding
            boxes.append({
                "id": cluster["cluster_id"],
                "label": cluster["label"],
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": y2 - y1,
            })
        return boxes

    def _lane_boxes(
        self,
        spec: dict[str, Any],
        positions: dict[str, tuple[int, int]],
        node_sizes: dict[str, tuple[int, int]],
    ) -> list[dict[str, Any]]:
        padding = 18
        boxes: list[dict[str, Any]] = []
        for lane in spec.get("lanes", []):
            members = [member for member in lane["members"] if member in positions]
            if not members:
                continue
            x1 = min(positions[item][0] for item in members) - padding
            y1 = min(positions[item][1] for item in members) - padding - 18
            x2 = max(positions[item][0] + node_sizes[item][0] for item in members) + padding
            y2 = max(positions[item][1] + node_sizes[item][1] for item in members) + padding
            boxes.append({
                "id": lane["lane_id"],
                "label": lane["label"],
                "x": x1,
                "y": y1,
                "width": x2 - x1,
                "height": y2 - y1,
            })
        return boxes

    def _canvas_bounds(
        self,
        spec: dict[str, Any],
        positions: dict[str, tuple[int, int]],
        node_sizes: dict[str, tuple[int, int]],
        cluster_boxes: list[dict[str, Any]],
        lane_boxes: list[dict[str, Any]],
        margin: int,
        title_offset: int,
    ) -> tuple[int, int]:
        max_x = max(x + node_sizes[node_id][0] for node_id, (x, _) in positions.items())
        max_y = max(y + node_sizes[node_id][1] for node_id, (_, y) in positions.items())
        for box in cluster_boxes + lane_boxes:
            max_x = max(max_x, box["x"] + box["width"])
            max_y = max(max_y, box["y"] + box["height"])
        if any(edge.get("kind") == "feedback" for edge in spec["edges"]):
            max_y += int(spec["style"].get("feedback_margin", 36))
        width = int(max_x + margin)
        height = int(max_y + margin + max(0, title_offset - 8))
        return width, height

    def _node_sizes(self, spec: dict[str, Any]) -> dict[str, tuple[int, int]]:
        min_width = int(spec["style"].get("node_min_width", 170))
        min_height = int(spec["style"].get("node_min_height", 64))
        max_lines = int(spec.get("label_policy", {}).get("max_lines_per_node", 3))
        max_chars = int(spec.get("label_policy", {}).get("max_chars_per_line", 18))
        sizes: dict[str, tuple[int, int]] = {}
        for node in spec["nodes"]:
            label = str(node["label"]).replace("\n", " ")
            lines = self._wrap_label(label, max_chars)[:max_lines]
            longest = max((len(line) for line in lines), default=0)
            width = max(min_width, min(320, 40 + longest * 8))
            height = max(min_height, 28 + len(lines) * 18 + 24)
            sizes[node["id"]] = (width, height)
        return sizes

    def _build_svg(self, spec: dict[str, Any], layout: dict[str, Any]) -> str:
        width, height = layout["width"], layout["height"]
        positions = layout["positions"]
        node_sizes = layout["node_sizes"]
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            "<defs>",
            '<marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">',
            '<path d="M0,0 L0,6 L9,3 z" fill="#2F3A45" />',
            "</marker>",
            "</defs>",
            '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        ]
        if spec.get("title"):
            parts.append(f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="DejaVu Sans, Arial" font-size="16" font-weight="600" fill="#1F2933">{escape(spec["title"])}</text>')
        for lane in layout["lane_boxes"]:
            parts.extend(self._svg_group_box(lane, fill="#F8FAFC", stroke="#CBD5E1", dash="6,4"))
        for cluster in layout["cluster_boxes"]:
            parts.extend(self._svg_group_box(cluster, fill="#F8FBF8", stroke="#C7DACC", dash=None))
        for edge in spec["edges"]:
            points = self._route_edge(spec, layout, edge)
            parts.append(self._svg_polyline(points, str(edge.get("kind") or "primary")))
            if edge.get("label"):
                lx, ly = points[len(points) // 2]
                parts.append(f'<text x="{lx:.1f}" y="{ly - 8:.1f}" text-anchor="middle" font-family="DejaVu Sans, Arial" font-size="11" fill="#52606D">{escape(edge["label"])}</text>')
        for node in spec["nodes"]:
            x, y = positions[node["id"]]
            node_w, node_h = node_sizes[node["id"]]
            fill = self._fill_for_role(node["role"])
            stroke = "#0F172A" if node.get("priority") == "primary" else "#2F3A45"
            parts.append(f'<rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.8"/>')
            lines = str(node["label"]).split("\n")
            start_y = y + node_h / 2 - (len(lines) - 1) * 8
            for idx, line in enumerate(lines):
                weight = "600" if idx == 0 else "400"
                parts.append(f'<text x="{x + node_w / 2}" y="{start_y + idx * 16:.1f}" text-anchor="middle" dominant-baseline="middle" font-family="DejaVu Sans, Arial" font-size="13" font-weight="{weight}" fill="#1F2933">{escape(line)}</text>')
            if spec["style"].get("show_node_roles", True):
                parts.append(f'<text x="{x + node_w / 2}" y="{y + node_h - 10}" text-anchor="middle" font-family="DejaVu Sans, Arial" font-size="9" fill="#52606D">{escape(node["role"])}</text>')
        parts.append("</svg>")
        return "\n".join(parts)

    def _svg_group_box(self, box: dict[str, Any], *, fill: str, stroke: str, dash: str | None) -> list[str]:
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        return [
            f'<rect x="{box["x"]}" y="{box["y"]}" width="{box["width"]}" height="{box["height"]}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash_attr}/>',
            f'<text x="{box["x"] + 14}" y="{box["y"] + 20}" font-family="DejaVu Sans, Arial" font-size="12" font-weight="600" fill="#334155">{escape(box["label"])}</text>',
        ]

    def _svg_polyline(self, points: list[tuple[float, float]], kind: str) -> str:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        stroke = "#9A3412" if kind == "feedback" else "#64748B" if kind == "secondary" else "#2F3A45"
        width = "1.8" if kind == "feedback" else "1.6" if kind == "secondary" else "2"
        dash = ' stroke-dasharray="7,5"' if kind == "feedback" else ' stroke-dasharray="6,4"' if kind == "secondary" else ""
        return f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width}" marker-end="url(#arrow)"{dash}/>'

    def _route_edge(self, spec: dict[str, Any], layout: dict[str, Any], edge: dict[str, Any]) -> list[tuple[float, float]]:
        sx, sy = layout["positions"][edge["source"]]
        tx, ty = layout["positions"][edge["target"]]
        sw, sh = layout["node_sizes"][edge["source"]]
        tw, th = layout["node_sizes"][edge["target"]]
        if edge.get("kind") == "feedback":
            return self._route_feedback_edge(layout, edge, sx, sy, sw, sh, tx, ty, tw, th)
        start = self._node_anchor(sx, sy, sw, sh, tx, ty, tw, th)
        end = self._node_anchor(tx, ty, tw, th, sx, sy, sw, sh)
        if not spec.get("routing_hints", {}).get("prefer_orthogonal_edges", False):
            return [start, end]
        if abs(start[0] - end[0]) < 4 or abs(start[1] - end[1]) < 4:
            return [start, end]
        horizontal_first = abs(end[0] - start[0]) >= abs(end[1] - start[1])
        if horizontal_first:
            mid_x = (start[0] + end[0]) / 2
            return [start, (mid_x, start[1]), (mid_x, end[1]), end]
        mid_y = (start[1] + end[1]) / 2
        return [start, (start[0], mid_y), (end[0], mid_y), end]

    def _route_feedback_edge(
        self,
        layout: dict[str, Any],
        edge: dict[str, Any],
        sx: int,
        sy: int,
        sw: int,
        sh: int,
        tx: int,
        ty: int,
        tw: int,
        th: int,
    ) -> list[tuple[float, float]]:
        positions = layout["positions"]
        node_sizes = layout["node_sizes"]
        min_y = min(y for _, y in positions.values())
        max_y = max(y + node_sizes[node_id][1] for node_id, (_, y) in positions.items())
        source_center_x = sx + sw / 2
        target_center_x = tx + tw / 2
        source_center_y = sy + sh / 2
        target_center_y = ty + th / 2
        if target_center_y <= source_center_y:
            loop_y = max(28, min_y - int(layout.get("feedback_margin", 48)))
            return [
                (source_center_x, sy),
                (source_center_x, loop_y),
                (target_center_x, loop_y),
                (target_center_x, ty + th),
            ]
        loop_y = max_y + int(layout.get("feedback_margin", 48))
        return [
            (source_center_x, sy + sh),
            (source_center_x, loop_y),
            (target_center_x, loop_y),
            (target_center_x, ty),
        ]

    def _wrap_label(self, label: str, max_chars: int) -> list[str]:
        words = label.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines[:3] or [label]

    def _fill_for_role(self, role: str) -> str:
        palette = {
            "input": "#E8F2FF",
            "process": "#EAF7EF",
            "tool": "#FFF5D6",
            "decision": "#FDECEC",
            "output": "#F0ECFF",
            "store": "#FFF7ED",
        }
        return palette.get(role, "#F4F6F8")

    def _save_outputs(self, svg: str, spec: dict[str, Any], layout: dict[str, Any], output: dict[str, Any], attempt: int) -> list[dict[str, str]]:
        FIGURE_DIR.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, str]] = []
        for fmt in output["formats"]:
            path = FIGURE_DIR / f"{output['basename']}_attempt_{attempt}.{fmt}"
            if fmt == "svg":
                path.write_text(svg, encoding="utf-8")
            elif fmt == "png":
                self._write_png(path, spec, layout)
            else:
                raise InvalidSpec(f"unsupported diagram output format: {fmt}")
            files.append({"path": str(path), "format": fmt})
        return files

    def _write_png(self, path: Path, spec: dict[str, Any], layout: dict[str, Any]) -> None:
        width, height = layout["width"], layout["height"]
        positions = layout["positions"]
        node_sizes = layout["node_sizes"]
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        if spec.get("title"):
            draw.text((width // 2, 18), spec["title"], fill=(31, 41, 51), anchor="mm")
        for lane in layout["lane_boxes"]:
            draw.rounded_rectangle([lane["x"], lane["y"], lane["x"] + lane["width"], lane["y"] + lane["height"]], radius=14, fill=self._hex_to_rgb("#F8FAFC"), outline=self._hex_to_rgb("#CBD5E1"), width=2)
            draw.text((lane["x"] + 14, lane["y"] + 18), lane["label"], fill=(51, 65, 85), anchor="lm")
        for cluster in layout["cluster_boxes"]:
            draw.rounded_rectangle([cluster["x"], cluster["y"], cluster["x"] + cluster["width"], cluster["y"] + cluster["height"]], radius=14, fill=self._hex_to_rgb("#F8FBF8"), outline=self._hex_to_rgb("#C7DACC"), width=2)
            draw.text((cluster["x"] + 14, cluster["y"] + 18), cluster["label"], fill=(51, 65, 85), anchor="lm")
        for edge in spec["edges"]:
            points = self._route_edge(spec, layout, edge)
            color = "#9A3412" if edge.get("kind") == "feedback" else "#64748B" if edge.get("kind") == "secondary" else "#2F3A45"
            draw.line(points, fill=self._hex_to_rgb(color), width=2)
            self._draw_arrow(draw, points[-2], points[-1])
            if edge.get("label"):
                mid = points[len(points) // 2]
                draw.text((mid[0], mid[1] - 10), edge["label"], fill=(82, 96, 109), anchor="mm")
        for node in spec["nodes"]:
            x, y = positions[node["id"]]
            node_w, node_h = node_sizes[node["id"]]
            fill = self._hex_to_rgb(self._fill_for_role(node["role"]))
            outline = self._hex_to_rgb("#0F172A" if node.get("priority") == "primary" else "#2F3A45")
            draw.rounded_rectangle([x, y, x + node_w, y + node_h], radius=10, fill=fill, outline=outline, width=2)
            lines = str(node["label"]).split("\n")
            start_y = y + node_h // 2 - (len(lines) - 1) * 8
            for idx, line in enumerate(lines):
                draw.text((x + node_w // 2, start_y + idx * 16), line, fill=(31, 41, 51), anchor="mm")
            if spec["style"].get("show_node_roles", True):
                draw.text((x + node_w // 2, y + node_h - 10), node["role"], fill=(82, 96, 109), anchor="mm")
        image.save(path)

    def _draw_arrow(self, draw: ImageDraw.ImageDraw, start: tuple[float, float], end: tuple[float, float]) -> None:
        x1, y1 = start
        x2, y2 = end
        if abs(x2 - x1) >= abs(y2 - y1):
            points = [(x2, y2), (x2 - 9, y2 - 5), (x2 - 9, y2 + 5)]
        else:
            points = [(x2, y2), (x2 - 5, y2 - 9), (x2 + 5, y2 - 9)]
        draw.polygon(points, fill=(47, 58, 69))

    def _node_anchor(
        self,
        x: float,
        y: float,
        node_w: int,
        node_h: int,
        other_x: float,
        other_y: float,
        other_w: int,
        other_h: int,
    ) -> tuple[float, float]:
        cx, cy = x + node_w / 2, y + node_h / 2
        other_cx, other_cy = other_x + other_w / 2, other_y + other_h / 2
        dx, dy = other_cx - cx, other_cy - cy
        if abs(dx) > abs(dy):
            return (x + node_w if dx > 0 else x, cy)
        return (cx, y + node_h if dy > 0 else y)

    def _ordered_nodes(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        primary = set(spec.get("primary_flow", []))
        node_map = {node["id"]: node for node in spec["nodes"]}
        ordered = [node_map[node_id] for node_id in spec.get("primary_flow", []) if node_id in node_map]
        remaining = [node for node in spec["nodes"] if node["id"] not in primary]
        return ordered + remaining

    def _hex_to_rgb(self, value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[idx:idx + 2], 16) for idx in (0, 2, 4))

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
