from __future__ import annotations

from room_extractor.models.drawing import CadRawExtraction, CadPolylineEntity
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
) -> list[RoomBoundaryCandidate]:
    """Extract filtered closed polyline boundary candidates from cad_raw."""
    candidates: list[RoomBoundaryCandidate] = []
    for index, polyline in enumerate(cad_raw.polylines):
        if not _is_usable_boundary(polyline, min_area=min_area, max_area=max_area):
            continue
        if boundary_layers and not _matches_any_layer_rule(polyline.layer, boundary_layers):
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
            if layer_value == rule_value or layer_value.endswith(f"${rule_value}") or layer_value.endswith(rule_value):
                return True
    return False


def _layer_values(layer: str) -> set[str]:
    return {str(layer).upper(), recover_gbk_mojibake(str(layer)).upper()}
