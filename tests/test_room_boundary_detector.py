from __future__ import annotations

from room_extractor.extraction import build_room_boundary_candidates, build_room_candidates
from room_extractor.extraction.elevator_symbol_detector import detect_elevator_symbols
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


def test_boundary_detector_wall_keyword_matches_any_wall_layer() -> None:
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
            ),
            CadPolylineEntity(
                layer="A-FURN",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (3000, 0), (3000, 3000), (0, 3000)],
                bbox=(0, 0, 3000, 3000),
                area=9_000_000,
            ),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["WALL"])

    assert len(boundaries) == 1
    assert boundaries[0].layer == "05-L2-WALL$1$VT-WALL-总包"


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


def test_boundary_detector_polygonizes_default_wall_layers_without_explicit_rules() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="05-L2-WALL$1$VT-WALL-总包", entity_type="LINE", closed=False, points=[(0, 0), (3000, 0)], bbox=(0, 0, 3000, 0)),
            CadPolylineEntity(layer="05-L2-WALL$1$VT-WALL-总包", entity_type="LINE", closed=False, points=[(3000, 0), (3000, 2000)], bbox=(3000, 0, 3000, 2000)),
            CadPolylineEntity(layer="05-L2-WALL$1$VT-WALL-总包", entity_type="LINE", closed=False, points=[(3000, 2000), (0, 2000)], bbox=(0, 2000, 3000, 2000)),
            CadPolylineEntity(layer="05-L2-WALL$1$VT-WALL-总包", entity_type="LINE", closed=False, points=[(0, 2000), (0, 0)], bbox=(0, 0, 0, 2000)),
            CadPolylineEntity(layer="A-FURN", entity_type="LINE", closed=False, points=[(0, 0), (3000, 2000)], bbox=(0, 0, 3000, 2000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw)

    assert len(boundaries) == 1
    assert boundaries[0].entity_type == "SEGMENT_POLYGONIZED"
    assert boundaries[0].layer == "05-L2-WALL$1$VT-WALL-总包"
    assert boundaries[0].area_cad == 6_000_000


def test_boundary_detector_bridges_configured_door_gap_width() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (2000, 0)], bbox=(0, 0, 2000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(2700, 0), (5000, 0)], bbox=(2700, 0, 5000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 0), (5000, 3000)], bbox=(5000, 0, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 3000), (0, 3000)], bbox=(0, 3000, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 3000), (0, 0)], bbox=(0, 0, 0, 3000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert len(boundaries) == 1
    assert boundaries[0].metadata["door_gap_bridge_count"] == 1
    assert boundaries[0].metadata["door_gap_min_width"] == 700.0
    assert boundaries[0].metadata["door_gap_max_width"] == 2500.0


def test_boundary_detector_does_not_bridge_gap_below_door_width() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (2000, 0)], bbox=(0, 0, 2000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(2650, 0), (5000, 0)], bbox=(2650, 0, 5000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 0), (5000, 3000)], bbox=(5000, 0, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 3000), (0, 3000)], bbox=(0, 3000, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 3000), (0, 0)], bbox=(0, 0, 0, 3000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert boundaries == []


def test_boundary_detector_stitches_tiny_aligned_wall_gap() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (2000, 0)], bbox=(0, 0, 2000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(2200, 0), (5000, 0)], bbox=(2200, 0, 5000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 0), (5000, 3000)], bbox=(5000, 0, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 3000), (0, 3000)], bbox=(0, 3000, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 3000), (0, 0)], bbox=(0, 0, 0, 3000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert len(boundaries) == 1
    assert boundaries[0].metadata["wall_gap_stitch_count"] == 1
    assert boundaries[0].metadata["door_gap_bridge_count"] == 0


def test_boundary_detector_does_not_bridge_non_aligned_door_gap() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (2000, 0)], bbox=(0, 0, 2000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(2700, 200), (5000, 200)], bbox=(2700, 200, 5000, 200)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 200), (5000, 3000)], bbox=(5000, 200, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(5000, 3000), (0, 3000)], bbox=(0, 3000, 5000, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 3000), (0, 0)], bbox=(0, 0, 0, 3000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert boundaries == []


def test_boundary_detector_bridges_endpoint_to_crossing_wall_line() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (4000, 0)], bbox=(0, 0, 4000, 0)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 0), (0, 3000)], bbox=(0, 0, 0, 3000)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(4000, 0), (4000, 1200)], bbox=(4000, 0, 4000, 1200)),
            CadPolylineEntity(layer="A-WALL", entity_type="LINE", closed=False, points=[(0, 3000), (5000, 3000)], bbox=(0, 3000, 5000, 3000)),
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert any(boundary.bbox_cad == (0.0, 0.0, 4000.0, 3000.0) for boundary in boundaries)


def test_boundary_detector_rejects_diagonal_room_boundary_edges() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (3000, 300), (3000, 3000), (0, 3000)],
                bbox=(0, 0, 3000, 3000),
                area=8_550_000,
            )
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert boundaries == []


def test_boundary_detector_keeps_tiny_non_orthogonal_noise() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (3000, 1), (3000, 3000), (0, 3000)],
                bbox=(0, 0, 3000, 3000),
                area=8_998_500,
            )
        ],
    )

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"])

    assert len(boundaries) == 1


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


def test_boundary_detector_does_not_emit_column_body_as_room_boundary() -> None:
    column_polygon = [(0, 0), (2000, 0), (2000, 2000), (0, 2000)]
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=column_polygon,
                bbox=(0, 0, 2000, 2000),
                area=4_000_000,
            )
        ],
    )
    columns = [
        CadColumnEntity(
            column_id="column_00001",
            layer="A-STR-COLM",
            entity_type="HATCH",
            source="hatch_boundary",
            polygon=column_polygon,
            bbox=(0, 0, 2000, 2000),
            area=4_000_000,
        )
    ]

    boundaries = build_room_boundary_candidates(cad_raw, boundary_layers=["A-WALL"], columns=columns)

    assert boundaries == []


def _elevator_symbol_polylines(layer: str = "A-DETL-GENF") -> list[CadPolylineEntity]:
    return [
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(-100, 0), (2300, 0)], bbox=(-100, 0, 2300, 0)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(-100, 2200), (2300, 2200)], bbox=(-100, 2200, 2300, 2200)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(-100, 0), (-100, 2200)], bbox=(-100, 0, -100, 2200)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(2300, 0), (2300, 2200)], bbox=(2300, 0, 2300, 2200)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(400, 200), (2200, 200)], bbox=(400, 200, 2200, 200)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(400, 2000), (2200, 2000)], bbox=(400, 2000, 2200, 2000)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(400, 200), (400, 2000)], bbox=(400, 200, 400, 2000)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(2200, 200), (2200, 2000)], bbox=(2200, 200, 2200, 2000)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(400, 200), (2200, 2000)], bbox=(400, 200, 2200, 2000)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(400, 2000), (2200, 200)], bbox=(400, 200, 2200, 2000)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(0, 400), (200, 400)], bbox=(0, 400, 200, 400)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(0, 1800), (200, 1800)], bbox=(0, 1800, 200, 1800)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(0, 400), (0, 1800)], bbox=(0, 400, 0, 1800)),
        CadPolylineEntity(layer=layer, entity_type="LINE", closed=False, points=[(200, 400), (200, 1800)], bbox=(200, 400, 200, 1800)),
    ]


def test_elevator_symbol_detector_requires_crossed_rectangle_and_side_strip() -> None:
    cad_raw = CadRawExtraction(source_file="sample.dxf", polylines=_elevator_symbol_polylines())

    symbols = detect_elevator_symbols(cad_raw)

    assert len(symbols) == 1
    assert symbols[0].bbox_cad == (-100.0, 0.0, 2300.0, 2200.0)
    assert symbols[0].metadata["space_envelope_bbox_cad"] == (-100.0, 0.0, 2300.0, 2200.0)
    assert symbols[0].metadata["cross_diagonal_count"] == 2
    assert symbols[0].metadata["side_strip_bbox_cad"] == (0.0, 400.0, 200.0, 1800.0)


def test_elevator_symbol_detector_ignores_structural_beam_rectangles() -> None:
    cad_raw = CadRawExtraction(source_file="sample.dxf", polylines=_elevator_symbol_polylines(layer="S-BEAM"))

    assert detect_elevator_symbols(cad_raw) == []


def test_room_candidate_builder_appends_elevator_symbol_candidate_without_text_label() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            *_elevator_symbol_polylines(),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(3000, 0), (3600, 0)], bbox=(3000, 0, 3600, 0)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(3000, 0), (3000, 1400)], bbox=(3000, 0, 3000, 1400)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(3600, 0), (3600, 1400)], bbox=(3600, 0, 3600, 1400)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(3000, 1400), (3600, 1400)], bbox=(3000, 1400, 3600, 1400)),
        ],
    )
    labels = RoomLabelCandidateSet(source_file="sample.dxf")

    result = build_room_candidates(cad_raw, labels, boundary_layers=["WALL"])

    assert len(result.room_candidates) == 1
    room = result.room_candidates[0]
    assert room.room_name == "客梯"
    assert room.room_category == "电梯"
    assert room.match_method == "elevator_symbol_shape"
    assert room.boundary is not None
    assert room.boundary.entity_type == "ELEVATOR_SYMBOL_SHAPE"
    assert result.summary["elevator_symbol_candidate_count"] == 1


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


def test_room_candidate_builder_suppresses_collection_polygon_over_small_rooms() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (5000, 0), (5000, 2500), (0, 2500)],
                bbox=(0, 0, 5000, 2500),
                area=12_500_000,
            ),
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (2500, 0), (2500, 2500), (0, 2500)],
                bbox=(0, 0, 2500, 2500),
                area=6_250_000,
            ),
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(2500, 0), (5000, 0), (5000, 2500), (2500, 2500)],
                bbox=(2500, 0, 5000, 2500),
                area=6_250_000,
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
                area=6.25,
                center=(1000, 1000),
                bbox=(900, 900, 1100, 1100),
                confidence=1.0,
            ),
            RoomLabelCandidate(
                candidate_id="label_0002",
                room_number="102",
                room_name="会议室",
                area=6.25,
                center=(4000, 1000),
                bbox=(3900, 900, 4100, 1100),
                confidence=1.0,
            ),
            RoomLabelCandidate(
                candidate_id="label_0003",
                room_number="100",
                room_name="合集",
                area=12.5,
                center=(2500, 1250),
                bbox=(2400, 1150, 2600, 1350),
                confidence=1.0,
            ),
        ],
    )

    result = build_room_candidates(cad_raw, labels, boundary_layers=["A-WALL"])

    matched = [room for room in result.room_candidates if room.status == "matched"]
    suppressed = result.room_candidates[2]
    assert len(matched) == 2
    assert suppressed.status == "auto_failed"
    assert suppressed.boundary is None
    assert suppressed.match_method == "overlap_suppressed"
    assert suppressed.issues[-1].issue_code in {
        "ROOM_BOUNDARY_CONTAINS_SELECTED_ROOM",
        "ROOM_BOUNDARY_OVERLAPS_SELECTED_ROOM",
    }


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


def test_room_candidate_builder_rejects_structural_enclosure_for_shaft_label() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (800, 0), (800, 5000), (0, 5000)],
                bbox=(0, 0, 800, 5000),
                area=4_000_000,
            ),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(200, 300), (200, 4700)], bbox=(200, 300, 200, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(600, 300), (600, 4700)], bbox=(600, 300, 600, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(200, 300), (600, 300)], bbox=(200, 300, 600, 300)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(200, 4700), (600, 4700)], bbox=(200, 4700, 600, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(250, 700), (550, 700)], bbox=(250, 700, 550, 700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(250, 4300), (550, 4300)], bbox=(250, 4300, 550, 4300)),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="E.L2.M215",
                room_name="排烟井",
                room_category="排烟井",
                center=(400, 2500),
                bbox=(300, 2400, 500, 2600),
                confidence=0.7,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels, boundary_layers=["WALL"]).room_candidates[0]

    assert room.status == "auto_failed"
    assert room.boundary is None
    assert room.issues[-1].issue_code == "STRUCTURAL_LAYER_ENCLOSED_SPACE_NOT_ROOM"


def test_room_candidate_builder_rejects_beam_and_column_structural_enclosure() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (1000, 0), (1000, 4000), (0, 4000)],
                bbox=(0, 0, 1000, 4000),
                area=4_000_000,
            ),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(0, 800), (0, 3200)], bbox=(0, 800, 0, 3200)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1000, 800), (1000, 3200)], bbox=(1000, 800, 1000, 3200)),
        ],
        columns=[
            CadColumnEntity(
                column_id="column_top",
                layer="A-STR-COLM",
                entity_type="HATCH",
                source="hatch_boundary",
                polygon=[(0, 0), (1000, 0), (1000, 800), (0, 800)],
                bbox=(0, 0, 1000, 800),
            ),
            CadColumnEntity(
                column_id="column_bottom",
                layer="A-STR-COLM",
                entity_type="HATCH",
                source="hatch_boundary",
                polygon=[(0, 3200), (1000, 3200), (1000, 4000), (0, 4000)],
                bbox=(0, 3200, 1000, 4000),
            ),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="E.L2.M215",
                room_name="排烟井",
                room_category="排烟井",
                center=(500, 2000),
                bbox=(400, 1900, 600, 2100),
                confidence=0.7,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels, boundary_layers=["WALL"]).room_candidates[0]

    assert room.status == "auto_failed"
    assert room.boundary is None
    assert room.issues[-1].issue_code == "STRUCTURAL_LAYER_ENCLOSED_SPACE_NOT_ROOM"


def test_room_candidate_builder_matches_adjacent_shaft_when_label_inside_structural_enclosure() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (900, 0), (900, 5000), (0, 5000)],
                bbox=(0, 0, 900, 5000),
                area=4_500_000,
            ),
            CadPolylineEntity(
                layer="A-WALL",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(900, 0), (1700, 0), (1700, 5000), (900, 5000)],
                bbox=(900, 0, 1700, 5000),
                area=4_000_000,
            ),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1100, 300), (1100, 4700)], bbox=(1100, 300, 1100, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1500, 300), (1500, 4700)], bbox=(1500, 300, 1500, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1100, 300), (1500, 300)], bbox=(1100, 300, 1500, 300)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1100, 4700), (1500, 4700)], bbox=(1100, 4700, 1500, 4700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1150, 700), (1450, 700)], bbox=(1150, 700, 1450, 700)),
            CadPolylineEntity(layer="S-BEAM", entity_type="LINE", closed=False, points=[(1150, 4300), (1450, 4300)], bbox=(1150, 4300, 1450, 4300)),
        ],
    )
    labels = RoomLabelCandidateSet(
        source_file="sample.dxf",
        candidates=[
            RoomLabelCandidate(
                candidate_id="label_0001",
                room_number="E.L2.M215",
                room_name="排烟井",
                room_category="排烟井",
                center=(1000, 2500),
                bbox=(900, 2400, 1100, 2600),
                confidence=0.7,
            )
        ],
    )

    room = build_room_candidates(cad_raw, labels, boundary_layers=["WALL"]).room_candidates[0]

    assert room.status == "matched_fallback"
    assert room.boundary is not None
    assert room.boundary.bbox_cad == (0, 0, 900, 5000)
