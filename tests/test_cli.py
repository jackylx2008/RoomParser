from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import fitz

from room_extractor.cad.dwg_converter import DwgConversionResult
from room_extractor.cli.main import main


def test_cli_extract_cad_writes_json(tmp_path: Path) -> None:
    dxf_path = tmp_path / "sample.dxf"
    out_path = tmp_path / "cad_raw.json"
    doc = ezdxf.new()
    msp = doc.modelspace()
    text = msp.add_text("办公室", dxfattribs={"layer": "A-ROOM-TEXT", "height": 350})
    text.dxf.insert = (1, 2)
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True)
    doc.saveas(dxf_path)

    assert main(["extract-cad", "--dxf", str(dxf_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["source_file"] == "sample.dxf"
    assert payload["texts"][0]["text"] == "办公室"
    assert payload["polylines"][0]["closed"] is True


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

    class FakeAcCoreConsoleDwgConverter:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_convert_dwg_directory(**kwargs):
        return [
            DwgConversionResult(
                source_file=Path(kwargs["input_dir"]) / "A.dwg",
                output_file=Path(kwargs["output_dir"]) / "A.dxf",
                status="converted",
                message=None,
            )
        ]

    monkeypatch.setattr("room_extractor.cli.main.AcCoreConsoleDwgConverter", FakeAcCoreConsoleDwgConverter)
    monkeypatch.setattr("room_extractor.cli.main.convert_dwg_directory", fake_convert_dwg_directory)

    assert main(["convert-dwg", "--input-dir", str(input_dir), "--output-dir", str(output_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1
    assert payload["converted"] == 1


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

    assert main(["build-room-candidates", "--cad", str(cad_path), "--labels", str(labels_path), "--out", str(out_path)]) == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["room_candidates"][0]["status"] == "matched"
    assert payload["room_candidates"][0]["boundary"]["area_cad"] == 4_000_000


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
