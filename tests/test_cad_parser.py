from __future__ import annotations

from pathlib import Path

import ezdxf

from room_extractor.cad import analyze_layers, extract_cad_raw, extract_columns, load_dxf
from room_extractor.config.column_rules import ColumnLayerRules


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
    assert raw.columns == []


def test_extract_columns_from_hatch_boundary(tmp_path: Path) -> None:
    dxf_path = tmp_path / "columns.dxf"
    doc = ezdxf.new()
    doc.layers.add("XREF$0$A-STR-COLM")
    doc.layers.add("A-WALL")
    msp = doc.modelspace()
    hatch = msp.add_hatch(dxfattribs={"layer": "XREF$0$A-STR-COLM"})
    hatch.paths.add_polyline_path([(0, 0), (1200, 0), (1200, 800), (0, 800)], is_closed=True)
    wall_hatch = msp.add_hatch(dxfattribs={"layer": "A-WALL"})
    wall_hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    doc.saveas(dxf_path)

    columns, issues = extract_columns(ezdxf.readfile(dxf_path), ColumnLayerRules(column_layers=["A-STR-COLM"]))

    assert issues == []
    assert len(columns) == 1
    assert columns[0].column_id == "column_00001"
    assert columns[0].source == "hatch_boundary"
    assert columns[0].bbox == (0.0, 0.0, 1200.0, 800.0)
    assert columns[0].center == (600.0, 400.0)
    assert columns[0].area == 960000.0


def test_extract_columns_expands_insert_virtual_entities(tmp_path: Path) -> None:
    dxf_path = tmp_path / "columns_in_block.dxf"
    doc = ezdxf.new()
    doc.layers.add("A-STR-COLM")
    block = doc.blocks.new("COLUMN_BLOCK")
    hatch = block.add_hatch(dxfattribs={"layer": "A-STR-COLM"})
    hatch.paths.add_polyline_path([(0, 0), (500, 0), (500, 500), (0, 500)], is_closed=True)
    doc.modelspace().add_blockref("COLUMN_BLOCK", (1000, 2000), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    columns, issues = extract_columns(ezdxf.readfile(dxf_path), ColumnLayerRules(column_layers=["A-STR-COLM"], column_entity_types=["HATCH"]))

    assert issues == []
    assert len(columns) == 1
    assert columns[0].bbox == (1000.0, 2000.0, 1500.0, 2500.0)


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
