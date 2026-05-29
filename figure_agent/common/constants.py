from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = Path(os.getenv("FIGURE_AGENT_ARTIFACT_ROOT", str(PACKAGE_ROOT / "artifacts")))
REQUEST_DIR = ARTIFACT_ROOT / "requests"
INTENT_DIR = ARTIFACT_ROOT / "intents"
SPEC_DIR = ARTIFACT_ROOT / "specs"
FIGURE_DIR = ARTIFACT_ROOT / "figures"
REPORT_DIR = ARTIFACT_ROOT / "reports"
MANIFEST_DIR = ARTIFACT_ROOT / "manifests"
SCHEMA_DIR = PACKAGE_ROOT / "schemas"

ARTIFACT_DIRS = [
    REQUEST_DIR,
    INTENT_DIR,
    SPEC_DIR,
    FIGURE_DIR,
    REPORT_DIR,
    MANIFEST_DIR,
]

CHART_TYPES = {"line", "bar", "grouped_bar", "scatter", "heatmap"}
DIAGRAM_TYPES = {"pipeline", "module_architecture", "agent_workflow", "decision_flow"}
OUTPUT_FORMATS = {"png", "pdf", "svg"}

TOL_MUTED = [
    "#332288",
    "#88CCEE",
    "#44AA99",
    "#117733",
    "#999933",
    "#DDCC77",
    "#CC6677",
    "#882255",
    "#AA4499",
]


def ensure_artifact_dirs() -> None:
    for directory in ARTIFACT_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
