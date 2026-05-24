from __future__ import annotations

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.entity_filter import iter_modelspace_entities
from room_extractor.geometry import calculate_bbox, calculate_polygon_area
from room_extractor.models.drawing import CadPolylineEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)
Point = tuple[float, float]


def extract_polylines(doc: DxfDrawing, visible_only: bool = False) -> tuple[list[CadPolylineEntity], list[Issue]]:
    """Extract LWPOLYLINE and POLYLINE entities from modelspace."""
    polylines: list[CadPolylineEntity] = []
    issues: list[Issue] = []
    for entity in iter_modelspace_entities(doc, visible_only=visible_only):
        if entity.dxftype() not in {"LWPOLYLINE", "POLYLINE"}:
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
    points: list[Point] = []
    for vertex in getattr(entity, "vertices", []):
        location = vertex.dxf.location
        points.append((float(location[0]), float(location[1])))
    return points


def _is_entity_closed(entity: object) -> bool:
    if entity.dxftype() == "LWPOLYLINE":
        return bool(getattr(entity, "closed", False))
    return bool(getattr(entity, "is_closed", False))
