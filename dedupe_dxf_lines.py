"""Analyze and optionally remove duplicate line-like entities from a DXF.

This root-level entrypoint is intended for exploded DXF files where repeated
EXPLODE passes may leave many duplicate LINE/LWPOLYLINE/POLYLINE/ARC entities.
By default it only writes/prints statistics. Pass --out to save a cleaned DXF.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import ezdxf
from ezdxf.document import Drawing as DxfDrawing


LINEAR_ENTITY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}
DEFAULT_EXACT_TOLERANCE = 1e-9
DEFAULT_NEAR_TOLERANCE = 1.0

Point = tuple[float, float]
Signature = tuple[Any, ...]


@dataclass
class EntityRecord:
    entity: object
    layer: str
    entity_type: str
    exact_signature: Signature
    near_signature: Signature


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze duplicate LINE/LWPOLYLINE/POLYLINE/ARC entities in an exploded DXF. "
            "Without --out this is statistics-only; with --out it writes a cleaned DXF."
        )
    )
    parser.add_argument("--input", required=True, help="Input DXF file.")
    parser.add_argument("--out", help="Optional output DXF path. If omitted, no DXF is modified or written.")
    parser.add_argument("--report-out", help="Optional JSON report path.")
    parser.add_argument(
        "--dedupe-mode",
        choices=["exact", "near"],
        default="exact",
        help="Duplicate signature used when --out is provided. Default: exact.",
    )
    parser.add_argument(
        "--exact-tolerance",
        type=float,
        default=DEFAULT_EXACT_TOLERANCE,
        help="Coordinate rounding tolerance for exact duplicate grouping. Default: 1e-9.",
    )
    parser.add_argument(
        "--near-tolerance",
        type=float,
        default=DEFAULT_NEAR_TOLERANCE,
        help="Coordinate grid size for near duplicate grouping, in CAD units. Default: 1.0.",
    )
    parser.add_argument(
        "--signature-scope",
        choices=["layer", "geometry"],
        default="layer",
        help=(
            "Use layer-aware signatures or geometry-only signatures. "
            "geometry ignores layer/color and keeps the first matching entity. Default: layer."
        ),
    )
    parser.add_argument(
        "--visible-only",
        action="store_true",
        help="Only analyze/delete entities on visible, unfrozen layers and with no invisible flag.",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=100000,
        help="Print progress every N modelspace entities. Use 0 to disable. Default: 100000.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.out) if args.out else None
    report_path = Path(args.report_out) if args.report_out else None

    doc = _load_dxf(input_path)
    records, skipped = collect_line_like_records(
        doc,
        visible_only=bool(args.visible_only),
        exact_tolerance=float(args.exact_tolerance),
        near_tolerance=float(args.near_tolerance),
        signature_scope=str(args.signature_scope),
        progress_interval=max(0, int(args.progress_interval)),
    )
    report = build_duplicate_report(
        records,
        input_path=input_path,
        output_path=output_path,
        visible_only=bool(args.visible_only),
        exact_tolerance=float(args.exact_tolerance),
        near_tolerance=float(args.near_tolerance),
        signature_scope=str(args.signature_scope),
        skipped_entity_count=skipped,
    )

    if output_path is not None:
        removed = remove_duplicates(doc, records, mode=str(args.dedupe_mode))
        report["dedupe_mode"] = str(args.dedupe_mode)
        report["totals"]["removed_count"] = removed["total"]
        for layer, count in removed["layers"].items():
            report["layers"].setdefault(layer, _empty_layer_stats())["removed_count"] = count
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(output_path)
    else:
        report["dedupe_mode"] = "none"

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


def collect_line_like_records(
    doc: DxfDrawing,
    visible_only: bool = False,
    exact_tolerance: float = DEFAULT_EXACT_TOLERANCE,
    near_tolerance: float = DEFAULT_NEAR_TOLERANCE,
    signature_scope: str = "layer",
    progress_interval: int = 0,
) -> tuple[list[EntityRecord], int]:
    records: list[EntityRecord] = []
    skipped = 0
    for index, entity in enumerate(doc.modelspace(), start=1):
        if progress_interval and index % progress_interval == 0:
            print(f"scanned {index} modelspace entities, collected {len(records)} line-like entities", file=sys.stderr)
        entity_type = entity.dxftype()
        if entity_type not in LINEAR_ENTITY_TYPES:
            continue
        if visible_only and not _is_entity_visible(doc, entity):
            skipped += 1
            continue
        try:
            layer = str(getattr(entity.dxf, "layer", "0"))
            exact_signature = entity_signature(entity, tolerance=exact_tolerance, scope=signature_scope)
            near_signature = entity_signature(entity, tolerance=near_tolerance, scope=signature_scope)
        except Exception as exc:
            skipped += 1
            print(f"skipped {entity_type} entity: {exc}", file=sys.stderr)
            continue
        records.append(
            EntityRecord(
                entity=entity,
                layer=layer,
                entity_type=entity_type,
                exact_signature=exact_signature,
                near_signature=near_signature,
            )
        )
    return records, skipped


def build_duplicate_report(
    records: list[EntityRecord],
    input_path: Path,
    output_path: Path | None,
    visible_only: bool,
    exact_tolerance: float,
    near_tolerance: float,
    signature_scope: str,
    skipped_entity_count: int,
) -> dict[str, Any]:
    layers: dict[str, dict[str, Any]] = defaultdict(_empty_layer_stats)
    totals = _empty_layer_stats()
    exact_seen: Counter[Signature] = Counter()
    near_seen: Counter[Signature] = Counter()
    exact_seen_by_layer: dict[str, Counter[Signature]] = defaultdict(Counter)
    near_seen_by_layer: dict[str, Counter[Signature]] = defaultdict(Counter)

    for record in records:
        layer_stats = layers[record.layer]
        _add_entity_count(layer_stats, record.entity_type)
        _add_entity_count(totals, record.entity_type)
        exact_seen[record.exact_signature] += 1
        near_seen[record.near_signature] += 1
        exact_seen_by_layer[record.layer][record.exact_signature] += 1
        near_seen_by_layer[record.layer][record.near_signature] += 1

    totals["exact_duplicate_count"] = _duplicate_count(exact_seen)
    totals["near_duplicate_count"] = _duplicate_count(near_seen)
    totals["exact_duplicate_group_count"] = _duplicate_group_count(exact_seen)
    totals["near_duplicate_group_count"] = _duplicate_group_count(near_seen)
    totals["skipped_entity_count"] = skipped_entity_count

    for layer, stats in layers.items():
        stats["exact_duplicate_count"] = _duplicate_count(exact_seen_by_layer[layer])
        stats["near_duplicate_count"] = _duplicate_count(near_seen_by_layer[layer])
        stats["exact_duplicate_group_count"] = _duplicate_group_count(exact_seen_by_layer[layer])
        stats["near_duplicate_group_count"] = _duplicate_group_count(near_seen_by_layer[layer])

    return {
        "input": str(input_path),
        "output": str(output_path) if output_path is not None else None,
        "visible_only": visible_only,
        "exact_tolerance": exact_tolerance,
        "near_tolerance": near_tolerance,
        "signature_scope": signature_scope,
        "entity_types": sorted(LINEAR_ENTITY_TYPES),
        "totals": totals,
        "layers": dict(sorted(layers.items(), key=lambda item: item[0])),
    }


def remove_duplicates(doc: DxfDrawing, records: list[EntityRecord], mode: str = "exact") -> dict[str, Any]:
    if mode not in {"exact", "near"}:
        raise ValueError(f"Unsupported dedupe mode: {mode}")
    seen: set[Signature] = set()
    removed_by_layer: Counter[str] = Counter()
    for record in records:
        signature = record.exact_signature if mode == "exact" else record.near_signature
        if signature not in seen:
            seen.add(signature)
            continue
        record.entity.destroy()
        removed_by_layer[record.layer] += 1
    doc.modelspace().entity_space.purge()
    return {"total": sum(removed_by_layer.values()), "layers": dict(sorted(removed_by_layer.items()))}


def entity_signature(entity: object, tolerance: float, scope: str = "layer") -> Signature:
    entity_type = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", "0"))
    prefix: tuple[Any, ...]
    if scope == "layer":
        prefix = (layer,)
    elif scope == "geometry":
        prefix = ()
    else:
        raise ValueError(f"Unsupported signature scope: {scope}")
    if entity_type == "LINE":
        start = _point2(entity.dxf.start)
        end = _point2(entity.dxf.end)
        first, second = sorted((_quantize_point(start, tolerance), _quantize_point(end, tolerance)))
        return (*prefix, "PATH", False, (first, second))
    if entity_type == "ARC":
        center = _quantize_point(_point2(entity.dxf.center), tolerance)
        radius = _quantize_number(float(entity.dxf.radius), tolerance)
        start_angle = _quantize_angle(float(entity.dxf.start_angle), tolerance)
        end_angle = _quantize_angle(float(entity.dxf.end_angle), tolerance)
        return (*prefix, "ARC", center, radius, start_angle, end_angle)
    points = _polyline_points(entity)
    closed = _is_polyline_closed(entity, points, tolerance)
    normalized_points = _normalize_polyline_points(points, closed=closed, tolerance=tolerance)
    return (*prefix, "PATH", closed, tuple(normalized_points))


def _normalize_polyline_points(points: list[Point], closed: bool, tolerance: float) -> list[tuple[int, int]]:
    quantized = [_quantize_point(point, tolerance) for point in points]
    if closed and len(quantized) > 1 and quantized[0] == quantized[-1]:
        quantized = quantized[:-1]
    if not quantized:
        return quantized
    if closed:
        rotations = [quantized[index:] + quantized[:index] for index in range(len(quantized))]
        reversed_points = list(reversed(quantized))
        rotations.extend(reversed_points[index:] + reversed_points[:index] for index in range(len(reversed_points)))
        return min(rotations)
    reversed_quantized = list(reversed(quantized))
    return min(quantized, reversed_quantized)


def _polyline_points(entity: object) -> list[Point]:
    if entity.dxftype() == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y in entity.get_points("xy")]
    points: list[Point] = []
    for vertex in getattr(entity, "vertices", []):
        location = vertex.dxf.location
        points.append(_point2(location))
    return points


def _is_polyline_closed(entity: object, points: list[Point], tolerance: float) -> bool:
    if entity.dxftype() == "LWPOLYLINE":
        return bool(getattr(entity, "closed", False))
    if bool(getattr(entity, "is_closed", False)):
        return True
    if len(points) < 2:
        return False
    return _quantize_point(points[0], tolerance) == _quantize_point(points[-1], tolerance)


def _is_entity_visible(doc: DxfDrawing, entity: object) -> bool:
    if bool(getattr(entity.dxf, "invisible", 0) or 0):
        return False
    layer_name = str(getattr(entity.dxf, "layer", "0"))
    try:
        layer = doc.layers.get(layer_name)
    except Exception:
        return True
    return not bool(layer.is_off() or layer.is_frozen())


def _load_dxf(path: Path) -> DxfDrawing:
    if not path.exists():
        raise FileNotFoundError(f"DXF file not found: {path}")
    if path.suffix.lower() != ".dxf":
        raise ValueError(f"Only DXF files are supported: {path}")
    return ezdxf.readfile(path)


def _empty_layer_stats() -> dict[str, Any]:
    return {
        "entity_count": 0,
        "line_count": 0,
        "lwpolyline_count": 0,
        "polyline_count": 0,
        "arc_count": 0,
        "exact_duplicate_count": 0,
        "near_duplicate_count": 0,
        "exact_duplicate_group_count": 0,
        "near_duplicate_group_count": 0,
        "removed_count": 0,
    }


def _add_entity_count(stats: dict[str, Any], entity_type: str) -> None:
    stats["entity_count"] += 1
    if entity_type == "LINE":
        stats["line_count"] += 1
    elif entity_type == "LWPOLYLINE":
        stats["lwpolyline_count"] += 1
    elif entity_type == "POLYLINE":
        stats["polyline_count"] += 1
    elif entity_type == "ARC":
        stats["arc_count"] += 1


def _duplicate_count(counter: Counter[Signature]) -> int:
    return sum(count - 1 for count in counter.values() if count > 1)


def _duplicate_group_count(counter: Counter[Signature]) -> int:
    return sum(1 for count in counter.values() if count > 1)


def _point2(point: Iterable[float]) -> Point:
    values = tuple(point)
    return (float(values[0]), float(values[1]))


def _quantize_point(point: Point, tolerance: float) -> tuple[int, int]:
    return (_quantize_number(point[0], tolerance), _quantize_number(point[1], tolerance))


def _quantize_angle(angle: float, tolerance: float) -> int:
    normalized = angle % 360.0
    return _quantize_number(normalized, tolerance)


def _quantize_number(value: float, tolerance: float) -> int:
    if tolerance <= 0:
        raise ValueError("tolerance must be greater than 0")
    if not math.isfinite(value):
        raise ValueError(f"non-finite coordinate: {value}")
    return int(round(value / tolerance))


if __name__ == "__main__":
    raise SystemExit(main())
