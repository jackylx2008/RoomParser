"""Explode selected modelspace INSERT handles with ezdxf."""

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
from room_extractor.extraction.room_text_parser import extract_room_name, extract_room_number


TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explode selected modelspace INSERT handles with ezdxf.")
    parser.add_argument("--source", required=True, help="Input DXF.")
    parser.add_argument("--out", required=True, help="Output DXF.")
    parser.add_argument("--handle", action="append", required=True, help="INSERT handle to explode. Repeatable.")
    parser.add_argument("--manifest-out", help="Optional JSON manifest path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = explode_handles(source=source, out=out, handles=[normalize_handle(handle) for handle in args.handle])
    manifest_path = Path(args.manifest_out) if args.manifest_out else out.with_suffix(".ezdxf_explode_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["status"] == "converted" and manifest["output_load_ok"] else 1


def explode_handles(source: Path, out: Path, handles: list[str]) -> dict[str, Any]:
    doc = load_dxf(source)
    before = inspect_doc(doc, source, handles)
    msp = doc.modelspace()
    exploded: list[dict[str, Any]] = []
    missing: list[str] = []
    wrong_type: list[dict[str, str]] = []
    for handle in handles:
        entity = doc.entitydb.get(handle)
        if entity is None:
            missing.append(handle)
            continue
        if entity.dxftype() != "INSERT":
            wrong_type.append({"handle": handle, "type": entity.dxftype()})
            continue
        name = str(getattr(entity.dxf, "name", ""))
        layer = str(getattr(entity.dxf, "layer", ""))
        exploded_count = 0
        try:
            result = entity.explode(target_layout=msp)
            exploded_count = len(result)
        except TypeError:
            result = entity.explode()
            exploded_count = len(result)
        exploded.append(
            {
                "handle": handle,
                "name": name,
                "layer": layer,
                "exploded_entity_count": exploded_count,
            }
        )
    try:
        msp.entity_space.purge()
    except Exception:
        pass
    doc.entitydb.purge()
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    after: dict[str, Any] | None = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out, handles)
        output_load_ok = True
    except Exception as exc:
        output_error = f"{type(exc).__name__}: {exc}"
    return {
        "status": "converted" if output_load_ok else "failed",
        "source": str(source),
        "out": str(out),
        "handles": handles,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "exploded": exploded,
        "missing": missing,
        "wrong_type": wrong_type,
        "before": before,
        "after": after,
    }


def inspect_doc(doc: Any, path: Path, handles: list[str]) -> dict[str, Any]:
    msp = doc.modelspace()
    counts = Counter(entity.dxftype() for entity in msp)
    target_entities = []
    msp_handles = {str(entity.dxf.handle).upper() for entity in msp}
    for handle in handles:
        entity = doc.entitydb.get(handle)
        if entity is None:
            continue
        target_entities.append(
            {
                "handle": handle,
                "in_modelspace": handle in msp_handles,
                "type": entity.dxftype(),
                "name": str(getattr(entity.dxf, "name", "")),
                "layer": str(getattr(entity.dxf, "layer", "")),
                "is_alive": bool(getattr(entity, "is_alive", False)),
            }
        )
    return {
        "file_size": path.stat().st_size,
        "layout_count": len(doc.layouts),
        "block_count": len(doc.blocks),
        "modelspace_entity_count": len(msp),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "insert_count": counts.get("INSERT", 0),
        "remaining_target_in_modelspace_count": sum(1 for item in target_entities if item["in_modelspace"]),
        "remaining_target_entities_sample": target_entities[:200],
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


def entity_text(entity: Any) -> str:
    if entity.dxftype() == "MTEXT":
        return str(entity.text)
    return str(getattr(entity.dxf, "text", ""))


def normalize_handle(handle: str) -> str:
    return str(handle).strip().upper()


if __name__ == "__main__":
    raise SystemExit(main())
