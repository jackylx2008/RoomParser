from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from room_extractor.models.confidence import Confidence
from room_extractor.models.geometry import Geometry
from room_extractor.models.issue import Issue
from room_extractor.models.room import AreaInfo, BasicInfo, Evidence, ReviewState, Room
from room_extractor.models.room_candidate import RoomCandidate, RoomCandidateSet
from room_extractor.utils.text_normalizer import normalize_cad_text


AREA_DEVIATION_THRESHOLD_PERCENT = 5.0
CAD_AREA_TO_M2 = 1_000_000.0


class RoomsAutoBuild(BaseModel):
    """Phase 4 rooms_auto.json payload."""

    source_file: str
    summary: dict[str, object] = Field(default_factory=dict)
    rooms: list[Room] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)


def build_rooms_auto(candidates: RoomCandidateSet) -> RoomsAutoBuild:
    """Build initial CAD-derived Room JSON from Phase 3 room candidates."""
    rooms = [_build_room(index=index + 1, candidate=candidate, source_file=candidates.source_file) for index, candidate in enumerate(candidates.room_candidates)]
    return RoomsAutoBuild(
        source_file=candidates.source_file,
        summary=_summary(rooms),
        rooms=rooms,
    )


def _build_room(index: int, candidate: RoomCandidate, source_file: str) -> Room:
    calculated_area = _calculated_area_m2(candidate)
    deviation = _area_deviation(candidate.area_text, calculated_area)
    issues = [*candidate.issues]
    if candidate.boundary is None:
        issues.append(
            Issue(
                issue_code="CAD_GEOMETRY_MISSING",
                severity="high",
                field="geometry",
                message="CAD 自动阶段未生成房间 polygon",
                need_manual_review=True,
            )
        )
    if deviation is not None and deviation > AREA_DEVIATION_THRESHOLD_PERCENT:
        issues.append(
            Issue(
                issue_code="CAD_AREA_DEVIATION_EXCEEDS_THRESHOLD",
                severity="medium",
                field="area",
                cad_value=calculated_area,
                message=f"CAD polygon 计算面积与文字面积偏差 {deviation:.2f}%",
                need_manual_review=True,
            )
        )
    confidence = _confidence(candidate, calculated_area, deviation)
    review_required = bool(issues) or confidence.overall < 0.85
    return Room(
        room_uid=_room_uid(source_file, index),
        basic_info=BasicInfo(
            floor=candidate.floor,
            room_number=candidate.room_number,
            room_name=candidate.room_name,
            room_type=_room_type(candidate.room_name),
        ),
        area=AreaInfo(
            text_value=candidate.area_text,
            calculated_value=calculated_area,
            unit=candidate.area_unit,
            deviation_percent=deviation,
        ),
        geometry=_geometry(candidate),
        evidence=Evidence(cad_source=_cad_source(source_file, candidate), pdf_source={}),
        confidence=confidence,
        review=ReviewState(
            required=review_required,
            status="pending_pdf_check" if not review_required else "pending_downstream_check",
        ),
        issues=issues,
        final_status="cad_auto_draft",
    )


def _geometry(candidate: RoomCandidate) -> Geometry:
    if candidate.boundary is None:
        return Geometry(geometry_source="auto_failed")
    source = "cad_auto" if candidate.status == "matched" else "cad_auto_fallback"
    return Geometry(
        polygon_cad=candidate.boundary.polygon_cad,
        bbox_cad=candidate.boundary.bbox_cad,
        coordinate_unit="mm",
        geometry_source=source,
    )


def _cad_source(source_file: str, candidate: RoomCandidate) -> dict[str, object]:
    return {
        "file": source_file,
        "layout": "Model",
        "label_candidate_id": candidate.label.candidate_id,
        "room_candidate_id": candidate.room_candidate_id,
        "match_status": candidate.status,
        "match_method": candidate.match_method,
        "boundary_id": candidate.boundary.boundary_id if candidate.boundary else None,
        "boundary_layer": candidate.boundary.layer if candidate.boundary else None,
        "source_text_indices": [text.source_index for text in candidate.label.source_texts],
        "source_texts": [text.normalized_text for text in candidate.label.source_texts],
    }


def _calculated_area_m2(candidate: RoomCandidate) -> float | None:
    if candidate.boundary is None:
        return None
    return round(candidate.boundary.area_cad / CAD_AREA_TO_M2, 3)


def _area_deviation(text_area: float | None, calculated_area: float | None) -> float | None:
    if text_area is None or calculated_area is None or text_area == 0:
        return None
    return round(abs(calculated_area - text_area) / text_area * 100.0, 3)


def _confidence(candidate: RoomCandidate, calculated_area: float | None, deviation: float | None) -> Confidence:
    room_number = 1.0 if candidate.room_number else 0.0
    room_name = 1.0 if candidate.room_name else 0.0
    area = _area_confidence(candidate.area_text, calculated_area, deviation)
    geometry = _geometry_confidence(candidate)
    overall = round(room_number * 0.2 + room_name * 0.25 + area * 0.25 + geometry * 0.3, 3)
    return Confidence(
        room_number=room_number,
        room_name=room_name,
        area=area,
        geometry=geometry,
        cad_pdf_consistency=0.0,
        overall=overall,
    )


def _area_confidence(text_area: float | None, calculated_area: float | None, deviation: float | None) -> float:
    if text_area is not None and calculated_area is not None:
        if deviation is not None and deviation <= AREA_DEVIATION_THRESHOLD_PERCENT:
            return 1.0
        return 0.55
    if text_area is not None:
        return 0.65
    if calculated_area is not None:
        return 0.45
    return 0.0


def _geometry_confidence(candidate: RoomCandidate) -> float:
    if candidate.status == "matched":
        return 0.9
    if candidate.status == "matched_fallback":
        return 0.65
    return 0.0


def _room_uid(source_file: str, index: int) -> str:
    stem = normalize_cad_text(source_file).rsplit(".", 1)[0].replace(" ", "_")
    return f"{stem}_r{index:04d}"


def _room_type(room_name: str | None) -> str | None:
    if not room_name:
        return None
    if "会议" in room_name:
        return "meeting"
    if "卫生间" in room_name:
        return "toilet"
    if "贵宾" in room_name:
        return "vip"
    if "电梯" in room_name or "客梯" in room_name or "货梯" in room_name:
        return "elevator"
    if "走道" in room_name or "通道" in room_name:
        return "circulation"
    if "服务" in room_name or "后勤" in room_name:
        return "service"
    if "储藏" in room_name or "库房" in room_name:
        return "storage"
    if "办公室" in room_name:
        return "office"
    return None


def _summary(rooms: list[Room]) -> dict[str, object]:
    review_counts = Counter(room.review.status for room in rooms)
    final_counts = Counter(room.final_status for room in rooms)
    issue_counts = Counter(issue.issue_code for room in rooms for issue in room.issues)
    return {
        "room_count": len(rooms),
        "with_geometry": sum(1 for room in rooms if room.geometry.polygon_cad),
        "without_geometry": sum(1 for room in rooms if not room.geometry.polygon_cad),
        "review_status_counts": dict(review_counts),
        "final_status_counts": dict(final_counts),
        "issue_counts": dict(issue_counts),
    }
