from __future__ import annotations

from pathlib import Path

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.entity_filter import iter_modelspace_entities
from room_extractor.models.drawing import LayerAnalysis, LayerSummary


def analyze_layers(doc: DxfDrawing, source_file: str | Path = "", visible_only: bool = False) -> LayerAnalysis:
    """Count modelspace entities by layer and relevant DXF entity type."""
    layers: dict[str, LayerSummary] = {}
    for layer in doc.layers:
        name = layer.dxf.name
        layers.setdefault(name, LayerSummary(name=name))

    totals = LayerSummary(name="__total__")
    for entity in iter_modelspace_entities(doc, visible_only=visible_only):
        layer_name = getattr(entity.dxf, "layer", "0")
        summary = layers.setdefault(layer_name, LayerSummary(name=layer_name))
        _count_entity(summary, entity)
        _count_entity(totals, entity)

    return LayerAnalysis(
        source_file=Path(source_file).name if source_file else "",
        layers=sorted(layers.values(), key=lambda item: item.name.lower()),
        totals=totals,
    )


def _count_entity(summary: LayerSummary, entity: object) -> None:
    summary.entity_count += 1
    entity_type = entity.dxftype()
    if entity_type == "TEXT":
        summary.text_count += 1
    elif entity_type == "MTEXT":
        summary.mtext_count += 1
    elif entity_type == "INSERT":
        summary.insert_count += 1
    elif entity_type == "LWPOLYLINE":
        summary.lwpolyline_count += 1
        if bool(getattr(entity, "closed", False)):
            summary.closed_lwpolyline_count += 1
    elif entity_type == "POLYLINE":
        summary.polyline_count += 1
        if bool(getattr(entity, "is_closed", False)):
            summary.closed_polyline_count += 1
