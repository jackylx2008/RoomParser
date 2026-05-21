from __future__ import annotations

from room_extractor.ai.local_ai_client import LocalAiConfig
from room_extractor.ai.room_image_checker import check_rooms_with_local_ai
from room_extractor.models.pdf import PdfTextExtraction
from room_extractor.models.room import BasicInfo, Evidence, Room
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


def test_check_rooms_with_local_ai_dry_run_updates_evidence() -> None:
    rooms = RoomsPdfCheck(
        source_file="sample.dxf",
        pdf_source_file="sample.pdf",
        pdf_text=PdfTextExtraction(source_file="sample.pdf", pages=[]),
        rooms=[
            Room(
                room_uid="sample_r0001",
                basic_info=BasicInfo(room_number="201", room_name="会议室"),
                evidence=Evidence(
                    pdf_source={
                        "local_text": "201\n25.0m2",
                        "review_image": {"path": "data/output/review_images/sample.png"},
                    }
                ),
            )
        ],
    )

    checked = check_rooms_with_local_ai(
        rooms,
        config=LocalAiConfig(base_url="http://127.0.0.1:8080/v1", model="test-model"),
        limit=1,
        dry_run=True,
    )

    ai_check = checked.rooms[0].evidence.pdf_source["local_ai_check"]
    assert checked.summary["local_ai_checked"] == 1
    assert checked.summary["local_ai_dry_run"] == 1
    assert ai_check["status"] == "dry_run"
    assert ai_check["model"] == "test-model"
