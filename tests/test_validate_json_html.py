from __future__ import annotations

import json
from pathlib import Path

from room_extractor.export.json_review_html import _load_source, build_json_review_html


def test_json_review_html_includes_mouse_wheel_zoom_controls(tmp_path: Path) -> None:
    json_path = tmp_path / "room_candidates.json"
    json_path.write_text(
        json.dumps(
            {
                "source_file": "sample.dxf",
                "boundary_candidates": [
                    {
                        "boundary_id": "boundary_00001",
                        "layer": "0-面积线",
                        "polygon_cad": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                        "bbox_cad": [0, 0, 2000, 2000],
                        "area_cad": 4_000_000,
                    }
                ],
                "room_candidates": [
                    {
                        "room_candidate_id": "room_candidate_0001",
                        "room_number": "101",
                        "room_name": "办公室",
                        "status": "matched",
                        "match_method": "point_in_polygon_smallest_area",
                        "confidence": 1.0,
                        "label_center": [1000, 1000],
                        "boundary": {
                            "boundary_id": "boundary_00001",
                            "layer": "0-面积线",
                            "polygon_cad": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
                        },
                        "issues": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = _load_source(1, json_path, include_polylines=False, include_texts=False, include_boundaries=True)

    html = build_json_review_html([source], title="房间校核")

    assert 'data-map' in html
    assert 'data-zoom-readout' in html
    assert 'data-base-stroke-width' in html
    assert 'data-base-font-size' in html
    assert 'addEventListener("wheel"' in html
    assert "clientToSvgPoint" in html
    assert "scaleStableStyles" in html
    assert "滚轮缩放" in html
    assert "room_candidate_0001" in html
