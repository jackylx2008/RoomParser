from __future__ import annotations

import math

from room_extractor.models.drawing import CadRawExtraction
from room_extractor.models.issue import Issue
from room_extractor.models.room_label import RoomLabelCandidate, RoomLabelCandidateSet, RoomTextParse
from room_extractor.extraction.room_text_parser import parse_room_text
from room_extractor.utils.text_normalizer import normalize_cad_text


def build_room_label_candidates(cad_raw: CadRawExtraction, floor: str | None = None) -> RoomLabelCandidateSet:
    """Build Phase 2 room label candidates from Phase 1 CAD raw text."""
    parsed = [parse_room_text(text, index) for index, text in enumerate(cad_raw.texts)]
    relevant = [item for item in parsed if item.matched_types]
    groups = _cluster_texts(relevant)
    candidates = [
        _build_candidate(index=index + 1, source_file=cad_raw.source_file, group=group, floor=floor)
        for index, group in enumerate(groups)
    ]
    candidates = [candidate for candidate in candidates if _has_room_label_signal(candidate)]
    source_stem = _source_stem(cad_raw.source_file)
    candidates = [
        candidate.model_copy(update={"candidate_id": f"{source_stem}_label_{index:04d}"})
        for index, candidate in enumerate(candidates, start=1)
    ]
    return RoomLabelCandidateSet(source_file=cad_raw.source_file, candidates=candidates, parsed_texts=parsed)


def _cluster_texts(texts: list[RoomTextParse]) -> list[list[RoomTextParse]]:
    if not texts:
        return []
    sorted_texts = sorted(texts, key=lambda item: (item.layer, item.position[0], item.position[1]))
    groups: list[list[RoomTextParse]] = []
    for text in sorted_texts:
        target = _find_nearest_group(text, groups)
        if target is None:
            groups.append([text])
        else:
            target.append(text)
    return [subgroup for group in groups for subgroup in _split_multi_room_group(group)]


def _split_multi_room_group(group: list[RoomTextParse]) -> list[list[RoomTextParse]]:
    room_number_texts = [item for item in group if item.room_number]
    room_numbers = {item.room_number for item in room_number_texts if item.room_number}
    if len(room_numbers) <= 1:
        return [group]

    subgroups: list[list[RoomTextParse]] = [[seed] for seed in room_number_texts]
    assigned = {id(seed) for seed in room_number_texts}
    for text in group:
        if id(text) in assigned:
            continue
        nearest_index = min(range(len(room_number_texts)), key=lambda index: _distance(text, room_number_texts[index]))
        nearest_seed = room_number_texts[nearest_index]
        if _distance(text, nearest_seed) <= _cluster_threshold([text, nearest_seed]):
            subgroups[nearest_index].append(text)
        else:
            subgroups.append([text])
    return subgroups


def _find_nearest_group(text: RoomTextParse, groups: list[list[RoomTextParse]]) -> list[RoomTextParse] | None:
    best_group: list[RoomTextParse] | None = None
    best_distance = math.inf
    for group in groups:
        threshold = _cluster_threshold([*group, text])
        distance = min(_distance(text, item) for item in group)
        if distance <= threshold and distance < best_distance:
            best_group = group
            best_distance = distance
    return best_group


def _cluster_threshold(group: list[RoomTextParse]) -> float:
    heights = [item.height for item in group if item.height]
    height = sorted(heights)[len(heights) // 2] if heights else 400.0
    return max(height * 5.0, 2500.0)


def _distance(left: RoomTextParse, right: RoomTextParse) -> float:
    dx = left.position[0] - right.position[0]
    dy = left.position[1] - right.position[1]
    return math.hypot(dx, dy)


def _build_candidate(index: int, source_file: str, group: list[RoomTextParse], floor: str | None) -> RoomLabelCandidate:
    ordered = sorted(group, key=lambda item: (-len(item.matched_types), item.source_index))
    room_number = _first_value(ordered, "room_number")
    room_name = _first_value(ordered, "room_name")
    room_name_raw = _first_value(ordered, "room_name_raw")
    room_category = _first_value(ordered, "room_category")
    area = _first_value(ordered, "area")
    bbox = _bbox(group)
    center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
    issues = _candidate_issues(room_number, room_name, area)
    confidence = _candidate_confidence(room_number, room_name, area)
    return RoomLabelCandidate(
        candidate_id=f"{_source_stem(source_file)}_label_{index:04d}",
        floor=floor,
        room_number=room_number,
        room_name=room_name,
        room_name_raw=room_name_raw,
        room_category=room_category,
        area=area,
        center=center,
        bbox=bbox,
        source_texts=sorted(group, key=lambda item: item.source_index),
        confidence=confidence,
        issues=issues,
    )


def _first_value(group: list[RoomTextParse], field: str):
    for item in group:
        value = getattr(item, field)
        if value is not None:
            return value
    return None


def _bbox(group: list[RoomTextParse]) -> tuple[float, float, float, float]:
    xs = [item.position[0] for item in group]
    ys = [item.position[1] for item in group]
    pad = max([item.height or 0.0 for item in group] + [100.0])
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _candidate_issues(room_number: str | None, room_name: str | None, area: float | None) -> list[Issue]:
    issues: list[Issue] = []
    if not room_number:
        issues.append(Issue(issue_code="ROOM_NUMBER_MISSING", severity="medium", field="room_number", message="未识别到房号"))
    if not room_name:
        issues.append(Issue(issue_code="ROOM_NAME_MISSING", severity="medium", field="room_name", message="未识别到房间名称"))
    if area is None:
        issues.append(Issue(issue_code="AREA_MISSING", severity="medium", field="area", message="未识别到面积"))
    return issues


def _candidate_confidence(room_number: str | None, room_name: str | None, area: float | None) -> float:
    score = 0.0
    if room_number:
        score += 0.3
    if room_name:
        score += 0.4
    if area is not None:
        score += 0.3
    return round(score, 2)


def _has_room_label_signal(candidate: RoomLabelCandidate) -> bool:
    return candidate.room_name is not None or (candidate.room_number is not None and candidate.area is not None)


def _source_stem(source_file: str) -> str:
    return normalize_cad_text(source_file).rsplit(".", 1)[0].replace(" ", "_")
