from __future__ import annotations

from math import cos, hypot, pi, radians, sin

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.entity_filter import iter_modelspace_entities
from room_extractor.geometry import calculate_bbox
from room_extractor.models.drawing import CadAxisEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.text_normalizer import recover_gbk_mojibake
from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)
Point = tuple[float, float]

AXIS_LAYER_MARKERS = ("AXIS", "GRID", "轴网", "轴线")
AXIS_ENTITY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC"}


def extract_axes(
    doc: DxfDrawing,
    axis_layers: list[str] | None = None,
    visible_only: bool = False,
) -> tuple[list[CadAxisEntity], list[Issue]]:
    """Extract line-like entities from DXF axis layers."""
    axes: list[CadAxisEntity] = []
    issues: list[Issue] = []
    for entity in iter_modelspace_entities(doc, visible_only=visible_only):
        if entity.dxftype() not in AXIS_ENTITY_TYPES:
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        if not is_axis_layer(layer, axis_layers=axis_layers):
            continue
        try:
            points = _extract_axis_points(entity)
            axes.append(
                CadAxisEntity(
                    layer=layer,
                    entity_type=entity.dxftype(),
                    points=points,
                    bbox=calculate_bbox(points),
                    length=_polyline_length(points),
                )
            )
        except Exception as exc:
            message = f"Failed to extract {entity.dxftype()} axis entity: {exc}"
            logger.warning(message)
            issues.append(Issue(issue_code="AXIS_EXTRACT_FAILED", field="axes", message=message))
    return _merge_connected_arc_axes(axes), issues


def is_axis_layer(layer: str, axis_layers: list[str] | None = None) -> bool:
    """Return True when a CAD layer name looks like an axis/grid layer."""
    if axis_layers:
        return _normalized_layer(layer) in {_normalized_layer(item) for item in axis_layers}
    normalized = layer.upper()
    recovered = recover_gbk_mojibake(layer).upper()
    return any(marker in normalized or marker in recovered for marker in AXIS_LAYER_MARKERS)


def _normalized_layer(layer: str) -> str:
    return recover_gbk_mojibake(layer).upper()


def _extract_axis_points(entity: object) -> list[Point]:
    entity_type = entity.dxftype()
    if entity_type == "LINE":
        start = getattr(entity.dxf, "start")
        end = getattr(entity.dxf, "end")
        return [(float(start[0]), float(start[1])), (float(end[0]), float(end[1]))]
    if entity_type == "ARC":
        return _arc_points(entity)
    if entity_type == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y in entity.get_points("xy")]
    points: list[Point] = []
    for vertex in getattr(entity, "vertices", []):
        location = vertex.dxf.location
        points.append((float(location[0]), float(location[1])))
    return points


def _arc_points(entity: object, max_segment_degrees: float = 3.0) -> list[Point]:
    center = getattr(entity.dxf, "center")
    radius = float(getattr(entity.dxf, "radius"))
    start_angle = float(getattr(entity.dxf, "start_angle"))
    end_angle = float(getattr(entity.dxf, "end_angle"))
    sweep = (end_angle - start_angle) % 360.0
    if sweep == 0.0:
        sweep = 360.0
    segment_count = max(8, int(sweep / max_segment_degrees) + 1)
    points: list[Point] = []
    for index in range(segment_count + 1):
        angle = radians(start_angle + sweep * index / segment_count)
        points.append((float(center[0]) + radius * cos(angle), float(center[1]) + radius * sin(angle)))
    return points


def _polyline_length(points: list[Point]) -> float | None:
    if len(points) < 2:
        return None
    return float(sum(hypot(end[0] - start[0], end[1] - start[1]) for start, end in zip(points, points[1:])))


def _merge_connected_arc_axes(axes: list[CadAxisEntity], tolerance: float = 1.0) -> list[CadAxisEntity]:
    merged: list[CadAxisEntity] = []
    pending_arcs = [axis for axis in axes if axis.entity_type == "ARC" and len(axis.points) >= 2]
    for axis in axes:
        if axis.entity_type != "ARC":
            merged.append(axis)

    while pending_arcs:
        current = pending_arcs.pop(0)
        changed = True
        while changed:
            changed = False
            for index, candidate in enumerate(pending_arcs):
                joined_points = _join_connected_points(current.points, candidate.points, tolerance=tolerance)
                if joined_points is None or candidate.layer != current.layer:
                    continue
                current = CadAxisEntity(
                    layer=current.layer,
                    entity_type="ARC",
                    points=joined_points,
                    bbox=calculate_bbox(joined_points),
                    length=_polyline_length(joined_points),
                )
                pending_arcs.pop(index)
                changed = True
                break
        merged.append(current)
    return merged


def _join_connected_points(first: list[Point], second: list[Point], tolerance: float) -> list[Point] | None:
    if _point_distance(first[-1], second[0]) <= tolerance:
        return [*first, *second[1:]]
    if _point_distance(first[0], second[-1]) <= tolerance:
        return [*second, *first[1:]]
    if _point_distance(first[0], second[0]) <= tolerance:
        return [*list(reversed(second)), *first[1:]]
    if _point_distance(first[-1], second[-1]) <= tolerance:
        return [*first, *list(reversed(second))[1:]]
    return None


def _point_distance(first: Point, second: Point) -> float:
    return float(hypot(first[0] - second[0], first[1] - second[1]))
