from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from room_extractor.models.drawing import BBox, CadPolylineEntity, CadRawExtraction, Point


ELEVATOR_SYMBOL_LAYER_MARKERS = ("A-DETL-GENF", "ELEV", "ELEVATOR", "电梯")
AXIS_TOLERANCE = 2.0
RECTANGLE_TOLERANCE = 3.0
ELEVATOR_CORE_MIN_WIDTH = 1_200.0
ELEVATOR_CORE_MAX_WIDTH = 2_600.0
ELEVATOR_CORE_MIN_HEIGHT = 1_200.0
ELEVATOR_CORE_MAX_HEIGHT = 2_600.0
ELEVATOR_CORE_MIN_ASPECT_RATIO = 0.75
ELEVATOR_CORE_MAX_ASPECT_RATIO = 1.33
MIN_SIDE_STRIP_WIDTH = 80.0
MAX_SIDE_STRIP_WIDTH = 450.0
MIN_SIDE_STRIP_ASPECT_RATIO = 3.0
MAX_SIDE_STRIP_GAP = 500.0
MIN_CROSS_DIAGONAL_COUNT = 2
MIN_SPACE_ENVELOPE_WIDTH = 1_800.0
MAX_SPACE_ENVELOPE_WIDTH = 4_000.0
MIN_SPACE_ENVELOPE_HEIGHT = 1_800.0
MAX_SPACE_ENVELOPE_HEIGHT = 4_000.0


@dataclass(frozen=True)
class ElevatorSymbolCandidate:
    symbol_id: str
    layer: str
    bbox_cad: BBox
    polygon_cad: list[Point]
    area_cad: float
    core_bbox_cad: BBox
    source_polyline_indices: list[int]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _LineSegment:
    source_index: int
    layer: str
    orientation: str
    start: Point
    end: Point
    bbox: BBox
    length: float


@dataclass(frozen=True)
class _Rectangle:
    layer: str
    bbox: BBox
    width: float
    height: float
    source_indices: tuple[int, int, int, int]


def detect_elevator_symbols(cad_raw: CadRawExtraction) -> list[ElevatorSymbolCandidate]:
    """Detect elevator car symbols from structural linework.

    Elevator symbols are only emitted when an X-shaped car icon and a nearby
    slim side rectangle are inside a larger enclosing rectangle. The larger
    rectangle is returned as the elevator space boundary; the car icon is only
    locating evidence. S-BEAM is intentionally not part of this detector because
    it represents structural members in this plan.
    """
    segments = _line_segments(cad_raw.polylines)
    if not segments:
        return []
    rectangles = _find_core_rectangles(segments)
    candidates: list[ElevatorSymbolCandidate] = []
    for rectangle in rectangles:
        candidate = _symbol_from_core_rectangle(rectangle, segments, len(candidates) + 1)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _line_segments(polylines: list[CadPolylineEntity]) -> list[_LineSegment]:
    segments: list[_LineSegment] = []
    for source_index, polyline in enumerate(polylines):
        if not _is_elevator_symbol_layer(polyline.layer):
            continue
        points = polyline.points
        if len(points) < 2:
            continue
        point_pairs = list(zip(points, points[1:]))
        if polyline.closed and len(points) > 2:
            point_pairs.append((points[-1], points[0]))
        for start, end in point_pairs:
            segment = _make_line_segment(source_index, polyline.layer, start, end)
            if segment is not None:
                segments.append(segment)
    return segments


def _make_line_segment(source_index: int, layer: str, start: Point, end: Point) -> _LineSegment | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = hypot(dx, dy)
    if length <= 1.0:
        return None
    if abs(dy) <= AXIS_TOLERANCE:
        orientation = "H"
    elif abs(dx) <= AXIS_TOLERANCE:
        orientation = "V"
    else:
        orientation = "D"
    min_x, max_x = sorted((float(start[0]), float(end[0])))
    min_y, max_y = sorted((float(start[1]), float(end[1])))
    return _LineSegment(
        source_index=source_index,
        layer=layer,
        orientation=orientation,
        start=(float(start[0]), float(start[1])),
        end=(float(end[0]), float(end[1])),
        bbox=(min_x, min_y, max_x, max_y),
        length=length,
    )


def _find_core_rectangles(segments: list[_LineSegment]) -> list[_Rectangle]:
    horizontals = [segment for segment in segments if segment.orientation == "H"]
    verticals = [segment for segment in segments if segment.orientation == "V"]
    rectangles: list[_Rectangle] = []
    seen: set[tuple[float, float, float, float]] = set()
    for bottom in horizontals:
        for top in horizontals:
            if top.bbox[1] <= bottom.bbox[1] + ELEVATOR_CORE_MIN_HEIGHT:
                continue
            if top.layer != bottom.layer:
                continue
            min_x = max(bottom.bbox[0], top.bbox[0])
            max_x = min(bottom.bbox[2], top.bbox[2])
            min_y = bottom.bbox[1]
            max_y = top.bbox[1]
            width = max_x - min_x
            height = max_y - min_y
            if not _is_elevator_core_size(width, height):
                continue
            if not _has_cross_diagonal_pair(segments, bottom.layer, (min_x, min_y, max_x, max_y)):
                continue
            left = _find_vertical_cover(verticals, bottom.layer, min_x, min_y, max_y)
            right = _find_vertical_cover(verticals, bottom.layer, max_x, min_y, max_y)
            if left is None or right is None:
                continue
            key = tuple(round(value, 3) for value in (min_x, min_y, max_x, max_y))
            if key in seen:
                continue
            seen.add(key)
            rectangles.append(
                _Rectangle(
                    layer=bottom.layer,
                    bbox=(min_x, min_y, max_x, max_y),
                    width=width,
                    height=height,
                    source_indices=(bottom.source_index, top.source_index, left.source_index, right.source_index),
                )
            )
    return sorted(rectangles, key=lambda item: (item.bbox[0], item.bbox[1]))


def _symbol_from_core_rectangle(
    rectangle: _Rectangle,
    segments: list[_LineSegment],
    index: int,
) -> ElevatorSymbolCandidate | None:
    side_strip = _find_side_strip(rectangle, segments)
    if side_strip is None:
        return None
    envelope = _find_space_envelope(rectangle, side_strip, segments)
    if envelope is None:
        return None
    diagonal_segments = _cross_diagonal_segments(segments, rectangle.layer, rectangle.bbox)
    min_x, min_y, max_x, max_y = envelope.bbox
    polygon = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    diagonal_count = _count_cross_diagonals(segments, rectangle)
    source_indices = sorted(
        {
            *rectangle.source_indices,
            *side_strip.source_indices,
            *envelope.source_indices,
            *(segment.source_index for segment in diagonal_segments),
        }
    )
    metadata = {
        "recognition_source": "elevator_symbol_shape",
        "space_envelope_bbox_cad": envelope.bbox,
        "space_envelope_width": round(envelope.width, 3),
        "space_envelope_height": round(envelope.height, 3),
        "core_bbox_cad": rectangle.bbox,
        "core_width": round(rectangle.width, 3),
        "core_height": round(rectangle.height, 3),
        "side_strip_bbox_cad": side_strip.bbox,
        "side_strip_width": round(side_strip.width, 3),
        "side_strip_height": round(side_strip.height, 3),
        "cross_diagonal_count": diagonal_count,
        "source_polyline_indices": source_indices,
        "layer_rule": list(ELEVATOR_SYMBOL_LAYER_MARKERS),
    }
    return ElevatorSymbolCandidate(
        symbol_id=f"elevator_symbol_{index:04d}",
        layer=rectangle.layer,
        bbox_cad=(min_x, min_y, max_x, max_y),
        polygon_cad=polygon,
        area_cad=(max_x - min_x) * (max_y - min_y),
        core_bbox_cad=rectangle.bbox,
        source_polyline_indices=source_indices,
        metadata=metadata,
    )


def _is_elevator_core_size(width: float, height: float) -> bool:
    if not (ELEVATOR_CORE_MIN_WIDTH <= width <= ELEVATOR_CORE_MAX_WIDTH):
        return False
    if not (ELEVATOR_CORE_MIN_HEIGHT <= height <= ELEVATOR_CORE_MAX_HEIGHT):
        return False
    aspect_ratio = width / max(height, 1.0)
    return ELEVATOR_CORE_MIN_ASPECT_RATIO <= aspect_ratio <= ELEVATOR_CORE_MAX_ASPECT_RATIO


def _find_vertical_cover(
    verticals: list[_LineSegment],
    layer: str,
    x: float,
    min_y: float,
    max_y: float,
) -> _LineSegment | None:
    candidates = [
        segment
        for segment in verticals
        if segment.layer == layer
        and abs(segment.bbox[0] - x) <= RECTANGLE_TOLERANCE
        and segment.bbox[1] <= min_y + RECTANGLE_TOLERANCE
        and segment.bbox[3] >= max_y - RECTANGLE_TOLERANCE
    ]
    return max(candidates, key=lambda segment: segment.length, default=None)


def _find_side_strip(rectangle: _Rectangle, segments: list[_LineSegment]) -> _Rectangle | None:
    candidates = [
        candidate
        for candidate in _find_rectangles(segments, layer=rectangle.layer)
        if _is_side_strip(candidate, rectangle)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: _side_strip_gap(candidate.bbox, rectangle.bbox))


def _find_space_envelope(core: _Rectangle, side_strip: _Rectangle, segments: list[_LineSegment]) -> _Rectangle | None:
    evidence_bbox = (
        min(core.bbox[0], side_strip.bbox[0]),
        min(core.bbox[1], side_strip.bbox[1]),
        max(core.bbox[2], side_strip.bbox[2]),
        max(core.bbox[3], side_strip.bbox[3]),
    )
    candidates = []
    for candidate in _find_rectangles(segments, layer=core.layer):
        if candidate.bbox == core.bbox or candidate.bbox == side_strip.bbox:
            continue
        if not _bbox_contains(candidate.bbox, evidence_bbox, padding=RECTANGLE_TOLERANCE):
            continue
        if not (MIN_SPACE_ENVELOPE_WIDTH <= candidate.width <= MAX_SPACE_ENVELOPE_WIDTH):
            continue
        if not (MIN_SPACE_ENVELOPE_HEIGHT <= candidate.height <= MAX_SPACE_ENVELOPE_HEIGHT):
            continue
        candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.width * candidate.height)


def _find_rectangles(segments: list[_LineSegment], *, layer: str) -> list[_Rectangle]:
    horizontals = [segment for segment in segments if segment.orientation == "H" and segment.layer == layer]
    verticals = [segment for segment in segments if segment.orientation == "V" and segment.layer == layer]
    rectangles: list[_Rectangle] = []
    seen: set[tuple[float, float, float, float]] = set()
    for bottom in horizontals:
        for top in horizontals:
            if top.bbox[1] <= bottom.bbox[1] + RECTANGLE_TOLERANCE:
                continue
            min_x = max(bottom.bbox[0], top.bbox[0])
            max_x = min(bottom.bbox[2], top.bbox[2])
            min_y = bottom.bbox[1]
            max_y = top.bbox[1]
            if max_x - min_x <= RECTANGLE_TOLERANCE or max_y - min_y <= RECTANGLE_TOLERANCE:
                continue
            left = _find_vertical_cover(verticals, layer, min_x, min_y, max_y)
            right = _find_vertical_cover(verticals, layer, max_x, min_y, max_y)
            if left is None or right is None:
                continue
            key = tuple(round(value, 3) for value in (min_x, min_y, max_x, max_y))
            if key in seen:
                continue
            seen.add(key)
            rectangles.append(
                _Rectangle(
                    layer=layer,
                    bbox=(min_x, min_y, max_x, max_y),
                    width=max_x - min_x,
                    height=max_y - min_y,
                    source_indices=(bottom.source_index, top.source_index, left.source_index, right.source_index),
                )
            )
    return rectangles


def _is_side_strip(candidate: _Rectangle, core: _Rectangle) -> bool:
    width = min(candidate.width, candidate.height)
    height = max(candidate.width, candidate.height)
    if not (MIN_SIDE_STRIP_WIDTH <= width <= MAX_SIDE_STRIP_WIDTH):
        return False
    if height / max(width, 1.0) < MIN_SIDE_STRIP_ASPECT_RATIO:
        return False
    if height < core.height * 0.45 or height > core.height * 1.05:
        return False
    vertical_overlap = min(candidate.bbox[3], core.bbox[3]) - max(candidate.bbox[1], core.bbox[1])
    if vertical_overlap < min(candidate.height, core.height) * 0.65:
        return False
    gap = _side_strip_gap(candidate.bbox, core.bbox)
    return 0.0 <= gap <= MAX_SIDE_STRIP_GAP


def _side_strip_gap(strip_bbox: BBox, core_bbox: BBox) -> float:
    if strip_bbox[2] <= core_bbox[0]:
        return core_bbox[0] - strip_bbox[2]
    if core_bbox[2] <= strip_bbox[0]:
        return strip_bbox[0] - core_bbox[2]
    return 0.0


def _count_cross_diagonals(segments: list[_LineSegment], rectangle: _Rectangle) -> int:
    return len(_cross_diagonal_segments(segments, rectangle.layer, rectangle.bbox))


def _has_cross_diagonal_pair(segments: list[_LineSegment], layer: str, bbox: BBox) -> bool:
    diagonal_segments = _cross_diagonal_segments(segments, layer, bbox)
    directions = {_diagonal_direction(segment) for segment in diagonal_segments}
    return len(diagonal_segments) >= MIN_CROSS_DIAGONAL_COUNT and {"positive", "negative"}.issubset(directions)


def _cross_diagonal_segments(segments: list[_LineSegment], layer: str, bbox: BBox) -> list[_LineSegment]:
    min_x, min_y, max_x, max_y = bbox
    diagonal = hypot(max_x - min_x, max_y - min_y)
    matches: list[_LineSegment] = []
    for segment in segments:
        if segment.layer != layer or segment.orientation != "D":
            continue
        if segment.length < diagonal * 0.85:
            continue
        if not _bbox_contains(bbox, segment.bbox, padding=50.0):
            continue
        matches.append(segment)
    return matches


def _diagonal_direction(segment: _LineSegment) -> str:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    return "positive" if dx * dy > 0 else "negative"


def _bbox_contains(outer: BBox, inner: BBox, *, padding: float = 0.0) -> bool:
    return (
        inner[0] >= outer[0] - padding
        and inner[1] >= outer[1] - padding
        and inner[2] <= outer[2] + padding
        and inner[3] <= outer[3] + padding
    )


def _is_elevator_symbol_layer(layer: str) -> bool:
    upper = layer.upper()
    return any(marker.upper() in upper for marker in ELEVATOR_SYMBOL_LAYER_MARKERS)
