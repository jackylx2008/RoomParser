"""房间提取工作流的项目根目录入口。

功能介绍：
    该文件用于从项目根目录启动房间提取相关命令。入口会先把项目的
    ``src`` 目录加入 Python 模块搜索路径，再把执行权转交给
    ``room_extractor.cli.room_extraction`` 中的正式 CLI。

    房间提取工作流面向预处理后的 CAD/DXF 数据，按阶段完成图层分析、
    CAD 原始实体导出、轴网和柱信息提取、房间文字候选生成、边界匹配、
    房间 JSON 构建、PDF 文本核验、图片渲染、AI 辅助检查和人工审核页面
    导出。它把图纸中的几何和文字信息逐步转换为可检查、可修正的结构化
    房间数据。

参数说明：
    该入口文件本身不定义业务参数，运行时接收的命令行参数会透传给
    ``room_extractor.cli.room_extraction``。

    常用输入输出参数包括：
    - ``--dxf``：输入 DXF 文件路径，用于图层分析、CAD 实体提取、柱特征
      分析和轴网规则推断等子命令。
    - ``--cad``：Phase 1 的 ``cad_raw.json``，用于生成房间文字候选、
      房间边界候选和审核地图。
    - ``--labels``：Phase 2 的 ``room_label_candidates.json``，用于和 CAD
      边界匹配生成房间候选。
    - ``--rooms``：中后期房间 JSON，例如 ``rooms_auto.json``、
      ``rooms_pdf_checked.json``、``rooms_with_review_images.json`` 或
      ``rooms_ai_checked.json``。
    - ``--out``、``--output-dir``：输出 JSON、HTML 或图片目录。
    - ``--floor``、``--visible-only``、``--axis-rules``、``--column-rules``、
      ``--boundary-layer``、``--min-boundary-area``、``--max-boundary-area``：
      控制楼层标记、可见性过滤、轴线/柱规则、候选边界图层和面积范围。
    - ``--pdf``、``--page``、``--dpi``、``--margin-ratio``：控制 PDF 文本核验
      和房间局部截图渲染。
    - ``--base-url``、``--model``、``--timeout-seconds``、``--max-tokens``、
      ``--limit``、``--dry-run``：控制本地 AI 兼容多模态模型检查。
    - ``--title``：控制导出的 HTML 审核或总览页面标题。

    可用子命令覆盖 ``analyze-layers``、``extract-cad``、
    ``analyze-column-features``、``infer-axis-rules``、
    ``export-json-review-html``、``build-room-labels``、
    ``build-room-candidates``、``export-review-map``、``build-rooms``、
    ``check-pdf``、``render-review-images``、``check-images-ai``、
    ``build-review-tasks``、``export-review-tasks-html`` 和
    ``export-rooms-html``。

用途：
    供用户在项目根目录直接执行 ``python room_extraction.py <子命令> ...``，
    基于预处理后的 CAD/DXF、PDF 和中间 JSON 文件生成房间识别结果及审核
    交付物。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def main() -> int:
    _ensure_src_on_path()
    from room_extractor.cli.room_extraction import main as workflow_main

    return workflow_main()


if __name__ == "__main__":
    raise SystemExit(main())
