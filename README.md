# Building Room Extractor

建筑图纸房间信息自动提取与 PDF 校核系统。当前实现重点是 Phase 0 / Phase 1 / Phase 2 / Phase 3 / Phase 4 / Phase 5 / Phase 6：项目基础结构、DWG 转 DXF、DXF 图层与原始 CAD 对象提取、轴线 JSON 提取与校核、结构柱 JSON 提取与特征分析、房间文字识别与 label 聚类、房间边界识别、初始房间 JSON 生成、PDF 矢量文字机器校核、PDF 局部截图生成，以及 DXF 膨胀数据的自驱动清理实验。

## 当前能力

- `room-extractor --version` 输出版本号。
- `room-extractor convert-dwg` 使用本机 AutoCAD `AcCoreConsole.exe` 无界面批量转换 DWG 为 DXF。
- `room-extractor dedupe-dxf-lines --input <file.dxf>` 统计并可清理炸块后 DXF 中重复的 `LINE / LWPOLYLINE / POLYLINE / ARC`。
- `python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --max-steps 1 --dry-run-ai` 运行 DXF 自驱动清理实验，每轮生成 DXF、HTML、PNG、删除记录和 rollback point。
- `room-extractor analyze-layers --dxf <file>` 输出 DXF 图层清单和实体统计；支持 `--visible-only` 只统计未关闭、未冻结、未 invisible 的图元。
- `room-extractor extract-cad --dxf <file> --out <file>` 输出 `cad_raw.json`，包含图层、文字、块属性、多段线、普通线段、圆弧采样点列和轴网线基础信息；支持 `--visible-only` 过滤关闭 / 冻结 / invisible 图元。
- `room-extractor extract-cad --dxf <file> --out <file> --axis-only` 仅按轴线规则输出轴线和轴号图层信息，适合生成轴线专项校核 JSON。
- `room-extractor extract-cad --dxf <file> --out <file> --columns-only` 按结构柱规则输出独立 `columns` JSON，可自动展开块 / 外参内部图元。
- `room-extractor analyze-column-features --dxf <verified-columns.dxf> --out <file>` 从已确认正确的柱专项 DXF 统计图层、颜色、填充、长宽和面积等可复用特征。
- `room-extractor infer-axis-rules --source-dxf <file> --target-dxf <file> --out <file>` 从人工整理过的源 DXF 推断轴线提取规则并应用到目标 DXF。
- `room-extractor export-json-review-html --json <file> --out <file>` 生成 `JSON人工校核` HTML，支持多个 JSON 叠加显示和开关控制；可绘制轴线、结构柱、房间识别 polygon、边界候选、房间 label 和明细表，并支持总图滚轮缩放和拖拽平移。
- `room-extractor build-room-labels --cad <cad_raw.json> --out <file>` 输出 `room_label_candidates.json`，包含房号、原始房名、房间类别、面积和文本聚类结果。
- `room-extractor build-room-candidates --cad <cad_raw.json> --labels <room_label_candidates.json> --out <file>` 输出 `room_candidates.json`，将房间 label 中心点匹配到闭合 polygon；支持 `--boundary-layer` 指定房间边界图层优先级，并可把炸碎后的 `LINE / ARC / open POLYLINE`、门洞补边和结构柱边线重建为闭合候选；支持 `--axes` / `--columns` 注入轴线和柱子 JSON 上下文。
- `room-extractor export-review-map --cad <cad_raw.json> --rooms <room_candidates.json> --out <file>` 输出 HTML/SVG 阶段检查图，仅用于 Phase 3 规则诊断。
- `room-extractor build-rooms --candidates <room_candidates.json> --out <file>` 输出 `rooms_auto.json`，生成 CAD 自动识别版初始 Room JSON。
- `room-extractor check-pdf --rooms <rooms_auto.json> --pdf <file.pdf> --out <file>` 输出 `rooms_pdf_checked.json`，提取 PDF 矢量文字并对 CAD 房间结果做局部一致性校核。
- `room-extractor render-review-images --rooms <rooms_pdf_checked.json> --pdf <file.pdf> --output-dir <dir> --out <file>` 输出带截图 evidence 的 JSON，并为低置信度房间生成 PDF 局部 PNG。
- `room-extractor check-images-ai --rooms <rooms_with_review_images.json> --out <file>` 调用本地 OpenAI 兼容多模态模型，对局部截图做辅助校核；支持 `--dry-run` 验证输入输出结构。
- `room-extractor build-review-tasks --rooms <rooms_ai_checked.json> --out <file>` 输出 PDF / OCR / AI 机器校核后的正式人工审核任务池。
- `room-extractor export-review-tasks-html --tasks <review_tasks.json> --out <file>` 输出正式人工审核 HTML，展示截图、字段、AI 判断和 issue。
- `room-extractor export-rooms-html --rooms <rooms_ai_checked.json> --out <file>` 输出识别房间总览 HTML，包含总图和每个房间的分图。
当前不包含 OCR、Streamlit 人工校核界面或最终 Room JSON 生成。Phase 5 已包含初版 CAD/PDF 线性坐标映射，但该映射仍标记为 `CAD_PDF_MAPPING_UNVERIFIED`，后续需要通过截图和 AI / 人工校核继续确认。本地 AI 命令已接入 OpenAI 兼容接口，真实调用需要先启动本地 llama.cpp 服务并准备 `common.env`。轴线和结构柱专项 JSON 是房间边界识别优化的独立输入，不替代正式房间成果。

说明：Phase 3 后的 HTML/SVG 只用于阶段开发验收和规则调试，已从正式人工审核链路中剔除。正式人工校核应使用 `review_tasks.json` 和 `export-review-tasks-html` 生成的 HTML，放在 PDF 矢量校核、局部截图、OCR / 本地 AI 辅助校验、置信度评分和 review task 生成之后。

## 当前工作流

当前代码按两个主工作流组织：

- Workflow A：DXF preparation。负责 DWG/DXF 输入标准化、AutoCAD 调用、炸块、去重和产物 DXF 管理；CLI 命令由 `room_extractor.workflows.dxf_preparation` 注册。
- Workflow B：Room extraction。负责 DXF 解析、轴线 / 柱子辅助抽取、房间文本识别、边界识别、Room JSON 生成、PDF / AI / 人工校核；CLI 命令由 `room_extractor.workflows.room_extraction` 注册。

项目根目录保留两个 workflow 专用入口：

- `python dxf_preparation.py ...`：只暴露 Workflow A 命令，例如 `convert-dwg`、`explode-dxf`、`dedupe-dxf-lines`。
- `python room_extraction.py ...`：只暴露 Workflow B 命令，例如 `extract-cad`、`build-room-labels`、`build-room-candidates`、`check-pdf`、`check-images-ai`。

这两个根目录入口的文件头均已写入中文模块 docstring，用于说明入口功能、用途、处理流程和主要参数。入口文件本身只负责把项目 `src` 目录加入 Python 模块搜索路径，并把命令行参数透传给 `src/room_extractor/cli/` 下的正式 CLI；业务参数仍由对应 workflow 的注册函数统一维护。

入口参数范围：

- `dxf_preparation.py` 覆盖 DXF 预处理参数，包括 `--input-dir`、`--output-dir`、`--recursive`、`--overwrite`、`--accoreconsole`、`--locale`、`--timeout-seconds`、`--dxf-precision`、`--explode-blocks`、`--max-explode-passes`、`--input`、`--out`、`--report-out`、`--dedupe-mode`、`--exact-tolerance`、`--near-tolerance`、`--signature-scope`、`--visible-only` 等。
- `room_extraction.py` 覆盖房间提取参数，包括 `--dxf`、`--cad`、`--labels`、`--rooms`、`--out`、`--output-dir`、`--floor`、`--visible-only`、`--axis-rules`、`--column-rules`、`--boundary-layer`、`--min-boundary-area`、`--max-boundary-area`、`--pdf`、`--page`、`--dpi`、`--margin-ratio`、`--base-url`、`--model`、`--timeout-seconds`、`--max-tokens`、`--limit`、`--dry-run`、`--title` 等。

安装后的统一入口 `room-extractor ...` 仍可使用全部命令。

## 安装

```powershell
python -m pip install -e .[dev]
```

## DWG 转 DXF

默认扫描 `data/input/cad`，输出到 `data/input/dxf`：

```powershell
room-extractor convert-dwg --input-dir data/input/cad --output-dir data/input/dxf --overwrite --timeout-seconds 300
```

如果需要在 DWG 转 DXF 时自动炸碎图块，并在输出后校核是否仍有 `INSERT`，可加 `--explode-blocks`。程序会在每轮 explode 前先解锁所有图层，再选择 modelspace 中的 `INSERT` 执行 `EXPLODE`，然后用 `ezdxf` 统计 modelspace 图块数量；只要 `remaining_insert_count > 0` 就会自动继续下一轮，直到清零或达到 `--max-explode-passes` 安全上限：

```powershell
room-extractor convert-dwg --input-dir data/input/cad --output-dir data/input/dxf_exploded --overwrite --timeout-seconds 300 --explode-blocks --max-explode-passes 5
```

对已有 DXF 也可以单独输出炸块版本：

```powershell
room-extractor explode-dxf --input-dir data/input/dxf --output-dir data/input/dxf_exploded --overwrite --timeout-seconds 300 --max-explode-passes 5
```

也可以直接传单个 DXF 文件：

```powershell
room-extractor explode-dxf --input-dir 'data/input/dxf/L2_20.00m平面图.dxf' --output-dir data/input/dxf_exploded --overwrite --timeout-seconds 1200 --progress-interval-seconds 10 --max-explode-passes 5
```

长时间炸块时可缩短进度日志间隔，便于确认 CoreConsole 没有卡死：

```powershell
room-extractor explode-dxf --input-dir data/input/dxf --output-dir data/input/dxf_exploded --overwrite --timeout-seconds 1200 --progress-interval-seconds 10 --max-explode-passes 5
```

心跳日志会附带 AcCoreConsole 的 stdout/stderr 尾部内容，便于判断当前是否停在选择对象、解锁图层、DXFOUT 或 AutoCAD 报错提示上。LISP explode 循环中还会每 100 个块输出一次 `ROOM_EXTRACTOR_EXPLODE_PROGRESS 1200/5769` 形式的进度，方便判断当前 pass 是否仍在推进。

AcCoreConsole 的中间 DXF、SCR、stdout/stderr 日志，以及子进程环境变量 `TEMP` / `TMP` / `TMPDIR` 默认都写入 `D:/TEMP/room_extractor_acad_*`。这样可以避开 Windows 系统盘空间不足导致的 AutoCAD 致命错误，例如“无法写入放弃文件”。运行完成且未指定 `--keep-scripts` 时，程序会清理本次运行创建的临时子目录。

炸块后的 DXF 可能产生大量重合线性图元。`room-extractor dedupe-dxf-lines` 可统计和清理 `LINE / LWPOLYLINE / POLYLINE / ARC` 重复实体。默认不写输出；传入 `--out` 时才生成清理后的 DXF：

```powershell
room-extractor dedupe-dxf-lines `
  --input "data/input/dxf_exploded/L2_20.00m平面图.dxf" `
  --report-out data/output/reports/dxf_exploded_duplicate_stats.json `
  --progress-interval 500000
```

保守清理只删除同图层、同几何签名的完全重复或反向一致线性实体，并把结果写回源 DXF 同目录、文件名加 `-DEDUP-EXACT`：

```powershell
room-extractor dedupe-dxf-lines `
  --input "data/input/dxf_exploded/L2_20.00m平面图.dxf" `
  --out "data/input/dxf_exploded/L2_20.00m平面图-DEDUP-EXACT.dxf" `
  --report-out "data/output/reports/L2_20.00m平面图-DEDUP-EXACT-report.json" `
  --dedupe-mode exact `
  --exact-tolerance 1e-9 `
  --progress-interval 500000
```

更激进的近似清理可忽略图层、颜色等属性，只按几何签名和 `--near-tolerance` 量化后的坐标去重，文件名加 `-DEDUP-NEAR`：

```powershell
room-extractor dedupe-dxf-lines `
  --input "data/input/dxf_exploded/L2_20.00m平面图.dxf" `
  --out "data/input/dxf_exploded/L2_20.00m平面图-DEDUP-NEAR.dxf" `
  --report-out "data/output/reports/L2_20.00m平面图-DEDUP-NEAR-report.json" `
  --dedupe-mode near `
  --signature-scope geometry `
  --near-tolerance 1.0 `
  --progress-interval 500000
```

真实样本 `L2_20.00m平面图.dxf` 已验证：原始 581M；`-DEDUP-EXACT` 删除 `55,847` 个重复线性实体后为 453M；`-DEDUP-NEAR` 在 `near_tolerance=1.0`、`signature_scope=geometry` 下删除 `127,293` 个近似重复线性实体后为 436M。近似清理会跨图层去重，建议先人工打开确认。

## DXF 自驱动清理实验

针对炸块后 DXF 中大量非几何数据导致文件膨胀、计算量增加和房间识别效果下降的问题，项目根目录新增实验脚本：

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --max-steps 1 --dry-run-ai
```

该脚本以一个臃肿 DXF 和一个视觉等价的小 DXF 为参考，按小步迭代清理：

- 每轮只删除一类候选数据。
- 每轮保存 `input.dxf`、`candidate_after.dxf`、`accepted_after.dxf` / `rejected_after.dxf`。
- 每轮生成 `report.html`、`removed_*.json`、`before_stats.json`、`after_stats.json`、`visual_check.json`。
- 每轮生成 `reference.png`、`before.png`、`after.png`、`diff.png`、`comparison.png`，用于人工或本地视觉模型复核。
- 每个 accepted step 都记录 rollback point。

当前实验样本已验证：

- 原始 `test.dxf`：约 155 MB。
- 参考 `test1.dxf`：323,576 bytes。
- 最终 accepted DXF：`log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`。
- 最终大小：437,346 bytes。
- AutoCAD 2024 人工打开验证：通过。

已验证的清理链包括：不可见 modelspace 实体、`ACAD_LAYERSTATES`、未使用 APPID、不可达 blocks、非几何 OBJECTS 元数据、未使用符号表、paper-space layouts、`CLASSES` / `ACDSDATA` 段、`POINT` / `XLINE` 辅助实体、二次 block/table 清理和大型空字典壳。

注意：当前实现没有实际调用本地 AI 或 Qwen；`--dry-run-ai` 只写入占位状态。自动接受依据是 ezdxf reload、结构保护检查、before/after PNG 像素差异和 AutoCAD 人工验证。通用“小步可审计解决问题”方法论 skill 已写入 `auditable-incremental-problem-solving-skill/SKILL.md`，不限定 DXF 或 AutoCAD 场景。

详细记录：

- `docs/dxf_self_cleaning_plan.md`
- `docs/dxf_cleaning_work_summary.md`

如果需要显式指定 AutoCAD 2024 控制台程序：

```powershell
room-extractor convert-dwg --input-dir data/input/cad --output-dir data/input/dxf --overwrite --timeout-seconds 300 --accoreconsole "C:\Program Files\Autodesk\AutoCAD 2024\AcCoreConsole.exe"
```

实现说明：

- 使用 `AcCoreConsole.exe /i input.dwg /s script.scr /l en-US`。
- 每个 DWG 会先复制到临时 ASCII 工作目录，避免 AutoCAD `.scr` 对中文路径解析失败。
- 转换完成后再把生成的 DXF 移动到目标目录。
- 炸块输出的 CLI JSON 摘要会记录 `explode_passes` 和 `remaining_insert_count`；如果剩余数量大于 0，说明存在无法被 AutoCAD `EXPLODE` 继续展开的对象或受保护/代理对象，需要人工处理或保留为块。
- 当前真实样本已验证：经过多轮 `explode-dxf` 后，处理后的 DXF 中 modelspace `INSERT` 可清零；该 DXF 可在 AutoCAD 中正常打开、编辑和保存。
- 炸块后的重线清理由 `room-extractor dedupe-dxf-lines` 处理，输出 DXF 和报告仍被 `.gitignore` 排除。
- 真实图纸数据、转换后的 DXF、输出 JSON 和日志均被 `.gitignore` 排除。

## DXF 解析

分析图层：

```powershell
room-extractor analyze-layers --dxf data/input/dxf/sample.dxf
```

仅分析 CAD 中未关闭、未冻结、未设置 invisible 的图元：

```powershell
room-extractor analyze-layers --dxf data/input/dxf/sample.dxf --visible-only
```

提取 CAD 原始对象：

```powershell
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw.json
```

如果输入 DXF 是人工处理后的可见图层版本，建议使用 `--visible-only`：

```powershell
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw_visible.json --visible-only
```

仅提取轴线专项 JSON：

```powershell
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw_axis_check.json --axis-only
```

轴线专项提取默认读取 `src/room_extractor/config/axis_layer_rules.yaml`：

```yaml
axis_layers:
  - A-GRID

axis_label_layers:
  - A-ANNO-TXT
```

如需指定其他规则文件：

```powershell
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw_axis_check.json --axis-only --axis-rules path/to/axis_layer_rules.yaml
```

也可以用 Workflow B 命令从一个人工整理过的源 DXF 中推断轴线提取规则，再应用到另一个目标 DXF：

```powershell
python room_extraction.py infer-axis-rules `
  --source-dxf "data/input/dxf/L2_20.00m平面图-AXIS.dxf" `
  --target-dxf "data/input/dxf_exploded/L2_20.00m平面图.dxf" `
  --out data/output/json/cad_raw_axis_inferred_from_exploded.json `
  --source-out data/output/json/cad_raw_axis_inferred_source_reference.json `
  --rules-out data/output/json/inferred_axis_rules_from_axis_to_exploded.json
```

当前实现用于 AXIS 专项：从源 DXF 图层的名称、冻结/关闭/锁定状态、颜色、线型和图元类型统计中推断轴线层与轴号层；应用到目标 DXF 时优先精确图层名匹配，再按 `$` 后缀和图层属性匹配。脚本仍复用已有 `extract_cad_raw(axis_only=True)`，因此输出 JSON 结构与 `extract-cad --axis-only` 保持一致。`rules-out` 会写入推断规则、源/目标图层 profile 和 `validation` 摘要。若目标 DXF 已经过炸块处理，只要求语义 JSON 结果一致，即 `axes`、`texts`、`issues` 一致；`layers` 中的 `insert_count` 等图层上下文统计允许不同。

`cad_raw.json` 至少包含：

```json
{
  "source_file": "sample.dxf",
  "layers": [],
  "texts": [],
  "blocks": [],
  "polylines": [],
  "axes": [],
  "issues": []
}
```

`polylines` 会保存 `LWPOLYLINE / POLYLINE / LINE / ARC` 的点列，其中 `LINE / ARC` 作为开放线性对象输出，供炸碎后的墙线重建房间边界使用。`axes` 来自轴网图层中的 `LINE / LWPOLYLINE / POLYLINE / ARC`。弧形轴线会采样为点列；同一图层中首尾相接的弧段会合并为一根曲线轴线。每条至少包含：

```json
{
  "layer": "A-AXIS",
  "entity_type": "LINE",
  "points": [[0, 0], [10000, 0]],
  "bbox": [0, 0, 10000, 0],
  "length": 10000
}
```

## 结构柱专项 JSON

从已确认正确的柱专项 DXF 中提取可复用特征：

```powershell
room-extractor analyze-column-features --dxf data/input/dxf/L2_20.00m平面图-COLUMNS.dxf --out data/output/json/column_features_real.json
```

该命令会统计：

- 图层后缀，例如外参图层中的 `A-STR-COLM`。
- 实体类型，例如 `HATCH`。
- DXF 颜色、true color、线型。
- HATCH 填充模式、是否 solid fill、边界 path 数量。
- 单个柱图元的宽、高、面积分布，包括 min / p50 / p90 / p95 / p99 / max。
- `recommended_rules`：带余量的推荐复用规则。

默认结构柱规则位于 `src/room_extractor/config/column_layer_rules.yaml`。当前真实样本沉淀的核心特征为：

```yaml
column_layers:
  - A-STR-COLM

column_entity_types:
  - HATCH

color_indices:
  - 256

hatch_patterns:
  - SOLID

solid_fill: true
max_width: 1800
max_height: 1800
max_area: 2500000
expand_insert_virtual_entities: true
```

直接从全量 DXF 提取结构柱，不需要在 CAD 中手工冻结/隐藏无关图元：

```powershell
room-extractor extract-cad --dxf data/input/dxf/L2_20.00m平面图.dxf --out data/output/json/cad_raw_columns_from_full_real.json --columns-only
```

输出 `columns` 字段，每个结构柱至少包含：

```json
{
  "column_id": "column_00001",
  "layer": "xref$0$A-STR-COLM",
  "entity_type": "HATCH",
  "source": "hatch_boundary",
  "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]],
  "bbox": [0, 0, 1000, 1000],
  "center": [500, 500],
  "area": 1000000,
  "width": 1000,
  "height": 1000
}
```

说明：

- `extract-cad --columns-only` 会按图层、实体类型、颜色、HATCH 填充和尺寸范围过滤候选。
- 当柱图元位于块或外参内部时，会通过 `INSERT.virtual_entities()` 展开后再识别。
- HATCH 有多条边界 path 时，当前取最大边界作为柱外轮廓，避免内外边界重复输出。
- 真实 L2 全量 DXF 已验证可直接提取 `750` 个结构柱，与手工柱专项 DXF 的确认结果一致。

## JSON 人工校核 HTML

从任意 CAD 原始 JSON 生成人工校核 HTML：

```powershell
python room_extraction.py export-json-review-html --json data/output/json/cad_raw_axis_check.json --out data/output/reports/json_review_real.html
```

默认只绘制轴线和匹配到的真实轴号标注，不绘制 `texts` 和 `polylines` 垃圾底图。需要调试完整原始 JSON 时可显式打开：

```powershell
python room_extraction.py export-json-review-html --json data/output/json/cad_raw_real.json --out data/output/reports/json_review_real.html --include-polylines --include-texts
```

多个 JSON 可以叠加到同一个 HTML 中，并通过页面顶部开关切换不同 JSON 数据源。

轴线和结构柱可以叠加检查：

```powershell
python room_extraction.py export-json-review-html --json data/output/json/cad_raw_axis_check.json --json data/output/json/cad_raw_columns_from_full_real.json --out data/output/reports/json_review_axis_columns_from_full.html
```

房间识别结果、轴线和结构柱也可以叠加检查：

```powershell
python room_extraction.py export-json-review-html `
  --json data/output/json/room_candidates_room_wall_visible.json `
  --json data/output/json/cad_raw_axis_check.json `
  --json data/output/json/cad_raw_columns_from_full_real.json `
  --out data/output/reports/json_review_room_recognition_room_wall.html `
  --title "ROOM_WALL房间识别JSON人工校核" `
  --include-boundaries
```

房间校核 HTML 会绘制：

- `room_candidates[].boundary` 或 `rooms[].geometry.polygon_cad`。
- `boundary_candidates`，需传 `--include-boundaries`。
- 房间 label 文字、房间状态颜色和房间明细表。
- 轴线、轴号、结构柱叠加图层。

总图交互：

- 鼠标滚轮按指针所在位置缩放。
- 鼠标左键拖拽平移。
- 双击总图或点击 `重置` 回到全图。
- 缩放时线宽、点半径和文字高度会自动反向调整，保持屏幕视觉大小基本一致。

该交互已在 `json_review_room_recognition_room_wall_zoom.html` 上验证，可用于房间名称密集区域的局部放大校核。

## 房间文字识别

从 `cad_raw.json` 生成 Phase 2 的房间 label 候选：

```powershell
room-extractor build-room-labels --cad data/output/json/cad_raw.json --out data/output/json/room_label_candidates.json --floor L2
```

输出包括：

- `parsed_texts`：每条 CAD 文本的标准化和字段识别结果。
- `candidates`：相邻房号、原始房名、房间类别、面积聚类后的房间 label 候选。
- `candidate_id`、`floor`、`room_number`、`room_name`、`room_name_raw`、`room_category`、`area`、`center`、`bbox`、`confidence`、`issues`。

Phase 2 会对常见 CAD 中文乱码做 GBK mojibake 恢复，例如真实图纸中的会议室、贵宾室、卫生间等文本可恢复后再解析。

当前词表已覆盖常规房间、机电空间和部分房间型特殊空间，例如 `空调机房`、`强电`、`弱电`、`风井`、`水井`、`楼梯`。这类标注会作为房间 label 进入后续边界匹配。房号识别已覆盖 `C.L2.M001-C04`、`C.L2.M020`、`C.2.M002` 等机电房编号格式。

## 房间边界识别

从 `cad_raw.json` 和 `room_label_candidates.json` 生成 Phase 3 的房间候选：

```powershell
room-extractor build-room-candidates --cad data/output/json/cad_raw.json --labels data/output/json/room_label_candidates.json --out data/output/json/room_candidates.json --floor L2
```

可显式指定房间边界图层和优先级，并注入轴线 / 柱子 JSON 上下文：

```powershell
room-extractor build-room-candidates `
  --cad data/output/json/cad_raw_room_wall_visible.json `
  --labels data/output/json/room_label_candidates_room_wall_visible.json `
  --out data/output/json/room_candidates_room_wall_visible.json `
  --floor L2 `
  --boundary-layer '0-面积线' `
  --boundary-layer 'WALL' `
  --boundary-layer 'Defpoints' `
  --axes data/output/json/cad_raw_axis_check.json `
  --columns data/output/json/cad_raw_columns_from_full_real.json
```

注意：PowerShell 中包含 `$1` 的图层名必须使用单引号，否则 `$1` 会被变量展开，导致图层规则失真。`--boundary-layer WALL` 是关键字规则，会纳入图层名中包含 `WALL` 的墙体层，例如 `05-L2-WALL$1$VT-WALL-总包` 和 `面积平面 - 会议2F- 20.00m平面图$1$A-WALL`。`ROOM_WALL` 当前样本中右侧 `服务间 2-07（66㎡）` 的闭合边界位于 `Defpoints`，复跑时需要保留该图层。

输出包括：

- `boundary_candidates`：过滤后的闭合 CAD polygon，包含 `bbox_cad` 和 `area_cad`。
- `room_candidates`：每个 room label 与 polygon 的匹配结果。
- `summary`：状态、匹配方式和 issue 统计摘要。
- 严格匹配：优先房间边界/面积线图层，使用 label 中心点落入 polygon 的最小合适边界。
- 炸碎墙线：当指定 `--boundary-layer` 时，会在这些图层上把开放 `LINE / ARC / open POLYLINE` 线段 polygonize 为 `SEGMENT_POLYGONIZED` 闭合候选，用于人工处理后暴露墙体线段的 DXF。
- 门洞补边：对近似共线且距离在门宽范围内的墙端点补虚拟闭合边，补边数量写入 `door_gap_bridge_count` metadata，后续 HTML/人工校核可据此判断风险。
- fallback 匹配：普通房间中心点未落入 polygon 时，可按优先边界图层 bbox 距离生成 `matched_fallback`，并写入 `LABEL_OUTSIDE_BOUNDARY_FALLBACK_MATCH`。
- 文字面积反查：当房间文字包含面积时，若附近边界的 CAD 面积与文字面积偏差小于阈值，会优先采用该边界并写入 `LABEL_OUTSIDE_BOUNDARY_AREA_MATCH`。该规则用于处理 MTEXT 插入点/对齐点落在相邻房间内、但视觉文字属于旁边房间的情况。
- 特殊空间：客梯、货梯、电梯厅、走道、通道等无面积空间不强行 fallback，标记 `SPECIAL_SPACE_NO_AREA_BOUNDARY` 等待人工确认。
- 房间型特殊空间：强电、弱电、风井、水井、楼梯等标注本身按房间处理，即使缺少面积文字，也允许按面积线或墙体闭合 polygon 低置信度匹配。
- 柱子辅助：当传入 `--columns` 时，结构柱边线会作为可闭合边界段参与 polygonize；边界候选会增加 `column_overlap_count`、`column_overlap_area`、`column_nearby_count`、`usable_area_cad` 等元数据，用于人工检查和后续规则优化。`rooms_auto.json` 的 CAD 计算面积优先使用扣除柱重叠后的 `usable_area_cad`；柱子 JSON 仍保持独立，不直接并入房间成果。

导出阶段检查图：

```powershell
room-extractor export-review-map --cad data/output/json/cad_raw.json --rooms data/output/json/room_candidates.json --out data/output/reports/room_candidates_review.html
```

检查图是自包含 HTML/SVG 文件，包含浅色 CAD 底图、绿色严格匹配、橙色低置信度匹配、红色未匹配标签和候选列表。它仅用于 Phase 3 规则诊断，不进入正式人工审核链路。

## 初始房间 JSON

从 `room_candidates.json` 生成 Phase 4 的 CAD 自动识别版房间 JSON：

```powershell
room-extractor build-rooms --candidates data/output/json/room_candidates.json --out data/output/json/rooms_auto.json
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

## 正式人工审核 HTML

PDF 矢量校核、局部截图、本地 AI 辅助校核和 review task 生成之后，导出正式人工审核页面：

```powershell
room-extractor build-review-tasks --rooms data/output/json/rooms_ai_checked.json --out data/output/json/review_tasks.json
room-extractor export-review-tasks-html --tasks data/output/json/review_tasks.json --out data/output/reports/review_tasks.html
```

该 HTML 用于正式人工审核，展示每个待审任务的 PDF 局部截图、自动识别字段、CAD 几何预览、PDF evidence、本地 AI 判断、issue 和建议修正字段。

## 识别房间总览 HTML

从全链路后的房间 JSON 导出房间总览页面：

```powershell
room-extractor export-rooms-html --rooms data/output/json/rooms_ai_checked.json --out data/output/reports/recognized_rooms.html
```

该 HTML 展示所有识别到的房间，左侧为 CAD 坐标总图和房间列表，右侧为每个房间的 PDF 局部分图、识别字段、CAD 几何预览、PDF/AI 校核结论和 issue。

## PDF 矢量文字校核

从 `rooms_auto.json` 和对应 PDF 生成 Phase 5 的机器校核结果：

```powershell
room-extractor check-pdf --rooms data/output/json/rooms_auto.json --pdf data/input/pdf/sample.pdf --out data/output/json/rooms_pdf_checked.json --page 1
```

输出包括：

- `pdf_text`：PDF 矢量文字及 bbox。
- `transform`：CAD bbox 到 PDF bbox 的线性映射参数。
- `rooms[].geometry.bbox_pdf`：映射后的 PDF 局部 bbox。
- `rooms[].evidence.pdf_source`：PDF 来源文件、页码、局部 bbox、局部文字和文字数量。
- `issues`：PDF 未找到局部文字、房号 / 房名 / 面积不一致、缺少 CAD geometry 等问题。
- `confidence.cad_pdf_consistency`：CAD 与 PDF 局部文本一致性分数。

注意：当前 CAD/PDF 坐标映射是基于房间 CAD bbox 外接范围到 PDF 页面外接范围的初版线性拟合，输出会保留 `CAD_PDF_MAPPING_UNVERIFIED` 顶层 issue。它适合作为后续局部截图、OCR / 本地 AI 辅助校验和 review task 生成的输入，不作为最终人工确认结论。

## PDF 局部截图

从 `rooms_pdf_checked.json` 生成 Phase 6 的局部截图，并把截图 evidence 写回 JSON：

```powershell
room-extractor render-review-images --rooms data/output/json/rooms_pdf_checked.json --pdf data/input/pdf/sample.pdf --output-dir data/output/review_images/sample --out data/output/json/rooms_with_review_images.json --dpi 200
```

输出包括：

- `rooms[].evidence.pdf_source.review_image.path`：局部 PNG 路径。
- `crop_bbox`：PDF 裁剪坐标。
- `dpi` 和 `margin_ratio`：截图渲染参数。
- `source`：`pdf_bbox_crop` 或 `pdf_text_anchor_crop`。
- `summary.review_images_rendered`：实际生成截图数。
- `summary.review_images_skipped_no_bbox`：因缺少 PDF bbox 跳过的房间数。

说明：渲染时会把 PDF 页面统一到未旋转坐标系，避免带旋转页面的 bbox 与截图错位。若房号能在 PDF 矢量文字中匹配，会优先以房号位置生成 anchor crop，让截图更容易看到房间标签和周边边界；否则退回 PDF bbox crop。

## 本地 AI 辅助校验

从 `rooms_with_review_images.json` 调用本地 OpenAI 兼容多模态模型：

```powershell
room-extractor check-images-ai --rooms data/output/json/rooms_with_review_images.json --out data/output/json/rooms_ai_checked.json --limit 3
```

如果本地模型服务尚未启动，可先验证结构：

```powershell
room-extractor check-images-ai --rooms data/output/json/rooms_with_review_images.json --out data/output/json/rooms_ai_checked_dry_run.json --dry-run --limit 3
```

配置读取顺序：

- `common.env` 中的 `LLAMACPP_BASE_URL`、`LLAMACPP_MODEL`、`LLAMACPP_TIMEOUT_SECONDS`、`LLAMACPP_MAX_TOKENS`。
- 进程环境变量。
- CLI 参数 `--base-url`、`--model`、`--timeout-seconds`、`--max-tokens` 覆盖默认值。

输出写入 `rooms[].evidence.pdf_source.local_ai_check`，真实调用时要求模型只返回 JSON，用于判断截图是否可见、房号 / 房名 / 面积是否匹配、是否需要后续校核。

CUDA 注意事项：

- `LLAMACPP_EXTRA_DLL_DIRS` 必须指向 CUDA runtime DLL 目录。
- 当前本机目录为 `../vendor/cuda12`，包含 `cudart64_12.dll`、`cublas64_12.dll`、`cublasLt64_12.dll`。
- 可用 `llama-server.exe --list-devices` 验证，期望看到 `CUDA0` 和 `loaded CUDA backend`。
- 项目自动启动的 `llama-server` 会在当前命令结束后关闭，命令结束后 GPU-Z / nvidia-smi 看不到进程是正常现象。

## 项目结构

```text
src/room_extractor/
  ai/         本地 OpenAI 兼容多模态模型客户端和截图校核流程
  cad/        DXF 加载、DWG 转换、炸块去重、图层分析、文本/块/线性对象/轴网线/结构柱提取
  cli/        命令行入口
  config/     图层规则配置、轴线和结构柱专项规则
  export/     阶段检查图等导出能力
  extraction/ 房间文字解析、label 聚类、边界识别、Room JSON 生成
  geometry/   bbox、polygon 面积、IoU 等基础几何能力
  models/     Pydantic 数据模型
  pdf/        PDF 矢量文字提取和 CAD/PDF 局部一致性校核
  utils/      日志配置等通用工具
  workflows/  DXF preparation 与 Room extraction 两个主工作流的 CLI 编排
tests/        单元测试
docs/         项目文档
data/         本地输入输出目录，真实数据不入库
```

## 测试

```powershell
python -m pytest
```

当前通过用例覆盖：

- DXF 加载、图层统计、TEXT/MTEXT/INSERT/LWPOLYLINE/LINE/ARC/AXIS 提取
- 炸碎墙线 polygonize 为房间边界候选
- 轴线专项提取、轴线图层 YAML 规则、轴线 JSON 人工校核入口
- 结构柱专项提取、结构柱特征分析、柱规则 YAML、块 / 外参内部图元展开
- DWG 文件扫描与转换路径组织
- `convert-dwg` CLI 汇总输出
- 房号、原始房名、房间类别、面积正则识别
- CAD 中文 mojibake 文本恢复
- 相邻房号、房名、面积聚类为 room label candidate
- 闭合 CAD polygon 过滤、bbox/面积输出、label 到 polygon 匹配
- 门洞补边、结构柱边线参与 polygonize、柱重叠面积扣减
- 初始 Room JSON 生成、CAD 面积换算、面积偏差和初始 confidence
- PDF 矢量文字提取、bbox 局部查找、CAD/PDF 字段一致性校核
- `check-pdf` CLI 输出
- PDF 局部截图渲染、旋转页面处理、基于房号的 anchor crop
- `render-review-images` CLI 输出
- 本地 AI 截图校核 dry-run 结构验证
- `check-images-ai` CLI 输出
- 几何 bbox、面积、点在 polygon 内、IoU

## 重启后建议起点

下一次对话可直接从“结构柱辅助房间边界优化”开始。当前基线已经可以从全量 DXF 自动生成轴线 JSON 和结构柱 JSON，不需要再手工冻结 / 隐藏图层后另存柱专用 DXF。

建议先确认基线：

```powershell
python -m pytest
```

然后复用或重新生成结构柱专项 JSON：

```powershell
room-extractor extract-cad --dxf data/input/dxf/L2_20.00m平面图.dxf --out data/output/json/cad_raw_columns_from_full_real.json --columns-only
```

若需要人工核对轴线和结构柱叠加效果：

```powershell
python room_extraction.py export-json-review-html --json data/output/json/cad_raw_axis_check.json --json data/output/json/cad_raw_columns_from_full_real.json --out data/output/reports/json_review_axis_columns_from_full.html
```

下一步工程目标是把 `columns` JSON 作为房间边界识别优化的独立输入：用于标记柱体障碍、柱体重叠、候选 polygon 扣除或降权，以及区分柱外轮廓、墙线和房间可用边界。结构柱 JSON 继续保持独立，不直接并入 `rooms_auto.json`，只作为匹配、校核和后处理规则的证据输入。

## 进展文档

阶段进展见 [docs/project_progress.md](docs/project_progress.md)。
