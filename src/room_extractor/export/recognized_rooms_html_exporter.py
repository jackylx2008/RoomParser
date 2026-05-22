from __future__ import annotations

import os
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any

from room_extractor.models.drawing import BBox
from room_extractor.models.room import Room
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


STATUS_LABELS = {
    "auto_passed": "自动通过",
    "pending_pdf_check": "待PDF校核",
    "pending_downstream_check": "待下游校核",
    "pending_manual_review": "待人工审核",
}


def export_recognized_rooms_html(
    rooms_checked: RoomsPdfCheck,
    out_path: str | Path,
    title: str = "识别房间总览",
) -> Path:
    """Write an HTML overview for recognized rooms after the full machine chain."""
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_recognized_rooms_html(rooms_checked, output, title=title), encoding="utf-8")
    return output


def build_recognized_rooms_html(
    rooms_checked: RoomsPdfCheck,
    out_path: str | Path | None = None,
    title: str = "识别房间总览",
) -> str:
    output_dir = Path(out_path).parent if out_path else Path(".")
    rooms = rooms_checked.rooms
    overview = _overview_svg(rooms)
    room_cards = "\n".join(_room_card(room, index, output_dir) for index, room in enumerate(rooms, start=1))
    room_panels = "\n".join(_room_panel(room, index, output_dir) for index, room in enumerate(rooms, start=1))
    summary = _summary_html(rooms_checked)
    escaped_title = escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      --bg: #f5f6f7;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #66717b;
      --line: #d9dde2;
      --ok: #19764b;
      --review: #d97706;
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
      grid-template-columns: minmax(340px, 430px) 1fr;
      height: 100vh;
    }}
    aside {{
      min-width: 0;
      overflow: auto;
      border-right: 1px solid var(--line);
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
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.3;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 15px;
      line-height: 1.3;
    }}
    .source, .hint, .meta, .reason {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
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
    .metric strong {{ font-size: 18px; }}
    .overview-map {{
      width: 100%;
      height: 100%;
      display: block;
      background: #faf9f5;
    }}
    .overview-room {{
      vector-effect: non-scaling-stroke;
      stroke-width: 1.5;
      cursor: pointer;
      fill: rgba(25, 118, 75, 0.12);
      stroke: var(--ok);
    }}
    .overview-room.needs-review {{
      fill: rgba(217, 119, 6, 0.14);
      stroke: var(--review);
    }}
    .overview-room.no-image {{
      stroke-dasharray: 7 4;
    }}
    .overview-room.selected-room {{
      fill: rgba(11, 95, 255, 0.22);
      stroke: var(--selected);
      stroke-width: 4;
    }}
    .overview-label {{
      font-size: 620px;
      fill: #1f2933;
      paint-order: stroke;
      stroke: #fff;
      stroke-width: 150px;
      pointer-events: none;
    }}
    .canvas-wrap {{
      flex: 1;
      min-height: 0;
      overflow: auto;
      background: #f4f2ed;
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
    .room-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .room-card {{
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
    .room-card:hover, .room-card.selected {{
      border-color: var(--selected);
      background: #eef4ff;
    }}
    .room-card[data-review="true"] {{ border-left-color: var(--review); }}
    .room-card[data-review="false"] {{ border-left-color: var(--ok); }}
    .room-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
    }}
    .room-title span:first-child {{ overflow-wrap: anywhere; }}
    .room-panel {{
      display: none;
    }}
    .room-panel.active {{ display: block; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      align-items: start;
    }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }}
    .image-wrap {{
      min-height: 220px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f0f2f3;
      border: 1px solid #d8dde2;
      border-radius: 6px;
      overflow: auto;
    }}
    .image-wrap img {{
      max-width: 100%;
      height: auto;
      display: block;
    }}
    .missing {{
      padding: 28px;
      text-align: center;
      color: var(--muted);
      font-size: 13px;
    }}
    .fields {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .field {{
      border: 1px solid #e0e4e7;
      border-radius: 6px;
      padding: 8px;
      background: #fbfbfa;
      min-width: 0;
    }}
    .field span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 3px;
    }}
    .field strong {{
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .chip {{
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      background: #edf1f4;
      color: #27313b;
    }}
    .chip.review {{ background: #fff3df; color: #9a5600; }}
    .chip.ok {{ background: #e9f6ef; color: var(--ok); }}
    .issue {{
      border: 1px solid #e5e8eb;
      border-left: 4px solid #aeb6be;
      border-radius: 6px;
      padding: 8px;
      margin-bottom: 6px;
      background: #fff;
    }}
    .issue[data-severity="high"] {{ border-left-color: var(--failed); }}
    .issue[data-severity="medium"] {{ border-left-color: var(--review); }}
    .issue-code {{
      font-weight: 700;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .mini-map {{
      width: 100%;
      height: 260px;
      display: block;
      background: #faf9f5;
      border: 1px solid #d8dde2;
      border-radius: 6px;
    }}
    .mini-polygon {{
      fill: rgba(11, 95, 255, 0.14);
      stroke: var(--selected);
      stroke-width: 2;
      vector-effect: non-scaling-stroke;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.45;
      color: #27313b;
    }}
    body.hide-review .overview-room.needs-review,
    body.hide-review .room-card[data-review="true"] {{ display: none; }}
    body.hide-auto .overview-room:not(.needs-review),
    body.hide-auto .room-card[data-review="false"] {{ display: none; }}
    body.hide-no-image .overview-room.no-image {{ display: none; }}
    body.hide-labels .overview-label {{ display: none; }}
    @media (max-width: 960px) {{
      .shell {{ grid-template-columns: 1fr; grid-template-rows: 48vh 52vh; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--line); }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>{escaped_title}</h1>
      <div class="source">CAD：{escape(rooms_checked.source_file)}<br>PDF：{escape(rooms_checked.pdf_source_file)}</div>
      <div class="summary">{summary}</div>
      <div class="hint">点击房间列表或右侧总图后，总图会定位到该房间，并在下方显示识别到的分图和证据。</div>
      <hr>
      <div id="selected-room-detail">{room_panels}</div>
      <hr>
      <div class="room-list">{room_cards}</div>
    </aside>
    <main>
      <header>
        <div class="controls">
          <label><input type="checkbox" data-toggle="hide-review" checked> 需复核</label>
          <label><input type="checkbox" data-toggle="hide-auto" checked> 自动通过</label>
          <label><input type="checkbox" data-toggle="hide-no-image" checked> 无分图</label>
          <label><input type="checkbox" data-toggle="hide-labels" checked> 标签</label>
        </div>
        <div class="hint">总图：全链路识别到的房间。双击总图可复位视图。</div>
      </header>
      <div class="canvas-wrap">
        {overview}
      </div>
    </main>
  </div>
  <script>
    const svg = document.getElementById('recognized-map');
    const baseViewBox = svg ? svg.getAttribute('viewBox') : null;
    function selectRoom(id) {{
      document.querySelectorAll('.room-card.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.room-panel.active').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.overview-room.selected-room').forEach(el => el.classList.remove('selected-room'));
      const card = document.querySelector(`.room-card[data-room-id="${{id}}"]`);
      const panel = document.querySelector(`.room-panel[data-room-id="${{id}}"]`);
      const overview = document.querySelector(`.overview-room[data-room-id="${{id}}"]`);
      if (card) card.classList.add('selected');
      if (panel) panel.classList.add('active');
      if (overview) overview.classList.add('selected-room');
      const bboxSource = overview || card;
      if (svg && bboxSource && bboxSource.dataset.bbox) {{
        const bbox = JSON.parse(bboxSource.dataset.bbox);
        if (bbox) {{
          const pad = Math.max(bbox[2] - bbox[0], bbox[3] - bbox[1], 2000) * 0.8;
          const x = bbox[0] - pad;
          const y = -bbox[3] - pad;
          const w = Math.max(1, bbox[2] - bbox[0] + pad * 2);
          const h = Math.max(1, bbox[3] - bbox[1] + pad * 2);
          svg.setAttribute('viewBox', `${{x}} ${{y}} ${{w}} ${{h}}`);
        }}
      }}
    }}
    document.querySelectorAll('.room-card, .overview-room').forEach(el => {{
      el.addEventListener('click', () => selectRoom(el.dataset.roomId));
    }});
    document.querySelectorAll('[data-toggle]').forEach(input => {{
      input.addEventListener('change', () => {{
        document.body.classList.toggle(input.dataset.toggle, !input.checked);
      }});
    }});
    if (svg && baseViewBox) {{
      svg.addEventListener('dblclick', () => svg.setAttribute('viewBox', baseViewBox));
    }}
    const first = document.querySelector('.room-card');
    if (first) selectRoom(first.dataset.roomId);
  </script>
</body>
</html>
"""


def _summary_html(rooms_checked: RoomsPdfCheck) -> str:
    rooms = rooms_checked.rooms
    ai_status = Counter(_ai_check(room).get("status", "none") for room in rooms)
    metrics = [
        ("房间总数", len(rooms)),
        ("有CAD几何", sum(1 for room in rooms if room.geometry.polygon_cad or room.geometry.bbox_cad)),
        ("有PDF分图", sum(1 for room in rooms if _image_path(room))),
        ("需人工复核", sum(1 for room in rooms if room.review.required)),
        ("AI成功", ai_status.get("ok", 0)),
        ("AI需复核", sum(1 for room in rooms if _ai_check(room).get("needs_review") is True)),
    ]
    return "\n".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in metrics
    )


def _overview_svg(rooms: list[Room]) -> str:
    drawable = [room for room in rooms if room.geometry.polygon_cad or room.geometry.bbox_cad]
    if not drawable:
        return '<div class="missing">缺少 CAD geometry，无法绘制总图。</div>'
    bounds = _combined_bounds(drawable)
    shapes = "\n".join(_overview_shape(room) for room in drawable)
    return f'<svg id="recognized-map" class="overview-map" viewBox="{_view_box(bounds)}" xmlns="http://www.w3.org/2000/svg">{shapes}</svg>'


def _overview_shape(room: Room) -> str:
    room_id = escape(room.room_uid)
    classes = ["overview-room"]
    if room.review.required:
        classes.append("needs-review")
    if not _image_path(room):
        classes.append("no-image")
    points = _room_points(room)
    title = escape(_room_label(room))
    bbox = _room_bbox(room)
    bbox_json = _bbox_json(bbox) if bbox is not None else "null"
    shape = (
        f'<polygon class="{" ".join(classes)}" data-room-id="{room_id}" '
        f'data-bbox="{bbox_json}" points="{points}"><title>{title}</title></polygon>'
    )
    label = ""
    if bbox is not None and (room.basic_info.room_number or room.basic_info.room_name):
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        label_text = escape(room.basic_info.room_number or room.basic_info.room_name or "")
        label = f'<text class="overview-label" x="{cx:.3f}" y="{-cy:.3f}">{label_text}</text>'
    return shape + label


def _room_card(room: Room, index: int, output_dir: Path) -> str:
    image_flag = "有分图" if _image_src(room, output_dir) else "无分图"
    issue_codes = ", ".join(issue.issue_code for issue in room.issues) or "无"
    bbox = _room_bbox(room)
    bbox_json = _bbox_json(bbox) if bbox is not None else "null"
    return (
        f'<button class="room-card" data-room-id="{escape(room.room_uid)}" data-review="{str(room.review.required).lower()}" data-bbox="{bbox_json}">'
        f'<div class="room-title"><span>{escape(_room_label(room, index))}</span><span>{escape(_review_label(room))}</span></div>'
        f'<div class="meta">confidence: {escape(_overall_confidence(room))} | {escape(image_flag)}<br>'
        f'issues: {escape(issue_codes)}</div>'
        "</button>"
    )


def _room_panel(room: Room, index: int, output_dir: Path) -> str:
    return f"""
      <section class="room-panel" data-room-id="{escape(room.room_uid)}">
        <div class="section">
          <h2>{escape(_room_label(room, index))}</h2>
          <div class="chips">
            <span class="chip {'review' if room.review.required else 'ok'}">{escape(_review_label(room))}</span>
            <span class="chip">final_status：{escape(room.final_status)}</span>
            <span class="chip">geometry：{escape(room.geometry.geometry_source)}</span>
          </div>
        </div>
        <div class="detail-grid">
          <div>
            <div class="section">
              <h2>房间分图</h2>
              {_image_html(room, output_dir)}
            </div>
            <div class="section">
              <h2>CAD 几何</h2>
              {_geometry_html(room)}
            </div>
          </div>
          <div>
            <div class="section">
              <h2>识别字段</h2>
              {_fields_html(room)}
            </div>
            <div class="section">
              <h2>AI / PDF 校核</h2>
              {_machine_check_html(room)}
            </div>
            <div class="section">
              <h2>Issues</h2>
              {_issues_html(room)}
            </div>
            <div class="section">
              <h2>证据来源</h2>
              {_sources_html(room)}
            </div>
          </div>
        </div>
      </section>
"""


def _fields_html(room: Room) -> str:
    values = [
        ("楼层", room.basic_info.floor),
        ("房号", room.basic_info.room_number),
        ("房名", room.basic_info.room_name),
        ("类型", room.basic_info.room_type),
        ("文字面积", _format_number(room.area.text_value, room.area.unit)),
        ("计算面积", _format_number(room.area.calculated_value, room.area.unit)),
        ("面积偏差", _format_percent(room.area.deviation_percent)),
        ("总置信度", _overall_confidence(room)),
    ]
    return '<div class="fields">' + "".join(_field(label, value) for label, value in values) + "</div>"


def _machine_check_html(room: Room) -> str:
    ai = _ai_check(room)
    pdf = room.evidence.pdf_source
    values = [
        ("PDF页", pdf.get("page")),
        ("PDF文字数", pdf.get("text_count")),
        ("AI状态", ai.get("status")),
        ("截图可见", _bool_label(ai.get("visible"))),
        ("房号匹配", _bool_label(ai.get("room_number_match"))),
        ("房名匹配", _bool_label(ai.get("room_name_match"))),
        ("面积匹配", _bool_label(ai.get("area_match"))),
        ("AI需复核", _bool_label(ai.get("needs_review"))),
    ]
    note = escape(str(ai.get("notes") or ""))
    local_text = escape(str(pdf.get("local_text") or ""))
    return (
        '<div class="fields">'
        + "".join(_field(label, value) for label, value in values)
        + f'</div><p class="reason">{note}</p><pre>{local_text}</pre>'
    )


def _issues_html(room: Room) -> str:
    if not room.issues:
        return '<div class="hint">无 issue。</div>'
    parts: list[str] = []
    for issue in room.issues:
        parts.append(
            f'<div class="issue" data-severity="{escape(issue.severity)}">'
            f'<div class="issue-code">{escape(issue.issue_code)} · {escape(issue.severity)} · {escape(str(issue.field or ""))}</div>'
            f'<div class="reason">{escape(issue.message)}</div>'
            "</div>"
        )
    return "\n".join(parts)


def _sources_html(room: Room) -> str:
    payload = {
        "cad_source": room.evidence.cad_source,
        "pdf_source": room.evidence.pdf_source,
        "bbox_cad": room.geometry.bbox_cad,
        "bbox_pdf": room.geometry.bbox_pdf,
    }
    return f"<pre>{escape(_compact_json_like(payload))}</pre>"


def _geometry_html(room: Room) -> str:
    if not room.geometry.polygon_cad and not room.geometry.bbox_cad:
        return '<div class="missing">缺少 CAD polygon / bbox。</div>'
    return f'<svg class="mini-map" viewBox="{_view_box(_room_bbox(room) or (0.0, 0.0, 1000.0, 1000.0))}" xmlns="http://www.w3.org/2000/svg"><polygon class="mini-polygon" points="{_room_points(room)}" /></svg>'


def _image_html(room: Room, output_dir: Path) -> str:
    src = _image_src(room, output_dir)
    if not src:
        return '<div class="image-wrap"><div class="missing">缺少 PDF 局部分图。</div></div>'
    return f'<div class="image-wrap"><img src="{escape(src)}" alt="{escape(_room_label(room))}"></div>'


def _image_src(room: Room, output_dir: Path) -> str | None:
    raw = _image_path(room)
    if not raw:
        return None
    image_path = Path(raw)
    if not image_path.is_absolute():
        image_path = Path.cwd() / image_path
    try:
        rel = os.path.relpath(image_path, output_dir)
    except ValueError:
        rel = str(image_path)
    return Path(rel).as_posix()


def _image_path(room: Room) -> str | None:
    review_image = room.evidence.pdf_source.get("review_image", {})
    if not isinstance(review_image, dict):
        return None
    path = review_image.get("path")
    return str(path) if path else None


def _room_label(room: Room, index: int | None = None) -> str:
    parts = [f"#{index:04d}" if index is not None else room.room_uid]
    if room.basic_info.room_number:
        parts.append(room.basic_info.room_number)
    if room.basic_info.room_name:
        parts.append(room.basic_info.room_name)
    if room.area.text_value is not None:
        parts.append(_format_number(room.area.text_value, room.area.unit))
    return " ".join(parts)


def _review_label(room: Room) -> str:
    if room.review.required:
        return STATUS_LABELS.get(room.review.status, room.review.status or "需复核")
    return STATUS_LABELS.get(room.review.status, room.review.status or "自动通过")


def _field(label: str, value: Any) -> str:
    rendered = "" if value is None else str(value)
    return f'<div class="field"><span>{escape(label)}</span><strong>{escape(rendered)}</strong></div>'


def _format_number(value: float | None, unit: str = "m2") -> str:
    if value is None:
        return ""
    return f"{value:g}{unit}"


def _format_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}%"


def _overall_confidence(room: Room) -> str:
    return f"{float(room.confidence.overall):.2f}"


def _bool_label(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return ""


def _ai_check(room: Room) -> dict[str, Any]:
    value = room.evidence.pdf_source.get("local_ai_check", {})
    return value if isinstance(value, dict) else {}


def _room_points(room: Room) -> str:
    if room.geometry.polygon_cad:
        return " ".join(f"{x:.3f},{-y:.3f}" for x, y in room.geometry.polygon_cad)
    bbox = room.geometry.bbox_cad or (0.0, 0.0, 1000.0, 1000.0)
    min_x, min_y, max_x, max_y = bbox
    return f"{min_x:.3f},{-min_y:.3f} {max_x:.3f},{-min_y:.3f} {max_x:.3f},{-max_y:.3f} {min_x:.3f},{-max_y:.3f}"


def _combined_bounds(rooms: list[Room]) -> BBox:
    bboxes = [_room_bbox(room) for room in rooms]
    valid = [bbox for bbox in bboxes if bbox is not None]
    if not valid:
        return (0.0, 0.0, 1000.0, 1000.0)
    min_x = min(bbox[0] for bbox in valid)
    min_y = min(bbox[1] for bbox in valid)
    max_x = max(bbox[2] for bbox in valid)
    max_y = max(bbox[3] for bbox in valid)
    return (min_x, min_y, max_x, max_y)


def _room_bbox(room: Room) -> BBox | None:
    if room.geometry.polygon_cad:
        return _bbox_from_points(room.geometry.polygon_cad)
    return room.geometry.bbox_cad


def _bbox_from_points(points: list[tuple[float, float]]) -> BBox:
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    return (min_x, min_y, max_x, max_y)


def _bbox_json(bbox: BBox) -> str:
    return "[" + ",".join(f"{value:.3f}" for value in bbox) + "]"


def _view_box(bounds: BBox) -> str:
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(width, height) * 0.12
    return f"{min_x - pad:.3f} {-max_y - pad:.3f} {width + pad * 2:.3f} {height + pad * 2:.3f}"


def _compact_json_like(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{key}: {_compact_json_like(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "[" + ", ".join(_compact_json_like(item) for item in value[:12]) + (", ..." if len(value) > 12 else "") + "]"
    return str(value)
