from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from room_extractor.geometry import is_point_in_bbox, is_point_in_polygon, point_to_bbox_distance
from room_extractor.models.drawing import CadRawExtraction
from room_extractor.models.issue import Issue
from room_extractor.models.room_candidate import RoomBoundaryCandidate, RoomCandidate, RoomCandidateSet
from room_extractor.models.room_label import RoomLabelCandidateSet
from room_extractor.extraction.room_boundary_detector import (
    DEFAULT_MAX_BOUNDARY_AREA,
    DEFAULT_MIN_BOUNDARY_AREA,
    boundary_layer_priority,
    build_room_boundary_candidates,
)


FALLBACK_MAX_DISTANCE = 8_000.0
SPECIAL_SPACE_NAMES = ("客梯", "货梯", "电梯厅", "走道", "通道", "楼梯")


@dataclass(frozen=True)
class BoundaryMatch:
    boundary: RoomBoundaryCandidate
    method: str
    fallback_distance: float = 0.0


def build_room_candidates(
    cad_raw: CadRawExtraction,
    labels: RoomLabelCandidateSet,
    floor: str | None = None,
    min_boundary_area: float = DEFAULT_MIN_BOUNDARY_AREA,
    max_boundary_area: float = DEFAULT_MAX_BOUNDARY_AREA,
) -> RoomCandidateSet:
    """Match Phase 2 labels to Phase 3 CAD boundary candidates."""
    boundaries = build_room_boundary_candidates(cad_raw, min_area=min_boundary_area, max_area=max_boundary_area)
    room_candidates = [
        _build_room_candidate(index=index + 1, label=label, boundaries=boundaries, floor=floor)
        for index, label in enumerate(labels.candidates)
    ]
    return RoomCandidateSet(
        source_file=cad_raw.source_file,
        label_source_file=labels.source_file,
        summary=_build_summary(boundaries, room_candidates),
        boundary_candidates=boundaries,
        room_candidates=room_candidates,
    )


def _build_room_candidate(
    index: int,
    label,
    boundaries: list[RoomBoundaryCandidate],
    floor: str | None,
) -> RoomCandidate:
    match = _find_boundary_match(label, boundaries)
    boundary = match.boundary if match else None
    issues: list[Issue] = []
    status = "matched"
    match_method = "point_in_polygon_smallest_area"
    confidence = _matched_confidence(label.confidence, boundary)
    if match is not None:
        match_method = match.method
        if match.method == "nearest_preferred_boundary_bbox_fallback":
            status = "matched_fallback"
            confidence = _fallback_confidence(label.confidence, match.fallback_distance)
            issues.append(
                Issue(
                    issue_code="LABEL_OUTSIDE_BOUNDARY_FALLBACK_MATCH",
                    severity="medium",
                    field="geometry",
                    cad_value={"fallback_distance": round(match.fallback_distance, 3), "boundary_id": boundary.boundary_id},
                    message="房间文字中心点未落入 polygon，已按优先边界图层 bbox 距离进行低置信度匹配",
                    need_manual_review=True,
                )
            )
    else:
        status = "auto_failed"
        match_method = "unmatched_classified"
        confidence = min(label.confidence, 0.5)
        issues.append(_unmatched_issue(label, boundaries))
    return RoomCandidate(
        room_candidate_id=f"room_candidate_{index:04d}",
        floor=floor or label.floor,
        room_number=label.room_number,
        room_name=label.room_name,
        area_text=label.area,
        area_unit=label.area_unit,
        label_center=label.center,
        label_bbox=label.bbox,
        boundary=boundary,
        match_method=match_method,
        status=status,
        confidence=confidence,
        label=label,
        issues=[*label.issues, *issues],
    )


def _find_boundary_match(label, boundaries: list[RoomBoundaryCandidate]) -> BoundaryMatch | None:
    containing = _containing_boundaries(label.center, boundaries)
    if containing:
        boundary = min(containing, key=lambda boundary: (boundary_layer_priority(boundary), boundary.area_cad))
        return BoundaryMatch(boundary=boundary, method="point_in_polygon_smallest_area")
    if _is_special_space(label) and label.area is None:
        return None
    fallback = _nearest_preferred_boundary(label.center, boundaries)
    if fallback is None:
        return None
    boundary, distance = fallback
    if distance > FALLBACK_MAX_DISTANCE:
        return None
    return BoundaryMatch(
        boundary=boundary,
        method="nearest_preferred_boundary_bbox_fallback",
        fallback_distance=distance,
    )


def _containing_boundaries(point: tuple[float, float], boundaries: list[RoomBoundaryCandidate]) -> list[RoomBoundaryCandidate]:
    containing = [
        boundary
        for boundary in boundaries
        if is_point_in_bbox(point, boundary.bbox_cad) and is_point_in_polygon(point, boundary.polygon_cad)
    ]
    return containing


def _nearest_preferred_boundary(
    point: tuple[float, float],
    boundaries: list[RoomBoundaryCandidate],
) -> tuple[RoomBoundaryCandidate, float] | None:
    preferred = [boundary for boundary in boundaries if boundary_layer_priority(boundary) == 0]
    if not preferred:
        return None
    scored = [(boundary, point_to_bbox_distance(point, boundary.bbox_cad)) for boundary in preferred]
    return min(scored, key=lambda item: (item[1], item[0].area_cad))


def _matched_confidence(label_confidence: float, boundary: RoomBoundaryCandidate | None) -> float:
    if boundary is None:
        return min(label_confidence, 0.5)
    return round(min(1.0, label_confidence * 0.75 + 0.25), 2)


def _fallback_confidence(label_confidence: float, distance: float) -> float:
    distance_penalty = min(0.25, distance / FALLBACK_MAX_DISTANCE * 0.25)
    return round(max(0.35, min(0.85, label_confidence * 0.65 + 0.2 - distance_penalty)), 2)


def _unmatched_issue(label, boundaries: list[RoomBoundaryCandidate]) -> Issue:
    if _is_special_space(label):
        return Issue(
            issue_code="SPECIAL_SPACE_NO_AREA_BOUNDARY",
            severity="medium",
            field="geometry",
            message="电梯、走道、通道等特殊空间未找到独立面积线或房间边界，需人工确认是否作为房间输出",
            need_manual_review=True,
        )
    nearest = _nearest_boundary_distance(label.center, boundaries)
    if nearest and nearest[1] <= FALLBACK_MAX_DISTANCE:
        return Issue(
            issue_code="LABEL_NEAR_BOUNDARY_BUT_OUTSIDE",
            severity="medium",
            field="geometry",
            cad_value={"nearest_boundary_id": nearest[0].boundary_id, "distance": round(nearest[1], 3), "layer": nearest[0].layer},
            message="附近存在闭合 polygon，但房间文字中心点未落入可用房间边界",
            need_manual_review=True,
        )
    return Issue(
        issue_code="BOUNDARY_LAYER_MISSING",
        severity="high",
        field="geometry",
        message="未找到可用于该房间标签的闭合房间边界",
        need_manual_review=True,
    )


def _nearest_boundary_distance(
    point: tuple[float, float],
    boundaries: list[RoomBoundaryCandidate],
) -> tuple[RoomBoundaryCandidate, float] | None:
    if not boundaries:
        return None
    scored = [(boundary, point_to_bbox_distance(point, boundary.bbox_cad)) for boundary in boundaries]
    return min(scored, key=lambda item: item[1])


def _is_special_space(label) -> bool:
    room_name = label.room_name or ""
    return any(name in room_name for name in SPECIAL_SPACE_NAMES)


def _build_summary(boundaries: list[RoomBoundaryCandidate], room_candidates: list[RoomCandidate]) -> dict[str, object]:
    status_counts = Counter(candidate.status for candidate in room_candidates)
    match_method_counts = Counter(candidate.match_method for candidate in room_candidates)
    issue_counts = Counter(issue.issue_code for candidate in room_candidates for issue in candidate.issues)
    complete_matched = sum(
        1
        for candidate in room_candidates
        if candidate.status in {"matched", "matched_fallback"}
        and candidate.room_name
        and candidate.room_number
        and candidate.area_text is not None
    )
    return {
        "boundary_candidate_count": len(boundaries),
        "room_candidate_count": len(room_candidates),
        "status_counts": dict(status_counts),
        "match_method_counts": dict(match_method_counts),
        "issue_counts": dict(issue_counts),
        "complete_matched_count": complete_matched,
    }
