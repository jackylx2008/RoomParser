from __future__ import annotations

from room_extractor.models.drawing import CadRawExtraction, CadPolylineEntity
from room_extractor.models.room_candidate import RoomBoundaryCandidate
from room_extractor.utils.text_normalizer import normalize_cad_text


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
) -> list[RoomBoundaryCandidate]:
    """Extract filtered closed polyline boundary candidates from cad_raw."""
    candidates: list[RoomBoundaryCandidate] = []
    for index, polyline in enumerate(cad_raw.polylines):
        if not _is_usable_boundary(polyline, min_area=min_area, max_area=max_area):
            continue
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
    return sorted(candidates, key=_boundary_sort_key)


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


def _boundary_sort_key(candidate: RoomBoundaryCandidate) -> tuple[int, float]:
    return (boundary_layer_priority(candidate), candidate.area_cad)


def boundary_layer_priority(candidate: RoomBoundaryCandidate) -> int:
    """Return 0 for likely room boundary layers, 1 for fallback layers."""
    layer = candidate.layer.upper()
    is_preferred = any(keyword.upper() in layer for keyword in PREFERRED_BOUNDARY_LAYER_KEYWORDS)
    return 0 if is_preferred else 1
