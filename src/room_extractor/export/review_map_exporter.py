from __future__ import annotations

from html import escape
from pathlib import Path

from room_extractor.models.drawing import BBox, CadPolylineEntity, CadRawExtraction, Point
from room_extractor.models.room_candidate import RoomCandidate, RoomCandidateSet


STATUS_LABELS = {
    "matched": "严格匹配",
    "matched_fallback": "低置信度匹配",
    "auto_failed": "未匹配",
}


def export_room_candidate_review_html(
    cad_raw: CadRawExtraction,
    rooms: RoomCandidateSet,
    out_path: str | Path,
    title: str = "房间边界阶段检查图",
) -> Path:
    """Write a self-contained HTML/SVG review map for room candidates."""
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_room_candidate_review_html(cad_raw, rooms, title=title), encoding="utf-8")
    return output


def build_room_candidate_review_html(
    cad_raw: CadRawExtraction,
    rooms: RoomCandidateSet,
    title: str = "房间边界阶段检查图",
) -> str:
    bounds = _drawing_bounds(cad_raw, rooms)
    view_box = _view_box(bounds)
    context_svg = "\n".join(_context_polyline_svg(polyline) for polyline in cad_raw.polylines if polyline.points)
    room_svg = "\n".join(_room_svg(candidate) for candidate in rooms.room_candidates)
    sidebar = "\n".join(_room_list_item(candidate) for candidate in rooms.room_candidates)
    summary_items = _summary_html(rooms)
    escaped_title = escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      --bg: #f7f7f4;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #68737d;
      --line: #d0d5d8;
      --matched: #168a4a;
      --fallback: #d97706;
      --failed: #c62828;
      --selected: #0b5fff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    .shell {{
      display: grid;
      grid-template-columns: minmax(280px, 360px) 1fr;
      height: 100vh;
    }}
    aside {{
      overflow: auto;
      border-right: 1px solid #d9dde0;
      background: var(--panel);
      padding: 14px;
    }}
    main {{
      min-width: 0;
      display: flex;
      flex-direction: column;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 16px;
      border-bottom: 1px solid #d9dde0;
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.3;
    }}
    .source, .hint {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .summary {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 12px 0;
    }}
    .metric {{
      border: 1px solid #e0e4e7;
      border-radius: 6px;
      padding: 8px;
      background: #fbfbfa;
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
    }}
    .metric strong {{
      font-size: 18px;
    }}
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 13px;
    }}
    .controls label {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }}
    .list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .room-button {{
      width: 100%;
      text-align: left;
      border: 1px solid #dfe3e6;
      border-left-width: 5px;
      border-radius: 6px;
      background: #fff;
      padding: 8px;
      cursor: pointer;
      font: inherit;
      color: inherit;
    }}
    .room-button:hover, .room-button.selected {{
      border-color: var(--selected);
      background: #eef4ff;
    }}
    .room-button[data-status="matched"] {{ border-left-color: var(--matched); }}
    .room-button[data-status="matched_fallback"] {{ border-left-color: var(--fallback); }}
    .room-button[data-status="auto_failed"] {{ border-left-color: var(--failed); }}
    .room-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
    }}
    .room-meta {{
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }}
    .canvas-wrap {{
      flex: 1;
      min-height: 0;
      overflow: auto;
      background: #f4f2ed;
    }}
    svg {{
      width: 100%;
      height: 100%;
      display: block;
      background: #faf9f5;
    }}
    .context-line {{
      fill: none;
      stroke: #b9c0c5;
      stroke-width: 0.7;
      opacity: 0.36;
      vector-effect: non-scaling-stroke;
    }}
    .room-shape {{
      vector-effect: non-scaling-stroke;
      stroke-width: 2;
      cursor: pointer;
    }}
    .room-shape.matched {{
      fill: rgba(22, 138, 74, 0.14);
      stroke: var(--matched);
    }}
    .room-shape.matched_fallback {{
      fill: rgba(217, 119, 6, 0.13);
      stroke: var(--fallback);
      stroke-dasharray: 8 5;
    }}
    .label-dot {{
      vector-effect: non-scaling-stroke;
      stroke: #fff;
      stroke-width: 2;
      cursor: pointer;
    }}
    .label-dot.matched {{ fill: var(--matched); }}
    .label-dot.matched_fallback {{ fill: var(--fallback); }}
    .label-dot.auto_failed {{ fill: var(--failed); }}
    .label-text {{
      font-size: 620px;
      paint-order: stroke;
      stroke: #fff;
      stroke-width: 160px;
      fill: #111827;
      pointer-events: none;
    }}
    .failed-cross {{
      stroke: var(--failed);
      stroke-width: 3;
      vector-effect: non-scaling-stroke;
    }}
    .selected-shape {{
      stroke: var(--selected) !important;
      stroke-width: 4 !important;
      opacity: 1 !important;
    }}
    .selected-dot {{
      fill: var(--selected) !important;
      r: 520;
    }}
    body.hide-context .context-line {{ display: none; }}
    body.hide-matched .matched {{ display: none; }}
    body.hide-fallback .matched_fallback {{ display: none; }}
    body.hide-failed .auto_failed, body.hide-failed .failed-cross {{ display: none; }}
    body.hide-labels .label-text, body.hide-labels .label-dot, body.hide-labels .failed-cross {{ display: none; }}
    @media (max-width: 900px) {{
      .shell {{ grid-template-columns: 1fr; grid-template-rows: 42vh 58vh; }}
      aside {{ border-right: 0; border-bottom: 1px solid #d9dde0; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>{escaped_title}</h1>
      <div class="source">CAD：{escape(cad_raw.source_file)}<br>候选：{escape(rooms.source_file)}</div>
      <div class="summary">{summary_items}</div>
      <div class="hint">点击左侧房间或图中轮廓可定位；滚轮/触控板可缩放浏览器页面，SVG 支持浏览器原生缩放。</div>
      <hr>
      <div class="list">{sidebar}</div>
    </aside>
    <main>
      <header>
        <div class="controls">
          <label><input type="checkbox" data-toggle="hide-context" checked> CAD底图</label>
          <label><input type="checkbox" data-toggle="hide-matched" checked> 严格匹配</label>
          <label><input type="checkbox" data-toggle="hide-fallback" checked> 低置信度</label>
          <label><input type="checkbox" data-toggle="hide-failed" checked> 未匹配</label>
          <label><input type="checkbox" data-toggle="hide-labels" checked> 标签</label>
        </div>
        <div class="hint">绿色=严格匹配，橙色=低置信度，红色=未匹配</div>
      </header>
      <div class="canvas-wrap">
        <svg id="map" viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg">
          <g id="cad-context">{context_svg}</g>
          <g id="room-overlay">{room_svg}</g>
        </svg>
      </div>
    </main>
  </div>
  <script>
    const svg = document.getElementById('map');
    const baseViewBox = svg.getAttribute('viewBox');
    function selectRoom(id, bbox) {{
      document.querySelectorAll('.selected-shape').forEach(el => el.classList.remove('selected-shape'));
      document.querySelectorAll('.selected-dot').forEach(el => el.classList.remove('selected-dot'));
      document.querySelectorAll('.room-button.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll(`[data-room-id="${{id}}"]`).forEach(el => {{
        if (el.classList.contains('room-shape')) el.classList.add('selected-shape');
        if (el.classList.contains('label-dot')) el.classList.add('selected-dot');
        if (el.classList.contains('room-button')) el.classList.add('selected');
      }});
      if (bbox) {{
        const pad = Math.max(bbox[2] - bbox[0], bbox[3] - bbox[1], 2000) * 0.8;
        const x = bbox[0] - pad;
        const y = -bbox[3] - pad;
        const w = Math.max(1, bbox[2] - bbox[0] + pad * 2);
        const h = Math.max(1, bbox[3] - bbox[1] + pad * 2);
        svg.setAttribute('viewBox', `${{x}} ${{y}} ${{w}} ${{h}}`);
      }}
    }}
    document.querySelectorAll('[data-room-id]').forEach(el => {{
      el.addEventListener('click', () => {{
        const bbox = el.dataset.bbox ? JSON.parse(el.dataset.bbox) : null;
        selectRoom(el.dataset.roomId, bbox);
      }});
    }});
    document.querySelectorAll('[data-toggle]').forEach(input => {{
      input.addEventListener('change', () => {{
        document.body.classList.toggle(input.dataset.toggle, !input.checked);
      }});
    }});
    svg.addEventListener('dblclick', () => svg.setAttribute('viewBox', baseViewBox));
  </script>
</body>
</html>
"""


def _drawing_bounds(cad_raw: CadRawExtraction, rooms: RoomCandidateSet) -> BBox:
    bboxes: list[BBox] = []
    bboxes.extend(polyline.bbox for polyline in cad_raw.polylines if polyline.bbox is not None)
    bboxes.extend(candidate.label_bbox for candidate in rooms.room_candidates)
    bboxes.extend(
        candidate.boundary.bbox_cad
        for candidate in rooms.room_candidates
        if candidate.boundary is not None
    )
    if not bboxes:
        return (0.0, 0.0, 1000.0, 1000.0)
    min_x = min(bbox[0] for bbox in bboxes)
    min_y = min(bbox[1] for bbox in bboxes)
    max_x = max(bbox[2] for bbox in bboxes)
    max_y = max(bbox[3] for bbox in bboxes)
    return (float(min_x), float(min_y), float(max_x), float(max_y))


def _view_box(bounds: BBox) -> str:
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(width, height) * 0.03
    return f"{min_x - pad:.3f} {-max_y - pad:.3f} {width + pad * 2:.3f} {height + pad * 2:.3f}"


def _context_polyline_svg(polyline: CadPolylineEntity) -> str:
    points = _svg_points(polyline.points)
    tag = "polygon" if polyline.closed else "polyline"
    return f'<{tag} class="context-line" points="{points}" />'


def _room_svg(candidate: RoomCandidate) -> str:
    parts: list[str] = []
    room_id = escape(candidate.room_candidate_id)
    status = escape(candidate.status)
    bbox = candidate.boundary.bbox_cad if candidate.boundary else candidate.label_bbox
    bbox_json = _bbox_json(bbox)
    if candidate.boundary is not None:
        points = _svg_points(candidate.boundary.polygon_cad)
        parts.append(
            f'<polygon class="room-shape {status}" data-room-id="{room_id}" data-bbox="{bbox_json}" points="{points}">'
            f"<title>{_room_title(candidate)}</title></polygon>"
        )
    if candidate.status == "auto_failed":
        x, y = candidate.label_center
        size = max((candidate.label_bbox[2] - candidate.label_bbox[0]), 900.0) * 0.35
        parts.append(
            f'<line class="failed-cross auto_failed" x1="{x - size:.3f}" y1="{-y - size:.3f}" '
            f'x2="{x + size:.3f}" y2="{-y + size:.3f}" />'
        )
        parts.append(
            f'<line class="failed-cross auto_failed" x1="{x - size:.3f}" y1="{-y + size:.3f}" '
            f'x2="{x + size:.3f}" y2="{-y - size:.3f}" />'
        )
    x, y = candidate.label_center
    parts.append(
        f'<circle class="label-dot {status}" data-room-id="{room_id}" data-bbox="{bbox_json}" '
        f'cx="{x:.3f}" cy="{-y:.3f}" r="350"><title>{_room_title(candidate)}</title></circle>'
    )
    parts.append(
        f'<text class="label-text {status}" x="{x + 460:.3f}" y="{-y - 460:.3f}">{escape(_label_text(candidate))}</text>'
    )
    return "\n".join(parts)


def _room_list_item(candidate: RoomCandidate) -> str:
    room_id = escape(candidate.room_candidate_id)
    status = escape(candidate.status)
    bbox = candidate.boundary.bbox_cad if candidate.boundary else candidate.label_bbox
    issue_codes = ", ".join(issue.issue_code for issue in candidate.issues) or "无"
    boundary = candidate.boundary.boundary_id if candidate.boundary else "无"
    return (
        f'<button class="room-button" data-room-id="{room_id}" data-status="{status}" data-bbox="{_bbox_json(bbox)}">'
        f'<div class="room-title"><span>{escape(_label_text(candidate))}</span><span>{escape(STATUS_LABELS.get(candidate.status, candidate.status))}</span></div>'
        f'<div class="room-meta">boundary: {escape(boundary)}<br>confidence: {candidate.confidence:.2f}<br>issues: {escape(issue_codes)}</div>'
        "</button>"
    )


def _summary_html(rooms: RoomCandidateSet) -> str:
    summary = rooms.summary or {}
    status_counts = summary.get("status_counts", {})
    metrics = [
        ("边界候选", summary.get("boundary_candidate_count", len(rooms.boundary_candidates))),
        ("房间候选", summary.get("room_candidate_count", len(rooms.room_candidates))),
        ("严格匹配", status_counts.get("matched", 0) if isinstance(status_counts, dict) else 0),
        ("低置信度", status_counts.get("matched_fallback", 0) if isinstance(status_counts, dict) else 0),
        ("未匹配", status_counts.get("auto_failed", 0) if isinstance(status_counts, dict) else 0),
        ("完整匹配", summary.get("complete_matched_count", 0)),
    ]
    return "\n".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in metrics
    )


def _svg_points(points: list[Point]) -> str:
    return " ".join(f"{x:.3f},{-y:.3f}" for x, y in points)


def _bbox_json(bbox: BBox) -> str:
    return "[" + ",".join(f"{value:.3f}" for value in bbox) + "]"


def _label_text(candidate: RoomCandidate) -> str:
    parts = [candidate.room_candidate_id.replace("room_candidate_", "#")]
    if candidate.room_number:
        parts.append(candidate.room_number)
    if candidate.room_name:
        parts.append(candidate.room_name)
    if candidate.area_text is not None:
        parts.append(f"{candidate.area_text:g}{candidate.area_unit}")
    return " ".join(parts)


def _room_title(candidate: RoomCandidate) -> str:
    issue_codes = ", ".join(issue.issue_code for issue in candidate.issues) or "无"
    boundary = candidate.boundary.boundary_id if candidate.boundary else "无"
    return escape(
        f"{_label_text(candidate)} | status={candidate.status} | boundary={boundary} | issues={issue_codes}"
    )
