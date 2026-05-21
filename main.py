"""建筑房间提取工具入口。

用途：
  从项目根目录直接启动 Building Room Extractor 命令行工具，转发到
  `room_extractor.cli.main` 中的 CLI 实现。

配置文件：
  当前 Phase 1 不强制读取业务配置文件。日志配置由包内
  `room_extractor.utils.logging_config` 统一初始化，默认写入项目根目录
  `log/` 下对应入口名称的日志文件。

必填参数：
  无固定必填参数。具体参数由子命令决定。

可选参数：
  --version        输出工具版本。
  analyze-layers   分析 DXF 图层与实体数量。
  extract-cad      提取 DXF 原始 CAD 对象并写入 JSON。
  convert-dwg      调用本地 AutoCAD AcCoreConsole 将 DWG 转换为 DXF。

示例：
  python main.py --version
  python main.py analyze-layers --dxf data/input/dxf/sample.dxf
  python main.py extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw.json
  python main.py convert-dwg --input-dir data/input/cad --output-dir data/input/dxf

输出：
  `analyze-layers` 输出结构化 JSON 到控制台；
  `extract-cad` 将 `cad_raw.json` 写入 `--out` 指定路径。
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
    from room_extractor.cli.main import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
