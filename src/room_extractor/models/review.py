from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReviewChange(BaseModel):
    """Single manual review field change."""

    field: str
    before: Any = None
    after: Any = None
    reason: str | None = None


class ReviewRecord(BaseModel):
    """Manual review audit record."""

    review_id: str
    room_uid: str
    review_type: str
    reviewer: str | None = None
    review_time: str | None = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    changes: list[ReviewChange] = Field(default_factory=list)
    review_image: str | None = None
    manual_polygon_file: str | None = None
    status: str = "pending_manual_review"

