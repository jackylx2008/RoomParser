from __future__ import annotations

from math import cos, radians, sin

from ezdxf.document import Drawing as DxfDrawing
from shapely.geometry import Polygon

from room_extractor.config.column_rules import ColumnLayerRules
from room_extractor.geometry import calculate_bbox, calculate_polygon_area
from room_extractor.models.drawing import CadColumnEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.logger import get_logger
from room_extractor.utils.text_normalizer import recover_gbk_mojibake

logger = get_logger(__name__)
Point = tuple[float, float]

COLUMN_LAYER_MARKERS = ("A-STR-COLM", "S-COL", "S-COLUMN", "COLUMN", "COLM", "结构柱", "柱")
COLUMN_ENTITY_TYPES = {"HATCH", "LWPOLYLINE", "POLYLINE", "INSERT"}


def extract_columns(
    doc: DxfDrawing,
    column_rules: ColumnLayerRules | None = None,
) -> tuple[list[CadColumnEntity], list[Issue]]:
    """Extract structural columns from configured DXF layers."""
    columns: list[CadColumnEntity] = []
    issues: list[Issue] = []
    entity_types = set(column_rules.column_entity_types if column_rules is not None and column_rules.column_entity_types else COLUMN_ENTITY_TYPES)
    for entity in _iter_column_source_entities(doc, column_rules):
        if entity.dxftype() not in entity_types:
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        if not is_column_layer(layer, column_rules=column_rules):
            continue
        if column_rules is not None and not _matches_entity_rules(entity, column_rules):
            continue
        try:
            for column in _extract_entity_columns(entity, next_index=len(columns) + 1):
                if _matches_geometry_rules(column, column_rules):
                    columns.append(column)
        except Exception as exc:
            message = f"Failed to extract {entity.dxftype()} column entity: {exc}"
            logger.warning(message)
            issues.append(Issue(issue_code="COLUMN_EXTRACT_FAILED", field="columns", message=message))
    return columns, issues


def _iter_column_source_entities(doc: DxfDrawing, column_rules: ColumnLayerRules | None) -> list[object]:
    entities = list(doc.modelspace())
    if column_rules is not None and not column_rules.expand_insert_virtual_entities:
        return entities
    for insert in doc.modelspace().query("INSERT"):
        entities.extend(_safe_virtual_entities(insert))
    return entities


def _safe_virtual_entities(entity: object, max_depth: int = 4) -> list[object]:
    if max_depth <= 0 or not hasattr(entity, "virtual_entities"):
        return []
    virtual_entities: list[object] = []
    try:
        children = list(entity.virtual_entities())
    except Exception as exc:
        logger.warning("Failed to expand INSERT virtual entities: %s", exc)
        return []
    for child in children:
        virtual_entities.append(child)
        if child.dxftype() == "INSERT":
            virtual_entities.extend(_safe_virtual_entities(child, max_depth=max_depth - 1))
    return virtual_entities


def is_column_layer(layer: str, column_rules: ColumnLayerRules | None = None) -> bool:
    """Return True when a CAD layer name is configured or looks like a structural column layer."""
    layer_values = list(column_rules.column_layers if column_rules is not None else [])
    block_layer_values = list(column_rules.column_block_layers if column_rules is not None else [])
    if layer_values or block_layer_values:
        return any(_matches_layer_rule(layer, rule) for rule in [*layer_values, *block_layer_values])
    return any(marker in value for value in _layer_values(layer) for marker in COLUMN_LAYER_MARKERS)


def _extract_entity_columns(entity: object, next_index: int) -> list[CadColumnEntity]:
    entity_type = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", "0"))
    if entity_type == "HATCH":
        return _extract_hatch_columns(entity, layer=layer, next_index=next_index)
    if entity_type in {"LWPOLYLINE", "POLYLINE"}:
        return [_column_from_polygon(_extract_polyline_points(entity), layer, entity_type, "polyline", next_index)]
    return [_column_from_insert(entity, layer=layer, next_index=next_index)]


def _extract_hatch_columns(entity: object, layer: str, next_index: int) -> list[CadColumnEntity]:
    path_candidates: list[list[Point]] = []
    for path in getattr(entity, "paths", []):
        points = _points_from_hatch_path(path)
        if len(points) < 3:
            continue
        path_candidates.append(points)
    if not path_candidates:
        return []
    points = max(path_candidates, key=lambda candidate: _polygon_area(candidate) or 0.0)
    return [_column_from_polygon(points, layer, "HATCH", "hatch_boundary", next_index)]


def _points_from_hatch_path(path: object) -> list[Point]:
    if hasattr(path, "vertices"):
        return [_xy(vertex) for vertex in getattr(path, "vertices", [])]
    points: list[Point] = []
    for edge in getattr(path, "edges", []):
        edge_points = _points_from_hatch_edge(edge)
        if not edge_points:
            continue
        if points and _same_point(points[-1], edge_points[0]):
            points.extend(edge_points[1:])
        else:
            points.extend(edge_points)
    return points


def _points_from_hatch_edge(edge: object) -> list[Point]:
    edge_type = type(edge).__name__
    if edge_type == "LineEdge":
        return [_xy(edge.start), _xy(edge.end)]
    if edge_type == "ArcEdge":
        return _arc_edge_points(edge)
    return []


def _arc_edge_points(edge: object, max_segment_degrees: float = 5.0) -> list[Point]:
    center = edge.center
    radius = float(edge.radius)
    start_angle = float(edge.start_angle)
    end_angle = float(edge.end_angle)
    ccw = bool(getattr(edge, "ccw", True))
    sweep = (end_angle - start_angle) % 360.0 if ccw else -((start_angle - end_angle) % 360.0)
    if sweep == 0.0:
        sweep = 360.0 if ccw else -360.0
    segment_count = max(6, int(abs(sweep) / max_segment_degrees) + 1)
    points: list[Point] = []
    for index in range(segment_count + 1):
        angle = radians(start_angle + sweep * index / segment_count)
        points.append((float(center[0]) + radius * cos(angle), float(center[1]) + radius * sin(angle)))
    return points


def _extract_polyline_points(entity: object) -> list[Point]:
    if entity.dxftype() == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y in entity.get_points("xy")]
    points: list[Point] = []
    for vertex in getattr(entity, "vertices", []):
        location = vertex.dxf.location
        points.append((float(location[0]), float(location[1])))
    return points


def _column_from_polygon(points: list[Point], layer: str, entity_type: str, source: str, index: int) -> CadColumnEntity:
    bbox = calculate_bbox(points)
    width = (bbox[2] - bbox[0]) if bbox is not None else None
    height = (bbox[3] - bbox[1]) if bbox is not None else None
    center = _polygon_center(points, bbox)
    return CadColumnEntity(
        column_id=f"column_{index:05d}",
        layer=layer,
        entity_type=entity_type,
        source=source,
        polygon=points,
        bbox=bbox,
        center=center,
        area=_polygon_area(points),
        width=width,
        height=height,
    )


def _column_from_insert(entity: object, layer: str, next_index: int) -> CadColumnEntity:
    insert = entity.dxf.insert
    attributes = {str(attrib.dxf.tag): str(attrib.dxf.text) for attrib in getattr(entity, "attribs", [])}
    center = (float(insert[0]), float(insert[1]))
    return CadColumnEntity(
        column_id=f"column_{next_index:05d}",
        layer=layer,
        entity_type="INSERT",
        source="block_insert",
        center=center,
        block_name=str(entity.dxf.name),
        attributes=attributes,
    )


def _matches_entity_rules(entity: object, column_rules: ColumnLayerRules) -> bool:
    if column_rules.color_indices:
        color = getattr(entity.dxf, "color", None)
        if color not in set(column_rules.color_indices):
            return False
    if entity.dxftype() == "HATCH":
        if column_rules.hatch_patterns:
            pattern_name = str(getattr(entity.dxf, "pattern_name", "")).upper()
            if pattern_name not in set(column_rules.hatch_patterns):
                return False
        if column_rules.solid_fill is not None:
            solid_fill = bool(getattr(entity.dxf, "solid_fill", False))
            if solid_fill != column_rules.solid_fill:
                return False
    return True


def _matches_geometry_rules(column: CadColumnEntity, column_rules: ColumnLayerRules | None) -> bool:
    if column_rules is None:
        return True
    if column.area is not None:
        if column_rules.min_area is not None and column.area < column_rules.min_area:
            return False
        if column_rules.max_area is not None and column.area > column_rules.max_area:
            return False
    if column.width is not None and column_rules.max_width is not None and column.width > column_rules.max_width:
        return False
    if column.height is not None and column_rules.max_height is not None and column.height > column_rules.max_height:
        return False
    return True


def _polygon_center(points: list[Point], bbox: tuple[float, float, float, float] | None) -> Point | None:
    if len(points) >= 3:
        polygon = Polygon(points)
        if not polygon.is_empty and polygon.is_valid:
            centroid = polygon.centroid
            return (float(centroid.x), float(centroid.y))
    if bbox is None:
        return None
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _polygon_area(points: list[Point]) -> float | None:
    area = calculate_polygon_area(points)
    if area is not None:
        return area
    if len(points) < 3:
        return None
    pairs = list(zip(points, [*points[1:], points[0]]))
    shoelace = sum(start[0] * end[1] - end[0] * start[1] for start, end in pairs) / 2.0
    return abs(float(shoelace))


def _matches_layer_rule(layer: str, rule: str) -> bool:
    for normalized in _layer_values(layer):
        for normalized_rule in _layer_values(rule):
            if not normalized_rule:
                continue
            if (
                normalized == normalized_rule
                or normalized.endswith(f"${normalized_rule}")
                or normalized.endswith(normalized_rule)
            ):
                return True
    return False


def _layer_values(layer: str) -> set[str]:
    return {str(layer).upper(), recover_gbk_mojibake(str(layer)).upper()}


def _xy(value: object) -> Point:
    return (float(value[0]), float(value[1]))


def _same_point(first: Point, second: Point, tolerance: float = 1e-6) -> bool:
    return abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance
