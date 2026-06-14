from __future__ import annotations

import re

from room_extractor.models.drawing import CadTextEntity
from room_extractor.models.room_label import RoomTextParse
from room_extractor.utils.text_normalizer import normalize_cad_text


AREA_RE = re.compile(r"(?:面积[:：]?\s*)?(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2|平方米)", re.IGNORECASE)
AREA_NO_UNIT_RE = re.compile(r"^面积[:：]?\s*(\d+(?:\.\d+)?)$")
ROOM_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]\.(?:L\d+|\d+)\.[A-Z]\d{3}(?:-[A-Z]\d{2})?|[A-Z]?\d{1,3}-\d{1,4}[A-Z]?|\d{2,4}[A-Z]?|[A-Z]{1,4}\d{1,3}(?:-[A-Z])?)(?![A-Za-z0-9])"
)
STAIR_ROOM_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])(?:E|C)-ST\d{1,3}(?![A-Za-z0-9])", re.IGNORECASE)
ROOM_CATEGORY_KEYWORDS = (
    "空调机房",
    "排油烟井",
    "排烟井",
    "加压送风井",
    "加压",
    "新风井",
    "回风",
    "办公室",
    "会议室",
    "贵宾室",
    "无障碍卫生间",
    "卫生间",
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
    "强电",
    "弱电",
    "风井",
    "水井",
    "走道",
    "通道",
    "前室",
    "大厅",
    "展厅",
)
ROOM_NAME_KEYWORDS = ROOM_CATEGORY_KEYWORDS


def parse_room_text(text: CadTextEntity, source_index: int = 0) -> RoomTextParse:
    """Parse room number, name and area from one CAD text entity."""
    normalized = normalize_cad_text(text.text)
    room_number = _best_room_number(text.text, normalized)
    inferred_stair = _is_stair_room_number(room_number)
    room_name = extract_room_name(normalized) or ("楼梯" if inferred_stair else None)
    room_category = extract_room_category(normalized) or ("楼梯" if inferred_stair else None)
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
        room_name_raw=room_name,
        room_category=room_category,
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
        if _looks_like_door_mark(line):
            continue
        if _looks_like_area_line(line) and not re.search(r"[A-Z]|\d+\s*-\s*\d+", line, re.IGNORECASE):
            continue
        stair_match = STAIR_ROOM_NUMBER_RE.search(line)
        if stair_match:
            return stair_match.group(0).upper()
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
                return _clean_room_name_line(line)
    return None


def extract_room_category(text: str) -> str | None:
    for line in _meaningful_lines(text):
        if _looks_like_area_line(line) or _looks_like_english(line):
            continue
        for keyword in sorted(ROOM_CATEGORY_KEYWORDS, key=len, reverse=True):
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


def _clean_room_name_line(line: str) -> str:
    cleaned = ROOM_NUMBER_RE.sub("", line)
    cleaned = STAIR_ROOM_NUMBER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -_/")


def _is_stair_room_number(room_number: str | None) -> bool:
    return bool(room_number and STAIR_ROOM_NUMBER_RE.fullmatch(room_number))


def _best_room_number(raw_text: str, normalized_text: str) -> str | None:
    raw_number = extract_room_number(raw_text)
    normalized_number = extract_room_number(normalized_text)
    if raw_number and normalized_number:
        return max((raw_number, normalized_number), key=len)
    return raw_number or normalized_number
