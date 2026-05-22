from __future__ import annotations

from room_extractor.models.confidence import Confidence
from room_extractor.models.geometry import Geometry
from room_extractor.models.issue import Issue
from room_extractor.models.pdf import PdfTextExtraction
from room_extractor.models.room import AreaInfo, BasicInfo, Evidence, ReviewState, Room
from room_extractor.pdf.pdf_checker import RoomsPdfCheck
from room_extractor.review.review_task_builder import build_review_tasks


def test_build_review_tasks_includes_machine_review_context() -> None:
    rooms = RoomsPdfCheck(
        source_file="sample.dxf",
        pdf_source_file="sample.pdf",
        pdf_text=PdfTextExtraction(source_file="sample.pdf", pages=[]),
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(floor="L2", room_number="201", room_name="会议室", room_type="meeting"),
                area=AreaInfo(text_value=25.0, calculated_value=26.0),
                geometry=Geometry(
                    polygon_cad=[(0, 0), (10, 0), (10, 10), (0, 10)],
                    bbox_cad=(0, 0, 10, 10),
                    bbox_pdf=(1, 1, 2, 2),
                ),
                evidence=Evidence(
                    cad_source={"file": "sample.dxf"},
                    pdf_source={
                        "review_image": {"path": "review.png"},
                        "local_ai_check": {
                            "status": "ok",
                            "visible": True,
                            "area_match": False,
                            "needs_review": True,
                            "notes": "面积不一致",
                        },
                    },
                ),
                confidence=Confidence(overall=0.7, cad_pdf_consistency=0.35),
                review=ReviewState(required=True, status="pending_downstream_check"),
                issues=[
                    Issue(
                        issue_code="PDF_AREA_MISMATCH",
                        severity="medium",
                        field="area",
                        message="面积不一致",
                        need_manual_review=True,
                    )
                ],
            ),
            Room(
                room_uid="sample_r0002",
                basic_info=BasicInfo(floor="L2", room_number="202", room_name="会议室"),
                evidence=Evidence(pdf_source={"local_ai_check": {"status": "ok", "needs_review": False}}),
                review=ReviewState(required=False, status="auto_passed"),
            ),
        ],
    )

    result = build_review_tasks(rooms)

    assert result.summary["task_count"] == 1
    assert result.summary["auto_pass_count"] == 1
    task = result.tasks[0]
    assert task.room_uid == "sample_r0001"
    assert task.review_image_path == "review.png"
    assert task.local_ai_check["notes"] == "面积不一致"
    assert "area" in task.suggested_fields
    assert task.polygon_cad == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
