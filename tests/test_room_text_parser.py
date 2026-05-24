from __future__ import annotations

from room_extractor.extraction import build_room_label_candidates
from room_extractor.extraction.room_text_parser import extract_area, extract_room_category, extract_room_name, extract_room_number, parse_room_text
from room_extractor.models.drawing import CadRawExtraction, CadTextEntity
from room_extractor.utils.text_normalizer import normalize_cad_text


def test_room_text_parser_recognizes_area_formats() -> None:
    assert extract_area("25.60㎡") == 25.6
    assert extract_area("25.60m²") == 25.6
    assert extract_area("面积：25.60") == 25.6


def test_room_text_parser_recognizes_room_numbers() -> None:
    assert extract_room_number("B1-023") == "B1-023"
    assert extract_room_number("101") == "101"
    assert extract_room_number("会议室 252") == "252"
    assert extract_room_number("C.L2.M001-C04") == "C.L2.M001-C04"
    assert extract_room_number("C.2.M002") == "C.2.M002"


def test_room_text_parser_recognizes_room_name_and_mojibake() -> None:
    assert extract_room_name("办公室") == "办公室"
    assert extract_room_name("会议室 252") == "会议室"
    assert extract_room_name("会议空调机房") == "会议空调机房"
    assert extract_room_category("会议空调机房") == "空调机房"
    assert extract_room_name("强电") == "强电"
    assert extract_room_name("风井") == "风井"
    assert normalize_cad_text("0-Ãæ»ýÏß") == "0-面积线"
    parsed = parse_room_text(
        CadTextEntity(
            text="»áÒéÊÒ 252\nMeeting Room 252\n392©O",
            entity_type="MTEXT",
            layer="00C_TEXT_Room",
            position=(1.0, 2.0),
            height=400.0,
        )
    )
    assert parsed.room_name == "会议室"
    assert parsed.room_name_raw == "会议室"
    assert parsed.room_category == "会议室"
    assert parsed.room_number == "252"
    assert parsed.area == 392


def test_room_label_grouper_merges_adjacent_room_text() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        texts=[
            CadTextEntity(text="办公室", entity_type="TEXT", layer="A-ROOM-TEXT", position=(1000, 1000), height=300),
            CadTextEntity(text="101", entity_type="TEXT", layer="A-ROOM-TEXT", position=(1000, 700), height=300),
            CadTextEntity(text="25.60㎡", entity_type="TEXT", layer="A-ROOM-TEXT", position=(1000, 400), height=300),
        ],
    )

    result = build_room_label_candidates(cad_raw, floor="L2")

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.floor == "L2"
    assert candidate.room_name == "办公室"
    assert candidate.room_name_raw == "办公室"
    assert candidate.room_category == "办公室"
    assert candidate.room_number == "101"
    assert candidate.area == 25.6
    assert candidate.confidence == 1.0


def test_room_label_grouper_splits_nearby_multiple_room_numbers() -> None:
    cad_raw = CadRawExtraction(
        source_file="sample.dxf",
        texts=[
            CadTextEntity(text="服务间\nPantry\n2-07（66㎡）", entity_type="MTEXT", layer="A-ROOM-TEXT", position=(5000, 1000), height=300),
            CadTextEntity(text="新风井", entity_type="TEXT", layer="A-ROOM-TEXT", position=(3200, 1000), height=300),
            CadTextEntity(text="C.L2.M019", entity_type="TEXT", layer="A-ROOM-TEXT", position=(3200, 700), height=300),
        ],
    )

    result = build_room_label_candidates(cad_raw, floor="L2")
    by_number = {candidate.room_number: candidate for candidate in result.candidates}

    assert by_number["2-07"].room_name == "服务间"
    assert by_number["C.L2.M019"].room_name == "新风井"
    assert by_number["C.L2.M019"].room_category == "新风井"
