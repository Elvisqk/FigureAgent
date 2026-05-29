from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


def get_asset_metadata(asset_path: str) -> dict[str, Any]:
    path = Path(asset_path)
    if not path.exists():
        return {"exists": False}

    metadata: dict[str, Any] = {
        "exists": True,
        "format": path.suffix.lstrip(".").lower(),
        "size_bytes": path.stat().st_size,
        "width_px": None,
        "height_px": None,
        "dpi": None,
    }
    if metadata["format"] in {"png", "jpg", "jpeg"}:
        with Image.open(path) as image:
            metadata["width_px"], metadata["height_px"] = image.size
            dpi = image.info.get("dpi")
            if dpi:
                metadata["dpi"] = int(round(dpi[0]))
    elif metadata["format"] == "svg":
        text = path.read_text(encoding="utf-8", errors="ignore")[:300]
        for attr in ("width", "height"):
            marker = f'{attr}="'
            if marker in text:
                value = text.split(marker, 1)[1].split('"', 1)[0]
                try:
                    metadata[f"{attr}_px"] = int(float(value))
                except ValueError:
                    pass
    return metadata

