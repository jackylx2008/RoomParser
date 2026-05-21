from __future__ import annotations

from pathlib import Path

import fitz

from room_extractor.models.pdf import PdfPageText, PdfTextExtraction, PdfTextItem


def extract_pdf_text(pdf_path: str | Path) -> PdfTextExtraction:
    """Extract vector words from a PDF using PyMuPDF."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    pages: list[PdfPageText] = []
    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            if page.rotation:
                page.set_rotation(0)
            rect = page.rect
            texts = [
                PdfTextItem(
                    page=page_index + 1,
                    text=str(word[4]).strip(),
                    bbox_pdf=(float(word[0]), float(word[1]), float(word[2]), float(word[3])),
                )
                for word in page.get_text("words")
                if str(word[4]).strip()
            ]
            pages.append(
                PdfPageText(
                    page=page_index + 1,
                    width=float(rect.width),
                    height=float(rect.height),
                    texts=texts,
                )
            )
    return PdfTextExtraction(source_file=path.name, pages=pages)
