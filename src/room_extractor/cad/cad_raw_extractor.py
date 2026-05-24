from __future__ import annotations

from pathlib import Path

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.axis_extractor import extract_axes
from room_extractor.cad.block_extractor import extract_blocks
from room_extractor.cad.column_extractor import extract_columns
from room_extractor.cad.layer_analyzer import analyze_layers
from room_extractor.cad.text_extractor import extract_texts
from room_extractor.cad.polyline_extractor import extract_polylines
from room_extractor.config.axis_rules import AxisLayerRules
from room_extractor.config.column_rules import ColumnLayerRules
from room_extractor.models.drawing import CadRawExtraction


def extract_cad_raw(
    doc: DxfDrawing,
    source_file: str | Path,
    axis_only: bool = False,
    axis_rules: AxisLayerRules | None = None,
    columns_only: bool = False,
    column_rules: ColumnLayerRules | None = None,
    visible_only: bool = False,
) -> CadRawExtraction:
    """Build the Phase 1 cad_raw extraction payload."""
    if axis_only and columns_only:
        raise ValueError("--axis-only and --columns-only cannot be used together.")
    layer_analysis = analyze_layers(doc, source_file, visible_only=visible_only)
    if axis_only:
        label_layers = axis_rules.axis_label_layers if axis_rules is not None else None
        axis_layers = axis_rules.axis_layers if axis_rules is not None else None
        texts, text_issues = extract_texts(doc, layers=label_layers, visible_only=visible_only)
        axes, axis_issues = extract_axes(doc, axis_layers=axis_layers, visible_only=visible_only)
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
    if columns_only:
        column_layers = column_rules.column_layers if column_rules is not None else None
        column_block_layers = column_rules.column_block_layers if column_rules is not None else None
        columns, column_issues = extract_columns(doc, column_rules=column_rules, visible_only=visible_only)
        kept_layers = {*(column_layers or []), *(column_block_layers or [])}
        return CadRawExtraction(
            source_file=Path(source_file).name,
            layers=[layer for layer in layer_analysis.layers if _matches_any_layer_rule(layer.name, kept_layers)],
            texts=[],
            blocks=[],
            polylines=[],
            axes=[],
            columns=columns,
            issues=column_issues,
        )

    texts, text_issues = extract_texts(doc, visible_only=visible_only)
    blocks, block_issues = extract_blocks(doc, visible_only=visible_only)
    polylines, polyline_issues = extract_polylines(doc, visible_only=visible_only)
    axes, axis_issues = extract_axes(doc, visible_only=visible_only)
    columns, column_issues = extract_columns(doc, visible_only=visible_only)
    return CadRawExtraction(
        source_file=Path(source_file).name,
        layers=layer_analysis.layers,
        texts=texts,
        blocks=blocks,
        polylines=polylines,
        axes=axes,
        columns=columns,
        issues=[*text_issues, *block_issues, *polyline_issues, *axis_issues, *column_issues],
    )


def _matches_any_layer_rule(layer: str, rules: set[str]) -> bool:
    if not rules:
        return False
    normalized = layer.upper()
    return any(
        normalized == rule.upper() or normalized.endswith(f"${rule.upper()}") or normalized.endswith(rule.upper())
        for rule in rules
    )
