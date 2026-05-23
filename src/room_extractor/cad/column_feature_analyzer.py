from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.column_extractor import (
    _points_from_hatch_path,
    _polygon_area,
    is_column_layer,
)
from room_extractor.config.column_rules import ColumnLayerRules
from room_extractor.geometry import calculate_bbox
from room_extractor.utils.text_normalizer import recover_gbk_mojibake

Point = tuple[float, float]


def analyze_column_features(
    doc: DxfDrawing,
    source_file: str | Path,
    column_rules: ColumnLayerRules,
    margin_ratio: float = 0.2,
) -> dict[str, Any]:
    """Summarize reusable DXF features from a verified column-only drawing."""
    entity_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    color_counts: Counter[str] = Counter()
    true_color_counts: Counter[str] = Counter()
    linetype_counts: Counter[str] = Counter()
    hatch_pattern_counts: Counter[str] = Counter()
    hatch_solid_fill_counts: Counter[str] = Counter()
    hatch_style_counts: Counter[str] = Counter()
    hatch_path_counts: Counter[str] = Counter()
    widths: list[float] = []
    heights: list[float] = []
    areas: list[float] = []

    entities = list(doc.modelspace())
    if column_rules.expand_insert_virtual_entities:
        for insert in doc.modelspace().query("INSERT"):
            try:
                entities.extend(insert.virtual_entities())
            except Exception:
                continue
    for entity in entities:
        layer = str(getattr(entity.dxf, "layer", "0"))
        if not is_column_layer(layer, column_rules=column_rules):
            continue
        entity_type = entity.dxftype()
        entity_counts[entity_type] += 1
        layer_counts[layer] += 1
        color_counts[str(getattr(entity.dxf, "color", None))] += 1
        true_color_counts[str(getattr(entity.dxf, "true_color", None))] += 1
        linetype_counts[str(getattr(entity.dxf, "linetype", None))] += 1
        if entity_type != "HATCH":
            continue
        hatch_pattern_counts[str(getattr(entity.dxf, "pattern_name", None))] += 1
        hatch_solid_fill_counts[str(getattr(entity.dxf, "solid_fill", None))] += 1
        hatch_style_counts[str(getattr(entity.dxf, "hatch_style", None))] += 1
        hatch_path_counts[str(len(getattr(entity, "paths", [])))] += 1
        points = _largest_hatch_path_points(entity)
        if not points:
            continue
        bbox = calculate_bbox(points)
        area = _polygon_area(points)
        if bbox is not None:
            widths.append(float(bbox[2] - bbox[0]))
            heights.append(float(bbox[3] - bbox[1]))
        if area is not None:
            areas.append(float(area))

    geometry = {
        "width": _number_stats(widths),
        "height": _number_stats(heights),
        "area": _number_stats(areas),
    }
    recommended = _recommended_rules(
        layer_counts=layer_counts,
        entity_counts=entity_counts,
        color_counts=color_counts,
        hatch_pattern_counts=hatch_pattern_counts,
        hatch_solid_fill_counts=hatch_solid_fill_counts,
        geometry=geometry,
        margin_ratio=margin_ratio,
    )
    return {
        "source_file": Path(source_file).name,
        "column_sample_count": len(areas),
        "entity_type_counts": dict(entity_counts),
        "layer_counts": dict(layer_counts),
        "normalized_layer_suffixes": sorted({_xref_suffix(layer) for layer in layer_counts}),
        "dxf_attributes": {
            "color_counts": dict(color_counts),
            "true_color_counts": dict(true_color_counts),
            "linetype_counts": dict(linetype_counts),
            "hatch_pattern_counts": dict(hatch_pattern_counts),
            "hatch_solid_fill_counts": dict(hatch_solid_fill_counts),
            "hatch_style_counts": dict(hatch_style_counts),
            "hatch_path_counts": dict(hatch_path_counts),
        },
        "geometry": geometry,
        "recommended_rules": recommended,
    }


def _largest_hatch_path_points(entity: object) -> list[Point]:
    candidates: list[list[Point]] = []
    for path in getattr(entity, "paths", []):
        points = _points_from_hatch_path(path)
        if len(points) >= 3:
            candidates.append(points)
    if not candidates:
        return []
    return max(candidates, key=lambda points: _polygon_area(points) or 0.0)


def _number_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p50": None, "p90": None, "p95": None, "p99": None, "max": None}
    sorted_values = sorted(values)
    return {
        "count": len(sorted_values),
        "min": sorted_values[0],
        "p50": _quantile(sorted_values, 0.50),
        "p90": _quantile(sorted_values, 0.90),
        "p95": _quantile(sorted_values, 0.95),
        "p99": _quantile(sorted_values, 0.99),
        "max": sorted_values[-1],
    }


def _quantile(sorted_values: list[float], q: float) -> float:
    index = int((len(sorted_values) - 1) * q)
    return sorted_values[index]


def _recommended_rules(
    layer_counts: Counter[str],
    entity_counts: Counter[str],
    color_counts: Counter[str],
    hatch_pattern_counts: Counter[str],
    hatch_solid_fill_counts: Counter[str],
    geometry: dict[str, dict[str, float | int | None]],
    margin_ratio: float,
) -> dict[str, Any]:
    max_width = _with_margin(geometry["width"]["max"], margin_ratio)
    max_height = _with_margin(geometry["height"]["max"], margin_ratio)
    max_area = _with_margin(geometry["area"]["max"], margin_ratio)
    return {
        "column_layers": sorted({_xref_suffix(layer) for layer in layer_counts}),
        "column_entity_types": [item for item, _ in entity_counts.most_common() if item == "HATCH"] or ["HATCH"],
        "color_indices": [int(item) for item, _ in color_counts.most_common(1) if item.isdigit()],
        "hatch_patterns": [item for item, _ in hatch_pattern_counts.most_common(1) if item not in {"None", ""}],
        "solid_fill": _solid_fill_value(hatch_solid_fill_counts),
        "max_width": max_width,
        "max_height": max_height,
        "max_area": max_area,
    }


def _with_margin(value: float | int | None, margin_ratio: float) -> float | None:
    if value is None:
        return None
    return float(value) * (1.0 + margin_ratio)


def _solid_fill_value(counter: Counter[str]) -> bool | None:
    if not counter:
        return None
    value, _ = counter.most_common(1)[0]
    if value in {"1", "True", "true"}:
        return True
    if value in {"0", "False", "false"}:
        return False
    return None


def _xref_suffix(layer: str) -> str:
    recovered = recover_gbk_mojibake(layer)
    suffix = recovered.rsplit("$", 1)[-1]
    return suffix or recovered
