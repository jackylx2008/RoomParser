from __future__ import annotations

from pydantic import BaseModel, Field


class Confidence(BaseModel):
    """Confidence scores for room extraction and downstream checking."""

    room_number: float = Field(default=0.0, ge=0.0, le=1.0)
    room_name: float = Field(default=0.0, ge=0.0, le=1.0)
    area: float = Field(default=0.0, ge=0.0, le=1.0)
    geometry: float = Field(default=0.0, ge=0.0, le=1.0)
    cad_pdf_consistency: float = Field(default=0.0, ge=0.0, le=1.0)
    overall: float = Field(default=0.0, ge=0.0, le=1.0)

