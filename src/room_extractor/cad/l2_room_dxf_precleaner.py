from __future__ import annotations

import argparse
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ezdxf import bbox

from room_extractor.cad.dxf_loader import load_dxf
from room_extractor.extraction.room_text_parser import extract_room_name, extract_room_number


TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}

DEFAULT_SOURCE = Path(
    "log/dxf_pre_explode_clean_experiment/steps/009_explode_largest_two_modelspace_blocks/candidate_after.dxf"
)
DEFAULT_OUT_DIR = Path("log/dxf_pre_explode_clean_experiment/main_flow")

DEFAULT_FURNITURE_LAYERS = [
    "活动家具",
    "1-活动家具细线",
    "1-活动家具粗线",
    "家具",
    "P-家具",
]
DEFAULT_WALL_INSERT_HANDLES = ["498936", "DF2884", "E02923"]
DEFAULT_COLUMN_INSERT_HANDLES = [
    "DAF5FB",
    "DAF5FC",
    "DB51C5",
    "DB51C6",
    "DB8875",
    "DB8876",
    "1117EFD",
    "1117EFE",
    "1117EFF",
    "1117F00",
    "1117F01",
    "1117F02",
    "1117F03",
    "1117F04",
    "1117F05",
    "1117F06",
    "1117F07",
    "1117F08",
    "1117F11",
    "1117F12",
    "1117F13",
    "1117F14",
    "1117F15",
    "1117F16",
    "1117F17",
    "1117F18",
    "1117F19",
    "1117F1A",
    "1117F1B",
    "1117F1C",
    "1117F1D",
    "1117F1E",
    "1117F1F",
    "1117F20",
    "1117F21",
    "1117F22",
    "1117F23",
    "1117F24",
    "1117F25",
    "1117F26",
    "1117F27",
    "1117F28",
    "1117F29",
    "1117F2A",
    "111A785",
    "111A786",
    "111A787",
    "111A788",
    "111A789",
    "111A78A",
    "111A78B",
    "111A78C",
    "111A78D",
    "111A78E",
    "111A78F",
    "111A790",
    "111A791",
    "111A792",
    "111A793",
    "111A794",
    "111A795",
    "111A796",
    "111B3D9",
    "111B3DA",
    "111B3DB",
    "111B3DC",
    "111C220",
    "111C221",
    "111C222",
    "111C223",
    "111C224",
    "111C225",
    "111C226",
    "111C227",
    "111C228",
    "111C229",
    "111C22A",
    "111C22B",
]
DEFAULT_REVIEW_WALL_INSERT_HANDLES = ["D38BC"]
REVIEW_WALL_NAME_TOKENS = ("墙半开洞口", "消火栓", "矩形")
REVIEW_WALL_LAYER = "05-L2-WALL$1$VT-WALL-总包"
DEFAULT_ADDED_LAYER0 = ["0"]
DEFAULT_ADDED_NON_COLUMN_LAYERS = [
    "05-L2-WALL$0$面积平面 - 会议2F- 20.00m平面图$0$A-DETL-GENF"
]


def add_l2_room_dxf_preclean_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help=(
            "Input DXF. Default is the experiment artifact after the two largest modelspace blocks were "
            "exploded by AutoCAD."
        ),
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory for staged DXF outputs and manifests.")
    parser.add_argument(
        "--final-name",
        default="candidate_after.dxf",
        help="Final DXF file name written under --out-dir.",
    )
    parser.add_argument(
        "--allow-missing-handles",
        action="store_true",
        help="Continue if a configured INSERT handle is absent. By default this is treated as a failed replay.",
    )
    parser.add_argument(
        "--furniture-layer",
        action="append",
        dest="furniture_layers",
        help="Exact furniture layer to delete. Repeatable. Defaults to the validated L2 furniture layers.",
    )
    parser.add_argument("--wall-handle", action="append", dest="wall_handles", help="Wall INSERT handle to explode.")
    parser.add_argument("--column-handle", action="append", dest="column_handles", help="Column INSERT handle to explode.")
    parser.add_argument(
        "--review-wall-handle",
        action="append",
        dest="review_wall_handles",
        help="Small reviewed wall/opening INSERT handle to explode.",
    )
    return parser


def run_l2_room_dxf_preclean(args: argparse.Namespace) -> int:
    source = Path(args.source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    allow_missing = bool(args.allow_missing_handles)

    furniture_layers = list(args.furniture_layers or DEFAULT_FURNITURE_LAYERS)
    wall_handles = normalize_handles(args.wall_handles or DEFAULT_WALL_INSERT_HANDLES)
    column_handles = normalize_handles(args.column_handles or DEFAULT_COLUMN_INSERT_HANDLES)
    review_wall_handles = normalize_handles(args.review_wall_handles or DEFAULT_REVIEW_WALL_INSERT_HANDLES)

    stages: list[dict[str, Any]] = []
    current = source

    stage_dir = out_dir / "001_delete_furniture_layers"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_exact_layers(
            source=source,
            out=current,
            layers=set(furniture_layers),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "002_explode_remaining_wall_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stages[-1]["out_path"],
            out=current,
            handles=wall_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
        )
    )
    wall_baseline = current

    stage_dir = out_dir / "003_explode_remaining_column_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stages[-1]["out_path"],
            out=current,
            handles=column_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
        )
    )

    stage_dir = out_dir / "004_explode_review_wall_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    review_wall_handles = merge_handles(select_review_wall_insert_handles(stages[-1]["out_path"]), review_wall_handles)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stages[-1]["out_path"],
            out=current,
            handles=review_wall_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
        )
    )

    stage_dir = out_dir / "005_remove_added_layer0_after_explode"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_added_entities_by_layer(
            baseline=wall_baseline,
            source=stages[-1]["out_path"],
            out=current,
            layers=set(DEFAULT_ADDED_LAYER0),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "006_keep_only_added_column_geometry_after_explode"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_added_entities_by_layer(
            baseline=wall_baseline,
            source=stages[-1]["out_path"],
            out=current,
            layers=set(DEFAULT_ADDED_NON_COLUMN_LAYERS),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    final_path = out_dir / str(args.final_name)
    shutil.copy2(current, final_path)

    payload = {
        "source": str(source),
        "out_dir": str(out_dir),
        "final": str(final_path),
        "final_load_ok": can_load(final_path),
        "stages": [public_stage_summary(stage) for stage in stages],
        "notes": [
            "This flow replays the automated part validated in steps 009-014.",
            "The preceding AutoCAD-only work is the largest-two-block explode that produced the default source.",
            "AutoCAD manual edits after step 014 are intentionally documented, not replayed here.",
        ],
    }
    manifest_path = out_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    failed = any(stage.get("failed") for stage in stages) or not payload["final_load_ok"]
    return 1 if failed else 0


def delete_exact_layers(source: Path, out: Path, layers: set[str], manifest_path: Path) -> dict[str, Any]:
    doc = load_dxf(source)
    before = inspect_doc(doc, source)
    removed: list[dict[str, Any]] = []
    removed_count = 0
    for space_label, space in iter_entity_spaces(doc):
        for entity in list(space):
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in layers:
                continue
            removed_count += 1
            if len(removed) < 500:
                removed.append(entity_summary(entity, space_label=space_label))
            entity.destroy()
        purge_space(space)
    doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    after_doc = load_dxf(out)
    manifest = {
        "stage": "delete_exact_layers",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "layers": sorted(layers),
        "removed_count": removed_count,
        "removed_type_counts": dict(Counter(item["type"] for item in removed).most_common()),
        "removed_layer_counts": dict(Counter(item["layer"] for item in removed).most_common()),
        "removed_sample": removed,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size,
        "output_load_ok": True,
        "failed": False,
        "before": before,
        "after": inspect_doc(after_doc, out),
    }
    write_manifest(manifest_path, manifest)
    return manifest


def explode_insert_handles(
    source: Path,
    out: Path,
    handles: list[str],
    manifest_path: Path,
    allow_missing: bool = False,
) -> dict[str, Any]:
    doc = load_dxf(source)
    before = inspect_doc(doc, source, target_handles=handles)
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
        try:
            result = entity.explode(target_layout=msp)
        except TypeError:
            result = entity.explode()
        exploded.append(
            {
                "handle": handle,
                "name": name,
                "layer": layer,
                "exploded_entity_count": len(result),
            }
        )
    purge_space(msp)
    doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    after = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out, target_handles=handles)
        output_load_ok = True
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"
    failed = bool(wrong_type or (missing and not allow_missing) or not output_load_ok)
    manifest = {
        "stage": "explode_insert_handles",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "handles": handles,
        "allow_missing": allow_missing,
        "exploded_count": len(exploded),
        "exploded": exploded,
        "missing": missing,
        "wrong_type": wrong_type,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "failed": failed,
        "before": before,
        "after": after,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def delete_added_entities_by_layer(
    baseline: Path,
    source: Path,
    out: Path,
    layers: set[str],
    manifest_path: Path,
) -> dict[str, Any]:
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
    purge_space(source_doc.modelspace())
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
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"
    manifest = {
        "stage": "delete_added_entities_by_layer",
        "baseline": str(baseline),
        "source": str(source),
        "out": str(out),
        "out_path": out,
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
        "failed": not output_load_ok,
        "before": before,
        "after": after,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def inspect_doc(doc: Any, path: Path, target_handles: Iterable[str] | None = None) -> dict[str, Any]:
    msp = doc.modelspace()
    counts = Counter(entity.dxftype() for entity in msp)
    layer_counts = Counter(str(getattr(entity.dxf, "layer", "")) for entity in msp)
    handles = [normalize_handle(handle) for handle in target_handles or []]
    msp_handles = {str(entity.dxf.handle).upper() for entity in msp}
    targets = []
    for handle in handles:
        entity = doc.entitydb.get(handle)
        if entity is None:
            targets.append({"handle": handle, "exists": False, "in_modelspace": False})
            continue
        targets.append(
            {
                "handle": handle,
                "exists": True,
                "in_modelspace": handle in msp_handles,
                "type": entity.dxftype(),
                "name": str(getattr(entity.dxf, "name", "")),
                "layer": str(getattr(entity.dxf, "layer", "")),
            }
        )
    return {
        "file_size": path.stat().st_size if path.exists() else None,
        "layout_count": len(doc.layouts),
        "block_count": len(doc.blocks),
        "modelspace_entity_count": len(msp),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "layer_counts_top": dict(layer_counts.most_common(30)),
        "insert_count": counts.get("INSERT", 0),
        "room_text": inspect_room_text(msp),
        "target_entities": targets,
    }


def select_review_wall_insert_handles(path: Path) -> list[str]:
    doc = load_dxf(path)
    selected = []
    for entity in doc.modelspace():
        if entity.dxftype() != "INSERT":
            continue
        name = str(getattr(entity.dxf, "name", ""))
        layer = str(getattr(entity.dxf, "layer", ""))
        if layer != REVIEW_WALL_LAYER:
            continue
        if all(token in name for token in REVIEW_WALL_NAME_TOKENS):
            selected.append(str(entity.dxf.handle))
    return normalize_handles(selected)


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


def iter_entity_spaces(doc: Any):
    yield "modelspace", doc.modelspace()
    for layout in doc.layouts:
        if str(layout.name).lower() != "model":
            yield f"layout:{layout.name}", layout
    for block in doc.blocks:
        yield f"block:{block.name}", block


def entity_summary(entity: Any, space_label: str = "modelspace") -> dict[str, Any]:
    bounds = entity_bbox(entity)
    return {
        "space": space_label,
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


def normalize_handle(handle: str) -> str:
    return str(handle).strip().upper()


def normalize_handles(handles: Iterable[str]) -> list[str]:
    return [normalize_handle(handle) for handle in handles if str(handle).strip()]


def merge_handles(*handle_groups: Iterable[str]) -> list[str]:
    merged = []
    seen = set()
    for handles in handle_groups:
        for handle in normalize_handles(handles):
            if handle in seen:
                continue
            seen.add(handle)
            merged.append(handle)
    return merged


def purge_space(space: Any) -> None:
    try:
        space.entity_space.purge()
    except Exception:
        pass


def can_load(path: Path) -> bool:
    try:
        load_dxf(path)
        return True
    except Exception:
        return False


def public_stage_summary(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": stage.get("stage"),
        "source": stage.get("source"),
        "out": stage.get("out"),
        "removed_count": stage.get("removed_count"),
        "exploded_count": stage.get("exploded_count"),
        "missing": stage.get("missing"),
        "wrong_type": stage.get("wrong_type"),
        "file_size_before": stage.get("file_size_before"),
        "file_size_after": stage.get("file_size_after"),
        "output_load_ok": stage.get("output_load_ok"),
        "failed": stage.get("failed"),
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    serializable = {key: str(value) if isinstance(value, Path) else value for key, value in manifest.items()}
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
