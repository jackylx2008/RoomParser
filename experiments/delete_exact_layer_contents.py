"""Delete all entities on exact layer names from modelspace, layouts, and blocks."""

from __future__ import annotations

import argparse
import json
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

from room_extractor.cad.dxf_loader import load_dxf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete entities on exact DXF layer names.")
    parser.add_argument("--source", required=True, help="Input DXF.")
    parser.add_argument("--out", required=True, help="Output DXF.")
    parser.add_argument("--layer", action="append", required=True, help="Exact layer name to delete. Repeatable.")
    parser.add_argument("--manifest-out", help="Optional JSON manifest path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = delete_exact_layers(source=source, out=out, layers=set(args.layer))
    manifest_path = Path(args.manifest_out) if args.manifest_out else out.with_suffix(".delete_layers.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0


def delete_exact_layers(source: Path, out: Path, layers: set[str]) -> dict[str, Any]:
    doc = load_dxf(source)
    before = inspect_layers(doc, layers)
    removed: list[dict[str, Any]] = []
    removed_count = 0
    for space_label, space in iter_entity_spaces(doc):
        for entity in list(space):
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in layers:
                continue
            removed_count += 1
            if len(removed) < 500:
                removed.append(
                    {
                        "space": space_label,
                        "handle": str(getattr(entity.dxf, "handle", "")),
                        "type": entity.dxftype(),
                        "layer": layer,
                    }
                )
            entity.destroy()
        try:
            space.entity_space.purge()
        except Exception:
            pass
    doc.entitydb.purge()
    doc.saveas(out)
    after_doc = load_dxf(out)
    after = inspect_layers(after_doc, layers)
    return {
        "source": str(source),
        "out": str(out),
        "layers": sorted(layers),
        "removed_count": removed_count,
        "removed_sample": removed,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size,
        "before": before,
        "after": after,
    }


def iter_entity_spaces(doc: Any):
    yield "modelspace", doc.modelspace()
    for layout in doc.layouts:
        if str(layout.name).lower() != "model":
            yield f"layout:{layout.name}", layout
    for block in doc.blocks:
        yield f"block:{block.name}", block


def inspect_layers(doc: Any, layers: set[str]) -> dict[str, Any]:
    counts_by_space: dict[str, dict[str, int]] = {}
    type_counts: Counter[str] = Counter()
    total = 0
    for space_label, space in iter_entity_spaces(doc):
        counts = Counter()
        for entity in space:
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in layers:
                continue
            counts[layer] += 1
            type_counts[entity.dxftype()] += 1
            total += 1
        if counts:
            counts_by_space[space_label] = dict(counts)
    return {
        "total": total,
        "counts_by_space": counts_by_space,
        "type_counts": dict(type_counts.most_common()),
    }


if __name__ == "__main__":
    raise SystemExit(main())
