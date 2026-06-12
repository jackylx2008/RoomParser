"""Auditable room recognition experiment runner for cleaned DXF inputs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from room_extractor.ai import LocalAiClient, LocalAiConfig
from room_extractor.cad import extract_cad_raw, load_dxf
from room_extractor.export.json_review_html import build_json_review_html
from room_extractor.export.json_review_html import _load_source as load_review_source
from room_extractor.extraction import build_room_label_candidates, build_rooms_auto
from room_extractor.extraction.room_candidate_builder import build_room_candidates
from room_extractor.models.drawing import CadRawExtraction
from room_extractor.models.room_candidate import RoomCandidate, RoomCandidateSet
from room_extractor.models.room_label import RoomLabelCandidateSet


DEFAULT_DXF = Path("log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf")
DEFAULT_OUT_DIR = Path("log/room_recognition_experiment")
NON_BOUNDARY_AUXILIARY_LAYER_TOKENS = ("A-DETL-GENF", "A-HOLE-E", "A-STAIR")
STRUCTURAL_COLUMN_LAYER_TOKENS = ("A-STR-COLM",)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_experiment(args)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run auditable room recognition experiments on a cleaned DXF.")
    parser.add_argument("--dxf", default=str(DEFAULT_DXF), help="Cleaned DXF input path.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Experiment output directory.")
    parser.add_argument("--floor", default="L2", help="Optional floor value written to room labels.")
    parser.add_argument("--ai-limit", type=int, help="Maximum room candidate images to check with local AI.")
    parser.add_argument("--skip-ai", action="store_true", help="Skip real local AI validation. Do not use for final validation.")
    parser.add_argument("--base-url", help="OpenAI-compatible local AI base URL.")
    parser.add_argument("--model", help="Local multimodal model name.")
    parser.add_argument("--timeout-seconds", type=int, help="Local AI request timeout.")
    parser.add_argument("--max-tokens", type=int, help="Local AI maximum response tokens.")
    return parser


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    dxf_path = Path(args.dxf)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    input_copy = out_dir / "input_cleaned.dxf"
    if input_copy.resolve() != dxf_path.resolve():
        shutil.copy2(dxf_path, input_copy)

    cad_raw = _extract_visible_cad(dxf_path)
    labels = build_room_label_candidates(cad_raw, floor=args.floor)
    _write_json(out_dir / "cad_raw_visible.json", cad_raw.model_dump(mode="json"))
    _write_json(out_dir / "room_label_candidates.json", labels.model_dump(mode="json"))

    ai_config = _ai_config_from_args(args)
    ai_client = None if args.skip_ai else LocalAiClient(ai_config)
    manifest: dict[str, Any] = {
        "source_dxf": str(dxf_path),
        "output_dir": str(out_dir),
        "local_ai": {
            "skipped": bool(args.skip_ai),
            "base_url": ai_config.base_url,
            "model": ai_config.model,
            "dry_run": False,
        },
        "steps": [],
    }

    if ai_client is not None:
        try:
            ai_client.ensure_server()
            manifest["local_ai"]["health_ok"] = True
        except Exception as exc:
            manifest["local_ai"]["health_ok"] = False
            manifest["local_ai"]["startup_error"] = str(exc)
            ai_client = None

    try:
        step000 = _run_step(
            out_dir=out_dir,
            index=0,
            name="existing_default",
            cad_raw=cad_raw,
            labels=labels,
            floor=args.floor,
            ai_client=ai_client,
            ai_config=ai_config,
            ai_limit=args.ai_limit,
            options={
                "min_boundary_area": 1_000_000.0,
                "max_boundary_area": 2_000_000_000.0,
                "boundary_layers": None,
                "door_gap_min_width": 700.0,
                "door_gap_max_width": 2500.0,
                "wall_gap_stitch_max_width": 300.0,
                "orthogonal_tolerance": 2.0,
                "max_non_orthogonal_edge_length": 50.0,
            },
        )
        step001 = _run_step(
            out_dir=out_dir,
            index=1,
            name="wall_boundary_with_door_gap",
            cad_raw=cad_raw,
            labels=labels,
            floor=args.floor,
            ai_client=ai_client,
            ai_config=ai_config,
            ai_limit=args.ai_limit,
            previous_summary=step000["summary"],
            options={
                "min_boundary_area": 10_000.0,
                "max_boundary_area": 5_000_000_000.0,
                "boundary_layers": ["WALL", "0-面积线", "Defpoints"],
                "door_gap_min_width": 700.0,
                "door_gap_max_width": 2500.0,
                "wall_gap_stitch_max_width": 300.0,
                "orthogonal_tolerance": 2.0,
                "max_non_orthogonal_edge_length": 50.0,
            },
        )
        manifest["steps"] = [step000, step001]
    finally:
        if ai_client is not None:
            ai_client.shutdown_server()

    _write_json(out_dir / "manifest.json", manifest)
    (out_dir / "index.html").write_text(_index_html(manifest), encoding="utf-8")
    print(f"Wrote {out_dir / 'manifest.json'}")
    print(f"Wrote {out_dir / 'index.html'}")
    return manifest


def _extract_visible_cad(dxf_path: Path) -> CadRawExtraction:
    doc = load_dxf(dxf_path)
    return extract_cad_raw(doc, dxf_path, visible_only=True)


def _run_step(
    *,
    out_dir: Path,
    index: int,
    name: str,
    cad_raw: CadRawExtraction,
    labels: RoomLabelCandidateSet,
    floor: str,
    ai_client: LocalAiClient | None,
    ai_config: LocalAiConfig,
    ai_limit: int | None,
    options: dict[str, Any],
    previous_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_dir = out_dir / "steps" / f"{index:03d}_{name}"
    step_dir.mkdir(parents=True, exist_ok=True)
    candidates = build_room_candidates(
        cad_raw,
        labels,
        floor=floor,
        min_boundary_area=float(options["min_boundary_area"]),
        max_boundary_area=float(options["max_boundary_area"]),
        boundary_layers=options["boundary_layers"],
        door_gap_min_width=float(options["door_gap_min_width"]),
        door_gap_max_width=float(options["door_gap_max_width"]),
        wall_gap_stitch_max_width=float(options["wall_gap_stitch_max_width"]),
        orthogonal_tolerance=float(options["orthogonal_tolerance"]),
        max_non_orthogonal_edge_length=float(options["max_non_orthogonal_edge_length"]),
    )
    rooms_auto = build_rooms_auto(candidates)
    _write_json(step_dir / "options.json", options)
    _write_json(step_dir / "room_candidates.json", candidates.model_dump(mode="json"))
    _write_json(step_dir / "rooms_auto.json", rooms_auto.model_dump(mode="json"))
    cad_background_path = step_dir / "cad_background.json"
    cad_auxiliary_path = step_dir / "cad_non_boundary_auxiliary.json"
    cad_columns_path = step_dir / "cad_structural_columns.json"
    _write_json(cad_background_path, _cad_background_payload(cad_raw, include_auxiliary_layers=False))
    _write_json(cad_auxiliary_path, _cad_background_payload(cad_raw, include_auxiliary_layers=True))
    _write_json(cad_columns_path, _cad_columns_payload(cad_raw))
    _write_review_html(
        step_dir / "room_candidates.html",
        cad_background_path,
        cad_auxiliary_path,
        cad_columns_path,
        step_dir / "room_candidates.json",
    )

    stats = _step_stats(candidates)
    automated_check = _automated_check(stats, previous_summary)
    _write_json(step_dir / "automated_check.json", automated_check)
    image_records = _render_room_images(step_dir / "images", cad_raw, candidates)
    _write_json(step_dir / "visual_images.json", image_records)

    ai_check = _run_ai_checks(
        candidates=candidates,
        image_records=image_records,
        client=ai_client,
        config=ai_config,
        limit=ai_limit,
    )
    _write_json(step_dir / "ai_check.json", ai_check)

    status = _step_status(index=index, automated_check=automated_check, ai_check=ai_check)
    step_payload = {
        "step": index,
        "name": name,
        "status": status,
        "path": str(step_dir),
        "options": options,
        "summary": stats,
        "automated_check": automated_check,
        "ai_check": {
            "status": ai_check.get("status"),
            "checked": ai_check.get("checked", 0),
            "failed": ai_check.get("failed", 0),
            "needs_review": ai_check.get("needs_review", 0),
        },
    }
    _write_json(step_dir / "step.json", step_payload)
    (step_dir / "report.html").write_text(_step_html(step_payload, candidates, image_records, ai_check), encoding="utf-8")
    return step_payload


def _write_review_html(
    out_path: Path,
    cad_json_path: Path,
    cad_auxiliary_json_path: Path,
    cad_columns_json_path: Path,
    room_json_path: Path,
) -> None:
    cad_source = load_review_source(
        1,
        cad_json_path,
        include_polylines=True,
        include_texts=True,
        include_boundaries=False,
    )
    cad_source = replace(cad_source, name="DXF房间底图 accepted_after.dxf")
    room_source = load_review_source(
        2,
        room_json_path,
        include_polylines=False,
        include_texts=False,
        include_boundaries=True,
    )
    room_source = replace(room_source, name="房间识别JSON room_candidates.json")
    auxiliary_source = load_review_source(
        3,
        cad_auxiliary_json_path,
        include_polylines=True,
        include_texts=False,
        include_boundaries=False,
    )
    auxiliary_source = replace(auxiliary_source, name="DXF非边界辅助图层")
    column_source = load_review_source(
        4,
        cad_columns_json_path,
        include_polylines=True,
        include_texts=False,
        include_boundaries=False,
    )
    column_source = replace(column_source, name="DXF结构柱图层 A-STR-COLM")
    html = build_json_review_html([cad_source, room_source, auxiliary_source, column_source], title="房间识别实验校核")
    html = _adapt_experiment_review_controls(html)
    html = html.replace(
        "<h1>房间识别实验校核</h1>",
        "<h1>房间识别实验校核</h1>"
        "<p class=\"warning\">已叠加 accepted_after.dxf 的可见 CAD 图元底图。默认底图排除了 "
        "A-DETL-GENF 引出标注斜线、A-HOLE-E 板洞画法和 A-STAIR 楼梯画法；这些内容保留在"
        "“DXF非边界辅助图层”数据源中，可单独打开审计。结构柱单独保留在"
        "“DXF结构柱图层 A-STR-COLM”。</p>",
    )
    out_path.write_text(html, encoding="utf-8")


def _cad_background_payload(cad_raw: CadRawExtraction, *, include_auxiliary_layers: bool) -> dict[str, Any]:
    payload = cad_raw.model_dump(mode="json")
    payload["axes"] = []
    payload["columns"] = []
    payload["blocks"] = []
    payload["polylines"] = [
        polyline
        for polyline in payload.get("polylines", [])
        if _is_non_boundary_auxiliary_layer(str(polyline.get("layer") or "")) is include_auxiliary_layers
        and (include_auxiliary_layers or not _is_structural_column_layer(str(polyline.get("layer") or "")))
    ]
    payload["columns"] = []
    if include_auxiliary_layers:
        payload["texts"] = []
    payload["metadata"] = {
        "source": "room_recognition_experiment",
        "include_auxiliary_layers": include_auxiliary_layers,
        "non_boundary_auxiliary_layer_tokens": list(NON_BOUNDARY_AUXILIARY_LAYER_TOKENS),
    }
    return payload


def _cad_columns_payload(cad_raw: CadRawExtraction) -> dict[str, Any]:
    payload = cad_raw.model_dump(mode="json")
    payload["axes"] = []
    payload["blocks"] = []
    payload["texts"] = []
    payload["polylines"] = [
        polyline
        for polyline in payload.get("polylines", [])
        if _is_structural_column_layer(str(polyline.get("layer") or ""))
    ]
    payload["columns"] = [
        column
        for column in payload.get("columns", [])
        if _is_structural_column_layer(str(column.get("layer") or ""))
    ]
    payload["metadata"] = {
        "source": "room_recognition_experiment",
        "structural_column_layer_tokens": list(STRUCTURAL_COLUMN_LAYER_TOKENS),
    }
    return payload


def _is_non_boundary_auxiliary_layer(layer: str) -> bool:
    normalized = layer.upper()
    return any(token in normalized for token in NON_BOUNDARY_AUXILIARY_LAYER_TOKENS)


def _is_structural_column_layer(layer: str) -> bool:
    normalized = layer.upper()
    return any(token in normalized for token in STRUCTURAL_COLUMN_LAYER_TOKENS)


def _adapt_experiment_review_controls(html: str) -> str:
    replacements = {
        '<strong>显示内容</strong>': '<strong>显示图层</strong>',
        '<strong>JSON 数据源</strong>': '<strong>数据源开关</strong>',
        '<label><input type="checkbox" data-toggle-class="hide-axes" checked> 轴线</label>':
            '<label><input type="checkbox" data-toggle-class="hide-axes" checked> 识别-轴线</label>',
        '<label><input type="checkbox" data-toggle-class="hide-axis-labels" checked> 轴号</label>':
            '<label><input type="checkbox" data-toggle-class="hide-axis-labels" checked> 识别-轴号</label>',
        '<label><input type="checkbox" data-toggle-class="hide-columns" checked> 结构柱</label>':
            '<label><input type="checkbox" data-toggle-class="hide-columns" checked> 识别-结构柱</label>',
        '<label><input type="checkbox" data-toggle-class="hide-rooms" checked> 房间识别结果</label>':
            '<label><input type="checkbox" data-toggle-class="hide-rooms" checked> 识别-房间结果</label>',
        '<label><input type="checkbox" data-toggle-class="hide-room-labels" checked> 房间标注</label>':
            '<label><input type="checkbox" data-toggle-class="hide-room-labels" checked> 识别-房间标注</label>',
        '<label><input type="checkbox" data-toggle-class="hide-boundaries"> 边界候选（需 --include-boundaries）</label>':
            '<label><input type="checkbox" data-toggle-class="hide-boundaries" checked> 识别-边界候选</label>',
        '<label><input type="checkbox" data-toggle-class="hide-polylines"> 多段线（需 --include-polylines）</label>':
            '<label><input type="checkbox" data-toggle-class="hide-polylines" checked> DXF图元-线/弧/多段线</label>',
        '<label><input type="checkbox" data-toggle-class="hide-texts"> 文本点（需 --include-texts）</label>':
            '<label><input type="checkbox" data-toggle-class="hide-texts" checked> DXF底图-原始文字</label>',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    html = html.replace(
        '<label><input type="checkbox" data-toggle-class="hide-source-3" checked> '
        '<span class="legend-dot" style="background:#16a34a"></span>DXF非边界辅助图层</label>',
        '<label><input type="checkbox" data-toggle-class="hide-source-3"> '
        '<span class="legend-dot" style="background:#16a34a"></span>DXF非边界辅助图层（默认关闭）</label>',
    )
    return html


def _step_stats(candidates: RoomCandidateSet) -> dict[str, Any]:
    status_counts = Counter(room.status for room in candidates.room_candidates)
    issue_counts = Counter(issue.issue_code for room in candidates.room_candidates for issue in room.issues)
    door_bridges = _unique_door_gap_bridge_count(candidates)
    wall_stitches = _unique_wall_gap_stitch_count(candidates)
    return {
        "room_candidate_count": len(candidates.room_candidates),
        "boundary_candidate_count": len(candidates.boundary_candidates),
        "matched_count": status_counts.get("matched", 0),
        "matched_fallback_count": status_counts.get("matched_fallback", 0),
        "auto_failed_count": status_counts.get("auto_failed", 0),
        "status_counts": dict(status_counts),
        "issue_counts": dict(issue_counts),
        "door_gap_bridge_count": door_bridges,
        "wall_gap_stitch_count": wall_stitches,
        "summary": candidates.summary,
    }


def _unique_door_gap_bridge_count(candidates: RoomCandidateSet) -> int:
    bridges_by_layer: dict[str, int] = {}
    for boundary in candidates.boundary_candidates:
        count = int(boundary.metadata.get("door_gap_bridge_count") or 0)
        if count <= 0:
            continue
        bridges_by_layer[boundary.layer] = max(count, bridges_by_layer.get(boundary.layer, 0))
    return sum(bridges_by_layer.values())


def _unique_wall_gap_stitch_count(candidates: RoomCandidateSet) -> int:
    stitches_by_layer: dict[str, int] = {}
    for boundary in candidates.boundary_candidates:
        count = int(boundary.metadata.get("wall_gap_stitch_count") or 0)
        if count <= 0:
            continue
        stitches_by_layer[boundary.layer] = max(count, stitches_by_layer.get(boundary.layer, 0))
    return sum(stitches_by_layer.values())


def _automated_check(stats: dict[str, Any], previous_summary: dict[str, Any] | None) -> dict[str, Any]:
    matched_total = int(stats["matched_count"]) + int(stats["matched_fallback_count"])
    payload = {
        "parser_ok": True,
        "room_candidate_count_positive": int(stats["room_candidate_count"]) > 0,
        "matched_total": matched_total,
        "boundary_candidate_count": int(stats["boundary_candidate_count"]),
        "door_gap_bridge_count": int(stats["door_gap_bridge_count"]),
        "improved_over_previous": None,
    }
    if previous_summary is not None:
        previous_matched = int(previous_summary.get("matched_count", 0)) + int(previous_summary.get("matched_fallback_count", 0))
        payload["improved_over_previous"] = matched_total > previous_matched
        payload["previous_matched_total"] = previous_matched
    payload["passed"] = payload["room_candidate_count_positive"] and matched_total > 0
    return payload


def _render_room_images(image_dir: Path, cad_raw: CadRawExtraction, candidates: RoomCandidateSet) -> list[dict[str, Any]]:
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    image_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    drawable_lines = [polyline for polyline in cad_raw.polylines if len(polyline.points) >= 2]
    for room in candidates.room_candidates:
        image_path = image_dir / f"{room.room_candidate_id}.png"
        bbox = _room_render_bbox(room)
        if bbox is None:
            bbox = _cad_bounds(drawable_lines)
        if bbox is None:
            continue
        min_x, min_y, max_x, max_y = _pad_bbox(bbox, ratio=0.35, min_pad=2000.0)
        fig, ax = plt.subplots(figsize=(8, 6), dpi=150)
        ax.set_facecolor("white")
        for polyline in drawable_lines:
            points = polyline.points
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            ax.plot(xs, ys, color="#9ca3af", linewidth=0.65, alpha=0.75)
        for boundary in candidates.boundary_candidates:
            points = [*boundary.polygon_cad, boundary.polygon_cad[0]] if boundary.polygon_cad else []
            if not points:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            ax.plot(xs, ys, color="#60a5fa", linewidth=0.9, alpha=0.45)
        if room.boundary is not None:
            points = [*room.boundary.polygon_cad, room.boundary.polygon_cad[0]]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            ax.fill(xs, ys, color="#f97316", alpha=0.18)
            ax.plot(xs, ys, color="#ea580c", linewidth=1.8)
        ax.scatter([room.label_center[0]], [room.label_center[1]], s=40, color="#dc2626", zorder=5)
        label = " ".join(part for part in [room.room_number, room.room_name] if part) or room.room_candidate_id
        ax.text(room.label_center[0], room.label_center[1], label, color="#111827", fontsize=9, ha="center", va="bottom")
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")
        fig.savefig(image_path, bbox_inches="tight", pad_inches=0.08)
        plt.close(fig)
        records.append(
            {
                "room_candidate_id": room.room_candidate_id,
                "room_number": room.room_number,
                "room_name": room.room_name,
                "status": room.status,
                "image_path": str(image_path),
                "boundary_id": room.boundary.boundary_id if room.boundary else None,
            }
        )
    return records


def _room_render_bbox(room: RoomCandidate) -> tuple[float, float, float, float] | None:
    bboxes = [room.label_bbox]
    if room.boundary is not None:
        bboxes.append(room.boundary.bbox_cad)
    return _merge_bboxes(bboxes)


def _cad_bounds(polylines) -> tuple[float, float, float, float] | None:
    bboxes = [polyline.bbox for polyline in polylines if polyline.bbox is not None]
    return _merge_bboxes(bboxes)


def _merge_bboxes(bboxes) -> tuple[float, float, float, float] | None:
    clean = [bbox for bbox in bboxes if bbox is not None]
    if not clean:
        return None
    return (
        min(float(bbox[0]) for bbox in clean),
        min(float(bbox[1]) for bbox in clean),
        max(float(bbox[2]) for bbox in clean),
        max(float(bbox[3]) for bbox in clean),
    )


def _pad_bbox(bbox: tuple[float, float, float, float], ratio: float, min_pad: float) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = bbox
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(width, height) * ratio
    pad = max(pad, min_pad)
    return (min_x - pad, min_y - pad, max_x + pad, max_y + pad)


def _run_ai_checks(
    *,
    candidates: RoomCandidateSet,
    image_records: list[dict[str, Any]],
    client: LocalAiClient | None,
    config: LocalAiConfig,
    limit: int | None,
) -> dict[str, Any]:
    if client is None:
        return {
            "status": "unavailable",
            "checked": 0,
            "failed": 0,
            "needs_review": 0,
            "model": config.model,
            "base_url": config.base_url,
            "dry_run": False,
        }
    room_by_id = {room.room_candidate_id: room for room in candidates.room_candidates}
    checks = []
    failed = 0
    needs_review = 0
    for record in image_records:
        if limit is not None and len(checks) >= limit:
            break
        room = room_by_id.get(str(record["room_candidate_id"]))
        if room is None:
            continue
        prompt = _ai_prompt(room)
        try:
            response = client.chat_with_image(prompt, record["image_path"])
            parsed = _parse_ai_response(response)
            if parsed.get("needs_review") is True:
                needs_review += 1
            checks.append(
                {
                    "room_candidate_id": room.room_candidate_id,
                    "image_path": record["image_path"],
                    "status": "ok",
                    "result": parsed,
                }
            )
        except Exception as exc:
            failed += 1
            checks.append(
                {
                    "room_candidate_id": room.room_candidate_id,
                    "image_path": record["image_path"],
                    "status": "failed",
                    "message": str(exc),
                }
            )
    return {
        "status": "ok" if failed == 0 and checks else "failed" if failed else "empty",
        "checked": len(checks),
        "failed": failed,
        "needs_review": needs_review,
        "model": config.model,
        "base_url": config.base_url,
        "dry_run": False,
        "checks": checks,
    }


def _ai_prompt(room: RoomCandidate) -> str:
    boundary = room.boundary
    boundary_summary = "无匹配边界"
    if boundary is not None:
        boundary_summary = (
            f"边界ID={boundary.boundary_id}, 图层={boundary.layer}, "
            f"面积={boundary.area_cad / 1_000_000.0:.2f}平方米, "
            f"门洞补边数={boundary.metadata.get('door_gap_bridge_count', 0)}"
        )
    return (
        "你是建筑平面图房间边界识别校核助手。请只根据图片和以下自动结果判断，不要猜测截图外内容。"
        "图片中灰线是CAD墙/线，蓝线是候选边界，橙色填充和橙线是当前匹配房间边界，红点是房间文字中心。\n\n"
        f"房间候选: {room.room_candidate_id}\n"
        f"房号: {room.room_number}\n"
        f"房名: {room.room_name}\n"
        f"类别: {room.room_category}\n"
        f"匹配状态: {room.status}\n"
        f"匹配方式: {room.match_method}\n"
        f"{boundary_summary}\n\n"
        "门洞规则：清理后的DXF已删除门图形，墙上700mm到2500mm的开口应视为门洞并桥接为房间分隔边。"
        "请检查橙色边界是否围住该房间，是否因为门洞未桥接而漏边，或是否把多个房间合并成过大的边界。\n\n"
        "只返回JSON，不要Markdown。Schema:"
        '{"visible": true/false, "boundary_correct": true/false/null, '
        '"label_inside_room": true/false/null, "door_gap_handled": true/false/null, '
        '"over_merged_boundary": true/false, "missing_wall_or_gap": true/false, '
        '"needs_review": true/false, "confidence": 0.0, "notes": "简短中文原因"}'
    )


def _parse_ai_response(response: dict[str, Any]) -> dict[str, Any]:
    content = str(response.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    if not content:
        raise ValueError("Local AI response did not contain message.content")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Local AI response is not JSON: {content[:200]}")
    parsed = json.loads(content[start : end + 1])
    parsed["raw_content"] = content
    return parsed


def _step_status(index: int, automated_check: dict[str, Any], ai_check: dict[str, Any]) -> str:
    if index == 0:
        return "baseline"
    if not automated_check.get("passed"):
        return "rejected"
    if ai_check.get("status") != "ok":
        return "needs_manual_review"
    if ai_check.get("failed", 0):
        return "needs_manual_review"
    return "needs_manual_review" if ai_check.get("needs_review", 0) else "candidate_passed_ai"


def _ai_config_from_args(args: argparse.Namespace) -> LocalAiConfig:
    config = LocalAiConfig.from_env()
    if args.base_url:
        config = replace(config, base_url=str(args.base_url).rstrip("/"))
    if args.model:
        config = replace(config, model=str(args.model))
    if args.timeout_seconds:
        config = replace(config, timeout_seconds=int(args.timeout_seconds))
    if args.max_tokens:
        config = replace(config, max_tokens=int(args.max_tokens))
    return config


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _index_html(manifest: dict[str, Any]) -> str:
    rows = []
    for step in manifest.get("steps", []):
        summary = step.get("summary", {})
        step_href = Path("steps") / Path(step.get("path", "")).name / "report.html"
        rows.append(
            "<tr>"
            f"<td>{step.get('step')}</td>"
            f"<td><a href=\"{escape(step_href.as_posix())}\">{escape(step.get('name', ''))}</a></td>"
            f"<td>{escape(step.get('status', ''))}</td>"
            f"<td>{summary.get('room_candidate_count')}</td>"
            f"<td>{summary.get('boundary_candidate_count')}</td>"
            f"<td>{summary.get('matched_count')}</td>"
            f"<td>{summary.get('auto_failed_count')}</td>"
            f"<td>{summary.get('door_gap_bridge_count')}</td>"
            f"<td>{escape(str(step.get('ai_check', {}).get('status')))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Room Recognition Experiment</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#1f2933}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #d1d5db;padding:8px;text-align:left}"
        "th{background:#f3f4f6}</style></head><body>"
        "<h1>Room Recognition Experiment</h1>"
        f"<p>Source DXF: <code>{escape(str(manifest.get('source_dxf')))}</code></p>"
        f"<p>Local AI: <code>{escape(json.dumps(manifest.get('local_ai'), ensure_ascii=False))}</code></p>"
        "<table><thead><tr><th>Step</th><th>Name</th><th>Status</th><th>Rooms</th><th>Boundaries</th>"
        "<th>Matched</th><th>Failed</th><th>Door Bridges</th><th>AI</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def _step_html(
    step: dict[str, Any],
    candidates: RoomCandidateSet,
    image_records: list[dict[str, Any]],
    ai_check: dict[str, Any],
) -> str:
    images = []
    ai_by_room = {item.get("room_candidate_id"): item for item in ai_check.get("checks", [])}
    for record in image_records:
        ai_item = ai_by_room.get(record["room_candidate_id"], {})
        result = ai_item.get("result", {})
        images.append(
            "<section>"
            f"<h3>{escape(record['room_candidate_id'])} {escape(str(record.get('room_number') or ''))} {escape(str(record.get('room_name') or ''))}</h3>"
            f"<p>Status: <code>{escape(str(record.get('status')))}</code> Boundary: <code>{escape(str(record.get('boundary_id')))}</code></p>"
            f"<img src=\"{escape(Path(record['image_path']).relative_to(Path(step['path'])).as_posix())}\" style=\"max-width:760px;border:1px solid #d1d5db\">"
            f"<pre>{escape(json.dumps(result or ai_item, ensure_ascii=False, indent=2))}</pre>"
            "</section>"
        )
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Room Step Report</title>"
        "<style>body{font-family:Arial,'Microsoft YaHei',sans-serif;margin:24px;color:#1f2933}"
        "pre{white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;padding:10px}"
        "section{margin:18px 0;padding-bottom:18px;border-bottom:1px solid #e5e7eb}</style></head><body>"
        f"<h1>{escape(step.get('name', ''))}</h1>"
        f"<p>Status: <code>{escape(step.get('status', ''))}</code></p>"
        f"<p><a href=\"room_candidates.html\">房间识别HTML校核页</a></p>"
        f"<h2>Step Summary</h2><pre>{escape(json.dumps(step, ensure_ascii=False, indent=2))}</pre>"
        f"<h2>Candidate Summary</h2><pre>{escape(json.dumps(candidates.summary, ensure_ascii=False, indent=2))}</pre>"
        f"<h2>AI Checks</h2><pre>{escape(json.dumps(ai_check, ensure_ascii=False, indent=2))}</pre>"
        f"<h2>Room Images</h2>{''.join(images)}"
        "</body></html>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
