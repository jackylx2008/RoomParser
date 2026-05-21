from __future__ import annotations

from pathlib import Path

import fitz

from room_extractor.extraction.room_json_builder import RoomsAutoBuild
from room_extractor.models.confidence import Confidence
from room_extractor.models.geometry import Geometry
from room_extractor.models.room import AreaInfo, BasicInfo, ReviewState, Room
from room_extractor.pdf.pdf_checker import check_rooms_against_pdf
from room_extractor.pdf.pdf_review_image_renderer import render_review_images


def test_check_rooms_against_pdf_records_local_text_and_confidence(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _write_pdf(pdf_path, ["201", "25.0m2"])
    rooms_auto = RoomsAutoBuild(
        source_file="sample.dxf",
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(room_number="201"),
                area=AreaInfo(text_value=25.0),
                geometry=Geometry(
                    polygon_cad=[(0, 0), (100, 0), (100, 100), (0, 100)],
                    bbox_cad=(0, 0, 100, 100),
                ),
                confidence=Confidence(room_number=1.0, area=1.0, geometry=0.9, overall=0.9),
                review=ReviewState(required=False, status="pending_pdf_check"),
            )
        ],
    )

    result = check_rooms_against_pdf(rooms_auto, pdf_path)

    room = result.rooms[0]
    assert result.summary["checked_with_pdf_bbox"] == 1
    assert result.transform["method"] == "linear_fit_unverified"
    assert room.geometry.bbox_pdf is not None
    assert room.evidence.pdf_source["text_count"] == 2
    assert room.evidence.pdf_source["local_text"] == "201\n25.0m2"
    assert room.confidence.cad_pdf_consistency == 0.75
    assert not [issue for issue in room.issues if issue.issue_code.startswith("PDF_")]


def test_check_rooms_against_pdf_marks_rooms_without_geometry(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    _write_pdf(pdf_path, ["201"])
    rooms_auto = RoomsAutoBuild(
        source_file="sample.dxf",
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(room_number="201"),
                geometry=Geometry(geometry_source="auto_failed"),
            )
        ],
    )

    result = check_rooms_against_pdf(rooms_auto, pdf_path)

    assert result.issues[0].issue_code == "CAD_PDF_MAPPING_FAILED"
    assert result.rooms[0].review.required is True
    assert result.rooms[0].issues[-1].issue_code == "PDF_CHECK_SKIPPED_NO_CAD_GEOMETRY"


def test_render_review_images_writes_crop_and_updates_evidence(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    image_dir = tmp_path / "images"
    _write_pdf(pdf_path, ["201", "25.0m2"])
    rooms_auto = RoomsAutoBuild(
        source_file="sample.dxf",
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(room_number="201"),
                area=AreaInfo(text_value=25.0),
                geometry=Geometry(
                    polygon_cad=[(0, 0), (100, 0), (100, 100), (0, 100)],
                    bbox_cad=(0, 0, 100, 100),
                ),
                confidence=Confidence(room_number=1.0, area=1.0, geometry=0.9, overall=0.9),
            )
        ],
    )
    checked = check_rooms_against_pdf(rooms_auto, pdf_path)

    rendered = render_review_images(
        checked,
        pdf_path=pdf_path,
        output_dir=image_dir,
        dpi=72,
        margin_ratio=0.0,
        only_review_required=False,
    )

    review_image = rendered.rooms[0].evidence.pdf_source["review_image"]
    image_path = Path(review_image["path"])
    assert rendered.summary["review_images_rendered"] == 1
    assert rendered.summary["review_images_anchor_crops"] == 1
    assert review_image["dpi"] == 72
    assert review_image["source"] == "pdf_text_anchor_crop"
    assert image_path.exists()
    assert image_path.stat().st_size > 0


def _write_pdf(path: Path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    for index, line in enumerate(lines):
        page.insert_text((70, 70 + index * 14), line, fontsize=10)
    doc.save(path)
    doc.close()
