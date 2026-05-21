from __future__ import annotations

from pydantic import BaseModel, Field

from room_extractor.models.drawing import BBox


class PdfTextItem(BaseModel):
    """One vector text item extracted from a PDF page."""

    page: int
    text: str
    bbox_pdf: BBox


class PdfPageText(BaseModel):
    """Vector text extracted from one PDF page."""

    page: int
    width: float
    height: float
    texts: list[PdfTextItem] = Field(default_factory=list)


class PdfTextExtraction(BaseModel):
    """PDF vector text extraction payload."""

    source_file: str
    pages: list[PdfPageText] = Field(default_factory=list)
