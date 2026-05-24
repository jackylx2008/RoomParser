from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from room_extractor.models.drawing import BBox, Point
from room_extractor.models.issue import Issue
from room_extractor.models.room_label import RoomLabelCandidate


class RoomBoundaryCandidate(BaseModel):
    """Closed CAD polyline that may represent a room boundary."""

    boundary_id: str
    source_polyline_index: int
    layer: str
    entity_type: str
    polygon_cad: list[Point] = Field(default_factory=list)
    bbox_cad: BBox
    area_cad: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoomCandidate(BaseModel):
    """Phase 3 room candidate with a label and optional matched boundary."""

    room_candidate_id: str
    floor: str | None = None
    room_number: str | None = None
    room_name: str | None = None
    area_text: float | None = None
    area_unit: str = "m2"
    label_center: Point
    label_bbox: BBox
    boundary: RoomBoundaryCandidate | None = None
    match_method: str = "point_in_polygon_smallest_area"
    status: str = "auto_failed"
    confidence: float = 0.0
    label: RoomLabelCandidate
    issues: list[Issue] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoomCandidateSet(BaseModel):
    """Phase 3 room_candidates.json payload."""

    source_file: str
    label_source_file: str
    summary: dict[str, Any] = Field(default_factory=dict)
    boundary_candidates: list[RoomBoundaryCandidate] = Field(default_factory=list)
    room_candidates: list[RoomCandidate] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
