from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf.document import Drawing
from ezdxf.lldxf.const import DXFStructureError


def load_dxf(path: str | Path) -> Drawing:
    """Load a DXF document from disk."""
    dxf_path = Path(path)
    if not dxf_path.exists():
        raise FileNotFoundError(f"DXF file not found: {dxf_path}")
    if not dxf_path.is_file():
        raise ValueError(f"DXF path is not a file: {dxf_path}")
    if dxf_path.suffix.lower() != ".dxf":
        raise ValueError(f"Only DXF files are supported in Phase 1: {dxf_path}")
    try:
        return ezdxf.readfile(dxf_path)
    except (DXFStructureError, OSError) as exc:
        raise ValueError(f"Invalid or corrupted DXF file: {dxf_path}") from exc
