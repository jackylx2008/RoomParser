from __future__ import annotations

from pathlib import Path

from room_extractor.export.recognized_rooms_html_exporter import build_recognized_rooms_html, export_recognized_rooms_html
from room_extractor.models.confidence import Confidence
from room_extractor.models.geometry import Geometry
from room_extractor.models.pdf import PdfTextExtraction
from room_extractor.models.room import AreaInfo, BasicInfo, Evidence, ReviewState, Room
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


def test_build_recognized_rooms_html_contains_overview_and_room_image() -> None:
    rooms = RoomsPdfCheck(
        source_file="sample.dxf",
        pdf_source_file="sample.pdf",
        pdf_text=PdfTextExtraction(source_file="sample.pdf", pages=[]),
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(floor="L2", room_number="201", room_name="会议室"),
                area=AreaInfo(text_value=25.0, calculated_value=25.2),
                geometry=Geometry(
                    polygon_cad=[(0, 0), (10, 0), (10, 10), (0, 10)],
                    bbox_cad=(0, 0, 10, 10),
                    geometry_source="cad_auto",
                ),
                evidence=Evidence(
                    pdf_source={
                        "local_text": "会议室 201\n25m2",
                        "review_image": {"path": "data/output/review_images/sample.png"},
                        "local_ai_check": {
                            "status": "ok",
                            "visible": True,
                            "needs_review": False,
                            "room_number_match": True,
                        },
                    }
                ),
                confidence=Confidence(overall=0.9),
                review=ReviewState(required=False, status="auto_passed"),
            )
        ],
    )

    html = build_recognized_rooms_html(rooms, out_path="data/output/reports/recognized_rooms.html")

    assert "识别房间总览" in html
    assert "总图：全链路识别到的房间" in html
    assert "overview-map" in html
    assert 'id="recognized-map"' in html
    assert "data-bbox" in html
    assert "房间分图" in html
    assert "../review_images/sample.png" in html
    assert "会议室" in html


def test_export_recognized_rooms_html_writes_file(tmp_path: Path) -> None:
    rooms = RoomsPdfCheck(
        source_file="sample.dxf",
        pdf_source_file="sample.pdf",
        pdf_text=PdfTextExtraction(source_file="sample.pdf", pages=[]),
        rooms=[],
    )
    out = export_recognized_rooms_html(rooms, tmp_path / "rooms.html")

    assert out.exists()
    assert "识别房间总览" in out.read_text(encoding="utf-8")
