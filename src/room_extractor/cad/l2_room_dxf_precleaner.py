from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from ezdxf import bbox

from room_extractor.cad.dxf_loader import load_dxf
from room_extractor.cad.dxf_line_deduper import (
    DEFAULT_EXACT_TOLERANCE,
    DEFAULT_NEAR_TOLERANCE,
    build_duplicate_report,
    collect_line_like_records,
    entity_signature,
    remove_duplicates,
)
from room_extractor.cad.entity_filter import is_entity_visible
from room_extractor.cad.dxf_self_cleaner import collect_reachable_blocks
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
DEFAULT_KEEP_PAPERSPACE_LAYOUT = "L2"
DEFAULT_DEDUPE_MODE = "near"
DEFAULT_DEDUPE_SIGNATURE_SCOPE = "geometry"
DEFAULT_CLEANUP_REFERENCE = Path(
    "log/dxf_pre_explode_clean_experiment/steps/014_keep_only_added_column_geometry_after_explode/candidate_after.dxf"
)
DEFAULT_REFERENCE_TOLERANCE = 1.0
DEFAULT_MAX_REFERENCE_EXPLODE_PASSES = 10


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
    parser.add_argument(
        "--keep-layout",
        default=DEFAULT_KEEP_PAPERSPACE_LAYOUT,
        help=(
            "Paper-space layout to retain as an empty required layout while deleting all other paper-space "
            f"layouts. Default: {DEFAULT_KEEP_PAPERSPACE_LAYOUT}."
        ),
    )
    parser.add_argument(
        "--dedupe-mode",
        choices=["exact", "near"],
        default=DEFAULT_DEDUPE_MODE,
        help="Linework duplicate mode used by the final cleanup stage. Default: near.",
    )
    parser.add_argument(
        "--dedupe-signature-scope",
        choices=["layer", "geometry"],
        default=DEFAULT_DEDUPE_SIGNATURE_SCOPE,
        help="Layer-aware or geometry-only linework signatures. Default: geometry.",
    )
    parser.add_argument(
        "--exact-tolerance",
        type=float,
        default=DEFAULT_EXACT_TOLERANCE,
        help=f"Exact linework tolerance. Default: {DEFAULT_EXACT_TOLERANCE}.",
    )
    parser.add_argument(
        "--near-tolerance",
        type=float,
        default=DEFAULT_NEAR_TOLERANCE,
        help=f"Near-duplicate coordinate grid size in CAD units. Default: {DEFAULT_NEAR_TOLERANCE}.",
    )
    parser.add_argument(
        "--cleanup-reference",
        default=str(DEFAULT_CLEANUP_REFERENCE),
        help="Reference DXF whose modelspace layer/entity content defines the final cleanup target.",
    )
    parser.add_argument(
        "--reference-tolerance",
        type=float,
        default=DEFAULT_REFERENCE_TOLERANCE,
        help=f"Geometry tolerance for reference-guided entity matching. Default: {DEFAULT_REFERENCE_TOLERANCE}.",
    )
    parser.add_argument(
        "--max-reference-explode-passes",
        type=int,
        default=DEFAULT_MAX_REFERENCE_EXPLODE_PASSES,
        help=(
            "Maximum synchronized explode/reference-prune passes. "
            f"Default: {DEFAULT_MAX_REFERENCE_EXPLODE_PASSES}."
        ),
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

    stage_dir = out_dir / "007_remove_paperspace_layouts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        remove_paperspace_layouts(
            source=stages[-1]["out_path"],
            out=current,
            keep_layout=str(args.keep_layout),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "008_enable_all_layers"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        enable_all_layers(
            source=stages[-1]["out_path"],
            out=current,
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "009_dedupe_linework"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        dedupe_linework(
            source=stages[-1]["out_path"],
            out=current,
            report_path=stage_dir / "duplicate_report.json",
            manifest_path=stage_dir / "manifest.json",
            mode=str(args.dedupe_mode),
            signature_scope=str(args.dedupe_signature_scope),
            exact_tolerance=float(args.exact_tolerance),
            near_tolerance=float(args.near_tolerance),
        )
    )

    stage_dir = out_dir / "010_reference_guided_prune"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        reference_guided_prune(
            source=stages[-1]["out_path"],
            reference=Path(args.cleanup_reference),
            out=current,
            report_path=stage_dir / "reference_prune_report.json",
            manifest_path=stage_dir / "manifest.json",
            tolerance=float(args.reference_tolerance),
        )
    )

    stage_dir = out_dir / "011_remove_reference_absent_unreachable_blocks"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        remove_reference_absent_unreachable_blocks(
            source=stages[-1]["out_path"],
            reference=Path(args.cleanup_reference),
            out=current,
            report_path=stage_dir / "removed_blocks.json",
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "012_reference_guided_block_content_prune"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        reference_guided_block_content_prune(
            source=stages[-1]["out_path"],
            reference=Path(args.cleanup_reference),
            out=current,
            report_path=stage_dir / "block_content_prune_report.json",
            manifest_path=stage_dir / "manifest.json",
            tolerance=float(args.reference_tolerance),
        )
    )

    stage_dir = out_dir / "013_remove_reference_absent_unreachable_blocks"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        remove_reference_absent_unreachable_blocks(
            source=stages[-1]["out_path"],
            reference=Path(args.cleanup_reference),
            out=current,
            report_path=stage_dir / "removed_blocks.json",
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "014_iterative_explode_reference_clean"
    stage_dir.mkdir(parents=True, exist_ok=True)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        iterative_explode_reference_clean(
            source=stages[-1]["out_path"],
            reference=Path(args.cleanup_reference),
            out=current,
            stage_dir=stage_dir,
            manifest_path=stage_dir / "manifest.json",
            max_passes=int(args.max_reference_explode_passes),
            reference_tolerance=float(args.reference_tolerance),
            dedupe_mode=str(args.dedupe_mode),
            dedupe_signature_scope=str(args.dedupe_signature_scope),
            exact_tolerance=float(args.exact_tolerance),
            near_tolerance=float(args.near_tolerance),
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
            "The final stage applies the AutoCAD-validated paper-space cleanup rule: retain one empty layout and preserve modelspace.",
            "All layers are enabled and thawed before the validated L2 near-geometry linework dedupe rule is applied.",
            "The final modelspace is pruned by layer/type/entity signatures derived from the manually validated step014 reference.",
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


def remove_paperspace_layouts(
    source: Path,
    out: Path,
    keep_layout: str,
    manifest_path: Path,
) -> dict[str, Any]:
    """Delete extra paper-space layouts and clear the one DXF-required layout.

    This is the production form of the ``remove_paperspace_layouts`` rule that
    was validated in ``experiments/dxf_self_clean_experiment.py``.  It does not
    run the rejected L2 experiment that also deleted unreachable blocks.
    """

    doc = load_dxf(source)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    paperspaces = [layout for layout in list(doc.layouts) if str(layout.name).lower() != "model"]
    available_names = [str(layout.name) for layout in paperspaces]
    kept_layout = next((name for name in available_names if name == keep_layout), None)
    if kept_layout is None and available_names:
        kept_layout = available_names[0]

    removed_layouts: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for layout in paperspaces:
        name = str(layout.name)
        if name == kept_layout:
            continue
        item = {
            "name": name,
            "block_record_name": str(getattr(layout, "block_record_name", "")),
            "entity_count": len(layout),
        }
        try:
            doc.layouts.delete(name)
            removed_layouts.append(item)
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    cleared_entities = 0
    if kept_layout is None:
        failed.append({"name": keep_layout, "error": "no paper-space layout exists to retain"})
    else:
        try:
            layout = doc.layouts.get(kept_layout)
            for entity in list(layout):
                entity.destroy()
                cleared_entities += 1
            purge_space(layout)
        except Exception as exc:
            failed.append({"name": kept_layout, "error": f"clear kept paperspace failed: {type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    doc.objects.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)

    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    protection_checks: list[dict[str, Any]] = []
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        output_load_ok = True
        for key in (
            "entity_count",
            "visible_entity_count",
            "invisible_entity_count",
            "entity_type_counts",
            "layer_counts",
            "entity_identity_sha256",
        ):
            passed = before_modelspace[key] == after_modelspace[key]
            protection_checks.append(
                {
                    "name": f"modelspace_{key}_unchanged",
                    "status": "passed" if passed else "failed",
                    "before": before_modelspace[key],
                    "after": after_modelspace[key],
                }
            )
        remaining_paperspaces = [layout for layout in after_doc.layouts if str(layout.name).lower() != "model"]
        layout_ok = len(remaining_paperspaces) == 1 and str(remaining_paperspaces[0].name) == kept_layout
        empty_ok = layout_ok and len(remaining_paperspaces[0]) == 0
        protection_checks.extend(
            [
                {
                    "name": "only_kept_paperspace_layout_remains",
                    "status": "passed" if layout_ok else "failed",
                    "expected": kept_layout,
                    "actual": [str(layout.name) for layout in remaining_paperspaces],
                },
                {
                    "name": "kept_paperspace_layout_is_empty",
                    "status": "passed" if empty_ok else "failed",
                    "entity_count": len(remaining_paperspaces[0]) if layout_ok else None,
                },
            ]
        )
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    protection_status = (
        "passed"
        if output_load_ok and protection_checks and all(check["status"] == "passed" for check in protection_checks)
        else "failed"
    )
    manifest = {
        "stage": "remove_paperspace_layouts",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "requested_keep_layout": keep_layout,
        "kept_paperspace_layout": kept_layout,
        "removed_count": len(removed_layouts) + cleared_entities,
        "removed_layout_count": len(removed_layouts),
        "removed_layouts": removed_layouts,
        "cleared_kept_paperspace_entity_count": cleared_entities,
        "failed_operations": failed,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {"status": protection_status, "checks": protection_checks},
        "failed": bool(failed or not output_load_ok or protection_status != "passed"),
        "before": before,
        "after": after,
        "before_modelspace": before_modelspace,
        "after_modelspace": after_modelspace,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def enable_all_layers(source: Path, out: Path, manifest_path: Path) -> dict[str, Any]:
    """Turn on and thaw every layer without changing modelspace entities."""

    doc = load_dxf(source)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    changed: list[dict[str, Any]] = []
    for layer in doc.layers:
        was_off = bool(layer.is_off())
        was_frozen = bool(layer.is_frozen())
        if was_off:
            layer.on()
        if was_frozen:
            layer.thaw()
        if was_off or was_frozen:
            changed.append({"name": str(layer.dxf.name), "was_off": was_off, "was_frozen": was_frozen})

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    remaining_off_or_frozen: list[dict[str, Any]] = []
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        output_load_ok = True
        remaining_off_or_frozen = [
            {
                "name": str(layer.dxf.name),
                "is_off": bool(layer.is_off()),
                "is_frozen": bool(layer.is_frozen()),
            }
            for layer in after_doc.layers
            if layer.is_off() or layer.is_frozen()
        ]
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    protected_keys = ("entity_count", "entity_type_counts", "layer_counts", "entity_identity_sha256")
    modelspace_unchanged = bool(
        after_modelspace
        and all(before_modelspace[key] == after_modelspace[key] for key in protected_keys)
    )
    protection_status = "passed" if output_load_ok and modelspace_unchanged and not remaining_off_or_frozen else "failed"
    manifest = {
        "stage": "enable_all_layers",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "changed_layer_count": len(changed),
        "changed_layers": changed,
        "remaining_off_or_frozen": remaining_off_or_frozen,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": protection_status,
            "modelspace_unchanged": modelspace_unchanged,
            "protected_keys": list(protected_keys),
        },
        "failed": not output_load_ok or protection_status != "passed",
        "before": before,
        "after": after,
        "before_modelspace": before_modelspace,
        "after_modelspace": after_modelspace,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def dedupe_linework(
    source: Path,
    out: Path,
    report_path: Path,
    manifest_path: Path,
    mode: str = DEFAULT_DEDUPE_MODE,
    signature_scope: str = DEFAULT_DEDUPE_SIGNATURE_SCOPE,
    exact_tolerance: float = DEFAULT_EXACT_TOLERANCE,
    near_tolerance: float = DEFAULT_NEAR_TOLERANCE,
) -> dict[str, Any]:
    """Apply the validated L2 exact/near linework dedupe implementation."""

    doc = load_dxf(source)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    records, skipped = collect_line_like_records(
        doc,
        visible_only=False,
        exact_tolerance=exact_tolerance,
        near_tolerance=near_tolerance,
        signature_scope=signature_scope,
        progress_interval=500000,
    )
    report = build_duplicate_report(
        records,
        input_path=source,
        output_path=out,
        visible_only=False,
        exact_tolerance=exact_tolerance,
        near_tolerance=near_tolerance,
        signature_scope=signature_scope,
        skipped_entity_count=skipped,
    )
    removed = remove_duplicates(doc, records, mode=mode)
    report["dedupe_mode"] = mode
    report["totals"]["removed_count"] = removed["total"]
    for layer, count in removed["layers"].items():
        report["layers"][layer]["removed_count"] = count
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        output_load_ok = True
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    expected_entity_count = before_modelspace["entity_count"] - int(removed["total"])
    non_linework_unchanged = bool(
        after_modelspace
        and all(
            before_modelspace["entity_type_counts"].get(entity_type, 0)
            == after_modelspace["entity_type_counts"].get(entity_type, 0)
            for entity_type in set(before_modelspace["entity_type_counts"]) - {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}
        )
    )
    count_matches = bool(after_modelspace and after_modelspace["entity_count"] == expected_entity_count)
    protection_status = "passed" if output_load_ok and non_linework_unchanged and count_matches else "failed"
    manifest = {
        "stage": "dedupe_linework",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "report": str(report_path),
        "dedupe_mode": mode,
        "signature_scope": signature_scope,
        "exact_tolerance": exact_tolerance,
        "near_tolerance": near_tolerance,
        "removed_count": removed["total"],
        "removed_layer_counts": removed["layers"],
        "skipped_entity_count": skipped,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": protection_status,
            "expected_modelspace_entity_count": expected_entity_count,
            "actual_modelspace_entity_count": after_modelspace["entity_count"] if after_modelspace else None,
            "non_linework_unchanged": non_linework_unchanged,
        },
        "failed": not output_load_ok or protection_status != "passed",
        "before": before,
        "after": after,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def reference_guided_prune(
    source: Path,
    reference: Path,
    out: Path,
    report_path: Path,
    manifest_path: Path,
    tolerance: float = DEFAULT_REFERENCE_TOLERANCE,
) -> dict[str, Any]:
    """Remove modelspace entities not represented by the validated reference.

    Matching is independent of DXF handles because AutoCAD rewrites many
    handles during round-trips.  A Counter budget prevents the candidate from
    retaining more copies of an entity signature than the reference contains.
    """

    if tolerance <= 0:
        raise ValueError("reference tolerance must be greater than 0")
    source_doc = load_dxf(source)
    reference_doc = load_dxf(reference)
    before = inspect_doc(source_doc, source)
    reference_stats = inspect_doc(reference_doc, reference)
    reference_layers = Counter(str(getattr(entity.dxf, "layer", "")) for entity in reference_doc.modelspace())
    reference_layer_types = Counter(
        (str(getattr(entity.dxf, "layer", "")), entity.dxftype()) for entity in reference_doc.modelspace()
    )
    reference_signatures = Counter(
        reference_entity_signature(entity, tolerance) for entity in reference_doc.modelspace()
    )
    retained_signatures: Counter[tuple[Any, ...]] = Counter()
    removed_entities: list[Any] = []
    removed_reasons: Counter[str] = Counter()
    removed_types: Counter[str] = Counter()
    removed_layers: Counter[str] = Counter()
    removed_samples: list[dict[str, Any]] = []

    for entity in source_doc.modelspace():
        layer = str(getattr(entity.dxf, "layer", ""))
        entity_type = entity.dxftype()
        signature = reference_entity_signature(entity, tolerance)
        if reference_layers[layer] == 0:
            reason = "layer_absent_from_reference"
        elif reference_layer_types[(layer, entity_type)] == 0:
            reason = "entity_type_absent_from_reference_layer"
        elif retained_signatures[signature] >= reference_signatures[signature]:
            reason = "entity_signature_exceeds_reference_budget"
        else:
            retained_signatures[signature] += 1
            continue
        removed_entities.append(entity)
        removed_reasons[reason] += 1
        removed_types[entity_type] += 1
        removed_layers[layer] += 1
        if len(removed_samples) < 500:
            item = entity_summary(entity)
            item["reason"] = reason
            if entity_type in TEXT_TYPES:
                item["text"] = entity_text(entity)[:500]
            if entity_type == "INSERT":
                item["name"] = str(getattr(entity.dxf, "name", ""))
            removed_samples.append(item)

    for entity in removed_entities:
        entity.destroy()
    purge_space(source_doc.modelspace())
    source_doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    source_doc.saveas(out)

    output_load_ok = False
    output_error = None
    after = None
    subset_check = False
    excess_signature_count = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        output_load_ok = True
        after_signatures = Counter(reference_entity_signature(entity, tolerance) for entity in after_doc.modelspace())
        excess_signature_count = sum(
            max(0, count - reference_signatures[signature]) for signature, count in after_signatures.items()
        )
        subset_check = excess_signature_count == 0
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    report = {
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "tolerance": tolerance,
        "removed_count": len(removed_entities),
        "removed_reason_counts": dict(removed_reasons.most_common()),
        "removed_type_counts": dict(removed_types.most_common()),
        "removed_layer_count": len(removed_layers),
        "removed_layer_counts": dict(removed_layers.most_common()),
        "removed_samples": removed_samples,
        "reference_modelspace_entity_count": len(reference_doc.modelspace()),
        "source_modelspace_entity_count": before["modelspace_entity_count"],
        "output_modelspace_entity_count": after["modelspace_entity_count"] if after else None,
        "output_is_reference_signature_subset": subset_check,
        "excess_signature_count": excess_signature_count,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    protection_status = "passed" if output_load_ok and subset_check else "failed"
    manifest = {
        "stage": "reference_guided_prune",
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "out_path": out,
        "report": str(report_path),
        "tolerance": tolerance,
        "removed_count": len(removed_entities),
        "removed_reason_counts": dict(removed_reasons.most_common()),
        "removed_type_counts": dict(removed_types.most_common()),
        "removed_layer_count": len(removed_layers),
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": protection_status,
            "output_is_reference_signature_subset": subset_check,
            "excess_signature_count": excess_signature_count,
        },
        "failed": not output_load_ok or protection_status != "passed",
        "before": before,
        "after": after,
        "reference_stats": reference_stats,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def remove_reference_absent_unreachable_blocks(
    source: Path,
    reference: Path,
    out: Path,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Delete unreachable non-anonymous block definitions absent from the reference.

    AutoCAD can keep DIMENSION entities tied to anonymous ``*D`` geometry blocks
    even when ezdxf's reachability scan reports those blocks as unreachable.
    Deleting such blocks makes AutoCAD reject the DXF with an invalid dimension
    block name, so all anonymous blocks are preserved by default.
    """

    doc = load_dxf(source)
    reference_doc = load_dxf(reference)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    reachable = collect_reachable_blocks(doc)
    reference_names = {str(block.name) for block in reference_doc.blocks}
    remove_names = sorted(
        str(block.name)
        for block in doc.blocks
        if str(block.name) not in reachable
        and str(block.name) not in reference_names
        and not is_anonymous_block_name(str(block.name))
    )
    preserved_anonymous = sorted(
        str(block.name)
        for block in doc.blocks
        if str(block.name) not in reachable
        and str(block.name) not in reference_names
        and is_anonymous_block_name(str(block.name))
    )
    removed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for name in remove_names:
        try:
            block = doc.blocks.get(name)
            removed.append({"name": name, "entity_count": len(block)})
            doc.blocks.delete_block(name, safe=False)
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    doc.objects.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    remaining_reference_absent_unreachable: list[str] = []
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        output_load_ok = True
        after_reachable = collect_reachable_blocks(after_doc)
        remaining_reference_absent_unreachable = sorted(
            str(block.name)
            for block in after_doc.blocks
            if str(block.name) not in after_reachable and str(block.name) not in reference_names
            and not is_anonymous_block_name(str(block.name))
        )
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    modelspace_unchanged = before_modelspace == after_modelspace
    protection_status = (
        "passed"
        if output_load_ok and modelspace_unchanged and not failed and not remaining_reference_absent_unreachable
        else "failed"
    )
    report = {
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "reachable_block_count_before": len(reachable),
        "reference_block_count": len(reference_names),
        "removed_block_count": len(removed),
        "removed_block_entity_count": sum(item["entity_count"] for item in removed),
        "removed_blocks": removed,
        "preserved_anonymous_reference_absent_unreachable_count": len(preserved_anonymous),
        "preserved_anonymous_reference_absent_unreachable": preserved_anonymous,
        "failed_count": len(failed),
        "failed": failed,
        "remaining_reference_absent_unreachable": remaining_reference_absent_unreachable,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "stage": "remove_reference_absent_unreachable_blocks",
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "out_path": out,
        "report": str(report_path),
        "removed_count": len(removed),
        "removed_block_count": len(removed),
        "removed_block_entity_count": sum(item["entity_count"] for item in removed),
        "preserved_anonymous_reference_absent_unreachable_count": len(preserved_anonymous),
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": protection_status,
            "modelspace_unchanged": modelspace_unchanged,
            "remaining_reference_absent_unreachable_count": len(remaining_reference_absent_unreachable),
        },
        "failed": not output_load_ok or protection_status != "passed",
        "before": before,
        "after": after,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def reference_guided_block_content_prune(
    source: Path,
    reference: Path,
    out: Path,
    report_path: Path,
    manifest_path: Path,
    tolerance: float = DEFAULT_REFERENCE_TOLERANCE,
) -> dict[str, Any]:
    """Prune shared named block definitions to reference signature budgets."""

    doc = load_dxf(source)
    reference_doc = load_dxf(reference)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    reference_blocks = {str(block.name): block for block in reference_doc.blocks}
    removed: list[Any] = []
    removed_types: Counter[str] = Counter()
    removed_layers: Counter[str] = Counter()
    removed_blocks: Counter[str] = Counter()
    removed_samples: list[dict[str, Any]] = []

    for block in doc.blocks:
        name = str(block.name)
        if is_layout_block_name(name) or name not in reference_blocks:
            continue
        reference_budget = Counter(
            reference_entity_signature(entity, tolerance) for entity in reference_blocks[name]
        )
        retained: Counter[tuple[Any, ...]] = Counter()
        for entity in list(block):
            signature = reference_entity_signature(entity, tolerance)
            if retained[signature] < reference_budget[signature]:
                retained[signature] += 1
                continue
            removed.append(entity)
            removed_types[entity.dxftype()] += 1
            removed_layers[str(getattr(entity.dxf, "layer", ""))] += 1
            removed_blocks[name] += 1
            if len(removed_samples) < 500:
                item = entity_summary(entity, space_label=f"block:{name}")
                if entity.dxftype() == "INSERT":
                    item["name"] = str(getattr(entity.dxf, "name", ""))
                removed_samples.append(item)
        purge_space(block)

    for entity in removed:
        entity.destroy()
    for block in doc.blocks:
        purge_space(block)
    doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)

    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    excess_shared_block_signature_count = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        output_load_ok = True
        excess_shared_block_signature_count = count_excess_shared_block_signatures(
            after_doc, reference_doc, tolerance
        )
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    modelspace_unchanged = before_modelspace == after_modelspace
    protection_status = (
        "passed"
        if output_load_ok and modelspace_unchanged and excess_shared_block_signature_count == 0
        else "failed"
    )
    report = {
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "tolerance": tolerance,
        "removed_count": len(removed),
        "removed_type_counts": dict(removed_types.most_common()),
        "removed_layer_counts": dict(removed_layers.most_common()),
        "affected_block_count": len(removed_blocks),
        "removed_by_block": dict(removed_blocks.most_common()),
        "removed_samples": removed_samples,
        "excess_shared_block_signature_count": excess_shared_block_signature_count,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "stage": "reference_guided_block_content_prune",
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "out_path": out,
        "report": str(report_path),
        "tolerance": tolerance,
        "removed_count": len(removed),
        "removed_type_counts": dict(removed_types.most_common()),
        "affected_block_count": len(removed_blocks),
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": protection_status,
            "modelspace_unchanged": modelspace_unchanged,
            "excess_shared_block_signature_count": excess_shared_block_signature_count,
        },
        "failed": not output_load_ok or protection_status != "passed",
        "before": before,
        "after": after,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def count_excess_shared_block_signatures(doc: Any, reference_doc: Any, tolerance: float) -> int:
    reference_blocks = {str(block.name): block for block in reference_doc.blocks}
    excess = 0
    for block in doc.blocks:
        name = str(block.name)
        if is_layout_block_name(name) or name not in reference_blocks:
            continue
        reference_budget = Counter(
            reference_entity_signature(entity, tolerance) for entity in reference_blocks[name]
        )
        actual = Counter(reference_entity_signature(entity, tolerance) for entity in block)
        excess += sum(max(0, count - reference_budget[signature]) for signature, count in actual.items())
    return excess


def is_layout_block_name(name: str) -> bool:
    upper = name.upper()
    return upper == "*MODEL_SPACE" or upper.startswith("*PAPER_SPACE")


def is_anonymous_block_name(name: str) -> bool:
    return name.startswith("*")


def iterative_explode_reference_clean(
    source: Path,
    reference: Path,
    out: Path,
    stage_dir: Path,
    manifest_path: Path,
    max_passes: int = DEFAULT_MAX_REFERENCE_EXPLODE_PASSES,
    reference_tolerance: float = DEFAULT_REFERENCE_TOLERANCE,
    dedupe_mode: str = DEFAULT_DEDUPE_MODE,
    dedupe_signature_scope: str = DEFAULT_DEDUPE_SIGNATURE_SCOPE,
    exact_tolerance: float = DEFAULT_EXACT_TOLERANCE,
    near_tolerance: float = DEFAULT_NEAR_TOLERANCE,
) -> dict[str, Any]:
    """Explode current/reference one level at a time, then prune and dedupe."""

    if max_passes < 1:
        raise ValueError("max reference explode passes must be at least 1")
    stage_dir.mkdir(parents=True, exist_ok=True)
    current_source = source
    current_reference = reference
    passes: list[dict[str, Any]] = []
    stop_reason = "max_passes_reached"

    for pass_number in range(1, max_passes + 1):
        pass_dir = stage_dir / f"pass_{pass_number:03d}"
        pass_dir.mkdir(parents=True, exist_ok=True)
        exploded_source = pass_dir / "current_exploded.dxf"
        exploded_reference = pass_dir / "reference_exploded.dxf"
        completed_files = {
            "source_explode": pass_dir / "current_explode_manifest.json",
            "reference_explode": pass_dir / "reference_explode_manifest.json",
            "pruned": pass_dir / "reference_prune_manifest.json",
            "deduped": pass_dir / "dedupe_manifest.json",
            "candidate": pass_dir / "candidate_after.dxf",
            "reference": exploded_reference,
        }
        if all(path.exists() and path.stat().st_size > 0 for path in completed_files.values()):
            source_explode = read_json_file(completed_files["source_explode"])
            reference_explode = read_json_file(completed_files["reference_explode"])
            pruned = read_json_file(completed_files["pruned"])
            deduped = read_json_file(completed_files["deduped"])
            remaining_insert_count = int((deduped.get("after") or {}).get("insert_count", 0))
            pass_failed = bool(
                source_explode["failed"] or reference_explode["failed"] or pruned["failed"] or deduped["failed"]
            )
            passes.append(
                iterative_pass_summary(
                    pass_number,
                    pass_dir,
                    source_explode,
                    reference_explode,
                    pruned,
                    deduped,
                    remaining_insert_count,
                    pass_failed,
                    resumed=True,
                )
            )
            current_source = completed_files["candidate"]
            current_reference = completed_files["reference"]
            if pass_failed:
                stop_reason = "pass_failed"
                break
            if remaining_insert_count == 0:
                stop_reason = "no_remaining_inserts"
                break
            if int(source_explode["exploded_count"]) == 0:
                stop_reason = "no_explode_progress"
                break
            continue
        source_explode = explode_modelspace_one_level(
            source=current_source,
            out=exploded_source,
            manifest_path=pass_dir / "current_explode_manifest.json",
        )
        reference_explode = explode_modelspace_one_level(
            source=current_reference,
            out=exploded_reference,
            manifest_path=pass_dir / "reference_explode_manifest.json",
        )
        pruned = reference_guided_prune(
            source=exploded_source,
            reference=exploded_reference,
            out=pass_dir / "candidate_after_reference_prune.dxf",
            report_path=pass_dir / "reference_prune_report.json",
            manifest_path=pass_dir / "reference_prune_manifest.json",
            tolerance=reference_tolerance,
        )
        deduped = dedupe_linework(
            source=Path(pruned["out_path"]),
            out=pass_dir / "candidate_after.dxf",
            report_path=pass_dir / "duplicate_report.json",
            manifest_path=pass_dir / "dedupe_manifest.json",
            mode=dedupe_mode,
            signature_scope=dedupe_signature_scope,
            exact_tolerance=exact_tolerance,
            near_tolerance=near_tolerance,
        )
        remaining_insert_count = int((deduped.get("after") or {}).get("insert_count", 0))
        pass_failed = bool(source_explode["failed"] or reference_explode["failed"] or pruned["failed"] or deduped["failed"])
        passes.append(
            iterative_pass_summary(
                pass_number,
                pass_dir,
                source_explode,
                reference_explode,
                pruned,
                deduped,
                remaining_insert_count,
                pass_failed,
                resumed=False,
            )
        )
        current_source = Path(deduped["out_path"])
        current_reference = exploded_reference
        if pass_failed:
            stop_reason = "pass_failed"
            break
        if remaining_insert_count == 0:
            stop_reason = "no_remaining_inserts"
            break
        if int(source_explode["exploded_count"]) == 0:
            stop_reason = "no_explode_progress"
            break

    shutil.copy2(current_source, out)
    final_load_ok = can_load(out)
    final_doc = load_dxf(out) if final_load_ok else None
    final_insert_count = len(final_doc.modelspace().query("INSERT")) if final_doc is not None else None
    failed = bool(not final_load_ok or any(item["failed"] for item in passes))
    manifest = {
        "stage": "iterative_explode_reference_clean",
        "source": str(source),
        "reference": str(reference),
        "out": str(out),
        "out_path": out,
        "max_passes": max_passes,
        "completed_passes": len(passes),
        "stop_reason": stop_reason,
        "final_insert_count": final_insert_count,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size,
        "output_load_ok": final_load_ok,
        "protection": {
            "status": "passed" if not failed else "failed",
            "synchronized_reference_explode": True,
        },
        "passes": passes,
        "failed": failed,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def iterative_pass_summary(
    pass_number: int,
    pass_dir: Path,
    source_explode: dict[str, Any],
    reference_explode: dict[str, Any],
    pruned: dict[str, Any],
    deduped: dict[str, Any],
    remaining_insert_count: int,
    pass_failed: bool,
    resumed: bool,
) -> dict[str, Any]:
    return {
        "pass": pass_number,
        "directory": str(pass_dir),
        "resumed": resumed,
        "current_insert_count_before": source_explode["insert_count_before"],
        "current_exploded_count": source_explode["exploded_count"],
        "current_explode_error_count": len(source_explode["explode_errors"]),
        "reference_insert_count_before": reference_explode["insert_count_before"],
        "reference_exploded_count": reference_explode["exploded_count"],
        "reference_explode_error_count": len(reference_explode["explode_errors"]),
        "reference_prune_removed_count": pruned["removed_count"],
        "dedupe_removed_count": deduped["removed_count"],
        "remaining_insert_count": remaining_insert_count,
        "failed": pass_failed,
    }


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def explode_modelspace_one_level(source: Path, out: Path, manifest_path: Path) -> dict[str, Any]:
    """Explode exactly the INSERT entities present at the start of one pass."""

    doc = load_dxf(source)
    msp = doc.modelspace()
    inserts = [entity for entity in list(msp) if entity.dxftype() == "INSERT"]
    exploded: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entity in inserts:
        handle = str(getattr(entity.dxf, "handle", ""))
        name = str(getattr(entity.dxf, "name", ""))
        layer = str(getattr(entity.dxf, "layer", ""))
        try:
            result = entity.explode(target_layout=msp)
            exploded.append(
                {
                    "handle": handle,
                    "name": name,
                    "layer": layer,
                    "exploded_entity_count": len(result),
                }
            )
        except Exception as exc:
            errors.append({"handle": handle, "name": name, "error": f"{type(exc).__name__}: {exc}"})
    purge_space(msp)
    doc.entitydb.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    output_load_ok = False
    output_error = None
    insert_count_after = None
    try:
        after_doc = load_dxf(out)
        insert_count_after = len(after_doc.modelspace().query("INSERT"))
        output_load_ok = True
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"
    manifest = {
        "stage": "explode_modelspace_one_level",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "insert_count_before": len(inserts),
        "exploded_count": len(exploded),
        "exploded_entity_count": sum(item["exploded_entity_count"] for item in exploded),
        "explode_errors": errors,
        "insert_count_after": insert_count_after,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "failed": not output_load_ok,
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


def modelspace_inventory(doc: Any) -> dict[str, Any]:
    """Return the exact structural fields protected by paper-space cleanup."""

    entities = list(doc.modelspace())
    type_counts = Counter(entity.dxftype() for entity in entities)
    layer_counts = Counter(str(getattr(entity.dxf, "layer", "")) for entity in entities)
    visible_count = sum(1 for entity in entities if is_entity_visible(doc, entity))
    identity_rows = sorted(
        f"{str(getattr(entity.dxf, 'handle', '')).upper()}|{entity.dxftype()}|{str(getattr(entity.dxf, 'layer', ''))}"
        for entity in entities
    )
    identity_digest = hashlib.sha256("\n".join(identity_rows).encode("utf-8")).hexdigest()
    return {
        "entity_count": len(entities),
        "visible_entity_count": visible_count,
        "invisible_entity_count": len(entities) - visible_count,
        "entity_type_counts": dict(type_counts),
        "layer_counts": dict(layer_counts),
        "entity_identity_sha256": identity_digest,
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


def reference_entity_signature(entity: Any, tolerance: float) -> tuple[Any, ...]:
    """Build a handle-independent signature for reference-guided pruning."""

    entity_type = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", ""))
    prefix: tuple[Any, ...] = (layer, entity_type)
    if entity_type in {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}:
        return (*prefix, entity_signature(entity, tolerance=tolerance, scope="geometry"))
    if entity_type == "CIRCLE":
        return (*prefix, quantized_point(entity.dxf.center, tolerance), quantized_number(entity.dxf.radius, tolerance))
    if entity_type == "ELLIPSE":
        return (
            *prefix,
            quantized_point(entity.dxf.center, tolerance),
            quantized_point(entity.dxf.major_axis, tolerance),
            quantized_number(entity.dxf.ratio, 1e-6),
            quantized_number(entity.dxf.start_param, 1e-6),
            quantized_number(entity.dxf.end_param, 1e-6),
        )
    if entity_type == "INSERT":
        return (
            *prefix,
            str(getattr(entity.dxf, "name", "")),
            quantized_point(entity.dxf.insert, tolerance),
            quantized_number(getattr(entity.dxf, "rotation", 0.0), 1e-4),
            quantized_number(getattr(entity.dxf, "xscale", 1.0), 1e-6),
            quantized_number(getattr(entity.dxf, "yscale", 1.0), 1e-6),
            quantized_number(getattr(entity.dxf, "zscale", 1.0), 1e-6),
        )
    if entity_type in TEXT_TYPES:
        insert = getattr(entity.dxf, "insert", (0.0, 0.0, 0.0))
        normalized_text = " ".join(entity_text(entity).split())
        return (*prefix, normalized_text, quantized_point(insert, tolerance))
    if entity_type == "DIMENSION":
        # AutoCAD round-trips can regenerate dimension geometry and alter its
        # bbox while preserving the same block/layer-level annotation payload.
        return prefix
    if entity_type == "HATCH":
        return (
            *prefix,
            str(getattr(entity.dxf, "pattern_name", "")),
            int(getattr(entity.dxf, "solid_fill", 0) or 0),
            quantized_bbox(entity_bbox(entity), tolerance),
        )
    if entity_type == "XLINE":
        return (
            *prefix,
            quantized_point(entity.dxf.start, tolerance),
            quantized_point(entity.dxf.unit_vector, 1e-6),
        )
    return (*prefix, quantized_bbox(entity_bbox(entity), tolerance))


def quantized_number(value: Any, tolerance: float) -> int:
    return int(round(float(value) / tolerance))


def quantized_point(point: Iterable[float], tolerance: float) -> tuple[int, ...]:
    values = tuple(point)
    return tuple(quantized_number(value, tolerance) for value in values[:3])


def quantized_bbox(bounds: list[float] | None, tolerance: float) -> tuple[int, ...] | None:
    if bounds is None:
        return None
    return tuple(quantized_number(value, tolerance) for value in bounds)


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
        "removed_layout_count": stage.get("removed_layout_count"),
        "cleared_kept_paperspace_entity_count": stage.get("cleared_kept_paperspace_entity_count"),
        "kept_paperspace_layout": stage.get("kept_paperspace_layout"),
        "changed_layer_count": stage.get("changed_layer_count"),
        "dedupe_mode": stage.get("dedupe_mode"),
        "signature_scope": stage.get("signature_scope"),
        "near_tolerance": stage.get("near_tolerance"),
        "reference": stage.get("reference"),
        "tolerance": stage.get("tolerance"),
        "removed_reason_counts": stage.get("removed_reason_counts"),
        "removed_block_count": stage.get("removed_block_count"),
        "removed_block_entity_count": stage.get("removed_block_entity_count"),
        "affected_block_count": stage.get("affected_block_count"),
        "completed_passes": stage.get("completed_passes"),
        "stop_reason": stage.get("stop_reason"),
        "final_insert_count": stage.get("final_insert_count"),
        "protection_status": (stage.get("protection") or {}).get("status"),
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
