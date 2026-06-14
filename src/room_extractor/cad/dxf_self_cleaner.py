"""Auditable self-driving DXF cleaner.

This script compares a bloated DXF against a visually equivalent reference DXF,
then applies small, auditable cleaning steps. Each step stores removed data,
before/after statistics, an HTML report, and rollback metadata.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.dxf_line_deduper import LINEAR_ENTITY_TYPES, entity_signature
from room_extractor.cad.dxf_loader import load_dxf
from room_extractor.cad.entity_filter import is_entity_visible


DEFAULT_SOURCE = Path("data/input/dxf_exploded/test.dxf")
DEFAULT_REFERENCE = Path("data/input/dxf_exploded/test1.dxf")
DEFAULT_OUT_DIR = Path("log/dxf_cleaning_experiment")
EXACT_TOLERANCE = 1e-9
AI_RENDER_EXCLUDED_ENTITY_TYPES = {"POINT", "XLINE", "RAY"}
AI_RENDER_MARGIN_RATIO = 0.04


@dataclass(frozen=True)
class DuplicateCandidate:
    entity: object
    handle: str | None
    entity_type: str
    layer: str
    signature: tuple[Any, ...]
    reason: str


def add_dxf_self_clean_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Bloated source DXF. Default: test.dxf sample.")
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE), help="Reference DXF. Default: test1.dxf sample.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for the auditable cleaning run.")
    parser.add_argument("--resume", help="Resume an existing self-clean output directory.")
    parser.add_argument("--max-steps", type=int, default=16, help="Maximum cleaning steps to run. Default: all 16 validated stages.")
    parser.add_argument("--analyze-only", action="store_true", help="Only create/update baseline reports; do not clean.")
    parser.add_argument("--rollback-to", type=int, help="Restore current.dxf to a rollback point recorded in manifest.")
    parser.add_argument(
        "--signature-scope",
        choices=["geometry", "layer"],
        default="geometry",
        help="Duplicate signature scope for exact linework cleanup. Default: geometry.",
    )
    parser.add_argument("--dry-run-ai", action="store_true", help="Reserve AI check output without calling local AI.")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI validation fields entirely.")
    parser.add_argument("--render-final", action="store_true", help="Render reference/current PNGs and write final visual check files.")
    parser.add_argument("--render-step-images", action="store_true", help="Render reference/before/after images inside every step directory.")
    parser.add_argument("--mark-step-rejected", type=int, help="Mark an existing step as rejected and roll current state back to the previous accepted step.")
    parser.add_argument("--reject-reason", default="", help="Reason used with --mark-step-rejected.")
    parser.add_argument("--mark-step-accepted", type=int, help="Accept an existing needs_manual_review step after external validation.")
    parser.add_argument("--accept-reason", default="", help="Reason used with --mark-step-accepted.")
    parser.add_argument("--write-bloat-audit", action="store_true", help="Write a detailed report explaining remaining DXF bloat.")
    parser.add_argument(
        "--generate-section-cleanup-chain",
        action="store_true",
        help="Generate three chained review candidates: BLOCKS, OBJECTS, then TABLES. Current accepted DXF is not advanced.",
    )
    parser.add_argument(
        "--accept-without-render",
        action="store_true",
        help=(
            "Accept low-risk exact duplicate cleanup without image rendering. "
            "This is currently the default for exact duplicate linework only."
        ),
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the auditable 16-stage DXF self-clean workflow.")
    return add_dxf_self_clean_arguments(parser)


def main(argv: list[str] | None = None) -> int:
    return run_dxf_self_clean(build_parser().parse_args(argv))


def run_dxf_self_clean(args: argparse.Namespace) -> int:
    if args.resume:
        out_dir = Path(args.resume)
        manifest = load_manifest(out_dir)
        if args.rollback_to is not None:
            rollback_to_step(out_dir, manifest, int(args.rollback_to))
            return 0
        source = Path(manifest["source"])
        reference = Path(manifest["reference"])
    else:
        out_dir = Path(args.out_dir)
        source = Path(args.source)
        reference = Path(args.reference)
        manifest = None

    if args.rollback_to is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        rollback_to_step(out_dir, manifest, int(args.rollback_to))
        return 0

    if args.mark_step_rejected is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        mark_step_rejected(out_dir, manifest, int(args.mark_step_rejected), str(args.reject_reason))
        return 0

    if args.mark_step_accepted is not None:
        if manifest is None:
            manifest = load_manifest(out_dir)
        mark_step_accepted(out_dir, manifest, int(args.mark_step_accepted), str(args.accept_reason))
        return 0

    if args.write_bloat_audit:
        if manifest is None:
            manifest = load_manifest(out_dir)
        write_bloat_audit(out_dir, manifest)
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        return 0

    if args.generate_section_cleanup_chain:
        if manifest is None:
            manifest = load_manifest(out_dir)
        generate_section_cleanup_chain(out_dir, manifest, dry_run_ai=bool(args.dry_run_ai), skip_ai=bool(args.skip_ai))
        return 0

    if args.render_step_images:
        if manifest is None:
            manifest = load_manifest(out_dir)
        render_all_step_images(out_dir, manifest)
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        return 0

    run_experiment(
        source=source,
        reference=reference,
        out_dir=out_dir,
        max_steps=max(0, int(args.max_steps)),
        analyze_only=bool(args.analyze_only),
        signature_scope=str(args.signature_scope),
        dry_run_ai=bool(args.dry_run_ai),
        skip_ai=bool(args.skip_ai),
        render_final=bool(args.render_final),
        render_step_images_enabled=bool(args.render_step_images),
    )
    return 0


def run_experiment(
    source: Path,
    reference: Path,
    out_dir: Path,
    max_steps: int,
    analyze_only: bool,
    signature_scope: str,
    dry_run_ai: bool,
    skip_ai: bool,
    render_final: bool,
    render_step_images_enabled: bool = False,
) -> None:
    source = source.resolve()
    reference = reference.resolve()
    out_dir = out_dir.resolve()
    validate_input_dxf(source, "source")
    validate_input_dxf(reference, "reference")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "steps").mkdir(exist_ok=True)
    (out_dir / "rollback").mkdir(exist_ok=True)

    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists():
        manifest = load_manifest(out_dir)
    else:
        manifest = new_manifest(source, reference, out_dir)

    ensure_baseline(source, reference, out_dir, manifest)
    if analyze_only or max_steps == 0:
        if render_final:
            write_final_visual_check(out_dir, manifest, dry_run_ai=dry_run_ai, skip_ai=skip_ai)
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        return

    steps_remaining = max_steps
    while steps_remaining > 0:
        current_path = Path(manifest["current_dxf"])
        next_step_number = next_cleaning_step_number(manifest)
        next_action = next_cleaning_action(manifest)
        if next_action is None:
            break
        if next_action == "remove_exact_duplicate_linework":
            step = run_exact_duplicate_linework_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                signature_scope=signature_scope,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_invisible_modelspace_entities":
            step = run_invisible_modelspace_entities_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_acad_layerstates":
            step = run_acad_layerstates_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_unused_appids":
            step = run_remove_unused_appids_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_unreachable_blocks":
            step = run_remove_unreachable_blocks_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_acad_color_branch":
            step = run_dictionary_branch_candidate_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                step_name="remove_acad_color_branch",
                step_title="Remove ACAD_COLOR color-book branch",
                dictionary_key="ACAD_COLOR",
                reason="Remove large color-book DBCOLOR metadata after modelspace and visual checks pass. Requires AutoCAD validation before acceptance.",
            )
        elif next_action == "remove_object_metadata":
            step = run_remove_object_metadata_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_sortents_tables":
            step = run_remove_sortents_tables_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_unused_symbol_table_records":
            step = run_remove_unused_symbol_table_records_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_paperspace_layouts":
            step = run_remove_paperspace_layouts_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_remaining_object_metadata":
            step = run_remove_remaining_object_metadata_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "strip_classes_and_acdsdata_sections":
            step = run_strip_sections_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                sections_to_remove={"CLASSES", "ACDSDATA"},
            )
        elif next_action == "remove_auxiliary_points_and_xlines":
            step = run_remove_auxiliary_points_and_xlines_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_unreachable_blocks_after_auxiliary":
            step = run_remove_unreachable_blocks_after_auxiliary_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_unused_tables_after_auxiliary":
            step = run_remove_unused_tables_after_auxiliary_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "remove_large_null_dictionary_shells":
            step = run_remove_large_null_dictionary_shells_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        elif next_action == "strip_regenerated_classes_section":
            step = run_strip_sections_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
                sections_to_remove={"CLASSES"},
                step_name="strip_regenerated_classes_section",
                step_title="Strip regenerated CLASSES section",
            )
        elif next_action == "rebuild_visible_modelspace":
            step = run_rebuild_visible_modelspace_step(
                current_path=current_path,
                reference_path=reference,
                out_dir=out_dir,
                step_number=next_step_number,
                dry_run_ai=dry_run_ai,
                skip_ai=skip_ai,
            )
        else:
            raise ValueError(f"Unsupported cleaning action: {next_action}")
        manifest["steps"].append(step)
        if step["status"] == "accepted":
            manifest["current_step"] = step["step"]
            manifest["current_dxf"] = step["accepted_after_dxf"]
            manifest["rollback_points"].append(
                {
                    "step": step["step"],
                    "label": step["title"],
                    "path": step["accepted_after_dxf"],
                }
            )
            upsert_rule(manifest, step)
        else:
            upsert_rejected_rule(manifest, step)
        step_after = step.get("accepted_after_dxf") or step.get("rejected_after_dxf") or step.get("candidate_after_dxf")
        if render_step_images_enabled and step.get("input_dxf") and step_after:
            step["visual_check"] = render_step_images(Path(step["step_dir"]), reference, Path(step["input_dxf"]), Path(step_after))
        write_rules_candidate(out_dir, manifest)
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)
        steps_remaining -= 1
        if step["status"] not in {"accepted", "rejected"}:
            break
    if render_final:
        write_final_visual_check(out_dir, manifest, dry_run_ai=dry_run_ai, skip_ai=skip_ai)
        write_manifest(out_dir, manifest)
        write_index_html(out_dir, manifest)


def validate_input_dxf(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} DXF not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} DXF path is not a file: {path}")
    if path.suffix.lower() != ".dxf":
        raise ValueError(f"{label} path must be a .dxf file: {path}")


def new_manifest(source: Path, reference: Path, out_dir: Path) -> dict[str, Any]:
    current_path = out_dir / "current.dxf"
    shutil.copy2(source, current_path)
    return {
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": str(source),
        "reference": str(reference),
        "out_dir": str(out_dir),
        "current_step": 0,
        "current_dxf": str(current_path),
        "steps": [],
        "rollback_points": [{"step": 0, "label": "original source", "path": str(source)}],
        "accepted_rules": [],
        "rejected_rules": [],
    }


def ensure_baseline(source: Path, reference: Path, out_dir: Path, manifest: dict[str, Any]) -> None:
    if any(step.get("name") == "baseline" for step in manifest["steps"]):
        return
    step_dir = out_dir / "steps" / "000_baseline"
    step_dir.mkdir(parents=True, exist_ok=True)
    source_stats = analyze_dxf(source)
    reference_stats = analyze_dxf(reference)
    write_json(step_dir / "source_stats.json", source_stats)
    write_json(step_dir / "reference_stats.json", reference_stats)
    report_path = step_dir / "report.html"
    report_path.write_text(build_baseline_html(source_stats, reference_stats), encoding="utf-8")
    manifest["steps"].append(
        {
            "step": 0,
            "name": "baseline",
            "title": "Baseline comparison",
            "status": "completed",
            "step_dir": str(step_dir),
            "report_html": str(report_path),
            "source_stats": str(step_dir / "source_stats.json"),
            "reference_stats": str(step_dir / "reference_stats.json"),
            "created_at": now_iso(),
        }
    )


def run_exact_duplicate_linework_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    signature_scope: str,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_exact_duplicate_linework"
    step_title = "Remove exact duplicate linework"
    step_dir = out_dir / "steps" / f"{step_number:03d}_exact_duplicate_linework"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    accepted_after_path = step_dir / "accepted_after.dxf"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_json_path = step_dir / "removed_entities.json"
    removed_dxf_path = step_dir / "removed_entities.dxf"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    ai_check_path = step_dir / "ai_check.json"
    report_path = step_dir / "report.html"

    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    candidates = collect_exact_duplicate_linework(doc, signature_scope=signature_scope)
    removed_payload = build_removed_payload(candidates, step_name, signature_scope)
    write_json(removed_json_path, removed_payload)
    write_removed_entities_dxf(doc, candidates, removed_dxf_path)

    removed_count = remove_candidates(doc, candidates)
    if removed_count:
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)

    after_stats = analyze_dxf(candidate_after_path)
    protection = run_protection_checks(before_stats, after_stats, removed_count)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)

    status = decide_step_status(
        removed_count=removed_count,
        before_stats=before_stats,
        after_stats=after_stats,
        protection=protection,
    )
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=removed_dxf_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status == "accepted":
        shutil.copy2(candidate_after_path, accepted_after_path)
        final_after_path = accepted_after_path
        write_rollback_script(out_dir, step_number, accepted_after_path)
    else:
        shutil.copy2(candidate_after_path, rejected_after_path)
        final_after_path = rejected_after_path

    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(final_after_path) if status == "accepted" else None,
        "rejected_after_dxf": str(final_after_path) if status != "accepted" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(removed_dxf_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "signature_scope": signature_scope,
        "exact_tolerance": EXACT_TOLERANCE,
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "entity_types": sorted(LINEAR_ENTITY_TYPES),
            "signature_scope": signature_scope,
            "tolerance": EXACT_TOLERANCE,
            "reason": "Exact duplicate linework removed after structure checks passed.",
        },
    }


def run_invisible_modelspace_entities_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_invisible_modelspace_entities"
    step_title = "Remove invisible modelspace entities"
    step_dir = out_dir / "steps" / f"{step_number:03d}_invisible_modelspace_entities"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    accepted_after_path = step_dir / "accepted_after.dxf"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_json_path = step_dir / "removed_entities.json"
    removed_dxf_path = step_dir / "removed_entities.dxf"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    ai_check_path = step_dir / "ai_check.json"
    report_path = step_dir / "report.html"

    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    candidates = collect_invisible_modelspace_entities(doc)
    removed_payload = build_removed_payload(candidates, step_name, "visibility")
    write_json(removed_json_path, removed_payload)
    write_removed_entities_dxf(doc, candidates, removed_dxf_path)

    removed_count = remove_candidates(doc, candidates)
    if removed_count:
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)

    after_stats = analyze_dxf(candidate_after_path)
    protection = run_visibility_protection_checks(before_stats, after_stats, removed_count)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    status = decide_visibility_step_status(
        removed_count=removed_count,
        before_stats=before_stats,
        after_stats=after_stats,
        protection=protection,
    )
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=removed_dxf_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status == "accepted":
        shutil.copy2(candidate_after_path, accepted_after_path)
        final_after_path = accepted_after_path
        write_rollback_script(out_dir, step_number, accepted_after_path)
    else:
        shutil.copy2(candidate_after_path, rejected_after_path)
        final_after_path = rejected_after_path

    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(final_after_path) if status == "accepted" else None,
        "rejected_after_dxf": str(final_after_path) if status != "accepted" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(removed_dxf_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "entity_types": "any",
            "reason": "Remove modelspace entities on off/frozen layers or with invisible DXF flags after visible-entity checks pass.",
        },
    }


def run_acad_layerstates_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_acad_layerstates"
    step_title = "Remove ACAD_LAYERSTATES object branch"
    step_dir = out_dir / "steps" / f"{step_number:03d}_acad_layerstates"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    accepted_after_path = step_dir / "accepted_after.dxf"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_json_path = step_dir / "removed_objects.json"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    ai_check_path = step_dir / "ai_check.json"
    report_path = step_dir / "report.html"

    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    branch = find_dictionary_branch(doc, "ACAD_LAYERSTATES")
    removed_payload = build_object_branch_payload(branch, step_name)
    write_json(removed_json_path, removed_payload)
    removed_count = remove_dictionary_branch(doc, branch)
    if removed_count:
        doc.objects.purge()
        doc.entitydb.purge()
        doc.saveas(candidate_after_path)
    else:
        shutil.copy2(input_path, candidate_after_path)

    after_stats = analyze_dxf(candidate_after_path)
    protection = run_object_branch_protection_checks(before_stats, after_stats, removed_count)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    status = decide_object_branch_step_status(
        removed_count=removed_count,
        before_stats=before_stats,
        after_stats=after_stats,
        protection=protection,
    )
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=input_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status == "accepted":
        shutil.copy2(candidate_after_path, accepted_after_path)
        final_after_path = accepted_after_path
        write_rollback_script(out_dir, step_number, accepted_after_path)
    else:
        shutil.copy2(candidate_after_path, rejected_after_path)
        final_after_path = rejected_after_path

    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(final_after_path) if status == "accepted" else None,
        "rejected_after_dxf": str(final_after_path) if status != "accepted" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(input_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "dictionary_key": "ACAD_LAYERSTATES",
            "reason": "Remove historical layer-state metadata branch after modelspace and visibility checks pass.",
        },
    }


def run_remove_unused_appids_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_unused_appids"
    step_title = "Remove unreferenced APPID table records"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_unused_appids"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_json_path = step_dir / "removed_appids.json"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    ai_check_path = step_dir / "ai_check.json"
    report_path = step_dir / "report.html"

    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    used_appids = collect_used_appids(doc)
    all_appids = [str(appid.dxf.name) for appid in doc.appids]
    removed: list[str] = []
    for name in all_appids:
        if name in used_appids:
            continue
        try:
            doc.appids.remove(name)
            removed.append(name)
        except Exception:
            continue
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed),
        "entity_type_counts": {},
        "layer_counts": {},
        "used_appids": sorted(used_appids),
        "removed_appids_count": len(removed),
        "removed_appids_sample": removed[:200],
        "notes": "Candidate only: AutoCAD 2024 validation is required before accepting this table cleanup.",
    }
    write_json(removed_json_path, removed_payload)
    protection = run_table_cleanup_protection_checks(before_stats, after_stats)
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    status = "needs_manual_review" if len(removed) > 0 and protection["status"] == "passed" else "rejected"
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=input_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status != "needs_manual_review":
        shutil.copy2(candidate_after_path, rejected_after_path)
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": None,
        "rejected_after_dxf": str(rejected_after_path) if status != "needs_manual_review" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(input_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": len(removed),
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "reason": "Remove APPID table records not referenced by any XDATA. Requires AutoCAD validation before acceptance.",
        },
    }


def collect_used_appids(doc: DxfDrawing) -> set[str]:
    used = {"ACAD"}
    for entity in doc.entitydb.values():
        xdata = getattr(entity, "xdata", None)
        if not xdata or not hasattr(xdata, "data"):
            continue
        try:
            used.update(str(name) for name in xdata.data.keys())
        except Exception:
            continue
    return used


def run_unreviewed_candidate_common(
    step_number: int,
    step_name: str,
    step_title: str,
    step_dir: Path,
    input_path: Path,
    candidate_after_path: Path,
    reference_path: Path,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    protection: dict[str, Any],
    dry_run_ai: bool,
    skip_ai: bool,
    removed_json_path: Path,
    rule: dict[str, Any],
) -> dict[str, Any]:
    ai_check_path = step_dir / "ai_check.json"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    report_path = step_dir / "report.html"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_count = int(removed_payload.get("removed_count", 0))
    status = "needs_manual_review" if removed_count > 0 and protection["status"] == "passed" else "rejected"
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    write_json(removed_json_path, removed_payload)
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=input_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status == "rejected":
        shutil.copy2(candidate_after_path, rejected_after_path)
    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": None,
        "rejected_after_dxf": str(rejected_after_path) if status == "rejected" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(input_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": removed_count,
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": rule,
    }


def run_remove_unreachable_blocks_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_unreachable_blocks"
    step_title = "Remove unreachable block definitions"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_unreachable_blocks"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_blocks.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    reachable = collect_reachable_blocks(doc)
    all_blocks = {block.name for block in doc.blocks}
    remove_names = sorted(all_blocks - reachable)
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
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_block_cleanup_protection_checks(before_stats, after_stats, removed_count=len(removed))
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed),
        "entity_type_counts": {},
        "layer_counts": {},
        "reachable_block_count": len(reachable),
        "removed_block_count": len(removed),
        "removed_block_entity_count": sum(int(item["entity_count"]) for item in removed),
        "removed_blocks_sample": removed[:200],
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": (
            "High-risk candidate: removes anonymous and named block definitions not reachable from layouts, "
            "nested INSERTs, DIMENSION geometry blocks, or DIMSTYLE arrow blocks. AutoCAD validation is required."
        ),
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove block definitions not reachable from layouts, nested block references, dimensions, or dimstyles. Requires AutoCAD validation before acceptance.",
            "requires_manual_autocad_validation": True,
        },
    )


def collect_reachable_blocks(doc: DxfDrawing) -> set[str]:
    all_blocks = {block.name for block in doc.blocks}
    queue: list[str] = []
    reachable: set[str] = set()
    for layout in doc.layouts:
        try:
            block_name = layout.block_record_name
        except Exception:
            continue
        if block_name in all_blocks:
            queue.append(block_name)
    for dimstyle in doc.dimstyles:
        for attr in ("dimblk", "dimblk1", "dimblk2", "dimldrblk"):
            try:
                block_name = getattr(dimstyle.dxf, attr)
            except Exception:
                block_name = None
            if block_name and block_name in all_blocks:
                queue.append(str(block_name))
    while queue:
        block_name = queue.pop(0)
        if block_name in reachable:
            continue
        reachable.add(block_name)
        try:
            block = doc.blocks.get(block_name)
        except Exception:
            continue
        for entity in block:
            for ref_name in entity_block_references(entity):
                if ref_name in all_blocks and ref_name not in reachable:
                    queue.append(ref_name)
    return reachable


def entity_block_references(entity: object) -> list[str]:
    refs: list[str] = []
    try:
        entity_type = entity.dxftype()
    except Exception:
        return refs
    if entity_type == "INSERT":
        try:
            refs.append(str(entity.dxf.name))
        except Exception:
            pass
    elif entity_type == "DIMENSION":
        try:
            geometry = entity.dxf.geometry
        except Exception:
            geometry = None
        if geometry:
            refs.append(str(geometry))
    return refs


def run_dictionary_branch_candidate_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
    step_name: str,
    step_title: str,
    dictionary_key: str,
    reason: str,
) -> dict[str, Any]:
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_objects.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    branch = find_dictionary_branch(doc, dictionary_key)
    removed_payload = build_object_branch_payload(branch, step_name)
    removed_payload["notes"] = reason
    removed_count = remove_dictionary_branch(doc, branch)
    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_object_branch_protection_checks(before_stats, after_stats, removed_count)
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "dictionary_key": dictionary_key,
            "reason": reason,
            "requires_manual_autocad_validation": True,
        },
    )


def run_remove_object_metadata_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_object_metadata"
    step_title = "Remove OBJECTS metadata: ACAD_COLOR and SORTENTSTABLE"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_object_metadata"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_objects.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)

    color_branch = find_dictionary_branch(doc, "ACAD_COLOR")
    color_payload = build_object_branch_payload(color_branch, step_name)
    removed_color_count = remove_dictionary_branch(doc, color_branch)

    removed_sortents: list[dict[str, str]] = []
    failed_sortents: list[dict[str, str]] = []
    for obj in list(doc.objects):
        if obj.dxftype() != "SORTENTSTABLE":
            continue
        handle = str(getattr(obj.dxf, "handle", ""))
        owner = str(getattr(obj.dxf, "owner", ""))
        try:
            obj.destroy()
            removed_sortents.append({"handle": handle, "owner": owner})
        except Exception as exc:
            failed_sortents.append({"handle": handle, "error": f"{type(exc).__name__}: {exc}"})

    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    removed_count = int(removed_color_count) + len(removed_sortents)
    protection = run_object_branch_protection_checks(before_stats, after_stats, removed_count)
    removed_payload = {
        "step_name": step_name,
        "removed_count": removed_count,
        "entity_type_counts": {
            "ACAD_COLOR_branch_objects": int(removed_color_count),
            "SORTENTSTABLE": len(removed_sortents),
        },
        "layer_counts": {},
        "acad_color_removed_count": int(removed_color_count),
        "acad_color_sample": color_payload.get("objects", [])[:200],
        "sortents_removed_count": len(removed_sortents),
        "sortents_removed_sample": removed_sortents[:200],
        "sortents_failed_count": len(failed_sortents),
        "sortents_failed_sample": failed_sortents[:50],
        "notes": "OBJECTS candidate: removes large color-book metadata and draw-order sort tables. AutoCAD validation is required before acceptance.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove ACAD_COLOR color-book metadata and SORTENTSTABLE draw-order objects after modelspace and visual checks pass. Requires AutoCAD validation before acceptance.",
            "requires_manual_autocad_validation": True,
        },
    )


def run_remove_sortents_tables_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_sortents_tables"
    step_title = "Remove SORTENTSTABLE objects"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_sortents_tables"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_sortents.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    removed: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for obj in list(doc.objects):
        if obj.dxftype() != "SORTENTSTABLE":
            continue
        handle = str(getattr(obj.dxf, "handle", ""))
        owner = str(getattr(obj.dxf, "owner", ""))
        try:
            obj.destroy()
            removed.append({"handle": handle, "owner": owner})
        except Exception as exc:
            failed.append({"handle": handle, "error": f"{type(exc).__name__}: {exc}"})
    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_object_branch_protection_checks(before_stats, after_stats, len(removed))
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed),
        "entity_type_counts": {"SORTENTSTABLE": len(removed)},
        "layer_counts": {},
        "removed_objects_sample": removed[:200],
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "High-risk candidate: removes draw-order sort tables. AutoCAD validation is required before acceptance.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove draw-order sort tables after modelspace and visual checks pass. Requires AutoCAD validation before acceptance.",
            "requires_manual_autocad_validation": True,
        },
    )


def run_remove_unused_symbol_table_records_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_unused_symbol_table_records"
    step_title = "Remove unused layers, styles, linetypes, and dimstyles"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_unused_symbol_table_records"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_symbol_table_records.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    used = collect_used_symbol_table_records(doc)
    removed: dict[str, list[str]] = {"layers": [], "styles": [], "linetypes": [], "dimstyles": []}
    failed: list[dict[str, str]] = []
    for record in list(doc.layers):
        name = str(record.dxf.name)
        if name not in used["layers"] and name not in {"0", "Defpoints"}:
            try:
                doc.layers.remove(name)
                removed["layers"].append(name)
            except Exception as exc:
                failed.append({"table": "LAYER", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.styles):
        name = str(record.dxf.name)
        if name not in used["styles"] and name != "Standard":
            try:
                doc.styles.remove(name)
                removed["styles"].append(name)
            except Exception as exc:
                failed.append({"table": "STYLE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.linetypes):
        name = str(record.dxf.name)
        if name not in used["linetypes"] and name not in {"ByBlock", "ByLayer", "Continuous"}:
            try:
                doc.linetypes.remove(name)
                removed["linetypes"].append(name)
            except Exception as exc:
                failed.append({"table": "LTYPE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.dimstyles):
        name = str(record.dxf.name)
        if name not in used["dimstyles"] and name != "Standard":
            try:
                doc.dimstyles.remove(name)
                removed["dimstyles"].append(name)
            except Exception as exc:
                failed.append({"table": "DIMSTYLE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_symbol_table_cleanup_protection_checks(before_stats, after_stats)
    removed_count = sum(len(items) for items in removed.values())
    removed_payload = {
        "step_name": step_name,
        "removed_count": removed_count,
        "entity_type_counts": {},
        "layer_counts": {},
        "removed_counts": {key: len(value) for key, value in removed.items()},
        "removed_sample": {key: value[:100] for key, value in removed.items()},
        "used_records": {key: sorted(value) for key, value in used.items()},
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "Candidate only: removes symbol table records not used by modelspace or retained blocks. AutoCAD validation is required.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove unused LAYER/STYLE/LTYPE/DIMSTYLE records after modelspace and visual checks pass. Requires AutoCAD validation before acceptance.",
            "requires_manual_autocad_validation": True,
        },
    )


def collect_used_symbol_table_records(doc: DxfDrawing) -> dict[str, set[str]]:
    used = {
        "layers": {"0", "Defpoints"},
        "styles": {"Standard"},
        "linetypes": {"ByBlock", "ByLayer", "Continuous"},
        "dimstyles": {"Standard"},
    }
    spaces: list[Any] = [doc.modelspace()]
    spaces.extend(list(doc.blocks))
    for space in spaces:
        for entity in space:
            for attr, key in (
                ("layer", "layers"),
                ("style", "styles"),
                ("linetype", "linetypes"),
                ("dimstyle", "dimstyles"),
            ):
                try:
                    value = getattr(entity.dxf, attr)
                except Exception:
                    value = None
                if value:
                    used[key].add(str(value))
    return used


def run_remove_paperspace_layouts_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_paperspace_layouts"
    step_title = "Remove paper-space layouts"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_paperspace_layouts"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_paperspace_layouts.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)

    paperspaces = [layout for layout in list(doc.layouts) if layout.name.lower() != "model"]
    removed_layouts: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    keep_layout_name = None
    if paperspaces:
        keep_layout_name = paperspaces[0].name
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
    if keep_layout_name:
        try:
            keep_layout = doc.layouts.get(keep_layout_name)
            for entity in list(keep_layout):
                entity.destroy()
                cleared_entities += 1
            keep_layout.entity_space.purge()
        except Exception as exc:
            failed.append({"name": str(keep_layout_name), "error": f"clear kept paperspace failed: {type(exc).__name__}: {exc}"})

    doc.entitydb.purge()
    doc.objects.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_paperspace_cleanup_protection_checks(before_stats, after_stats)
    removed_count = len(removed_layouts) + cleared_entities
    removed_payload = {
        "step_name": step_name,
        "removed_count": removed_count,
        "entity_type_counts": {},
        "layer_counts": {},
        "kept_paperspace_layout": keep_layout_name,
        "removed_layout_count": len(removed_layouts),
        "removed_layouts": removed_layouts,
        "cleared_kept_paperspace_entity_count": cleared_entities,
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "Candidate only: removes paper-space layouts and clears the retained paper-space layout. Modelspace is preserved; AutoCAD validation is required before acceptance.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove paper-space layouts and paper-space-only block data after modelspace and visual checks pass. Requires AutoCAD validation before acceptance.",
            "requires_manual_autocad_validation": True,
        },
    )


def run_remove_remaining_object_metadata_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_remaining_object_metadata"
    step_title = "Remove remaining non-geometry OBJECTS metadata"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_remaining_object_metadata"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_remaining_object_metadata.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)

    dictionary_keys = [
        "ACAD_SCALELIST",
        "ACAD_VISUALSTYLE",
        "ACAD_IMAGE_DICT",
        "ACAD_DETAILVIEWSTYLE",
        "ACAD_SECTIONVIEWSTYLE",
        "ACAD_PLOTSETTINGS",
        "ACAD_PLOTSTYLENAME",
        "ACAD_RENDER_ACTIVE_RAPIDRT_SETTINGS",
        "ACAD_RENDER_ACTIVE_SETTINGS",
        "ACAD_CIP_PREVIOUS_PRODUCT_INFO",
        "ACAD_LAST_SAVED_VERSION_INFO",
        "ASE_INDEX_DICTIONARY",
        "AcSheetSetData",
        "EZDXF_META",
    ]
    removed_branches: list[dict[str, Any]] = []
    removed_type_counts: Counter[str] = Counter()
    removed_count = 0
    for key in dictionary_keys:
        branch = find_dictionary_branch(doc, key)
        payload = build_object_branch_payload(branch, step_name)
        branch_count = remove_dictionary_branch(doc, branch)
        if branch_count:
            removed_branches.append(payload)
            removed_count += branch_count
            removed_type_counts.update(payload.get("entity_type_counts", {}))

    orphan_payloads: list[dict[str, Any]] = []
    for orphan_branch in find_orphan_large_color_dictionaries(doc):
        payload = build_object_branch_payload(orphan_branch, step_name)
        branch_count = remove_dictionary_branch(doc, orphan_branch)
        if branch_count:
            orphan_payloads.append(payload)
            removed_count += branch_count
            removed_type_counts.update(payload.get("entity_type_counts", {}))

    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_object_branch_protection_checks(before_stats, after_stats, removed_count)
    removed_payload = {
        "step_name": step_name,
        "removed_count": removed_count,
        "entity_type_counts": dict(removed_type_counts.most_common()),
        "layer_counts": {},
        "removed_dictionary_keys": [item.get("dictionary_key") for item in removed_branches],
        "removed_branches": removed_branches,
        "removed_orphan_large_color_dictionaries": orphan_payloads,
        "notes": (
            "Removes OBJECTS branches that do not describe visible modelspace geometry: "
            "scale list, visual styles, image/detail/section view dictionaries, plot/render "
            "settings, saved-version metadata, ASE index data, sheet-set data, ezdxf metadata, "
            "and orphan large DBCOLOR dictionaries."
        ),
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "dictionary_keys": dictionary_keys,
            "reason": "Remove remaining OBJECTS metadata after modelspace and cropped visual checks pass.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_strip_sections_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
    sections_to_remove: set[str],
    step_name: str = "strip_classes_and_acdsdata_sections",
    step_title: str = "Strip CLASSES and ACDSDATA sections",
) -> dict[str, Any]:
    step_dir = out_dir / "steps" / f"{step_number:03d}_{step_name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_sections.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    strip_result = strip_dxf_sections(input_path, candidate_after_path, sections_to_remove)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_section_strip_protection_checks(before_stats, after_stats, strip_result)
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(strip_result["removed_sections"]),
        "entity_type_counts": {"SECTION": len(strip_result["removed_sections"])},
        "layer_counts": {},
        "removed_sections": strip_result["removed_sections"],
        "removed_section_names": sorted(strip_result["removed_sections"].keys()),
        "notes": (
            "Raw DXF section strip: removes non-geometry sections only. These sections carry "
            "class definitions or application custom data, not modelspace drawing entities."
        ),
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "sections": sorted(sections_to_remove),
            "reason": "Strip non-geometry sections after reload, structure, and visual checks pass.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_remove_auxiliary_points_and_xlines_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_auxiliary_points_and_xlines"
    step_title = "Remove auxiliary POINT/XLINE/RAY modelspace entities"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_auxiliary_points_and_xlines"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_auxiliary_entities.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    reference_stats = analyze_dxf(reference_path)
    doc = load_dxf(input_path)

    candidates: list[DuplicateCandidate] = []
    for entity in doc.modelspace():
        entity_type = entity.dxftype()
        if entity_type not in AI_RENDER_EXCLUDED_ENTITY_TYPES:
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        candidates.append(
            DuplicateCandidate(
                entity=entity,
                handle=str(getattr(entity.dxf, "handle", "") or "") or None,
                entity_type=entity_type,
                layer=layer,
                signature=("auxiliary", entity_type, layer, str(getattr(entity.dxf, "handle", "") or "")),
                reason="auxiliary point/infinite construction entity not present in reference modelspace",
            )
        )
    removed_payload = build_removed_payload(candidates, step_name, signature_scope="auxiliary_entity_type")
    removed_payload["reference_modelspace_entity_count"] = reference_stats["modelspace"]["entity_count"]
    removed_payload["expected_after_entity_count"] = int(before_stats["modelspace"]["entity_count"]) - len(candidates)
    removed_payload["notes"] = (
        "Removes only POINT/XLINE/RAY from modelspace. These entities are excluded from the cropped "
        "visual review renderer and are absent from the reference DXF modelspace."
    )
    removed_count = remove_candidates(doc, candidates)
    doc.entitydb.purge()
    doc.objects.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_auxiliary_entity_cleanup_protection_checks(
        before_stats=before_stats,
        after_stats=after_stats,
        reference_stats=reference_stats,
        removed_payload=removed_payload,
        removed_count=removed_count,
    )
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "entity_types": sorted(AI_RENDER_EXCLUDED_ENTITY_TYPES),
            "reason": "Remove modelspace POINT/XLINE/RAY auxiliary entities after reference comparison and cropped visual checks pass.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_remove_unreachable_blocks_after_auxiliary_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_unreachable_blocks_after_auxiliary"
    step_title = "Remove blocks unreachable after auxiliary entity cleanup"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_unreachable_blocks_after_auxiliary"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_blocks_after_auxiliary.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    reachable = collect_reachable_blocks(doc)
    removed_blocks: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for block in list(doc.blocks):
        name = str(block.name)
        if name in reachable:
            continue
        removed_blocks.append(
            {
                "name": name,
                "entity_count": len(block),
                "entity_type_counts": dict(Counter(entity.dxftype() for entity in block).most_common()),
            }
        )
        try:
            doc.blocks.delete_block(name, safe=False)
        except Exception as exc:
            failed.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
            removed_blocks.pop()
    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_block_cleanup_protection_checks(before_stats, after_stats, len(removed_blocks))
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed_blocks),
        "entity_type_counts": {},
        "layer_counts": {},
        "reachable_block_count": len(reachable),
        "removed_blocks": removed_blocks,
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "Second-pass block cleanup after POINT/XLINE/RAY removal. Modelspace geometry is preserved.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove block definitions that became unreachable after auxiliary modelspace entities were removed.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_remove_unused_tables_after_auxiliary_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_unused_tables_after_auxiliary"
    step_title = "Remove table records unused after auxiliary cleanup"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_unused_tables_after_auxiliary"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_tables_after_auxiliary.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    used_symbols = collect_used_symbol_table_records(doc)
    used_appids = collect_used_appids(doc)
    removed: dict[str, list[str]] = {"layers": [], "linetypes": [], "styles": [], "dimstyles": [], "appids": []}
    failed: list[dict[str, str]] = []
    for record in list(doc.layers):
        name = str(record.dxf.name)
        if name not in used_symbols["layers"] and name not in {"0", "Defpoints"}:
            try:
                doc.layers.remove(name)
                removed["layers"].append(name)
            except Exception as exc:
                failed.append({"table": "LAYER", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.linetypes):
        name = str(record.dxf.name)
        if name not in used_symbols["linetypes"] and name not in {"ByBlock", "ByLayer", "Continuous"}:
            try:
                doc.linetypes.remove(name)
                removed["linetypes"].append(name)
            except Exception as exc:
                failed.append({"table": "LTYPE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.styles):
        name = str(record.dxf.name)
        if name not in used_symbols["styles"] and name != "Standard":
            try:
                doc.styles.remove(name)
                removed["styles"].append(name)
            except Exception as exc:
                failed.append({"table": "STYLE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.dimstyles):
        name = str(record.dxf.name)
        if name not in used_symbols["dimstyles"] and name != "Standard":
            try:
                doc.dimstyles.remove(name)
                removed["dimstyles"].append(name)
            except Exception as exc:
                failed.append({"table": "DIMSTYLE", "name": name, "error": f"{type(exc).__name__}: {exc}"})
    for record in list(doc.appids):
        name = str(record.dxf.name)
        if name not in used_appids and name != "ACAD":
            try:
                doc.appids.remove(name)
                removed["appids"].append(name)
            except Exception as exc:
                failed.append({"table": "APPID", "name": name, "error": f"{type(exc).__name__}: {exc}"})

    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_secondary_table_cleanup_protection_checks(before_stats, after_stats, removed)
    removed_count = sum(len(items) for items in removed.values())
    removed_payload = {
        "step_name": step_name,
        "removed_count": removed_count,
        "entity_type_counts": {},
        "layer_counts": {},
        "removed_counts": {key: len(value) for key, value in removed.items()},
        "removed_records": removed,
        "used_symbols": {key: sorted(value) for key, value in used_symbols.items()},
        "used_appids_count": len(used_appids),
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "Second-pass table cleanup after auxiliary entity and block cleanup.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove layer, linetype, style, dimstyle, and APPID table records unused after auxiliary cleanup.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_remove_large_null_dictionary_shells_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "remove_large_null_dictionary_shells"
    step_title = "Remove large null OBJECTS dictionary shells"
    step_dir = out_dir / "steps" / f"{step_number:03d}_remove_large_null_dictionary_shells"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    removed_json_path = step_dir / "removed_large_null_dictionary_shells.json"
    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    doc = load_dxf(input_path)
    candidates = find_large_null_dictionary_shells(doc)
    removed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for dictionary in candidates:
        handle = str(getattr(dictionary.dxf, "handle", ""))
        owner = str(getattr(dictionary.dxf, "owner", ""))
        try:
            items = list(dictionary.items())
        except Exception:
            items = []
        item_count = len(items)
        null_reference_count = sum(1 for _, child in items if isinstance(child, str) and child == "0")
        sample_keys = [str(key) for key, _ in items[:20]]
        parent_refs = remove_dictionary_references(doc, handle)
        try:
            doc.objects.delete_entity(dictionary)
            removed.append(
                {
                    "handle": handle,
                    "owner": owner,
                    "item_count": item_count,
                    "null_reference_count": null_reference_count,
                    "parent_references_removed": parent_refs,
                    "sample_keys": sample_keys,
                }
            )
        except Exception as exc:
            failed.append({"handle": handle, "error": f"{type(exc).__name__}: {exc}"})
    doc.objects.purge()
    doc.entitydb.purge()
    doc.saveas(candidate_after_path)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_object_branch_protection_checks(before_stats, after_stats, len(removed))
    removed_payload = {
        "step_name": step_name,
        "removed_count": len(removed),
        "entity_type_counts": {"DICTIONARY": len(removed)},
        "layer_counts": {},
        "removed_dictionaries": removed,
        "failed_count": len(failed),
        "failed_sample": failed[:50],
        "notes": "Removes large OBJECTS dictionaries whose entries point to string '0' instead of real DXF objects.",
    }
    return run_unreviewed_candidate_common(
        step_number=step_number,
        step_name=step_name,
        step_title=step_title,
        step_dir=step_dir,
        input_path=input_path,
        candidate_after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
        removed_json_path=removed_json_path,
        rule={
            "name": step_name,
            "reason": "Remove large null dictionary shells after modelspace and cropped visual checks pass.",
            "requires_manual_autocad_validation": False,
            "final_autocad_validation_deferred": True,
        },
    )


def run_rebuild_visible_modelspace_step(
    current_path: Path,
    reference_path: Path,
    out_dir: Path,
    step_number: int,
    dry_run_ai: bool,
    skip_ai: bool,
) -> dict[str, Any]:
    step_name = "rebuild_visible_modelspace"
    step_title = "Rebuild DXF from visible modelspace"
    step_dir = out_dir / "steps" / f"{step_number:03d}_rebuild_visible_modelspace"
    step_dir.mkdir(parents=True, exist_ok=True)
    input_path = step_dir / "input.dxf"
    candidate_after_path = step_dir / "candidate_after.dxf"
    accepted_after_path = step_dir / "accepted_after.dxf"
    rejected_after_path = step_dir / "rejected_after.dxf"
    removed_json_path = step_dir / "omitted_data.json"
    before_stats_path = step_dir / "before_stats.json"
    after_stats_path = step_dir / "after_stats.json"
    ai_check_path = step_dir / "ai_check.json"
    report_path = step_dir / "report.html"

    shutil.copy2(current_path, input_path)
    before_stats = analyze_dxf(input_path)
    rebuild_result = rebuild_visible_modelspace_dxf(input_path, candidate_after_path)
    removed_payload = build_rebuild_payload(before_stats, rebuild_result, step_name)
    write_json(removed_json_path, removed_payload)
    after_stats = analyze_dxf(candidate_after_path)
    protection = run_rebuild_protection_checks(before_stats, after_stats, rebuild_result["copied_count"])
    ai_check = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name=step_name)
    write_json(ai_check_path, ai_check)
    write_json(before_stats_path, before_stats)
    write_json(after_stats_path, after_stats)
    status = decide_rebuild_step_status(
        copied_count=int(rebuild_result["copied_count"]),
        before_stats=before_stats,
        after_stats=after_stats,
        protection=protection,
    )
    if status == "accepted":
        status = "rejected"
        protection = {
            **protection,
            "status": "failed",
            "checks": [
                *protection.get("checks", []),
                {
                    "name": "autocad_rebuild_compatibility",
                    "status": "failed",
                    "message": "visible-modelspace rebuild is a retained rejected stage; AutoCAD 2024 validation failed in the experiment",
                },
            ],
        }
    report = build_step_html(
        step_number=step_number,
        title=step_title,
        status=status,
        input_path=input_path,
        after_path=candidate_after_path,
        reference_path=reference_path,
        before_stats=before_stats,
        after_stats=after_stats,
        removed_payload=removed_payload,
        protection=protection,
        ai_check=ai_check,
        removed_json_path=removed_json_path,
        removed_dxf_path=input_path,
    )
    report_path.write_text(report, encoding="utf-8")
    if status == "accepted":
        shutil.copy2(candidate_after_path, accepted_after_path)
        final_after_path = accepted_after_path
        write_rollback_script(out_dir, step_number, accepted_after_path)
    else:
        shutil.copy2(candidate_after_path, rejected_after_path)
        final_after_path = rejected_after_path

    return {
        "step": step_number,
        "name": step_name,
        "title": step_title,
        "status": status,
        "step_dir": str(step_dir),
        "input_dxf": str(input_path),
        "candidate_after_dxf": str(candidate_after_path),
        "accepted_after_dxf": str(final_after_path) if status == "accepted" else None,
        "rejected_after_dxf": str(final_after_path) if status != "accepted" else None,
        "before_stats": str(before_stats_path),
        "after_stats": str(after_stats_path),
        "removed_entities_json": str(removed_json_path),
        "removed_entities_dxf": str(input_path),
        "ai_check": str(ai_check_path),
        "report_html": str(report_path),
        "removed_count": int(before_stats["modelspace"]["entity_count"]) - int(after_stats["modelspace"]["entity_count"]),
        "copied_count": int(rebuild_result["copied_count"]),
        "file_size_before": before_stats["file"]["size_bytes"],
        "file_size_after": after_stats["file"]["size_bytes"],
        "created_at": now_iso(),
        "protection": protection,
        "rule": {
            "name": step_name,
            "reason": "Create a fresh DXF containing only visible modelspace entities and their used layers.",
        },
    }


def rebuild_visible_modelspace_dxf(input_path: Path, output_path: Path) -> dict[str, Any]:
    source_doc = load_dxf(input_path)
    new_doc = ezdxf.new(source_doc.dxfversion)
    used_layers: list[str] = []
    visible_entities: list[object] = []
    for entity in source_doc.modelspace():
        if not is_entity_visible(source_doc, entity):
            continue
        visible_entities.append(entity)
        layer = str(getattr(entity.dxf, "layer", "0"))
        if layer not in used_layers:
            used_layers.append(layer)
    for layer_name in used_layers:
        if layer_name in new_doc.layers:
            continue
        try:
            old_layer = source_doc.layers.get(layer_name)
            new_doc.layers.add(
                layer_name,
                color=getattr(old_layer.dxf, "color", 7),
                linetype=getattr(old_layer.dxf, "linetype", "CONTINUOUS"),
            )
        except Exception:
            new_doc.layers.add(layer_name)
    copied = 0
    failed: list[dict[str, Any]] = []
    new_msp = new_doc.modelspace()
    for entity in visible_entities:
        try:
            new_msp.add_entity(entity.copy())
            copied += 1
        except Exception as exc:
            failed.append(
                {
                    "entity_type": entity.dxftype(),
                    "handle": str(getattr(entity.dxf, "handle", "")),
                    "layer": str(getattr(entity.dxf, "layer", "0")),
                    "message": str(exc),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    new_doc.saveas(output_path)
    return {"copied_count": copied, "failed_count": len(failed), "failed": failed, "used_layers": used_layers}


def build_rebuild_payload(before_stats: dict[str, Any], rebuild_result: dict[str, Any], step_name: str) -> dict[str, Any]:
    sections = before_stats["sections"]["sections"]
    omitted_sections = {
        name: stats
        for name, stats in sections.items()
        if name in {"BLOCKS", "OBJECTS", "TABLES", "ACDSDATA", "CLASSES"}
    }
    return {
        "step_name": step_name,
        "removed_count": 0,
        "entity_type_counts": {},
        "layer_counts": {},
        "copied_visible_modelspace_entities": rebuild_result["copied_count"],
        "failed_copy_count": rebuild_result["failed_count"],
        "failed": rebuild_result["failed"],
        "used_layers": rebuild_result["used_layers"],
        "omitted_sections_from_source_snapshot": omitted_sections,
        "omitted_table_counts": before_stats["tables"],
        "omitted_object_counts": before_stats.get("objects", {}),
        "notes": "The full pre-rebuild DXF is preserved as this step's input.dxf rollback/audit snapshot.",
    }


def collect_exact_duplicate_linework(doc: DxfDrawing, signature_scope: str) -> list[DuplicateCandidate]:
    seen: dict[tuple[Any, ...], object] = {}
    candidates: list[DuplicateCandidate] = []
    for entity in doc.modelspace():
        entity_type = entity.dxftype()
        if entity_type not in LINEAR_ENTITY_TYPES:
            continue
        try:
            signature = entity_signature(entity, tolerance=EXACT_TOLERANCE, scope=signature_scope)
        except Exception:
            continue
        if signature not in seen:
            seen[signature] = entity
            continue
        candidates.append(
            DuplicateCandidate(
                entity=entity,
                handle=str(getattr(entity.dxf, "handle", "") or "") or None,
                entity_type=entity_type,
                layer=str(getattr(entity.dxf, "layer", "0")),
                signature=signature,
                reason="exact duplicate linework",
            )
        )
    return candidates


def collect_invisible_modelspace_entities(doc: DxfDrawing) -> list[DuplicateCandidate]:
    candidates: list[DuplicateCandidate] = []
    for entity in doc.modelspace():
        if is_entity_visible(doc, entity):
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        candidates.append(
            DuplicateCandidate(
                entity=entity,
                handle=str(getattr(entity.dxf, "handle", "") or "") or None,
                entity_type=entity.dxftype(),
                layer=layer,
                signature=("visibility", layer, str(getattr(entity.dxf, "handle", "") or "")),
                reason=invisible_reason(doc, entity),
            )
        )
    return candidates


def find_dictionary_branch(doc: DxfDrawing, key: str) -> dict[str, Any] | None:
    for obj in doc.objects:
        if obj.dxftype() != "DICTIONARY":
            continue
        try:
            if key in obj:
                target = obj.get(key)
                return {"parent": obj, "key": key, "target": target}
        except Exception:
            continue
    return None


def build_object_branch_payload(branch: dict[str, Any] | None, step_name: str) -> dict[str, Any]:
    if branch is None:
        return {
            "step_name": step_name,
            "removed_count": 0,
            "entity_type_counts": {},
            "layer_counts": {},
            "objects": [],
            "notes": "ACAD_LAYERSTATES dictionary branch was not found.",
        }
    parent = branch["parent"]
    target = branch["target"]
    objects = collect_dictionary_branch_objects(target)
    type_counts = Counter(obj.dxftype() for obj in objects)
    return {
        "step_name": step_name,
        "dictionary_key": branch["key"],
        "parent_handle": str(getattr(parent.dxf, "handle", "")),
        "parent_owner": str(getattr(parent.dxf, "owner", "")),
        "target_handle": str(getattr(target.dxf, "handle", "")),
        "target_type": target.dxftype(),
        "removed_count": len(objects),
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts": {},
        "objects": [object_summary(obj, key=name) for name, obj in dictionary_items(target)],
        "notes": "The full pre-clean branch is preserved in this step's input.dxf rollback snapshot.",
    }


def collect_dictionary_branch_objects(target: object) -> list[object]:
    objects = [target] if hasattr(target, "dxftype") else []
    for _, child in dictionary_items(target):
        if hasattr(child, "dxftype"):
            objects.append(child)
    return objects


def dictionary_items(dictionary: object) -> list[tuple[str, object]]:
    if dictionary is None or dictionary.dxftype() != "DICTIONARY":
        return []
    try:
        return list(dictionary.items())
    except Exception:
        return []


def object_summary(obj: object, key: str | None = None) -> dict[str, Any]:
    tag_count = 0
    if hasattr(obj, "tags"):
        try:
            tag_count = len(obj.tags)
        except Exception:
            tag_count = 0
    dxf_namespace = getattr(obj, "dxf", None)
    return {
        "key": key,
        "handle": str(getattr(dxf_namespace, "handle", "")),
        "owner": str(getattr(dxf_namespace, "owner", "")),
        "object_type": obj.dxftype() if hasattr(obj, "dxftype") else type(obj).__name__,
        "tag_count": tag_count,
    }


def remove_dictionary_branch(doc: DxfDrawing, branch: dict[str, Any] | None) -> int:
    if branch is None:
        return 0
    target = branch["target"]
    objects = collect_dictionary_branch_objects(target)
    for obj in objects[1:]:
        try:
            doc.objects.delete_entity(obj)
        except Exception:
            continue
    try:
        del branch["parent"][branch["key"]]
    except Exception:
        try:
            doc.objects.delete_entity(target)
        except Exception:
            pass
    return len(objects)


def find_orphan_large_color_dictionaries(doc: DxfDrawing) -> list[dict[str, Any]]:
    referenced_handles: set[str] = set()
    for obj in doc.objects:
        if obj.dxftype() != "DICTIONARY":
            continue
        for _, child in dictionary_items(obj):
            if not hasattr(child, "dxftype"):
                continue
            handle = str(getattr(getattr(child, "dxf", None), "handle", ""))
            if handle:
                referenced_handles.add(handle)

    branches: list[dict[str, Any]] = []
    for obj in doc.objects:
        if obj.dxftype() != "DICTIONARY":
            continue
        handle = str(getattr(getattr(obj, "dxf", None), "handle", ""))
        if not handle or handle in referenced_handles:
            continue
        items = dictionary_items(obj)
        if len(items) < 50:
            continue
        child_types = Counter(child.dxftype() for _, child in items if hasattr(child, "dxftype"))
        color_like_count = child_types.get("DBCOLOR", 0) + child_types.get("ACDBPLACEHOLDER", 0)
        if color_like_count < max(50, int(len(items) * 0.8)):
            continue
        branches.append({"parent": obj, "key": f"ORPHAN_COLOR_DICTIONARY_{handle}", "target": obj})
    return branches


def find_large_null_dictionary_shells(doc: DxfDrawing) -> list[object]:
    candidates: list[object] = []
    for obj in doc.objects:
        if obj.dxftype() != "DICTIONARY":
            continue
        try:
            items = list(obj.items())
        except Exception:
            continue
        if len(items) < 50:
            continue
        null_count = sum(1 for _, child in items if isinstance(child, str) and child == "0")
        if null_count >= max(50, int(len(items) * 0.8)):
            candidates.append(obj)
    return candidates


def remove_dictionary_references(doc: DxfDrawing, target_handle: str) -> list[dict[str, str]]:
    removed: list[dict[str, str]] = []
    for parent in doc.objects:
        if parent.dxftype() != "DICTIONARY":
            continue
        try:
            items = list(parent.items())
        except Exception:
            continue
        for key, child in items:
            child_handle = str(getattr(getattr(child, "dxf", None), "handle", ""))
            if child_handle != target_handle:
                continue
            try:
                del parent[key]
                removed.append(
                    {
                        "parent_handle": str(getattr(parent.dxf, "handle", "")),
                        "key": str(key),
                        "target_handle": target_handle,
                    }
                )
            except Exception:
                continue
    return removed


def strip_dxf_sections(input_path: Path, output_path: Path, sections_to_remove: set[str]) -> dict[str, Any]:
    lines = input_path.read_bytes().splitlines(keepends=True)
    out_lines: list[bytes] = []
    removed: dict[str, dict[str, int]] = {}
    normalized = {name.upper() for name in sections_to_remove}
    index = 0
    while index < len(lines):
        if (
            lines[index].strip() == b"0"
            and index + 3 < len(lines)
            and lines[index + 1].strip() == b"SECTION"
            and lines[index + 2].strip() == b"2"
        ):
            section_name = lines[index + 3].strip().decode("utf-8", errors="replace")
            if section_name.upper() in normalized:
                start = index
                index += 4
                while index < len(lines):
                    if lines[index].strip() == b"0" and index + 1 < len(lines) and lines[index + 1].strip() == b"ENDSEC":
                        index += 2
                        break
                    index += 1
                section_lines = lines[start:index]
                removed[section_name] = {
                    "line_count": len(section_lines),
                    "byte_count": sum(len(line) for line in section_lines),
                }
                continue
        out_lines.append(lines[index])
        index += 1
    output_path.write_bytes(b"".join(out_lines))
    return {"removed_sections": removed}


def invisible_reason(doc: DxfDrawing, entity: object) -> str:
    reasons: list[str] = []
    if bool(getattr(entity.dxf, "invisible", 0) or 0):
        reasons.append("entity invisible flag")
    layer_name = str(getattr(entity.dxf, "layer", "0"))
    try:
        layer = doc.layers.get(layer_name)
        if layer.is_off():
            reasons.append("layer off")
        if layer.is_frozen():
            reasons.append("layer frozen")
    except Exception:
        pass
    return ", ".join(reasons) or "not visible"


def build_removed_payload(candidates: list[DuplicateCandidate], step_name: str, signature_scope: str) -> dict[str, Any]:
    type_counts = Counter(item.entity_type for item in candidates)
    layer_counts = Counter(item.layer for item in candidates)
    return {
        "step_name": step_name,
        "signature_scope": signature_scope,
        "exact_tolerance": EXACT_TOLERANCE,
        "removed_count": len(candidates),
        "entity_type_counts": dict(sorted(type_counts.items())),
        "layer_counts": dict(layer_counts.most_common()),
        "entities": [
            {
                "handle": item.handle,
                "entity_type": item.entity_type,
                "layer": item.layer,
                "reason": item.reason,
                "signature": signature_to_json(item.signature),
                "geometry": entity_geometry(item.entity),
            }
            for item in candidates
        ],
    }


def write_removed_entities_dxf(doc: DxfDrawing, candidates: list[DuplicateCandidate], path: Path) -> None:
    removed_doc = ezdxf.new(doc.dxfversion)
    removed_msp = removed_doc.modelspace()
    ensure_layers(removed_doc, sorted({candidate.layer for candidate in candidates}))
    for candidate in candidates:
        add_entity_copy(removed_msp, candidate.entity)
    path.parent.mkdir(parents=True, exist_ok=True)
    removed_doc.saveas(path)


def ensure_layers(doc: DxfDrawing, layer_names: list[str]) -> None:
    for layer_name in layer_names:
        if not layer_name:
            continue
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)


def add_entity_copy(modelspace: Any, entity: object) -> None:
    entity_type = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", "0"))
    color = getattr(entity.dxf, "color", 256)
    attrs = {"layer": layer, "color": color}
    if entity_type == "LINE":
        modelspace.add_line(entity.dxf.start, entity.dxf.end, dxfattribs=attrs)
    elif entity_type == "ARC":
        modelspace.add_arc(
            center=entity.dxf.center,
            radius=float(entity.dxf.radius),
            start_angle=float(entity.dxf.start_angle),
            end_angle=float(entity.dxf.end_angle),
            dxfattribs=attrs,
        )
    elif entity_type == "LWPOLYLINE":
        points = list(entity.get_points("xyseb"))
        modelspace.add_lwpolyline(points, format="xyseb", close=bool(getattr(entity, "closed", False)), dxfattribs=attrs)
    elif entity_type == "POLYLINE":
        points = [tuple(vertex.dxf.location) for vertex in getattr(entity, "vertices", [])]
        polyline = modelspace.add_polyline3d(points, dxfattribs=attrs)
        if bool(getattr(entity, "is_closed", False)):
            polyline.close(True)
    else:
        try:
            modelspace.add_entity(entity.copy())
        except Exception:
            return


def remove_candidates(doc: DxfDrawing, candidates: list[DuplicateCandidate]) -> int:
    removed = 0
    for candidate in candidates:
        try:
            candidate.entity.destroy()
            removed += 1
        except Exception:
            continue
    doc.modelspace().entity_space.purge()
    return removed


def analyze_dxf(path: Path) -> dict[str, Any]:
    section_stats = scan_dxf_sections(path)
    doc = load_dxf(path)
    modelspace_stats = analyze_modelspace(doc)
    table_stats = analyze_tables(doc)
    object_stats = analyze_objects(doc)
    duplicate_stats = analyze_duplicate_linework(doc)
    return {
        "path": str(path),
        "created_at": now_iso(),
        "file": {"size_bytes": path.stat().st_size, "size_mb": round(path.stat().st_size / 1024 / 1024, 3)},
        "sections": section_stats,
        "modelspace": modelspace_stats,
        "tables": table_stats,
        "objects": object_stats,
        "duplicates": duplicate_stats,
    }


def scan_dxf_sections(path: Path) -> dict[str, Any]:
    sections: dict[str, dict[str, int]] = defaultdict(lambda: {"line_count": 0, "byte_count": 0})
    current = "__preamble__"
    total_lines = 0
    with path.open("rb") as handle:
        previous_code = b""
        for raw_line in handle:
            total_lines += 1
            stripped = raw_line.strip()
            if previous_code == b"2" and current == "__pending_section__":
                current = stripped.decode("utf-8", errors="replace") or "__unknown__"
            elif previous_code == b"0" and stripped == b"SECTION":
                current = "__pending_section__"
            elif previous_code == b"0" and stripped == b"ENDSEC":
                current = "__between_sections__"
            sections[current]["line_count"] += 1
            sections[current]["byte_count"] += len(raw_line)
            previous_code = stripped
    cleaned = {name: stats for name, stats in sections.items() if name != "__pending_section__"}
    return {
        "total_lines": total_lines,
        "sections": dict(sorted(cleaned.items(), key=lambda item: item[1]["byte_count"], reverse=True)),
    }


def analyze_modelspace(doc: DxfDrawing) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    layer_type_counts: dict[str, Counter[str]] = defaultdict(Counter)
    visible_count = 0
    invisible_count = 0
    closed_lwpolyline_count = 0
    closed_polyline_count = 0
    for entity in doc.modelspace():
        entity_type = entity.dxftype()
        layer = str(getattr(entity.dxf, "layer", "0"))
        type_counts[entity_type] += 1
        layer_counts[layer] += 1
        layer_type_counts[layer][entity_type] += 1
        if is_entity_visible(doc, entity):
            visible_count += 1
        else:
            invisible_count += 1
        if entity_type == "LWPOLYLINE" and bool(getattr(entity, "closed", False)):
            closed_lwpolyline_count += 1
        elif entity_type == "POLYLINE" and bool(getattr(entity, "is_closed", False)):
            closed_polyline_count += 1
    return {
        "entity_count": sum(type_counts.values()),
        "visible_entity_count": visible_count,
        "invisible_entity_count": invisible_count,
        "entity_type_counts": dict(type_counts.most_common()),
        "layer_counts": dict(layer_counts.most_common()),
        "layer_type_counts": {layer: dict(counter.most_common()) for layer, counter in sorted(layer_type_counts.items())},
        "text_count": type_counts.get("TEXT", 0),
        "mtext_count": type_counts.get("MTEXT", 0),
        "insert_count": type_counts.get("INSERT", 0),
        "closed_lwpolyline_count": closed_lwpolyline_count,
        "closed_polyline_count": closed_polyline_count,
    }


def analyze_tables(doc: DxfDrawing) -> dict[str, Any]:
    block_entity_count = 0
    block_count = 0
    for block in doc.blocks:
        block_count += 1
        block_entity_count += len(block)
    return {
        "layer_count": len(doc.layers),
        "appid_count": len(doc.appids),
        "linetype_count": len(doc.linetypes),
        "style_count": len(doc.styles),
        "dimstyle_count": len(doc.dimstyles),
        "block_count": block_count,
        "block_entity_count": block_entity_count,
        "layout_count": len(doc.layouts),
    }


def analyze_objects(doc: DxfDrawing) -> dict[str, Any]:
    type_counts: Counter[str] = Counter()
    dictionary_sizes: list[dict[str, Any]] = []
    for obj in doc.objects:
        object_type = obj.dxftype()
        type_counts[object_type] += 1
        if object_type == "DICTIONARY":
            items = dictionary_items(obj)
            dictionary_sizes.append(
                {
                    "handle": str(getattr(obj.dxf, "handle", "")),
                    "owner": str(getattr(obj.dxf, "owner", "")),
                    "item_count": len(items),
                    "sample_keys": [key for key, _ in items[:8]],
                }
            )
    dictionary_sizes.sort(key=lambda item: item["item_count"], reverse=True)
    return {
        "object_count": sum(type_counts.values()),
        "object_type_counts": dict(type_counts.most_common()),
        "largest_dictionaries": dictionary_sizes[:20],
    }


def analyze_duplicate_linework(doc: DxfDrawing) -> dict[str, Any]:
    by_scope: dict[str, Any] = {}
    for scope in ("geometry", "layer"):
        signatures: Counter[tuple[Any, ...]] = Counter()
        type_counts: Counter[str] = Counter()
        layer_counts: Counter[str] = Counter()
        skipped = 0
        for entity in doc.modelspace():
            entity_type = entity.dxftype()
            if entity_type not in LINEAR_ENTITY_TYPES:
                continue
            try:
                signature = entity_signature(entity, tolerance=EXACT_TOLERANCE, scope=scope)
            except Exception:
                skipped += 1
                continue
            signatures[signature] += 1
            type_counts[entity_type] += 1
            layer_counts[str(getattr(entity.dxf, "layer", "0"))] += 1
        duplicate_count = sum(count - 1 for count in signatures.values() if count > 1)
        duplicate_group_count = sum(1 for count in signatures.values() if count > 1)
        by_scope[scope] = {
            "linework_count": sum(type_counts.values()),
            "exact_duplicate_count": duplicate_count,
            "exact_duplicate_group_count": duplicate_group_count,
            "skipped_count": skipped,
            "entity_type_counts": dict(type_counts.most_common()),
            "layer_counts": dict(layer_counts.most_common(20)),
        }
    return by_scope


def run_protection_checks(before_stats: dict[str, Any], after_stats: dict[str, Any], removed_count: int) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("text_count", "mtext_count", "insert_count", "closed_lwpolyline_count", "closed_polyline_count"):
        before_value = int(before_model.get(key, 0))
        after_value = int(after_model.get(key, 0))
        checks.append(
            {
                "name": key,
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    expected_after_entities = int(before_model["entity_count"]) - removed_count
    actual_after_entities = int(after_model["entity_count"])
    checks.append(
        {
            "name": "modelspace_entity_count_delta",
            "status": "passed" if actual_after_entities == expected_after_entities else "failed",
            "before": int(before_model["entity_count"]),
            "after": actual_after_entities,
            "expected_after": expected_after_entities,
            "message": "matches removed count" if actual_after_entities == expected_after_entities else "does not match removed count",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_visibility_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_count: int,
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    before_visible = int(before_model["visible_entity_count"])
    after_visible = int(after_model["visible_entity_count"])
    checks.append(
        {
            "name": "visible_entity_count_unchanged",
            "status": "passed" if before_visible == after_visible else "failed",
            "before": before_visible,
            "after": after_visible,
            "message": "visible modelspace entities unchanged"
            if before_visible == after_visible
            else "visible modelspace entity count changed",
        }
    )
    after_invisible = int(after_model["invisible_entity_count"])
    checks.append(
        {
            "name": "invisible_entity_count_zero",
            "status": "passed" if after_invisible == 0 else "failed",
            "before": int(before_model["invisible_entity_count"]),
            "after": after_invisible,
            "message": "all invisible modelspace entities removed" if after_invisible == 0 else "invisible entities remain",
        }
    )
    expected_after_entities = int(before_model["entity_count"]) - removed_count
    actual_after_entities = int(after_model["entity_count"])
    checks.append(
        {
            "name": "modelspace_entity_count_delta",
            "status": "passed" if actual_after_entities == expected_after_entities else "failed",
            "before": int(before_model["entity_count"]),
            "after": actual_after_entities,
            "expected_after": expected_after_entities,
            "message": "matches removed count" if actual_after_entities == expected_after_entities else "does not match removed count",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_object_branch_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_count: int,
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count"):
        before_value = int(before_model.get(key, 0))
        after_value = int(after_model.get(key, 0))
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_objects = int(before_stats.get("objects", {}).get("object_count", 0))
    after_objects = int(after_stats.get("objects", {}).get("object_count", 0))
    checks.append(
        {
            "name": "object_count_decreased",
            "status": "passed" if removed_count > 0 and after_objects < before_objects else "failed",
            "before": before_objects,
            "after": after_objects,
            "message": "OBJECTS count decreased" if after_objects < before_objects else "OBJECTS count did not decrease",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_rebuild_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    copied_count: int,
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    expected_count = int(before_model["visible_entity_count"])
    after_count = int(after_model["entity_count"])
    checks.append(
        {
            "name": "copied_visible_entity_count",
            "status": "passed" if copied_count == expected_count and after_count == expected_count else "failed",
            "before": expected_count,
            "after": after_count,
            "copied": copied_count,
            "message": "all visible modelspace entities copied"
            if copied_count == expected_count and after_count == expected_count
            else "visible modelspace copy count mismatch",
        }
    )
    checks.append(
        {
            "name": "no_invisible_entities_after_rebuild",
            "status": "passed" if int(after_model["invisible_entity_count"]) == 0 else "failed",
            "before": int(before_model["invisible_entity_count"]),
            "after": int(after_model["invisible_entity_count"]),
            "message": "rebuilt DXF has no invisible modelspace entities"
            if int(after_model["invisible_entity_count"]) == 0
            else "rebuilt DXF still has invisible entities",
        }
    )
    for key in ("entity_type_counts",):
        before_value = before_model.get(key, {})
        after_value = after_model.get(key, {})
        checks.append(
            {
                "name": key,
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    for key in ("mtext_count", "closed_lwpolyline_count", "closed_polyline_count"):
        before_value = int(before_model.get(key, 0))
        after_value = int(after_model.get(key, 0))
        checks.append(
            {
                "name": key,
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_table_cleanup_protection_checks(before_stats: dict[str, Any], after_stats: dict[str, Any]) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_appids = int(before_stats.get("tables", {}).get("appid_count", 0))
    after_appids = int(after_stats.get("tables", {}).get("appid_count", 0))
    checks.append(
        {
            "name": "appid_count_decreased",
            "status": "passed" if after_appids < before_appids else "failed",
            "before": before_appids,
            "after": after_appids,
            "message": "APPID table reduced" if after_appids < before_appids else "APPID table did not reduce",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_block_cleanup_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_count: int,
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_blocks = int(before_stats.get("tables", {}).get("block_count", 0))
    after_blocks = int(after_stats.get("tables", {}).get("block_count", 0))
    checks.append(
        {
            "name": "block_count_decreased",
            "status": "passed" if removed_count > 0 and after_blocks < before_blocks else "failed",
            "before": before_blocks,
            "after": after_blocks,
            "removed": removed_count,
            "message": "BLOCK table reduced" if after_blocks < before_blocks else "BLOCK table did not reduce",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_symbol_table_cleanup_protection_checks(before_stats: dict[str, Any], after_stats: dict[str, Any]) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_tables = before_stats.get("tables", {})
    after_tables = after_stats.get("tables", {})
    for key in ("layer_count", "style_count", "linetype_count", "dimstyle_count"):
        before_value = int(before_tables.get(key, 0))
        after_value = int(after_tables.get(key, 0))
        checks.append(
            {
                "name": f"{key}_not_increased",
                "status": "passed" if after_value <= before_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "not increased" if after_value <= before_value else "increased unexpectedly",
            }
        )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_paperspace_cleanup_protection_checks(before_stats: dict[str, Any], after_stats: dict[str, Any]) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_tables = before_stats.get("tables", {})
    after_tables = after_stats.get("tables", {})
    for key in ("layout_count", "block_count", "block_entity_count"):
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
            "name": "layout_count_decreased",
            "status": "passed"
            if int(after_tables.get("layout_count", 0)) < int(before_tables.get("layout_count", 0))
            else "failed",
            "before": int(before_tables.get("layout_count", 0)),
            "after": int(after_tables.get("layout_count", 0)),
            "message": "paper-space layouts removed",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_section_strip_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    strip_result: dict[str, Any],
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_sections = before_stats.get("sections", {}).get("sections", {})
    after_sections = after_stats.get("sections", {}).get("sections", {})
    removed_sections = strip_result.get("removed_sections", {})
    for name in removed_sections:
        checks.append(
            {
                "name": f"section_{name}_removed",
                "status": "passed" if name not in after_sections else "failed",
                "before": before_sections.get(name, {}),
                "after": after_sections.get(name, {}),
                "message": "section removed" if name not in after_sections else "section still present",
            }
        )
    before_size = int(before_stats.get("file", {}).get("size_bytes", 0))
    after_size = int(after_stats.get("file", {}).get("size_bytes", 0))
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_sections and after_size < before_size else "failed",
            "before": before_size,
            "after": after_size,
            "message": "file size decreased" if after_size < before_size else "file size did not decrease",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_auxiliary_entity_cleanup_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    reference_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    removed_count: int,
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    reference_model = reference_stats["modelspace"]
    checks = []
    before_type_counts = dict(before_model.get("entity_type_counts", {}))
    after_type_counts = dict(after_model.get("entity_type_counts", {}))
    removed_type_counts = dict(removed_payload.get("entity_type_counts", {}))
    protected_types = sorted((set(before_type_counts) | set(after_type_counts)) - AI_RENDER_EXCLUDED_ENTITY_TYPES)
    for entity_type in protected_types:
        before_value = int(before_type_counts.get(entity_type, 0))
        after_value = int(after_type_counts.get(entity_type, 0))
        checks.append(
            {
                "name": f"entity_type_{entity_type}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    for entity_type in AI_RENDER_EXCLUDED_ENTITY_TYPES:
        before_value = int(before_type_counts.get(entity_type, 0))
        after_value = int(after_type_counts.get(entity_type, 0))
        removed_value = int(removed_type_counts.get(entity_type, 0))
        checks.append(
            {
                "name": f"entity_type_{entity_type}_removed_delta",
                "status": "passed" if after_value == before_value - removed_value else "failed",
                "before": before_value,
                "after": after_value,
                "removed": removed_value,
                "message": "removed count matches" if after_value == before_value - removed_value else "removed count mismatch",
            }
        )
    before_count = int(before_model.get("entity_count", 0))
    after_count = int(after_model.get("entity_count", 0))
    reference_count = int(reference_model.get("entity_count", 0))
    checks.append(
        {
            "name": "modelspace_entity_count_delta",
            "status": "passed" if after_count == before_count - removed_count else "failed",
            "before": before_count,
            "after": after_count,
            "removed": removed_count,
            "message": "matches removed count" if after_count == before_count - removed_count else "does not match removed count",
        }
    )
    checks.append(
        {
            "name": "modelspace_entity_count_matches_reference",
            "status": "passed" if after_count == reference_count else "warning",
            "reference": reference_count,
            "after": after_count,
            "message": "matches reference" if after_count == reference_count else "does not match reference",
        }
    )
    before_size = int(before_stats.get("file", {}).get("size_bytes", 0))
    after_size = int(after_stats.get("file", {}).get("size_bytes", 0))
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_count > 0 and after_size < before_size else "failed",
            "before": before_size,
            "after": after_size,
            "message": "file size decreased" if after_size < before_size else "file size did not decrease",
        }
    )
    status = "passed" if all(check["status"] in {"passed", "warning"} for check in checks) else "failed"
    return {"status": status, "checks": checks}


def run_secondary_table_cleanup_protection_checks(
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed: dict[str, list[str]],
) -> dict[str, Any]:
    before_model = before_stats["modelspace"]
    after_model = after_stats["modelspace"]
    checks = []
    for key in ("entity_count", "visible_entity_count", "invisible_entity_count", "entity_type_counts", "layer_counts"):
        before_value = before_model.get(key)
        after_value = after_model.get(key)
        checks.append(
            {
                "name": f"modelspace_{key}_unchanged",
                "status": "passed" if before_value == after_value else "failed",
                "before": before_value,
                "after": after_value,
                "message": "unchanged" if before_value == after_value else "changed unexpectedly",
            }
        )
    before_tables = before_stats.get("tables", {})
    after_tables = after_stats.get("tables", {})
    table_map = {
        "layers": "layer_count",
        "linetypes": "linetype_count",
        "styles": "style_count",
        "dimstyles": "dimstyle_count",
        "appids": "appid_count",
    }
    for removed_key, stats_key in table_map.items():
        before_value = int(before_tables.get(stats_key, 0))
        after_value = int(after_tables.get(stats_key, 0))
        removed_value = len(removed.get(removed_key, []))
        if removed_value > 0:
            passed = after_value < before_value
            message = "decreased" if passed else "did not decrease"
        else:
            passed = after_value == before_value
            message = "unchanged" if passed else "changed unexpectedly"
        checks.append(
            {
                "name": f"{stats_key}_decreased_when_records_removed",
                "status": "passed" if passed else "failed",
                "before": before_value,
                "after": after_value,
                "removed": removed_value,
                "message": message,
            }
        )
    before_size = int(before_stats.get("file", {}).get("size_bytes", 0))
    after_size = int(after_stats.get("file", {}).get("size_bytes", 0))
    removed_count = sum(len(items) for items in removed.values())
    checks.append(
        {
            "name": "file_size_decreased",
            "status": "passed" if removed_count > 0 and after_size < before_size else "failed",
            "before": before_size,
            "after": after_size,
            "message": "file size decreased" if after_size < before_size else "file size did not decrease",
        }
    )
    status = "passed" if all(check["status"] == "passed" for check in checks) else "failed"
    return {"status": status, "checks": checks}


def build_ai_placeholder(dry_run_ai: bool, skip_ai: bool, step_name: str) -> dict[str, Any]:
    if skip_ai:
        return {"status": "skipped", "step_name": step_name, "notes": "AI validation skipped by --skip-ai."}
    if dry_run_ai:
        return {"status": "dry_run", "step_name": step_name, "notes": "AI validation reserved but not called."}
    return {
        "status": "not_implemented",
        "step_name": step_name,
        "notes": "Rendering and local AI visual validation are planned for the next phase.",
    }


def decide_step_status(
    removed_count: int,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    protection: dict[str, Any],
) -> str:
    if removed_count <= 0:
        return "rejected"
    if protection["status"] != "passed":
        return "rejected"
    if after_stats["file"]["size_bytes"] > before_stats["file"]["size_bytes"]:
        return "needs_manual_review"
    return "accepted"


def decide_visibility_step_status(
    removed_count: int,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    protection: dict[str, Any],
) -> str:
    if removed_count <= 0:
        return "rejected"
    if protection["status"] != "passed":
        return "rejected"
    if after_stats["file"]["size_bytes"] > before_stats["file"]["size_bytes"]:
        return "needs_manual_review"
    return "accepted"


def decide_object_branch_step_status(
    removed_count: int,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    protection: dict[str, Any],
) -> str:
    if removed_count <= 0:
        return "rejected"
    if protection["status"] != "passed":
        return "rejected"
    if after_stats["file"]["size_bytes"] >= before_stats["file"]["size_bytes"]:
        return "needs_manual_review"
    return "accepted"


def decide_rebuild_step_status(
    copied_count: int,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    protection: dict[str, Any],
) -> str:
    if copied_count <= 0:
        return "rejected"
    if protection["status"] != "passed":
        return "rejected"
    if after_stats["file"]["size_bytes"] >= before_stats["file"]["size_bytes"]:
        return "needs_manual_review"
    return "accepted"


def upsert_rule(manifest: dict[str, Any], step: dict[str, Any]) -> None:
    rule = step.get("rule")
    if not rule:
        return
    accepted = [item for item in manifest.get("accepted_rules", []) if item.get("name") != rule.get("name")]
    accepted.append(rule)
    manifest["accepted_rules"] = accepted


def upsert_rejected_rule(manifest: dict[str, Any], step: dict[str, Any]) -> None:
    rule = step.get("rule")
    if not rule:
        return
    rejected = [item for item in manifest.get("rejected_rules", []) if item.get("name") != rule.get("name")]
    rejected.append({**rule, "status": step.get("status"), "removed_count": step.get("removed_count", 0)})
    manifest["rejected_rules"] = rejected


def write_rules_candidate(out_dir: Path, manifest: dict[str, Any]) -> None:
    payload = {
        "updated_at": now_iso(),
        "accepted_steps": manifest.get("accepted_rules", []),
        "rejected_steps": manifest.get("rejected_rules", []),
    }
    write_json(out_dir / "rules_candidate.json", payload)


def rollback_to_step(out_dir: Path, manifest: dict[str, Any], step_number: int) -> None:
    points = {int(point["step"]): point for point in manifest.get("rollback_points", [])}
    if step_number not in points:
        raise ValueError(f"Rollback step not found in manifest: {step_number}")
    target = Path(points[step_number]["path"])
    if not target.exists():
        raise FileNotFoundError(f"Rollback target does not exist: {target}")
    current = out_dir.resolve() / "current.dxf"
    shutil.copy2(target, current)
    manifest["current_step"] = step_number
    manifest["current_dxf"] = str(current)
    manifest["updated_at"] = now_iso()
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def write_rollback_script(out_dir: Path, step_number: int, target: Path) -> None:
    script = out_dir / "rollback" / f"rollback_to_step_{step_number:03d}.ps1"
    current = out_dir / "current.dxf"
    script.write_text(
        f'Copy-Item -LiteralPath "{target}" -Destination "{current}" -Force\n',
        encoding="utf-8",
    )


def already_ran_step(manifest: dict[str, Any], name: str) -> bool:
    return any(step.get("name") == name for step in manifest.get("steps", []))


def next_cleaning_action(manifest: dict[str, Any]) -> str | None:
    if any(step.get("status") == "needs_manual_review" for step in manifest.get("steps", [])):
        return None
    ordered_actions = [
        "remove_exact_duplicate_linework",
        "remove_invisible_modelspace_entities",
        "remove_acad_layerstates",
        "rebuild_visible_modelspace",
        "remove_unused_appids",
        "remove_unreachable_blocks",
        "remove_object_metadata",
        "remove_unused_symbol_table_records",
        "remove_paperspace_layouts",
        "remove_remaining_object_metadata",
        "strip_classes_and_acdsdata_sections",
        "remove_auxiliary_points_and_xlines",
        "remove_unreachable_blocks_after_auxiliary",
        "remove_unused_tables_after_auxiliary",
        "remove_large_null_dictionary_shells",
        "strip_regenerated_classes_section",
    ]
    for action in ordered_actions:
        if not already_ran_step(manifest, action):
            return action
    return None


def next_cleaning_step_number(manifest: dict[str, Any]) -> int:
    numbers = [int(step.get("step", 0)) for step in manifest.get("steps", [])]
    return max(numbers, default=0) + 1


def load_manifest(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Experiment manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(out_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    write_json(Path(out_dir) / "manifest.json", manifest)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_baseline_html(source_stats: dict[str, Any], reference_stats: dict[str, Any]) -> str:
    source_size = source_stats["file"]["size_bytes"]
    reference_size = reference_stats["file"]["size_bytes"]
    ratio = source_size / reference_size if reference_size else 0
    return html_page(
        "DXF Baseline Comparison",
        f"""
        <section>
          <h2>结论</h2>
          <p>源文件体积为参考文件的 <strong>{ratio:.1f}x</strong>。本报告用于定位体积膨胀来源，并作为后续分步清理的 baseline。</p>
        </section>
        {stats_pair_html(source_stats, reference_stats)}
        """,
    )


def build_step_html(
    step_number: int,
    title: str,
    status: str,
    input_path: Path,
    after_path: Path,
    reference_path: Path,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    removed_payload: dict[str, Any],
    protection: dict[str, Any],
    ai_check: dict[str, Any],
    removed_json_path: Path,
    removed_dxf_path: Path,
) -> str:
    removed_count = int(removed_payload["removed_count"])
    notes = str(removed_payload.get("notes", "本轮只处理一个独立清理候选。"))
    report_dir = Path(removed_json_path).parent
    image_links = ""
    for label, filename in (
        ("Reference", "reference.png"),
        ("Before", "before.png"),
        ("After", "after.png"),
        ("Diff", "diff.png"),
        ("Comparison", "comparison.png"),
    ):
        image_path = report_dir / filename
        image_links += f'<div><h3>{escape(label)}</h3><img src="{escape(image_path.name)}" alt="{escape(label)}"></div>'
    return html_page(
        f"Step {step_number:03d} - {title}",
        f"""
        <section>
          <h2>本轮结论</h2>
          <div class="status {escape(status)}">{escape(status)}</div>
          <p>删除候选数量：<strong>{removed_count}</strong>。{escape(notes)}</p>
        </section>
        <section>
          <h2>文件</h2>
          <table>
            <tr><th>输入</th><td>{escape(str(input_path))}</td></tr>
            <tr><th>输出</th><td>{escape(str(after_path))}</td></tr>
            <tr><th>参考</th><td>{escape(str(reference_path))}</td></tr>
            <tr><th>被删 JSON</th><td>{escape(str(removed_json_path))}</td></tr>
            <tr><th>被删 DXF</th><td>{escape(str(removed_dxf_path))}</td></tr>
          </table>
        </section>
        {stats_pair_html(before_stats, after_stats, left_title="Before", right_title="After")}
        <section>
          <h2>被删除实体</h2>
          {counter_table_html("Entity types", removed_payload.get("entity_type_counts", {}))}
          {counter_table_html("Layers", dict(list(removed_payload.get("layer_counts", {}).items())[:20]))}
        </section>
        <section>
          <h2>保护检查</h2>
          {protection_html(protection)}
        </section>
        <section>
          <h2>AI / 视觉验证</h2>
          <pre>{escape(json.dumps(ai_check, ensure_ascii=False, indent=2))}</pre>
        </section>
        <section>
          <h2>图像校验文件</h2>
          <div class="grid images">{image_links}</div>
          <p>图片由脚本写入本 step 目录，可用于本地 AI 或人工复核。</p>
        </section>
        <style>.images img {{ width: 100%; border: 1px solid #d9e1ea; background: #fff; }}</style>
        """,
    )


def write_index_html(out_dir: Path, manifest: dict[str, Any]) -> None:
    rows = []
    for step in manifest.get("steps", []):
        report = step.get("report_html", "")
        rows.append(
            "<tr>"
            f"<td>{escape(str(step.get('step')))}</td>"
            f"<td>{escape(str(step.get('name')))}</td>"
            f"<td>{escape(str(step.get('status')))}</td>"
            f"<td>{escape(str(step.get('removed_count', '')))}</td>"
            f"<td><a href=\"{escape(rel_path(out_dir, Path(report))) if report else '#'}\">report</a></td>"
            "</tr>"
        )
    body = f"""
    <section>
      <h2>当前状态</h2>
      <table>
        <tr><th>Current step</th><td>{escape(str(manifest.get("current_step")))}</td></tr>
        <tr><th>Current DXF</th><td>{escape(str(manifest.get("current_dxf")))}</td></tr>
        <tr><th>Source</th><td>{escape(str(manifest.get("source")))}</td></tr>
        <tr><th>Reference</th><td>{escape(str(manifest.get("reference")))}</td></tr>
      </table>
    </section>
    <section>
      <h2>步骤</h2>
      <table>
        <tr><th>Step</th><th>Name</th><th>Status</th><th>Removed</th><th>Report</th></tr>
        {''.join(rows)}
      </table>
    </section>
    <section>
      <h2>已接受规则</h2>
      <pre>{escape(json.dumps(manifest.get("accepted_rules", []), ensure_ascii=False, indent=2))}</pre>
    </section>
    """
    (out_dir / "index.html").write_text(html_page("DXF Cleaning Experiment", body), encoding="utf-8")


def mark_step_rejected(out_dir: Path, manifest: dict[str, Any], step_number: int, reason: str) -> None:
    target_step: dict[str, Any] | None = None
    for step in manifest.get("steps", []):
        if int(step.get("step", -1)) == step_number:
            target_step = step
            break
    if target_step is None:
        raise ValueError(f"Step not found: {step_number}")
    target_step["status"] = "rejected"
    target_step["rejected_reason"] = reason or "Marked rejected manually."
    if target_step.get("accepted_after_dxf") and not target_step.get("rejected_after_dxf"):
        target_step["rejected_after_dxf"] = target_step["accepted_after_dxf"]
    target_step["accepted_after_dxf"] = None

    accepted_steps = [
        step
        for step in manifest.get("steps", [])
        if int(step.get("step", -1)) < step_number and step.get("status") == "accepted" and step.get("accepted_after_dxf")
    ]
    if accepted_steps:
        previous = max(accepted_steps, key=lambda item: int(item["step"]))
        manifest["current_step"] = int(previous["step"])
        manifest["current_dxf"] = previous["accepted_after_dxf"]
    else:
        manifest["current_step"] = 0
        manifest["current_dxf"] = str(out_dir.resolve() / "current.dxf")
        shutil.copy2(Path(manifest["source"]), Path(manifest["current_dxf"]))

    manifest["rollback_points"] = [
        point for point in manifest.get("rollback_points", []) if int(point.get("step", -1)) < step_number
    ]
    manifest["accepted_rules"] = [
        rule for rule in manifest.get("accepted_rules", []) if rule.get("name") != target_step.get("name")
    ]
    upsert_rejected_rule(manifest, target_step)
    write_rules_candidate(out_dir, manifest)
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def mark_step_accepted(out_dir: Path, manifest: dict[str, Any], step_number: int, reason: str) -> None:
    target_step: dict[str, Any] | None = None
    for step in manifest.get("steps", []):
        if int(step.get("step", -1)) == step_number:
            target_step = step
            break
    if target_step is None:
        raise ValueError(f"Step not found: {step_number}")
    if target_step.get("status") != "needs_manual_review":
        raise ValueError(f"Only needs_manual_review steps can be accepted manually: step {step_number}")
    candidate = target_step.get("candidate_after_dxf")
    if not candidate:
        raise ValueError(f"Step has no candidate_after_dxf: step {step_number}")
    candidate_path = Path(candidate)
    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate DXF does not exist: {candidate_path}")
    accepted_path = Path(target_step["step_dir"]) / "accepted_after.dxf"
    shutil.copy2(candidate_path, accepted_path)
    target_step["status"] = "accepted"
    target_step["accepted_after_dxf"] = str(accepted_path)
    target_step["rejected_after_dxf"] = None
    target_step["accepted_reason"] = reason or "Accepted manually after external validation."
    manifest["current_step"] = step_number
    manifest["current_dxf"] = str(accepted_path)
    manifest["rollback_points"] = [
        point for point in manifest.get("rollback_points", []) if int(point.get("step", -1)) != step_number
    ]
    manifest["rollback_points"].append(
        {
            "step": step_number,
            "label": target_step.get("title", target_step.get("name", f"step {step_number}")),
            "path": str(accepted_path),
        }
    )
    manifest["rejected_rules"] = [
        rule for rule in manifest.get("rejected_rules", []) if rule.get("name") != target_step.get("name")
    ]
    upsert_rule(manifest, target_step)
    write_rollback_script(out_dir, step_number, accepted_path)
    write_rules_candidate(out_dir, manifest)
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def generate_section_cleanup_chain(out_dir: Path, manifest: dict[str, Any], dry_run_ai: bool, skip_ai: bool) -> None:
    existing = {step.get("name") for step in manifest.get("steps", [])}
    planned = ["remove_unreachable_blocks", "remove_object_metadata", "remove_unused_symbol_table_records"]
    already = [name for name in planned if name in existing]
    if already:
        raise ValueError(f"Section cleanup chain already contains steps: {', '.join(already)}")

    reference = Path(manifest["reference"])
    current_path = Path(manifest["current_dxf"])
    next_number = next_cleaning_step_number(manifest)

    chain: list[tuple[str, dict[str, Any]]] = []
    block_step = run_remove_unreachable_blocks_step(
        current_path=current_path,
        reference_path=reference,
        out_dir=out_dir,
        step_number=next_number,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
    )
    chain.append(("BLOCKS", block_step))

    object_step = run_remove_object_metadata_step(
        current_path=Path(block_step["candidate_after_dxf"]),
        reference_path=reference,
        out_dir=out_dir,
        step_number=next_number + 1,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
    )
    object_step["chain_parent_step"] = block_step["step"]
    chain.append(("OBJECTS", object_step))

    table_step = run_remove_unused_symbol_table_records_step(
        current_path=Path(object_step["candidate_after_dxf"]),
        reference_path=reference,
        out_dir=out_dir,
        step_number=next_number + 2,
        dry_run_ai=dry_run_ai,
        skip_ai=skip_ai,
    )
    table_step["chain_parent_step"] = object_step["step"]
    chain.append(("TABLES", table_step))

    for section_name, step in chain:
        step["chain_section"] = section_name
        step["chain_status"] = "candidate_only"
        step_after = step.get("candidate_after_dxf")
        if step.get("input_dxf") and step_after:
            step["visual_check"] = render_step_images(Path(step["step_dir"]), reference, Path(step["input_dxf"]), Path(step_after))
        manifest["steps"].append(step)
        upsert_rejected_rule(manifest, step)

    write_rules_candidate(out_dir, manifest)
    write_manifest(out_dir, manifest)
    write_index_html(out_dir, manifest)


def write_bloat_audit(out_dir: Path, manifest: dict[str, Any]) -> None:
    audit_dir = Path(out_dir) / "bloat_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    reference = Path(manifest["reference"])
    current = Path(manifest["current_dxf"])
    paths: dict[str, Path] = {"current": current, "reference": reference}
    for step in manifest.get("steps", []):
        if step.get("status") == "needs_manual_review" and step.get("candidate_after_dxf"):
            paths[f"candidate_step_{step['step']}_{step['name']}"] = Path(step["candidate_after_dxf"])
    comparisons = {label: detailed_bloat_analysis(path) for label, path in paths.items() if path.exists()}
    payload = {
        "created_at": now_iso(),
        "paths": {label: str(path) for label, path in paths.items()},
        "analyses": comparisons,
        "conclusion": build_bloat_conclusion(comparisons),
    }
    json_path = audit_dir / "bloat_audit.json"
    html_path = audit_dir / "report.html"
    write_json(json_path, payload)
    html_path.write_text(build_bloat_audit_html(payload), encoding="utf-8")
    manifest["bloat_audit"] = {"json": str(json_path), "report_html": str(html_path), "status": "completed"}


def detailed_bloat_analysis(path: Path) -> dict[str, Any]:
    doc = load_dxf(path)
    raw = scan_dxf_sections(path)
    table_bytes, table_records = scan_table_breakdown(path)
    object_bytes = scan_object_breakdown(path)
    reachable = collect_reachable_blocks(doc)
    all_blocks = {block.name for block in doc.blocks}
    unreachable = sorted(all_blocks - reachable)
    used_symbols = collect_used_symbol_table_records(doc)
    unused_symbols = {
        "layers": sorted(str(record.dxf.name) for record in doc.layers if str(record.dxf.name) not in used_symbols["layers"] and str(record.dxf.name) not in {"0", "Defpoints"}),
        "styles": sorted(str(record.dxf.name) for record in doc.styles if str(record.dxf.name) not in used_symbols["styles"] and str(record.dxf.name) != "Standard"),
        "linetypes": sorted(str(record.dxf.name) for record in doc.linetypes if str(record.dxf.name) not in used_symbols["linetypes"] and str(record.dxf.name) not in {"ByBlock", "ByLayer", "Continuous"}),
        "dimstyles": sorted(str(record.dxf.name) for record in doc.dimstyles if str(record.dxf.name) not in used_symbols["dimstyles"] and str(record.dxf.name) != "Standard"),
    }
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "sections": raw["sections"],
        "table_bytes": table_bytes,
        "table_records": table_records,
        "object_bytes": object_bytes,
        "block_count": len(all_blocks),
        "reachable_block_count": len(reachable),
        "unreachable_block_count": len(unreachable),
        "unreachable_block_entity_count": sum(len(doc.blocks.get(name)) for name in unreachable),
        "unreachable_blocks_sample": unreachable[:100],
        "unused_symbol_counts": {key: len(value) for key, value in unused_symbols.items()},
        "unused_symbol_samples": {key: value[:100] for key, value in unused_symbols.items()},
        "tables": analyze_tables(doc),
        "objects": analyze_objects(doc),
        "modelspace": analyze_modelspace(doc),
    }


def scan_table_breakdown(path: Path) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    table_bytes: dict[str, int] = defaultdict(int)
    table_records: dict[str, Counter[str]] = defaultdict(Counter)
    section = ""
    in_table = False
    current_table = ""
    for code, value, byte_count in iter_dxf_pairs(path):
        if section == "TABLES" and in_table and current_table:
            table_bytes[current_table] += byte_count
        if code == "0" and value == "SECTION":
            section = "__pending__"
            in_table = False
            current_table = ""
        elif section == "__pending__" and code == "2":
            section = value
        elif code == "0" and value == "ENDSEC":
            section = ""
            in_table = False
            current_table = ""
        elif section == "TABLES" and code == "0" and value == "TABLE":
            in_table = True
            current_table = "__pending_table__"
        elif section == "TABLES" and in_table and current_table == "__pending_table__" and code == "2":
            current_table = value
        elif section == "TABLES" and in_table and code == "0" and value == "ENDTAB":
            in_table = False
            current_table = ""
        elif section == "TABLES" and in_table and current_table and code == "0" and value not in {"TABLE", "ENDTAB"}:
            table_records[current_table][value] += 1
    return dict(sorted(table_bytes.items(), key=lambda item: item[1], reverse=True)), {
        name: dict(counter.most_common()) for name, counter in table_records.items()
    }


def scan_object_breakdown(path: Path) -> dict[str, Any]:
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "bytes": 0})
    top_objects: list[dict[str, Any]] = []
    section = ""
    current: dict[str, Any] | None = None
    for code, value, byte_count in iter_dxf_pairs(path):
        if code == "0" and value == "SECTION":
            section = "__pending__"
            continue
        if section == "__pending__" and code == "2":
            section = value
            continue
        if code == "0" and value == "ENDSEC":
            if section == "OBJECTS" and current:
                append_object_breakdown(current, by_type, top_objects)
            section = ""
            current = None
            continue
        if section != "OBJECTS":
            continue
        if code == "0":
            if current:
                append_object_breakdown(current, by_type, top_objects)
            current = {"type": value, "bytes": byte_count, "handle": "", "owner": ""}
        elif current is not None:
            current["bytes"] += byte_count
            if code == "5":
                current["handle"] = value
            elif code == "330":
                current["owner"] = value
    if current:
        append_object_breakdown(current, by_type, top_objects)
    return {
        "by_type": dict(sorted(by_type.items(), key=lambda item: item[1]["bytes"], reverse=True)),
        "top_objects": sorted(top_objects, key=lambda item: item["bytes"], reverse=True)[:30],
    }


def append_object_breakdown(
    obj: dict[str, Any],
    by_type: dict[str, dict[str, int]],
    top_objects: list[dict[str, Any]],
) -> None:
    entry = by_type[str(obj["type"])]
    entry["count"] += 1
    entry["bytes"] += int(obj["bytes"])
    top_objects.append(
        {
            "type": obj["type"],
            "bytes": int(obj["bytes"]),
            "handle": obj.get("handle", ""),
            "owner": obj.get("owner", ""),
        }
    )


def iter_dxf_pairs(path: Path):
    with path.open("rb") as handle:
        while True:
            code = handle.readline()
            if not code:
                return
            value = handle.readline()
            if not value:
                return
            yield (
                code.strip().decode("utf-8", errors="replace"),
                value.rstrip(b"\r\n").decode("utf-8", errors="replace"),
                len(code) + len(value),
            )


def build_bloat_conclusion(comparisons: dict[str, dict[str, Any]]) -> list[str]:
    current = comparisons.get("current")
    reference = comparisons.get("reference")
    if not current or not reference:
        return ["缺少 current 或 reference，无法形成完整结论。"]
    lines = []
    ratio = current["size_bytes"] / reference["size_bytes"] if reference["size_bytes"] else 0
    lines.append(f"当前 accepted DXF 是参考文件的 {ratio:.1f}x。")
    current_sections = current.get("sections", {})
    for name in ("BLOCKS", "OBJECTS", "TABLES", "ENTITIES"):
        current_bytes = int(current_sections.get(name, {}).get("byte_count", 0))
        reference_bytes = int(reference.get("sections", {}).get(name, {}).get("byte_count", 0))
        if current_bytes > reference_bytes:
            lines.append(f"{name} 比参考文件多 {current_bytes - reference_bytes:,} bytes。")
    lines.append(
        f"当前有 {current.get('unreachable_block_count', 0):,} 个不可达块，包含 "
        f"{current.get('unreachable_block_entity_count', 0):,} 个块内实体。"
    )
    object_types = current.get("object_bytes", {}).get("by_type", {})
    for name in ("DBCOLOR", "SORTENTSTABLE", "XRECORD"):
        if name in object_types:
            item = object_types[name]
            lines.append(f"OBJECTS/{name}：{item['count']:,} 个对象，占 {item['bytes']:,} bytes。")
    return lines


def build_bloat_audit_html(payload: dict[str, Any]) -> str:
    analyses = payload.get("analyses", {})
    sections = ""
    for label, analysis in analyses.items():
        sections += f"""
        <section>
          <h2>{escape(label)}</h2>
          <table>
            <tr><th>Path</th><td>{escape(str(analysis.get('path')))}</td></tr>
            <tr><th>Size</th><td>{escape(format_value(analysis.get('size_bytes')))} bytes</td></tr>
            <tr><th>Blocks</th><td>{escape(format_value(analysis.get('block_count')))}</td></tr>
            <tr><th>Reachable blocks</th><td>{escape(format_value(analysis.get('reachable_block_count')))}</td></tr>
            <tr><th>Unreachable blocks</th><td>{escape(format_value(analysis.get('unreachable_block_count')))}</td></tr>
            <tr><th>Unreachable block entities</th><td>{escape(format_value(analysis.get('unreachable_block_entity_count')))}</td></tr>
          </table>
          {section_table_html('DXF sections', analysis.get('sections', {}))}
          {counter_table_html('TABLE bytes', analysis.get('table_bytes', {}))}
          {object_bytes_html(analysis.get('object_bytes', {}).get('by_type', {}))}
          <h3>Unused symbol table counts</h3>
          <pre>{escape(json.dumps(analysis.get('unused_symbol_counts', {}), ensure_ascii=False, indent=2))}</pre>
        </section>
        """
    return html_page(
        "DXF Remaining Bloat Audit",
        f"""
        <section>
          <h2>结论</h2>
          <ul>{''.join(f'<li>{escape(line)}</li>' for line in payload.get('conclusion', []))}</ul>
        </section>
        {sections}
        """,
    )


def object_bytes_html(by_type: dict[str, dict[str, int]]) -> str:
    rows = ""
    for name, item in list(by_type.items())[:30]:
        rows += (
            f"<tr><td>{escape(str(name))}</td>"
            f"<td>{escape(format_value(item.get('count', 0)))}</td>"
            f"<td>{escape(format_value(item.get('bytes', 0)))}</td></tr>"
        )
    if not rows:
        rows = '<tr><td colspan="3">None</td></tr>'
    return f"<div><h3>OBJECT bytes</h3><table><tr><th>Type</th><th>Count</th><th>Bytes</th></tr>{rows}</table></div>"


def render_all_step_images(out_dir: Path, manifest: dict[str, Any]) -> None:
    reference = Path(manifest["reference"])
    for step in manifest.get("steps", []):
        if step.get("name") == "baseline":
            before = Path(manifest["source"])
            after = reference
        else:
            before_raw = step.get("input_dxf")
            after_raw = step.get("accepted_after_dxf") or step.get("rejected_after_dxf") or step.get("candidate_after_dxf")
            if not before_raw or not after_raw:
                continue
            before = Path(before_raw)
            after = Path(after_raw)
        step_dir = Path(step.get("step_dir", ""))
        if not step_dir:
            continue
        visual = render_step_images(step_dir, reference, before, after)
        step["visual_check"] = visual


def render_step_images(step_dir: Path, reference: Path, before: Path, after: Path) -> dict[str, Any]:
    reference_png = step_dir / "reference.png"
    before_png = step_dir / "before.png"
    after_png = step_dir / "after.png"
    diff_png = step_dir / "diff.png"
    comparison_png = step_dir / "comparison.png"
    result: dict[str, Any] = {
        "status": "pending",
        "render_mode": "cropped_ai_review",
        "excluded_entity_types": sorted(AI_RENDER_EXCLUDED_ENTITY_TYPES),
        "reference_dxf": str(reference),
        "before_dxf": str(before),
        "after_dxf": str(after),
        "reference_png": str(reference_png),
        "before_png": str(before_png),
        "after_png": str(after_png),
        "diff_png": str(diff_png),
        "comparison_png": str(comparison_png),
        "created_at": now_iso(),
    }
    try:
        reference_bbox = compute_shared_render_bbox([reference])
        before_bbox = compute_shared_render_bbox([before])
        after_bbox = compute_shared_render_bbox([after])
        if bboxes_are_coordinate_compatible(before_bbox, after_bbox):
            before_view_bbox = expand_render_bbox(union_render_bboxes([before_bbox, after_bbox]), 0.0)
            after_view_bbox = before_view_bbox
            diff_alignment = "shared_coordinate_view"
        else:
            before_view_bbox = before_bbox
            after_view_bbox = after_bbox
            diff_alignment = "independent_crops_coordinate_shift_detected"
        result["reference_view_bbox"] = bbox_to_json(reference_bbox)
        result["before_view_bbox"] = bbox_to_json(before_view_bbox)
        result["after_view_bbox"] = bbox_to_json(after_view_bbox)
        result["step_view_bbox"] = bbox_to_json(before_view_bbox)
        result["before_after_diff_alignment"] = diff_alignment
        render_dxf_png(reference, reference_png, view_bbox=reference_bbox)
        render_dxf_png(before, before_png, view_bbox=before_view_bbox)
        render_dxf_png(after, after_png, view_bbox=after_view_bbox)
        result["before_after_diff"] = compare_pngs(before_png, after_png)
        result["reference_after_diff"] = compare_pngs(reference_png, after_png)
        write_diff_png(reference_png, after_png, diff_png)
        write_comparison_png([reference_png, before_png, after_png, diff_png], comparison_png)
        result["status"] = "rendered"
    except Exception as exc:
        result["status"] = "failed"
        result["message"] = str(exc)
    write_json(step_dir / "visual_check.json", result)
    return result


def write_final_visual_check(out_dir: Path, manifest: dict[str, Any], dry_run_ai: bool, skip_ai: bool) -> None:
    visual_dir = out_dir / "final_visual_check"
    visual_dir.mkdir(parents=True, exist_ok=True)
    reference_path = Path(manifest["reference"])
    current_path = Path(manifest["current_dxf"])
    reference_png = visual_dir / "reference.png"
    current_png = visual_dir / "current.png"
    diff_json = visual_dir / "final_visual_check.json"
    report_html = visual_dir / "report.html"
    result: dict[str, Any] = {
        "created_at": now_iso(),
        "reference_dxf": str(reference_path),
        "current_dxf": str(current_path),
        "reference_png": str(reference_png),
        "current_png": str(current_png),
        "status": "pending",
    }
    try:
        render_dxf_png(reference_path, reference_png, view_bbox=compute_shared_render_bbox([reference_path]))
        render_dxf_png(current_path, current_png, view_bbox=compute_shared_render_bbox([current_path]))
        diff = compare_pngs(reference_png, current_png)
        result.update({"status": "rendered", "image_diff": diff})
    except Exception as exc:
        result.update({"status": "failed", "message": str(exc)})
    result["ai_check"] = build_ai_placeholder(dry_run_ai=dry_run_ai, skip_ai=skip_ai, step_name="final_visual_check")
    write_json(diff_json, result)
    report_html.write_text(build_final_visual_html(result, out_dir), encoding="utf-8")
    manifest["final_visual_check"] = {
        "status": result["status"],
        "report_html": str(report_html),
        "json": str(diff_json),
        "reference_png": str(reference_png),
        "current_png": str(current_png),
    }


def render_dxf_png(dxf_path: Path, png_path: Path, view_bbox: tuple[float, float, float, float] | None = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = load_dxf(dxf_path)
    if view_bbox is None:
        view_bbox = compute_shared_render_bbox([dxf_path])
    fig_size = render_figure_size(view_bbox)
    fig = plt.figure(figsize=fig_size, dpi=180)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    frontend = Frontend(ctx, backend)
    filter_func = lambda entity: ai_render_filter(entity, doc)
    try:
        frontend.draw_layout(doc.modelspace(), finalize=True, filter_func=filter_func)
    except ValueError as exc:
        if "dictionary update sequence element" not in str(exc):
            raise
        modelspace = doc.modelspace()
        ctx.set_current_layout(modelspace)
        frontend.set_background(ctx.current_layout_properties.background_color)
        frontend.parent_stack = []
        frontend.draw_entities(modelspace, filter_func=filter_func)
        frontend.pipeline.finalize()
    min_x, min_y, max_x, max_y = view_bbox
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=180, facecolor="white")
    plt.close(fig)


def compute_shared_render_bbox(paths: list[Path]) -> tuple[float, float, float, float]:
    boxes = []
    for path in paths:
        try:
            doc = load_dxf(path)
            box = compute_document_render_bbox(doc)
        except Exception:
            box = None
        if box is not None:
            boxes.append(box)
    if not boxes:
        return (0.0, 0.0, 100.0, 100.0)
    min_x = min(box[0] for box in boxes)
    min_y = min(box[1] for box in boxes)
    max_x = max(box[2] for box in boxes)
    max_y = max(box[3] for box in boxes)
    return expand_render_bbox((min_x, min_y, max_x, max_y), AI_RENDER_MARGIN_RATIO)


def compute_document_render_bbox(doc: DxfDrawing) -> tuple[float, float, float, float] | None:
    from ezdxf import bbox

    boxes = []
    for entity in doc.modelspace():
        if not ai_render_filter(entity, doc):
            continue
        try:
            entity_box = bbox.extents([entity])
        except Exception:
            continue
        try:
            min_x = float(entity_box.extmin.x)
            min_y = float(entity_box.extmin.y)
            max_x = float(entity_box.extmax.x)
            max_y = float(entity_box.extmax.y)
        except Exception:
            continue
        if not all(value == value and abs(value) != float("inf") for value in (min_x, min_y, max_x, max_y)):
            continue
        if max_x <= min_x and max_y <= min_y:
            continue
        boxes.append((min_x, min_y, max_x, max_y))
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def ai_render_filter(entity: object, doc: DxfDrawing | None = None) -> bool:
    try:
        entity_type = entity.dxftype()
    except Exception:
        return False
    if entity_type in AI_RENDER_EXCLUDED_ENTITY_TYPES:
        return False
    if doc is not None:
        try:
            if not is_entity_visible(doc, entity):
                return False
        except Exception:
            return False
    return True


def expand_render_bbox(
    box: tuple[float, float, float, float],
    margin_ratio: float,
) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = box
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad_x = width * margin_ratio
    pad_y = height * margin_ratio
    return (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)


def union_render_bboxes(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def bboxes_are_coordinate_compatible(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    first_w = max(first[2] - first[0], 1.0)
    first_h = max(first[3] - first[1], 1.0)
    second_w = max(second[2] - second[0], 1.0)
    second_h = max(second[3] - second[1], 1.0)
    size_ratio = max(first_w, second_w) / max(min(first_w, second_w), 1.0)
    height_ratio = max(first_h, second_h) / max(min(first_h, second_h), 1.0)
    first_center = ((first[0] + first[2]) / 2.0, (first[1] + first[3]) / 2.0)
    second_center = ((second[0] + second[2]) / 2.0, (second[1] + second[3]) / 2.0)
    center_dx = abs(first_center[0] - second_center[0])
    center_dy = abs(first_center[1] - second_center[1])
    tolerance = max(first_w, first_h, second_w, second_h) * 0.25
    return size_ratio <= 1.2 and height_ratio <= 1.2 and center_dx <= tolerance and center_dy <= tolerance


def render_figure_size(box: tuple[float, float, float, float]) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = box
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    aspect = width / height
    long_side = 10.0
    min_side = 5.0
    if aspect >= 1.0:
        return (long_side, max(min_side, long_side / aspect))
    return (max(min_side, long_side * aspect), long_side)


def bbox_to_json(box: tuple[float, float, float, float] | None) -> list[float] | None:
    if box is None:
        return None
    return [round(float(value), 6) for value in box]


def compare_pngs(left: Path, right: Path) -> dict[str, Any]:
    import numpy as np
    from PIL import Image

    left_image = Image.open(left).convert("RGB")
    right_image = Image.open(right).convert("RGB")
    if left_image.size != right_image.size:
        right_image = right_image.resize(left_image.size)
    left_arr = np.asarray(left_image, dtype=np.int16)
    right_arr = np.asarray(right_image, dtype=np.int16)
    diff = np.abs(left_arr - right_arr)
    changed = np.any(diff > 16, axis=2)
    changed_pixels = int(changed.sum())
    total_pixels = int(changed.shape[0] * changed.shape[1])
    bbox = None
    if changed_pixels:
        ys, xs = np.where(changed)
        bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return {
        "image_size": [left_image.size[0], left_image.size[1]],
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "changed_ratio": changed_pixels / total_pixels if total_pixels else 0.0,
        "mean_abs_channel_delta": float(diff.mean()),
        "changed_bbox": bbox,
    }


def write_diff_png(left: Path, right: Path, out: Path) -> None:
    import numpy as np
    from PIL import Image

    left_image = Image.open(left).convert("RGB")
    right_image = Image.open(right).convert("RGB")
    if left_image.size != right_image.size:
        right_image = right_image.resize(left_image.size)
    left_arr = np.asarray(left_image, dtype=np.int16)
    right_arr = np.asarray(right_image, dtype=np.int16)
    delta = np.abs(left_arr - right_arr).max(axis=2).astype(np.uint8)
    heat = np.zeros((*delta.shape, 3), dtype=np.uint8)
    heat[:, :, 0] = delta
    heat[:, :, 1] = np.clip(delta // 3, 0, 255)
    heat[:, :, 2] = 255 - delta
    Image.fromarray(heat, "RGB").save(out)


def write_comparison_png(images: list[Path], out: Path) -> None:
    from PIL import Image, ImageDraw

    loaded = [Image.open(path).convert("RGB") for path in images if path.exists()]
    if not loaded:
        return
    width = max(image.width for image in loaded)
    height = max(image.height for image in loaded)
    labels = ["reference", "before", "after", "diff"]
    margin = 16
    label_h = 32
    canvas = Image.new("RGB", (width * 2 + margin * 3, (height + label_h) * 2 + margin * 3), "white")
    draw = ImageDraw.Draw(canvas)
    for index, image in enumerate(loaded[:4]):
        row = index // 2
        col = index % 2
        x = margin + col * (width + margin)
        y = margin + row * (height + label_h + margin)
        draw.text((x, y), labels[index], fill=(20, 30, 40))
        canvas.paste(image.resize((width, height)), (x, y + label_h))
    canvas.save(out)


def build_final_visual_html(result: dict[str, Any], out_dir: Path) -> str:
    reference_png = rel_path(out_dir / "final_visual_check", Path(result["reference_png"]))
    current_png = rel_path(out_dir / "final_visual_check", Path(result["current_png"]))
    images = ""
    if Path(result["reference_png"]).exists():
        images += f'<div><h3>Reference</h3><img src="{escape(reference_png)}" alt="reference"></div>'
    if Path(result["current_png"]).exists():
        images += f'<div><h3>Current</h3><img src="{escape(current_png)}" alt="current"></div>'
    return html_page(
        "Final Visual Check",
        f"""
        <section>
          <h2>状态</h2>
          <div class="status {escape(str(result.get('status')))}">{escape(str(result.get('status')))}</div>
          <pre>{escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>
        </section>
        <section>
          <h2>图像</h2>
          <div class="grid images">{images}</div>
        </section>
        <style>.images img {{ width: 100%; border: 1px solid #d9e1ea; background: #fff; }}</style>
        """,
    )


def stats_pair_html(
    left: dict[str, Any],
    right: dict[str, Any],
    left_title: str = "Source",
    right_title: str = "Reference",
) -> str:
    return f"""
    <section>
      <h2>核心指标</h2>
      <table>
        <tr><th>Metric</th><th>{escape(left_title)}</th><th>{escape(right_title)}</th><th>Delta</th></tr>
        {metric_row("File size MB", left["file"]["size_mb"], right["file"]["size_mb"])}
        {metric_row("Modelspace entities", left["modelspace"]["entity_count"], right["modelspace"]["entity_count"])}
        {metric_row("Visible entities", left["modelspace"]["visible_entity_count"], right["modelspace"]["visible_entity_count"])}
        {metric_row("Layers", left["tables"]["layer_count"], right["tables"]["layer_count"])}
        {metric_row("Blocks", left["tables"]["block_count"], right["tables"]["block_count"])}
        {metric_row("Block entities", left["tables"]["block_entity_count"], right["tables"]["block_entity_count"])}
        {metric_row("Exact duplicate linework (geometry)", left["duplicates"]["geometry"]["exact_duplicate_count"], right["duplicates"]["geometry"]["exact_duplicate_count"])}
        {metric_row("Exact duplicate linework (layer)", left["duplicates"]["layer"]["exact_duplicate_count"], right["duplicates"]["layer"]["exact_duplicate_count"])}
      </table>
    </section>
    <section>
      <h2>实体类型 Top</h2>
      <div class="grid">
        {counter_table_html(left_title, left["modelspace"]["entity_type_counts"])}
        {counter_table_html(right_title, right["modelspace"]["entity_type_counts"])}
      </div>
    </section>
    <section>
      <h2>DXF Section 体积 Top</h2>
      <div class="grid">
        {section_table_html(left_title, left["sections"]["sections"])}
        {section_table_html(right_title, right["sections"]["sections"])}
      </div>
    </section>
    """


def metric_row(label: str, left: Any, right: Any) -> str:
    try:
        delta = float(right) - float(left)
        delta_text = f"{delta:,.3f}" if isinstance(left, float) or isinstance(right, float) else f"{int(delta):,}"
    except (TypeError, ValueError):
        delta_text = ""
    return f"<tr><td>{escape(label)}</td><td>{escape(format_value(left))}</td><td>{escape(format_value(right))}</td><td>{escape(delta_text)}</td></tr>"


def counter_table_html(title: str, counter: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{escape(str(key))}</td><td>{escape(format_value(value))}</td></tr>"
        for key, value in list(counter.items())[:30]
    )
    if not rows:
        rows = '<tr><td colspan="2">None</td></tr>'
    return f"<div><h3>{escape(title)}</h3><table><tr><th>Name</th><th>Count</th></tr>{rows}</table></div>"


def section_table_html(title: str, sections: dict[str, dict[str, int]]) -> str:
    rows = ""
    for name, stats in list(sections.items())[:12]:
        rows += (
            f"<tr><td>{escape(name)}</td>"
            f"<td>{escape(format_value(stats.get('byte_count', 0)))}</td>"
            f"<td>{escape(format_value(stats.get('line_count', 0)))}</td></tr>"
        )
    return f"<div><h3>{escape(title)}</h3><table><tr><th>Section</th><th>Bytes</th><th>Lines</th></tr>{rows}</table></div>"


def protection_html(protection: dict[str, Any]) -> str:
    rows = ""
    for check in protection.get("checks", []):
        rows += (
            f"<tr><td>{escape(str(check.get('name')))}</td>"
            f"<td>{escape(str(check.get('status')))}</td>"
            f"<td>{escape(format_value(check.get('before')))}</td>"
            f"<td>{escape(format_value(check.get('after')))}</td>"
            f"<td>{escape(str(check.get('message')))}</td></tr>"
        )
    return f"<table><tr><th>Check</th><th>Status</th><th>Before</th><th>After</th><th>Message</th></tr>{rows}</table>"


def html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #17202a; background: #f5f7fa; }}
    header {{ padding: 20px 28px; background: #17202a; color: #fff; }}
    main {{ padding: 24px 28px 48px; }}
    section {{ margin: 0 0 20px; padding: 18px; background: #fff; border: 1px solid #d9e1ea; border-radius: 6px; }}
    h1 {{ margin: 0; font-size: 22px; }}
    h2 {{ margin: 0 0 12px; font-size: 17px; }}
    h3 {{ margin: 0 0 8px; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid #e6ebf0; text-align: left; vertical-align: top; }}
    th {{ background: #eef3f8; font-weight: 600; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f1720; color: #d8dee9; padding: 12px; border-radius: 6px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .status {{ display: inline-block; padding: 5px 9px; border-radius: 4px; background: #eef3f8; font-weight: 700; }}
    .status.accepted, .status.completed {{ background: #e1f5e9; color: #0b6b38; }}
    .status.rejected {{ background: #fde7e7; color: #a82020; }}
    .status.needs_manual_review {{ background: #fff4d6; color: #7a5700; }}
  </style>
</head>
<body>
  <header><h1>{escape(title)}</h1></header>
  <main>{body}</main>
</body>
</html>
"""


def entity_geometry(entity: object) -> dict[str, Any]:
    entity_type = entity.dxftype()
    if entity_type == "LINE":
        return {"start": point_to_json(entity.dxf.start), "end": point_to_json(entity.dxf.end)}
    if entity_type == "ARC":
        return {
            "center": point_to_json(entity.dxf.center),
            "radius": float(entity.dxf.radius),
            "start_angle": float(entity.dxf.start_angle),
            "end_angle": float(entity.dxf.end_angle),
        }
    if entity_type == "LWPOLYLINE":
        return {"closed": bool(getattr(entity, "closed", False)), "points": [list(point) for point in entity.get_points("xyseb")]}
    if entity_type == "POLYLINE":
        return {
            "closed": bool(getattr(entity, "is_closed", False)),
            "points": [point_to_json(vertex.dxf.location) for vertex in getattr(entity, "vertices", [])],
        }
    return {}


def point_to_json(point: Any) -> list[float]:
    values = tuple(point)
    return [float(values[0]), float(values[1]), float(values[2]) if len(values) > 2 else 0.0]


def signature_to_json(signature: tuple[Any, ...]) -> list[Any]:
    payload: list[Any] = []
    for item in signature:
        if isinstance(item, tuple):
            payload.append(signature_to_json(item))
        else:
            payload.append(item)
    return payload


def format_value(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.3f}"
    if value is None:
        return ""
    return str(value)


def rel_path(base: Path, target: Path) -> str:
    try:
        return str(target.resolve().relative_to(base.resolve())).replace("\\", "/")
    except ValueError:
        return str(target)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
