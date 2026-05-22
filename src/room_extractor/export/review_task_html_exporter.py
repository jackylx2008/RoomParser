from __future__ import annotations

import os
from html import escape
from pathlib import Path
from typing import Any

from room_extractor.models.drawing import BBox
from room_extractor.models.review_task import ReviewTask, ReviewTaskSet


PRIORITY_LABELS = {
    "high": "高优先级",
    "medium": "中优先级",
    "low": "低优先级",
}


def export_review_task_html(
    tasks: ReviewTaskSet,
    out_path: str | Path,
    title: str = "正式人工审核任务",
) -> Path:
    """Write a self-contained HTML review queue for post-machine-check tasks."""
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_review_task_html(tasks, output, title=title), encoding="utf-8")
    return output


def build_review_task_html(
    tasks: ReviewTaskSet,
    out_path: str | Path | None = None,
    title: str = "正式人工审核任务",
) -> str:
    """Build the formal manual review HTML after CAD/PDF/local-AI checks."""
    output_dir = Path(out_path).parent if out_path else Path(".")
    overview_svg = _overview_svg(tasks.tasks)
    task_cards = "\n".join(_task_card(task, output_dir) for task in tasks.tasks)
    task_panels = "\n".join(_task_panel(task, output_dir) for task in tasks.tasks)
    summary_html = _summary_html(tasks)
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
      --high: #c62828;
      --medium: #d97706;
      --low: #19764b;
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
      grid-template-columns: minmax(320px, 420px) 1fr;
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
      overflow: auto;
      padding: 16px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.3;
    }}
    .source, .hint, .meta, .reason, .kv, .ai-note {{
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
    .controls {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 12px;
      font-size: 13px;
    }}
    .controls label {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }}
    .task-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .overview-section {{
      margin: 12px 0;
    }}
    .overview-map {{
      width: 100%;
      height: 260px;
      display: block;
      background: #faf9f5;
      border: 1px solid #d8dde2;
      border-radius: 6px;
    }}
    .overview-room {{
      vector-effect: non-scaling-stroke;
      stroke-width: 1.5;
      cursor: pointer;
      fill: rgba(11, 95, 255, 0.08);
      stroke: #66717b;
    }}
    .overview-room.high {{
      fill: rgba(198, 40, 40, 0.12);
      stroke: var(--high);
    }}
    .overview-room.medium {{
      fill: rgba(217, 119, 6, 0.12);
      stroke: var(--medium);
    }}
    .overview-room.low {{
      fill: rgba(25, 118, 75, 0.12);
      stroke: var(--low);
    }}
    .overview-room.selected-overview {{
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
    .task-card {{
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
    .task-card:hover, .task-card.selected {{
      border-color: var(--selected);
      background: #eef4ff;
    }}
    .task-card[data-priority="high"] {{ border-left-color: var(--high); }}
    .task-card[data-priority="medium"] {{ border-left-color: var(--medium); }}
    .task-card[data-priority="low"] {{ border-left-color: var(--low); }}
    .task-title {{
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 600;
    }}
    .task-title span:first-child {{
      overflow-wrap: anywhere;
    }}
    .task-panel {{
      display: none;
      max-width: 1280px;
      margin: 0 auto;
    }}
    .task-panel.active {{ display: block; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: minmax(320px, 45%) 1fr;
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
    .section h2 {{
      margin: 0 0 10px;
      font-size: 15px;
      line-height: 1.3;
    }}
    .image-wrap {{
      min-height: 260px;
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
    .missing-image {{
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
    .chip.high {{ background: #fdecec; color: var(--high); }}
    .chip.medium {{ background: #fff3df; color: #9a5600; }}
    .chip.low {{ background: #e9f6ef; color: var(--low); }}
    .issue {{
      border: 1px solid #e5e8eb;
      border-left: 4px solid #aeb6be;
      border-radius: 6px;
      padding: 8px;
      margin-bottom: 6px;
      background: #fff;
    }}
    .issue[data-severity="high"] {{ border-left-color: var(--high); }}
    .issue[data-severity="medium"] {{ border-left-color: var(--medium); }}
    .issue[data-severity="low"] {{ border-left-color: var(--low); }}
    .issue-code {{
      font-weight: 700;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.45;
      color: #27313b;
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
    .mini-label {{
      fill: var(--selected);
      stroke: #fff;
      stroke-width: 2;
      vector-effect: non-scaling-stroke;
    }}
    .task-card.hidden {{ display: none; }}
    body.hide-high .task-card[data-priority="high"],
    body.hide-medium .task-card[data-priority="medium"],
    body.hide-low .task-card[data-priority="low"] {{ display: none; }}
    body.hide-images .image-section {{ display: none; }}
    @media (max-width: 960px) {{
      .shell {{ grid-template-columns: 1fr; grid-template-rows: 44vh 56vh; }}
      aside {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>{escaped_title}</h1>
      <div class="source">来源：{escape(tasks.source_file)}<br>房间数据：{escape(str(tasks.rooms_source_file or ""))}</div>
      <div class="summary">{summary_html}</div>
      <div class="overview-section">
        <div class="hint">总图：全链路识别后进入人工校核的房间分布。点击房间可切换到对应分图。</div>
        {overview_svg}
      </div>
      <div class="controls">
        <label><input type="checkbox" data-toggle="hide-high" checked> 高优先级</label>
        <label><input type="checkbox" data-toggle="hide-medium" checked> 中优先级</label>
        <label><input type="checkbox" data-toggle="hide-low" checked> 低优先级</label>
        <label><input type="checkbox" data-toggle="hide-images" checked> 截图</label>
      </div>
      <div class="hint">这是 PDF/OCR/AI 机器校核后的正式人工审核队列。点击任务查看截图、字段、AI 判断和 issue。</div>
      <hr>
      <div class="task-list">{task_cards}</div>
    </aside>
    <main id="task-detail">
      {task_panels}
    </main>
  </div>
  <script>
    function selectTask(id) {{
      document.querySelectorAll('.task-card.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('.task-panel.active').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.overview-room.selected-overview').forEach(el => el.classList.remove('selected-overview'));
      const card = document.querySelector(`.task-card[data-task-id="${{id}}"]`);
      const panel = document.querySelector(`.task-panel[data-task-id="${{id}}"]`);
      const overview = document.querySelector(`.overview-room[data-task-id="${{id}}"]`);
      if (card) card.classList.add('selected');
      if (panel) panel.classList.add('active');
      if (overview) overview.classList.add('selected-overview');
    }}
    document.querySelectorAll('.task-card, .overview-room').forEach(el => {{
      el.addEventListener('click', () => selectTask(el.dataset.taskId));
    }});
    document.querySelectorAll('[data-toggle]').forEach(input => {{
      input.addEventListener('change', () => {{
        document.body.classList.toggle(input.dataset.toggle, !input.checked);
      }});
    }});
    const first = document.querySelector('.task-card');
    if (first) selectTask(first.dataset.taskId);
  </script>
</body>
</html>
"""


def _task_card(task: ReviewTask, output_dir: Path) -> str:
    issue_codes = ", ".join(task.issue_codes) or "无"
    image_flag = "有截图" if _image_src(task, output_dir) else "无截图"
    return (
        f'<button class="task-card" data-task-id="{escape(task.task_id)}" data-priority="{escape(task.priority)}">'
        f'<div class="task-title"><span>{escape(_task_label(task))}</span><span>{escape(PRIORITY_LABELS.get(task.priority, task.priority))}</span></div>'
        f'<div class="meta">confidence: {escape(_overall_confidence(task))} | {escape(image_flag)}<br>'
        f'fields: {escape(", ".join(task.suggested_fields) or "无")}<br>'
        f'issues: {escape(issue_codes)}</div>'
        "</button>"
    )


def _task_panel(task: ReviewTask, output_dir: Path) -> str:
    image = _image_html(task, output_dir)
    fields = _fields_html(task)
    ai = _ai_html(task)
    issues = _issues_html(task)
    reasons = _reasons_html(task)
    sources = _sources_html(task)
    geometry = _geometry_html(task)
    return f"""
      <section class="task-panel" data-task-id="{escape(task.task_id)}">
        <div class="section">
          <h2>{escape(_task_label(task))}</h2>
          <div class="chips">
            <span class="chip {escape(task.priority)}">{escape(PRIORITY_LABELS.get(task.priority, task.priority))}</span>
            <span class="chip">状态：{escape(task.status)}</span>
            <span class="chip">建议字段：{escape(", ".join(task.suggested_fields) or "无")}</span>
          </div>
        </div>
        <div class="detail-grid">
          <div>
            <div class="section image-section">
              <h2>PDF 局部截图</h2>
              {image}
            </div>
            <div class="section">
              <h2>CAD 几何</h2>
              {geometry}
            </div>
          </div>
          <div>
            <div class="section">
              <h2>自动识别字段</h2>
              {fields}
            </div>
            <div class="section">
              <h2>机器校核结论</h2>
              {ai}
            </div>
            <div class="section">
              <h2>审核原因</h2>
              {reasons}
            </div>
            <div class="section">
              <h2>Issues</h2>
              {issues}
            </div>
            <div class="section">
              <h2>证据来源</h2>
              {sources}
            </div>
          </div>
        </div>
      </section>
"""


def _summary_html(tasks: ReviewTaskSet) -> str:
    summary = tasks.summary or {}
    priority_counts = summary.get("priority_counts", {})
    metrics = [
        ("房间总数", summary.get("room_count", 0)),
        ("审核任务", summary.get("task_count", len(tasks.tasks))),
        ("自动通过", summary.get("auto_pass_count", 0)),
        ("高优先级", priority_counts.get("high", 0) if isinstance(priority_counts, dict) else 0),
        ("中优先级", priority_counts.get("medium", 0) if isinstance(priority_counts, dict) else 0),
        ("AI需复核", (summary.get("ai_needs_review_counts", {}) or {}).get("True", 0) if isinstance(summary.get("ai_needs_review_counts", {}), dict) else 0),
    ]
    return "\n".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in metrics
    )


def _overview_svg(tasks: list[ReviewTask]) -> str:
    drawable = [task for task in tasks if task.polygon_cad or task.bbox_cad]
    if not drawable:
        return '<div class="missing-image">总图缺少 CAD geometry，无法绘制房间分布。</div>'
    bounds = _combined_bounds(drawable)
    shapes = "\n".join(_overview_shape(task) for task in drawable)
    return f'<svg class="overview-map" viewBox="{_view_box(bounds)}" xmlns="http://www.w3.org/2000/svg">{shapes}</svg>'


def _overview_shape(task: ReviewTask) -> str:
    task_id = escape(task.task_id)
    priority = escape(task.priority)
    title = escape(_task_label(task))
    if task.polygon_cad:
        points = " ".join(f"{x:.3f},{-y:.3f}" for x, y in task.polygon_cad)
        shape = (
            f'<polygon class="overview-room {priority}" data-task-id="{task_id}" '
            f'points="{points}"><title>{title}</title></polygon>'
        )
    else:
        assert task.bbox_cad is not None
        min_x, min_y, max_x, max_y = task.bbox_cad
        points = f"{min_x:.3f},{-min_y:.3f} {max_x:.3f},{-min_y:.3f} {max_x:.3f},{-max_y:.3f} {min_x:.3f},{-max_y:.3f}"
        shape = (
            f'<polygon class="overview-room {priority}" data-task-id="{task_id}" '
            f'points="{points}"><title>{title}</title></polygon>'
        )
    bbox = _task_bbox(task)
    label = ""
    if bbox is not None and (task.room_number or task.room_name):
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        label_text = escape(task.room_number or task.room_name or "")
        label = f'<text class="overview-label" x="{cx:.3f}" y="{-cy:.3f}">{label_text}</text>'
    return shape + label


def _combined_bounds(tasks: list[ReviewTask]) -> BBox:
    bboxes = [_task_bbox(task) for task in tasks]
    valid = [bbox for bbox in bboxes if bbox is not None]
    if not valid:
        return (0.0, 0.0, 1000.0, 1000.0)
    min_x = min(bbox[0] for bbox in valid)
    min_y = min(bbox[1] for bbox in valid)
    max_x = max(bbox[2] for bbox in valid)
    max_y = max(bbox[3] for bbox in valid)
    return (min_x, min_y, max_x, max_y)


def _task_bbox(task: ReviewTask) -> BBox | None:
    if task.polygon_cad:
        return _bbox_from_points(task.polygon_cad)
    return task.bbox_cad


def _fields_html(task: ReviewTask) -> str:
    values = [
        ("楼层", task.floor),
        ("房号", task.room_number),
        ("房名", task.room_name),
        ("类型", task.room_type),
        ("文字面积", _format_number(task.area_text_value, task.area_unit)),
        ("计算面积", _format_number(task.area_calculated_value, task.area_unit)),
        ("总置信度", _overall_confidence(task)),
        ("CAD匹配", task.cad_source.get("match_status")),
    ]
    return '<div class="fields">' + "".join(_field(label, value) for label, value in values) + "</div>"


def _ai_html(task: ReviewTask) -> str:
    ai = task.local_ai_check or {}
    if not ai:
        return '<div class="hint">无本地 AI 校核结果。</div>'
    fields = [
        ("状态", ai.get("status")),
        ("截图可见", _bool_label(ai.get("visible"))),
        ("房号匹配", _bool_label(ai.get("room_number_match"))),
        ("房名匹配", _bool_label(ai.get("room_name_match"))),
        ("面积匹配", _bool_label(ai.get("area_match"))),
        ("需复核", _bool_label(ai.get("needs_review"))),
        ("AI置信度", ai.get("confidence")),
    ]
    note = escape(str(ai.get("notes") or ""))
    return '<div class="fields">' + "".join(_field(label, value) for label, value in fields) + f'</div><p class="ai-note">{note}</p>'


def _reasons_html(task: ReviewTask) -> str:
    if not task.reasons:
        return '<div class="hint">无额外原因。</div>'
    return "".join(f'<div class="reason">• {escape(reason)}</div>' for reason in task.reasons)


def _issues_html(task: ReviewTask) -> str:
    if not task.issues:
        return '<div class="hint">无 issue。</div>'
    parts: list[str] = []
    for issue in task.issues:
        parts.append(
            f'<div class="issue" data-severity="{escape(issue.severity)}">'
            f'<div class="issue-code">{escape(issue.issue_code)} · {escape(issue.severity)} · {escape(str(issue.field or ""))}</div>'
            f'<div class="reason">{escape(issue.message)}</div>'
            "</div>"
        )
    return "\n".join(parts)


def _sources_html(task: ReviewTask) -> str:
    payload = {
        "cad_source": task.cad_source,
        "pdf_source": task.pdf_source,
        "bbox_cad": task.bbox_cad,
        "bbox_pdf": task.bbox_pdf,
    }
    return f"<pre>{escape(_compact_json_like(payload))}</pre>"


def _geometry_html(task: ReviewTask) -> str:
    if not task.polygon_cad and not task.bbox_cad:
        return '<div class="missing-image">缺少 CAD polygon / bbox，需人工从原图定位。</div>'
    if task.polygon_cad:
        points = " ".join(f"{x:.3f},{-y:.3f}" for x, y in task.polygon_cad)
        view_box = _view_box(_bbox_from_points(task.polygon_cad))
        return f'<svg class="mini-map" viewBox="{view_box}" xmlns="http://www.w3.org/2000/svg"><polygon class="mini-polygon" points="{points}" /></svg>'
    assert task.bbox_cad is not None
    min_x, min_y, max_x, max_y = task.bbox_cad
    points = f"{min_x:.3f},{-min_y:.3f} {max_x:.3f},{-min_y:.3f} {max_x:.3f},{-max_y:.3f} {min_x:.3f},{-max_y:.3f}"
    return f'<svg class="mini-map" viewBox="{_view_box(task.bbox_cad)}" xmlns="http://www.w3.org/2000/svg"><polygon class="mini-polygon" points="{points}" /></svg>'


def _image_html(task: ReviewTask, output_dir: Path) -> str:
    src = _image_src(task, output_dir)
    if not src:
        return '<div class="image-wrap"><div class="missing-image">缺少局部截图，需回到原 PDF 或 CAD 图纸人工定位。</div></div>'
    return f'<div class="image-wrap"><img src="{escape(src)}" alt="{escape(_task_label(task))}"></div>'


def _image_src(task: ReviewTask, output_dir: Path) -> str | None:
    raw = task.review_image_path
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


def _task_label(task: ReviewTask) -> str:
    parts = [task.task_id.replace("review_task_", "#")]
    if task.room_number:
        parts.append(task.room_number)
    if task.room_name:
        parts.append(task.room_name)
    if task.area_text_value is not None:
        parts.append(_format_number(task.area_text_value, task.area_unit))
    return " ".join(parts)


def _field(label: str, value: Any) -> str:
    rendered = "" if value is None else str(value)
    return f'<div class="field"><span>{escape(label)}</span><strong>{escape(rendered)}</strong></div>'


def _format_number(value: float | None, unit: str = "m2") -> str:
    if value is None:
        return ""
    return f"{value:g}{unit}"


def _overall_confidence(task: ReviewTask) -> str:
    value = task.confidence.get("overall")
    if value is None:
        return ""
    return f"{float(value):.2f}"


def _bool_label(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return ""


def _bbox_from_points(points: list[tuple[float, float]]) -> BBox:
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    return (min_x, min_y, max_x, max_y)


def _view_box(bounds: BBox) -> str:
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(width, height) * 0.12
    return f"{min_x - pad:.3f} {-max_y - pad:.3f} {width + pad * 2:.3f} {height + pad * 2:.3f}"


def _compact_json_like(value: Any) -> str:
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            lines.append(f"{key}: {_compact_json_like(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "[" + ", ".join(_compact_json_like(item) for item in value[:12]) + (", ..." if len(value) > 12 else "") + "]"
    return str(value)
