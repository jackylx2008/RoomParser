from __future__ import annotations

from room_extractor.geometry import (
    calculate_bbox,
    calculate_polygon_area,
    is_point_in_bbox,
    is_point_in_polygon,
    is_polygon_closed,
    point_to_bbox_distance,
    polygon_iou,
)


def test_bbox_and_area() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)]

    assert calculate_bbox(points) == (0.0, 0.0, 10.0, 5.0)
    assert calculate_polygon_area(points) == 50.0


def test_point_closed_and_iou() -> None:
    polygon = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    closed = [*polygon, polygon[0]]

    assert is_point_in_polygon((5.0, 5.0), polygon)
    assert is_point_in_bbox((5.0, 5.0), (0.0, 0.0, 10.0, 10.0))
    assert point_to_bbox_distance((15.0, 5.0), (0.0, 0.0, 10.0, 10.0)) == 5.0
    assert is_polygon_closed(closed)
    assert polygon_iou(polygon, polygon) == 1.0
