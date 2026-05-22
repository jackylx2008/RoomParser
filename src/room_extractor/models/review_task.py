from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from room_extractor.models.drawing import BBox
from room_extractor.models.geometry import Point
from room_extractor.models.issue import Issue


class ReviewTask(BaseModel):
    """One room task for formal manual review."""

    task_id: str
    room_uid: str
    floor: str | None = None
    room_number: str | None = None
    room_name: str | None = None
    room_type: str | None = None
    area_text_value: float | None = None
    area_calculated_value: float | None = None
    area_unit: str = "m2"
    confidence: dict[str, float] = Field(default_factory=dict)
    priority: str = "medium"
    reasons: list[str] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    cad_source: dict[str, Any] = Field(default_factory=dict)
    pdf_source: dict[str, Any] = Field(default_factory=dict)
    local_ai_check: dict[str, Any] = Field(default_factory=dict)
    review_image_path: str | None = None
    bbox_pdf: BBox | None = None
    bbox_cad: BBox | None = None
    polygon_cad: list[Point] = Field(default_factory=list)
    suggested_fields: list[str] = Field(default_factory=list)
    manual_input_schema: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending_manual_review"


class ReviewTaskSet(BaseModel):
    """Formal manual review task payload."""

    source_file: str
    rooms_source_file: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    tasks: list[ReviewTask] = Field(default_factory=list)
