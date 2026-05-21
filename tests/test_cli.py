from __future__ import annotations

import json
from pathlib import Path

import ezdxf

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
