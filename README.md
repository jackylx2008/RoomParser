# Building Room Extractor

建筑图纸房间信息自动提取与 PDF 校核系统。当前实现重点是 Phase 0 / Phase 1：项目基础结构、DWG 转 DXF、DXF 图层与原始 CAD 对象提取。

## 当前能力

- `room-extractor --version` 输出版本号。
- `room-extractor convert-dwg` 使用本机 AutoCAD `AcCoreConsole.exe` 无界面批量转换 DWG 为 DXF。
- `room-extractor analyze-layers --dxf <file>` 输出 DXF 图层清单和实体统计。
- `room-extractor extract-cad --dxf <file> --out <file>` 输出 `cad_raw.json`，包含图层、文字、块属性和多段线基础信息。
- 根目录入口 `python main.py ...` 与安装后的 `room-extractor ...` 等价。

本阶段不包含 OCR、VLM、PDF 坐标映射、Streamlit 人工校核界面或高级房间匹配。

## 安装

```powershell
python -m pip install -e .[dev]
```

## DWG 转 DXF

默认扫描 `data/input/cad`，输出到 `data/input/dxf`：

```powershell
python main.py convert-dwg --input-dir data/input/cad --output-dir data/input/dxf --overwrite --timeout-seconds 300
```

如果需要显式指定 AutoCAD 2024 控制台程序：

```powershell
python main.py convert-dwg --input-dir data/input/cad --output-dir data/input/dxf --overwrite --timeout-seconds 300 --accoreconsole "C:\Program Files\Autodesk\AutoCAD 2024\AcCoreConsole.exe"
```

实现说明：

- 使用 `AcCoreConsole.exe /i input.dwg /s script.scr /l en-US`。
- 每个 DWG 会先复制到临时 ASCII 工作目录，避免 AutoCAD `.scr` 对中文路径解析失败。
- 转换完成后再把生成的 DXF 移动到目标目录。
- 真实图纸数据、转换后的 DXF、输出 JSON 和日志均被 `.gitignore` 排除。

## DXF 解析

分析图层：

```powershell
python main.py analyze-layers --dxf data/input/dxf/sample.dxf
```

提取 CAD 原始对象：

```powershell
python main.py extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw.json
```

`cad_raw.json` 至少包含：

```json
{
  "source_file": "sample.dxf",
  "layers": [],
  "texts": [],
  "blocks": [],
  "polylines": [],
  "issues": []
}
```

## 项目结构

```text
src/room_extractor/
  cad/        DXF 加载、DWG 转换、图层分析、文本/块/多段线提取
  cli/        命令行入口
  config/     图层规则配置
  geometry/   bbox、polygon 面积、IoU 等基础几何能力
  models/     Pydantic 数据模型
  utils/      日志配置等通用工具
tests/        单元测试
docs/         项目文档
data/         本地输入输出目录，真实数据不入库
```

## 测试

```powershell
python -m pytest
```

当前通过用例覆盖：

- DXF 加载、图层统计、TEXT/MTEXT/INSERT/LWPOLYLINE 提取
- DWG 文件扫描与转换路径组织
- `convert-dwg` CLI 汇总输出
- 几何 bbox、面积、点在 polygon 内、IoU

## 进展文档

阶段进展见 [docs/project_progress.md](docs/project_progress.md)。

