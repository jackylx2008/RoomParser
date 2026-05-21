from __future__ import annotations

import re
from pathlib import Path

import fitz

from room_extractor.models.drawing import BBox
from room_extractor.models.issue import Issue
from room_extractor.models.pdf import PdfPageText, PdfTextItem
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


def render_review_images(
    rooms_pdf_checked: RoomsPdfCheck,
    pdf_path: str | Path,
    output_dir: str | Path,
    dpi: int = 200,
    margin_ratio: float = 0.2,
    only_review_required: bool = True,
) -> RoomsPdfCheck:
    """Render PDF crop images for rooms that need downstream review."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    rendered = rooms_pdf_checked.model_copy(deep=True)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered_count = 0
    anchor_crop_count = 0
    skipped_no_bbox = 0
    skipped_not_required = 0
    scale = max(dpi, 1) / 72.0
    pages_by_number = {page.page: page for page in rendered.pdf_text.pages}
    with fitz.open(path) as doc:
        for index, room in enumerate(rendered.rooms, start=1):
            if only_review_required and not room.review.required:
                skipped_not_required += 1
                continue
            bbox_pdf = room.geometry.bbox_pdf
            if bbox_pdf is None:
                skipped_no_bbox += 1
                room.issues.append(
                    Issue(
                        issue_code="PDF_REVIEW_IMAGE_SKIPPED_NO_BBOX",
                        severity="medium",
                        field="pdf_source",
                        message="房间缺少 PDF bbox，无法生成局部截图",
                        need_manual_review=True,
                    )
                )
                room.review.required = True
                room.review.status = "pending_downstream_check"
                continue
            page_number = int(room.evidence.pdf_source.get("page", 1) or 1)
            page = doc[page_number - 1]
            if page.rotation:
                page.set_rotation(0)
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            page_text = pages_by_number.get(page_number)
            anchor_bbox = _find_anchor_bbox(room_number=room.basic_info.room_number, page_text=page_text, fallback_center=bbox_pdf)
            crop_source = "pdf_bbox_crop"
            base_bbox = bbox_pdf
            if anchor_bbox is not None:
                base_bbox = _anchor_crop_bbox(anchor_bbox, bbox_pdf, page_width, page_height)
                crop_source = "pdf_text_anchor_crop"
                anchor_crop_count += 1
            crop_bbox = _ensure_minimum_bbox(
                _expand_bbox(base_bbox, margin_ratio, page_width, page_height),
                page_width,
                page_height,
            )
            image_path = out_dir / f"{index:04d}_{_safe_stem(room.room_uid)}.png"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=fitz.Rect(crop_bbox), alpha=False)
            pixmap.save(image_path)
            room.evidence.pdf_source["review_image"] = {
                "path": str(image_path),
                "pdf_page": page_number,
                "crop_bbox": crop_bbox,
                "dpi": dpi,
                "margin_ratio": margin_ratio,
                "source": crop_source,
            }
            rendered_count += 1
    rendered.summary = {
        **rendered.summary,
        "review_images_rendered": rendered_count,
        "review_images_anchor_crops": anchor_crop_count,
        "review_images_skipped_no_bbox": skipped_no_bbox,
        "review_images_skipped_not_required": skipped_not_required,
        "review_image_output_dir": str(out_dir),
        "review_image_dpi": dpi,
    }
    return rendered


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return (stem or "room")[:80]


def _find_anchor_bbox(room_number: str | None, page_text: PdfPageText | None, fallback_center: BBox) -> BBox | None:
    if not room_number or page_text is None:
        return None
    matches = [item for item in page_text.texts if item.text == room_number]
    if not matches:
        return None
    clusters = _cluster_text_items(matches, max_center_distance=16.0)
    fallback_x = (fallback_center[0] + fallback_center[2]) / 2.0
    fallback_y = (fallback_center[1] + fallback_center[3]) / 2.0
    return min(clusters, key=lambda bbox: _distance_squared(_bbox_center(bbox), (fallback_x, fallback_y)))


def _cluster_text_items(items: list[PdfTextItem], max_center_distance: float) -> list[BBox]:
    clusters: list[list[PdfTextItem]] = []
    for item in items:
        item_center = _bbox_center(item.bbox_pdf)
        for cluster in clusters:
            cluster_bbox = _union_bbox([cluster_item.bbox_pdf for cluster_item in cluster])
            if _distance_squared(item_center, _bbox_center(cluster_bbox)) <= max_center_distance * max_center_distance:
                cluster.append(item)
                break
        else:
            clusters.append([item])
    return [_union_bbox([item.bbox_pdf for item in cluster]) for cluster in clusters]


def _anchor_crop_bbox(anchor_bbox: BBox, fallback_bbox: BBox, page_width: float, page_height: float) -> BBox:
    anchor_x, anchor_y = _bbox_center(anchor_bbox)
    fallback_width = fallback_bbox[2] - fallback_bbox[0]
    fallback_height = fallback_bbox[3] - fallback_bbox[1]
    width = min(max(fallback_width, 100.0), page_width)
    height = min(max(fallback_height, 80.0), page_height)
    return _clamp_bbox(
        (
            anchor_x - width / 2.0,
            anchor_y - height / 2.0,
            anchor_x + width / 2.0,
            anchor_y + height / 2.0,
        ),
        page_width,
        page_height,
    )


def _union_bbox(bboxes: list[BBox]) -> BBox:
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _bbox_center(bbox: BBox) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _distance_squared(left: tuple[float, float], right: tuple[float, float]) -> float:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _expand_bbox(bbox: BBox, ratio: float, page_width: float, page_height: float) -> BBox:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    pad_x = width * ratio
    pad_y = height * ratio
    return _clamp_bbox(
        (
            bbox[0] - pad_x,
            bbox[1] - pad_y,
            bbox[2] + pad_x,
            bbox[3] + pad_y,
        ),
        page_width,
        page_height,
    )


def _clamp_bbox(bbox: BBox, page_width: float, page_height: float) -> BBox:
    return (
        max(0.0, bbox[0]),
        max(0.0, bbox[1]),
        min(page_width, bbox[2]),
        min(page_height, bbox[3]),
    )


def _ensure_minimum_bbox(bbox: BBox, page_width: float, page_height: float, min_size: float = 1.0) -> BBox:
    min_width = min(min_size, page_width)
    min_height = min(min_size, page_height)
    x0, y0, x1, y1 = bbox
    if x1 - x0 < min_width:
        center_x = (x0 + x1) / 2.0
        x0 = center_x - min_width / 2.0
        x1 = center_x + min_width / 2.0
    if y1 - y0 < min_height:
        center_y = (y0 + y1) / 2.0
        y0 = center_y - min_height / 2.0
        y1 = center_y + min_height / 2.0
    if x0 < 0.0:
        x1 -= x0
        x0 = 0.0
    if y0 < 0.0:
        y1 -= y0
        y0 = 0.0
    if x1 > page_width:
        x0 -= x1 - page_width
        x1 = page_width
    if y1 > page_height:
        y0 -= y1 - page_height
        y1 = page_height
    return _clamp_bbox((x0, y0, x1, y1), page_width, page_height)
