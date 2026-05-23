from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any


Point = tuple[float, float]
BBox = tuple[float, float, float, float]

DEFAULT_INPUT = Path("data/output/json/cad_raw_real.json")
DEFAULT_OUTPUT = Path("data/output/reports/json_review.html")


@dataclass
class ReviewSource:
    index: int
    path: Path
    name: str
    payload: dict[str, Any]
    axes: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    polylines: list[dict[str, Any]]
    texts: list[dict[str, Any]]
    label_texts: list[dict[str, Any]]
    axis_labels: dict[int, tuple[str, str]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an HTML/SVG manual review page from one or more JSON files.")
    parser.add_argument(
        "--json",
        action="append",
        default=None,
        help="Input JSON path. Repeat this option to overlay multiple JSON data sources.",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Output HTML path.")
    parser.add_argument("--title", default="JSON人工校核", help="HTML title.")
    parser.add_argument("--include-polylines", action="store_true", help="Write polylines into the HTML as an optional overlay.")
    parser.add_argument("--include-texts", action="store_true", help="Write text points into the HTML as an optional overlay.")
    args = parser.parse_args()

    input_paths = [Path(path) for path in (args.json or [str(DEFAULT_INPUT)])]
    output_path = Path(args.out)
    sources = [
        _load_source(
            index,
            path,
            include_polylines=bool(args.include_polylines),
            include_texts=bool(args.include_texts),
        )
        for index, path in enumerate(input_paths, start=1)
    ]
    html = build_json_review_html(sources, title=str(args.title))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def _load_source(index: int, path: Path, include_polylines: bool, include_texts: bool) -> ReviewSource:
    payload = json.loads(path.read_text(encoding="utf-8"))
    name = str(payload.get("source_file") or path.name)
    axes = [_normalize_axis(axis) for axis in payload.get("axes", []) if _normalize_axis(axis)["points"]]
    columns = [_normalize_column(column) for column in payload.get("columns", []) if _normalize_column(column)["drawable"]]
    polylines = (
        [_normalize_polyline(polyline) for polyline in payload.get("polylines", []) if _normalize_polyline(polyline)["points"]]
        if include_polylines
        else []
    )
    label_texts = [_normalize_text(text) for text in payload.get("texts", []) if _normalize_text(text)["position"] is not None]
    texts = label_texts if include_texts else []
    axis_labels = _match_axis_endpoint_labels(axes, label_texts)
    return ReviewSource(
        index=index,
        path=path,
        name=name,
        payload=payload,
        axes=axes,
        columns=columns,
        polylines=polylines,
        texts=texts,
        label_texts=label_texts,
        axis_labels=axis_labels,
    )


def build_json_review_html(sources: list[ReviewSource], title: str) -> str:
    bounds = _bounds_for_sources(sources)
    svg = _empty_svg() if bounds is None else _review_svg(sources, bounds)
    source_controls = "\n".join(_source_control(source) for source in sources)
    source_rows = "\n".join(_source_row(source) for source in sources)
    layer_rows = "\n".join(_layer_row(source) for source in sources)
    axis_detail_rows = "\n".join(_axis_rows(source) for source in sources)
    if not axis_detail_rows:
        axis_detail_rows = '<tr><td colspan="8">未发现可绘制轴线。</td></tr>'
    column_detail_rows = "\n".join(_column_rows(source) for source in sources)
    if not column_detail_rows:
        column_detail_rows = '<tr><td colspan="9">未发现可绘制结构柱。</td></tr>'

    warning = ""
    if not any(source.axes or source.columns or source.polylines or source.texts for source in sources):
        warning = '<div class="warning">输入 JSON 中没有可绘制的 axes、columns、polylines 或 texts。</div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, "Microsoft YaHei", sans-serif;
      color: #1f2933;
      background: #f6f8fb;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      padding: 16px 24px;
      background: #ffffff;
      border-bottom: 1px solid #d8dee9;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 22px;
      font-weight: 700;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 18px;
      align-items: center;
      font-size: 13px;
    }}
    .control-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding-right: 12px;
      border-right: 1px solid #e5e7eb;
    }}
    label {{
      white-space: nowrap;
    }}
    main {{
      padding: 18px 24px 28px;
    }}
    .warning {{
      margin-bottom: 14px;
      padding: 12px 14px;
      border: 1px solid #f59e0b;
      background: #fffbeb;
      color: #7c2d12;
      border-radius: 6px;
      font-size: 14px;
    }}
    .map {{
      overflow: auto;
      background: #ffffff;
      border: 1px solid #d8dee9;
      border-radius: 6px;
    }}
    svg {{
      display: block;
      min-width: 900px;
      width: 100%;
      height: auto;
      background: #ffffff;
    }}
    .panel {{
      display: grid;
      grid-template-columns: minmax(260px, 420px) minmax(0, 1fr);
      gap: 16px;
      margin-top: 16px;
      align-items: start;
    }}
    section {{
      background: #ffffff;
      border: 1px solid #d8dee9;
      border-radius: 6px;
      overflow: hidden;
    }}
    h2 {{
      margin: 0;
      padding: 12px 14px;
      font-size: 15px;
      border-bottom: 1px solid #d8dee9;
      background: #f9fafb;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid #edf1f5;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: #4b5563;
      background: #fbfcfe;
      font-weight: 600;
    }}
    code {{
      font-family: Consolas, monospace;
      font-size: 12px;
    }}
    .legend-dot {{
      display: inline-block;
      width: 10px;
      height: 10px;
      margin-right: 6px;
      border-radius: 50%;
      vertical-align: -1px;
    }}
    body.hide-axes .kind-axes,
    body.hide-columns .kind-columns,
    body.hide-polylines .kind-polylines,
    body.hide-texts .kind-texts,
    body.hide-axis-labels .kind-axis-labels {{
      display: none;
    }}
    {''.join(f'body.hide-source-{source.index} .source-{source.index} {{ display: none; }}' for source in sources)}
    @media (max-width: 900px) {{
      .panel {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="controls">
      <div class="control-group">
        <strong>显示内容</strong>
        <label><input type="checkbox" data-toggle-class="hide-axes" checked> 轴线</label>
        <label><input type="checkbox" data-toggle-class="hide-axis-labels" checked> 轴号</label>
        <label><input type="checkbox" data-toggle-class="hide-columns" checked> 结构柱</label>
        <label><input type="checkbox" data-toggle-class="hide-polylines"> 多段线（需 --include-polylines）</label>
        <label><input type="checkbox" data-toggle-class="hide-texts"> 文本点（需 --include-texts）</label>
      </div>
      <div class="control-group">
        <strong>JSON 数据源</strong>
        {source_controls}
      </div>
    </div>
  </header>
  <main>
    {warning}
    <div class="map">{svg}</div>
    <div class="panel">
      <section>
        <h2>数据源</h2>
        <table>
          <thead><tr><th>数据源</th><th>内容</th></tr></thead>
          <tbody>{source_rows}</tbody>
        </table>
      </section>
      <section>
        <h2>图层统计</h2>
        <table>
          <thead><tr><th>数据源</th><th>图层</th><th>轴线</th><th>结构柱</th><th>多段线</th></tr></thead>
          <tbody>{layer_rows}</tbody>
        </table>
      </section>
      <section style="grid-column: 1 / -1;">
        <h2>轴线明细（每个数据源前 200 条）</h2>
        <table>
          <thead><tr><th>数据源</th><th>#</th><th>轴号</th><th>图层</th><th>类型</th><th>长度</th><th>BBox</th><th>点数</th></tr></thead>
          <tbody>{axis_detail_rows}</tbody>
        </table>
      </section>
      <section style="grid-column: 1 / -1;">
        <h2>结构柱明细（每个数据源前 300 条）</h2>
        <table>
          <thead><tr><th>数据源</th><th>#</th><th>柱 ID</th><th>图层</th><th>来源</th><th>面积</th><th>宽 x 高</th><th>BBox</th><th>点数</th></tr></thead>
          <tbody>{column_detail_rows}</tbody>
        </table>
      </section>
    </div>
  </main>
  <script>
    function applyToggle(input) {{
      document.body.classList.toggle(input.dataset.toggleClass, !input.checked);
    }}
    document.querySelectorAll("input[data-toggle-class]").forEach((input) => {{
      applyToggle(input);
      input.addEventListener("change", () => applyToggle(input));
    }});
  </script>
</body>
</html>
"""


def _source_control(source: ReviewSource) -> str:
    color = _source_color(source.index)
    return (
        f'<label><input type="checkbox" data-toggle-class="hide-source-{source.index}" checked> '
        f'<span class="legend-dot" style="background:{color}"></span>{escape(source.name)}</label>'
    )


def _source_row(source: ReviewSource) -> str:
    return (
        f'<tr class="source-{source.index}"><td><code>{escape(str(source.path))}</code><br>{escape(source.name)}</td>'
        f"<td>axes: {len(source.axes)}<br>columns: {len(source.columns)}<br>"
        f"polylines: {len(source.polylines)}<br>texts: {len(source.texts)}</td></tr>"
    )


def _layer_row(source: ReviewSource) -> str:
    axis_counts = Counter(axis["layer"] for axis in source.axes)
    column_counts = Counter(column["layer"] for column in source.columns)
    polyline_counts = Counter(polyline["layer"] for polyline in source.polylines)
    layers = sorted(set(axis_counts) | set(column_counts) | set(polyline_counts))
    if not layers:
        return f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td colspan="4">无图层数据</td></tr>'
    return "\n".join(
        f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td>{escape(layer)}</td>'
        f"<td>{axis_counts.get(layer, 0)}</td><td>{column_counts.get(layer, 0)}</td><td>{polyline_counts.get(layer, 0)}</td></tr>"
        for layer in layers
    )


def _axis_rows(source: ReviewSource) -> str:
    rows = []
    for index, axis in enumerate(source.axes[:200], start=1):
        rows.append(_axis_row(source, index, axis, source.axis_labels.get(index - 1, ("", ""))))
    return "\n".join(rows)


def _column_rows(source: ReviewSource) -> str:
    rows = []
    for index, column in enumerate(source.columns[:300], start=1):
        rows.append(_column_row(source, index, column))
    return "\n".join(rows)


def _normalize_axis(axis: dict[str, Any]) -> dict[str, Any]:
    points = [_point(point) for point in axis.get("points", []) if _point(point) is not None]
    return {
        "layer": str(axis.get("layer") or "0"),
        "entity_type": str(axis.get("entity_type") or ""),
        "points": points,
        "bbox": axis.get("bbox"),
        "length": axis.get("length"),
    }


def _normalize_polyline(polyline: dict[str, Any]) -> dict[str, Any]:
    points = [_point(point) for point in polyline.get("points", []) if _point(point) is not None]
    return {
        "layer": str(polyline.get("layer") or "0"),
        "entity_type": str(polyline.get("entity_type") or ""),
        "closed": bool(polyline.get("closed")),
        "points": points,
        "bbox": polyline.get("bbox"),
    }


def _normalize_column(column: dict[str, Any]) -> dict[str, Any]:
    polygon = [_point(point) for point in column.get("polygon", []) if _point(point) is not None]
    center = _point(column.get("center"))
    return {
        "column_id": str(column.get("column_id") or ""),
        "layer": str(column.get("layer") or "0"),
        "entity_type": str(column.get("entity_type") or ""),
        "source": str(column.get("source") or ""),
        "polygon": polygon,
        "center": center,
        "bbox": column.get("bbox"),
        "area": column.get("area"),
        "width": column.get("width"),
        "height": column.get("height"),
        "drawable": bool(polygon or center is not None),
    }


def _normalize_text(text: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(text.get("text") or "").strip(),
        "layer": str(text.get("layer") or "0"),
        "position": _point(text.get("position")),
    }


def _point(value: Any) -> Point | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError):
        return None


def _bounds_for_sources(sources: list[ReviewSource]) -> BBox | None:
    points: list[Point] = []
    for source in sources:
        points.extend(point for axis in source.axes for point in axis["points"])
        points.extend(point for column in source.columns for point in column["polygon"])
        points.extend(column["center"] for column in source.columns if column["center"] is not None)
        points.extend(point for polyline in source.polylines for point in polyline["points"])
        points.extend(text["position"] for text in source.texts if text["position"] is not None)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if min_x == max_x:
        min_x -= 1.0
        max_x += 1.0
    if min_y == max_y:
        min_y -= 1.0
        max_y += 1.0
    return (min_x, min_y, max_x, max_y)


def _review_svg(sources: list[ReviewSource], bounds: BBox) -> str:
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    pad = max(width, height) * 0.03
    view_min_x = min_x - pad
    view_min_y = -(max_y + pad)
    view_width = width + pad * 2
    view_height = height + pad * 2
    stroke_width = max(width, height) / 1200.0
    font_size = max(width, height) / 90.0

    geometry = []
    labels = []
    for source in sources:
        color = _source_color(source.index)
        geometry.extend(_column_shape(source, column, color, stroke_width) for column in source.columns)
        geometry.extend(_polyline_shape(source, polyline, color, stroke_width) for polyline in source.polylines)
        geometry.extend(_axis_shape(source, axis, color, stroke_width) for axis in source.axes)
        labels.extend(
            _axis_endpoint_labels(source, axis, source.axis_labels.get(index, ("", "")), font_size)
            for index, axis in enumerate(source.axes)
        )
        labels.extend(_text_marker(source, text, font_size) for text in source.texts)

    return f"""<svg viewBox="{view_min_x:.3f} {view_min_y:.3f} {view_width:.3f} {view_height:.3f}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="JSON review map">
  <rect x="{view_min_x:.3f}" y="{view_min_y:.3f}" width="{view_width:.3f}" height="{view_height:.3f}" fill="#ffffff"/>
  <g transform="scale(1 -1)">
    {''.join(geometry)}
  </g>
  {''.join(labels)}
</svg>"""


def _axis_shape(source: ReviewSource, axis: dict[str, Any], color: str, stroke_width: float) -> str:
    title = escape(f'{source.name} / axes / {axis["layer"]} / {axis["entity_type"]}')
    points = axis["points"]
    if len(points) == 2:
        (x1, y1), (x2, y2) = points
        return (
            f'<line class="source-{source.index} kind-axes" x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
            f'stroke="{color}" stroke-width="{stroke_width:.3f}" stroke-linecap="round" opacity="0.88"><title>{title}</title></line>'
        )
    point_text = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    return (
        f'<polyline class="source-{source.index} kind-axes" points="{point_text}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width:.3f}" stroke-linecap="round" stroke-linejoin="round" opacity="0.88"><title>{title}</title></polyline>'
    )


def _polyline_shape(source: ReviewSource, polyline: dict[str, Any], color: str, stroke_width: float) -> str:
    points = polyline["points"]
    point_text = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    title = escape(f'{source.name} / polylines / {polyline["layer"]}')
    close = "Z" if polyline["closed"] else ""
    if polyline["closed"] and points:
        path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + f" {close}"
        return (
            f'<path class="source-{source.index} kind-polylines" d="{path}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_width * 0.35:.3f}" opacity="0.22"><title>{title}</title></path>'
        )
    return (
        f'<polyline class="source-{source.index} kind-polylines" points="{point_text}" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width * 0.35:.3f}" opacity="0.22"><title>{title}</title></polyline>'
    )


def _column_shape(source: ReviewSource, column: dict[str, Any], color: str, stroke_width: float) -> str:
    title = escape(f'{source.name} / columns / {column["column_id"]} / {column["layer"]}')
    points = column["polygon"]
    if len(points) >= 3:
        path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + " Z"
        return (
            f'<path class="source-{source.index} kind-columns" d="{path}" fill="{color}" fill-opacity="0.20" '
            f'stroke="{color}" stroke-width="{stroke_width * 0.75:.3f}" opacity="0.95"><title>{title}</title></path>'
        )
    center = column["center"]
    if center is None:
        return ""
    x, y = center
    radius = stroke_width * 3.0
    return (
        f'<circle class="source-{source.index} kind-columns" cx="{x:.3f}" cy="{y:.3f}" r="{radius:.3f}" '
        f'fill="{color}" fill-opacity="0.45" stroke="{color}" stroke-width="{stroke_width:.3f}"><title>{title}</title></circle>'
    )


def _axis_endpoint_labels(source: ReviewSource, axis: dict[str, Any], labels: tuple[str, str], font_size: float) -> str:
    if not axis["points"]:
        return ""
    start_label, end_label = labels
    shapes = []
    if start_label:
        shapes.append(_svg_text(source, axis["points"][0], start_label, font_size, class_name="kind-axis-labels"))
    if end_label:
        shapes.append(_svg_text(source, axis["points"][-1], end_label, font_size, class_name="kind-axis-labels"))
    return "".join(shapes)


def _text_marker(source: ReviewSource, text: dict[str, Any], font_size: float) -> str:
    position = text["position"]
    if position is None or not text["text"]:
        return ""
    return _svg_text(source, position, text["text"], font_size * 0.55, class_name="kind-texts")


def _svg_text(source: ReviewSource, point: Point, text: str, font_size: float, class_name: str) -> str:
    x, y = point
    return (
        f'<text class="source-{source.index} {class_name}" x="{x:.3f}" y="{-y:.3f}" font-size="{font_size:.3f}" '
        f'font-family="Arial, Microsoft YaHei, sans-serif" text-anchor="middle" dominant-baseline="central" '
        f'fill="#111827" stroke="#ffffff" stroke-width="{font_size * 0.18:.3f}" paint-order="stroke">'
        f"{escape(text)}</text>"
    )


def _empty_svg() -> str:
    return """<svg viewBox="0 0 900 420" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="No JSON geometry">
  <rect x="0" y="0" width="900" height="420" fill="#ffffff"/>
  <text x="450" y="210" text-anchor="middle" font-size="20" fill="#6b7280">未发现可绘制 JSON 数据</text>
</svg>"""


def _axis_row(source: ReviewSource, index: int, axis: dict[str, Any], labels: tuple[str, str]) -> str:
    bbox = axis.get("bbox")
    bbox_text = "-"
    if isinstance(bbox, list) and len(bbox) == 4:
        bbox_text = ", ".join(_format_number(value) for value in bbox)
    label_text = " / ".join(label for label in labels if label) or "-"
    return (
        f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td>{index}</td><td>{escape(label_text)}</td>'
        f"<td>{escape(axis['layer'])}</td><td>{escape(axis['entity_type'])}</td><td>{_format_number(axis.get('length'))}</td>"
        f"<td><code>{escape(bbox_text)}</code></td><td>{len(axis['points'])}</td></tr>"
    )


def _column_row(source: ReviewSource, index: int, column: dict[str, Any]) -> str:
    bbox = column.get("bbox")
    bbox_text = "-"
    if isinstance(bbox, list) and len(bbox) == 4:
        bbox_text = ", ".join(_format_number(value) for value in bbox)
    size_text = f"{_format_number(column.get('width'))} x {_format_number(column.get('height'))}"
    return (
        f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td>{index}</td>'
        f"<td>{escape(column['column_id'])}</td><td>{escape(column['layer'])}</td><td>{escape(column['source'])}</td>"
        f"<td>{_format_number(column.get('area'))}</td><td>{escape(size_text)}</td>"
        f"<td><code>{escape(bbox_text)}</code></td><td>{len(column['polygon'])}</td></tr>"
    )


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.2f}"


def _match_axis_endpoint_labels(axes: list[dict[str, Any]], texts: list[dict[str, Any]]) -> dict[int, tuple[str, str]]:
    candidates = [text for text in texts if _looks_like_axis_label(text["text"])]
    if not candidates:
        return {index: ("", "") for index in range(len(axes))}
    drawing_bounds = _bounds_for_axis_list(axes)
    max_distance = _label_match_distance(drawing_bounds)
    labels: dict[int, tuple[str, str]] = {}
    for index, axis in enumerate(axes):
        prefer_hyphen = axis.get("entity_type") == "ARC"
        start_label = _nearest_label(axis["points"][0], candidates, max_distance, prefer_hyphen=prefer_hyphen) if axis["points"] else None
        end_label = _nearest_label(axis["points"][-1], candidates, max_distance, prefer_hyphen=prefer_hyphen) if axis["points"] else None
        labels[index] = (start_label or "", end_label or "")
    return labels


def _bounds_for_axis_list(axes: list[dict[str, Any]]) -> BBox | None:
    points = [point for axis in axes for point in axis["points"]]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _looks_like_axis_label(text: str) -> bool:
    if not text or len(text) > 6:
        return False
    return bool(re.fullmatch(r"[A-Za-z]{1,3}|\d{1,3}|[A-Za-z]\d{1,2}|\d{1,2}[A-Za-z]|[A-Za-z]{1,3}-\d{1,3}", text))


def _label_match_distance(bounds: BBox | None) -> float:
    if bounds is None:
        return 8000.0
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    return max(8000.0, min(max(width, height) * 0.025, 20000.0))


def _nearest_label(point: Point, candidates: list[dict[str, Any]], max_distance: float, prefer_hyphen: bool = False) -> str | None:
    matches: list[tuple[float, str]] = []
    for candidate in candidates:
        position = candidate["position"]
        if position is None:
            continue
        distance = math.hypot(point[0] - position[0], point[1] - position[1])
        if distance <= max_distance:
            matches.append((distance, str(candidate["text"])))
    if not matches:
        return None
    if prefer_hyphen:
        hyphen_matches = [match for match in matches if "-" in match[1]]
        if hyphen_matches:
            return min(hyphen_matches, key=lambda item: item[0])[1]
    return min(matches, key=lambda item: item[0])[1]


def _source_color(index: int) -> str:
    palette = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be123c", "#4f46e5"]
    return palette[(index - 1) % len(palette)]


if __name__ == "__main__":
    raise SystemExit(main())
