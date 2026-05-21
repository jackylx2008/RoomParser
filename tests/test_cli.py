from __future__ import annotations

import json
from pathlib import Path

import ezdxf

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

