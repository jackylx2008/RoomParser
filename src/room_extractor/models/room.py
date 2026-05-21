from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from room_extractor.models.confidence import Confidence
from room_extractor.models.geometry import Geometry
from room_extractor.models.issue import Issue


class BasicInfo(BaseModel):
    """Basic room fields extracted from CAD/PDF/manual review."""

    floor: str | None = None
    room_number: str | None = None
    room_name: str | None = None
    room_type: str | None = None


class AreaInfo(BaseModel):
    """Room area from text and geometry calculation."""

    text_value: float | None = None
    calculated_value: float | None = None
    unit: str = "m2"
    deviation_percent: float | None = None


class Evidence(BaseModel):
    """Source references supporting a room result."""

    cad_source: dict[str, Any] = Field(default_factory=dict)
    pdf_source: dict[str, Any] = Field(default_factory=dict)


class ReviewState(BaseModel):
    """Current review state attached to a room."""

    required: bool = False
    status: str = "auto_passed"
    reviewer: str | None = None
    review_time: str | None = None
    changes: list[dict[str, Any]] = Field(default_factory=list)


class Room(BaseModel):
    """Final room result schema target."""

    room_uid: str
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    area: AreaInfo = Field(default_factory=AreaInfo)
    geometry: Geometry = Field(default_factory=Geometry)
    evidence: Evidence = Field(default_factory=Evidence)
    confidence: Confidence = Field(default_factory=Confidence)
    review: ReviewState = Field(default_factory=ReviewState)
    issues: list[Issue] = Field(default_factory=list)
    final_status: str = "draft"

