from __future__ import annotations

from room_extractor.extraction import build_room_boundary_candidates, build_room_candidates
from room_extractor.models.drawing import CadPolylineEntity, CadRawExtraction
from room_extractor.models.room_label import RoomLabelCandidate, RoomLabelCandidateSet


def test_boundary_detector_filters_closed_polylines_by_area() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (10, 0), (10, 10), (0, 10)],
                bbox=(0, 0, 10, 10),
                area=100,
            ),
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (2000, 0), (2000, 2000), (0, 2000)],
                bbox=(0, 0, 2000, 2000),
                area=4_000_000,
            ),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw)

    assert len(boundaries) == 1
    assert boundaries[0].area_cad == 4_000_000
    assert boundaries[0].bbox_cad == (0, 0, 2000, 2000)


def test_room_candidate_builder_matches_label_to_smallest_containing_polygon() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (5000, 0), (5000, 5000), (0, 5000)],
                bbox=(0, 0, 5000, 5000),
                area=25_000_000,
            ),
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(500, 500), (1500, 500), (1500, 1500), (500, 1500)],
                bbox=(500, 500, 1500, 1500),
                area=1_000_000,
            ),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                floor="L2",
                room_number="101",
                room_name="办公室",
                area=25.6,
                center=(1000, 1000),
                bbox=(900, 900, 1100, 1100),
                confidence=1.0,
            )
        ],
    )

    result = build_room_candidates(cad_raw, labels)

    assert len(result.room_candidates) == 1
    room = result.room_candidates[0]
    assert room.status == "matched"
    assert room.boundary is not None
    assert room.boundary.area_cad == 1_000_000
    assert room.confidence == 1.0


def test_room_candidate_builder_prefers_boundary_layer_over_smaller_fallback_polygon() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (5000, 0), (5000, 5000), (0, 5000)],
                bbox=(0, 0, 5000, 5000),
                area=25_000_000,
            ),
            CadPolylineEntity(
                layer="IFF-Furn",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(500, 500), (1500, 500), (1500, 1500), (500, 1500)],
                bbox=(500, 500, 1500, 1500),
                area=1_000_000,
            ),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="101",
                room_name="办公室",
                area=25.6,
                center=(1000, 1000),
                bbox=(900, 900, 1100, 1100),
                confidence=1.0,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels).room_candidates[0]

    assert room.boundary is not None
    assert room.boundary.layer == "A-AREA-BNDY"
    assert room.boundary.area_cad == 25_000_000


def test_room_candidate_builder_marks_unmatched_label() -> None:
    cad_raw = CadRawExtraction(source_file="sample.dxf")
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="101",
                room_name="办公室",
                area=25.6,
                center=(1000, 1000),
                bbox=(900, 900, 1100, 1100),
                confidence=1.0,
            )
        ],
    )

    result = build_room_candidates(cad_raw, labels)

    room = result.room_candidates[0]
    assert room.status == "auto_failed"
    assert room.boundary is None
    assert room.issues[-1].issue_code == "BOUNDARY_LAYER_MISSING"


def test_room_candidate_builder_fallback_matches_near_preferred_boundary() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="0-面积线",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (2000, 0), (2000, 2000), (0, 2000)],
                bbox=(0, 0, 2000, 2000),
                area=4_000_000,
            )
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="101",
                room_name="办公室",
                area=25.6,
                center=(2500, 1000),
                bbox=(2400, 900, 2600, 1100),
                confidence=1.0,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels).room_candidates[0]

    assert room.status == "matched_fallback"
    assert room.match_method == "nearest_preferred_boundary_bbox_fallback"
    assert room.boundary is not None
    assert room.issues[-1].issue_code == "LABEL_OUTSIDE_BOUNDARY_FALLBACK_MATCH"


def test_room_candidate_builder_classifies_special_space_without_boundary() -> None:
    cad_raw = CadRawExtraction(source_file="sample.dxf")
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="KT1",
                room_name="客梯",
                center=(1000, 1000),
                bbox=(900, 900, 1100, 1100),
                confidence=0.7,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels).room_candidates[0]

    assert room.status == "auto_failed"
    assert room.issues[-1].issue_code == "SPECIAL_SPACE_NO_AREA_BOUNDARY"


def test_room_candidate_builder_does_not_fallback_match_special_space_without_area() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="0-面积线",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (2000, 0), (2000, 2000), (0, 2000)],
                bbox=(0, 0, 2000, 2000),
                area=4_000_000,
            )
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="KT1",
                room_name="客梯",
                center=(2500, 1000),
                bbox=(2400, 900, 2600, 1100),
                confidence=0.7,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels).room_candidates[0]

    assert room.status == "auto_failed"
    assert room.match_method == "unmatched_classified"
    assert room.boundary is None
    assert room.issues[-1].issue_code == "SPECIAL_SPACE_NO_AREA_BOUNDARY"
