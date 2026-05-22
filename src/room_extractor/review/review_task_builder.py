from __future__ import annotations

from collections import Counter
from typing import Any

from room_extractor.models.review_task import ReviewTask, ReviewTaskSet
from room_extractor.models.room import Room
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


HIGH_PRIORITY_ISSUES = {
    "CAD_GEOMETRY_MISSING",
    "CAD_PDF_MAPPING_FAILED",
    "PDF_CHECK_SKIPPED_NO_CAD_GEOMETRY",
    "PDF_REVIEW_IMAGE_SKIPPED_NO_BBOX",
    "LOCAL_AI_CHECK_FAILED",
    "LOCAL_AI_REVIEW_REQUIRED",
}


def build_review_tasks(rooms_ai_checked: RoomsPdfCheck) -> ReviewTaskSet:
    """Build formal manual review tasks after CAD/PDF/local-AI machine checks."""
    tasks = [
        _build_task(index=index + 1, room=room)
        for index, room in enumerate(rooms_ai_checked.rooms)
        if _requires_manual_review(room)
    ]
    return ReviewTaskSet(
        source_file=rooms_ai_checked.source_file,
        rooms_source_file=rooms_ai_checked.pdf_source_file,
        summary=_summary(rooms_ai_checked.rooms, tasks),
        tasks=tasks,
    )


def _requires_manual_review(room: Room) -> bool:
    ai_check = room.evidence.pdf_source.get("local_ai_check", {})
    return (
        room.review.required
        or any(issue.need_manual_review for issue in room.issues)
        or ai_check.get("needs_review") is True
        or ai_check.get("status") == "failed"
    )


def _build_task(index: int, room: Room) -> ReviewTask:
    pdf_source = room.evidence.pdf_source
    ai_check = dict(pdf_source.get("local_ai_check", {}))
    review_image = pdf_source.get("review_image", {})
    reasons = _reasons(room, ai_check)
    issue_codes = [issue.issue_code for issue in room.issues]
    return ReviewTask(
        task_id=f"review_task_{index:04d}",
        room_uid=room.room_uid,
        floor=room.basic_info.floor,
        room_number=room.basic_info.room_number,
        room_name=room.basic_info.room_name,
        room_type=room.basic_info.room_type,
        area_text_value=room.area.text_value,
        area_calculated_value=room.area.calculated_value,
        area_unit=room.area.unit,
        confidence=room.confidence.model_dump(mode="json"),
        priority=_priority(room, ai_check),
        reasons=reasons,
        issue_codes=issue_codes,
        issues=room.issues,
        cad_source=room.evidence.cad_source,
        pdf_source={
            "file": pdf_source.get("file"),
            "page": pdf_source.get("page"),
            "bbox_pdf": pdf_source.get("bbox_pdf"),
            "local_text": pdf_source.get("local_text"),
            "text_count": pdf_source.get("text_count"),
            "review_image": review_image,
        },
        local_ai_check=ai_check,
        review_image_path=review_image.get("path") if isinstance(review_image, dict) else None,
        bbox_pdf=room.geometry.bbox_pdf,
        bbox_cad=room.geometry.bbox_cad,
        polygon_cad=room.geometry.polygon_cad,
        suggested_fields=_suggested_fields(room, ai_check),
        manual_input_schema=_manual_input_schema(),
    )


def _reasons(room: Room, ai_check: dict[str, Any]) -> list[str]:
    reasons = [issue.message for issue in room.issues if issue.need_manual_review]
    if ai_check.get("status") == "failed":
        reasons.append(f"本地 AI 校验失败：{ai_check.get('message')}")
    elif ai_check.get("needs_review") is True:
        reasons.append(f"本地 AI 建议复核：{ai_check.get('notes')}")
    if not room.evidence.pdf_source.get("review_image"):
        reasons.append("缺少局部截图，需人工从原图定位确认")
    return _dedupe([reason for reason in reasons if reason])


def _priority(room: Room, ai_check: dict[str, Any]) -> str:
    issue_codes = {issue.issue_code for issue in room.issues}
    if issue_codes & HIGH_PRIORITY_ISSUES or ai_check.get("status") == "failed" or ai_check.get("visible") is False:
        return "high"
    if ai_check.get("needs_review") is True or any(issue.severity in {"high", "medium"} for issue in room.issues):
        return "medium"
    return "low"


def _suggested_fields(room: Room, ai_check: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    issue_map = {
        "ROOM_NUMBER_MISSING": "room_number",
        "PDF_ROOM_NUMBER_MISMATCH": "room_number",
        "ROOM_NAME_MISMATCH": "room_name",
        "PDF_ROOM_NAME_MISMATCH": "room_name",
        "AREA_MISSING": "area",
        "PDF_AREA_MISMATCH": "area",
        "CAD_AREA_DEVIATION_EXCEEDS_THRESHOLD": "area",
        "CAD_GEOMETRY_MISSING": "geometry",
        "PDF_CHECK_SKIPPED_NO_CAD_GEOMETRY": "geometry",
        "PDF_REVIEW_IMAGE_SKIPPED_NO_BBOX": "geometry",
        "SPECIAL_SPACE_NO_AREA_BOUNDARY": "geometry",
    }
    for issue in room.issues:
        field = issue_map.get(issue.issue_code, issue.field)
        if field:
            fields.append(str(field))
    if ai_check.get("room_number_match") is False:
        fields.append("room_number")
    if ai_check.get("room_name_match") is False:
        fields.append("room_name")
    if ai_check.get("area_match") is False:
        fields.append("area")
    if not room.geometry.polygon_cad:
        fields.append("geometry")
    return _dedupe(fields)


def _manual_input_schema() -> dict[str, Any]:
    return {
        "room_number": {"type": "string", "required": False},
        "room_name": {"type": "string", "required": False},
        "area": {"type": "number", "required": False, "unit": "m2"},
        "room_type": {"type": "string", "required": False},
        "polygon_cad": {"type": "array[point]", "required": False},
        "decision": {"type": "enum", "values": ["approve", "correct", "reject", "unresolved"], "required": True},
        "reason_code": {"type": "string", "required": True},
        "comment": {"type": "string", "required": False},
    }


def _summary(rooms: list[Room], tasks: list[ReviewTask]) -> dict[str, Any]:
    priority_counts = Counter(task.priority for task in tasks)
    field_counts = Counter(field for task in tasks for field in task.suggested_fields)
    issue_counts = Counter(code for task in tasks for code in task.issue_codes)
    ai_status_counts = Counter(str(task.local_ai_check.get("status")) for task in tasks if task.local_ai_check)
    ai_needs_review_counts = Counter(str(task.local_ai_check.get("needs_review")) for task in tasks if task.local_ai_check)
    return {
        "room_count": len(rooms),
        "task_count": len(tasks),
        "auto_pass_count": len(rooms) - len(tasks),
        "priority_counts": dict(priority_counts),
        "suggested_field_counts": dict(field_counts),
        "issue_counts": dict(issue_counts),
        "ai_status_counts": dict(ai_status_counts),
        "ai_needs_review_counts": dict(ai_needs_review_counts),
    }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
