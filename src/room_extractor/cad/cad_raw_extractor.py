from __future__ import annotations

from pathlib import Path

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.axis_extractor import extract_axes
from room_extractor.cad.block_extractor import extract_blocks
from room_extractor.cad.layer_analyzer import analyze_layers
from room_extractor.cad.text_extractor import extract_texts
from room_extractor.cad.polyline_extractor import extract_polylines
from room_extractor.config.axis_rules import AxisLayerRules
from room_extractor.models.drawing import CadRawExtraction


def extract_cad_raw(
    doc: DxfDrawing,
    source_file: str | Path,
    axis_only: bool = False,
    axis_rules: AxisLayerRules | None = None,
) -> CadRawExtraction:
    """Build the Phase 1 cad_raw extraction payload."""
    layer_analysis = analyze_layers(doc, source_file)
    if axis_only:
        label_layers = axis_rules.axis_label_layers if axis_rules is not None else None
        axis_layers = axis_rules.axis_layers if axis_rules is not None else None
        texts, text_issues = extract_texts(doc, layers=label_layers)
        axes, axis_issues = extract_axes(doc, axis_layers=axis_layers)
        kept_layers = {*(axis_layers or []), *(label_layers or [])}
        return CadRawExtraction(
            source_file=Path(source_file).name,
            layers=[layer for layer in layer_analysis.layers if layer.name in kept_layers],
            texts=texts,
            blocks=[],
            polylines=[],
            axes=axes,
            issues=[*text_issues, *axis_issues],
        )

    texts, text_issues = extract_texts(doc)
    blocks, block_issues = extract_blocks(doc)
    polylines, polyline_issues = extract_polylines(doc)
    axes, axis_issues = extract_axes(doc)
    return CadRawExtraction(
        source_file=Path(source_file).name,
        layers=layer_analysis.layers,
        texts=texts,
        blocks=blocks,
        polylines=polylines,
        axes=axes,
        issues=[*text_issues, *block_issues, *polyline_issues, *axis_issues],
    )
