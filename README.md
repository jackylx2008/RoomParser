# Building Room Extractor

建筑图纸房间信息自动提取与 PDF 校核系统。当前实现重点是 Phase 0 / Phase 1 / Phase 2 / Phase 3 / Phase 4 / Phase 5：项目基础结构、DWG 转 DXF、DXF 图层与原始 CAD 对象提取、房间文字识别与 label 聚类、房间边界识别、初始房间 JSON 生成、PDF 矢量文字机器校核。

## 当前能力

- `room-extractor --version` 输出版本号。
- `room-extractor convert-dwg` 使用本机 AutoCAD `AcCoreConsole.exe` 无界面批量转换 DWG 为 DXF。
- `room-extractor analyze-layers --dxf <file>` 输出 DXF 图层清单和实体统计。
- `room-extractor extract-cad --dxf <file> --out <file>` 输出 `cad_raw.json`，包含图层、文字、块属性和多段线基础信息。
- `room-extractor build-room-labels --cad <cad_raw.json> --out <file>` 输出 `room_label_candidates.json`，包含房号、房名、面积和文本聚类结果。
- `room-extractor build-room-candidates --cad <cad_raw.json> --labels <room_label_candidates.json> --out <file>` 输出 `room_candidates.json`，将房间 label 中心点匹配到闭合 polygon。
- `room-extractor export-review-map --cad <cad_raw.json> --rooms <room_candidates.json> --out <file>` 输出 HTML/SVG 阶段检查图，用于人工看图检查 Phase 3 结果。
- `room-extractor build-rooms --candidates <room_candidates.json> --out <file>` 输出 `rooms_auto.json`，生成 CAD 自动识别版初始 Room JSON。
- `room-extractor check-pdf --rooms <rooms_auto.json> --pdf <file.pdf> --out <file>` 输出 `rooms_pdf_checked.json`，提取 PDF 矢量文字并对 CAD 房间结果做局部一致性校核。
- 根目录入口 `python main.py ...` 与安装后的 `room-extractor ...` 等价。

当前不包含局部截图、OCR、VLM、Streamlit 人工校核界面或最终 Room JSON 生成。Phase 5 已包含初版 CAD/PDF 线性坐标映射，但该映射仍标记为 `CAD_PDF_MAPPING_UNVERIFIED`，后续需要通过截图和 AI / 人工校核继续确认。

说明：Phase 3 后的 HTML/SVG 只用于阶段开发验收和规则调试。正式人工校核应放在后续 PDF 矢量校核、局部截图、OCR / 本地 AI 辅助校验、置信度评分和 review task 生成之后。

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

## 房间文字识别

从 `cad_raw.json` 生成 Phase 2 的房间 label 候选：

```powershell
python main.py build-room-labels --cad data/output/json/cad_raw.json --out data/output/json/room_label_candidates.json --floor L2
```

输出包括：

- `parsed_texts`：每条 CAD 文本的标准化和字段识别结果。
- `candidates`：相邻房号、房名、面积聚类后的房间 label 候选。
- `candidate_id`、`floor`、`room_number`、`room_name`、`area`、`center`、`bbox`、`confidence`、`issues`。

Phase 2 会对常见 CAD 中文乱码做 GBK mojibake 恢复，例如真实图纸中的会议室、贵宾室、卫生间等文本可恢复后再解析。

## 房间边界识别

从 `cad_raw.json` 和 `room_label_candidates.json` 生成 Phase 3 的房间候选：

```powershell
python main.py build-room-candidates --cad data/output/json/cad_raw.json --labels data/output/json/room_label_candidates.json --out data/output/json/room_candidates.json --floor L2
```

输出包括：

- `boundary_candidates`：过滤后的闭合 CAD polygon，包含 `bbox_cad` 和 `area_cad`。
- `room_candidates`：每个 room label 与 polygon 的匹配结果。
- `summary`：状态、匹配方式和 issue 统计摘要。
- 严格匹配：优先房间边界/面积线图层，使用 label 中心点落入 polygon 的最小合适边界。
- fallback 匹配：普通房间中心点未落入 polygon 时，可按优先边界图层 bbox 距离生成 `matched_fallback`，并写入 `LABEL_OUTSIDE_BOUNDARY_FALLBACK_MATCH`。
- 特殊空间：客梯、货梯、电梯厅、走道、通道等无面积空间不强行 fallback，标记 `SPECIAL_SPACE_NO_AREA_BOUNDARY` 等待人工确认。

导出阶段检查图：

```powershell
python main.py export-review-map --cad data/output/json/cad_raw.json --rooms data/output/json/room_candidates.json --out data/output/reports/room_candidates_review.html
```

检查图是自包含 HTML/SVG 文件，包含浅色 CAD 底图、绿色严格匹配、橙色低置信度匹配、红色未匹配标签和候选列表。它用于 Phase 3 规则验收，不是最终人工校核界面。

## 初始房间 JSON

从 `room_candidates.json` 生成 Phase 4 的 CAD 自动识别版房间 JSON：

```powershell
python main.py build-rooms --candidates data/output/json/room_candidates.json --out data/output/json/rooms_auto.json
```

输出包括：

- `rooms`：标准 `Room` 对象列表。
- `basic_info`：楼层、房号、房名、房间类型。
- `area`：文字面积、CAD polygon 计算面积、面积偏差。
- `geometry`：CAD polygon、bbox、坐标单位和 geometry source。
- `evidence`：CAD 来源文件、label candidate、room candidate、boundary id、源文字。
- `confidence`：房号、房名、面积、几何和 overall 初始置信度。
- `issues`：缺失几何、面积偏差、fallback 匹配等问题。

该输出仍是 `cad_auto_draft`，后续必须继续进入 PDF / OCR / 本地 AI 机器校验流程，不能作为最终成果。

## PDF 矢量文字校核

从 `rooms_auto.json` 和对应 PDF 生成 Phase 5 的机器校核结果：

```powershell
python main.py check-pdf --rooms data/output/json/rooms_auto.json --pdf data/input/pdf/sample.pdf --out data/output/json/rooms_pdf_checked.json --page 1
```

输出包括：

- `pdf_text`：PDF 矢量文字及 bbox。
- `transform`：CAD bbox 到 PDF bbox 的线性映射参数。
- `rooms[].geometry.bbox_pdf`：映射后的 PDF 局部 bbox。
- `rooms[].evidence.pdf_source`：PDF 来源文件、页码、局部 bbox、局部文字和文字数量。
- `issues`：PDF 未找到局部文字、房号 / 房名 / 面积不一致、缺少 CAD geometry 等问题。
- `confidence.cad_pdf_consistency`：CAD 与 PDF 局部文本一致性分数。

注意：当前 CAD/PDF 坐标映射是基于房间 CAD bbox 外接范围到 PDF 页面外接范围的初版线性拟合，输出会保留 `CAD_PDF_MAPPING_UNVERIFIED` 顶层 issue。它适合作为后续局部截图、OCR / 本地 AI 辅助校验和 review task 生成的输入，不作为最终人工确认结论。

## 项目结构

```text
src/room_extractor/
  cad/        DXF 加载、DWG 转换、图层分析、文本/块/多段线提取
  cli/        命令行入口
  config/     图层规则配置
  export/     阶段检查图等导出能力
  extraction/ 房间文字解析、label 聚类、边界识别、Room JSON 生成
  geometry/   bbox、polygon 面积、IoU 等基础几何能力
  models/     Pydantic 数据模型
  pdf/        PDF 矢量文字提取和 CAD/PDF 局部一致性校核
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
- 房号、房名、面积正则识别
- CAD 中文 mojibake 文本恢复
- 相邻房号、房名、面积聚类为 room label candidate
- 闭合 CAD polygon 过滤、bbox/面积输出、label 到 polygon 匹配
- 初始 Room JSON 生成、CAD 面积换算、面积偏差和初始 confidence
- PDF 矢量文字提取、bbox 局部查找、CAD/PDF 字段一致性校核
- `check-pdf` CLI 输出
- 几何 bbox、面积、点在 polygon 内、IoU

## 进展文档

阶段进展见 [docs/project_progress.md](docs/project_progress.md)。
