from __future__ import annotations

from pathlib import Path

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.block_extractor import extract_blocks
from room_extractor.cad.layer_analyzer import analyze_layers
from room_extractor.cad.text_extractor import extract_texts
from room_extractor.cad.polyline_extractor import extract_polylines
from room_extractor.models.drawing import CadRawExtraction


def extract_cad_raw(doc: DxfDrawing, source_file: str | Path) -> CadRawExtraction:
    """Build the Phase 1 cad_raw extraction payload."""
    layer_analysis = analyze_layers(doc, source_file)
    texts, text_issues = extract_texts(doc)
    blocks, block_issues = extract_blocks(doc)
    polylines, polyline_issues = extract_polylines(doc)
    return CadRawExtraction(
        source_file=Path(source_file).name,
        layers=layer_analysis.layers,
        texts=texts,
        blocks=blocks,
        polylines=polylines,
        issues=[*text_issues, *block_issues, *polyline_issues],
    )

