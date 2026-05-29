#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from textwrap import wrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = PROJECT_ROOT / "skill_test_session" / "direct_pdf_figures" / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(DEFAULT_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(DEFAULT_CACHE_ROOT / "xdg"))

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

PALETTE = ["#355C7D", "#6C5B7B", "#C06C84", "#F67280", "#99B898", "#2A9D8F"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate direct paper figures without calling FigureAgent.")
    parser.add_argument("--contexts", type=Path, default=PROJECT_ROOT / "skill_test_session" / "ccfa_eval" / "contexts")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "skill_test_session" / "direct_pdf_figures")
    parser.add_argument("--base-dir", type=Path, default=PROJECT_ROOT / "skill_test_session")
    args = parser.parse_args()

    output_dir = args.output.resolve()
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for context_path in sorted(args.contexts.resolve().glob("*_context.json")):
        context = read_json(context_path)
        chart_path = make_chart(context, args.base_dir.resolve(), figures_dir)
        diagram_path = make_diagram(context, figures_dir)
        entries.append({
            "paper_id": context["paper_id"],
            "paper_title": context["paper_title"],
            "venue": context.get("venue"),
            "source_pdf": context.get("source_pdf"),
            "chart_path": str(chart_path),
            "diagram_path": str(diagram_path),
        })

    contact_sheet = output_dir / "direct_pdf_figures_overview.png"
    make_contact_sheet(entries, contact_sheet)
    manifest = {
        "generator": "scripts/generate_direct_pdf_figures.py",
        "uses_figure_agent": False,
        "paper_count": len(entries),
        "overview": str(contact_sheet),
        "figures": entries,
    }
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def make_chart(context: dict[str, Any], base_dir: Path, figures_dir: Path) -> Path:
    claim = context["analysis_claims"][0]
    evidence_id = claim["evidence_ids"][0]
    evidence = next(item for item in context["evidence_catalog"] if item["evidence_id"] == evidence_id)
    rows = read_csv(resolve_path(evidence["path"], base_dir))
    output = figures_dir / f"{context['paper_id']}_direct_chart.png"

    plt.rcParams.update({
        "font.size": 9,
        "axes.labelsize": 9,
        "axes.titlesize": 11,
        "legend.fontsize": 8,
    })
    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=180)
    chart_type = claim.get("suggested_chart_type") or "bar"
    if chart_type == "grouped_bar" and "method" in rows[0]:
        draw_grouped_bar(ax, rows)
    else:
        draw_bar(ax, rows)

    title = context["paper_title"]
    ax.set_title(title, loc="left", fontweight="bold", pad=12)
    ax.text(0, 1.01, claim["target_section"], transform=ax.transAxes, ha="left", va="bottom", color="#52606D", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#CBD5E1", alpha=0.45, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def draw_bar(ax, rows: list[dict[str, Any]]) -> None:
    label_field = "method" if "method" in rows[0] else "dataset"
    labels = [row[label_field] for row in rows]
    values = [float(row["score_mean"]) for row in rows]
    bars = ax.bar(labels, values, color=PALETTE[: len(rows)], edgecolor="#1F2933", linewidth=0.6)
    ax.set_ylabel(value_label(rows))
    ax.tick_params(axis="x", rotation=18)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:g}", ha="center", va="bottom", fontsize=8)


def draw_grouped_bar(ax, rows: list[dict[str, Any]]) -> None:
    datasets = list(dict.fromkeys(row["dataset"] for row in rows))
    methods = list(dict.fromkeys(row["method"] for row in rows))
    lookup = {(row["dataset"], row["method"]): float(row["score_mean"]) for row in rows}
    centers = list(range(len(datasets)))
    width = 0.78 / max(1, len(methods))
    for idx, method in enumerate(methods):
        xs = [center - 0.39 + width / 2 + idx * width for center in centers]
        values = [lookup[(dataset, method)] for dataset in datasets]
        ax.bar(xs, values, width=width, label=method, color=PALETTE[idx % len(PALETTE)], edgecolor="#1F2933", linewidth=0.5)
        for x, value in zip(xs, values):
            ax.text(x, value, f"{value:g}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(centers)
    ax.set_xticklabels(datasets)
    ax.set_ylabel(value_label(rows))
    ax.legend(frameon=False, ncols=min(3, len(methods)), loc="upper left")


def value_label(rows: list[dict[str, Any]]) -> str:
    dataset_text = " ".join(str(row.get("dataset", "")) for row in rows).lower()
    if "bleu" in dataset_text:
        return "BLEU"
    if "error" in dataset_text:
        return "Top-5 error (%)"
    if "ap" in dataset_text:
        return "Mask AP"
    if "kb/s" in dataset_text:
        return "Leak rate (KB/s)"
    if "seconds" in dataset_text:
        return "Elapsed time (s)"
    if "tb" in dataset_text:
        return "Table size (TB)"
    return "Score"


def make_diagram(context: dict[str, Any], figures_dir: Path) -> Path:
    summary = context["method_summaries"][0]
    steps = [part.strip() for part in summary["text"].split("->") if part.strip()]
    output = figures_dir / f"{context['paper_id']}_direct_diagram.png"

    fig, ax = plt.subplots(figsize=(10, 4.9), dpi=180)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.text(0.03, 0.94, context["paper_title"], fontsize=12, fontweight="bold", color="#17202A")
    ax.text(0.03, 0.895, summary["target_section"], fontsize=8.5, color="#52606D")

    n = len(steps)
    cols = min(4, max(2, math.ceil(math.sqrt(n + 1))))
    rows = math.ceil(n / cols)
    box_w = 0.19 if cols >= 4 else 0.24
    box_h = 0.14
    x_gap = (0.94 - cols * box_w) / max(1, cols - 1)
    y_gap = 0.18 if rows > 1 else 0.0
    y_start = 0.72

    positions: list[tuple[float, float]] = []
    for idx, step in enumerate(steps):
        row = idx // cols
        col = idx % cols
        if row % 2 == 1:
            col = cols - 1 - col
        x = 0.03 + col * (box_w + x_gap)
        y = y_start - row * (box_h + y_gap)
        positions.append((x, y))
        draw_box(ax, x, y, box_w, box_h, step, PALETTE[idx % len(PALETTE)])

    for idx in range(len(positions) - 1):
        draw_arrow_between(ax, positions[idx], positions[idx + 1], box_w, box_h)

    note = method_note(context)
    ax.text(0.03, 0.07, note, fontsize=8.2, color="#334155", ha="left", va="bottom", wrap=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return output


def draw_box(ax, x: float, y: float, width: float, height: float, label: str, color: str) -> None:
    rect = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.01,rounding_size=0.018",
        linewidth=1.2,
        edgecolor="#1F2933",
        facecolor=lighten(color, 0.78),
    )
    ax.add_patch(rect)
    lines = wrap(label, 19)[:3]
    text = "\n".join(lines)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=8.4, color="#17202A")
    ax.add_patch(Rectangle((x, y + height - 0.018), width, 0.018, color=color, linewidth=0))


def draw_arrow_between(ax, start: tuple[float, float], end: tuple[float, float], box_w: float, box_h: float) -> None:
    sx, sy = start
    ex, ey = end
    sc = (sx + box_w / 2, sy + box_h / 2)
    ec = (ex + box_w / 2, ey + box_h / 2)
    if abs(sc[1] - ec[1]) < 0.02:
        start_point = (sx + box_w, sc[1]) if ec[0] > sc[0] else (sx, sc[1])
        end_point = (ex, ec[1]) if ec[0] > sc[0] else (ex + box_w, ec[1])
        arrow = FancyArrowPatch(start_point, end_point, arrowstyle="-|>", mutation_scale=12, linewidth=1.1, color="#475569")
    else:
        mid_y = min(sc[1], ec[1]) - 0.11
        start_point = (sc[0], sy)
        end_point = (ec[0], ey + box_h)
        arrow = FancyArrowPatch(start_point, end_point, connectionstyle=f"angle3,angleA=-90,angleB=180", arrowstyle="-|>", mutation_scale=12, linewidth=1.1, color="#475569")
    ax.add_patch(arrow)


def method_note(context: dict[str, Any]) -> str:
    evidence = next((item for item in context["evidence_catalog"] if item["kind"] == "text_block"), None)
    if not evidence:
        return ""
    return str(evidence.get("content") or "")[:260]


def make_contact_sheet(entries: list[dict[str, Any]], output: Path) -> None:
    thumbs: list[tuple[dict[str, Any], Image.Image, Image.Image]] = []
    for entry in entries:
        chart = Image.open(entry["chart_path"]).convert("RGB")
        diagram = Image.open(entry["diagram_path"]).convert("RGB")
        chart.thumbnail((520, 310), Image.Resampling.LANCZOS)
        diagram.thumbnail((520, 310), Image.Resampling.LANCZOS)
        thumbs.append((entry, chart.copy(), diagram.copy()))
        chart.close()
        diagram.close()

    width = 1120
    row_h = 395
    height = 90 + len(thumbs) * row_h
    sheet = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(sheet)
    font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28) if Path("/System/Library/Fonts/Supplemental/Arial.ttf").exists() else ImageFont.load_default()
    font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 17) if Path("/System/Library/Fonts/Supplemental/Arial.ttf").exists() else ImageFont.load_default()
    draw.text((32, 28), "Direct PDF Paper Figures - No FigureAgent", fill="#111827", font=font_title)
    y = 85
    for entry, chart, diagram in thumbs:
        draw.text((32, y), f"{entry['paper_id']} | {entry.get('venue') or ''}", fill="#334155", font=font_small)
        sheet.paste(chart, (32, y + 32))
        sheet.paste(diagram, (584, y + 32))
        y += row_h
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def lighten(hex_color: str, factor: float) -> str:
    hex_color = hex_color.lstrip("#")
    values = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
    mixed = [round(value + (255 - value) * factor) for value in values]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def resolve_path(path_text: str, base_dir: Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = base_dir / path
    return path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
