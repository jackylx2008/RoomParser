from __future__ import annotations

from math import cos, radians, sin

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.entity_filter import iter_modelspace_entities
from room_extractor.geometry import calculate_bbox, calculate_polygon_area
from room_extractor.models.drawing import CadPolylineEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)
Point = tuple[float, float]


def extract_polylines(doc: DxfDrawing, visible_only: bool = False) -> tuple[list[CadPolylineEntity], list[Issue]]:
    """Extract linear CAD entities from modelspace."""
    polylines: list[CadPolylineEntity] = []
    issues: list[Issue] = []
    for entity in iter_modelspace_entities(doc, visible_only=visible_only):
        if entity.dxftype() not in {"LWPOLYLINE", "POLYLINE", "LINE", "ARC"}:
            continue
        try:
            points = _extract_points(entity)
            closed = _is_entity_closed(entity)
            polylines.append(
                CadPolylineEntity(
                    layer=str(getattr(entity.dxf, "layer", "0")),
                    entity_type=entity.dxftype(),
                    closed=closed,
                    points=points,
                    bbox=calculate_bbox(points),
                    area=calculate_polygon_area(points) if closed else None,
                )
            )
        except Exception as exc:
            message = f"Failed to extract {entity.dxftype()} entity: {exc}"
            logger.warning(message)
            issues.append(Issue(issue_code="POLYLINE_EXTRACT_FAILED", field="polylines", message=message))
    return polylines, issues


def _extract_points(entity: object) -> list[Point]:
    if entity.dxftype() == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y in entity.get_points("xy")]
    if entity.dxftype() == "LINE":
        start = entity.dxf.start
        end = entity.dxf.end
        return [(float(start[0]), float(start[1])), (float(end[0]), float(end[1]))]
    if entity.dxftype() == "ARC":
        return _sample_arc_points(entity)
    points: list[Point] = []
    for vertex in getattr(entity, "vertices", []):
        location = vertex.dxf.location
        points.append((float(location[0]), float(location[1])))
    return points


def _is_entity_closed(entity: object) -> bool:
    if entity.dxftype() == "LWPOLYLINE":
        return bool(getattr(entity, "closed", False))
    if entity.dxftype() in {"LINE", "ARC"}:
        return False
    return bool(getattr(entity, "is_closed", False))


def _sample_arc_points(entity: object, max_step_degrees: float = 10.0) -> list[Point]:
    center = entity.dxf.center
    radius = float(entity.dxf.radius)
    start_angle = float(entity.dxf.start_angle)
    end_angle = float(entity.dxf.end_angle)
    sweep = (end_angle - start_angle) % 360.0
    if sweep == 0:
        sweep = 360.0
    segment_count = max(2, int(sweep / max_step_degrees) + 1)
    points: list[Point] = []
    for index in range(segment_count + 1):
        angle = radians(start_angle + sweep * index / segment_count)
        points.append((float(center[0]) + radius * cos(angle), float(center[1]) + radius * sin(angle)))
    return points
