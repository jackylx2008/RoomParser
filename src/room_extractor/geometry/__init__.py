"""Geometry helper functions."""

from room_extractor.geometry.polygon import (
    calculate_bbox,
    calculate_polygon_area,
    is_point_in_bbox,
    is_point_in_polygon,
    is_polygon_closed,
    point_to_bbox_distance,
    polygon_iou,
)

__all__ = [
    "calculate_bbox",
    "calculate_polygon_area",
    "is_point_in_bbox",
    "is_point_in_polygon",
    "is_polygon_closed",
    "point_to_bbox_distance",
    "polygon_iou",
]
