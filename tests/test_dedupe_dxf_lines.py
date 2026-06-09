from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from dedupe_dxf_lines import build_duplicate_report, collect_line_like_records, main, remove_duplicates


def test_collect_line_like_records_counts_exact_and_near_duplicates(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((100, 0), (0, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0.2, 0.1), (100.2, 0.1), dxfattribs={"layer": "A-WALL"})
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], dxfattribs={"layer": "A-ROOM"})
    msp.add_lwpolyline([(10, 10), (10, 0), (0, 0)], dxfattribs={"layer": "A-ROOM"})
    doc.saveas(dxf_path)

    loaded = ezdxf.readfile(dxf_path)
    records, skipped = collect_line_like_records(loaded, near_tolerance=1.0)
    report = build_duplicate_report(
        records,
        input_path=dxf_path,
        output_path=None,
        visible_only=False,
        exact_tolerance=1e-9,
        near_tolerance=1.0,
        signature_scope="layer",
        skipped_entity_count=skipped,
    )

    assert report["totals"]["entity_count"] == 5
    assert report["totals"]["line_count"] == 3
    assert report["totals"]["lwpolyline_count"] == 2
    assert report["layers"]["A-WALL"]["exact_duplicate_count"] == 1
    assert report["layers"]["A-WALL"]["near_duplicate_count"] == 2
    assert report["layers"]["A-ROOM"]["exact_duplicate_count"] == 1


def test_remove_duplicates_deletes_repeated_entities(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    out_path = tmp_path / "clean.dxf"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((100, 0), (0, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0, 10), (100, 10), dxfattribs={"layer": "A-WALL"})
    doc.saveas(dxf_path)

    loaded = ezdxf.readfile(dxf_path)
    records, _ = collect_line_like_records(loaded)
    removed = remove_duplicates(loaded, records, mode="exact")
    loaded.saveas(out_path)

    cleaned = ezdxf.readfile(out_path)
    assert removed == {"total": 1, "layers": {"A-WALL": 1}}
    assert sum(1 for entity in cleaned.modelspace() if entity.dxftype() == "LINE") == 2


def test_cli_writes_report_and_clean_dxf(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    out_path = tmp_path / "clean.dxf"
    report_path = tmp_path / "report.json"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((100, 0), (0, 0), dxfattribs={"layer": "A-WALL"})
    doc.saveas(dxf_path)

    exit_code = main(["--input", str(dxf_path), "--out", str(out_path), "--report-out", str(report_path)])

    report = json.loads(report_path.read_text(encoding="utf-8"))
    cleaned = ezdxf.readfile(out_path)
    assert exit_code == 0
    assert report["dedupe_mode"] == "exact"
    assert report["totals"]["removed_count"] == 1
    assert sum(1 for entity in cleaned.modelspace() if entity.dxftype() == "LINE") == 1


def test_geometry_scope_near_dedupe_ignores_layers(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    out_path = tmp_path / "clean.dxf"
    report_path = tmp_path / "report.json"
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (100, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_line((0.2, 0.1), (100.2, 0.1), dxfattribs={"layer": "A-DOOR"})
    msp.add_line((0, 10), (100, 10), dxfattribs={"layer": "A-DOOR"})
    doc.saveas(dxf_path)

    exit_code = main(
        [
            "--input",
            str(dxf_path),
            "--out",
            str(out_path),
            "--report-out",
            str(report_path),
            "--dedupe-mode",
            "near",
            "--signature-scope",
            "geometry",
            "--near-tolerance",
            "1.0",
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    cleaned = ezdxf.readfile(out_path)
    assert exit_code == 0
    assert report["signature_scope"] == "geometry"
    assert report["totals"]["removed_count"] == 1
    assert sum(1 for entity in cleaned.modelspace() if entity.dxftype() == "LINE") == 2
