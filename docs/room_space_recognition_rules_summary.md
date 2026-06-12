# 房间空间识别规则与验证总结

本文档记录 `accepted_after.dxf` 上完成的房间空间识别算法验证、规则设置和当前结论。目标是把本轮人工校核形成的规则固化，作为后续泛化测试和回归测试的依据。

## 验证对象

- 源文件：`log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`
- 实验脚本：`room_recognition_experiment.py`
- 实验输出：`log/room_recognition_experiment/`
- 最终采用步骤：`log/room_recognition_experiment/steps/001_wall_boundary_with_door_gap`
- 人工校核页面：`log/room_recognition_experiment/steps/001_wall_boundary_with_door_gap/room_candidates.html`

清理后的 DXF 保留墙体和结构柱，门扇图形已被清除，只留下门洞。当前算法因此把门洞作为房间分隔逻辑的一部分处理。

## 当前验证结果

最终步骤 `wall_boundary_with_door_gap` 的状态为 `candidate_passed_ai`。

- 房间候选数：9
- 边界候选数：22
- 匹配成功：8
- 兜底匹配：1
- 自动失败：0
- 门洞补桥：24
- 小墙缝拼接：5
- 电梯符号候选：2
- 结构柱识别数量：10
- 与结构柱有交叠关系的边界：10

匹配方法统计：

- `point_in_polygon_smallest_area`：6
- `nearest_preferred_boundary_bbox_fallback`：1
- `elevator_symbol_shape`：2

当前保留的问题标记：

- `AREA_MISSING`：7。原始图中多数房间缺少面积文本，不影响空间边界识别。
- `LABEL_OUTSIDE_BOUNDARY_FALLBACK_MATCH`：1。排烟井文字位置没有精确落在目标狭长空间内，已通过人工校核确认兜底匹配正确。

## 本地 AI 验证

本轮验证使用本地 AI 真实检查候选结果，不使用 dry run。

- 模型：`Qwen3.6-27B-Q4_K_M`
- 地址：`http://127.0.0.1:8080/v1`
- `dry_run`：`false`
- 检查候选：9
- 检查失败：0
- 需要复核：0

AI 校核结论覆盖排烟井、合用前室、强弱电房间、加压、楼梯和两个客梯候选，边界判断均为通过。

## 已固化规则

### 墙体边界

房间空间的主边界来自墙体类图层，多边形化时使用以下逻辑：

- 参与边界识别的图层关键字：`WALL`、`0-面积线`、`Defpoints`
- 门洞宽度范围：700mm 到 2500mm
- 门洞处理：墙体开口在该范围内时作为门洞补桥，保持房间边界闭合，但不把门洞误认为墙体缺失
- 小墙缝拼接：小于等于 300mm 的同轴墙线断点作为绘图断裂拼接，不作为门洞
- 正交过滤：本项目墙体为水平和竖直墙，带明显斜边的候选边界被排除
- 斜线容差：`orthogonal_tolerance = 2.0`
- 明显非正交边阈值：`max_non_orthogonal_edge_length = 50.0`

### 非墙体辅助线

以下图层不能作为常规房间边界来源：

- `A-DETL-GENF`：引出标注和细部图形，存在斜线，不作为普通墙体边界
- `A-HOLE-E`：板洞表达，不是实际墙体
- `A-STAIR`：楼梯画法线，不是房间边界

补充说明：更新后的 DXF 中电梯图例线条可能也落在 `A-DETL-GENF` 等细部图层内。该图层仍不能作为普通边界来源，只能在严格满足电梯符号强条件时作为电梯定位证据。

### 结构构件

结构图层封闭区域不是需要识别的房间空间或竖井空间：

- `S-BEAM` 表示结构梁或结构线
- `A-STR-COLM` 表示结构柱
- `A-STR-CONC`、`A-STR-BEAM`、`结构梁` 等结构类图层只用于结构上下文或排除误识别

`S-BEAM` 与柱子围合出的空间属于结构体，不输出为房间、竖井或电梯空间。

### 结构柱参与边界

部分真实房间墙体会借用结构柱边界，例如 `E.L2.E208 弱电`。算法允许结构柱作为边界上下文参与候选判断，但不会把结构构件自身围合出的区域作为目标空间输出。

### 楼梯

楼梯空间可通过文本编码和闭合空间共同识别：

- `E-ST` 或 `C-ST` 表示楼梯
- 楼梯闭合空间内通常存在 `上` 或 `下` 等方向文字
- 当前 `E-ST24` 已通过识别和校核

### 加压与排烟井

加压空间通过房间文字和墙体闭合边界识别。

排烟井识别需要注意：

- 原始 DXF 中排烟井文字可能没有精确落到目标狭长空间内
- 可使用就近优先边界兜底匹配
- 结构图层围合空间必须排除，避免把结构体误识别为排烟井
- 本轮人工校核确认 `E.L2.M215 排烟井` 的狭长边界候选正确

### 电梯空间

电梯识别采用图纸符号强条件，输出对象是电梯外周建筑墙体包围的空间，不是轿箱本身。

强条件包括：

- 存在矩形轿箱核心图例
- 轿箱核心内存在两条对角交叉线
- 轿箱一侧存在细长矩形构件
- 存在包含轿箱核心、交叉线和侧边细长矩形的更大外周空间包络
- `S-BEAM` 等结构图层完全排除，不能作为电梯空间来源

当前两个电梯候选均由 `elevator_symbol_shape` 生成：

- `room_candidate_0008`
  - 空间包络：`[758207.3535797374, -211860.0896270339, 760907.3535797375, -209360.089627034]`
  - 轿箱核心：`[758657.3535797374, -211510.0896270339, 760457.3535797377, -209710.0896270339]`
- `room_candidate_0009`
  - 空间包络：`[761107.3535797375, -211860.0896270339, 763807.3535797378, -209360.089627034]`
  - 轿箱核心：`[761557.3535797375, -211510.0896270339, 763357.3535797374, -209710.0896270339]`

## HTML 人工校核约定

`room_candidates.html` 已调整为便于人工校核：

- DXF 底图和识别 JSON 数据源分开显示，避免同名 `accepted_after.dxf` 混淆
- 原始 DXF 辅助线、文本点、多段线和识别结果分层控制
- 房间标签字号放大，便于直接核对
- 结构柱独立显示
- 默认重点展示识别候选，DXF 辅助内容可按需打开

## 相关代码位置

- 边界检测：`src/room_extractor/extraction/room_boundary_detector.py`
- 候选构建：`src/room_extractor/extraction/room_candidate_builder.py`
- 文本解析：`src/room_extractor/extraction/room_text_parser.py`
- 电梯符号识别：`src/room_extractor/extraction/elevator_symbol_detector.py`
- HTML 校核页导出：`src/room_extractor/export/json_review_html.py`
- 工作流入口：`src/room_extractor/workflows/room_extraction.py`
- 实验脚本：`room_recognition_experiment.py`

## 回归验证

已执行：

```powershell
python -m pytest -q
python room_recognition_experiment.py
```

结果：

- 单元测试：91 passed
- 实验状态：`candidate_passed_ai`
- 本地 AI：9 个候选全部通过，0 失败，0 需复核

## 后续使用注意

- 当前规则已针对本项目 `accepted_after.dxf` 通过人工和本地 AI 校核。
- 若换用新 DXF，应优先复用 `room_recognition_experiment.py` 生成 auditable step 输出，再用 HTML 和本地 AI 共同核对。
- 新项目如果存在斜墙、弧墙或非正交房间，当前正交过滤规则需要重新配置。
- 电梯识别必须继续保持强符号条件，避免把结构矩形、梁构件或轿箱自身误输出为电梯空间。
