from __future__ import annotations

from room_extractor.extraction import build_rooms_auto
from room_extractor.models.room_candidate import RoomBoundaryCandidate, RoomCandidate, RoomCandidateSet
from room_extractor.models.room_label import RoomLabelCandidate


def test_build_rooms_auto_creates_room_with_geometry_area_and_confidence() -> None:
    boundary = RoomBoundaryCandidate(
        boundary_id="boundary_00001",
        source_polyline_index=0,
        layer="A-AREA-BNDY",
        entity_type="LWPOLYLINE",
        polygon_cad=[(0, 0), (5000, 0), (5000, 5000), (0, 5000)],
        bbox_cad=(0, 0, 5000, 5000),
        area_cad=25_000_000,
    )
    label = RoomLabelCandidate(
        candidate_id="sample_label_0001",
        floor="L2",
        room_number="201",
        room_name="会议室",
        area=25.0,
        center=(2500, 2500),
        bbox=(2400, 2400, 2600, 2600),
        confidence=1.0,
    )
    candidates = RoomCandidateSet(
        source_file="sample.dxf",
        label_source_file="sample.dxf",
        room_candidates=[
            RoomCandidate(
                room_candidate_id="room_candidate_0001",
                floor="L2",
                room_number="201",
                room_name="会议室",
                area_text=25.0,
                label_center=(2500, 2500),
                label_bbox=(2400, 2400, 2600, 2600),
                boundary=boundary,
                status="matched",
                confidence=1.0,
                label=label,
            )
        ],
    )

    result = build_rooms_auto(candidates)

    assert result.summary["room_count"] == 1
    room = result.rooms[0]
    assert room.room_uid == "sample_r0001"
    assert room.basic_info.room_type == "meeting"
    assert room.area.calculated_value == 25.0
    assert room.area.deviation_percent == 0.0
    assert room.geometry.geometry_source == "cad_auto"
    assert room.geometry.bbox_cad == (0, 0, 5000, 5000)
    assert room.confidence.overall == 0.97
    assert room.review.status == "pending_pdf_check"
    assert room.final_status == "cad_auto_draft"


def test_build_rooms_auto_marks_missing_geometry() -> None:
    label = RoomLabelCandidate(
        candidate_id="sample_label_0001",
        room_name="客梯",
        center=(1000, 1000),
        bbox=(900, 900, 1100, 1100),
        confidence=0.4,
    )
    candidates = RoomCandidateSet(
        source_file="sample.dxf",
        label_source_file="sample.dxf",
        room_candidates=[
            RoomCandidate(
                room_candidate_id="room_candidate_0001",
                room_name="客梯",
                label_center=(1000, 1000),
                label_bbox=(900, 900, 1100, 1100),
                status="auto_failed",
                confidence=0.4,
                label=label,
            )
        ],
    )

    room = build_rooms_auto(candidates).rooms[0]

    assert room.geometry.geometry_source == "auto_failed"
    assert room.review.required is True
    assert room.review.status == "pending_downstream_check"
    assert room.issues[-1].issue_code == "CAD_GEOMETRY_MISSING"
