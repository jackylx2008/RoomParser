from __future__ import annotations

from pathlib import Path

import ezdxf

from room_extractor.cad import analyze_layers, extract_cad_raw, load_dxf


def test_dxf_phase1_extraction(tmp_path: Path) -> None:
    dxf_path = _build_sample_dxf(tmp_path / "sample.dxf")

    doc = load_dxf(dxf_path)
    layer_analysis = analyze_layers(doc, dxf_path)
    raw = extract_cad_raw(doc, dxf_path)

    assert layer_analysis.totals.text_count == 1
    assert layer_analysis.totals.mtext_count == 1
    assert layer_analysis.totals.insert_count == 1
    assert layer_analysis.totals.closed_lwpolyline_count == 1
    assert raw.source_file == "sample.dxf"
    assert {text.text for text in raw.texts} == {"办公室", "25.60m2"}
    assert {text.height for text in raw.texts} == {250.0, 350.0}
    assert raw.blocks[0].name == "ROOM_TAG"
    assert raw.blocks[0].attributes == {"ROOM_NO": "101"}
    assert raw.polylines[0].closed is True
    assert raw.polylines[0].bbox == (0.0, 0.0, 10.0, 10.0)
    assert raw.polylines[0].area == 100.0
    assert len(raw.axes) == 2
    assert raw.axes[0].layer == "A-AXIS"
    assert raw.axes[0].entity_type == "LINE"
    assert raw.axes[0].points == [(0.0, -5.0), (10.0, -5.0)]
    assert raw.axes[0].bbox == (0.0, -5.0, 10.0, -5.0)
    assert raw.axes[0].length == 10.0
    assert raw.axes[1].entity_type == "ARC"
    assert len(raw.axes[1].points) >= 17
    assert raw.axes[1].length is not None


def _build_sample_dxf(path: Path) -> Path:
    doc = ezdxf.new()
    doc.layers.add("A-ROOM-TEXT")
    doc.layers.add("A-ROOM-BOUNDARY")
    doc.layers.add("A-AXIS")
    msp = doc.modelspace()

    text = msp.add_text("办公室", dxfattribs={"layer": "A-ROOM-TEXT", "height": 350, "rotation": 0})
    text.dxf.insert = (12000, 8500)
    mtext = msp.add_mtext("25.60m2", dxfattribs={"layer": "A-ROOM-TEXT", "char_height": 250})
    mtext.dxf.insert = (12000, 8000)

    doc.blocks.new("ROOM_TAG")
    insert = msp.add_blockref("ROOM_TAG", (1000, 2000), dxfattribs={"layer": "A-ROOM-TEXT"})
    insert.add_attrib("ROOM_NO", "101", insert=(1000, 2000))

    msp.add_lwpolyline(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        close=True,
        dxfattribs={"layer": "A-ROOM-BOUNDARY"},
    )
    msp.add_line((0, -5), (10, -5), dxfattribs={"layer": "A-AXIS"})
    msp.add_arc(
        center=(5, -5),
        radius=5,
        start_angle=0,
        end_angle=90,
        dxfattribs={"layer": "A-AXIS"},
    )
    msp.add_arc(
        center=(15, -5),
        radius=5,
        start_angle=90,
        end_angle=180,
        dxfattribs={"layer": "A-AXIS"},
    )

    doc.saveas(path)
    return path
