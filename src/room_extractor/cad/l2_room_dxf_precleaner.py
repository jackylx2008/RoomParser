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
LINEAR_ENTITY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}
DOOR_PROTECTION_TOKEN = "door"

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
DEFAULT_LAYER_POLICY_JSON: Path | None = None
DEFAULT_FINAL_LAYER_POLICY_JSON: Path | None = None
WALL_PRESERVE_LAYER_TOKENS = [
    "WALL",
    "墙",
    "幕墙",
    "FINISH",
    "完成面",
    "DOOR",
    "门",
    "IBS-",
]
WALL_PRESERVE_EXCLUDE_LAYER_TOKENS = [
    "DIM",
    "ANNO",
    "AREA",
    "CEIL",
    "LIGHT",
    "LIGT",
    "LTG",
    "EQUIP",
    "DUCT",
    "风口",
    "喷淋",
    "定位",
    "标注",
    "轴号",
    "编号",
    "文字",
    "TEXT",
    "材质",
    "地面",
    "FLOOR",
    "FL",
    "REFE",
    "GRID",
    "CCTV",
    "电",
    "灯",
    "天花",
    "吊顶",
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
        help=(
            "Continue if a configured INSERT handle is absent or no longer an INSERT. "
            "By default this is treated as a failed replay."
        ),
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
    parser.add_argument(
        "--post-009-cleanup-mode",
        choices=["preserve-door", "reference-guided"],
        default="preserve-door",
        help=(
            "Cleanup path after stage 009. preserve-door is the AutoCAD/manual-validated flow that unlocks layers, "
            "removes non-door HATCH entities, and dedupes non-door linework. reference-guided keeps the older "
            "reference-prune chain. Default: preserve-door."
        ),
    )
    parser.add_argument(
        "--layer-policy-json",
        default=str(DEFAULT_LAYER_POLICY_JSON) if DEFAULT_LAYER_POLICY_JSON else None,
        help=(
            "Optional layer export JSON. When set, every explode step deletes entities and layer records for "
            "layers absent from the JSON, hidden, frozen, or non-plottable in the JSON."
        ),
    )
    parser.add_argument(
        "--final-layer-policy-json",
        default=str(DEFAULT_FINAL_LAYER_POLICY_JSON) if DEFAULT_FINAL_LAYER_POLICY_JSON else None,
        help=(
            "Optional layer export JSON applied after the preserve-door cleanup. "
            "It deletes frozen/non-plottable/absent policy layers while preserving wall, door, and finish layers."
        ),
    )
    parser.add_argument(
        "--skip-xref-cleanup",
        action="store_true",
        help="Skip the final cleanup stage that removes bound/external reference layers and unreachable xref blocks.",
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
    layer_policy_json = getattr(args, "layer_policy_json", None)
    layer_policy = load_layer_policy_json(Path(layer_policy_json)) if layer_policy_json else None
    final_layer_policy_json = getattr(args, "final_layer_policy_json", None)
    final_layer_policy = load_layer_policy_json(Path(final_layer_policy_json)) if final_layer_policy_json else None

    stages: list[dict[str, Any]] = []
    current = source

    stage_dir = out_dir / "001_delete_furniture_layers"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(source, stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_exact_layers(
            source=stage_input,
            out=current,
            layers=set(furniture_layers),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "002_explode_remaining_wall_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stage_input,
            out=current,
            handles=wall_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
            layer_policy=layer_policy,
        )
    )
    wall_baseline = current

    stage_dir = out_dir / "003_explode_remaining_column_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stage_input,
            out=current,
            handles=column_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
            layer_policy=layer_policy,
        )
    )

    stage_dir = out_dir / "004_explode_review_wall_inserts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    review_wall_handles = merge_handles(select_review_wall_insert_handles(stages[-1]["out_path"]), review_wall_handles)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        explode_insert_handles(
            source=stage_input,
            out=current,
            handles=review_wall_handles,
            manifest_path=stage_dir / "manifest.json",
            allow_missing=allow_missing,
            layer_policy=layer_policy,
        )
    )

    stage_dir = out_dir / "005_remove_added_layer0_after_explode"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_added_entities_by_layer(
            baseline=wall_baseline,
            source=stage_input,
            out=current,
            layers=set(DEFAULT_ADDED_LAYER0),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "006_keep_only_added_column_geometry_after_explode"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        delete_added_entities_by_layer(
            baseline=wall_baseline,
            source=stage_input,
            out=current,
            layers=set(DEFAULT_ADDED_NON_COLUMN_LAYERS),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "007_remove_paperspace_layouts"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        remove_paperspace_layouts(
            source=stage_input,
            out=current,
            keep_layout=str(args.keep_layout),
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "008_enable_all_layers"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        enable_all_layers(
            source=stage_input,
            out=current,
            manifest_path=stage_dir / "manifest.json",
        )
    )

    stage_dir = out_dir / "009_dedupe_linework"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
    current = stage_dir / "candidate_after.dxf"
    stages.append(
        dedupe_linework(
            source=stage_input,
            out=current,
            report_path=stage_dir / "duplicate_report.json",
            manifest_path=stage_dir / "manifest.json",
            mode=str(args.dedupe_mode),
            signature_scope=str(args.dedupe_signature_scope),
            exact_tolerance=float(args.exact_tolerance),
            near_tolerance=float(args.near_tolerance),
        )
    )

    post_009_cleanup_mode = str(getattr(args, "post_009_cleanup_mode", "preserve-door"))
    if post_009_cleanup_mode == "preserve-door":
        stage_dir = out_dir / "010_unlock_all_layers_preserve_door"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            unlock_all_layers_preserve_door(
                source=stage_input,
                out=current,
                manifest_path=stage_dir / "manifest.json",
            )
        )

        stage_dir = out_dir / "011_remove_hatches_preserve_door"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            remove_hatches_preserve_door(
                source=stage_input,
                out=current,
                manifest_path=stage_dir / "manifest.json",
            )
        )

        stage_dir = out_dir / "012_dedupe_linework_preserve_door"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            dedupe_linework_preserve_door(
                source=stage_input,
                out=current,
                manifest_path=stage_dir / "manifest.json",
                mode=str(args.dedupe_mode),
                signature_scope=str(args.dedupe_signature_scope),
                exact_tolerance=float(args.exact_tolerance),
                near_tolerance=float(args.near_tolerance),
            )
        )

        if final_layer_policy is not None:
            stage_dir = out_dir / "013_apply_layer_policy_preserve_walls_doors"
            stage_dir.mkdir(parents=True, exist_ok=True)
            stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
            current = stage_dir / "candidate_after.dxf"
            stages.append(
                apply_layer_policy_preserve_walls_doors(
                    source=stage_input,
                    out=current,
                    manifest_path=stage_dir / "manifest.json",
                    layer_policy=final_layer_policy,
                    layer_policy_json=Path(final_layer_policy_json),
                )
            )
    else:
        stage_dir = out_dir / "010_reference_guided_prune"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            reference_guided_prune(
                source=stage_input,
                reference=Path(args.cleanup_reference),
                out=current,
                report_path=stage_dir / "reference_prune_report.json",
                manifest_path=stage_dir / "manifest.json",
                tolerance=float(args.reference_tolerance),
            )
        )

        stage_dir = out_dir / "011_remove_reference_absent_unreachable_blocks"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            remove_reference_absent_unreachable_blocks(
                source=stage_input,
                reference=Path(args.cleanup_reference),
                out=current,
                report_path=stage_dir / "removed_blocks.json",
                manifest_path=stage_dir / "manifest.json",
            )
        )

        stage_dir = out_dir / "012_reference_guided_block_content_prune"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            reference_guided_block_content_prune(
                source=stage_input,
                reference=Path(args.cleanup_reference),
                out=current,
                report_path=stage_dir / "block_content_prune_report.json",
                manifest_path=stage_dir / "manifest.json",
                tolerance=float(args.reference_tolerance),
            )
        )

        stage_dir = out_dir / "013_remove_reference_absent_unreachable_blocks"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            remove_reference_absent_unreachable_blocks(
                source=stage_input,
                reference=Path(args.cleanup_reference),
                out=current,
                report_path=stage_dir / "removed_blocks.json",
                manifest_path=stage_dir / "manifest.json",
            )
        )

        stage_dir = out_dir / "014_iterative_explode_reference_clean"
        stage_dir.mkdir(parents=True, exist_ok=True)
        stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
        current = stage_dir / "candidate_after.dxf"
        stages.append(
            iterative_explode_reference_clean(
                source=stage_input,
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
                layer_policy=layer_policy,
            )
        )

        if not bool(getattr(args, "skip_xref_cleanup", False)):
            stage_dir = out_dir / "015_remove_external_references"
            stage_dir.mkdir(parents=True, exist_ok=True)
            stage_input = copy_stage_input(stages[-1]["out_path"], stage_dir)
            current = stage_dir / "candidate_after.dxf"
            stages.append(
                remove_external_references(
                    source=stage_input,
                    out=current,
                    report_path=stage_dir / "external_references_report.json",
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
        "post_009_cleanup_mode": post_009_cleanup_mode,
        "final_layer_policy_json": str(final_layer_policy_json) if final_layer_policy_json else None,
        "stages": [public_stage_summary(stage) for stage in stages],
        "notes": [
            "Stages 001-009 replay the validated L2 precleaning chain from the source DXF.",
            "The final stage applies the AutoCAD-validated paper-space cleanup rule: retain one empty layout and preserve modelspace.",
            "All layers are enabled and thawed before the validated L2 near-geometry linework dedupe rule is applied.",
            "The default post-009 cleanup is the manually validated preserve-door flow: unlock layers, remove non-door HATCH entities, and dedupe non-door linework.",
            "Door protection is based on case-insensitive 'door' in layer names, block space names, INSERT block names, or text.",
            "When --final-layer-policy-json is set, the final stage removes frozen/non-plottable/absent policy layers while preserving wall, door, and finish layers.",
            "Use --post-009-cleanup-mode reference-guided only to replay the older reference-prune chain.",
            "When --layer-policy-json is set, every explode step deletes layers absent from the policy, hidden, frozen, or non-plottable.",
            "The preceding AutoCAD-only work is the largest-two-block explode that produced the default source.",
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


def unlock_all_layers_preserve_door(source: Path, out: Path, manifest_path: Path) -> dict[str, Any]:
    """Unlock every layer while checking that door-related entities survive unchanged."""

    doc = load_dxf(source)
    before = inspect_door_cleanup_doc(doc, source)
    protected_before = collect_door_protected_handles(doc)
    unlocked: list[str] = []
    for layer in doc.layers:
        if layer.is_locked():
            unlocked.append(str(layer.dxf.name))
            layer.unlock()

    save_doc_for_door_cleanup(doc, out)
    manifest = build_door_cleanup_manifest(
        stage="unlock_all_layers_preserve_door",
        source=source,
        out=out,
        before=before,
        protected_before=protected_before,
        operation={
            "removed_count": 0,
            "unlocked_layer_count": len(unlocked),
            "unlocked_layers": unlocked,
        },
    )
    write_manifest(manifest_path, manifest)
    return manifest


def remove_hatches_preserve_door(source: Path, out: Path, manifest_path: Path) -> dict[str, Any]:
    """Remove HATCH entities except those protected by the door heuristic."""

    doc = load_dxf(source)
    before = inspect_door_cleanup_doc(doc, source)
    protected_before = collect_door_protected_handles(doc)
    removed_by_space: Counter[str] = Counter()
    removed_by_layer: Counter[str] = Counter()
    removed_samples: list[dict[str, Any]] = []
    skipped_door_hatch_count = 0
    skipped_door_hatches: list[dict[str, Any]] = []

    for space_label, space in iter_cleanup_entity_spaces(doc):
        for entity in list(space):
            if not is_live_entity(entity) or entity.dxftype() != "HATCH":
                continue
            if is_door_protected_entity(entity, space_label):
                skipped_door_hatch_count += 1
                if len(skipped_door_hatches) < 100:
                    skipped_door_hatches.append(entity_summary(entity, space_label))
                continue
            layer = str(getattr(entity.dxf, "layer", ""))
            if len(removed_samples) < 1000:
                removed_samples.append(entity_summary(entity, space_label))
            removed_by_space[space_label] += 1
            removed_by_layer[layer] += 1
            entity.destroy()
        purge_space(space)

    save_doc_for_door_cleanup(doc, out)
    manifest = build_door_cleanup_manifest(
        stage="remove_hatches_preserve_door",
        source=source,
        out=out,
        before=before,
        protected_before=protected_before,
        operation={
            "removed_count": sum(removed_by_space.values()),
            "removed_by_space": dict(removed_by_space.most_common()),
            "removed_by_layer": dict(removed_by_layer.most_common()),
            "removed_samples": removed_samples,
            "skipped_door_hatch_count": skipped_door_hatch_count,
            "skipped_door_hatches": skipped_door_hatches,
        },
    )
    write_manifest(manifest_path, manifest)
    return manifest


def dedupe_linework_preserve_door(
    source: Path,
    out: Path,
    manifest_path: Path,
    mode: str = DEFAULT_DEDUPE_MODE,
    signature_scope: str = DEFAULT_DEDUPE_SIGNATURE_SCOPE,
    exact_tolerance: float = DEFAULT_EXACT_TOLERANCE,
    near_tolerance: float = DEFAULT_NEAR_TOLERANCE,
) -> dict[str, Any]:
    """Remove duplicate line-like entities per space, skipping door-protected entities."""

    if mode not in {"exact", "near"}:
        raise ValueError(f"Unsupported dedupe mode: {mode}")
    doc = load_dxf(source)
    before = inspect_door_cleanup_doc(doc, source)
    protected_before = collect_door_protected_handles(doc)
    tolerance = exact_tolerance if mode == "exact" else near_tolerance
    removed_by_space: Counter[str] = Counter()
    removed_by_layer: Counter[str] = Counter()
    removed_by_type: Counter[str] = Counter()
    removed_samples: list[dict[str, Any]] = []
    scanned_linework_count = 0
    skipped_door_linework_count = 0
    skipped_error_count = 0

    for space_label, space in iter_cleanup_entity_spaces(doc):
        seen: set[tuple[Any, ...]] = set()
        for entity in list(space):
            if not is_live_entity(entity) or entity.dxftype() not in LINEAR_ENTITY_TYPES:
                continue
            scanned_linework_count += 1
            if is_door_protected_entity(entity, space_label):
                skipped_door_linework_count += 1
                continue
            try:
                signature = entity_signature(entity, tolerance=tolerance, scope=signature_scope)
            except Exception:
                skipped_error_count += 1
                continue
            key = (space_label, *signature)
            if key not in seen:
                seen.add(key)
                continue
            layer = str(getattr(entity.dxf, "layer", ""))
            if len(removed_samples) < 1000:
                removed_samples.append(entity_summary(entity, space_label))
            removed_by_space[space_label] += 1
            removed_by_layer[layer] += 1
            removed_by_type[entity.dxftype()] += 1
            entity.destroy()
        purge_space(space)

    save_doc_for_door_cleanup(doc, out)
    manifest = build_door_cleanup_manifest(
        stage="dedupe_linework_preserve_door",
        source=source,
        out=out,
        before=before,
        protected_before=protected_before,
        operation={
            "dedupe_mode": mode,
            "signature_scope": signature_scope,
            "exact_tolerance": exact_tolerance,
            "near_tolerance": near_tolerance,
            "scanned_linework_count": scanned_linework_count,
            "skipped_door_linework_count": skipped_door_linework_count,
            "skipped_error_count": skipped_error_count,
            "removed_count": sum(removed_by_space.values()),
            "removed_by_space": dict(removed_by_space.most_common()),
            "removed_by_layer": dict(removed_by_layer.most_common()),
            "removed_by_type": dict(removed_by_type.most_common()),
            "removed_samples": removed_samples,
        },
    )
    write_manifest(manifest_path, manifest)
    return manifest


def apply_layer_policy_preserve_walls_doors(
    source: Path,
    out: Path,
    manifest_path: Path,
    layer_policy: dict[str, Any],
    layer_policy_json: Path | None = None,
) -> dict[str, Any]:
    """Apply final layer cleanup while preserving wall/door/finish layers.

    The source layer JSON may mark some geometry-critical wall layers as frozen
    or non-plottable. This stage removes auxiliary frozen/non-plottable layers
    while keeping those wall/door/finish layers as explicit exceptions.
    """

    doc = load_dxf(source)
    strict_target_layers = collect_disallowed_layers(doc, layer_policy)
    preserve_override_layers = {
        name for name in strict_target_layers if should_preserve_wall_door_layer(name, layer_policy)
    }
    target_layers = strict_target_layers - preserve_override_layers
    strict_before = inspect_disallowed_layers(doc, strict_target_layers)
    before = inspect_disallowed_layers(doc, target_layers)

    removed_entities: list[dict[str, str]] = []
    removed_by_space: Counter[str] = Counter()
    removed_by_layer: Counter[str] = Counter()
    removed_by_type: Counter[str] = Counter()
    destroyed_handles: set[str] = set()

    for space_label, space in iter_cleanup_entity_spaces(doc):
        for entity in list(space):
            if not is_live_entity(entity):
                continue
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in target_layers:
                continue
            handle = str(getattr(entity.dxf, "handle", ""))
            if handle and handle in destroyed_handles:
                continue
            if len(removed_entities) < 1000:
                removed_entities.append(
                    {
                        "space": space_label,
                        "handle": handle,
                        "type": entity.dxftype(),
                        "layer": layer,
                    }
                )
            removed_by_space[space_label] += 1
            removed_by_layer[layer] += 1
            removed_by_type[entity.dxftype()] += 1
            entity.destroy()
            if handle:
                destroyed_handles.add(handle)
        purge_space(space)

    doc.entitydb.purge()
    try:
        doc.objects.purge()
    except Exception:
        pass

    deleted_layer_records: list[str] = []
    failed_layer_records: list[dict[str, str]] = []
    for name in sorted(target_layers):
        if not doc.layers.has_entry(name):
            continue
        try:
            layer = doc.layers.get(name)
            if layer.is_locked():
                layer.unlock()
            doc.layers.remove(name)
            deleted_layer_records.append(name)
        except Exception as exc:
            failed_layer_records.append({"layer": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    try:
        doc.objects.purge()
    except Exception:
        pass
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)

    output_load_ok = False
    output_error = None
    after = None
    strict_after = None
    try:
        after_doc = load_dxf(out)
        after_target_layers = collect_disallowed_layers(after_doc, layer_policy) - preserve_override_layers
        strict_after_target_layers = collect_disallowed_layers(after_doc, layer_policy)
        after = inspect_disallowed_layers(after_doc, after_target_layers)
        strict_after = inspect_disallowed_layers(after_doc, strict_after_target_layers)
        output_load_ok = True
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    protection_status = (
        "passed"
        if output_load_ok
        and not failed_layer_records
        and after is not None
        and after["remaining_entity_count"] == 0
        else "failed"
    )
    manifest = {
        "stage": "apply_layer_policy_preserve_walls_doors",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "layer_policy_json": str(layer_policy_json) if layer_policy_json is not None else None,
        "policy_rule_count": len(layer_policy["rules"]),
        "allowed_layer_count": len(layer_policy["allowed_layers"]),
        "strict_target_layer_count_before": len(strict_target_layers),
        "strict_target_entity_count_before": strict_before["remaining_entity_count"],
        "preserve_override_layer_count": len(preserve_override_layers),
        "preserve_override_layers": sorted(preserve_override_layers),
        "target_layer_count": len(target_layers),
        "target_layer_reasons": dict(count_target_layer_reasons(target_layers, layer_policy)),
        "removed_count": sum(removed_by_space.values()),
        "removed_entity_count": sum(removed_by_space.values()),
        "removed_layer_record_count": len(deleted_layer_records),
        "deleted_layer_records": deleted_layer_records,
        "failed_layer_records": failed_layer_records,
        "removed_by_space": dict(removed_by_space.most_common()),
        "removed_by_layer": dict(removed_by_layer.most_common()),
        "removed_by_type": dict(removed_by_type.most_common()),
        "removed_entities": removed_entities,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "before": before,
        "strict_before": strict_before,
        "after": after,
        "strict_after": strict_after,
        "protection": {
            "status": protection_status,
            "remaining_entity_count_after_exceptions": (after or {}).get("remaining_entity_count"),
            "remaining_layer_record_count_after_exceptions": (after or {}).get("remaining_layer_record_count"),
            "strict_remaining_entity_count_after": (strict_after or {}).get("remaining_entity_count"),
        },
        "failed": protection_status != "passed",
    }
    write_manifest(manifest_path, manifest)
    return manifest


def remove_external_references(
    source: Path,
    out: Path,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Remove bound/external reference layer content and unreachable xref blocks."""

    doc = load_dxf(source)
    before = inspect_doc(doc, source)
    before_modelspace = modelspace_inventory(doc)
    target_layers = {str(layer.dxf.name) for layer in doc.layers if is_external_reference_name(str(layer.dxf.name))}
    target_blocks = {
        str(block.name)
        for block in doc.blocks
        if is_external_reference_name(str(block.name))
        and not is_layout_block_name(str(block.name))
        and not is_anonymous_block_name(str(block.name))
    }
    removed_entities: list[dict[str, str]] = []
    removed_by_space: Counter[str] = Counter()
    removed_by_layer: Counter[str] = Counter()
    removed_by_type: Counter[str] = Counter()
    destroyed_handles: set[str] = set()

    for space_label, space in iter_cleanup_entity_spaces(doc):
        for entity in list(space):
            if not getattr(entity, "is_alive", True):
                continue
            layer = str(getattr(entity.dxf, "layer", ""))
            block_name = str(getattr(entity.dxf, "name", "")) if entity.dxftype() == "INSERT" else ""
            if layer not in target_layers and block_name not in target_blocks:
                continue
            handle = str(getattr(entity.dxf, "handle", ""))
            if handle and handle in destroyed_handles:
                continue
            if len(removed_entities) < 1000:
                removed_entities.append(
                    {
                        "space": space_label,
                        "handle": handle,
                        "type": entity.dxftype(),
                        "layer": layer,
                        "block_name": block_name,
                    }
                )
            removed_by_space[space_label] += 1
            removed_by_layer[layer] += 1
            removed_by_type[entity.dxftype()] += 1
            entity.destroy()
            if handle:
                destroyed_handles.add(handle)
        purge_space(space)

    doc.entitydb.purge()
    reachable = collect_reachable_blocks(doc)
    deleted_blocks: list[dict[str, Any]] = []
    failed_blocks: list[dict[str, str]] = []
    for name in sorted(target_blocks):
        if name in reachable:
            continue
        try:
            block = doc.blocks.get(name)
            deleted_blocks.append({"name": name, "entity_count": len(block)})
            doc.blocks.delete_block(name, safe=False)
        except KeyError:
            continue
        except Exception as exc:
            failed_blocks.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    deleted_layers: list[str] = []
    failed_layers: list[dict[str, str]] = []
    for name in sorted(target_layers):
        if not doc.layers.has_entry(name):
            continue
        try:
            doc.layers.remove(name)
            deleted_layers.append(name)
        except Exception as exc:
            failed_layers.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    doc.objects.purge()
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)

    output_load_ok = False
    output_error = None
    after = None
    after_modelspace = None
    remaining = None
    try:
        after_doc = load_dxf(out)
        after = inspect_doc(after_doc, out)
        after_modelspace = modelspace_inventory(after_doc)
        remaining = inspect_external_reference_residue(after_doc)
        output_load_ok = True
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"

    modelspace_changed_by_removed_count = before_modelspace["entity_count"] - (
        after_modelspace["entity_count"] if after_modelspace else before_modelspace["entity_count"]
    )
    failed = bool(
        not output_load_ok
        or failed_layers
        or failed_blocks
        or (remaining and remaining["entity_count"] != 0)
        or (remaining and remaining["layer_count"] != 0)
    )
    report = {
        "source": str(source),
        "out": str(out),
        "target_layer_count": len(target_layers),
        "target_block_count": len(target_blocks),
        "removed_entity_count": sum(removed_by_space.values()),
        "removed_entity_sample": removed_entities,
        "removed_by_space": dict(removed_by_space.most_common()),
        "removed_by_layer": dict(removed_by_layer.most_common()),
        "removed_by_type": dict(removed_by_type.most_common()),
        "removed_layer_record_count": len(deleted_layers),
        "removed_layer_records": deleted_layers,
        "failed_layer_records": failed_layers,
        "removed_block_count": len(deleted_blocks),
        "removed_blocks": deleted_blocks,
        "failed_blocks": failed_blocks,
        "remaining": remaining,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "stage": "remove_external_references",
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "report": str(report_path),
        "removed_count": sum(removed_by_space.values()) + len(deleted_layers) + len(deleted_blocks),
        "removed_entity_count": sum(removed_by_space.values()),
        "removed_layer_record_count": len(deleted_layers),
        "removed_block_count": len(deleted_blocks),
        "target_layer_count": len(target_layers),
        "target_block_count": len(target_blocks),
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "protection": {
            "status": "passed" if not failed else "failed",
            "modelspace_entity_delta": modelspace_changed_by_removed_count,
            "remaining_external_reference_entity_count": (remaining or {}).get("entity_count"),
            "remaining_external_reference_layer_count": (remaining or {}).get("layer_count"),
        },
        "failed": failed,
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


def is_external_reference_name(name: str) -> bool:
    upper = name.upper()
    return "$0$" in upper or "XREF" in upper


def inspect_external_reference_residue(doc: Any) -> dict[str, Any]:
    layers = sorted(str(layer.dxf.name) for layer in doc.layers if is_external_reference_name(str(layer.dxf.name)))
    blocks = sorted(
        str(block.name)
        for block in doc.blocks
        if is_external_reference_name(str(block.name))
        and not is_layout_block_name(str(block.name))
        and not is_anonymous_block_name(str(block.name))
    )
    entity_count = 0
    entity_by_layer: Counter[str] = Counter()
    entity_by_type: Counter[str] = Counter()
    insert_by_block: Counter[str] = Counter()
    layer_set = set(layers)
    block_set = set(blocks)
    for _, space in iter_cleanup_entity_spaces(doc):
        for entity in space:
            layer = str(getattr(entity.dxf, "layer", ""))
            name = str(getattr(entity.dxf, "name", "")) if entity.dxftype() == "INSERT" else ""
            if layer not in layer_set and name not in block_set:
                continue
            entity_count += 1
            entity_by_layer[layer] += 1
            entity_by_type[entity.dxftype()] += 1
            if name:
                insert_by_block[name] += 1
    return {
        "layer_count": len(layers),
        "layers": layers,
        "block_count": len(blocks),
        "blocks": blocks,
        "entity_count": entity_count,
        "entity_by_layer": dict(entity_by_layer.most_common()),
        "entity_by_type": dict(entity_by_type.most_common()),
        "insert_by_block": dict(insert_by_block.most_common()),
    }


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
    layer_policy: dict[str, Any] | None = None,
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
            layer_policy=layer_policy,
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
            "layer_policy_applied_to_current_after_explode": layer_policy is not None,
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
        "current_layer_policy_removed_entity_count": (
            source_explode.get("layer_policy_cleanup") or {}
        ).get("removed_entity_count"),
        "current_layer_policy_removed_layer_record_count": (
            source_explode.get("layer_policy_cleanup") or {}
        ).get("removed_layer_record_count"),
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


def load_layer_policy_json(path: Path) -> dict[str, Any]:
    payload = read_json_file(path)
    layer_rules: dict[str, dict[str, Any]] = {}
    allowed_layers: set[str] = set()
    for item in payload.get("图层", []):
        name = str(item.get("图层名称", ""))
        if not name:
            continue
        visible = bool(item.get("显示"))
        frozen = bool(item.get("冻结"))
        plottable = bool(item.get("打印", True))
        rule = {
            "name": name,
            "visible": visible,
            "frozen": frozen,
            "plottable": plottable,
            "locked": bool(item.get("锁定")),
            "allowed": bool(visible and not frozen and plottable),
        }
        layer_rules[name] = rule
        if rule["allowed"]:
            allowed_layers.add(name)
    return {
        "path": str(path),
        "drawing_name": payload.get("图纸名称"),
        "layer_count": len(layer_rules),
        "allowed_layer_count": len(allowed_layers),
        "excluded_layer_count": len(layer_rules) - len(allowed_layers),
        "rules": layer_rules,
        "allowed_layers": allowed_layers,
    }


def apply_layer_policy_cleanup(doc: Any, layer_policy: dict[str, Any]) -> dict[str, Any]:
    target_layers = collect_disallowed_layers(doc, layer_policy)
    before = inspect_disallowed_layers(doc, target_layers)
    removed_entities: list[dict[str, str]] = []
    removed_by_space: Counter[str] = Counter()
    removed_by_layer: Counter[str] = Counter()
    removed_by_type: Counter[str] = Counter()
    destroyed_handles: set[str] = set()

    for space_label, space in iter_cleanup_entity_spaces(doc):
        for entity in list(space):
            if not getattr(entity, "is_alive", True):
                continue
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in target_layers:
                continue
            handle = str(getattr(entity.dxf, "handle", ""))
            if handle and handle in destroyed_handles:
                continue
            if len(removed_entities) < 1000:
                removed_entities.append(
                    {
                        "space": space_label,
                        "handle": handle,
                        "type": entity.dxftype(),
                        "layer": layer,
                    }
                )
            removed_by_space[space_label] += 1
            removed_by_layer[layer] += 1
            removed_by_type[entity.dxftype()] += 1
            entity.destroy()
            if handle:
                destroyed_handles.add(handle)
        purge_space(space)

    doc.entitydb.purge()
    deleted_layer_records: list[str] = []
    failed_layer_records: list[dict[str, str]] = []
    for name in sorted(target_layers):
        if not doc.layers.has_entry(name):
            continue
        try:
            doc.layers.remove(name)
            deleted_layer_records.append(name)
        except Exception as exc:
            failed_layer_records.append({"layer": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    doc.objects.purge()
    after = inspect_disallowed_layers(doc, target_layers)
    failed = bool(
        failed_layer_records
        or after["remaining_entity_count"] != 0
        or after["remaining_layer_record_count"] != 0
    )
    return {
        "policy_path": layer_policy.get("path"),
        "policy_layer_count": layer_policy.get("layer_count"),
        "allowed_layer_count": layer_policy.get("allowed_layer_count"),
        "target_layer_count": len(target_layers),
        "target_reason_counts": dict(count_target_layer_reasons(target_layers, layer_policy).most_common()),
        "removed_entity_count": sum(removed_by_space.values()),
        "removed_entity_sample": removed_entities,
        "removed_by_space": dict(removed_by_space.most_common()),
        "removed_by_layer": dict(removed_by_layer.most_common()),
        "removed_by_type": dict(removed_by_type.most_common()),
        "removed_layer_record_count": len(deleted_layer_records),
        "removed_layer_records": deleted_layer_records,
        "failed_layer_records": failed_layer_records,
        "before": before,
        "after": after,
        "failed": failed,
    }


def collect_disallowed_layers(doc: Any, layer_policy: dict[str, Any]) -> set[str]:
    present_layers = {str(layer.dxf.name) for layer in doc.layers}
    for _, space in iter_cleanup_entity_spaces(doc):
        for entity in space:
            present_layers.add(str(getattr(entity.dxf, "layer", "")))
    allowed_layers = layer_policy["allowed_layers"]
    return {name for name in present_layers if name and name not in allowed_layers}


def count_target_layer_reasons(target_layers: set[str], layer_policy: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for name in target_layers:
        for reason in disallowed_layer_reasons(name, layer_policy):
            counts[reason] += 1
    return counts


def disallowed_layer_reasons(name: str, layer_policy: dict[str, Any]) -> list[str]:
    rule = layer_policy["rules"].get(name)
    if rule is None:
        return ["absent_from_policy"]
    reasons: list[str] = []
    if not rule["visible"]:
        reasons.append("hidden_in_policy")
    if rule["frozen"]:
        reasons.append("frozen_in_policy")
    if not rule["plottable"]:
        reasons.append("non_plottable_in_policy")
    return reasons or ["allowed_in_policy"]


def inspect_disallowed_layers(doc: Any, target_layers: set[str]) -> dict[str, Any]:
    entity_counts_by_space: dict[str, dict[str, int]] = {}
    entity_counts_by_layer: Counter[str] = Counter()
    entity_counts_by_type: Counter[str] = Counter()
    for space_label, space in iter_cleanup_entity_spaces(doc):
        counts: Counter[str] = Counter()
        for entity in space:
            layer = str(getattr(entity.dxf, "layer", ""))
            if layer not in target_layers:
                continue
            counts[layer] += 1
            entity_counts_by_layer[layer] += 1
            entity_counts_by_type[entity.dxftype()] += 1
        if counts:
            entity_counts_by_space[space_label] = dict(counts.most_common())
    remaining_layer_records = sorted(name for name in target_layers if doc.layers.has_entry(name))
    return {
        "remaining_entity_count": sum(entity_counts_by_layer.values()),
        "remaining_layer_record_count": len(remaining_layer_records),
        "remaining_layer_records": remaining_layer_records,
        "entity_counts_by_space": entity_counts_by_space,
        "entity_counts_by_layer": dict(entity_counts_by_layer.most_common()),
        "entity_counts_by_type": dict(entity_counts_by_type.most_common()),
    }


def iter_cleanup_entity_spaces(doc: Any) -> Iterable[tuple[str, Any]]:
    yield "modelspace", doc.modelspace()
    for layout in doc.layouts:
        if str(layout.name).lower() != "model":
            yield f"layout:{layout.name}", layout
    for block in doc.blocks:
        name = str(block.name)
        if is_layout_block_name(name):
            continue
        yield f"block:{name}", block


def explode_modelspace_one_level(
    source: Path,
    out: Path,
    manifest_path: Path,
    layer_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    layer_policy_cleanup = apply_layer_policy_cleanup(doc, layer_policy) if layer_policy is not None else None
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
    failed = bool(not output_load_ok or (layer_policy_cleanup and layer_policy_cleanup["failed"]))
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
        "layer_policy_cleanup": layer_policy_cleanup,
        "failed": failed,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def explode_insert_handles(
    source: Path,
    out: Path,
    handles: list[str],
    manifest_path: Path,
    allow_missing: bool = False,
    layer_policy: dict[str, Any] | None = None,
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
    layer_policy_cleanup = apply_layer_policy_cleanup(doc, layer_policy) if layer_policy is not None else None
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
    failed = bool(
        ((wrong_type or missing) and not allow_missing)
        or not output_load_ok
        or (layer_policy_cleanup and layer_policy_cleanup["failed"])
    )
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
        "layer_policy_cleanup": layer_policy_cleanup,
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


def inspect_door_cleanup_doc(doc: Any, path: Path) -> dict[str, Any]:
    entity_types: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    locked_layers: list[str] = []
    door_layers: list[str] = []
    hatch_count = 0
    linework_count = 0
    for layer in doc.layers:
        name = str(layer.dxf.name)
        if layer.is_locked():
            locked_layers.append(name)
        if contains_door_token(name):
            door_layers.append(name)
    for _, space in iter_cleanup_entity_spaces(doc):
        for entity in space:
            if not is_live_entity(entity):
                continue
            entity_type = entity.dxftype()
            entity_types[entity_type] += 1
            layer_counts[str(getattr(entity.dxf, "layer", ""))] += 1
            if entity_type == "HATCH":
                hatch_count += 1
            if entity_type in LINEAR_ENTITY_TYPES:
                linework_count += 1
    return {
        "file_size": path.stat().st_size if path.exists() else None,
        "layer_count": len(doc.layers),
        "layout_count": len(doc.layouts),
        "block_count": len(doc.blocks),
        "locked_layer_count": len(locked_layers),
        "locked_layers_sample": sorted(locked_layers)[:100],
        "door_layer_count": len(door_layers),
        "door_layers": sorted(door_layers),
        "hatch_count": hatch_count,
        "linework_count": linework_count,
        "entity_type_counts_top": dict(entity_types.most_common(30)),
        "layer_counts_top": dict(layer_counts.most_common(30)),
    }


def collect_door_protected_handles(doc: Any) -> dict[str, Any]:
    handles: set[str] = set()
    by_space: Counter[str] = Counter()
    by_layer: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    for space_label, space in iter_cleanup_entity_spaces(doc):
        for entity in space:
            if not is_live_entity(entity) or not is_door_protected_entity(entity, space_label):
                continue
            handle = str(getattr(entity.dxf, "handle", ""))
            if handle:
                handles.add(handle)
            by_space[space_label] += 1
            by_layer[str(getattr(entity.dxf, "layer", ""))] += 1
            by_type[entity.dxftype()] += 1
    return {
        "handles": handles,
        "summary": {
            "entity_count": sum(by_space.values()),
            "handle_count": len(handles),
            "by_space_top": dict(by_space.most_common(50)),
            "by_layer_top": dict(by_layer.most_common(50)),
            "by_type_top": dict(by_type.most_common()),
        },
    }


def build_door_cleanup_manifest(
    stage: str,
    source: Path,
    out: Path,
    before: dict[str, Any],
    protected_before: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any]:
    output_load_ok = False
    output_error = None
    after = None
    door_protection: dict[str, Any]
    try:
        after_doc = load_dxf(out)
        after = inspect_door_cleanup_doc(after_doc, out)
        protected_after = collect_door_protected_handles(after_doc)
        missing_handles = sorted(protected_before["handles"] - protected_after["handles"])
        output_load_ok = True
        door_protection = {
            "status": "passed" if not missing_handles else "failed",
            "before_handle_count": len(protected_before["handles"]),
            "after_handle_count": len(protected_after["handles"]),
            "missing_handle_count": len(missing_handles),
            "missing_handles_sample": missing_handles[:100],
            "before": protected_before["summary"],
            "after": protected_after["summary"],
        }
    except Exception as exc:  # pragma: no cover - defensive manifest field
        output_error = f"{type(exc).__name__}: {exc}"
        door_protection = {
            "status": "failed",
            "before_handle_count": len(protected_before["handles"]),
            "after_handle_count": None,
            "missing_handle_count": None,
            "missing_handles_sample": [],
            "before": protected_before["summary"],
            "after": None,
        }
    manifest = {
        "stage": stage,
        "source": str(source),
        "out": str(out),
        "out_path": out,
        "file_size_before": source.stat().st_size,
        "file_size_after": out.stat().st_size if out.exists() else None,
        "output_load_ok": output_load_ok,
        "output_error": output_error,
        "before": before,
        "after": after,
        "protection": door_protection,
        "door_protection": door_protection,
        **operation,
    }
    manifest["failed"] = bool(not output_load_ok or door_protection["status"] != "passed")
    return manifest


def save_doc_for_door_cleanup(doc: Any, out: Path) -> None:
    for _, space in iter_cleanup_entity_spaces(doc):
        purge_space(space)
    doc.entitydb.purge()
    try:
        doc.objects.purge()
    except Exception:
        pass
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)


def is_door_protected_entity(entity: Any, space_label: str) -> bool:
    if contains_door_token(space_label):
        return True
    if contains_door_token(str(getattr(entity.dxf, "layer", ""))):
        return True
    if entity.dxftype() == "INSERT" and contains_door_token(str(getattr(entity.dxf, "name", ""))):
        return True
    if entity.dxftype() in TEXT_TYPES and contains_door_token(entity_text(entity)):
        return True
    return False


def should_preserve_wall_door_layer(name: str, layer_policy: dict[str, Any]) -> bool:
    rule = layer_policy["rules"].get(name)
    if rule is None or not rule.get("visible", False):
        return False
    upper_name = str(name).upper()
    excluded = any(token.upper() in upper_name for token in WALL_PRESERVE_EXCLUDE_LAYER_TOKENS)
    if excluded and "DOOR" not in upper_name and "门" not in str(name):
        return False
    return any(token.upper() in upper_name for token in WALL_PRESERVE_LAYER_TOKENS)


def contains_door_token(value: str) -> bool:
    return DOOR_PROTECTION_TOKEN in str(value).casefold()


def is_live_entity(entity: Any) -> bool:
    return bool(getattr(entity, "is_alive", True))


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


def copy_stage_input(source: Path, stage_dir: Path) -> Path:
    stage_input = stage_dir / "input.dxf"
    if source.resolve() != stage_input.resolve():
        shutil.copy2(source, stage_input)
    return stage_input


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
        "removed_entity_count": stage.get("removed_entity_count"),
        "removed_layer_record_count": stage.get("removed_layer_record_count"),
        "target_layer_count": stage.get("target_layer_count"),
        "strict_target_layer_count_before": stage.get("strict_target_layer_count_before"),
        "strict_target_entity_count_before": stage.get("strict_target_entity_count_before"),
        "preserve_override_layer_count": stage.get("preserve_override_layer_count"),
        "target_block_count": stage.get("target_block_count"),
        "affected_block_count": stage.get("affected_block_count"),
        "completed_passes": stage.get("completed_passes"),
        "stop_reason": stage.get("stop_reason"),
        "final_insert_count": stage.get("final_insert_count"),
        "protection_status": (stage.get("protection") or {}).get("status"),
        "door_missing_handle_count": (stage.get("door_protection") or stage.get("protection") or {}).get(
            "missing_handle_count"
        ),
        "door_before_entity_count": (
            (stage.get("door_protection") or stage.get("protection") or {}).get("before") or {}
        ).get("entity_count"),
        "door_after_entity_count": (
            (stage.get("door_protection") or stage.get("protection") or {}).get("after") or {}
        ).get("entity_count"),
        "layer_policy_removed_entity_count": (stage.get("layer_policy_cleanup") or {}).get("removed_entity_count"),
        "layer_policy_removed_layer_record_count": (stage.get("layer_policy_cleanup") or {}).get(
            "removed_layer_record_count"
        ),
        "layer_policy_target_layer_count": (stage.get("layer_policy_cleanup") or {}).get("target_layer_count"),
        "remaining_entity_count_after_exceptions": (stage.get("protection") or {}).get(
            "remaining_entity_count_after_exceptions"
        ),
        "strict_remaining_entity_count_after": (stage.get("protection") or {}).get(
            "strict_remaining_entity_count_after"
        ),
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
