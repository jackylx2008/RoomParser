from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from room_extractor.extraction.room_json_builder import RoomsAutoBuild
from room_extractor.extraction.room_text_parser import extract_area, extract_room_name, extract_room_number
from room_extractor.models.drawing import BBox
from room_extractor.models.issue import Issue
from room_extractor.models.pdf import PdfPageText, PdfTextExtraction, PdfTextItem
from room_extractor.models.room import Room
from room_extractor.pdf.pdf_text_extractor import extract_pdf_text


class RoomsPdfCheck(BaseModel):
    """Phase 5 rooms_pdf_checked.json payload."""

    source_file: str
    pdf_source_file: str
    summary: dict[str, object] = Field(default_factory=dict)
    transform: dict[str, object] = Field(default_factory=dict)
    rooms: list[Room] = Field(default_factory=list)
    pdf_text: PdfTextExtraction
    issues: list[Issue] = Field(default_factory=list)


class CadPdfLinearTransform(BaseModel):
    """Simple CAD-to-PDF linear fit for one page."""

    cad_bbox: BBox
    pdf_bbox: BBox
    page: int
    method: str = "linear_fit_unverified"

    def cad_bbox_to_pdf(self, bbox: BBox) -> BBox:
        cad_min_x, cad_min_y, cad_max_x, cad_max_y = self.cad_bbox
        pdf_min_x, pdf_min_y, pdf_max_x, pdf_max_y = self.pdf_bbox
        cad_width = max(cad_max_x - cad_min_x, 1.0)
        cad_height = max(cad_max_y - cad_min_y, 1.0)
        pdf_width = pdf_max_x - pdf_min_x
        pdf_height = pdf_max_y - pdf_min_y
        x0 = pdf_min_x + (bbox[0] - cad_min_x) / cad_width * pdf_width
        x1 = pdf_min_x + (bbox[2] - cad_min_x) / cad_width * pdf_width
        y0 = pdf_max_y - (bbox[3] - cad_min_y) / cad_height * pdf_height
        y1 = pdf_max_y - (bbox[1] - cad_min_y) / cad_height * pdf_height
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def check_rooms_against_pdf(
    rooms_auto: RoomsAutoBuild,
    pdf_path: str | Path,
    page_number: int = 1,
    margin_ratio: float = 0.2,
) -> RoomsPdfCheck:
    """Check CAD-derived rooms against vector PDF text in mapped bboxes."""
    pdf_text = extract_pdf_text(pdf_path)
    page = _get_page(pdf_text, page_number)
    transform = _build_transform(rooms_auto.rooms, page)
    rooms = [
        _check_room(room, page, transform, pdf_source_file=pdf_text.source_file, margin_ratio=margin_ratio)
        for room in rooms_auto.rooms
    ]
    top_issues: list[Issue] = []
    if transform is None:
        top_issues.append(
            Issue(
                issue_code="CAD_PDF_MAPPING_FAILED",
                severity="high",
                field="geometry",
                message="缺少 CAD geometry，无法建立 CAD 到 PDF 的线性映射",
                need_manual_review=True,
            )
        )
    else:
        top_issues.append(
            Issue(
                issue_code="CAD_PDF_MAPPING_UNVERIFIED",
                severity="warning",
                field="geometry",
                message="当前 CAD/PDF 坐标映射为外接范围线性拟合，尚未通过锚点或人工校准",
                need_manual_review=False,
            )
        )
    return RoomsPdfCheck(
        source_file=rooms_auto.source_file,
        pdf_source_file=pdf_text.source_file,
        summary=_summary(rooms),
        transform=transform.model_dump(mode="json") if transform else {},
        rooms=rooms,
        pdf_text=pdf_text,
        issues=top_issues,
    )


def _check_room(
    room: Room,
    page: PdfPageText,
    transform: CadPdfLinearTransform | None,
    pdf_source_file: str,
    margin_ratio: float,
) -> Room:
    checked = room.model_copy(deep=True)
    if transform is None or checked.geometry.bbox_cad is None:
        checked.issues.append(
            Issue(
                issue_code="PDF_CHECK_SKIPPED_NO_CAD_GEOMETRY",
                severity="medium",
                field="geometry",
                message="房间缺少 CAD bbox，跳过 PDF bbox 文本校核",
                need_manual_review=True,
            )
        )
        checked.review.required = True
        checked.review.status = "pending_downstream_check"
        return checked
    bbox_pdf = _expand_bbox(transform.cad_bbox_to_pdf(checked.geometry.bbox_cad), margin_ratio, page.width, page.height)
    local_text_items = _texts_in_bbox(page.texts, bbox_pdf)
    local_text = "\n".join(item.text for item in local_text_items)
    checked.geometry.bbox_pdf = bbox_pdf
    checked.evidence.pdf_source = {
        "file": pdf_source_file,
        "page": page.page,
        "bbox_pdf": bbox_pdf,
        "local_text": local_text,
        "text_count": len(local_text_items),
    }
    if not local_text_items:
        checked.issues.append(
            Issue(
                issue_code="PDF_TEXT_NOT_FOUND_IN_ROOM_BBOX",
                severity="medium",
                field="pdf_source",
                message="映射后的 PDF bbox 内未找到矢量文字",
                need_manual_review=True,
            )
        )
        checked.review.required = True
        checked.review.status = "pending_downstream_check"
        return checked
    _compare_pdf_fields(checked, local_text)
    checked.confidence.cad_pdf_consistency = _cad_pdf_consistency(checked)
    checked.confidence.overall = round(
        checked.confidence.overall * 0.75 + checked.confidence.cad_pdf_consistency * 0.25,
        3,
    )
    if any(issue.need_manual_review for issue in checked.issues):
        checked.review.required = True
        checked.review.status = "pending_downstream_check"
    return checked


def _compare_pdf_fields(room: Room, local_text: str) -> None:
    pdf_room_number = extract_room_number(local_text)
    pdf_room_name = extract_room_name(local_text)
    pdf_area = extract_area(local_text)
    if room.basic_info.room_number and pdf_room_number and room.basic_info.room_number != pdf_room_number:
        room.issues.append(
            Issue(
                issue_code="PDF_ROOM_NUMBER_MISMATCH",
                severity="medium",
                field="room_number",
                cad_value=room.basic_info.room_number,
                pdf_value=pdf_room_number,
                message="CAD 房号与 PDF 局部文字不一致",
                need_manual_review=True,
            )
        )
    if room.basic_info.room_name and pdf_room_name and room.basic_info.room_name != pdf_room_name:
        room.issues.append(
            Issue(
                issue_code="PDF_ROOM_NAME_MISMATCH",
                severity="medium",
                field="room_name",
                cad_value=room.basic_info.room_name,
                pdf_value=pdf_room_name,
                message="CAD 房名与 PDF 局部文字不一致",
                need_manual_review=True,
            )
        )
    if room.area.text_value is not None and pdf_area is not None:
        deviation = abs(room.area.text_value - pdf_area) / max(room.area.text_value, 1.0) * 100.0
        if deviation > 5.0:
            room.issues.append(
                Issue(
                    issue_code="PDF_AREA_MISMATCH",
                    severity="medium",
                    field="area",
                    cad_value=room.area.text_value,
                    pdf_value=pdf_area,
                    message=f"CAD 面积文字与 PDF 局部面积文字偏差 {deviation:.2f}%",
                    need_manual_review=True,
                )
            )


def _cad_pdf_consistency(room: Room) -> float:
    blocking = {
        "PDF_ROOM_NUMBER_MISMATCH",
        "PDF_ROOM_NAME_MISMATCH",
        "PDF_AREA_MISMATCH",
        "PDF_TEXT_NOT_FOUND_IN_ROOM_BBOX",
    }
    if any(issue.issue_code in blocking for issue in room.issues):
        return 0.35
    return 0.75


def _build_transform(rooms: list[Room], page: PdfPageText) -> CadPdfLinearTransform | None:
    bboxes = [room.geometry.bbox_cad for room in rooms if room.geometry.bbox_cad is not None]
    if not bboxes:
        return None
    cad_bbox = (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )
    return CadPdfLinearTransform(cad_bbox=cad_bbox, pdf_bbox=(0.0, 0.0, page.width, page.height), page=page.page)


def _get_page(pdf_text: PdfTextExtraction, page_number: int) -> PdfPageText:
    for page in pdf_text.pages:
        if page.page == page_number:
            return page
    raise ValueError(f"PDF page not found: {page_number}")


def _texts_in_bbox(texts: list[PdfTextItem], bbox: BBox) -> list[PdfTextItem]:
    return [item for item in texts if _bbox_intersects(item.bbox_pdf, bbox)]


def _bbox_intersects(left: BBox, right: BBox) -> bool:
    return not (left[2] < right[0] or left[0] > right[2] or left[3] < right[1] or left[1] > right[3])


def _expand_bbox(bbox: BBox, ratio: float, page_width: float, page_height: float) -> BBox:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    pad_x = width * ratio
    pad_y = height * ratio
    return (
        max(0.0, bbox[0] - pad_x),
        max(0.0, bbox[1] - pad_y),
        min(page_width, bbox[2] + pad_x),
        min(page_height, bbox[3] + pad_y),
    )


def _summary(rooms: list[Room]) -> dict[str, object]:
    issue_counts: dict[str, int] = {}
    for room in rooms:
        for issue in room.issues:
            issue_counts[issue.issue_code] = issue_counts.get(issue.issue_code, 0) + 1
    return {
        "room_count": len(rooms),
        "checked_with_pdf_bbox": sum(1 for room in rooms if room.geometry.bbox_pdf is not None),
        "pdf_review_required": sum(1 for room in rooms if room.review.required),
        "issue_counts": issue_counts,
    }
