from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from infer_dxf_rules import infer_axis_rules, main


def _add_layer(doc, name: str, color: int = 7, linetype: str = "CONTINUOUS", locked: bool = False):
    layer = doc.layers.new(name=name, dxfattribs={"color": color, "linetype": linetype})
    if locked:
        layer.lock()
    return layer


def test_infer_axis_rules_matches_target_layers_by_source_features() -> None:
    source = ezdxf.new()
    _add_layer(source, "A-GRID", color=1, linetype="CENTER")
    _add_layer(source, "A-ANNO-TXT", color=2)
    _add_layer(source, "A-AREA", color=3)
    _add_layer(source, "A-DOORS_TEXT", color=4)
    source.modelspace().add_line((0, 0), (100, 0), dxfattribs={"layer": "A-GRID"})
    source.modelspace().add_text("1", dxfattribs={"layer": "A-ANNO-TXT"})
    source.modelspace().add_line((0, 10), (100, 10), dxfattribs={"layer": "A-AREA"})
    source.modelspace().add_text("door", dxfattribs={"layer": "A-DOORS_TEXT"})

    target = ezdxf.new()
    _add_layer(target, "xref$0$A-GRID", color=1, linetype="CENTER")
    _add_layer(target, "xref$0$A-ANNO-TXT", color=2)
    target.modelspace().add_line((0, 0), (100, 0), dxfattribs={"layer": "xref$0$A-GRID"})
    target.modelspace().add_text("1", dxfattribs={"layer": "xref$0$A-ANNO-TXT"})

    inferred = infer_axis_rules(source, target)

    assert inferred["source_rules"] == {"axis_layers": ["A-GRID"], "axis_label_layers": ["A-ANNO-TXT"]}
    assert inferred["target_rules"] == {"axis_layers": ["xref$0$A-GRID"], "axis_label_layers": ["xref$0$A-ANNO-TXT"]}
    assert inferred["target_matches"]["axis_layers"][0]["reason"] == "layer_suffix"


def test_infer_dxf_rules_cli_writes_target_axis_json(tmp_path: Path) -> None:
    source_path = tmp_path / "source_axis.dxf"
    target_path = tmp_path / "target_full.dxf"
    out_path = tmp_path / "target_axis.json"
    source_out = tmp_path / "source_axis.json"
    rules_out = tmp_path / "rules.json"

    source = ezdxf.new()
    _add_layer(source, "A-GRID", color=1, linetype="CENTER")
    _add_layer(source, "A-ANNO-TXT", color=2)
    source.blocks.new("AXIS_LABEL")
    source.modelspace().add_line((0, 0), (100, 0), dxfattribs={"layer": "A-GRID"})
    source.modelspace().add_blockref("AXIS_LABEL", (0, 0), dxfattribs={"layer": "A-ANNO-TXT"})
    source.modelspace().add_text("1", dxfattribs={"layer": "A-ANNO-TXT"})
    source.saveas(source_path)

    target = ezdxf.new()
    _add_layer(target, "A-GRID", color=1, linetype="CENTER")
    _add_layer(target, "A-ANNO-TXT", color=2)
    _add_layer(target, "A-WALL", color=3)
    target.modelspace().add_line((0, 0), (100, 0), dxfattribs={"layer": "A-GRID"})
    target.modelspace().add_text("1", dxfattribs={"layer": "A-ANNO-TXT"})
    target.modelspace().add_line((0, 10), (100, 10), dxfattribs={"layer": "A-WALL"})
    target.saveas(target_path)

    exit_code = main(
        [
            "--source-dxf",
            str(source_path),
            "--target-dxf",
            str(target_path),
            "--out",
            str(out_path),
            "--source-out",
            str(source_out),
            "--rules-out",
            str(rules_out),
        ]
    )

    target_payload = json.loads(out_path.read_text(encoding="utf-8"))
    source_payload = json.loads(source_out.read_text(encoding="utf-8"))
    rules_payload = json.loads(rules_out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert len(target_payload["axes"]) == 1
    assert len(target_payload["texts"]) == 1
    assert {layer["name"] for layer in target_payload["layers"]} == {"A-GRID", "A-ANNO-TXT"}
    assert len(source_payload["axes"]) == 1
    assert rules_payload["summary"]["target_axis_count"] == 1
    assert rules_payload["summary"]["validation"]["semantic_json_equal"] is True
    assert rules_payload["summary"]["validation"]["layer_names_equal"] is True
    assert rules_payload["summary"]["validation"]["layer_summary_equal"] is False
    assert "Exploded target DXF" in rules_payload["summary"]["validation"]["semantic_json_note"]
