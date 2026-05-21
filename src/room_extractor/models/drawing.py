from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from room_extractor.models.issue import Issue


Point = tuple[float, float]
BBox = tuple[float, float, float, float]


class LayerSummary(BaseModel):
    """Entity counts for one DXF layer."""

    name: str
    entity_count: int = 0
    text_count: int = 0
    mtext_count: int = 0
    insert_count: int = 0
    lwpolyline_count: int = 0
    polyline_count: int = 0
    closed_lwpolyline_count: int = 0
    closed_polyline_count: int = 0


class LayerAnalysis(BaseModel):
    """DXF layer analysis output."""

    source_file: str
    layers: list[LayerSummary] = Field(default_factory=list)
    totals: LayerSummary


class CadTextEntity(BaseModel):
    """Raw TEXT/MTEXT entity extracted from DXF."""

    text: str
    entity_type: str
    layer: str
    position: Point
    height: float | None = None
    rotation: float = 0.0


class CadBlockEntity(BaseModel):
    """Raw INSERT entity and attributes extracted from DXF."""

    name: str
    layer: str
    position: Point
    attributes: dict[str, str] = Field(default_factory=dict)


class CadPolylineEntity(BaseModel):
    """Raw LWPOLYLINE/POLYLINE entity extracted from DXF."""

    layer: str
    entity_type: str
    closed: bool
    points: list[Point] = Field(default_factory=list)
    bbox: BBox | None = None
    area: float | None = None


class CadRawExtraction(BaseModel):
    """Phase 1 raw CAD extraction JSON."""

    source_file: str
    layers: list[LayerSummary] = Field(default_factory=list)
    texts: list[CadTextEntity] = Field(default_factory=list)
    blocks: list[CadBlockEntity] = Field(default_factory=list)
    polylines: list[CadPolylineEntity] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)


class Drawing(BaseModel):
    """Drawing metadata placeholder for later room extraction phases."""

    drawing_id: str | None = None
    source_file: str
    file_type: str = "dxf"
    metadata: dict[str, Any] = Field(default_factory=dict)

