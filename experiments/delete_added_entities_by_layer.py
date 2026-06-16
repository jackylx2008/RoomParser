"""Delete entities that were added relative to a baseline and match layers."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


_ensure_src_on_path()

from ezdxf import bbox

from room_extractor.cad.dxf_loader import load_dxf
from room_extractor.extraction.room_text_parser import extract_room_name, extract_room_number


TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete entities added since a baseline DXF on exact layer names.")
    parser.add_argument("--baseline", required=True, help="Baseline DXF whose modelspace handles are protected.")
    parser.add_argument("--source", required=True, help="Input DXF to clean.")
    parser.add_argument("--out", required=True, help="Output DXF.")
    parser.add_argument("--layer", action="append", required=True, help="Exact layer name to delete among added entities.")
    parser.add_argument("--manifest-out", help="Optional JSON manifest path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = delete_added_entities_by_layer(
        baseline=Path(args.baseline),
        source=Path(args.source),
        out=Path(args.out),
        layers=set(str(layer) for layer in args.layer),
    )
    manifest_path = Path(args.manifest_out) if args.manifest_out else Path(args.out).with_suffix(".delete_added_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["output_load_ok"] else 1


def delete_added_entities_by_layer(baseline: Path, source: Path, out: Path, layers: set[str]) -> dict[str, Any]:
    baseline_doc = load_dxf(baseline)
    source_doc = load_dxf(source)
    baseline_handles = {str(entity.dxf.handle).upper() for entity in baseline_doc.modelspace()}
    before = inspect_doc(source_doc, source)
    candidates = []
    for entity in source_doc.modelspace():
        handle = str(entity.dxf.handle).upper()
        layer = str(getattr(entity.dxf, "layer", ""))
        if handle in baseline_handles or layer not in layers:
            continue
        candidates.append(entity)
    removed = [entity_summary(entity) for entity in candidates]
    for entity in candidates:
        entity.destroy()
    try:
        source_doc.modelspace().entity_space.purge()
    except Exception:
        pass
    source_doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    source_doc.saveas(out)
    output_load_ok = False
    output_error = None
    after = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        output_load_ok = True
    except Exception as exc:
        output_error = f"{type(exc).__name__}: {exc}"
    return {
        "baseline": str(baseline),
        "source": str(source),
        "out": str(out),
        "layers": sorted(layers),
        "removed_count": len(removed),
        "removed_type_counts": dict(Counter(item["type"] for item in removed).most_common()),
        "removed_layer_counts": dict(Counter(item["layer"] for item in removed).most_common()),
        "removed_bbox_summary": bbox_summary(removed),
        "removed_sample": removed[:300],
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "before": before,
        "after": after,
    }


def inspect_doc(doc: Any, path: Path) -> dict[str, Any]:
    msp = doc.modelspace()
    counts = Counter(entity.dxftype() for entity in msp)
    layer_counts = Counter(str(getattr(entity.dxf, "layer", "")) for entity in msp)
    return {
        "file_size": path.stat().st_size,
        "layout_count": len(doc.layouts),
        "block_count": len(doc.blocks),
        "modelspace_entity_count": len(msp),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "layer_counts_top": dict(layer_counts.most_common(30)),
        "room_text": inspect_room_text(msp),
    }


def inspect_room_text(msp: Any) -> dict[str, Any]:
    room_number = 0
    room_name = 0
    parsed = 0
    for entity in msp:
        if entity.dxftype() not in TEXT_TYPES:
            continue
        text = entity_text(entity)
        has_number = extract_room_number(text) is not None
        has_name = extract_room_name(text) is not None
        room_number += int(has_number)
        room_name += int(has_name)
        parsed += int(has_number or has_name)
    return {"parsed_count": parsed, "room_number_count": room_number, "room_name_count": room_name}


def entity_summary(entity: Any) -> dict[str, Any]:
    bounds = entity_bbox(entity)
    return {
        "handle": str(entity.dxf.handle),
        "type": entity.dxftype(),
        "layer": str(getattr(entity.dxf, "layer", "")),
        "bbox": bounds,
        "diag": bbox_diag(bounds),
    }


def entity_bbox(entity: Any) -> list[float] | None:
    try:
        bounds = bbox.extents([entity], fast=True)
    except Exception:
        return None
    if not bounds.has_data:
        return None
    return [float(bounds.extmin.x), float(bounds.extmin.y), float(bounds.extmax.x), float(bounds.extmax.y)]


def bbox_diag(bounds: list[float] | None) -> float | None:
    if not bounds:
        return None
    return round(math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1]), 3)


def bbox_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    bounds = [item["bbox"] for item in items if item.get("bbox")]
    if not bounds:
        return {"has_bbox": False}
    diags = [float(item["diag"]) for item in items if item.get("diag") is not None]
    return {
        "has_bbox": True,
        "overall_bbox": [
            min(bound[0] for bound in bounds),
            min(bound[1] for bound in bounds),
            max(bound[2] for bound in bounds),
            max(bound[3] for bound in bounds),
        ],
        "diag_min": min(diags) if diags else None,
        "diag_max": max(diags) if diags else None,
        "diag_over_1000": sum(1 for diag in diags if diag > 1000),
    }


def entity_text(entity: Any) -> str:
    if entity.dxftype() == "MTEXT":
        return str(entity.text)
    return str(getattr(entity.dxf, "text", ""))


if __name__ == "__main__":
    raise SystemExit(main())
