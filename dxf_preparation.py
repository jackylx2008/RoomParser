"""DXF 预处理工作流的项目根目录入口。

功能介绍：
    该文件用于从项目根目录启动 DXF 预处理相关命令。入口会先把项目的
    ``src`` 目录加入 Python 模块搜索路径，再把执行权转交给
    ``room_extractor.cli.dxf_preparation`` 中的正式 CLI。

    预处理工作流面向房间识别前的数据准备，主要覆盖 DWG 转 DXF、DXF 块
    炸开、线状实体去重、自驱动分步清理和报告输出等步骤。它的输出通常
    作为后续房间提取工作流的输入，用于降低 CAD 原图中块引用、重复线、
    无用 OBJECTS/TABLES 数据和格式差异对识别结果的影响。

参数说明：
    该入口文件本身不定义业务参数，运行时接收的命令行参数会透传给
    ``room_extractor.cli.dxf_preparation``。

    可用子命令包括：
    - ``convert-dwg``：批量调用 AcCoreConsole 将 DWG 转为 DXF，可通过
      ``--input-dir``、``--output-dir``、``--recursive``、``--overwrite``、
      ``--accoreconsole``、``--locale``、``--timeout-seconds``、
      ``--dxf-precision``、``--explode-blocks`` 等参数控制输入输出、
      AutoCAD 命令行工具位置、超时、精度和是否同步炸块。
    - ``explode-dxf``：批量炸开 DXF 文件中的块引用，可通过
      ``--input-dir``、``--output-dir``、``--recursive``、``--overwrite``、
      ``--accoreconsole``、``--locale``、``--timeout-seconds``、
      ``--dxf-precision``、``--max-explode-passes`` 等参数控制扫描范围、
      输出目录和重复炸块上限。
    - ``dedupe-dxf-lines``：分析并可选删除 DXF 中重复的 LINE、LWPOLYLINE、
      POLYLINE、ARC 等线状实体，可通过 ``--input``、``--out``、
      ``--report-out``、``--dedupe-mode``、``--exact-tolerance``、
      ``--near-tolerance``、``--signature-scope``、``--visible-only`` 等参数
      控制输入文件、清理输出、报告输出、去重策略和可见图层过滤。
    - ``self-clean-dxf``：运行正式 16 阶段 DXF 自驱动清理流程，每步生成
      独立 DXF、HTML、PNG、删除记录和 rollback point；可通过
      ``--source``、``--reference``、``--out-dir``、``--resume``、
      ``--max-steps``、``--rollback-to``、``--mark-step-accepted``、
      ``--mark-step-rejected``、``--render-step-images`` 等参数控制启动、
      续跑、人工验收和回滚。
    - ``prepare-l2-room-dxf``：重放人工和 AutoCAD 验证过的 L2 房间边界
      预清理链。流程会删除家具图层、炸开指定墙/柱 INSERT、删除炸块暴露
      的残留、清空多余图纸空间、打开并解冻图层，再按 L2 near/geometry
      规则去重。默认的 010 之后流程固定为已验证的 door 保护清理：解锁
      所有图层、删除非 door 填充、删除非 door 重线，并保留每个 step 的
      ``input.dxf``、``candidate_after.dxf`` 和 ``manifest.json``。如果传入
      ``--final-layer-policy-json``，会在最后按导出的图层 JSON 删除冻结、
      不打印和缺失图层，同时保护墙体、门和完成面图层，避免误删精装墙体。
      旧的参照清理链可通过 ``--post-009-cleanup-mode reference-guided``
      手动启用。

用途：
    供用户在项目根目录直接执行 ``python dxf_preparation.py <子命令> ...``，
    生成规范化、炸块、去重或分步清理后的 DXF 数据及审计报告。
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
    from room_extractor.cli.dxf_preparation import main as workflow_main

    return workflow_main()


if __name__ == "__main__":
    raise SystemExit(main())
