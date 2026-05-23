from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_COLUMN_RULES_PATH = Path(__file__).with_name("column_layer_rules.yaml")


@dataclass(frozen=True)
class ColumnLayerRules:
    """Configured CAD layers used by structure-column extraction."""

    column_layers: list[str] = field(default_factory=list)
    column_block_layers: list[str] = field(default_factory=list)
    column_entity_types: list[str] = field(default_factory=list)
    color_indices: list[int] = field(default_factory=list)
    hatch_patterns: list[str] = field(default_factory=list)
    solid_fill: bool | None = None
    min_area: float | None = None
    max_area: float | None = None
    max_width: float | None = None
    max_height: float | None = None
    expand_insert_virtual_entities: bool = True


def load_column_layer_rules(path: str | Path | None = None) -> ColumnLayerRules:
    """Load a small YAML list mapping without adding a runtime YAML dependency."""
    rules_path = Path(path) if path is not None else DEFAULT_COLUMN_RULES_PATH
    if not rules_path.exists():
        raise FileNotFoundError(f"Column layer rules file not found: {rules_path}")
    return _parse_column_rules(rules_path.read_text(encoding="utf-8"))


def _parse_column_rules(content: str) -> ColumnLayerRules:
    list_values: dict[str, list[str]] = {
        "column_layers": [],
        "column_block_layers": [],
        "column_entity_types": [],
        "color_indices": [],
        "hatch_patterns": [],
    }
    scalar_values: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            key = line[:-1].strip()
            current_key = key if key in list_values else None
            continue
        if not raw_line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            current_key = None
            scalar_values[key.strip()] = value.strip().strip("'\"")
            continue
        stripped = line.strip()
        if current_key is not None and stripped.startswith("- "):
            list_values[current_key].append(stripped[2:].strip().strip("'\""))
    return ColumnLayerRules(
        column_layers=list_values["column_layers"],
        column_block_layers=list_values["column_block_layers"],
        column_entity_types=[item.upper() for item in list_values["column_entity_types"]],
        color_indices=[int(item) for item in list_values["color_indices"] if _is_int(item)],
        hatch_patterns=[item.upper() for item in list_values["hatch_patterns"]],
        solid_fill=_parse_bool(scalar_values.get("solid_fill")),
        min_area=_parse_float(scalar_values.get("min_area")),
        max_area=_parse_float(scalar_values.get("max_area")),
        max_width=_parse_float(scalar_values.get("max_width")),
        max_height=_parse_float(scalar_values.get("max_height")),
        expand_insert_virtual_entities=_parse_bool(scalar_values.get("expand_insert_virtual_entities")) is not False,
    )


def _is_int(value: str) -> bool:
    try:
        int(value)
    except ValueError:
        return False
    return True


def _parse_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None
