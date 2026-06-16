from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import fitz
from shapely.geometry import MultiPolygon, Point as ShapelyPoint, Polygon


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from room_extractor.ai.local_ai_client import LocalAiClient, LocalAiConfig  # noqa: E402
from room_extractor.cad.dxf_loader import load_dxf  # noqa: E402
from room_extractor.cad.polyline_extractor import _extract_points, _is_entity_closed  # noqa: E402
from room_extractor.export.json_review_html import run_json_review_html  # noqa: E402
from room_extractor.geometry import calculate_bbox  # noqa: E402


Point = tuple[float, float]
BBox = tuple[float, float, float, float]

DEFAULT_DXF = Path("data/input/dxf/L2_20.00m平面图-BuildingFacadeOutline.dxf")
DEFAULT_COLUMNS = Path("data/output/json/cad_raw_columns_from_full_real.json")
DEFAULT_STEP_DIR = Path("log/building_facade_inner_envelope/steps/002_curve_facade_profile")
ENVELOPE_LAYER = "BUILDING-FACADE-INNER-ENVELOPE"
OUTER_LAYER = "BUILDING-FACADE-OUTER-PROFILE"


@dataclass(frozen=True)
class LineSample:
    x: float
    y: float
    layer: str
    entity_type: str


@dataclass(frozen=True)
class ColumnData:
    payload: dict[str, Any]
    centers: list[Point]
    bboxes: list[BBox]
    polygons: list[list[Point]]


@dataclass(frozen=True)
class FacadeSamples:
    samples: list[LineSample]
    entity_counts: Counter[str]
    layer_counts: Counter[str]
    source_bbox: BBox | None
    sampled_bbox: BBox | None
    window_bbox: BBox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an inward building facade envelope from the L2 facade-outline DXF and structural columns."
    )
    parser.add_argument("--dxf", default=str(DEFAULT_DXF), help="Facade outline DXF path.")
    parser.add_argument("--columns", default=str(DEFAULT_COLUMNS), help="Existing structural-column cad_raw JSON path.")
    parser.add_argument("--out-dir", default=str(DEFAULT_STEP_DIR), help="Audit step output directory.")
    parser.add_argument("--inner-offset", type=float, default=300.0, help="CAD-unit inward offset from detected outer facade profile.")
    parser.add_argument("--subject-margin", type=float, default=8000.0, help="Column bbox expansion used to crop facade line samples.")
    parser.add_argument("--bin-width", type=float, default=2000.0, help="X bin width used to preserve the curved upper facade profile.")
    parser.add_argument("--sample-step", type=float, default=1200.0, help="Maximum distance between sampled points along long segments.")
    parser.add_argument("--edge-quantile", type=float, default=0.001, help="Robust edge quantile for straight left/right/bottom edges.")
    parser.add_argument("--top-quantile", type=float, default=0.995, help="Per-bin top profile quantile.")
    parser.add_argument("--column-clearance", type=float, default=500.0, help="Minimum clearance from column bbox to detected outer profile.")
    parser.add_argument("--min-column-coverage", type=float, default=0.90, help="Minimum accepted inner-envelope column-center coverage.")
    parser.add_argument("--render-sample-limit", type=int, default=12000, help="Maximum sampled facade points rendered into SVG/PNG.")
    parser.add_argument("--skip-ai-validation", action="store_true", help="Skip the real local AI image validation call.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "accepted" else 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    dxf_path = Path(args.dxf)
    columns_path = Path(args.columns)
    step_dir = Path(args.out_dir)
    step_dir.mkdir(parents=True, exist_ok=True)

    columns = _load_columns(columns_path)
    facade = _extract_facade_samples(
        dxf_path=dxf_path,
        columns=columns,
        subject_margin=float(args.subject_margin),
        sample_step=float(args.sample_step),
    )
    before_stats = _before_stats(dxf_path, columns_path, columns, facade)
    _write_json(step_dir / "before_stats.json", before_stats)
    _write_json(step_dir / "input_original.json", {"dxf": _file_fingerprint(dxf_path), "columns": _file_fingerprint(columns_path)})

    outer_points, top_profile_metadata = _build_outer_profile(
        dxf_path,
        facade.samples,
        columns,
        bin_width=float(args.bin_width),
        edge_quantile=float(args.edge_quantile),
        top_quantile=float(args.top_quantile),
        column_clearance=float(args.column_clearance),
    )
    outer_polygon = _valid_polygon(outer_points)
    inner_polygon = _inner_offset_polygon(outer_polygon, offset=float(args.inner_offset))
    inner_points = _polygon_points(inner_polygon)
    outer_points = _polygon_points(outer_polygon)

    after_stats = _after_stats(outer_polygon, inner_polygon, columns, float(args.inner_offset), outer_points, inner_points)
    after_stats["top_profile"] = top_profile_metadata
    automated_check = _automated_check(after_stats, min_column_coverage=float(args.min_column_coverage))
    status = "accepted" if automated_check["ok"] else "rejected"
    output_payload = _build_output_payload(
        dxf_path=dxf_path,
        columns_path=columns_path,
        columns=columns,
        outer_points=outer_points,
        inner_points=inner_points,
        after_stats=after_stats,
        automated_check=automated_check,
        top_profile_metadata=top_profile_metadata,
        args=args,
    )

    candidate_path = step_dir / "candidate_after.json"
    accepted_or_rejected_path = step_dir / f"{status}_after.json"
    _write_json(candidate_path, output_payload)
    _write_json(accepted_or_rejected_path, output_payload)
    _write_json(step_dir / "after_stats.json", after_stats)
    _write_json(step_dir / "automated_check.json", automated_check)
    _write_json(
        step_dir / "removed_or_changed_data.json",
        {
            "source_files_modified": False,
            "source_dxf_entities_removed": 0,
            "operation": "derived facade profile and inward envelope; inputs are read-only",
        },
    )

    before_svg = _build_svg(facade, columns, outer_points=outer_points, inner_points=[], render_sample_limit=args.render_sample_limit)
    after_svg = _build_svg(facade, columns, outer_points=outer_points, inner_points=inner_points, render_sample_limit=args.render_sample_limit)
    (step_dir / "before.svg").write_text(before_svg, encoding="utf-8")
    (step_dir / "after.svg").write_text(after_svg, encoding="utf-8")
    _render_svg_png(before_svg, step_dir / "before.png")
    _render_svg_png(after_svg, step_dir / "after.png")
    comparison_svg = _build_comparison_svg_from_pngs(step_dir / "before.png", step_dir / "after.png")
    (step_dir / "comparison.svg").write_text(comparison_svg, encoding="utf-8")
    _render_svg_png(comparison_svg, step_dir / "comparison.png")
    _write_json(step_dir / "visual_check.json", {"before_png": "before.png", "after_png": "after.png", "comparison_png": "comparison.png"})

    ai_validation = _run_ai_validation(step_dir / "comparison.png", after_stats, skip=bool(args.skip_ai_validation))
    _write_json(step_dir / "ai_validation.json", ai_validation)
    review_html_path = step_dir / "json_review_facade_outer_inner.html"
    _write_json_review_html(accepted_or_rejected_path, review_html_path)
    report_html = _build_report_html(status, before_stats, after_stats, automated_check, ai_validation)
    (step_dir / "report.html").write_text(report_html, encoding="utf-8")
    manifest = _update_manifest(step_dir, status, accepted_or_rejected_path, automated_check)

    return {
        "status": status,
        "step_dir": str(step_dir),
        "candidate": str(candidate_path),
        f"{status}_after": str(accepted_or_rejected_path),
        "report": str(step_dir / "report.html"),
        "json_review_html": str(review_html_path),
        "manifest": str(manifest),
        "automated_check_ok": automated_check["ok"],
        "ai_validation_status": ai_validation["status"],
    }


def _load_columns(path: Path) -> ColumnData:
    payload = json.loads(path.read_text(encoding="utf-8"))
    centers: list[Point] = []
    bboxes: list[BBox] = []
    polygons: list[list[Point]] = []
    for column in payload.get("columns", []):
        center = _point(column.get("center"))
        bbox = _bbox(column.get("bbox"))
        polygon = [_point(point) for point in column.get("polygon", [])]
        polygon = [point for point in polygon if point is not None]
        if center is not None:
            centers.append(center)
        if bbox is not None:
            bboxes.append(bbox)
        if len(polygon) >= 3:
            polygons.append(polygon)
    if not centers or not bboxes:
        raise ValueError(f"No usable columns found in {path}")
    return ColumnData(payload=payload, centers=centers, bboxes=bboxes, polygons=polygons)


def _extract_facade_samples(dxf_path: Path, columns: ColumnData, subject_margin: float, sample_step: float) -> FacadeSamples:
    column_bbox = _bbox_for_points([point for bbox in columns.bboxes for point in [(bbox[0], bbox[1]), (bbox[2], bbox[3])]])
    window = (
        column_bbox[0] - subject_margin,
        column_bbox[1] - subject_margin,
        column_bbox[2] + subject_margin,
        column_bbox[3] + subject_margin,
    )
    doc = load_dxf(dxf_path)
    samples: list[LineSample] = []
    entity_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    source_bboxes: list[BBox] = []
    for entity in doc.modelspace():
        entity_type = entity.dxftype()
        entity_counts[entity_type] += 1
        layer = str(getattr(entity.dxf, "layer", "0"))
        layer_counts[f"{layer}::{entity_type}"] += 1
        if entity_type not in {"LWPOLYLINE", "POLYLINE", "LINE", "ARC"}:
            continue
        try:
            points = _extract_points(entity)
            bbox = calculate_bbox(points)
        except Exception:
            continue
        if bbox is None:
            continue
        source_bboxes.append(bbox)
        if not _bbox_intersects(bbox, window):
            continue
        ring = [*points, points[0]] if _is_entity_closed(entity) and len(points) >= 3 else points
        for start, end in zip(ring, ring[1:]):
            for x, y in _sample_segment(start, end, sample_step=sample_step):
                if window[0] <= x <= window[2] and window[1] <= y <= window[3]:
                    samples.append(LineSample(x=x, y=y, layer=layer, entity_type=entity_type))
    if len(samples) < 100:
        raise ValueError(f"Too few facade line samples extracted from {dxf_path}: {len(samples)}")
    return FacadeSamples(
        samples=samples,
        entity_counts=entity_counts,
        layer_counts=layer_counts,
        source_bbox=_bbox_union(source_bboxes),
        sampled_bbox=_bbox_for_points([(sample.x, sample.y) for sample in samples]),
        window_bbox=window,
    )


def _build_outer_profile(
    dxf_path: Path,
    samples: list[LineSample],
    columns: ColumnData,
    bin_width: float,
    edge_quantile: float,
    top_quantile: float,
    column_clearance: float,
) -> tuple[list[Point], dict[str, Any]]:
    chain = _extract_curved_top_facade_chain(dxf_path)
    if chain is not None:
        top_points, metadata = chain
        bottom_y = min(_quantile([sample.y for sample in samples], edge_quantile * 10.0), min(bbox[1] for bbox in columns.bboxes) - column_clearance)
        left_x = min(top_points[0][0], min(bbox[0] for bbox in columns.bboxes) - column_clearance)
        right_x = max(top_points[-1][0], max(bbox[2] for bbox in columns.bboxes) + column_clearance)
        if top_points[0][0] > left_x:
            top_points = [(left_x, top_points[0][1]), *top_points]
        if top_points[-1][0] < right_x:
            top_points = [*top_points, (right_x, top_points[-1][1])]
        polygon = [(left_x, bottom_y), (right_x, bottom_y), *reversed(top_points)]
        return _dedupe_adjacent_points(polygon), metadata

    xs = [sample.x for sample in samples]
    ys = [sample.y for sample in samples]
    left_x = min(_quantile(xs, edge_quantile), min(bbox[0] for bbox in columns.bboxes) - column_clearance)
    right_x = max(_quantile(xs, 1.0 - edge_quantile), max(bbox[2] for bbox in columns.bboxes) + column_clearance)
    bottom_y = min(_quantile(ys, edge_quantile * 10.0), min(bbox[1] for bbox in columns.bboxes) - column_clearance)
    top_min = max(bbox[3] for bbox in columns.bboxes) + column_clearance

    bin_count = max(8, int(math.ceil((right_x - left_x) / bin_width)))
    actual_width = (right_x - left_x) / bin_count
    top_points: list[Point] = []
    for index in range(bin_count + 1):
        x = left_x + actual_width * index
        half_width = actual_width * 0.75
        bin_ys = [sample.y for sample in samples if abs(sample.x - x) <= half_width]
        column_bin_tops = [
            bbox[3]
            for bbox in columns.bboxes
            if bbox[0] - half_width <= x <= bbox[2] + half_width
        ]
        y = _quantile(bin_ys, top_quantile) if bin_ys else top_min
        if column_bin_tops:
            y = max(y, max(column_bin_tops) + column_clearance)
        top_points.append((x, max(y, top_min)))
    top_points = _smooth_profile(top_points, radius=2)
    top_points = _dedupe_adjacent_points(top_points)
    polygon = [(left_x, bottom_y), (right_x, bottom_y), *reversed(top_points)]
    return _dedupe_adjacent_points(polygon), {"method": "robust_quantile_upper_profile", "source_entity_count": 0}


def _extract_curved_top_facade_chain(dxf_path: Path) -> tuple[list[Point], dict[str, Any]] | None:
    doc = load_dxf(dxf_path)
    selected: list[dict[str, Any]] = []
    for index, entity in enumerate(doc.modelspace()):
        entity_type = entity.dxftype()
        if entity_type not in {"LWPOLYLINE", "POLYLINE", "LINE", "ARC"}:
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        try:
            points = _extract_points(entity)
            bbox = calculate_bbox(points)
        except Exception:
            continue
        if bbox is None or len(points) < 2:
            continue
        role = _top_facade_entity_role(layer, entity_type, bbox)
        if role is None:
            continue
        oriented = _orient_left_to_right(_densify_points(points, max_step=1200.0))
        selected.append(
            {
                "index": index,
                "layer": layer,
                "entity_type": entity_type,
                "bbox": bbox,
                "role": role,
                "points": oriented,
            }
        )
    if len(selected) < 4:
        return None
    selected.sort(key=lambda item: (item["points"][0][0], item["points"][-1][0], item["role"]))
    chain: list[Point] = []
    used: list[dict[str, Any]] = []
    for item in selected:
        points = item["points"]
        if not chain:
            chain.extend(points)
            used.append(_selected_entity_summary(item))
            continue
        if points[-1][0] <= chain[-1][0] + 500.0:
            continue
        bridge_gap = points[0][0] - chain[-1][0]
        if bridge_gap > 30000.0:
            continue
        append_points = [point for point in points if point[0] > chain[-1][0] + 50.0]
        if not append_points:
            continue
        chain.extend(append_points)
        used.append(_selected_entity_summary(item))
    chain = _dedupe_adjacent_points(chain)
    if len(chain) < 10:
        return None
    x_span = chain[-1][0] - chain[0][0]
    y_span = max(point[1] for point in chain) - min(point[1] for point in chain)
    if x_span < 400000.0 or y_span < 10000.0:
        return None
    return chain, {
        "method": "explicit_curved_top_facade_chain",
        "source_entity_count": len(used),
        "source_entities": used,
        "chain_point_count": len(chain),
        "chain_bbox": _bbox_for_points(chain),
    }


def _top_facade_entity_role(layer: str, entity_type: str, bbox: BBox) -> str | None:
    min_x, min_y, max_x, max_y = bbox
    if "A-FIN-S" in layer and max_y > 120000.0 and min_x < 217000.0:
        return "north_curve_and_recess"
    if "20m" in layer and entity_type == "ARC" and min_x > 200000.0 and max_y > 135000.0 and max_x > 350000.0:
        return "east_curve"
    return None


def _orient_left_to_right(points: list[Point]) -> list[Point]:
    if len(points) >= 2 and points[0][0] > points[-1][0]:
        return list(reversed(points))
    return points


def _densify_points(points: list[Point], max_step: float) -> list[Point]:
    densified: list[Point] = []
    for start, end in zip(points, points[1:]):
        segment_points = _sample_segment(start, end, sample_step=max_step)
        if densified:
            densified.extend(segment_points[1:])
        else:
            densified.extend(segment_points)
    return densified or points


def _selected_entity_summary(item: dict[str, Any]) -> dict[str, Any]:
    bbox = item["bbox"]
    return {
        "source_entity_index": item["index"],
        "layer": item["layer"],
        "entity_type": item["entity_type"],
        "role": item["role"],
        "bbox": tuple(float(value) for value in bbox),
        "point_count": len(item["points"]),
    }


def _valid_polygon(points: list[Point]) -> Polygon:
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda geom: geom.area)
    if polygon.is_empty or polygon.area <= 0:
        raise ValueError("Failed to build a valid outer facade polygon")
    return polygon


def _inner_offset_polygon(outer_polygon: Polygon, offset: float) -> Polygon:
    inner = outer_polygon.buffer(-offset, join_style=2, resolution=16)
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda geom: geom.area)
    if inner.is_empty or inner.area <= 0:
        raise ValueError(f"Inward offset {offset} removed the facade polygon")
    if not inner.is_valid:
        inner = inner.buffer(0)
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda geom: geom.area)
    return inner


def _before_stats(dxf_path: Path, columns_path: Path, columns: ColumnData, facade: FacadeSamples) -> dict[str, Any]:
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_dxf": _file_fingerprint(dxf_path),
        "columns_json": _file_fingerprint(columns_path),
        "entity_counts": dict(facade.entity_counts.most_common()),
        "top_layer_type_counts": dict(facade.layer_counts.most_common(25)),
        "source_bbox": facade.source_bbox,
        "sampled_bbox": facade.sampled_bbox,
        "window_bbox": facade.window_bbox,
        "sample_count": len(facade.samples),
        "columns": {
            "count": len(columns.centers),
            "bbox": _bbox_for_points([point for bbox in columns.bboxes for point in [(bbox[0], bbox[1]), (bbox[2], bbox[3])]]),
        },
    }


def _after_stats(
    outer_polygon: Polygon,
    inner_polygon: Polygon,
    columns: ColumnData,
    inner_offset: float,
    outer_points: list[Point],
    inner_points: list[Point],
) -> dict[str, Any]:
    outer_contains = _count_covered_centers(outer_polygon, columns.centers)
    inner_contains = _count_covered_centers(inner_polygon, columns.centers)
    return {
        "inner_offset": inner_offset,
        "outer": {
            "area": float(outer_polygon.area),
            "bbox": tuple(float(value) for value in outer_polygon.bounds),
            "point_count": len(outer_points),
            "column_center_coverage": outer_contains / len(columns.centers),
            "column_centers_inside": outer_contains,
        },
        "inner": {
            "area": float(inner_polygon.area),
            "bbox": tuple(float(value) for value in inner_polygon.bounds),
            "point_count": len(inner_points),
            "column_center_coverage": inner_contains / len(columns.centers),
            "column_centers_inside": inner_contains,
        },
        "columns_count": len(columns.centers),
    }


def _automated_check(after_stats: dict[str, Any], min_column_coverage: float) -> dict[str, Any]:
    checks = [
        {
            "name": "outer_area_positive",
            "ok": after_stats["outer"]["area"] > 0,
            "value": after_stats["outer"]["area"],
        },
        {
            "name": "inner_area_positive",
            "ok": after_stats["inner"]["area"] > 0,
            "value": after_stats["inner"]["area"],
        },
        {
            "name": "inner_smaller_than_outer",
            "ok": after_stats["inner"]["area"] < after_stats["outer"]["area"],
            "value": after_stats["inner"]["area"] / after_stats["outer"]["area"],
        },
        {
            "name": "outer_covers_all_column_centers",
            "ok": after_stats["outer"]["column_centers_inside"] == after_stats["columns_count"],
            "value": after_stats["outer"]["column_center_coverage"],
        },
        {
            "name": "inner_column_center_coverage",
            "ok": after_stats["inner"]["column_center_coverage"] >= min_column_coverage,
            "value": after_stats["inner"]["column_center_coverage"],
            "minimum": min_column_coverage,
        },
    ]
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def _build_output_payload(
    dxf_path: Path,
    columns_path: Path,
    columns: ColumnData,
    outer_points: list[Point],
    inner_points: list[Point],
    after_stats: dict[str, Any],
    automated_check: dict[str, Any],
    top_profile_metadata: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    inner_bbox = tuple(float(value) for value in Polygon(inner_points).bounds)
    inner_area = float(Polygon(inner_points).area)
    outer_bbox = tuple(float(value) for value in Polygon(outer_points).bounds)
    outer_area = float(Polygon(outer_points).area)
    return {
        "source_file": dxf_path.name,
        "source_dxf": str(dxf_path),
        "columns_source": str(columns_path),
        "method": "column-constrained_facade_edge_profile_with_inward_buffer",
        "parameters": {
            "inner_offset": args.inner_offset,
            "subject_margin": args.subject_margin,
            "bin_width": args.bin_width,
            "sample_step": args.sample_step,
            "edge_quantile": args.edge_quantile,
            "top_quantile": args.top_quantile,
            "column_clearance": args.column_clearance,
        },
        "layers": [],
        "texts": [],
        "blocks": [],
        "axes": [],
        "columns": columns.payload.get("columns", []),
        "polylines": [
            {
                "layer": OUTER_LAYER,
                "entity_type": "DERIVED_FACADE_PROFILE",
                "closed": True,
                "points": outer_points,
                "bbox": outer_bbox,
                "area": outer_area,
            },
            {
                "layer": ENVELOPE_LAYER,
                "entity_type": "DERIVED_INNER_ENVELOPE",
                "closed": True,
                "points": inner_points,
                "bbox": inner_bbox,
                "area": inner_area,
            },
        ],
        "boundary_candidates": [
            {
                "boundary_id": "building_inner_envelope_00001",
                "source_polyline_index": 1,
                "layer": ENVELOPE_LAYER,
                "entity_type": "DERIVED_INNER_ENVELOPE",
                "polygon_cad": inner_points,
                "bbox_cad": inner_bbox,
                "area_cad": inner_area,
                "metadata": {
                    "boundary_source": "building_facade_outline_inner_envelope",
                    "outer_profile_layer": OUTER_LAYER,
                    "inner_offset": args.inner_offset,
                    "columns_count": len(columns.centers),
                    "outer_column_center_coverage": after_stats["outer"]["column_center_coverage"],
                    "inner_column_center_coverage": after_stats["inner"]["column_center_coverage"],
                },
            }
        ],
        "facade_outer_profile": {
            "polygon_cad": outer_points,
            "bbox_cad": outer_bbox,
            "area_cad": outer_area,
        },
        "top_profile_metadata": top_profile_metadata,
        "automated_check": automated_check,
        "issues": [],
    }


def _build_svg(
    facade: FacadeSamples,
    columns: ColumnData,
    outer_points: list[Point],
    inner_points: list[Point],
    render_sample_limit: int,
) -> str:
    render_samples = _downsample(facade.samples, limit=render_sample_limit)
    all_points = [(sample.x, sample.y) for sample in render_samples]
    all_points.extend(point for polygon in columns.polygons for point in polygon)
    all_points.extend(outer_points)
    all_points.extend(inner_points)
    bounds = _bbox_for_points(all_points)
    pad = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.025
    min_x, min_y, max_x, max_y = bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad
    width = max_x - min_x
    height = max_y - min_y
    stroke = max(width, height) / 900.0
    dots = "\n".join(
        f'<circle cx="{sample.x:.2f}" cy="{sample.y:.2f}" r="{stroke * 0.35:.2f}" fill="#94a3b8" fill-opacity="0.32"/>'
        for sample in render_samples
    )
    column_shapes = "\n".join(_svg_polygon(points, fill="#111827", stroke="#111827", stroke_width=stroke * 0.35, opacity=0.45) for points in columns.polygons)
    outer_shape = _svg_polygon(outer_points, fill="none", stroke="#2563eb", stroke_width=stroke * 1.4, opacity=0.9)
    inner_shape = _svg_polygon(inner_points, fill="#dc2626", stroke="#b91c1c", stroke_width=stroke * 1.7, opacity=0.22)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.3f} {-max_y:.3f} {width:.3f} {height:.3f}" width="1600" height="900">
  <rect x="{min_x:.3f}" y="{-max_y:.3f}" width="{width:.3f}" height="{height:.3f}" fill="#ffffff"/>
  <g transform="scale(1 -1)">
    {dots}
    {column_shapes}
    {outer_shape}
    {inner_shape}
  </g>
  <text x="{min_x + pad:.3f}" y="{-max_y + pad * 1.5:.3f}" font-size="{stroke * 6:.2f}" fill="#111827">blue: outer facade profile; red: inner envelope; black: columns; gray: sampled facade lines</text>
</svg>"""


def _build_comparison_svg_from_pngs(before_png: Path, after_png: Path) -> str:
    before_data = base64.b64encode(before_png.read_bytes()).decode("ascii")
    after_data = base64.b64encode(after_png.read_bytes()).decode("ascii")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="900" viewBox="0 0 1800 900">
  <rect width="1800" height="900" fill="#ffffff"/>
  <text x="30" y="38" font-size="28" fill="#111827">Before: facade samples + detected outer profile</text>
  <text x="930" y="38" font-size="28" fill="#111827">After: inward envelope for room recognition support</text>
  <image x="20" y="60" width="860" height="810" href="data:image/png;base64,{before_data}" preserveAspectRatio="xMidYMid meet"/>
  <image x="920" y="60" width="860" height="810" href="data:image/png;base64,{after_data}" preserveAspectRatio="xMidYMid meet"/>
</svg>"""


def _run_ai_validation(image_path: Path, after_stats: dict[str, Any], skip: bool) -> dict[str, Any]:
    if skip:
        return {"status": "skipped", "reason": "skip-ai-validation requested"}
    client = LocalAiClient(LocalAiConfig.from_env())
    prompt = (
        "请检查这张建筑外轮廓内包络线对比图。左图是外轮廓采样和蓝色外轮廓，右图额外显示红色内包络线。"
        "请判断红色内包络是否位于蓝色外轮廓内部、是否覆盖主要柱网范围、顶部曲线是否被大致保留。"
        "只输出JSON，字段为 ok(boolean), issues(array), summary(string)。"
        f"自动统计：{json.dumps(after_stats, ensure_ascii=False)}"
    )
    try:
        client.ensure_server()
        response = client.chat_with_image(prompt, image_path)
        content = _extract_ai_content(response)
        return {"status": "completed", "raw_response": response, "content": content}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}
    finally:
        client.shutdown_server()


def _write_json_review_html(json_path: Path, html_path: Path) -> None:
    args = argparse.Namespace(
        json=[str(json_path)],
        out=str(html_path),
        title="建筑外轮廓与内包络人工校核",
        include_polylines=True,
        include_texts=False,
        include_boundaries=True,
    )
    run_json_review_html(args)
    html = html_path.read_text(encoding="utf-8")
    html = html.replace(
        '<label><input type="checkbox" data-toggle-class="hide-boundaries"> 边界候选（需 --include-boundaries）</label>',
        '<label><input type="checkbox" data-toggle-class="hide-boundaries" checked> 边界候选（需 --include-boundaries）</label>',
    )
    html = html.replace(
        '<label><input type="checkbox" data-toggle-class="hide-polylines"> 多段线（需 --include-polylines）</label>',
        '<label><input type="checkbox" data-toggle-class="hide-polylines" checked> 多段线（需 --include-polylines）</label>',
    )
    html_path.write_text(html, encoding="utf-8")


def _build_report_html(
    status: str,
    before_stats: dict[str, Any],
    after_stats: dict[str, Any],
    automated_check: dict[str, Any],
    ai_validation: dict[str, Any],
) -> str:
    check_rows = "\n".join(
        f"<tr><td>{escape(check['name'])}</td><td>{'PASS' if check['ok'] else 'FAIL'}</td><td><code>{escape(json.dumps(check.get('value'), ensure_ascii=False))}</code></td></tr>"
        for check in automated_check["checks"]
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Building Facade Inner Envelope Audit</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; color: #111827; }}
    img {{ max-width: 100%; border: 1px solid #d1d5db; }}
    code, pre {{ background: #f3f4f6; padding: 2px 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; vertical-align: top; }}
  </style>
</head>
<body>
  <h1>Building Facade Inner Envelope Audit</h1>
  <p>Status: <strong>{escape(status)}</strong></p>
  <h2>Visual Check</h2>
  <p><img src="comparison.png" alt="before and after comparison"></p>
  <h2>Automated Checks</h2>
  <table><thead><tr><th>Check</th><th>Status</th><th>Value</th></tr></thead><tbody>{check_rows}</tbody></table>
  <h2>Before Stats</h2>
  <pre>{escape(json.dumps(before_stats, ensure_ascii=False, indent=2))}</pre>
  <h2>After Stats</h2>
  <pre>{escape(json.dumps(after_stats, ensure_ascii=False, indent=2))}</pre>
  <h2>Local AI Validation</h2>
  <pre>{escape(json.dumps(ai_validation, ensure_ascii=False, indent=2))}</pre>
</body>
</html>"""


def _update_manifest(step_dir: Path, status: str, artifact_path: Path, automated_check: dict[str, Any]) -> Path:
    manifest_path = step_dir.parent.parent / "manifest.json"
    step_number = _step_number(step_dir)
    manifest = {
        "current_step": step_number,
        "current_artifact": str(artifact_path),
        "steps": [
            {
                "step": step_number,
                "name": step_dir.name,
                "status": status,
                "artifact": str(artifact_path),
                "automated_check_ok": automated_check["ok"],
            }
        ],
        "accepted_rules": [],
        "rejected_rules": [],
        "rollback_points": [],
    }
    if status == "accepted":
        manifest["accepted_rules"].append(
            {
                "condition": "L2 facade-outline DXF contains noisy linework but useful facade extremes around the structural column grid.",
                "action": "Use structural columns to crop the subject area, derive a robust outer facade edge profile, then buffer inward.",
                "protection_checks": ["outer covers all column centers", "inner area is positive and smaller than outer", "inner keeps configured column-center coverage"],
                "risk": "sample-proven only for the current L2 facade-outline DXF",
            }
        )
        manifest["rollback_points"].append(str(artifact_path))
    else:
        manifest["rejected_rules"].append({"reason": "automated checks failed", "artifact": str(artifact_path)})
    _write_json(manifest_path, manifest)
    return manifest_path


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _step_number(step_dir: Path) -> int:
    match = re.match(r"^(\d+)_", step_dir.name)
    return int(match.group(1)) if match else 0


def _file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "name": path.name, "size_bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")}


def _sample_segment(start: Point, end: Point, sample_step: float) -> list[Point]:
    distance = math.dist(start, end)
    steps = max(1, int(math.ceil(distance / sample_step)))
    return [
        (float(start[0]) + (float(end[0]) - float(start[0])) * index / steps, float(start[1]) + (float(end[1]) - float(start[1])) * index / steps)
        for index in range(steps + 1)
    ]


def _smooth_profile(points: list[Point], radius: int) -> list[Point]:
    if radius <= 0 or len(points) < radius * 2 + 1:
        return points
    smoothed: list[Point] = []
    for index, (x, y) in enumerate(points):
        left = max(0, index - radius)
        right = min(len(points), index + radius + 1)
        window = sorted(point[1] for point in points[left:right])
        median = window[len(window) // 2]
        smoothed.append((x, max(y * 0.35 + median * 0.65, y - 2000.0)))
    return smoothed


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("Cannot calculate quantile for empty values")
    bounded = min(1.0, max(0.0, quantile))
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * bounded))
    return float(ordered[index])


def _polygon_points(polygon: Polygon) -> list[Point]:
    return [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]]


def _count_covered_centers(polygon: Polygon, centers: list[Point]) -> int:
    return sum(1 for center in centers if polygon.covers(ShapelyPoint(center)))


def _bbox_for_points(points: list[Point]) -> BBox:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_union(bboxes: list[BBox]) -> BBox | None:
    if not bboxes:
        return None
    return (min(bbox[0] for bbox in bboxes), min(bbox[1] for bbox in bboxes), max(bbox[2] for bbox in bboxes), max(bbox[3] for bbox in bboxes))


def _bbox_intersects(first: BBox, second: BBox) -> bool:
    return not (first[2] < second[0] or second[2] < first[0] or first[3] < second[1] or second[3] < first[1])


def _point(value: Any) -> Point | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


def _bbox(value: Any) -> BBox | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except (TypeError, ValueError):
        return None


def _dedupe_adjacent_points(points: list[Point], tolerance: float = 1e-6) -> list[Point]:
    deduped: list[Point] = []
    for point in points:
        if deduped and math.dist(deduped[-1], point) <= tolerance:
            continue
        deduped.append(point)
    if len(deduped) > 1 and math.dist(deduped[0], deduped[-1]) <= tolerance:
        deduped.pop()
    return deduped


def _downsample(samples: list[LineSample], limit: int) -> list[LineSample]:
    if len(samples) <= limit:
        return samples
    step = len(samples) / limit
    return [samples[int(index * step)] for index in range(limit)]


def _svg_polygon(points: list[Point], fill: str, stroke: str, stroke_width: float, opacity: float) -> str:
    if len(points) < 3:
        return ""
    path = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in points) + " Z"
    return f'<path d="{path}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width:.2f}" opacity="{opacity:.3f}"/>'


def _render_svg_png(svg: str, output_path: Path) -> None:
    doc = fitz.open("svg", svg.encode("utf-8"))
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    output_path.write_bytes(pix.tobytes("png"))


def _extract_ai_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
