from __future__ import annotations

from collections import defaultdict
from fnmatch import fnmatchcase

from shapely import set_precision
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import polygonize, unary_union

from room_extractor.geometry import calculate_bbox
from room_extractor.models.drawing import CadColumnEntity, CadRawExtraction, CadPolylineEntity
from room_extractor.models.room_candidate import RoomBoundaryCandidate
from room_extractor.utils.text_normalizer import normalize_cad_text
from room_extractor.utils.text_normalizer import recover_gbk_mojibake


DEFAULT_MIN_BOUNDARY_AREA = 1_000_000.0
DEFAULT_MAX_BOUNDARY_AREA = 2_000_000_000.0
PREFERRED_BOUNDARY_LAYER_KEYWORDS = (
    "A-AREA-BNDY",
    "ROOM-BOUNDARY",
    "AREA-LINE",
    "A-SPACE",
    "面积线",
    "房间边界",
)


def build_room_boundary_candidates(
    cad_raw: CadRawExtraction,
    min_area: float = DEFAULT_MIN_BOUNDARY_AREA,
    max_area: float = DEFAULT_MAX_BOUNDARY_AREA,
    boundary_layers: list[str] | None = None,
    columns: list[CadColumnEntity] | None = None,
) -> list[RoomBoundaryCandidate]:
    """Extract filtered closed boundary candidates from cad_raw."""
    candidates: list[RoomBoundaryCandidate] = []
    signatures: set[tuple[float, float, float, float, float]] = set()
    column_shapes = _column_shapes(columns or [])
    for index, polyline in enumerate(cad_raw.polylines):
        if not _is_usable_boundary(polyline, min_area=min_area, max_area=max_area):
            continue
        if boundary_layers and not _matches_any_layer_rule(polyline.layer, boundary_layers):
            continue
        if _is_column_body_candidate(polyline.points, polyline.bbox, float(polyline.area), column_shapes):
            continue
        signature = _boundary_signature(polyline.bbox, float(polyline.area))
        signatures.add(signature)
        candidate_id = f"boundary_{len(candidates) + 1:05d}"
        candidates.append(
            RoomBoundaryCandidate(
                boundary_id=candidate_id,
                source_polyline_index=index,
                layer=normalize_cad_text(polyline.layer),
                entity_type=polyline.entity_type,
                polygon_cad=polyline.points,
                bbox_cad=polyline.bbox,
                area_cad=float(polyline.area),
            )
        )
    candidates.extend(
        _build_polygonized_segment_candidates(
            cad_raw.polylines,
            start_index=len(candidates),
            min_area=min_area,
            max_area=max_area,
            boundary_layers=boundary_layers,
            existing_signatures=signatures,
            columns=columns or [],
            column_shapes=column_shapes,
        )
    )
    return sorted(candidates, key=lambda candidate: _boundary_sort_key(candidate, boundary_layers=boundary_layers))


def _is_usable_boundary(polyline: CadPolylineEntity, min_area: float, max_area: float) -> bool:
    if not polyline.closed or polyline.area is None or polyline.bbox is None:
        return False
    if len(polyline.points) < 3:
        return False
    if polyline.area < min_area or polyline.area > max_area:
        return False
    bbox_width = polyline.bbox[2] - polyline.bbox[0]
    bbox_height = polyline.bbox[3] - polyline.bbox[1]
    if bbox_width <= 0 or bbox_height <= 0:
        return False
    return True


def _build_polygonized_segment_candidates(
    polylines: list[CadPolylineEntity],
    start_index: int,
    min_area: float,
    max_area: float,
    boundary_layers: list[str] | None,
    existing_signatures: set[tuple[float, float, float, float, float]],
    columns: list[CadColumnEntity],
    column_shapes: list[Polygon],
) -> list[RoomBoundaryCandidate]:
    """Build closed polygons from exploded LINE/ARC/open-polyline wall segments."""
    if not boundary_layers:
        return []
    segments_by_layer: dict[str, list[LineString]] = defaultdict(list)
    for polyline in polylines:
        if polyline.closed or len(polyline.points) < 2:
            continue
        if not _matches_any_layer_rule(polyline.layer, boundary_layers):
            continue
        line = _line_string_from_points(polyline.points)
        if line is not None:
            segments_by_layer[polyline.layer].append(line)

    candidates: list[RoomBoundaryCandidate] = []
    for layer, segments in segments_by_layer.items():
        if not segments:
            continue
        column_segments = _column_segments(columns)
        base_segments = _line_segments(unary_union(segments))
        bridge_segments = _bridge_segment_gaps(base_segments)
        try:
            merged = unary_union([*base_segments, *column_segments, *bridge_segments])
            polygons = list(polygonize(merged))
        except Exception:
            continue
        for polygon in polygons:
            if polygon.is_empty or not polygon.is_valid:
                continue
            area = float(polygon.area)
            if area < min_area or area > max_area:
                continue
            points = [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]]
            bbox = calculate_bbox(points)
            if bbox is None:
                continue
            if not _has_usable_bbox(bbox):
                continue
            if _is_column_body_candidate(points, bbox, area, column_shapes):
                continue
            signature = _boundary_signature(bbox, area)
            if signature in existing_signatures:
                continue
            existing_signatures.add(signature)
            candidate_id = f"boundary_{start_index + len(candidates) + 1:05d}"
            candidates.append(
                RoomBoundaryCandidate(
                    boundary_id=candidate_id,
                    source_polyline_index=-1,
                    layer=normalize_cad_text(layer),
                    entity_type="SEGMENT_POLYGONIZED",
                    polygon_cad=points,
                    bbox_cad=bbox,
                    area_cad=area,
                    metadata={
                        "boundary_source": "polygonized_open_segments",
                        "door_gap_bridge_count": len(bridge_segments),
                        "column_edge_segments_used": len(column_segments),
                    },
                )
            )
    return candidates


def _column_shapes(columns: list[CadColumnEntity]) -> list[Polygon]:
    shapes: list[Polygon] = []
    for column in columns:
        points = column.polygon
        if not points and column.bbox:
            min_x, min_y, max_x, max_y = column.bbox
            points = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        if len(points) < 3:
            continue
        polygon = Polygon(points)
        if not polygon.is_empty and polygon.is_valid and polygon.area > 0:
            shapes.append(polygon)
    return shapes


def _is_column_body_candidate(
    points: list[tuple[float, float]],
    bbox: tuple[float, float, float, float] | None,
    area: float,
    column_shapes: list[Polygon],
) -> bool:
    if not column_shapes or len(points) < 3 or bbox is None or area <= 0:
        return False
    polygon = Polygon(points)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        return False
    for column_shape in column_shapes:
        if not _bbox_intersects(bbox, column_shape.bounds):
            continue
        intersection_area = polygon.intersection(column_shape).area
        if intersection_area <= 0:
            continue
        candidate_coverage = intersection_area / max(polygon.area, 1.0)
        column_coverage = intersection_area / max(column_shape.area, 1.0)
        area_ratio = polygon.area / max(column_shape.area, 1.0)
        if candidate_coverage >= 0.9 and column_coverage >= 0.9 and 0.75 <= area_ratio <= 1.35:
            return True
    return False


def _bbox_intersects(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
    return not (first[2] < second[0] or second[2] < first[0] or first[3] < second[1] or second[3] < first[1])


def _column_segments(columns: list[CadColumnEntity]) -> list[LineString]:
    segments: list[LineString] = []
    for column in columns:
        points = column.polygon
        if not points and column.bbox:
            min_x, min_y, max_x, max_y = column.bbox
            points = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
        if len(points) < 3:
            continue
        ring = [*points, points[0]]
        for start, end in zip(ring, ring[1:]):
            line = _line_string_from_points([start, end])
            if line is not None:
                segments.append(line)
    return segments


def _line_segments(geometry) -> list[LineString]:
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if isinstance(line, LineString)]
    if hasattr(geometry, "geoms"):
        return [line for item in geometry.geoms for line in _line_segments(item)]
    return []


def _bridge_segment_gaps(
    segments: list[LineString],
    min_gap: float = 400.0,
    max_gap: float = 1800.0,
    direction_cosine_threshold: float = 0.92,
    max_bridges_per_endpoint: int = 1,
) -> list[LineString]:
    endpoints: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for segment in segments:
        coords = list(segment.coords)
        if len(coords) < 2:
            continue
        endpoints.append(((float(coords[0][0]), float(coords[0][1])), _unit_vector(coords[1], coords[0])))
        endpoints.append(((float(coords[-1][0]), float(coords[-1][1])), _unit_vector(coords[-2], coords[-1])))

    bridges: list[LineString] = []
    seen: set[tuple[float, float, float, float]] = set()
    endpoint_bridge_counts: dict[int, int] = defaultdict(int)
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)
    bin_size = max_gap
    for index, (point, _) in enumerate(endpoints):
        bins[(int(point[0] // bin_size), int(point[1] // bin_size))].append(index)

    for index, (point, direction) in enumerate(endpoints):
        if endpoint_bridge_counts[index] >= max_bridges_per_endpoint:
            continue
        bin_x = int(point[0] // bin_size)
        bin_y = int(point[1] // bin_size)
        nearby_indices = [
            other_index
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for other_index in bins.get((bin_x + dx, bin_y + dy), [])
            if other_index > index
        ]
        scored: list[tuple[float, int, tuple[float, float]]] = []
        for other_index in nearby_indices:
            if endpoint_bridge_counts[other_index] >= max_bridges_per_endpoint:
                continue
            other_point, other_direction = endpoints[other_index]
            distance = _distance(point, other_point)
            if distance < min_gap or distance > max_gap:
                continue
            gap_direction = _unit_vector(other_point, point)
            if _dot(direction, other_direction) > -direction_cosine_threshold:
                continue
            if abs(_dot(direction, gap_direction)) < direction_cosine_threshold:
                continue
            if abs(_dot(other_direction, gap_direction)) < direction_cosine_threshold:
                continue
            scored.append((distance, other_index, other_point))
        for _, other_index, other_point in sorted(scored, key=lambda item: item[0])[:max_bridges_per_endpoint]:
            key = _segment_key(point, other_point)
            if key in seen:
                continue
            seen.add(key)
            line = _line_string_from_points([point, other_point])
            if line is not None:
                bridges.append(line)
                endpoint_bridge_counts[index] += 1
                endpoint_bridge_counts[other_index] += 1
                if endpoint_bridge_counts[index] >= max_bridges_per_endpoint:
                    break
    return bridges


def _unit_vector(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    dx = float(start[0]) - float(end[0])
    dy = float(start[1]) - float(end[1])
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _dot(first: tuple[float, float], second: tuple[float, float]) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    dx = first[0] - second[0]
    dy = first[1] - second[1]
    return float((dx * dx + dy * dy) ** 0.5)


def _segment_key(first: tuple[float, float], second: tuple[float, float]) -> tuple[float, float, float, float]:
    left, right = sorted((first, second))
    return (round(left[0], 1), round(left[1], 1), round(right[0], 1), round(right[1], 1))


def _line_string_from_points(points: list[tuple[float, float]]) -> LineString | None:
    rounded = [(round(point[0], 3), round(point[1], 3)) for point in points]
    if len(set(rounded)) < 2:
        return None
    line = set_precision(LineString(rounded), grid_size=1.0)
    if line.is_empty or line.length <= 0:
        return None
    return line


def _has_usable_bbox(bbox: tuple[float, float, float, float]) -> bool:
    bbox_width = bbox[2] - bbox[0]
    bbox_height = bbox[3] - bbox[1]
    return bbox_width > 0 and bbox_height > 0


def _boundary_signature(bbox: tuple[float, float, float, float] | None, area: float) -> tuple[float, float, float, float, float]:
    if bbox is None:
        return (0.0, 0.0, 0.0, 0.0, round(area, 1))
    return (round(bbox[0], 1), round(bbox[1], 1), round(bbox[2], 1), round(bbox[3], 1), round(area, 1))


def _boundary_sort_key(candidate: RoomBoundaryCandidate, boundary_layers: list[str] | None = None) -> tuple[int, float]:
    return (boundary_layer_priority(candidate, boundary_layers=boundary_layers), candidate.area_cad)


def boundary_layer_priority(candidate: RoomBoundaryCandidate, boundary_layers: list[str] | None = None) -> int:
    """Return 0 for likely room boundary layers, 1 for fallback layers."""
    if boundary_layers:
        for index, rule in enumerate(boundary_layers):
            if _matches_layer_rule(candidate.layer, rule):
                return index
        return len(boundary_layers)
    layer = candidate.layer.upper()
    is_preferred = any(keyword.upper() in layer for keyword in PREFERRED_BOUNDARY_LAYER_KEYWORDS)
    return 0 if is_preferred else 1


def _matches_any_layer_rule(layer: str, rules: list[str]) -> bool:
    return any(_matches_layer_rule(layer, rule) for rule in rules)


def _matches_layer_rule(layer: str, rule: str) -> bool:
    for layer_value in _layer_values(layer):
        for rule_value in _layer_values(rule):
            if not rule_value:
                continue
            if rule_value.startswith("CONTAINS:"):
                token = rule_value.removeprefix("CONTAINS:").strip()
                if token and token in layer_value:
                    return True
                continue
            if "*" in rule_value or "?" in rule_value:
                if fnmatchcase(layer_value, rule_value):
                    return True
                continue
            if _is_keyword_contains_rule(rule_value) and rule_value in layer_value:
                return True
            if layer_value == rule_value or layer_value.endswith(f"${rule_value}") or layer_value.endswith(rule_value):
                return True
    return False


def _layer_values(layer: str) -> set[str]:
    return {str(layer).upper(), recover_gbk_mojibake(str(layer)).upper()}


def _is_keyword_contains_rule(rule: str) -> bool:
    return rule in {"WALL"}
