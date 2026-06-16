# 建筑外轮廓内包络线识别记录

记录日期：2026-06-16

本文记录 `L2_20.00m平面图-BuildingFacadeOutline.dxf` 建筑外轮廓识别、内包络线构造、人工校核和后续复用方式。当前人工通过版本为 `log/building_facade_inner_envelope/steps/002_curve_facade_profile`。

## 背景

输入 DXF：

`data/input/dxf/L2_20.00m平面图-BuildingFacadeOutline.dxf`

该文件是 L2 标高建筑外轮廓。上部立面包含曲线和中部凹口，左右及下部主要由直线构成。识别结果需要结合已有柱识别数据，为后续房间边界识别提供建筑平面外轮廓的内包络线。

柱识别输入：

`data/output/json/cad_raw_columns_from_full_real.json`

## 代码入口

新增根目录脚本：

`building_facade_inner_envelope.py`

默认运行命令：

```powershell
python building_facade_inner_envelope.py
```

主要默认参数：

- DXF：`data/input/dxf/L2_20.00m平面图-BuildingFacadeOutline.dxf`
- 柱 JSON：`data/output/json/cad_raw_columns_from_full_real.json`
- 输出目录：`log/building_facade_inner_envelope/steps/002_curve_facade_profile`
- 内偏移距离：`300.0`
- 本地 AI 校核：默认直接运行，不 dry-run

## 识别方法

本轮使用小步审计方式推进，每个 step 输出候选 JSON、验收 JSON、统计、校核、图片和 HTML。

step001 使用上沿分位数拟合，人工发现上部曲线立面被压平，已废弃。

step002 修正为显式提取上部曲线立面链：

- 从 `A-FIN-S` 图层提取左侧上部 ARC、中部凹口 LWPOLYLINE、凹口右侧 ARC。
- 从 `20m幕墙_dwg` 图层提取右侧上部两段 ARC。
- 将 5 个源实体按 X 方向串接、加密采样，形成上部外轮廓 profile。
- 左、右、下三侧使用直线边界构造。
- 通过 Shapely 对外轮廓执行向内偏移，得到内包络线。
- 将外轮廓和内包络线写回 `CadRawExtraction` 兼容 JSON，方便复用现有 HTML 校核器和后续房间识别流程。

## 当前通过版本

人工通过目录：

`log/building_facade_inner_envelope/steps/002_curve_facade_profile`

关键产物：

- `accepted_after.json`：通过版本，后续流程应优先使用。
- `candidate_after.json`：同一轮候选输出。
- `json_review_facade_outer_inner.html`：人工校核页面。
- `comparison.png`：外轮廓、内包络线和柱子的对比图。
- `report.html`：审计报告。
- `after_stats.json`：几何统计。
- `automated_check.json`：自动规则校核。
- `ai_validation.json`：本地 AI 视觉校核记录。

`accepted_after.json` 中新增的数据层：

- `BUILDING-FACADE-OUTER-PROFILE`：建筑外轮廓 profile。
- `BUILDING-FACADE-INNER-ENVELOPE`：向内偏移后的内包络线。
- `boundary_candidates[0].id = building_inner_envelope_00001`：供房间识别使用的建筑内包络边界候选。

## 验证结论

step002 自动校核通过：

- 外轮廓面积：`62365532310.98865`
- 内包络线面积：`61999359922.11774`
- 面积比例：`0.9941286095812512`
- 外轮廓点数：`398`
- 内包络线点数：`308`
- 柱数量：`750`
- 外轮廓覆盖柱中心：`750 / 750`
- 内包络线覆盖柱中心：`750 / 750`

上部曲线链统计：

- 方法：`explicit_curved_top_facade_chain`
- 源实体数量：`5`
- 链点数：`396`
- 链 bbox：`[-1050.2114, 124028.7848, 456950.3959, 146978.7590]`

本地 AI 校核使用模型 `Qwen3.6-27B-Q4_K_M`，返回 `ok: true`，结论为内包络线位于外轮廓内部，覆盖全部柱中心，并保留顶部复杂曲线和凹槽特征。

人工校核结论：

`steps/002_curve_facade_profile/json_review_facade_outer_inner.html` 已通过人工验证。

## 后续接入建议

后续房间识别流程优先读取：

`log/building_facade_inner_envelope/steps/002_curve_facade_profile/accepted_after.json`

推荐使用方式：

- 将 `boundary_candidates` 中的 `building_inner_envelope_00001` 作为房间候选的建筑级裁剪边界。
- 将 `BUILDING-FACADE-INNER-ENVELOPE` 作为房间边界外扩搜索的硬约束。
- 保留 `BUILDING-FACADE-OUTER-PROFILE` 用于 HTML 人工复核和异常排查。

注意事项：

- 不再使用 `steps/001_*` 的结果。
- 如果 DXF 图层名或上部外轮廓实体发生变化，需要重新检查 `_top_facade_entity_role` 的实体选择规则。
- 当前脚本只派生 JSON 和审计产物，不修改源 DXF 和柱识别 JSON。
