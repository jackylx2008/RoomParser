from __future__ import annotations

from pydantic import BaseModel, Field


Point = tuple[float, float]
BBox = tuple[float, float, float, float]


class Geometry(BaseModel):
    """Room geometry in CAD/PDF coordinate systems."""

    polygon_cad: list[Point] = Field(default_factory=list)
    bbox_cad: BBox | None = None
    polygon_pdf: list[Point] = Field(default_factory=list)
    bbox_pdf: BBox | None = None
    coordinate_unit: str = "mm"
    geometry_source: str = "cad_auto"

