"""Auditable pre-explode DXF cleaning experiment.

This experiment targets the stage before AutoCAD EXPLODE turns hidden block
content into large linework. It audits layer/block visibility and creates a
conservative candidate that removes only invisible modelspace entities while
protecting room names and room numbers.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


_ensure_src_on_path()

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.dxf_loader import load_dxf
from room_extractor.cad.dxf_self_cleaner import (
    analyze_dxf,
    build_ai_placeholder,
    compare_pngs,
    compute_shared_render_bbox,
    collect_reachable_blocks,
    entity_block_references,
    html_page,
    now_iso,
    protection_html,
    render_dxf_png,
    scan_dxf_sections,
    write_comparison_png,
    write_diff_png,
    write_json,
    write_rollback_script,
)
from room_extractor.cad.entity_filter import is_entity_visible
from room_extractor.extraction.room_text_parser import extract_room_name, extract_room_number


DEFAULT_SOURCE = Path("data/input/dxf/L2_20.00m平面图.dxf")
DEFAULT_EXPLODED_REFERENCE = Path("data/input/dxf_exploded/L2_20.00m平面图.dxf")
DEFAULT_OUT_DIR = Path("log/dxf_pre_explode_clean_experiment")
ROOM_BOUNDARY_LAYER_KEYWORDS = ("0-面积线", "WALL", "Defpoints")
ROOM_OPENING_LAYER_KEYWORDS = (
    "DOOR",
    "ÃÅ",
    "门",
    "HOLE",
    "OPENING",
    "A-HOLE",
)
ROOM_TEXT_ENTITY_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and validate conservative DXF cleanup before block explosion. "
            "The first candidate removes invisible non-room modelspace entities."
        )
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Pre-explode source DXF.")
    parser.add_argument(
        "--exploded-reference",
        default=str(DEFAULT_EXPLODED_REFERENCE),
        help="Optional already-exploded DXF used only for file/section comparison.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Experiment output directory.")
    parser.add_argument("--resume", help="Resume an existing experiment directory.")
    parser.add_argument("--max-steps", type=int, default=1, help="Maximum candidate steps to run. Default: 1.")
    parser.add_argument("--analyze-only", action="store_true", help="Only write baseline audit; do not create candidates.")
    parser.add_argument("--rollback-to", type=int, help="Restore current.dxf to an accepted rollback point.")
    parser.add_argument("--mark-step-accepted", type=int, help="Accept an existing needs_manual_review step.")
    parser.add_argument("--accept-reason", default="", help="Reason recorded with --mark-step-accepted.")
    parser.add_argument("--mark-step-rejected", type=int, help="Reject an existing needs_manual_review step.")
    parser.add_argument("--reject-reason", default="", help="Reason recorded with --mark-step-rejected.")
    parser.add_argument("--render-images", action="store_true", help="Render before/after/diff PNG files for candidate steps.")
    parser.add_argument("--dry-run-ai", action="store_true", help="Reserve AI check output without calling local AI.")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI validation fields entirely.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.resume:
        out_dir = Path(args.resume)
        manifest = load_manifest(out_dir)
        source = Path(manifest["source"])
        exploded_reference = Path(manifest["exploded_reference"]) if manifest.get("exploded_reference") else None
    else:
        out_dir = Path(args.out_dir)
        source = Path(args.source)
        exploded_reference = Path(args.exploded_reference) if args.exploded_reference else None
        manifest = None

    if args.rollback_to is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        rollback_to_step(out_dir, manifest, int(args.rollback_to))
        return 0
    if args.mark_step_accepted is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        mark_step_accepted(out_dir, manifest, int(args.mark_step_accepted), str(args.accept_reason))
        return 0
    if args.mark_step_rejected is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        mark_step_rejected(out_dir, manifest, int(args.mark_step_rejected), str(args.reject_reason))
        return 0

    run_experiment(
        source=source,
        exploded_reference=exploded_reference,
        out_dir=out_dir,
        max_steps=max(0, int(args.max_steps)),
        analyze_only=bool(args.analyze_only),
        render_images=bool(args.render_images),
        dry_run_ai=bool(args.dry_run_ai),
        skip_ai=bool(args.skip_ai),
        manifest=manifest,
    )
    return 0


def run_experiment(
    source: Path,
    exploded_reference: Path | None,
    out_dir: Path,
    max_steps: int,
    analyze_only: bool,
    render_images: bool,
    dry_run_ai: bool,
    skip_ai: bool,
    manifest: dict[str, Any] | None = None,
) -> None:
    source = source.resolve()
    out_dir = out_dir.resolve()
    validate_dxf(source, "source")
    if exploded_reference is not None:
        exploded_reference = exploded_reference.resolve()
        if not exploded_reference.exists():
            exploded_reference = None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "steps").mkdir(exist_ok=True)
    (out_dir / "rollback").mkdir(exist_ok=True)
    if manifest is None:
        manifest_path = out_dir / "manifest.json"
        manifest = load_manifest(out_dir) if manifest_path.exists() else new_manifest(source, exploded_reference, out_dir)

    ensure_baseline(source, exploded_reference, out_dir, manifest)
    if analyze_only or max_steps == 0:
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        return

    steps_remaining = max_steps
    while steps_remaining > 0:
        if has_pending_manual_review(manifest):
            break
        next_step = next_step_number(manifest)
        if next_step == 1:
            step = run_invisible_non_room_modelspace_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_step == 2:
            step = run_unreachable_blocks_after_visibility_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                protect_room_text_blocks=False,
            )
        elif next_step == 3:
            step = run_unreachable_blocks_after_visibility_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                protect_room_text_blocks=True,
            )
        elif next_step == 4:
            step = run_room_focused_visible_prune_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                protect_opening_layers=False,
            )
        elif next_step == 5:
            step = run_room_focused_visible_prune_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                protect_opening_layers=True,
            )
        elif next_step == 6:
            step = run_remove_paperspace_layouts_and_blocks_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                clear_kept_layout=True,
            )
        elif next_step == 7:
            step = run_remove_paperspace_layouts_and_blocks_step(
                current_path=Path(manifest["current_dxf"]),
                out_dir=out_dir,
                step_number=next_step,
                render_images=render_images,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                clear_kept_layout=False,
            )
        else:
            break
        manifest["steps"].append(step)
        if step["status"] == "accepted":
            manifest["current_step"] = step["step"]
            manifest["current_dxf"] = step["accepted_after_dxf"]
            manifest["rollback_points"].append(
                {"step": step["step"], "label": step["title"], "path": step["accepted_after_dxf"]}
            )
        else:
            manifest["review_candidates"].append(
                {
                    "step": step["step"],
                    "name": step["name"],
                    "status": step["status"],
                    "candidate_after_dxf": step["candidate_after_dxf"],
                    "report_html": step["report_html"],
                }
            )
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        steps_remaining -= 1


def validate_dxf(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} DXF not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} DXF path is not a file: {path}")
    if path.suffix.lower() != ".dxf":
        raise ValueError(f"{label} path must be a .dxf file: {path}")


def new_manifest(source: Path, exploded_reference: Path | None, out_dir: Path) -> dict[str, Any]:
    current_path = out_dir / "current.dxf"
    shutil.copy2(source, current_path)
    return {
        "version": 1,
        "workflow": "pre_explode_dxf_cleaning_experiment",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": str(source),
        "exploded_reference": str(exploded_reference) if exploded_reference else None,
        "out_dir": str(out_dir),
        "current_step": 0,
        "current_dxf": str(current_path),
        "steps": [],
        "rollback_points": [{"step": 0, "label": "original pre-explode source", "path": str(source)}],
        "review_candidates": [],
        "notes": [
            "AutoCAD visual visibility is approximated by layer off/frozen state and entity invisible flag.",
            "Room-name and room-number text is protected even if it is on an invisible layer.",
        ],
    }


def ensure_baseline(
    source: Path,
    exploded_reference: Path | None,
    out_dir: Path,
    manifest: dict[str, Any],
) -> None:
    if any(step.get("name") == "baseline" for step in manifest.get("steps", [])):
        return
    step_dir = out_dir / "steps" / "000_baseline"
    step_dir.mkdir(parents=True, exist_ok=True)
    source_audit = analyze_pre_explode_dxf(source)
    exploded_audit = analyze_exploded_reference(exploded_reference) if exploded_reference else None
    source_audit_path = step_dir / "source_pre_explode_audit.json"
    exploded_audit_path = step_dir / "exploded_reference_audit.json"
    report_path = step_dir / "report.html"
    write_json(source_audit_path, source_audit)
    if exploded_audit:
        write_json(exploded_audit_path, exploded_audit)
    report_path.write_text(build_baseline_html(source_audit, exploded_audit), encoding="utf-8")
    manifest["steps"].append(
        {
            "step": 0,
            "name": "baseline",
            "title": "Pre-explode source audit",
            "status": "completed",
            "step_dir": str(step_dir),
            "source_audit": str(source_audit_path),
            "exploded_reference_audit": str(exploded_audit_path) if exploded_audit else None,
            "report_html": str(report_path),
            "created_at": now_iso(),
        }
    )


def analyze_exploded_reference(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return {
        "path": str(path),
        "created_at": now_iso(),
        "file": {"size_bytes": path.stat().st_size, "size_mb": round(path.stat().st_size / 1024 / 1024, 3)},
        "sections": scan_dxf_sections(path),
        "notes": "This audit intentionally avoids full ezdxf loading for the large exploded reference.",
    }


def analyze_pre_explode_dxf(path: Path) -> dict[str, Any]:
    base = analyze_dxf(path)
    doc = load_dxf(path)
    layer_audit = analyze_layers(doc)
    room_text = analyze_room_text(doc)
    insert_audit = analyze_modelspace_inserts(doc)
    block_audit = analyze_blocks(doc, insert_audit)
    boundary_audit = analyze_room_boundary_layers(doc)
    opening_audit = analyze_room_opening_layers(doc)
    cleanup_candidates = summarize_cleanup_candidates(doc, insert_audit)
    return {
        **base,
        "pre_explode": {
            "layers": layer_audit,
            "room_text": room_text,
            "modelspace_inserts": insert_audit,
            "blocks": block_audit,
            "room_boundary_layers": boundary_audit,
            "room_opening_layers": opening_audit,
            "cleanup_candidates": cleanup_candidates,
        },
    }


def analyze_layers(doc: DxfDrawing) -> dict[str, Any]:
    layers = []
    off_count = 0
    frozen_count = 0
    for layer in doc.layers:
        name = str(layer.dxf.name)
        is_off = bool(layer.is_off())
        is_frozen = bool(layer.is_frozen())
        off_count += int(is_off)
        frozen_count += int(is_frozen)
        layers.append(
            {
                "name": name,
                "is_off": is_off,
                "is_frozen": is_frozen,
                "is_room_boundary_candidate": is_room_boundary_layer(name),
            }
        )
    return {
        "layer_count": len(layers),
        "off_layer_count": off_count,
        "frozen_layer_count": frozen_count,
        "room_boundary_candidate_layers": [item for item in layers if item["is_room_boundary_candidate"]],
        "off_or_frozen_layers_sample": [item for item in layers if item["is_off"] or item["is_frozen"]][:200],
    }


def analyze_room_text(doc: DxfDrawing) -> dict[str, Any]:
    all_items = collect_room_text_items(doc, visible_only=False)
    visible_items = [item for item in all_items if item["visible"]]
    hidden_items = [item for item in all_items if not item["visible"]]
    return {
        "room_text_count": len(all_items),
        "visible_room_text_count": len(visible_items),
        "hidden_room_text_count": len(hidden_items),
        "room_number_count": sum(1 for item in all_items if item.get("room_number")),
        "room_name_count": sum(1 for item in all_items if item.get("room_name")),
        "visible_room_number_count": sum(1 for item in visible_items if item.get("room_number")),
        "visible_room_name_count": sum(1 for item in visible_items if item.get("room_name")),
        "hidden_room_text_sample": hidden_items[:200],
        "visible_room_text_sample": visible_items[:200],
    }


def collect_room_text_items(doc: DxfDrawing, visible_only: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entity in doc.modelspace():
        if entity.dxftype() not in ROOM_TEXT_ENTITY_TYPES:
            continue
        visible = is_entity_visible(doc, entity)
        if visible_only and not visible:
            continue
        text = entity_text(entity)
        parsed = parse_room_text(text)
        if not parsed:
            continue
        items.append(
            {
                "handle": str(getattr(entity.dxf, "handle", "")),
                "entity_type": entity.dxftype(),
                "layer": str(getattr(entity.dxf, "layer", "")),
                "visible": visible,
                "text": text,
                **parsed,
            }
        )
    return items


def analyze_modelspace_inserts(doc: DxfDrawing) -> dict[str, Any]:
    payload_cache: dict[str, dict[str, Any]] = {}
    block_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    hidden_layer_counts: Counter[str] = Counter()
    visible_payload: Counter[str] = Counter()
    hidden_payload: Counter[str] = Counter()
    hidden_insert_samples: list[dict[str, Any]] = []
    risky_hidden_insert_samples: list[dict[str, Any]] = []
    visible_count = 0
    hidden_count = 0
    for entity in doc.modelspace():
        if entity.dxftype() != "INSERT":
            continue
        block_name = str(entity.dxf.name)
        layer = str(getattr(entity.dxf, "layer", "0"))
        visible = is_entity_visible(doc, entity)
        payload = estimate_block_payload(doc, block_name, payload_cache)
        block_counts[block_name] += 1
        layer_counts[layer] += 1
        if visible:
            visible_count += 1
            visible_payload.update(payload["entity_type_counts"])
        else:
            hidden_count += 1
            hidden_layer_counts[layer] += 1
            hidden_payload.update(payload["entity_type_counts"])
            sample = {
                "handle": str(getattr(entity.dxf, "handle", "")),
                "block_name": block_name,
                "layer": layer,
                "estimated_payload_entity_count": payload["estimated_entity_count"],
                "payload_type_counts": payload["entity_type_counts"],
                "contains_room_text": payload["room_text_count"] > 0,
                "room_text_sample": payload["room_text_sample"],
            }
            hidden_insert_samples.append(sample)
            if payload["room_text_count"] > 0:
                risky_hidden_insert_samples.append(sample)
    return {
        "insert_count": visible_count + hidden_count,
        "visible_insert_count": visible_count,
        "hidden_insert_count": hidden_count,
        "insert_block_counts_top": dict(block_counts.most_common(50)),
        "insert_layer_counts_top": dict(layer_counts.most_common(50)),
        "hidden_insert_layer_counts_top": dict(hidden_layer_counts.most_common(50)),
        "estimated_visible_explode_payload_type_counts": dict(visible_payload.most_common()),
        "estimated_hidden_explode_payload_type_counts": dict(hidden_payload.most_common()),
        "hidden_insert_samples": hidden_insert_samples[:300],
        "risky_hidden_insert_samples": risky_hidden_insert_samples[:200],
    }


def analyze_blocks(doc: DxfDrawing, insert_audit: dict[str, Any]) -> dict[str, Any]:
    payload_cache: dict[str, dict[str, Any]] = {}
    referenced_blocks = set(insert_audit.get("insert_block_counts_top", {}).keys())
    heavy_blocks = []
    room_text_blocks = []
    for block in doc.blocks:
        name = str(block.name)
        payload = estimate_block_payload(doc, name, payload_cache)
        item = {
            "name": name,
            "direct_entity_count": len(block),
            "estimated_recursive_entity_count": payload["estimated_entity_count"],
            "entity_type_counts": payload["entity_type_counts"],
            "contains_room_text": payload["room_text_count"] > 0,
            "is_referenced_by_modelspace_insert": name in referenced_blocks,
        }
        if payload["estimated_entity_count"] > 100:
            heavy_blocks.append(item)
        if payload["room_text_count"] > 0:
            room_text_blocks.append({**item, "room_text_sample": payload["room_text_sample"]})
    heavy_blocks.sort(key=lambda item: int(item["estimated_recursive_entity_count"]), reverse=True)
    return {
        "block_count": len(doc.blocks),
        "heavy_blocks_top": heavy_blocks[:100],
        "room_text_blocks": room_text_blocks[:100],
    }


def analyze_room_boundary_layers(doc: DxfDrawing) -> dict[str, Any]:
    return analyze_keyword_layers(doc, is_room_boundary_layer)


def analyze_room_opening_layers(doc: DxfDrawing) -> dict[str, Any]:
    return analyze_keyword_layers(doc, is_room_opening_layer)


def analyze_keyword_layers(doc: DxfDrawing, predicate: Any) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    visible_type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    visible_layer_counts: Counter[str] = Counter()
    for entity in doc.modelspace():
        layer = str(getattr(entity.dxf, "layer", "0"))
        if not predicate(layer):
            continue
        entity_type = entity.dxftype()
        type_counts[entity_type] += 1
        layer_counts[layer] += 1
        if is_entity_visible(doc, entity):
            visible_type_counts[entity_type] += 1
            visible_layer_counts[layer] += 1
    return {
        "entity_type_counts": dict(type_counts.most_common()),
        "visible_entity_type_counts": dict(visible_type_counts.most_common()),
        "layer_counts_top": dict(layer_counts.most_common(50)),
        "visible_layer_counts_top": dict(visible_layer_counts.most_common(50)),
    }


def summarize_cleanup_candidates(doc: DxfDrawing, insert_audit: dict[str, Any]) -> dict[str, Any]:
    invisible_non_room_count = 0
    protected_room_text_count = 0
    protected_room_text_handles: list[str] = []
    protected_insert_with_room_text_count = 0
    payload_cache: dict[str, dict[str, Any]] = {}
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    for entity in doc.modelspace():
        if is_entity_visible(doc, entity):
            continue
        if is_room_text_entity(entity):
            protected_room_text_count += 1
            protected_room_text_handles.append(str(getattr(entity.dxf, "handle", "")))
            continue
        if entity.dxftype() == "INSERT":
            payload = estimate_block_payload(doc, str(entity.dxf.name), payload_cache)
            if payload["room_text_count"] > 0:
                protected_insert_with_room_text_count += 1
                continue
        invisible_non_room_count += 1
        type_counts[entity.dxftype()] += 1
        layer_counts[str(getattr(entity.dxf, "layer", "0"))] += 1
    return {
        "first_step_candidate_name": "remove_invisible_non_room_modelspace_entities",
        "candidate_entity_count": invisible_non_room_count,
        "candidate_type_counts": dict(type_counts.most_common()),
        "candidate_layer_counts_top": dict(layer_counts.most_common(50)),
        "protected_room_text_count": protected_room_text_count,
        "protected_room_text_handles_sample": protected_room_text_handles[:200],
        "protected_hidden_insert_with_room_text_count": protected_insert_with_room_text_count,
        "hidden_insert_count": insert_audit.get("hidden_insert_count", 0),
    }


def estimate_block_payload(
    doc: DxfDrawing,
    block_name: str,
    cache: dict[str, dict[str, Any]],
    stack: tuple[str, ...] = (),
) -> dict[str, Any]:
    if block_name in cache:
        return cache[block_name]
    if block_name in stack:
        return {
            "estimated_entity_count": 0,
            "entity_type_counts": {},
            "room_text_count": 0,
            "room_text_sample": [],
            "cycle_detected": True,
        }
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    room_text_sample: list[dict[str, Any]] = []
    room_text_count = 0
    try:
        block = doc.blocks.get(block_name)
    except Exception:
        result = {
            "estimated_entity_count": 0,
            "entity_type_counts": {},
            "layer_counts": {},
            "room_text_count": 0,
            "room_text_sample": [],
            "missing_block": True,
        }
        cache[block_name] = result
        return result
    if block is None:
        result = {
            "estimated_entity_count": 0,
            "entity_type_counts": {},
            "layer_counts": {},
            "room_text_count": 0,
            "room_text_sample": [],
            "missing_block": True,
        }
        cache[block_name] = result
        return result
    for entity in block:
        entity_type = entity.dxftype()
        layer_counts[str(getattr(entity.dxf, "layer", "0"))] += 1
        type_counts[entity_type] += 1
        parsed = parse_room_text(entity_text(entity)) if entity_type in ROOM_TEXT_ENTITY_TYPES else None
        if parsed:
            room_text_count += 1
            if len(room_text_sample) < 20:
                room_text_sample.append(
                    {
                        "entity_type": entity_type,
                        "layer": str(getattr(entity.dxf, "layer", "")),
                        "text": entity_text(entity),
                        **parsed,
                    }
                )
        if entity_type == "INSERT":
            try:
                nested_name = str(entity.dxf.name)
            except Exception:
                continue
            nested = estimate_block_payload(doc, nested_name, cache, stack + (block_name,))
            type_counts.update(nested.get("entity_type_counts", {}))
            layer_counts.update(nested.get("layer_counts", {}))
            room_text_count += int(nested.get("room_text_count", 0))
            for item in nested.get("room_text_sample", []):
                if len(room_text_sample) < 20:
                    room_text_sample.append(item)
    result = {
        "estimated_entity_count": sum(type_counts.values()),
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts": dict(layer_counts.most_common()),
        "room_text_count": room_text_count,
        "room_text_sample": room_text_sample,
    }
    cache[block_name] = result
    return result


def run_invisible_non_room_modelspace_step(
    current_path: Path,
    out_dir: Path,
    step_number: int,
    render_images: bool,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_invisible_non_room_modelspace_entities"
    step_title = "Remove invisible non-room modelspace entities"
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    removed_json_path = step_dir / "removed_or_protected_entities.json"
    ai_check_path = step_dir / "ai_check.json"
    visual_check_path = step_dir / "visual_check.json"
    report_path = step_dir / "report.html"
    shutil.copy2(current_path, input_path)

    before_stats = analyze_pre_explode_dxf(input_path)
    write_json(step_dir / "before_stats.json", before_stats)
    doc = load_dxf(input_path)
    candidates, protected = collect_invisible_non_room_candidates(doc)
    removed_payload = build_removed_payload(candidates, protected, step_name)
    write_json(removed_json_path, removed_payload)
    removed_count = remove_entities(doc, candidates)
    if removed_count:
        doc.modelspace().entity_space.purge()
        doc.entitydb.purge()
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)
    after_stats = analyze_pre_explode_dxf(candidate_after_path)
    protection = run_pre_explode_protection_checks(before_stats, after_stats, removed_payload, removed_count)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    visual_check = {"status": "skipped", "notes": "Pass --render-images to create before/after/diff PNGs."}
    if render_images:
        visual_check = render_candidate_images(step_dir, input_path, candidate_after_path)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    write_json(ai_check_path, ai_check)
    write_json(visual_check_path, visual_check)
    status = decide_candidate_status(removed_count, protection, visual_check, render_images)
    if status == "accepted":
        accepted_after_path = step_dir / "accepted_after.dxf"
        shutil.copy2(candidate_after_path, accepted_after_path)
        write_rollback_script(out_dir, step_number, accepted_after_path)
    elif status == "rejected":
        rejected_after_path = step_dir / "rejected_after.dxf"
        shutil.copy2(candidate_after_path, rejected_after_path)

    report_path.write_text(
        build_step_html(
            step_number=step_number,
            title=step_title,
            status=status,
            input_path=input_path,
            candidate_after_path=candidate_after_path,
            before_stats=before_stats,
            after_stats=after_stats,
            removed_payload=removed_payload,
            protection=protection,
            visual_check=visual_check,
            ai_check=ai_check,
            removed_json_path=removed_json_path,
        ),
        encoding="utf-8",
    )
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(step_dir / "accepted_after.dxf") if status == "accepted" else None,
        "rejected_after_dxf": str(step_dir / "rejected_after.dxf") if status == "rejected" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "ai_check": str(ai_check_path),
        "visual_check": str(visual_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "protected_count": removed_payload["protected_count"],
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "condition": "Modelspace entity is invisible by layer off/frozen state or DXF invisible flag.",
            "action": "Remove only if it is not a parsed room text and not an INSERT whose block contains room text.",
            "risk": "medium",
            "requires_manual_validation": True,
        },
    }


def run_unreachable_blocks_after_visibility_step(
    current_path: Path,
    out_dir: Path,
    step_number: int,
    render_images: bool,
    dry_run_ai: bool,
    skip_ai: bool,
    protect_room_text_blocks: bool,
) -> dict[str, Any]:
    step_name = (
        "remove_unreachable_non_room_blocks_after_visibility_prune"
        if protect_room_text_blocks
        else "remove_unreachable_blocks_after_visibility_prune"
    )
    step_title = (
        "Remove unreachable non-room block definitions after visibility prune"
        if protect_room_text_blocks
        else "Remove unreachable block definitions after visibility prune"
    )
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    removed_json_path = step_dir / "removed_blocks.json"
    ai_check_path = step_dir / "ai_check.json"
    visual_check_path = step_dir / "visual_check.json"
    report_path = step_dir / "report.html"
    shutil.copy2(current_path, input_path)

    before_stats = analyze_pre_explode_dxf(input_path)
    doc = load_dxf(input_path)
    reachable = collect_reachable_blocks(doc)
    all_blocks = {str(block.name) for block in doc.blocks}
    unreachable_names = sorted(all_blocks - reachable)
    payload_cache: dict[str, dict[str, Any]] = {}
    protected_blocks: list[dict[str, Any]] = []
    protected_names: set[str] = set()
    for name in unreachable_names:
        payload = estimate_block_payload(doc, name, payload_cache)
        if protect_room_text_blocks and int(payload.get("room_text_count", 0)) > 0:
            protected_names.add(name)
            protected_blocks.append(
                {
                    "name": name,
                    "room_text_count": payload.get("room_text_count", 0),
                    "room_text_sample": payload.get("room_text_sample", [])[:10],
                }
            )
    if protected_names:
        protected_names.update(collect_block_reference_closure(doc, protected_names))
    remove_names = [name for name in unreachable_names if name not in protected_names]
    removed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for name in remove_names:
        try:
            block = doc.blocks.get(name)
            payload = estimate_block_payload(doc, name, payload_cache)
            removed.append(
                {
                    "name": name,
                    "direct_entity_count": len(block),
                    "contains_room_text": int(payload.get("room_text_count", 0)) > 0,
                }
            )
            doc.blocks.delete_block(name, safe=False)
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    doc.entitydb.purge()
    doc.objects.purge()
    if removed:
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)

    after_stats = analyze_pre_explode_dxf(candidate_after_path)
    write_json(step_dir / "after_stats.json", after_stats)
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed),
        "unreachable_block_count": len(unreachable_names),
        "reachable_block_count": len(reachable),
        "removed_block_count": len(removed),
        "removed_block_entity_count": sum(int(item["direct_entity_count"]) for item in removed),
        "removed_blocks_sample": removed[:300],
        "removed_blocks_with_room_text_count": sum(1 for item in removed if item["contains_room_text"]),
        "protected_room_text_block_count": len(protected_blocks),
        "protected_room_text_blocks_sample": protected_blocks[:100],
        "failed_count": len(failed),
        "failed_sample": failed[:100],
        "notes": (
            "Deletes block definitions unreachable from layouts, nested INSERTs, DIMENSION geometry, or DIMSTYLE arrow blocks. "
            "Room-text blocks are protected." if protect_room_text_blocks
            else "Deletes all unreachable block definitions; this intentionally can fail room-text protection checks."
        ),
    }
    write_json(removed_json_path, removed_payload)
    protection = run_pre_explode_block_protection_checks(before_stats, after_stats, removed_payload)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    visual_check = {"status": "skipped", "notes": "Pass --render-images to create before/after/diff PNGs."}
    if render_images:
        visual_check = render_candidate_images(step_dir, input_path, candidate_after_path)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    write_json(ai_check_path, ai_check)
    write_json(visual_check_path, visual_check)
    status = decide_candidate_status(len(removed), protection, visual_check, render_images)
    if status == "accepted":
        accepted_after_path = step_dir / "accepted_after.dxf"
        shutil.copy2(candidate_after_path, accepted_after_path)
        write_rollback_script(out_dir, step_number, accepted_after_path)
    elif status == "rejected":
        rejected_after_path = step_dir / "rejected_after.dxf"
        shutil.copy2(candidate_after_path, rejected_after_path)

    report_path.write_text(
        build_step_html(
            step_number=step_number,
            title=step_title,
            status=status,
            input_path=input_path,
            candidate_after_path=candidate_after_path,
            before_stats=before_stats,
            after_stats=after_stats,
            removed_payload=removed_payload,
            protection=protection,
            visual_check=visual_check,
            ai_check=ai_check,
            removed_json_path=removed_json_path,
        ),
        encoding="utf-8",
    )
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(step_dir / "accepted_after.dxf") if status == "accepted" else None,
        "rejected_after_dxf": str(step_dir / "rejected_after.dxf") if status == "rejected" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "ai_check": str(ai_check_path),
        "visual_check": str(visual_check_path),
        "report_html": str(report_path),
        "removed_count": len(removed),
        "protected_count": 0,
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "condition": "Block definition is unreachable after invisible non-room modelspace entities are removed.",
            "action": "Delete unreachable block definitions.",
            "protect_room_text_blocks": protect_room_text_blocks,
            "risk": "medium",
            "requires_manual_validation": True,
        },
    }


def run_pre_explode_block_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
) -> dict[str, Any]:
    checks = []
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    for name, before, after in [
        ("modelspace_entity_count_unchanged", before_model.get("entity_count"), after_model.get("entity_count")),
        ("visible_modelspace_entity_count_unchanged", before_model.get("visible_entity_count"), after_model.get("visible_entity_count")),
        ("insert_count_unchanged", before_model.get("insert_count"), after_model.get("insert_count")),
        (
            "visible_room_text_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_text_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_text_count"],
        ),
        (
            "visible_room_number_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_number_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_number_count"],
        ),
        (
            "visible_room_name_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_name_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_name_count"],
        ),
        (
            "room_boundary_visible_layer_counts_unchanged",
            before_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
            after_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
        ),
    ]:
        checks.append(check_equal(name, before, after))
    before_blocks = before_stats["tables"]["block_count"]
    after_blocks = after_stats["tables"]["block_count"]
    removed_count = int(removed_payload.get("removed_count", 0))
    checks.append(
        {
            "name": "block_count_delta",
            "status": "passed" if int(after_blocks) == int(before_blocks) - removed_count else "failed",
            "before": before_blocks,
            "after": after_blocks,
            "expected_after": int(before_blocks) - removed_count,
            "message": "matches removed count" if int(after_blocks) == int(before_blocks) - removed_count else "mismatch",
        }
    )
    checks.append(
        {
            "name": "removed_blocks_do_not_contain_room_text",
            "status": "passed" if int(removed_payload.get("removed_blocks_with_room_text_count", 0)) == 0 else "failed",
            "removed_blocks_with_room_text_count": removed_payload.get("removed_blocks_with_room_text_count", 0),
            "message": "no parsed room text in removed block definitions",
        }
    )
    before_size = int(before_stats["file"]["size_bytes"])
    after_size = int(after_stats["file"]["size_bytes"])
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_count > 0 and after_size < before_size else "warning",
            "before": before_size,
            "after": after_size,
            "message": "decreased" if after_size < before_size else "did not decrease",
        }
    )
    status = "passed" if all(check["status"] in {"passed", "warning"} for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_room_focused_visible_prune_step(
    current_path: Path,
    out_dir: Path,
    step_number: int,
    render_images: bool,
    dry_run_ai: bool,
    skip_ai: bool,
    protect_opening_layers: bool,
) -> dict[str, Any]:
    step_name = (
        "remove_visible_non_room_entities_keep_openings_for_room_boundary"
        if protect_opening_layers
        else "remove_visible_non_room_entities_for_room_boundary"
    )
    step_title = (
        "Remove visible non-room entities while keeping door/opening context"
        if protect_opening_layers
        else "Remove visible non-room entities for room-boundary extraction"
    )
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    removed_json_path = step_dir / "removed_or_protected_entities.json"
    ai_check_path = step_dir / "ai_check.json"
    visual_check_path = step_dir / "visual_check.json"
    report_path = step_dir / "report.html"
    shutil.copy2(current_path, input_path)

    before_stats = analyze_pre_explode_dxf(input_path)
    doc = load_dxf(input_path)
    candidates, protected = collect_visible_non_room_candidates(doc, protect_opening_layers=protect_opening_layers)
    removed_payload = build_visible_room_prune_payload(candidates, protected, step_name)
    write_json(removed_json_path, removed_payload)
    removed_count = remove_entities(doc, candidates)
    if removed_count:
        doc.modelspace().entity_space.purge()
        doc.entitydb.purge()
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)

    after_stats = analyze_pre_explode_dxf(candidate_after_path)
    protection = run_room_focused_prune_protection_checks(
        before_stats,
        after_stats,
        removed_payload,
        removed_count,
        protect_opening_layers=protect_opening_layers,
    )
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    visual_check = {"status": "skipped", "notes": "Pass --render-images to create before/after/diff PNGs."}
    if render_images:
        visual_check = render_candidate_images(step_dir, input_path, candidate_after_path)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    write_json(ai_check_path, ai_check)
    write_json(visual_check_path, visual_check)
    status = decide_candidate_status(removed_count, protection, visual_check, render_images)
    if status == "accepted":
        accepted_after_path = step_dir / "accepted_after.dxf"
        shutil.copy2(candidate_after_path, accepted_after_path)
        write_rollback_script(out_dir, step_number, accepted_after_path)
    elif status == "rejected":
        rejected_after_path = step_dir / "rejected_after.dxf"
        shutil.copy2(candidate_after_path, rejected_after_path)
    report_path.write_text(
        build_step_html(
            step_number=step_number,
            title=step_title,
            status=status,
            input_path=input_path,
            candidate_after_path=candidate_after_path,
            before_stats=before_stats,
            after_stats=after_stats,
            removed_payload=removed_payload,
            protection=protection,
            visual_check=visual_check,
            ai_check=ai_check,
            removed_json_path=removed_json_path,
        ),
        encoding="utf-8",
    )
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(step_dir / "accepted_after.dxf") if status == "accepted" else None,
        "rejected_after_dxf": str(step_dir / "rejected_after.dxf") if status == "rejected" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "ai_check": str(ai_check_path),
        "visual_check": str(visual_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "protected_count": removed_payload["protected_count"],
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "condition": "Visible modelspace entity is not protected room text/boundary/opening context and not an INSERT whose block payload contains protected room context.",
            "action": "Remove from a room-boundary-focused pre-explode candidate.",
            "protect_opening_layers": protect_opening_layers,
            "risk": "high",
            "requires_manual_validation": True,
        },
    }


def run_remove_paperspace_layouts_and_blocks_step(
    current_path: Path,
    out_dir: Path,
    step_number: int,
    render_images: bool,
    dry_run_ai: bool,
    skip_ai: bool,
    clear_kept_layout: bool,
) -> dict[str, Any]:
    step_name = (
        "remove_paperspace_layouts_and_unreachable_blocks"
        if clear_kept_layout
        else "remove_extra_paperspace_layouts_keep_base_layout"
    )
    step_title = (
        "Remove paper-space layouts and newly unreachable non-room blocks"
        if clear_kept_layout
        else "Remove extra paper-space layouts while keeping the base layout"
    )
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_layouts_and_blocks.json"
    shutil.copy2(current_path, input_path)

    before_stats = analyze_pre_explode_dxf(input_path)
    doc = load_dxf(input_path)
    layout_cleanup = remove_paperspace_layouts(doc, clear_kept_layout=clear_kept_layout)
    block_cleanup = remove_unreachable_non_room_blocks(doc)
    doc.entitydb.purge()
    doc.objects.purge()
    doc.saveas(candidate_after_path)

    after_stats = analyze_pre_explode_dxf(candidate_after_path)
    removed_payload = {
        "step_name": step_name,
        "removed_count": int(layout_cleanup["removed_count"]) + int(block_cleanup["removed_block_count"]),
        "layout_cleanup": layout_cleanup,
        "block_cleanup": block_cleanup,
        "entity_type_counts": {},
        "layer_counts": {},
        "notes": (
            "Deletes paper-space layouts except for one required empty paper-space layout, then deletes block "
            "definitions that become unreachable and do not contain parsed room text."
        ),
    }
    write_json(removed_json_path, removed_payload)
    protection = run_paperspace_layout_and_block_protection_checks(before_stats, after_stats, removed_payload)
    visual_check = (
        render_candidate_images(step_dir, input_path, candidate_after_path)
        if render_images
        else {"status": "skipped", "notes": "Pass --render-images to create before/after/diff PNGs."}
    )
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(step_dir / "ai_check.json", ai_check)
    write_json(step_dir / "visual_check.json", visual_check)
    report_path = step_dir / "report.html"
    report_path.write_text(
        build_step_html(
            step_number=step_number,
            title=step_title,
            status="pending",
            input_path=input_path,
            candidate_after_path=candidate_after_path,
            before_stats=before_stats,
            after_stats=after_stats,
            removed_payload=removed_payload,
            protection=protection,
            ai_check=ai_check,
            visual_check=visual_check,
            removed_json_path=removed_json_path,
        ),
        encoding="utf-8",
    )
    status = decide_candidate_status(int(removed_payload["removed_count"]), protection, visual_check, render_images)
    if status == "accepted":
        accepted_after_path = step_dir / "accepted_after.dxf"
        shutil.copy2(candidate_after_path, accepted_after_path)
    elif status == "rejected":
        rejected_after_path = step_dir / "rejected_after.dxf"
        shutil.copy2(candidate_after_path, rejected_after_path)
    report_path.write_text(
        build_step_html(
            step_number=step_number,
            title=step_title,
            status=status,
            input_path=input_path,
            candidate_after_path=candidate_after_path,
            before_stats=before_stats,
            after_stats=after_stats,
            removed_payload=removed_payload,
            protection=protection,
            visual_check=visual_check,
            ai_check=ai_check,
            removed_json_path=removed_json_path,
        ),
        encoding="utf-8",
    )
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(step_dir / "accepted_after.dxf") if status == "accepted" else None,
        "rejected_after_dxf": str(step_dir / "rejected_after.dxf") if status == "rejected" else None,
        "before_stats": str(step_dir / "before_stats.json"),
        "after_stats": str(step_dir / "after_stats.json"),
        "removed_entities_json": str(removed_json_path),
        "ai_check": str(step_dir / "ai_check.json"),
        "visual_check": str(step_dir / "visual_check.json"),
        "report_html": str(report_path),
        "removed_count": removed_payload["removed_count"],
        "protected_count": block_cleanup["protected_room_text_block_count"],
        "file_size_before": input_path.stat().st_size,
        "file_size_after": candidate_after_path.stat().st_size,
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "condition": (
                "Paper-space layouts are outside the room-boundary target, and block definitions are unreachable "
                "after paper-space cleanup and contain no parsed room text."
            ),
            "action": (
                "Delete paper-space content and newly unreachable non-room blocks."
                if clear_kept_layout
                else "Delete extra paper-space layouts, keep the required base paper layout, and delete newly unreachable non-room blocks."
            ),
            "clear_kept_layout": clear_kept_layout,
            "risk": "medium",
            "requires_manual_validation": True,
        },
    }


def remove_paperspace_layouts(doc: DxfDrawing, clear_kept_layout: bool) -> dict[str, Any]:
    paperspaces = [layout for layout in list(doc.layouts) if str(layout.name).lower() != "model"]
    removed_layouts: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    keep_layout_name = str(paperspaces[0].name) if paperspaces else None
    for layout in paperspaces[1:]:
        name = str(layout.name)
        block_name = str(getattr(layout, "block_record_name", ""))
        entity_count = len(layout)
        try:
            doc.layouts.delete(name)
            removed_layouts.append({"name": name, "block_record_name": block_name, "entity_count": entity_count})
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})

    cleared_entities = 0
    if keep_layout_name and clear_kept_layout:
        try:
            keep_layout = doc.layouts.get(keep_layout_name)
            for entity in list(keep_layout):
                entity.destroy()
                cleared_entities += 1
            keep_layout.entity_space.purge()
        except Exception as exc:
            failed.append({"name": keep_layout_name, "error": f"clear kept paperspace failed: {type(exc).__name__}: {exc}"})
    return {
        "paperspace_layout_count_before": len(paperspaces),
        "kept_empty_paperspace_layout": keep_layout_name,
        "removed_layout_count": len(removed_layouts),
        "removed_layouts": removed_layouts,
        "cleared_kept_paperspace_entity_count": cleared_entities,
        "clear_kept_layout": clear_kept_layout,
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "removed_count": len(removed_layouts) + cleared_entities,
    }


def remove_unreachable_non_room_blocks(doc: DxfDrawing) -> dict[str, Any]:
    reachable = collect_reachable_blocks(doc)
    all_blocks = {str(block.name) for block in doc.blocks}
    unreachable_names = sorted(all_blocks - reachable)
    payload_cache: dict[str, dict[str, Any]] = {}
    removed: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for name in unreachable_names:
        payload = estimate_block_payload(doc, name, payload_cache)
        try:
            block = doc.blocks.get(name)
        except Exception:
            block = None
        direct_count = len(block) if block is not None else 0
        item = {
            "name": name,
            "direct_entity_count": direct_count,
            "estimated_entity_count": int(payload.get("estimated_entity_count", 0)),
            "contains_room_text": int(payload.get("room_text_count", 0)) > 0,
            "type_counts": payload.get("entity_type_counts", {}),
        }
        if item["contains_room_text"]:
            protected.append(item)
            continue
        try:
            doc.blocks.delete_block(name, safe=False)
            removed.append(item)
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "reachable_block_count_after_layout_cleanup": len(reachable),
        "unreachable_block_count_after_layout_cleanup": len(unreachable_names),
        "removed_block_count": len(removed),
        "removed_block_entity_count": sum(int(item["direct_entity_count"]) for item in removed),
        "removed_estimated_entity_count": sum(int(item["estimated_entity_count"]) for item in removed),
        "removed_blocks_sample": sorted(removed, key=lambda item: int(item["direct_entity_count"]), reverse=True)[:300],
        "protected_room_text_block_count": len(protected),
        "protected_room_text_blocks_sample": protected[:100],
        "failed_count": len(failed),
        "failed_sample": failed[:50],
    }


def run_paperspace_layout_and_block_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
) -> dict[str, Any]:
    checks = []
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        checks.append(check_equal(f"modelspace_{key}_unchanged", before_model.get(key), after_model.get(key)))
    checks.extend(
        [
            check_equal(
                "visible_room_text_count_unchanged",
                before_stats["pre_explode"]["room_text"]["visible_room_text_count"],
                after_stats["pre_explode"]["room_text"]["visible_room_text_count"],
            ),
            check_equal(
                "visible_room_number_count_unchanged",
                before_stats["pre_explode"]["room_text"]["visible_room_number_count"],
                after_stats["pre_explode"]["room_text"]["visible_room_number_count"],
            ),
            check_equal(
                "visible_room_name_count_unchanged",
                before_stats["pre_explode"]["room_text"]["visible_room_name_count"],
                after_stats["pre_explode"]["room_text"]["visible_room_name_count"],
            ),
            check_equal(
                "room_boundary_visible_layer_counts_unchanged",
                before_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
                after_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
            ),
            check_equal(
                "room_opening_visible_layer_counts_unchanged",
                before_stats["pre_explode"]["room_opening_layers"]["visible_layer_counts_top"],
                after_stats["pre_explode"]["room_opening_layers"]["visible_layer_counts_top"],
            ),
        ]
    )
    before_tables = before_stats["tables"]
    after_tables = after_stats["tables"]
    checks.append(
        {
            "name": "layout_count_decreased",
            "status": "passed" if int(after_tables.get("layout_count", 0)) < int(before_tables.get("layout_count", 0)) else "failed",
            "before": before_tables.get("layout_count", 0),
            "after": after_tables.get("layout_count", 0),
            "message": "paper-space layouts removed",
        }
    )
    for key in ("block_count", "block_entity_count"):
        before_value = int(before_tables.get(key, 0))
        after_value = int(after_tables.get(key, 0))
        checks.append(
            {
                "name": f"{key}_decreased_or_same",
                "status": "passed" if after_value <= before_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "not increased" if after_value <= before_value else "increased unexpectedly",
            }
        )
    checks.append(
        {
            "name": "layout_cleanup_failures",
            "status": "passed" if int(removed_payload["layout_cleanup"]["failed_count"]) == 0 else "failed",
            "failed_count": removed_payload["layout_cleanup"]["failed_count"],
            "message": "no layout cleanup failures",
        }
    )
    checks.append(
        {
            "name": "block_cleanup_failures",
            "status": "passed" if int(removed_payload["block_cleanup"]["failed_count"]) == 0 else "failed",
            "failed_count": removed_payload["block_cleanup"]["failed_count"],
            "message": "no block cleanup failures",
        }
    )
    checks.append(
        {
            "name": "removed_blocks_do_not_contain_room_text",
            "status": "passed",
            "message": "only blocks without parsed room text are deleted",
        }
    )
    status = "passed" if all(check["status"] in {"passed", "warning"} for check in checks) else "failed"
    return {"status": status, "checks": checks}


def collect_visible_non_room_candidates(doc: DxfDrawing, protect_opening_layers: bool) -> tuple[list[object], list[dict[str, Any]]]:
    candidates: list[object] = []
    protected: list[dict[str, Any]] = []
    payload_cache: dict[str, dict[str, Any]] = {}
    for entity in doc.modelspace():
        if not is_entity_visible(doc, entity):
            protected.append(entity_summary(entity, "keep_hidden_not_exploded_by_visible_only_flow"))
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        if is_room_boundary_layer(layer):
            protected.append(entity_summary(entity, "keep_room_boundary_layer"))
            continue
        if protect_opening_layers and is_room_opening_layer(layer):
            protected.append(entity_summary(entity, "keep_room_opening_layer"))
            continue
        if is_room_text_entity(entity):
            protected.append(entity_summary(entity, "keep_room_text"))
            continue
        if entity.dxftype() == "INSERT":
            payload = estimate_block_payload(doc, str(entity.dxf.name), payload_cache)
            payload_layers = payload.get("layer_counts", {})
            has_boundary_payload = any(is_room_boundary_layer(str(name)) for name in payload_layers)
            has_opening_payload = protect_opening_layers and any(is_room_opening_layer(str(name)) for name in payload_layers)
            if int(payload.get("room_text_count", 0)) > 0 or has_boundary_payload or has_opening_payload:
                protected.append(
                    {
                        **entity_summary(entity, "keep_insert_room_payload"),
                        "payload_room_text_count": payload.get("room_text_count", 0),
                        "payload_boundary_layers": [name for name in payload_layers if is_room_boundary_layer(str(name))][:20],
                        "payload_opening_layers": [name for name in payload_layers if is_room_opening_layer(str(name))][:20],
                    }
                )
                continue
        candidates.append(entity)
    return candidates, protected


def build_visible_room_prune_payload(candidates: list[object], protected: list[dict[str, Any]], step_name: str) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    samples = []
    for entity in candidates:
        type_counts[entity.dxftype()] += 1
        layer_counts[str(getattr(entity.dxf, "layer", "0"))] += 1
        if len(samples) < 300:
            samples.append(entity_summary(entity, "remove_visible_non_room"))
    protected_reasons = Counter(str(item.get("reason", "")) for item in protected)
    return {
        "step_name": step_name,
        "removed_count": len(candidates),
        "protected_count": len(protected),
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts_top": dict(layer_counts.most_common(100)),
        "removed_samples": samples,
        "protected_reason_counts": dict(protected_reasons.most_common()),
        "protected_samples": protected[:300],
        "notes": "High-risk room-boundary-focused prune; keeps room text, boundary layers, hidden curated content, and INSERTs with room text or boundary payload.",
    }


def run_room_focused_prune_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    removed_count: int,
    protect_opening_layers: bool,
) -> dict[str, Any]:
    checks = []
    for name, before, after in [
        (
            "visible_room_text_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_text_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_text_count"],
        ),
        (
            "visible_room_number_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_number_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_number_count"],
        ),
        (
            "visible_room_name_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_name_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_name_count"],
        ),
        (
            "room_boundary_visible_layer_counts_unchanged",
            before_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
            after_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
        ),
    ]:
        checks.append(check_equal(name, before, after))
    if protect_opening_layers:
        checks.append(
            check_equal(
                "room_opening_visible_layer_counts_unchanged",
                before_stats["pre_explode"]["room_opening_layers"]["visible_layer_counts_top"],
                after_stats["pre_explode"]["room_opening_layers"]["visible_layer_counts_top"],
            )
        )
    before_count = int(before_stats["modelspace"]["entity_count"])
    after_count = int(after_stats["modelspace"]["entity_count"])
    checks.append(
        {
            "name": "modelspace_entity_count_delta",
            "status": "passed" if after_count == before_count - removed_count else "failed",
            "before": before_count,
            "after": after_count,
            "expected_after": before_count - removed_count,
            "message": "matches removed count" if after_count == before_count - removed_count else "mismatch",
        }
    )
    before_size = int(before_stats["file"]["size_bytes"])
    after_size = int(after_stats["file"]["size_bytes"])
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_count > 0 and after_size < before_size else "warning",
            "before": before_size,
            "after": after_size,
            "message": "decreased" if after_size < before_size else "did not decrease",
        }
    )
    status = "passed" if all(check["status"] in {"passed", "warning"} for check in checks) else "failed"
    return {"status": status, "checks": checks}


def block_contains_room_text(block: object) -> bool:
    for entity in block:
        if entity.dxftype() in ROOM_TEXT_ENTITY_TYPES and parse_room_text(entity_text(entity)):
            return True
    return False


def collect_block_reference_closure(doc: DxfDrawing, root_names: set[str]) -> set[str]:
    all_blocks = {str(block.name) for block in doc.blocks}
    protected: set[str] = set()
    queue = list(root_names)
    while queue:
        name = queue.pop(0)
        if name in protected or name not in all_blocks:
            continue
        protected.add(name)
        block = doc.blocks.get(name)
        if block is None:
            continue
        for entity in block:
            for nested_name in entity_block_references(entity):
                if nested_name in all_blocks and nested_name not in protected:
                    queue.append(nested_name)
    return protected


def collect_invisible_non_room_candidates(doc: DxfDrawing) -> tuple[list[object], list[dict[str, Any]]]:
    candidates: list[object] = []
    protected: list[dict[str, Any]] = []
    payload_cache: dict[str, dict[str, Any]] = {}
    for entity in doc.modelspace():
        if is_entity_visible(doc, entity):
            continue
        if is_room_text_entity(entity):
            protected.append(entity_summary(entity, "protected_room_text"))
            continue
        if entity.dxftype() == "INSERT":
            payload = estimate_block_payload(doc, str(entity.dxf.name), payload_cache)
            if payload["room_text_count"] > 0:
                protected.append(
                    {
                        **entity_summary(entity, "protected_insert_contains_room_text"),
                        "block_name": str(entity.dxf.name),
                        "room_text_sample": payload["room_text_sample"],
                    }
                )
                continue
        candidates.append(entity)
    return candidates, protected


def build_removed_payload(candidates: list[object], protected: list[dict[str, Any]], step_name: str) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    samples = []
    for entity in candidates:
        entity_type = entity.dxftype()
        layer = str(getattr(entity.dxf, "layer", "0"))
        type_counts[entity_type] += 1
        layer_counts[layer] += 1
        if len(samples) < 300:
            samples.append(entity_summary(entity, "remove_invisible_non_room"))
    return {
        "step_name": step_name,
        "removed_count": len(candidates),
        "protected_count": len(protected),
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts_top": dict(layer_counts.most_common(100)),
        "removed_samples": samples,
        "protected_samples": protected[:300],
        "notes": (
            "Room text is protected by extract_room_number/extract_room_name. "
            "Invisible INSERTs are protected when their block payload contains parsed room text."
        ),
    }


def remove_entities(doc: DxfDrawing, entities: list[object]) -> int:
    removed = 0
    for entity in entities:
        try:
            entity.destroy()
            removed += 1
        except Exception:
            continue
    return removed


def run_pre_explode_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    removed_count: int,
) -> dict[str, Any]:
    checks = []
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks.append(
        check_equal(
            "visible_modelspace_entity_count_unchanged",
            before_model.get("visible_entity_count"),
            after_model.get("visible_entity_count"),
        )
    )
    checks.append(
        check_equal(
            "visible_room_text_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_text_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_text_count"],
        )
    )
    checks.append(
        check_equal(
            "visible_room_number_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_number_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_number_count"],
        )
    )
    checks.append(
        check_equal(
            "visible_room_name_count_unchanged",
            before_stats["pre_explode"]["room_text"]["visible_room_name_count"],
            after_stats["pre_explode"]["room_text"]["visible_room_name_count"],
        )
    )
    checks.append(
        check_equal(
            "room_boundary_visible_layer_counts_unchanged",
            before_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
            after_stats["pre_explode"]["room_boundary_layers"]["visible_layer_counts_top"],
        )
    )
    expected_after = int(before_model["entity_count"]) - removed_count
    checks.append(
        {
            "name": "modelspace_entity_count_delta",
            "status": "passed" if int(after_model["entity_count"]) == expected_after else "failed",
            "before": before_model["entity_count"],
            "after": after_model["entity_count"],
            "expected_after": expected_after,
            "message": "matches removed count" if int(after_model["entity_count"]) == expected_after else "mismatch",
        }
    )
    before_size = int(before_stats["file"]["size_bytes"])
    after_size = int(after_stats["file"]["size_bytes"])
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_count > 0 and after_size < before_size else "warning",
            "before": before_size,
            "after": after_size,
            "message": "decreased" if after_size < before_size else "did not decrease",
        }
    )
    checks.append(
        {
            "name": "protected_room_sensitive_entities_not_removed",
            "status": "passed",
            "protected_count": removed_payload.get("protected_count", 0),
            "message": "protected entities were skipped by candidate deletion",
        }
    )
    status = "passed" if all(check["status"] in {"passed", "warning"} for check in checks) else "failed"
    return {"status": status, "checks": checks}


def check_equal(name: str, before: Any, after: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if before == after else "failed",
        "before": before,
        "after": after,
        "message": "unchanged" if before == after else "changed unexpectedly",
    }


def decide_candidate_status(
    removed_count: int,
    protection: dict[str, Any],
    visual_check: dict[str, Any],
    render_images: bool,
) -> str:
    if removed_count <= 0:
        return "rejected"
    if protection["status"] != "passed":
        return "rejected"
    if render_images:
        diff = visual_check.get("image_diff") or {}
        if int(diff.get("changed_pixels", 1)) != 0:
            return "needs_manual_review"
    return "needs_manual_review"


def render_candidate_images(step_dir: Path, before_path: Path, after_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "created_at": now_iso(),
        "status": "pending",
        "before_png": str(step_dir / "before.png"),
        "after_png": str(step_dir / "after.png"),
        "diff_png": str(step_dir / "diff.png"),
        "comparison_png": str(step_dir / "comparison.png"),
    }
    try:
        before_png = step_dir / "before.png"
        after_png = step_dir / "after.png"
        diff_png = step_dir / "diff.png"
        comparison_png = step_dir / "comparison.png"
        shared_bbox = compute_shared_render_bbox([before_path, after_path])
        render_dxf_png(before_path, before_png, view_bbox=shared_bbox)
        render_dxf_png(after_path, after_png, view_bbox=shared_bbox)
        write_diff_png(before_png, after_png, diff_png)
        write_comparison_png([before_png, before_png, after_png, diff_png], comparison_png)
        result["image_diff"] = compare_pngs(before_png, after_png)
        result["shared_bbox"] = [round(float(value), 6) for value in shared_bbox]
        result["status"] = "rendered"
    except Exception as exc:
        result["status"] = "failed"
        result["message"] = f"{type(exc).__name__}: {exc}"
    return result


def is_room_boundary_layer(layer_name: str) -> bool:
    upper_name = layer_name.upper()
    return any(keyword.upper() in upper_name for keyword in ROOM_BOUNDARY_LAYER_KEYWORDS)


def is_room_opening_layer(layer_name: str) -> bool:
    upper_name = layer_name.upper()
    return any(keyword.upper() in upper_name for keyword in ROOM_OPENING_LAYER_KEYWORDS)


def is_room_text_entity(entity: object) -> bool:
    if entity.dxftype() not in ROOM_TEXT_ENTITY_TYPES:
        return False
    return parse_room_text(entity_text(entity)) is not None


def parse_room_text(text: str) -> dict[str, str] | None:
    if not text.strip():
        return None
    room_number = extract_room_number(text)
    room_name = extract_room_name(text)
    if not room_number and not room_name:
        return None
    payload: dict[str, str] = {}
    if room_number:
        payload["room_number"] = room_number
    if room_name:
        payload["room_name"] = room_name
    return payload


def entity_text(entity: object) -> str:
    entity_type = entity.dxftype()
    if entity_type in {"TEXT", "ATTRIB", "ATTDEF"}:
        return str(getattr(entity.dxf, "text", "") or "")
    if entity_type == "MTEXT":
        try:
            return str(entity.plain_text())
        except Exception:
            return str(getattr(entity, "text", "") or "")
    return ""


def entity_summary(entity: object, reason: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "handle": str(getattr(entity.dxf, "handle", "")),
        "entity_type": entity.dxftype(),
        "layer": str(getattr(entity.dxf, "layer", "")),
        "reason": reason,
    }
    text = entity_text(entity)
    if text:
        parsed = parse_room_text(text)
        payload["text"] = text
        if parsed:
            payload.update(parsed)
    if entity.dxftype() == "INSERT":
        try:
            payload["block_name"] = str(entity.dxf.name)
        except Exception:
            pass
    return payload


def build_baseline_html(source_audit: dict[str, Any], exploded_audit: dict[str, Any] | None) -> str:
    pre = source_audit["pre_explode"]
    exploded = ""
    if exploded_audit:
        exploded = f"""
        <section>
          <h2>已炸块参考文件</h2>
          <table>
            <tr><th>Path</th><td>{exploded_audit["path"]}</td></tr>
            <tr><th>Size</th><td>{format_value(exploded_audit["file"]["size_bytes"])} bytes</td></tr>
          </table>
          {section_table_html("Exploded reference sections", exploded_audit["sections"]["sections"])}
        </section>
        """
    return html_page(
        "Pre-explode DXF Audit",
        f"""
        <section>
          <h2>源文件</h2>
          <table>
            <tr><th>Path</th><td>{source_audit["path"]}</td></tr>
            <tr><th>Size</th><td>{format_value(source_audit["file"]["size_bytes"])} bytes</td></tr>
            <tr><th>Modelspace entities</th><td>{format_value(source_audit["modelspace"]["entity_count"])}</td></tr>
            <tr><th>Visible entities</th><td>{format_value(source_audit["modelspace"]["visible_entity_count"])}</td></tr>
            <tr><th>INSERT</th><td>{format_value(pre["modelspace_inserts"]["insert_count"])}</td></tr>
            <tr><th>Hidden INSERT</th><td>{format_value(pre["modelspace_inserts"]["hidden_insert_count"])}</td></tr>
          </table>
        </section>
        <section>
          <h2>第一步候选</h2>
          <pre>{json_dumps(pre["cleanup_candidates"])}</pre>
        </section>
        <section>
          <h2>房间文本保护</h2>
          <pre>{json_dumps(pre["room_text"])}</pre>
        </section>
        <section>
          <h2>隐藏 INSERT 爆炸影响估算</h2>
          <pre>{json_dumps(pre["modelspace_inserts"])}</pre>
        </section>
        <section>
          <h2>房间边界图层</h2>
          <pre>{json_dumps(pre["room_boundary_layers"])}</pre>
        </section>
        {exploded}
        """,
    )


def build_step_html(
    step_number: int,
    title: str,
    status: str,
    input_path: Path,
    candidate_after_path: Path,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    protection: dict[str, Any],
    visual_check: dict[str, Any],
    ai_check: dict[str, Any],
    removed_json_path: Path,
) -> str:
    return html_page(
        f"Step {step_number:03d}: {title}",
        f"""
        <section>
          <h2>状态</h2>
          <div class="status {status}">{status}</div>
          <table>
            <tr><th>Input</th><td>{input_path}</td></tr>
            <tr><th>Candidate</th><td>{candidate_after_path}</td></tr>
            <tr><th>Removed JSON</th><td>{removed_json_path}</td></tr>
          </table>
        </section>
        <section>
          <h2>核心变化</h2>
          <table>
            <tr><th>Metric</th><th>Before</th><th>After</th></tr>
            <tr><td>File size</td><td>{format_value(before_stats["file"]["size_bytes"])}</td><td>{format_value(after_stats["file"]["size_bytes"])}</td></tr>
            <tr><td>Modelspace entities</td><td>{format_value(before_stats["modelspace"]["entity_count"])}</td><td>{format_value(after_stats["modelspace"]["entity_count"])}</td></tr>
            <tr><td>Visible entities</td><td>{format_value(before_stats["modelspace"]["visible_entity_count"])}</td><td>{format_value(after_stats["modelspace"]["visible_entity_count"])}</td></tr>
            <tr><td>Visible room text</td><td>{format_value(before_stats["pre_explode"]["room_text"]["visible_room_text_count"])}</td><td>{format_value(after_stats["pre_explode"]["room_text"]["visible_room_text_count"])}</td></tr>
            <tr><td>Hidden INSERT</td><td>{format_value(before_stats["pre_explode"]["modelspace_inserts"]["hidden_insert_count"])}</td><td>{format_value(after_stats["pre_explode"]["modelspace_inserts"]["hidden_insert_count"])}</td></tr>
          </table>
        </section>
        <section>
          <h2>删除与保护摘要</h2>
          <pre>{json_dumps(removed_payload)}</pre>
        </section>
        <section>
          <h2>保护检查</h2>
          {protection_html(protection)}
        </section>
        <section>
          <h2>视觉 / AI</h2>
          <h3>Visual</h3>
          <pre>{json_dumps(visual_check)}</pre>
          <h3>AI</h3>
          <pre>{json_dumps(ai_check)}</pre>
        </section>
        """,
    )


def section_table_html(title: str, sections: dict[str, dict[str, int]]) -> str:
    rows = "".join(
        f"<tr><td>{name}</td><td>{format_value(stats.get('byte_count', 0))}</td><td>{format_value(stats.get('line_count', 0))}</td></tr>"
        for name, stats in list(sections.items())[:12]
    )
    return f"<div><h3>{title}</h3><table><tr><th>Section</th><th>Bytes</th><th>Lines</th></tr>{rows}</table></div>"


def write_index_html(out_dir: Path, manifest: dict[str, Any]) -> None:
    rows = ""
    for step in manifest.get("steps", []):
        rows += (
            f"<tr><td>{step.get('step')}</td><td>{step.get('name')}</td><td>{step.get('status')}</td>"
            f"<td>{step.get('report_html')}</td></tr>"
        )
    for candidate in manifest.get("review_candidates", []):
        rows += (
            f"<tr><td>{candidate.get('step')}</td><td>{candidate.get('name')}</td><td>{candidate.get('status')}</td>"
            f"<td>{candidate.get('report_html')}</td></tr>"
        )
    html = html_page(
        "Pre-explode DXF Cleaning Experiment",
        f"""
        <section>
          <h2>当前状态</h2>
          <pre>{json_dumps({key: manifest.get(key) for key in ["source", "current_step", "current_dxf", "updated_at"]})}</pre>
        </section>
        <section>
          <h2>步骤</h2>
          <table><tr><th>Step</th><th>Name</th><th>Status</th><th>Report</th></tr>{rows}</table>
        </section>
        <section>
          <h2>Rollback</h2>
          <pre>{json_dumps(manifest.get("rollback_points", []))}</pre>
        </section>
        """,
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def load_manifest(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Experiment manifest not found: {path}")
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(out_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    write_json(out_dir / "manifest.json", manifest)


def rollback_to_step(out_dir: Path, manifest: dict[str, Any], step_number: int) -> None:
    matches = [point for point in manifest.get("rollback_points", []) if int(point.get("step", -1)) == step_number]
    if not matches:
        raise ValueError(f"No rollback point recorded for step {step_number}")
    target = Path(matches[-1]["path"])
    current = out_dir / "current.dxf"
    shutil.copy2(target, current)
    manifest["current_step"] = step_number
    manifest["current_dxf"] = str(current)
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def mark_step_accepted(out_dir: Path, manifest: dict[str, Any], step_number: int, reason: str) -> None:
    step = find_step(manifest, step_number)
    candidate = Path(step.get("candidate_after_dxf") or "")
    if not candidate.exists():
        raise FileNotFoundError(f"Candidate DXF not found for step {step_number}: {candidate}")
    accepted = Path(step["step_dir"]) / "accepted_after.dxf"
    shutil.copy2(candidate, accepted)
    step["status"] = "accepted"
    step["accepted_after_dxf"] = str(accepted)
    step["rejected_after_dxf"] = None
    step["accepted_at"] = now_iso()
    step["accept_reason"] = reason
    manifest["current_step"] = step_number
    manifest["current_dxf"] = str(accepted)
    manifest["rollback_points"] = [
        point for point in manifest.get("rollback_points", []) if int(point.get("step", -1)) != step_number
    ]
    manifest["rollback_points"].append({"step": step_number, "label": step["title"], "path": str(accepted)})
    manifest["review_candidates"] = [
        item for item in manifest.get("review_candidates", []) if int(item.get("step", -1)) != step_number
    ]
    write_rollback_script(out_dir, step_number, accepted)
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def mark_step_rejected(out_dir: Path, manifest: dict[str, Any], step_number: int, reason: str) -> None:
    step = find_step(manifest, step_number)
    candidate = Path(step.get("candidate_after_dxf") or "")
    if not candidate.exists():
        raise FileNotFoundError(f"Candidate DXF not found for step {step_number}: {candidate}")
    rejected = Path(step["step_dir"]) / "rejected_after.dxf"
    shutil.copy2(candidate, rejected)
    step["status"] = "rejected"
    step["accepted_after_dxf"] = None
    step["rejected_after_dxf"] = str(rejected)
    step["rejected_at"] = now_iso()
    step["reject_reason"] = reason
    manifest["rollback_points"] = [
        point for point in manifest.get("rollback_points", []) if int(point.get("step", -1)) != step_number
    ]
    manifest["review_candidates"] = [
        item for item in manifest.get("review_candidates", []) if int(item.get("step", -1)) != step_number
    ]
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def find_step(manifest: dict[str, Any], step_number: int) -> dict[str, Any]:
    for step in manifest.get("steps", []):
        if int(step.get("step", -1)) == step_number:
            return step
    raise ValueError(f"Step {step_number} not found in manifest")


def has_pending_manual_review(manifest: dict[str, Any]) -> bool:
    return any(step.get("status") == "needs_manual_review" for step in manifest.get("steps", []))


def next_step_number(manifest: dict[str, Any]) -> int:
    return max([int(step.get("step", 0)) for step in manifest.get("steps", [])], default=0) + 1


def json_dumps(payload: Any) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_value(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.3f}"
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
