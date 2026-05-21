from __future__ import annotations

from collections.abc import Sequence

from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import Polygon

Point = tuple[float, float]
BBox = tuple[float, float, float, float]


def calculate_bbox(points: Sequence[Point]) -> BBox | None:
    """Return a bounding box as (min_x, min_y, max_x, max_y)."""
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def calculate_polygon_area(points: Sequence[Point]) -> float | None:
    """Return polygon area for three or more points."""
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    if polygon.is_empty or not polygon.is_valid:
        return None
    return float(polygon.area)


def is_polygon_closed(points: Sequence[Point], tolerance: float = 1e-6) -> bool:
    """Return True when first and last points coincide within tolerance."""
    if len(points) < 2:
        return False
    first = points[0]
    last = points[-1]
    return abs(first[0] - last[0]) <= tolerance and abs(first[1] - last[1]) <= tolerance


def is_point_in_polygon(point: Point, polygon_points: Sequence[Point]) -> bool:
    """Return True when a point is inside or touches a polygon."""
    if len(polygon_points) < 3:
        return False
    polygon = Polygon(polygon_points)
    if polygon.is_empty or not polygon.is_valid:
        return False
    shape_point = ShapelyPoint(point)
    return bool(polygon.contains(shape_point) or polygon.touches(shape_point))


def is_point_in_bbox(point: Point, bbox: BBox) -> bool:
    """Return True when a point is inside or touches a bbox."""
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def point_to_bbox_distance(point: Point, bbox: BBox) -> float:
    """Return the shortest Euclidean distance from a point to a bbox."""
    dx = max(bbox[0] - point[0], 0.0, point[0] - bbox[2])
    dy = max(bbox[1] - point[1], 0.0, point[1] - bbox[3])
    return float((dx * dx + dy * dy) ** 0.5)


def polygon_iou(first_points: Sequence[Point], second_points: Sequence[Point]) -> float:
    """Return intersection-over-union for two polygons."""
    if len(first_points) < 3 or len(second_points) < 3:
        return 0.0
    first = Polygon(first_points)
    second = Polygon(second_points)
    if first.is_empty or second.is_empty or not first.is_valid or not second.is_valid:
        return 0.0
    union_area = first.union(second).area
    if union_area == 0:
        return 0.0
    return float(first.intersection(second).area / union_area)
