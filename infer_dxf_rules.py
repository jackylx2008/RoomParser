"""Infer axis extraction rules from one DXF and apply them to another DXF.

This is an experimental root-level entrypoint for migrating a manually curated
DXF extraction profile, such as an AXIS-only drawing, back to a full/exploded
DXF while preserving the existing cad_raw axis-only JSON structure.

For exploded target DXF files, validation is intentionally based on semantic
JSON content (`axes`, `texts`, `issues`). Layer summaries may differ because
block INSERTs from the source can become primitive entities in the target.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ezdxf.document import Drawing as DxfDrawing


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from room_extractor.cad import extract_cad_raw, load_dxf
from room_extractor.cad.axis_extractor import AXIS_ENTITY_TYPES
from room_extractor.cad.entity_filter import is_entity_visible
from room_extractor.config.axis_rules import AxisLayerRules
from room_extractor.utils.text_normalizer import recover_gbk_mojibake


DEFAULT_SOURCE_DXF = Path("data/input/dxf/L2_20.00m平面图-AXIS.dxf")
DEFAULT_TARGET_DXF = Path("data/input/dxf_exploded/L2_20.00m平面图.dxf")
DEFAULT_OUT = Path("data/output/json/cad_raw_axis_inferred_from_target.json")
DEFAULT_SOURCE_OUT = Path("data/output/json/cad_raw_axis_inferred_source_reference.json")
DEFAULT_RULES_OUT = Path("data/output/json/inferred_axis_rules_from_source.json")

TEXT_ENTITY_TYPES = {"TEXT", "MTEXT"}
AXIS_LAYER_MARKERS = ("AXIS", "GRID", "轴网", "轴线")
AXIS_LABEL_LAYER_MARKERS = ("ANNO", "AXIS", "GRID", "轴号", "轴网", "轴线")


@dataclass(frozen=True)
class LayerProfile:
    name: str
    normalized_name: str
    suffix: str
    is_off: bool
    is_frozen: bool
    is_locked: bool
    color: int | None
    true_color: int | None
    linetype: str | None
    lineweight: int | None

    def fingerprint(self) -> tuple[Any, ...]:
        return (self.color, self.true_color, _norm_text(self.linetype), self.is_off, self.is_frozen, self.is_locked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "suffix": self.suffix,
            "is_off": self.is_off,
            "is_frozen": self.is_frozen,
            "is_locked": self.is_locked,
            "color": self.color,
            "true_color": self.true_color,
            "linetype": self.linetype,
            "lineweight": self.lineweight,
        }


@dataclass
class RoleLayer:
    profile: LayerProfile
    entity_counts: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        payload = self.profile.to_dict()
        payload["entity_counts"] = dict(sorted(self.entity_counts.items()))
        return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Infer axis layer rules from a source DXF and apply them to a target DXF, "
            "writing cad_raw axis-only JSON with the existing extractor. For exploded "
            "targets, validation checks semantic JSON equality instead of layer statistics."
        )
    )
    parser.add_argument("--source-dxf", default=str(DEFAULT_SOURCE_DXF), help="Curated source DXF used to infer rules.")
    parser.add_argument("--target-dxf", default=str(DEFAULT_TARGET_DXF), help="Target DXF to extract with inferred rules.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output cad_raw JSON extracted from the target DXF.")
    parser.add_argument("--source-out", default=str(DEFAULT_SOURCE_OUT), help="Optional source reference cad_raw JSON path.")
    parser.add_argument("--rules-out", default=str(DEFAULT_RULES_OUT), help="Output inferred rules/profile JSON path.")
    parser.add_argument("--visible-only", action="store_true", help="Ignore off/frozen/invisible entities while inferring and extracting.")
    parser.add_argument("--no-source-out", action="store_true", help="Do not write source reference cad_raw JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_dxf = Path(args.source_dxf)
    target_dxf = Path(args.target_dxf)
    out_path = Path(args.out)
    rules_out = Path(args.rules_out)
    source_out = None if args.no_source_out else Path(args.source_out)

    source_doc = load_dxf(source_dxf)
    target_doc = load_dxf(target_dxf)
    inferred = infer_axis_rules(source_doc, target_doc, visible_only=bool(args.visible_only))
    axis_rules = AxisLayerRules(
        axis_layers=inferred["target_rules"]["axis_layers"],
        axis_label_layers=inferred["target_rules"]["axis_label_layers"],
    )

    target_raw = extract_cad_raw(
        target_doc,
        target_dxf,
        axis_only=True,
        axis_rules=axis_rules,
        visible_only=bool(args.visible_only),
    )
    _write_json(out_path, target_raw.model_dump(mode="json"))

    source_axis_rules = AxisLayerRules(
        axis_layers=inferred["source_rules"]["axis_layers"],
        axis_label_layers=inferred["source_rules"]["axis_label_layers"],
    )
    source_raw = extract_cad_raw(
        source_doc,
        source_dxf,
        axis_only=True,
        axis_rules=source_axis_rules,
        visible_only=bool(args.visible_only),
    )
    if source_out is not None:
        _write_json(source_out, source_raw.model_dump(mode="json"))

    validation = _compare_axis_payloads(source_raw.model_dump(mode="json"), target_raw.model_dump(mode="json"))
    summary = {
        "source_dxf": str(source_dxf),
        "target_dxf": str(target_dxf),
        "visible_only": bool(args.visible_only),
        "source_json": str(source_out) if source_out is not None else None,
        "target_json": str(out_path),
        "source_axis_layers": inferred["source_rules"]["axis_layers"],
        "source_axis_label_layers": inferred["source_rules"]["axis_label_layers"],
        "target_axis_layers": inferred["target_rules"]["axis_layers"],
        "target_axis_label_layers": inferred["target_rules"]["axis_label_layers"],
        "source_axis_count": len(source_raw.axes),
        "source_text_count": len(source_raw.texts),
        "target_axis_count": len(target_raw.axes),
        "target_text_count": len(target_raw.texts),
        "target_layer_count": len(target_raw.layers),
        "validation": validation,
    }
    inferred["summary"] = summary
    _write_json(rules_out, inferred)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def infer_axis_rules(source_doc: DxfDrawing, target_doc: DxfDrawing, visible_only: bool = False) -> dict[str, Any]:
    source_profiles = _layer_profiles(source_doc)
    target_profiles = _layer_profiles(target_doc)
    source_counts = _entity_counts_by_layer(source_doc, visible_only=visible_only)
    target_counts = _entity_counts_by_layer(target_doc, visible_only=visible_only)

    source_axis_layers = _source_role_layers(source_profiles, source_counts, role="axis")
    source_label_layers = _source_role_layers(source_profiles, source_counts, role="label")
    target_axis_layers, axis_matches = _match_target_layers(source_axis_layers, target_profiles, target_counts, role="axis")
    target_label_layers, label_matches = _match_target_layers(source_label_layers, target_profiles, target_counts, role="label")

    return {
        "source_rules": {
            "axis_layers": [item.profile.name for item in source_axis_layers],
            "axis_label_layers": [item.profile.name for item in source_label_layers],
        },
        "target_rules": {
            "axis_layers": target_axis_layers,
            "axis_label_layers": target_label_layers,
        },
        "source_profiles": {
            "axis_layers": [item.to_dict() for item in source_axis_layers],
            "axis_label_layers": [item.to_dict() for item in source_label_layers],
        },
        "target_matches": {
            "axis_layers": axis_matches,
            "axis_label_layers": label_matches,
        },
    }


def _source_role_layers(
    profiles: dict[str, LayerProfile],
    counts_by_layer: dict[str, Counter[str]],
    role: str,
) -> list[RoleLayer]:
    role_layers: list[RoleLayer] = []
    for layer, counts in counts_by_layer.items():
        if role == "axis" and not any(counts.get(entity_type, 0) for entity_type in AXIS_ENTITY_TYPES):
            continue
        if role == "label" and not any(counts.get(entity_type, 0) for entity_type in TEXT_ENTITY_TYPES):
            continue
        role_layers.append(RoleLayer(profile=profiles[layer], entity_counts=counts))
    semantic_layers = [item for item in role_layers if _looks_like_role_layer(item.profile.name, role)]
    selected_layers = semantic_layers or role_layers
    return sorted(selected_layers, key=lambda item: item.profile.normalized_name)


def _looks_like_role_layer(layer: str, role: str) -> bool:
    values = _layer_text_values(layer)
    if role == "axis":
        return any(marker in value for value in values for marker in AXIS_LAYER_MARKERS)
    return any(marker in value for value in values for marker in AXIS_LABEL_LAYER_MARKERS)


def _match_target_layers(
    source_layers: list[RoleLayer],
    target_profiles: dict[str, LayerProfile],
    target_counts: dict[str, Counter[str]],
    role: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    target_by_normalized = {profile.normalized_name: profile for profile in target_profiles.values()}
    target_by_suffix: dict[str, list[LayerProfile]] = defaultdict(list)
    for profile in target_profiles.values():
        target_by_suffix[profile.suffix].append(profile)

    matched: list[str] = []
    match_details: list[dict[str, Any]] = []
    for source in source_layers:
        candidates = _candidate_target_profiles(source.profile, target_by_normalized, target_by_suffix)
        candidates = [candidate for candidate in candidates if _target_has_role_entities(candidate.name, target_counts, role)]
        if not candidates:
            match_details.append({"source_layer": source.profile.name, "matched_layer": None, "reason": "no_target_layer_with_matching_features"})
            continue
        best = sorted(candidates, key=lambda candidate: _match_score(source.profile, candidate))[0]
        if best.name not in matched:
            matched.append(best.name)
        match_details.append(
            {
                "source_layer": source.profile.name,
                "matched_layer": best.name,
                "reason": _match_reason(source.profile, best),
                "source_profile": source.profile.to_dict(),
                "target_profile": best.to_dict(),
            }
        )
    return matched, match_details


def _candidate_target_profiles(
    source: LayerProfile,
    target_by_normalized: dict[str, LayerProfile],
    target_by_suffix: dict[str, list[LayerProfile]],
) -> list[LayerProfile]:
    candidates: list[LayerProfile] = []
    exact = target_by_normalized.get(source.normalized_name)
    if exact is not None:
        candidates.append(exact)
    for candidate in target_by_suffix.get(source.suffix, []):
        if candidate.name not in {item.name for item in candidates}:
            candidates.append(candidate)
    for suffix, suffix_candidates in target_by_suffix.items():
        if source.suffix and (suffix.endswith(source.suffix) or source.suffix.endswith(suffix)):
            for candidate in suffix_candidates:
                if candidate.fingerprint() == source.fingerprint() and candidate.name not in {item.name for item in candidates}:
                    candidates.append(candidate)
    return candidates


def _target_has_role_entities(layer: str, counts_by_layer: dict[str, Counter[str]], role: str) -> bool:
    counts = counts_by_layer.get(layer, Counter())
    if role == "axis":
        return any(counts.get(entity_type, 0) for entity_type in AXIS_ENTITY_TYPES)
    return any(counts.get(entity_type, 0) for entity_type in TEXT_ENTITY_TYPES)


def _match_score(source: LayerProfile, target: LayerProfile) -> tuple[int, int, str]:
    exact_penalty = 0 if source.normalized_name == target.normalized_name else 1
    profile_penalty = 0 if source.fingerprint() == target.fingerprint() else 1
    return (exact_penalty, profile_penalty, target.normalized_name)


def _match_reason(source: LayerProfile, target: LayerProfile) -> str:
    if source.normalized_name == target.normalized_name:
        return "exact_layer_name"
    if source.suffix == target.suffix:
        return "layer_suffix"
    if source.fingerprint() == target.fingerprint():
        return "layer_suffix_and_properties"
    return "layer_features"


def _entity_counts_by_layer(doc: DxfDrawing, visible_only: bool = False) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for entity in doc.modelspace():
        if visible_only and not is_entity_visible(doc, entity):
            continue
        layer = str(getattr(entity.dxf, "layer", "0"))
        counts[layer][entity.dxftype()] += 1
    return counts


def _layer_profiles(doc: DxfDrawing) -> dict[str, LayerProfile]:
    profiles: dict[str, LayerProfile] = {}
    for layer in doc.layers:
        name = str(layer.dxf.name)
        profiles[name] = LayerProfile(
            name=name,
            normalized_name=_norm_text(name),
            suffix=_layer_suffix(name),
            is_off=bool(layer.is_off()),
            is_frozen=bool(layer.is_frozen()),
            is_locked=bool(layer.is_locked()),
            color=_optional_int(getattr(layer.dxf, "color", None)),
            true_color=_optional_int(getattr(layer.dxf, "true_color", None)),
            linetype=str(getattr(layer.dxf, "linetype", "")) or None,
            lineweight=_optional_int(getattr(layer.dxf, "lineweight", None)),
        )
    return profiles


def _layer_suffix(layer: str) -> str:
    normalized = _norm_text(layer)
    if "$" in normalized:
        return normalized.rsplit("$", 1)[-1]
    return normalized


def _norm_text(value: str | None) -> str:
    return str(value or "").strip().upper()


def _layer_text_values(layer: str) -> set[str]:
    return {_norm_text(layer), _norm_text(recover_gbk_mojibake(layer))}


def _optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _compare_axis_payloads(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    axes_equal = source.get("axes") == target.get("axes")
    texts_equal = source.get("texts") == target.get("texts")
    issues_equal = source.get("issues") == target.get("issues")
    source_layer_names = [layer["name"] for layer in source.get("layers", [])]
    target_layer_names = [layer["name"] for layer in target.get("layers", [])]
    return {
        "axes_equal": axes_equal,
        "texts_equal": texts_equal,
        "issues_equal": issues_equal,
        "semantic_json_equal": axes_equal and texts_equal and issues_equal,
        "semantic_json_note": "Exploded target DXF is accepted when axes/texts/issues match; layer statistics may differ.",
        "layer_names_equal": source_layer_names == target_layer_names,
        "layer_summary_equal": source.get("layers") == target.get("layers"),
        "source_layer_names": source_layer_names,
        "target_layer_names": target_layer_names,
    }


if __name__ == "__main__":
    raise SystemExit(main())
