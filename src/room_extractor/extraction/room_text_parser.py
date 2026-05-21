from __future__ import annotations

import re

from room_extractor.models.drawing import CadTextEntity
from room_extractor.models.room_label import RoomTextParse
from room_extractor.utils.text_normalizer import normalize_cad_text


AREA_RE = re.compile(r"(?:面积[:：]?\s*)?(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2|平方米)", re.IGNORECASE)
AREA_NO_UNIT_RE = re.compile(r"^面积[:：]?\s*(\d+(?:\.\d+)?)$")
ROOM_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]?\d{1,3}-\d{1,4}[A-Z]?|\d{2,4}[A-Z]?|[A-Z]{1,4}\d{1,3}(?:-[A-Z])?)(?![A-Za-z0-9])")
ROOM_NAME_KEYWORDS = (
    "办公室",
    "会议室",
    "贵宾室",
    "卫生间",
    "无障碍卫生间",
    "服务间",
    "清洁间",
    "后勤用房",
    "机房",
    "库房",
    "储藏",
    "电梯厅",
    "客梯",
    "货梯",
    "楼梯",
    "走道",
    "通道",
    "前室",
    "大厅",
    "展厅",
)


def parse_room_text(text: CadTextEntity, source_index: int = 0) -> RoomTextParse:
    """Parse room number, name and area from one CAD text entity."""
    normalized = normalize_cad_text(text.text)
    room_name = extract_room_name(normalized)
    room_number = extract_room_number(normalized)
    area = extract_area(normalized)
    matched_types: list[str] = []
    if room_number:
        matched_types.append("room_number")
    if room_name:
        matched_types.append("room_name")
    if area is not None:
        matched_types.append("area")
    return RoomTextParse(
        source_index=source_index,
        raw_text=text.text,
        normalized_text=normalized,
        layer=text.layer,
        position=text.position,
        height=text.height,
        room_number=room_number,
        room_name=room_name,
        area=area,
        matched_types=matched_types,
    )


def extract_area(text: str) -> float | None:
    for line in _meaningful_lines(text):
        match = AREA_RE.search(line) or AREA_NO_UNIT_RE.search(line)
        if match:
            return float(match.group(1))
    return None


def extract_room_number(text: str) -> str | None:
    for line in _meaningful_lines(text):
        if _looks_like_area_line(line) or _looks_like_door_mark(line):
            continue
        match = ROOM_NUMBER_RE.search(line)
        if match:
            return match.group(0)
    return None


def extract_room_name(text: str) -> str | None:
    for line in _meaningful_lines(text):
        if _looks_like_area_line(line) or _looks_like_english(line):
            continue
        for keyword in sorted(ROOM_NAME_KEYWORDS, key=len, reverse=True):
            if keyword in line:
                return keyword
    return None


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _looks_like_area_line(line: str) -> bool:
    return bool(AREA_RE.search(line) or AREA_NO_UNIT_RE.search(line))


def _looks_like_english(line: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9()' /.-]+", line))


def _looks_like_door_mark(line: str) -> bool:
    return bool(re.fullmatch(r"[A-Z()]+D\d{3,4}", line) or re.fullmatch(r"[A-Z()]+PD\d{3,4}", line))
