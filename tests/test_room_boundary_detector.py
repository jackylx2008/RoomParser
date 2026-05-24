from __future__ import annotations

from room_extractor.extraction import build_room_boundary_candidates, build_room_candidates
from room_extractor.models.drawing import CadColumnEntity, CadPolylineEntity, CadRawExtraction
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


def test_boundary_detector_can_filter_to_configured_layers() -> None:
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
            ),
            CadPolylineEntity(
                layer="IFF-Furn",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (3000, 0), (3000, 3000), (0, 3000)],
                bbox=(0, 0, 3000, 3000),
                area=9_000_000,
            ),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["0-面积线"])

    assert len(boundaries) == 1
    assert boundaries[0].layer == "0-面积线"


def test_boundary_detector_polygonizes_exploded_wall_lines_on_configured_layers() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="05-L2-WALL$1$VT-WALL-总包",
                entity_type="LINE",
                closed=False,
                points=[(0, 0), (2000, 0)],
                bbox=(0, 0, 2000, 0),
            ),
            CadPolylineEntity(
                layer="05-L2-WALL$1$VT-WALL-总包",
                entity_type="LINE",
                closed=False,
                points=[(2000, 0), (2000, 2000)],
                bbox=(2000, 0, 2000, 2000),
            ),
            CadPolylineEntity(
                layer="05-L2-WALL$1$VT-WALL-总包",
                entity_type="LINE",
                closed=False,
                points=[(2000, 2000), (0, 2000)],
                bbox=(0, 2000, 2000, 2000),
            ),
            CadPolylineEntity(
                layer="05-L2-WALL$1$VT-WALL-总包",
                entity_type="LINE",
                closed=False,
                points=[(0, 2000), (0, 0)],
                bbox=(0, 0, 0, 2000),
            ),
        ],
    )

    boundaries = build_room_boundary_candidates(
        cad_raw,
        boundary_layers=["05-L2-WALL$1$VT-WALL-总包"],
    )

    assert len(boundaries) == 1
    assert boundaries[0].entity_type == "SEGMENT_POLYGONIZED"
    assert boundaries[0].area_cad == 4_000_000
    assert boundaries[0].metadata["boundary_source"] == "polygonized_open_segments"


def test_boundary_detector_can_use_column_edge_as_room_boundary_segment() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (2000, 0)], bbox=(0, 0, 2000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (0, 2000)], bbox=(0, 0, 0, 2000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 2000), (2000, 2000)], bbox=(0, 2000, 2000, 2000)),
        ],
    )
    columns = [
        CadColumnEntity(
            column_id="column_00001",
            layer="A-STR-COLM",
            entity_type="HATCH",
            source="hatch_boundary",
            polygon=[(2000, 0), (2100, 0), (2100, 2000), (2000, 2000)],
            bbox=(2000, 0, 2100, 2000),
        )
    ]

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"], columns=columns)

    assert any(boundary.area_cad == 4_000_000 for boundary in boundaries)
    assert all(boundary.metadata["column_edge_segments_used"] == 4 for boundary in boundaries)


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


def test_room_candidate_builder_uses_text_area_when_mtext_anchor_falls_in_neighbor_room() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (9000, 0), (9000, 10_000), (0, 10_000)],
                bbox=(0, 0, 9000, 10_000),
                area=90_000_000,
            ),
            CadPolylineEntity(
                layer="Defpoints",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(10_500, 0), (17_100, 0), (17_100, 10_000), (10_500, 10_000)],
                bbox=(10_500, 0, 17_100, 10_000),
                area=66_000_000,
            ),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="2-07",
                room_name="服务间",
                area=66.0,
                center=(8000, 5000),
                bbox=(7600, 4600, 8400, 5400),
                confidence=1.0,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels, boundary_layers=["A-WALL", "Defpoints"]).room_candidates[0]

    assert room.status == "matched_fallback"
    assert room.match_method == "text_area_nearby_boundary_match"
    assert room.boundary is not None
    assert room.boundary.layer == "Defpoints"
    assert room.boundary.area_cad == 66_000_000


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


def test_room_candidate_builder_fallback_matches_room_like_special_space_without_area() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="05-L2-WALL$1$VT-WALL-总包",
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
                room_name="强电",
                center=(2500, 1000),
                bbox=(2400, 900, 2600, 1100),
                confidence=0.4,
            )
        ],
    )

    room = build_room_candidates(
        cad_raw,
        labels,
        boundary_layers=["0-面积线", "05-L2-WALL$1$VT-WALL-总包"],
    ).room_candidates[0]

    assert room.status == "matched_fallback"
    assert room.boundary is not None
    assert room.boundary.layer == "05-L2-WALL$1$VT-WALL-总包"
