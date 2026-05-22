from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_AXIS_RULES_PATH = Path(__file__).with_name("axis_layer_rules.yaml")


@dataclass(frozen=True)
class AxisLayerRules:
    """Configured CAD layers used by axis-only extraction."""

    axis_layers: list[str] = field(default_factory=list)
    axis_label_layers: list[str] = field(default_factory=list)


def load_axis_layer_rules(path: str | Path | None = None) -> AxisLayerRules:
    """Load a small YAML list mapping without adding a runtime YAML dependency."""
    rules_path = Path(path) if path is not None else DEFAULT_AXIS_RULES_PATH
    if not rules_path.exists():
        raise FileNotFoundError(f"Axis layer rules file not found: {rules_path}")
    return _parse_axis_rules(rules_path.read_text(encoding="utf-8"))


def _parse_axis_rules(content: str) -> AxisLayerRules:
    values: dict[str, list[str]] = {"axis_layers": [], "axis_label_layers": []}
    current_key: str | None = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            key = line[:-1].strip()
            current_key = key if key in values else None
            continue
        stripped = line.strip()
        if current_key is not None and stripped.startswith("- "):
            values[current_key].append(stripped[2:].strip().strip("'\""))
    return AxisLayerRules(
        axis_layers=values["axis_layers"],
        axis_label_layers=values["axis_label_layers"],
    )
