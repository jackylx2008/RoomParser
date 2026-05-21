from __future__ import annotations

from pathlib import Path

from room_extractor.export import export_room_candidate_review_html
from room_extractor.models.drawing import CadPolylineEntity, CadRawExtraction
from room_extractor.models.room_candidate import RoomBoundaryCandidate, RoomCandidate, RoomCandidateSet
from room_extractor.models.room_label import RoomLabelCandidate


def test_export_room_candidate_review_html_writes_visual_map(tmp_path: Path) -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        polylines=[
            CadPolylineEntity(
                layer="A-AREA-BNDY",
                entity_type="LWPOLYLINE",
                closed=True,
                points=[(0, 0), (2000, 0), (2000, 2000), (0, 2000)],
                bbox=(0, 0, 2000, 2000),
                area=4_000_000,
            )
        ],
    )
    boundary = RoomBoundaryCandidate(
        boundary_id="boundary_00001",
        source_polyline_index=0,
        layer="A-AREA-BNDY",
        entity_type="LWPOLYLINE",
        polygon_cad=[(0, 0), (2000, 0), (2000, 2000), (0, 2000)],
        bbox_cad=(0, 0, 2000, 2000),
        area_cad=4_000_000,
    )
    label = RoomLabelCandidate(
        candidate_id="label_0001",
        room_number="101",
        room_name="办公室",
        area=25.6,
        center=(1000, 1000),
        bbox=(900, 900, 1100, 1100),
        confidence=1.0,
    )
    rooms = RoomCandidateSet(
        source_file="sample.dxf",
        label_source_file="sample.dxf",
        summary={"status_counts": {"matched": 1}, "boundary_candidate_count": 1, "room_candidate_count": 1},
        boundary_candidates=[boundary],
        room_candidates=[
            RoomCandidate(
                room_candidate_id="room_candidate_0001",
                room_number="101",
                room_name="办公室",
                area_text=25.6,
                label_center=(1000, 1000),
                label_bbox=(900, 900, 1100, 1100),
                boundary=boundary,
                status="matched",
                confidence=1.0,
                label=label,
            )
        ],
    )
    out_path = tmp_path / "review.html"

    export_room_candidate_review_html(cad_raw, rooms, out_path)

    html = out_path.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "CAD底图" in html
    assert "room_candidate_0001" in html
    assert "办公室" in html
    assert "严格匹配" in html
