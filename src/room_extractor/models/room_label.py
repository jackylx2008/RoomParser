from __future__ import annotations

from pydantic import BaseModel, Field

from room_extractor.models.drawing import BBox, Point
from room_extractor.models.issue import Issue


class RoomTextParse(BaseModel):
    """Parsed room-related fields from one CAD text entity."""

    source_index: int
    raw_text: str
    normalized_text: str
    layer: str
    position: Point
    height: float | None = None
    room_number: str | None = None
    room_name: str | None = None
    room_name_raw: str | None = None
    room_category: str | None = None
    area: float | None = None
    area_unit: str = "m2"
    matched_types: list[str] = Field(default_factory=list)


class RoomLabelCandidate(BaseModel):
    """Phase 2 room label candidate grouped from nearby CAD text."""

    candidate_id: str
    floor: str | None = None
    room_number: str | None = None
    room_name: str | None = None
    room_name_raw: str | None = None
    room_category: str | None = None
    area: float | None = None
    area_unit: str = "m2"
    center: Point
    bbox: BBox
    source_texts: list[RoomTextParse] = Field(default_factory=list)
    confidence: float = 0.0
    issues: list[Issue] = Field(default_factory=list)


class RoomLabelCandidateSet(BaseModel):
    """Phase 2 room_label_candidates.json payload."""

    source_file: str
    candidates: list[RoomLabelCandidate] = Field(default_factory=list)
    parsed_texts: list[RoomTextParse] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
