from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import fitz
import pytest

from room_extractor.cad.dwg_converter import DwgConversionResult
from room_extractor.cad.dxf_self_cleaner import next_cleaning_action
from room_extractor.cli.main import main
from room_extractor.cli.dxf_preparation import main as dxf_preparation_main
from room_extractor.cli.room_extraction import main as room_extraction_main


def test_cli_extract_cad_writes_json(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    out_path = tmp_path / "cad_raw.json"
    doc = ezdxf.new()
    msp = doc.modelspace()
    text = msp.add_text("办公室", dxfattribs={"layer": "A-ROOM-TEXT", "height": 350})
    text.dxf.insert = (1, 2)
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True)
    msp.add_line((0, 2), (1, 2), dxfattribs={"layer": "A-AXIS"})
    doc.saveas(dxf_path)

    assert main(["extract-cad", "--dxf", str(dxf_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["source_file"] == "sample.dxf"
    assert payload["texts"][0]["text"] == "办公室"
    assert payload["polylines"][0]["closed"] is True
    assert payload["axes"][0]["layer"] == "A-AXIS"
    assert payload["axes"][0]["points"] == [[0.0, 2.0], [1.0, 2.0]]


def test_cli_extract_cad_visible_only_skips_frozen_layers(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample_visible.dxf"
    out_path = tmp_path / "cad_raw.json"
    doc = ezdxf.new()
    doc.layers.add("FROZEN")
    doc.layers.get("FROZEN").freeze()
    msp = doc.modelspace()
    visible_text = msp.add_text("办公室", dxfattribs={"layer": "VISIBLE", "height": 350})
    visible_text.dxf.insert = (1, 2)
    hidden_text = msp.add_text("隐藏", dxfattribs={"layer": "FROZEN", "height": 350})
    hidden_text.dxf.insert = (3, 4)
    doc.saveas(dxf_path)

    assert main(["extract-cad", "--dxf", str(dxf_path), "--out", str(out_path), "--visible-only"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert [text["text"] for text in payload["texts"]] == ["办公室"]
    frozen_layer = next(layer for layer in payload["layers"] if layer["name"] == "FROZEN")
    assert frozen_layer["entity_count"] == 0


def test_cli_extract_cad_axis_only_uses_axis_rules(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample_axis.dxf"
    out_path = tmp_path / "cad_raw_axis.json"
    rules_path = tmp_path / "axis_rules.yaml"
    rules_path.write_text("axis_layers:\n  - A-GRID\naxis_label_layers:\n  - A-ANNO-TXT\n", encoding="utf-8")
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A-GRID"})
    label = msp.add_text("1", dxfattribs={"layer": "A-ANNO-TXT", "height": 350})
    label.dxf.insert = (11, 0)
    junk = msp.add_text("垃圾", dxfattribs={"layer": "A-DOORS_TEXT", "height": 350})
    junk.dxf.insert = (5, 5)
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True, dxfattribs={"layer": "A-AREA-BNDY"})
    doc.blocks.new("JUNK_BLOCK")
    msp.add_blockref("JUNK_BLOCK", (0, 0), dxfattribs={"layer": "A-DOORS_TEXT"})
    doc.saveas(dxf_path)

    assert (
        main(
            [
                "extract-cad",
                "--dxf",
                str(dxf_path),
                "--out",
                str(out_path),
                "--axis-only",
                "--axis-rules",
                str(rules_path),
            ]
        )
        == 0
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert [axis["layer"] for axis in payload["axes"]] == ["A-GRID"]
    assert [text["text"] for text in payload["texts"]] == ["1"]
    assert payload["blocks"] == []
    assert payload["polylines"] == []
    assert {layer["name"] for layer in payload["layers"]} == {"A-GRID", "A-ANNO-TXT"}


def test_cli_extract_cad_columns_only_uses_column_rules(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample_columns.dxf"
    out_path = tmp_path / "cad_raw_columns.json"
    rules_path = tmp_path / "column_rules.yaml"
    rules_path.write_text("column_layers:\n  - A-STR-COLM\ncolumn_block_layers:\n  - new column &beam\n", encoding="utf-8")
    doc = ezdxf.new()
    doc.layers.add("XREF$0$A-STR-COLM")
    doc.layers.add("A-WALL")
    msp = doc.modelspace()
    hatch = msp.add_hatch(dxfattribs={"layer": "XREF$0$A-STR-COLM"})
    hatch.paths.add_polyline_path([(0, 0), (1000, 0), (1000, 500), (0, 500)], is_closed=True)
    junk = msp.add_text("垃圾", dxfattribs={"layer": "A-WALL", "height": 350})
    junk.dxf.insert = (5, 5)
    doc.blocks.new("COLUMN_TAG")
    insert = msp.add_blockref("COLUMN_TAG", (2000, 3000), dxfattribs={"layer": "new column &beam"})
    insert.add_attrib("COL_NO", "C1", insert=(2000, 3000))
    doc.saveas(dxf_path)

    assert (
        main(
            [
                "extract-cad",
                "--dxf",
                str(dxf_path),
                "--out",
                str(out_path),
                "--columns-only",
                "--column-rules",
                str(rules_path),
            ]
        )
        == 0
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert [column["source"] for column in payload["columns"]] == ["hatch_boundary", "block_insert"]
    assert payload["columns"][0]["bbox"] == [0.0, 0.0, 1000.0, 500.0]
    assert payload["columns"][1]["block_name"] == "COLUMN_TAG"
    assert payload["columns"][1]["attributes"] == {"COL_NO": "C1"}
    assert payload["texts"] == []
    assert payload["blocks"] == []
    assert payload["polylines"] == []
    assert payload["axes"] == []
    assert {layer["name"] for layer in payload["layers"]} == {"XREF$0$A-STR-COLM", "new column &beam"}


def test_cli_analyze_column_features_writes_reusable_summary(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample_columns.dxf"
    out_path = tmp_path / "column_features.json"
    rules_path = tmp_path / "column_rules.yaml"
    rules_path.write_text("column_layers:\n  - A-STR-COLM\n", encoding="utf-8")
    doc = ezdxf.new()
    doc.layers.add("XREF$0$A-STR-COLM")
    msp = doc.modelspace()
    hatch = msp.add_hatch(dxfattribs={"layer": "XREF$0$A-STR-COLM", "color": 256})
    hatch.paths.add_polyline_path([(0, 0), (1000, 0), (1000, 500), (0, 500)], is_closed=True)
    doc.saveas(dxf_path)

    assert (
        main(
            [
                "analyze-column-features",
                "--dxf",
                str(dxf_path),
                "--out",
                str(out_path),
                "--column-rules",
                str(rules_path),
            ]
        )
        == 0
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["column_sample_count"] == 1
    assert payload["entity_type_counts"] == {"HATCH": 1}
    color_index = int(next(iter(payload["dxf_attributes"]["color_counts"])))
    assert payload["recommended_rules"]["column_layers"] == ["A-STR-COLM"]
    assert payload["recommended_rules"]["column_entity_types"] == ["HATCH"]
    assert payload["recommended_rules"]["color_indices"] == [color_index]
    assert payload["recommended_rules"]["max_area"] == 600000.0


def test_cli_rejects_non_dxf_file(tmp_path: Path, capsys) -> None:
    dwg_path = tmp_path / "sample.dwg"
    dwg_path.write_bytes(b"not a dxf")

    assert main(["analyze-layers", "--dxf", str(dwg_path)]) == 2
    captured = capsys.readouterr()
    assert "Only DXF files are supported in Phase 1" in captured.err


def test_cli_convert_dwg_prints_summary(tmp_path: Path, capsys, monkeypatch) -> None:
    input_dir = tmp_path / "cad"
    output_dir = tmp_path / "dxf"
    input_dir.mkdir()
    seen: dict[str, object] = {}

    class FakeAcCoreConsoleDwgConverter:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_convert_dwg_directory(**kwargs):
        seen["convert_kwargs"] = kwargs
        return [
            DwgConversionResult(
                source_file=Path(kwargs["input_dir"]) / "A.dwg",
                output_file=Path(kwargs["output_dir"]) / "A.dxf",
                status="converted",
                message=None,
                explode_passes=3,
                remaining_insert_count=0,
            )
        ]

    monkeypatch.setattr("room_extractor.workflows.dxf_preparation.AcCoreConsoleDwgConverter", FakeAcCoreConsoleDwgConverter)
    monkeypatch.setattr("room_extractor.workflows.dxf_preparation.convert_dwg_directory", fake_convert_dwg_directory)

    assert (
        main(
            [
                "convert-dwg",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                "--explode-blocks",
                "--max-explode-passes",
                "3",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["converted"] == 1
    assert payload["results"][0]["remaining_insert_count"] == 0
    assert seen["convert_kwargs"]["explode_blocks"] is True
    assert seen["convert_kwargs"]["max_explode_passes"] == 3


def test_cli_explode_dxf_prints_summary(tmp_path: Path, capsys, monkeypatch) -> None:
    input_dir = tmp_path / "dxf"
    output_dir = tmp_path / "dxf_exploded"
    input_dir.mkdir()
    seen: dict[str, object] = {}

    class FakeAcCoreConsoleDwgConverter:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_explode_dxf_directory(**kwargs):
        seen["explode_kwargs"] = kwargs
        return [
            DwgConversionResult(
                source_file=Path(kwargs["input_dir"]) / "A.dxf",
                output_file=Path(kwargs["output_dir"]) / "A.dxf",
                status="converted",
                message=None,
                explode_passes=2,
                remaining_insert_count=0,
            )
        ]

    monkeypatch.setattr("room_extractor.workflows.dxf_preparation.AcCoreConsoleDwgConverter", FakeAcCoreConsoleDwgConverter)
    monkeypatch.setattr("room_extractor.workflows.dxf_preparation.explode_dxf_directory", fake_explode_dxf_directory)

    assert (
        main(
            [
                "explode-dxf",
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                "--max-explode-passes",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["converted"] == 1
    assert payload["remaining_insert_total"] == 0
    assert seen["explode_kwargs"]["max_explode_passes"] == 2


def test_cli_dedupe_dxf_lines_writes_report(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    report_path = tmp_path / "report.json"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((100, 0), (0, 0), dxfattribs={"layer": "A-WALL"})
    doc.saveas(dxf_path)

    assert main(["dedupe-dxf-lines", "--input", str(dxf_path), "--report-out", str(report_path)]) == 0

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["dedupe_mode"] == "none"
    assert payload["totals"]["exact_duplicate_count"] == 1


def test_dxf_self_cleaner_preserves_validated_16_stage_order() -> None:
    expected_actions = [
        "remove_exact_duplicate_linework",
        "remove_invisible_modelspace_entities",
        "remove_acad_layerstates",
        "rebuild_visible_modelspace",
        "remove_unused_appids",
        "remove_unreachable_blocks",
        "remove_object_metadata",
        "remove_unused_symbol_table_records",
        "remove_paperspace_layouts",
        "remove_remaining_object_metadata",
        "strip_classes_and_acdsdata_sections",
        "remove_auxiliary_points_and_xlines",
        "remove_unreachable_blocks_after_auxiliary",
        "remove_unused_tables_after_auxiliary",
        "remove_large_null_dictionary_shells",
        "strip_regenerated_classes_section",
    ]
    manifest = {"steps": []}
    actual_actions = []

    while True:
        action = next_cleaning_action(manifest)
        if action is None:
            break
        actual_actions.append(action)
        manifest["steps"].append({"name": action, "status": "rejected" if action == "rebuild_visible_modelspace" else "accepted"})

    assert actual_actions == expected_actions


def test_cli_self_clean_dxf_analyze_only_writes_manifest_and_rolls_back(tmp_path: Path) -> None:
    source_path = tmp_path / "source.dxf"
    reference_path = tmp_path / "reference.dxf"
    out_dir = tmp_path / "clean"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (1000, 0), dxfattribs={"layer": "A-WALL"})
    doc.saveas(source_path)
    doc.saveas(reference_path)

    assert (
        main(
            [
                "self-clean-dxf",
                "--source",
                str(source_path),
                "--reference",
                str(reference_path),
                "--out-dir",
                str(out_dir),
                "--analyze-only",
            ]
        )
        == 0
    )

    manifest_path = out_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["current_step"] == 0
    assert payload["rollback_points"] == [{"step": 0, "label": "original source", "path": str(source_path.resolve())}]
    assert payload["steps"][0]["name"] == "baseline"
    assert Path(payload["current_dxf"]).exists()
    assert (out_dir / "steps" / "000_baseline" / "report.html").exists()

    assert main(["self-clean-dxf", "--resume", str(out_dir), "--rollback-to", "0"]) == 0
    rolled_back = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rolled_back["current_step"] == 0
    assert Path(rolled_back["current_dxf"]).exists()


def test_workflow_specific_cli_boundaries(capsys) -> None:
    with pytest.raises(SystemExit) as dxf_error:
        dxf_preparation_main(["build-room-labels", "--help"])
    assert dxf_error.value.code == 2

    with pytest.raises(SystemExit) as room_error:
        room_extraction_main(["convert-dwg", "--help"])
    assert room_error.value.code == 2

    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_cli_build_room_labels_writes_json(tmp_path: Path) -> None:
    cad_path = tmp_path / "cad_raw.json"
    out_path = tmp_path / "room_label_candidates.json"
    cad_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "layers": [],
                "texts": [
                    {
                        "text": "会议室 201\nMeeting Room 201\n35.5㎡",
                        "entity_type": "MTEXT",
                        "layer": "00C_TEXT_Room",
                        "position": [10, 20],
                        "height": 300,
                        "rotation": 0,
                    }
                ],
                "blocks": [],
                "polylines": [],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["build-room-labels", "--cad", str(cad_path), "--out", str(out_path), "--floor", "L2"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["source_file"] == "sample.dxf"
    assert payload["candidates"][0]["room_name"] == "会议室"
    assert payload["candidates"][0]["room_number"] == "201"
    assert payload["candidates"][0]["area"] == 35.5


def test_cli_build_room_candidates_writes_json(tmp_path: Path) -> None:
    cad_path = tmp_path / "cad_raw.json"
    labels_path = tmp_path / "room_label_candidates.json"
    out_path = tmp_path / "room_candidates.json"
    cad_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "layers": [],
                "texts": [],
                "blocks": [],
                "polylines": [
                    {
                        "layer": "A-AREA-BNDY",
                        "entity_type": "LWPOLYLINE",
                        "closed": True,
                        "points": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                        "bbox": [0, 0, 2000, 2000],
                        "area": 4_000_000,
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    labels_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "candidates": [
                    {
                        "candidate_id": "label_0001",
                        "floor": "L2",
                        "room_number": "201",
                        "room_name": "会议室",
                        "area": 35.5,
                        "area_unit": "m2",
                        "center": [1000, 1000],
                        "bbox": [900, 900, 1100, 1100],
                        "source_texts": [],
                        "confidence": 1.0,
                        "issues": [],
                    }
                ],
                "parsed_texts": [],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "build-room-candidates",
                "--cad",
                str(cad_path),
                "--labels",
                str(labels_path),
                "--out",
                str(out_path),
                "--door-gap-min-width",
                "700",
                "--door-gap-max-width",
                "2500",
            ]
        )
        == 0
    )

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["room_candidates"][0]["status"] == "matched"
    assert payload["room_candidates"][0]["boundary"]["area_cad"] == 4_000_000
    assert payload["summary"]["door_gap_bridge"]["min_width"] == 700.0
    assert payload["summary"]["door_gap_bridge"]["max_width"] == 2500.0


def test_cli_build_room_candidates_uses_validated_wall_defaults(tmp_path: Path) -> None:
    cad_path = tmp_path / "cad_raw.json"
    labels_path = tmp_path / "room_label_candidates.json"
    out_path = tmp_path / "room_candidates.json"
    cad_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "layers": [],
                "texts": [],
                "blocks": [],
                "polylines": [
                    {"layer": "A-WALL", "entity_type": "LINE", "closed": False, "points": [[0, 0], [4000, 0]], "bbox": [0, 0, 4000, 0]},
                    {"layer": "A-WALL", "entity_type": "LINE", "closed": False, "points": [[4000, 0], [4000, 3000]], "bbox": [4000, 0, 4000, 3000]},
                    {"layer": "A-WALL", "entity_type": "LINE", "closed": False, "points": [[4000, 3000], [0, 3000]], "bbox": [0, 3000, 4000, 3000]},
                    {"layer": "A-WALL", "entity_type": "LINE", "closed": False, "points": [[0, 3000], [0, 0]], "bbox": [0, 0, 0, 3000]},
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    labels_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "candidates": [
                    {
                        "candidate_id": "label_0001",
                        "floor": "L2",
                        "room_number": "201",
                        "room_name": "会议室",
                        "area": 12.0,
                        "area_unit": "m2",
                        "center": [2000, 1500],
                        "bbox": [1900, 1400, 2100, 1600],
                        "source_texts": [],
                        "confidence": 1.0,
                        "issues": [],
                    }
                ],
                "parsed_texts": [],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["build-room-candidates", "--cad", str(cad_path), "--labels", str(labels_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    room = payload["room_candidates"][0]
    assert room["status"] == "matched"
    assert room["boundary"]["entity_type"] == "SEGMENT_POLYGONIZED"
    assert room["boundary"]["area_cad"] == 12_000_000.0
    assert payload["summary"]["boundary_layers"][:3] == ["WALL", "0-面积线", "Defpoints"]
    assert payload["summary"]["boundary_candidate_count"] == 1


def test_cli_export_review_map_writes_html(tmp_path: Path) -> None:
    cad_path = tmp_path / "cad_raw.json"
    rooms_path = tmp_path / "room_candidates.json"
    out_path = tmp_path / "review.html"
    cad_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "layers": [],
                "texts": [],
                "blocks": [],
                "polylines": [
                    {
                        "layer": "A-AREA-BNDY",
                        "entity_type": "LWPOLYLINE",
                        "closed": True,
                        "points": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                        "bbox": [0, 0, 2000, 2000],
                        "area": 4_000_000,
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    boundary = {
        "boundary_id": "boundary_00001",
        "source_polyline_index": 0,
        "layer": "A-AREA-BNDY",
        "entity_type": "LWPOLYLINE",
        "polygon_cad": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
        "bbox_cad": [0, 0, 2000, 2000],
        "area_cad": 4_000_000,
    }
    label = {
        "candidate_id": "label_0001",
        "room_number": "201",
        "room_name": "会议室",
        "area": 35.5,
        "area_unit": "m2",
        "center": [1000, 1000],
        "bbox": [900, 900, 1100, 1100],
        "source_texts": [],
        "confidence": 1.0,
        "issues": [],
    }
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "label_source_file": "sample.dxf",
                "summary": {"status_counts": {"matched": 1}, "boundary_candidate_count": 1, "room_candidate_count": 1},
                "boundary_candidates": [boundary],
                "room_candidates": [
                    {
                        "room_candidate_id": "room_candidate_0001",
                        "room_number": "201",
                        "room_name": "会议室",
                        "area_text": 35.5,
                        "area_unit": "m2",
                        "label_center": [1000, 1000],
                        "label_bbox": [900, 900, 1100, 1100],
                        "boundary": boundary,
                        "match_method": "point_in_polygon_smallest_area",
                        "status": "matched",
                        "confidence": 1.0,
                        "label": label,
                        "issues": [],
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["export-review-map", "--cad", str(cad_path), "--rooms", str(rooms_path), "--out", str(out_path)]) == 0

    html = out_path.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "会议室" in html


def test_cli_build_rooms_writes_rooms_auto_json(tmp_path: Path) -> None:
    candidates_path = tmp_path / "room_candidates.json"
    out_path = tmp_path / "rooms_auto.json"
    boundary = {
        "boundary_id": "boundary_00001",
        "source_polyline_index": 0,
        "layer": "A-AREA-BNDY",
        "entity_type": "LWPOLYLINE",
        "polygon_cad": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
        "bbox_cad": [0, 0, 5000, 5000],
        "area_cad": 25_000_000,
    }
    label = {
        "candidate_id": "sample_label_0001",
        "floor": "L2",
        "room_number": "201",
        "room_name": "会议室",
        "area": 25.0,
        "area_unit": "m2",
        "center": [2500, 2500],
        "bbox": [2400, 2400, 2600, 2600],
        "source_texts": [],
        "confidence": 1.0,
        "issues": [],
    }
    candidates_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "label_source_file": "sample.dxf",
                "summary": {},
                "boundary_candidates": [boundary],
                "room_candidates": [
                    {
                        "room_candidate_id": "room_candidate_0001",
                        "floor": "L2",
                        "room_number": "201",
                        "room_name": "会议室",
                        "area_text": 25.0,
                        "area_unit": "m2",
                        "label_center": [2500, 2500],
                        "label_bbox": [2400, 2400, 2600, 2600],
                        "boundary": boundary,
                        "match_method": "point_in_polygon_smallest_area",
                        "status": "matched",
                        "confidence": 1.0,
                        "label": label,
                        "issues": [],
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["build-rooms", "--candidates", str(candidates_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["rooms"][0]["basic_info"]["room_name"] == "会议室"
    assert payload["rooms"][0]["area"]["calculated_value"] == 25.0
    assert payload["rooms"][0]["geometry"]["geometry_source"] == "cad_auto"


def test_cli_check_pdf_writes_checked_json(tmp_path: Path) -> None:
    rooms_path = tmp_path / "rooms_auto.json"
    pdf_path = tmp_path / "sample.pdf"
    out_path = tmp_path / "rooms_pdf_checked.json"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((70, 70), "201", fontsize=10)
    page.insert_text((70, 84), "25.0m2", fontsize=10)
    doc.save(pdf_path)
    doc.close()
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "summary": {},
                "rooms": [
                    {
                        "room_uid": "sample_r0001",
                        "basic_info": {"room_number": "201"},
                        "area": {"text_value": 25.0, "unit": "m2"},
                        "geometry": {
                            "polygon_cad": [[0, 0], [100, 0], [100, 100], [0, 100]],
                            "bbox_cad": [0, 0, 100, 100],
                            "coordinate_unit": "mm",
                            "geometry_source": "cad_auto",
                        },
                        "confidence": {"room_number": 1.0, "area": 1.0, "geometry": 0.9, "overall": 0.9},
                        "review": {"required": False, "status": "pending_pdf_check"},
                        "issues": [],
                        "final_status": "cad_auto_draft",
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["check-pdf", "--rooms", str(rooms_path), "--pdf", str(pdf_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["summary"]["checked_with_pdf_bbox"] == 1
    assert payload["rooms"][0]["evidence"]["pdf_source"]["local_text"] == "201\n25.0m2"


def test_cli_render_review_images_writes_images_and_json(tmp_path: Path) -> None:
    rooms_path = tmp_path / "rooms_auto.json"
    checked_path = tmp_path / "rooms_pdf_checked.json"
    out_path = tmp_path / "rooms_with_images.json"
    image_dir = tmp_path / "review_images"
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((70, 70), "201", fontsize=10)
    page.insert_text((70, 84), "25.0m2", fontsize=10)
    doc.save(pdf_path)
    doc.close()
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "summary": {},
                "rooms": [
                    {
                        "room_uid": "sample_r0001",
                        "basic_info": {"room_number": "201"},
                        "area": {"text_value": 30.0, "unit": "m2"},
                        "geometry": {
                            "polygon_cad": [[0, 0], [100, 0], [100, 100], [0, 100]],
                            "bbox_cad": [0, 0, 100, 100],
                            "coordinate_unit": "mm",
                            "geometry_source": "cad_auto",
                        },
                        "confidence": {"room_number": 1.0, "area": 1.0, "geometry": 0.9, "overall": 0.9},
                        "review": {"required": False, "status": "pending_pdf_check"},
                        "issues": [],
                        "final_status": "cad_auto_draft",
                    }
                ],
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert main(["check-pdf", "--rooms", str(rooms_path), "--pdf", str(pdf_path), "--out", str(checked_path)]) == 0

    assert main(["render-review-images", "--rooms", str(checked_path), "--pdf", str(pdf_path), "--output-dir", str(image_dir), "--out", str(out_path), "--dpi", "72"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    review_image = payload["rooms"][0]["evidence"]["pdf_source"]["review_image"]
    assert payload["summary"]["review_images_rendered"] == 1
    assert payload["summary"]["review_images_anchor_crops"] == 1
    assert review_image["source"] == "pdf_text_anchor_crop"
    assert Path(review_image["path"]).exists()


def test_cli_check_images_ai_dry_run_writes_json(tmp_path: Path) -> None:
    rooms_path = tmp_path / "rooms_with_images.json"
    out_path = tmp_path / "rooms_ai_checked.json"
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "pdf_source_file": "sample.pdf",
                "summary": {},
                "transform": {},
                "rooms": [
                    {
                        "room_uid": "sample_r0001",
                        "basic_info": {"room_number": "201", "room_name": "会议室"},
                        "evidence": {
                            "pdf_source": {
                                "local_text": "201\n25.0m2",
                                "review_image": {"path": str(tmp_path / "sample.png")},
                            }
                        },
                        "issues": [],
                    }
                ],
                "pdf_text": {"source_file": "sample.pdf", "pages": []},
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["check-images-ai", "--rooms", str(rooms_path), "--out", str(out_path), "--dry-run", "--limit", "1", "--model", "test-model"]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["summary"]["local_ai_checked"] == 1
    assert payload["rooms"][0]["evidence"]["pdf_source"]["local_ai_check"]["status"] == "dry_run"


def test_cli_build_review_tasks_writes_json(tmp_path: Path) -> None:
    rooms_path = tmp_path / "rooms_ai_checked.json"
    out_path = tmp_path / "review_tasks.json"
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "pdf_source_file": "sample.pdf",
                "summary": {},
                "transform": {},
                "rooms": [
                    {
                        "room_uid": "sample_r0001",
                        "basic_info": {"floor": "L2", "room_number": "201", "room_name": "会议室"},
                        "area": {"text_value": 25.0, "unit": "m2"},
                        "geometry": {
                            "polygon_cad": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "bbox_cad": [0, 0, 10, 10],
                            "bbox_pdf": [1, 1, 2, 2],
                        },
                        "evidence": {
                            "pdf_source": {
                                "review_image": {"path": "review.png"},
                                "local_ai_check": {"status": "ok", "needs_review": True, "area_match": False, "notes": "面积不一致"},
                            }
                        },
                        "review": {"required": True, "status": "pending_downstream_check"},
                        "issues": [
                            {
                                "issue_code": "PDF_AREA_MISMATCH",
                                "severity": "medium",
                                "field": "area",
                                "message": "面积不一致",
                                "need_manual_review": True,
                            }
                        ],
                    }
                ],
                "pdf_text": {"source_file": "sample.pdf", "pages": []},
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["build-review-tasks", "--rooms", str(rooms_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["summary"]["task_count"] == 1
    assert payload["tasks"][0]["review_image_path"] == "review.png"
    assert "area" in payload["tasks"][0]["suggested_fields"]


def test_cli_export_rooms_html_writes_html(tmp_path: Path) -> None:
    rooms_path = tmp_path / "rooms_ai_checked.json"
    out_path = tmp_path / "recognized_rooms.html"
    rooms_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "pdf_source_file": "sample.pdf",
                "summary": {},
                "transform": {},
                "rooms": [
                    {
                        "room_uid": "sample_r0001",
                        "basic_info": {"floor": "L2", "room_number": "201", "room_name": "会议室"},
                        "area": {"text_value": 25.0, "unit": "m2"},
                        "geometry": {
                            "polygon_cad": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "bbox_cad": [0, 0, 10, 10],
                            "geometry_source": "cad_auto",
                        },
                        "evidence": {
                            "pdf_source": {
                                "local_text": "会议室 201",
                                "review_image": {"path": "review.png"},
                                "local_ai_check": {"status": "ok", "needs_review": False},
                            }
                        },
                        "review": {"required": False, "status": "auto_passed"},
                        "issues": [],
                    }
                ],
                "pdf_text": {"source_file": "sample.pdf", "pages": []},
                "issues": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert main(["export-rooms-html", "--rooms", str(rooms_path), "--out", str(out_path)]) == 0

    html = out_path.read_text(encoding="utf-8")
    assert "识别房间总览" in html
    assert "overview-map" in html
    assert "房间分图" in html
    assert "会议室" in html
