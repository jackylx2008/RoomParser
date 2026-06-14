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
    boundaries: list[dict[str, Any]]
    rooms: list[dict[str, Any]]
    label_texts: list[dict[str, Any]]
    axis_labels: dict[int, tuple[str, str]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate an HTML/SVG manual review page from one or more JSON files.")
    add_json_review_html_arguments(parser)
    return parser


def add_json_review_html_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
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
    parser.add_argument("--include-boundaries", action="store_true", help="Write room boundary candidates into the HTML overlay.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_json_review_html(args)


def run_json_review_html(args: argparse.Namespace) -> int:
    input_paths = [Path(path) for path in (args.json or [str(DEFAULT_INPUT)])]
    output_path = Path(args.out)
    sources = [
        _load_source(
            index,
            path,
            include_polylines=bool(args.include_polylines),
            include_texts=bool(args.include_texts),
            include_boundaries=bool(args.include_boundaries),
        )
        for index, path in enumerate(input_paths, start=1)
    ]
    html = build_json_review_html(sources, title=str(args.title))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def _load_source(index: int, path: Path, include_polylines: bool, include_texts: bool, include_boundaries: bool) -> ReviewSource:
    payload = json.loads(path.read_text(encoding="utf-8"))
    name = str(payload.get("source_file") or path.name)
    axes = [_normalize_axis(axis) for axis in payload.get("axes", []) if _normalize_axis(axis)["points"]]
    columns = [_normalize_column(column) for column in payload.get("columns", []) if _normalize_column(column)["drawable"]]
    all_boundaries = [_normalize_boundary(boundary) for boundary in payload.get("boundary_candidates", [])]
    boundaries = [boundary for boundary in all_boundaries if include_boundaries and boundary["points"]]
    rooms = [_normalize_room(room) for room in _room_items(payload) if _normalize_room(room)["drawable"]]
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
        boundaries=boundaries,
        rooms=rooms,
        label_texts=label_texts,
        axis_labels=axis_labels,
    )


def build_json_review_html(sources: list[ReviewSource], title: str) -> str:
    bounds = _bounds_for_sources(sources)
    svg = _empty_svg() if bounds is None else _review_svg(sources, bounds)
    source_controls = "\n".join(_source_control(source) for source in sources)
    source_rows = "\n".join(_source_row(source) for source in sources)
    layer_rows = "\n".join(_layer_row(source) for source in sources)
    room_detail_rows = "\n".join(_room_rows(source) for source in sources)
    if not room_detail_rows:
        room_detail_rows = '<tr><td colspan="10">未发现可绘制房间识别结果。</td></tr>'
    axis_detail_rows = "\n".join(_axis_rows(source) for source in sources)
    if not axis_detail_rows:
        axis_detail_rows = '<tr><td colspan="8">未发现可绘制轴线。</td></tr>'
    column_detail_rows = "\n".join(_column_rows(source) for source in sources)
    if not column_detail_rows:
        column_detail_rows = '<tr><td colspan="9">未发现可绘制结构柱。</td></tr>'

    warning = ""
    if not any(source.axes or source.columns or source.polylines or source.texts or source.boundaries or source.rooms for source in sources):
        warning = '<div class="warning">输入 JSON 中没有可绘制的 axes、columns、polylines、texts、boundary_candidates 或 rooms。</div>'

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
      position: relative;
      overflow: hidden;
      background: #ffffff;
      border: 1px solid #d8dee9;
      border-radius: 6px;
      height: min(72vh, 860px);
      min-height: 520px;
      touch-action: none;
      user-select: none;
    }}
    .map-toolbar {{
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 3;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 6px;
      border: 1px solid #d8dee9;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.94);
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
      font-size: 12px;
    }}
    .map-toolbar button {{
      min-width: 30px;
      height: 28px;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      background: #ffffff;
      color: #1f2933;
      cursor: pointer;
      font: inherit;
      line-height: 1;
    }}
    .map-toolbar button:hover {{
      background: #f3f4f6;
    }}
    .zoom-readout {{
      min-width: 48px;
      text-align: center;
      font-variant-numeric: tabular-nums;
      color: #4b5563;
    }}
    .map-hint {{
      position: absolute;
      left: 12px;
      bottom: 10px;
      z-index: 3;
      padding: 5px 8px;
      border-radius: 4px;
      background: rgba(255, 255, 255, 0.88);
      color: #4b5563;
      font-size: 12px;
      pointer-events: none;
    }}
    svg {{
      display: block;
      width: 100%;
      height: 100%;
      background: #ffffff;
      cursor: grab;
    }}
    svg.is-panning {{
      cursor: grabbing;
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
    body.hide-boundaries .kind-boundaries,
    body.hide-rooms .kind-rooms,
    body.hide-room-labels .kind-room-labels,
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
        <label><input type="checkbox" data-toggle-class="hide-rooms" checked> 房间识别结果</label>
        <label><input type="checkbox" data-toggle-class="hide-room-labels" checked> 房间标注</label>
        <label><input type="checkbox" data-toggle-class="hide-boundaries"> 边界候选（需 --include-boundaries）</label>
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
    <div class="map" data-map>
      <div class="map-toolbar" aria-label="地图缩放工具">
        <button type="button" data-zoom-out title="缩小">-</button>
        <span class="zoom-readout" data-zoom-readout>100%</span>
        <button type="button" data-zoom-in title="放大">+</button>
        <button type="button" data-zoom-reset title="重置视图">重置</button>
      </div>
      <div class="map-hint">滚轮缩放，拖拽平移，双击重置</div>
      {svg}
    </div>
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
        <h2>房间识别明细（每个数据源前 500 条）</h2>
        <table>
          <thead><tr><th>数据源</th><th>#</th><th>房间ID</th><th>房号</th><th>房名</th><th>类别</th><th>状态</th><th>匹配方式</th><th>置信度</th><th>边界/图层</th><th>问题</th></tr></thead>
          <tbody>{room_detail_rows}</tbody>
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

    function installMapZoom(container) {{
      const svg = container.querySelector("svg");
      if (!svg) return;
      const readout = container.querySelector("[data-zoom-readout]");
      const zoomIn = container.querySelector("[data-zoom-in]");
      const zoomOut = container.querySelector("[data-zoom-out]");
      const zoomReset = container.querySelector("[data-zoom-reset]");
      const initialBox = parseViewBox(svg);
      if (!initialBox) return;
      let viewBox = {{ ...initialBox }};
      let isPanning = false;
      let panStart = null;
      const minZoom = 0.25;
      const maxZoom = 80;
      const stableStrokeElements = Array.from(svg.querySelectorAll("[data-base-stroke-width]"));
      const stableTextElements = Array.from(svg.querySelectorAll("[data-base-font-size]"));
      const stableRadiusElements = Array.from(svg.querySelectorAll("[data-base-radius]"));

      function parseViewBox(target) {{
        const value = target.getAttribute("viewBox");
        if (!value) return null;
        const parts = value.trim().split(/[\\s,]+/).map(Number);
        if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
        return {{ x: parts[0], y: parts[1], width: parts[2], height: parts[3] }};
      }}

      function applyViewBox() {{
        svg.setAttribute("viewBox", `${{viewBox.x}} ${{viewBox.y}} ${{viewBox.width}} ${{viewBox.height}}`);
        const zoom = initialBox.width / viewBox.width;
        scaleStableStyles(zoom);
        if (readout) {{
          readout.textContent = `${{Math.round(zoom * 100)}}%`;
        }}
      }}

      function scaledValue(value, zoom) {{
        const number = Number(value);
        if (!Number.isFinite(number)) return null;
        return String(number / zoom);
      }}

      function scaleStableStyles(zoom) {{
        if (!Number.isFinite(zoom) || zoom <= 0) return;
        stableStrokeElements.forEach((element) => {{
          const strokeWidth = scaledValue(element.dataset.baseStrokeWidth, zoom);
          if (strokeWidth !== null) {{
            element.setAttribute("stroke-width", strokeWidth);
          }}
          if (element.dataset.baseDasharray) {{
            const dasharray = element.dataset.baseDasharray
              .split(/\\s+/)
              .map((value) => scaledValue(value, zoom))
              .filter((value) => value !== null)
              .join(" ");
            if (dasharray) {{
              element.setAttribute("stroke-dasharray", dasharray);
            }}
          }}
        }});
        stableTextElements.forEach((element) => {{
          const fontSize = scaledValue(element.dataset.baseFontSize, zoom);
          const strokeWidth = scaledValue(element.dataset.baseStrokeWidth, zoom);
          if (fontSize !== null) {{
            element.setAttribute("font-size", fontSize);
          }}
          if (strokeWidth !== null) {{
            element.setAttribute("stroke-width", strokeWidth);
          }}
        }});
        stableRadiusElements.forEach((element) => {{
          const radius = scaledValue(element.dataset.baseRadius, zoom);
          if (radius !== null) {{
            element.setAttribute("r", radius);
          }}
        }});
      }}

      function clientToSvgPoint(clientX, clientY) {{
        const rect = svg.getBoundingClientRect();
        const rx = rect.width ? (clientX - rect.left) / rect.width : 0.5;
        const ry = rect.height ? (clientY - rect.top) / rect.height : 0.5;
        return {{
          x: viewBox.x + rx * viewBox.width,
          y: viewBox.y + ry * viewBox.height,
          rx,
          ry,
        }};
      }}

      function zoomAt(clientX, clientY, factor) {{
        const currentZoom = initialBox.width / viewBox.width;
        const nextZoom = Math.min(maxZoom, Math.max(minZoom, currentZoom / factor));
        const effectiveFactor = currentZoom / nextZoom;
        const anchor = clientToSvgPoint(clientX, clientY);
        const nextWidth = initialBox.width / nextZoom;
        const nextHeight = initialBox.height / nextZoom;
        viewBox = {{
          x: anchor.x - anchor.rx * nextWidth,
          y: anchor.y - anchor.ry * nextHeight,
          width: nextWidth,
          height: nextHeight,
        }};
        if (Number.isFinite(effectiveFactor)) {{
          applyViewBox();
        }}
      }}

      function zoomFromCenter(factor) {{
        const rect = svg.getBoundingClientRect();
        zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
      }}

      function resetView() {{
        viewBox = {{ ...initialBox }};
        applyViewBox();
      }}

      svg.addEventListener("wheel", (event) => {{
        event.preventDefault();
        const factor = Math.exp(event.deltaY * 0.0015);
        zoomAt(event.clientX, event.clientY, factor);
      }}, {{ passive: false }});

      svg.addEventListener("pointerdown", (event) => {{
        if (event.button !== 0) return;
        isPanning = true;
        panStart = {{
          clientX: event.clientX,
          clientY: event.clientY,
          viewBox: {{ ...viewBox }},
        }};
        svg.classList.add("is-panning");
        svg.setPointerCapture(event.pointerId);
      }});

      svg.addEventListener("pointermove", (event) => {{
        if (!isPanning || !panStart) return;
        const rect = svg.getBoundingClientRect();
        const dx = rect.width ? (event.clientX - panStart.clientX) / rect.width * panStart.viewBox.width : 0;
        const dy = rect.height ? (event.clientY - panStart.clientY) / rect.height * panStart.viewBox.height : 0;
        viewBox = {{
          x: panStart.viewBox.x - dx,
          y: panStart.viewBox.y - dy,
          width: panStart.viewBox.width,
          height: panStart.viewBox.height,
        }};
        applyViewBox();
      }});

      function endPan(event) {{
        if (!isPanning) return;
        isPanning = false;
        panStart = null;
        svg.classList.remove("is-panning");
        if (event && svg.hasPointerCapture(event.pointerId)) {{
          svg.releasePointerCapture(event.pointerId);
        }}
      }}

      svg.addEventListener("pointerup", endPan);
      svg.addEventListener("pointercancel", endPan);
      svg.addEventListener("dblclick", resetView);
      if (zoomIn) zoomIn.addEventListener("click", () => zoomFromCenter(1 / 1.6));
      if (zoomOut) zoomOut.addEventListener("click", () => zoomFromCenter(1.6));
      if (zoomReset) zoomReset.addEventListener("click", resetView);
      applyViewBox();
    }}

    document.querySelectorAll("[data-map]").forEach(installMapZoom);
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
        f"rooms: {len(source.rooms)}<br>boundaries: {len(source.boundaries)}<br>"
        f"polylines: {len(source.polylines)}<br>texts: {len(source.texts)}</td></tr>"
    )


def _layer_row(source: ReviewSource) -> str:
    axis_counts = Counter(axis["layer"] for axis in source.axes)
    column_counts = Counter(column["layer"] for column in source.columns)
    polyline_counts = Counter(polyline["layer"] for polyline in source.polylines)
    boundary_counts = Counter(boundary["layer"] for boundary in source.boundaries)
    room_counts = Counter(room["layer"] for room in source.rooms if room["layer"])
    layers = sorted(set(axis_counts) | set(column_counts) | set(polyline_counts) | set(boundary_counts) | set(room_counts))
    if not layers:
        return f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td colspan="4">无图层数据</td></tr>'
    return "\n".join(
        f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td>{escape(layer)}</td>'
        f"<td>{axis_counts.get(layer, 0)}</td><td>{column_counts.get(layer, 0)}</td>"
        f"<td>{polyline_counts.get(layer, 0) + boundary_counts.get(layer, 0) + room_counts.get(layer, 0)}</td></tr>"
        for layer in layers
    )


def _room_rows(source: ReviewSource) -> str:
    rows = []
    for index, room in enumerate(source.rooms[:500], start=1):
        rows.append(_room_row(source, index, room))
    return "\n".join(rows)


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


def _room_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("room_candidates"), list):
        return payload["room_candidates"]
    if isinstance(payload.get("rooms"), list):
        return payload["rooms"]
    return []


def _normalize_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    points = [_point(point) for point in boundary.get("polygon_cad", []) if _point(point) is not None]
    return {
        "boundary_id": str(boundary.get("boundary_id") or ""),
        "layer": str(boundary.get("layer") or ""),
        "points": points,
        "area": boundary.get("area_cad"),
        "metadata": boundary.get("metadata") or {},
    }


def _normalize_room(room: dict[str, Any]) -> dict[str, Any]:
    if "room_candidate_id" in room:
        boundary = room.get("boundary") or {}
        points = [_point(point) for point in boundary.get("polygon_cad", []) if _point(point) is not None]
        label_center = _point(room.get("label_center"))
        issue_codes = [str(issue.get("issue_code") or "") for issue in room.get("issues", []) if isinstance(issue, dict)]
        return {
            "room_id": str(room.get("room_candidate_id") or ""),
            "room_number": str(room.get("room_number") or ""),
            "room_name": str(room.get("room_name") or ""),
            "room_category": str(room.get("room_category") or ""),
            "status": str(room.get("status") or ""),
            "match_method": str(room.get("match_method") or ""),
            "confidence": room.get("confidence"),
            "boundary_id": str(boundary.get("boundary_id") or ""),
            "layer": str(boundary.get("layer") or ""),
            "points": points,
            "label_center": label_center,
            "issue_codes": issue_codes,
            "drawable": bool(points or label_center is not None),
        }
    basic_info = room.get("basic_info") or {}
    geometry = room.get("geometry") or {}
    review = room.get("review") or {}
    evidence = room.get("evidence") or {}
    cad_source = evidence.get("cad_source") or {}
    points = [_point(point) for point in geometry.get("polygon_cad", []) if _point(point) is not None]
    issue_codes = [str(issue.get("issue_code") or "") for issue in room.get("issues", []) if isinstance(issue, dict)]
    return {
        "room_id": str(room.get("room_uid") or ""),
        "room_number": str(basic_info.get("room_number") or ""),
        "room_name": str(basic_info.get("room_name") or ""),
        "room_category": str(basic_info.get("room_category") or ""),
        "status": str(review.get("status") or room.get("final_status") or ""),
        "match_method": str(geometry.get("geometry_source") or ""),
        "confidence": (room.get("confidence") or {}).get("overall"),
        "boundary_id": str(cad_source.get("boundary_id") or ""),
        "layer": str(cad_source.get("boundary_layer") or ""),
        "points": points,
        "label_center": None,
        "issue_codes": issue_codes,
        "drawable": bool(points),
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
        points.extend(point for boundary in source.boundaries for point in boundary["points"])
        points.extend(point for room in source.rooms for point in room["points"])
        points.extend(room["label_center"] for room in source.rooms if room["label_center"] is not None)
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
        geometry.extend(_boundary_shape(source, boundary, stroke_width) for boundary in source.boundaries)
        geometry.extend(_room_shape(source, room, stroke_width) for room in source.rooms)
        geometry.extend(_column_shape(source, column, stroke_width) for column in source.columns)
        geometry.extend(_polyline_shape(source, polyline, color, stroke_width) for polyline in source.polylines)
        geometry.extend(_axis_shape(source, axis, color, stroke_width) for axis in source.axes)
        labels.extend(
            _axis_endpoint_labels(source, axis, source.axis_labels.get(index, ("", "")), font_size)
            for index, axis in enumerate(source.axes)
        )
        labels.extend(_text_marker(source, text, font_size) for text in source.texts)
        labels.extend(_room_label(source, room, font_size) for room in source.rooms)

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
    base_stroke = f"{stroke_width:.3f}"
    if len(points) == 2:
        (x1, y1), (x2, y2) = points
        return (
            f'<line class="source-{source.index} kind-axes" x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
            f'stroke="{color}" stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" '
            f'stroke-linecap="round" opacity="0.88"><title>{title}</title></line>'
        )
    point_text = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    return (
        f'<polyline class="source-{source.index} kind-axes" points="{point_text}" fill="none" stroke="{color}" '
        f'stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity="0.88"><title>{title}</title></polyline>'
    )


def _polyline_shape(source: ReviewSource, polyline: dict[str, Any], color: str, stroke_width: float) -> str:
    points = polyline["points"]
    point_text = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    title = escape(f'{source.name} / polylines / {polyline["layer"]}')
    close = "Z" if polyline["closed"] else ""
    base_stroke = f"{stroke_width * 0.35:.3f}"
    if polyline["closed"] and points:
        path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + f" {close}"
        return (
            f'<path class="source-{source.index} kind-polylines" d="{path}" fill="none" stroke="{color}" '
            f'stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" opacity="0.22"><title>{title}</title></path>'
        )
    return (
        f'<polyline class="source-{source.index} kind-polylines" points="{point_text}" fill="none" stroke="{color}" '
        f'stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" opacity="0.22"><title>{title}</title></polyline>'
    )


def _boundary_shape(source: ReviewSource, boundary: dict[str, Any], stroke_width: float) -> str:
    points = boundary["points"]
    if len(points) < 3:
        return ""
    path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + " Z"
    title = escape(f'{source.name} / boundary / {boundary["boundary_id"]} / {boundary["layer"]}')
    base_stroke = f"{stroke_width * 0.45:.3f}"
    base_dasharray = f"{stroke_width * 2:.3f} {stroke_width * 1.5:.3f}"
    return (
        f'<path class="source-{source.index} kind-boundaries" d="{path}" fill="none" stroke="#64748b" '
        f'stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" '
        f'stroke-dasharray="{base_dasharray}" data-base-dasharray="{base_dasharray}" '
        f'opacity="0.42"><title>{title}</title></path>'
    )


def _room_shape(source: ReviewSource, room: dict[str, Any], stroke_width: float) -> str:
    points = room["points"]
    if len(points) < 3:
        return ""
    color = _room_status_color(room["status"])
    path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + " Z"
    title = escape(
        f'{source.name} / room / {room["room_id"]} / {room["room_number"]} {room["room_name"]} / {room["status"]}'
    )
    base_stroke = f"{stroke_width * 0.9:.3f}"
    return (
        f'<path class="source-{source.index} kind-rooms" d="{path}" fill="{color}" fill-opacity="0.16" '
        f'stroke="{color}" stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" '
        f'opacity="0.92"><title>{title}</title></path>'
    )


def _column_shape(source: ReviewSource, column: dict[str, Any], stroke_width: float) -> str:
    title = escape(f'{source.name} / columns / {column["column_id"]} / {column["layer"]}')
    fill_color = "#374151"
    stroke_color = "#111827"
    points = column["polygon"]
    if len(points) >= 3:
        path = "M " + " L ".join(f"{x:.3f} {y:.3f}" for x, y in points) + " Z"
        base_stroke = f"{stroke_width * 0.75:.3f}"
        return (
            f'<path class="source-{source.index} kind-columns" d="{path}" fill="{fill_color}" fill-opacity="0.62" '
            f'stroke="{stroke_color}" stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" '
            f'opacity="0.95"><title>{title}</title></path>'
        )
    center = column["center"]
    if center is None:
        return ""
    x, y = center
    radius = f"{stroke_width * 3.0:.3f}"
    base_stroke = f"{stroke_width:.3f}"
    return (
        f'<circle class="source-{source.index} kind-columns" cx="{x:.3f}" cy="{y:.3f}" r="{radius}" data-base-radius="{radius}" '
        f'fill="{fill_color}" fill-opacity="0.75" stroke="{stroke_color}" stroke-width="{base_stroke}" '
        f'data-base-stroke-width="{base_stroke}"><title>{title}</title></circle>'
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


def _room_label(source: ReviewSource, room: dict[str, Any], font_size: float) -> str:
    position = room["label_center"] or _polygon_center(room["points"])
    if position is None:
        return ""
    text = " ".join(value for value in [room["room_number"], room["room_name"]] if value) or room["room_id"]
    if not text:
        return ""
    return _svg_text(source, position, text, font_size * 0.9, class_name="kind-room-labels")


def _svg_text(source: ReviewSource, point: Point, text: str, font_size: float, class_name: str) -> str:
    x, y = point
    base_font = f"{font_size:.3f}"
    base_stroke = f"{font_size * 0.18:.3f}"
    return (
        f'<text class="source-{source.index} {class_name}" x="{x:.3f}" y="{-y:.3f}" '
        f'font-size="{base_font}" data-base-font-size="{base_font}" '
        f'font-family="Arial, Microsoft YaHei, sans-serif" text-anchor="middle" dominant-baseline="central" '
        f'fill="#111827" stroke="#ffffff" stroke-width="{base_stroke}" data-base-stroke-width="{base_stroke}" paint-order="stroke">'
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


def _room_row(source: ReviewSource, index: int, room: dict[str, Any]) -> str:
    issue_text = ", ".join(code for code in room["issue_codes"] if code) or "-"
    boundary_text = room["boundary_id"] or "-"
    if room["layer"]:
        boundary_text = f"{boundary_text}<br><code>{escape(room['layer'])}</code>"
    return (
        f'<tr class="source-{source.index}"><td>{escape(source.name)}</td><td>{index}</td>'
        f"<td>{escape(room['room_id'])}</td><td>{escape(room['room_number'])}</td><td>{escape(room['room_name'])}</td>"
        f"<td>{escape(room['room_category'])}</td>"
        f"<td>{escape(room['status'])}</td><td>{escape(room['match_method'])}</td>"
        f"<td>{_format_number(room.get('confidence'))}</td><td>{boundary_text}</td><td>{escape(issue_text)}</td></tr>"
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


def _room_status_color(status: str) -> str:
    if status in {"matched", "auto_passed"}:
        return "#16a34a"
    if status in {"matched_fallback", "pending_downstream_check", "pending_pdf_check"}:
        return "#f59e0b"
    if status in {"auto_failed", "cad_auto_draft"}:
        return "#dc2626"
    return "#2563eb"


def _polygon_center(points: list[Point]) -> Point | None:
    if not points:
        return None
    return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))


if __name__ == "__main__":
    raise SystemExit(main())
