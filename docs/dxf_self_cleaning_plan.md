# DXF 自驱动清理实验项目计划书

## 背景

当前房间识别输出的 HTML 效果不理想，初步判断与原始 DXF 中存在大量无用数据有关。

样本文件位于：

- `data/input/dxf_exploded/test.dxf`
- `data/input/dxf_exploded/test1.dxf`

两个文件在 CAD 中显示内容一致，但体积差异很大：

- `test.dxf`：约 163 MB
- `test1.dxf`：约 324 KB

这说明 `test.dxf` 中很可能包含大量不影响 CAD 当前视觉显示、但会增加解析成本并干扰房间识别的冗余数据，例如重复线、隐藏图层实体、未引用块定义、残留对象、代理对象、表记录或其他无绘制贡献数据。

本小项目的目标不是一次性写一个激进清理脚本，而是构造一个可审计、可回滚、可复用的 DXF 清理实验流程。

## 项目目标

1. 使用 `test.dxf` 和 `test1.dxf` 作为对照样本，从数据层面分析大文件膨胀原因。
2. 将清理过程拆成多轮小步操作，每轮只做一个低风险清理动作。
3. 每轮清理后生成 HTML 报告，保存清理前后统计、视觉对比、本地 AI 视觉验证结果和被清理数据。
4. 每轮保存可回滚快照，形成类似 git 的事务日志，任何一轮出现问题都能回滚到之前状态。
5. 从通过验证的清理步骤中沉淀可复用规则，用于后续处理其他 DXF。
6. 避免一次清理过多导致有用数据被误删。

## 非目标

1. 不直接覆盖原始 DXF 文件。
2. 不把文件体积完全等同作为唯一成功标准。
3. 不让本地 AI 直接决定删除哪些 DXF 数据。
4. 不在第一版就处理所有可能的 DXF 膨胀原因。
5. 不把实验中间文件提交进源码仓库。

## 成功标准

一个清理步骤只有同时满足以下条件，才允许被接受并进入下一轮：

1. 清理后 DXF 能被正常打开和解析。
2. 文件大小、实体数或冗余指标有实质改善。
3. 关键结构化指标没有异常下降，例如文本数量、闭合多段线数量、关键图层实体数量。
4. 清理前后渲染图与参考图相比没有明显视觉损失。
5. 本地 AI 视觉判断为一致或低风险。
6. 被清理数据已保存，可供人工复查。
7. 当前轮已生成完整 HTML 报告和 JSON 记录。

整体实验停止条件：

1. `test.dxf` 的体积和实体规模已接近 `test1.dxf` 的合理区间。
2. 继续清理的候选动作收益很低。
3. 后续清理动作开始触发视觉风险或结构化保护规则。
4. 没有新的安全清理候选。

## 设计原则

1. 小步清理：每轮只做一种清理动作。
2. 先低风险后高风险：从完全重复数据开始，再逐步处理隐藏数据、块定义、对象表和近似重复。
3. 先确定性判断，再 AI 验证：结构统计和像素差异先筛选，本地 AI 只做视觉辅助验收。
4. 可审计：每轮必须说明删了什么、为什么删、删后变化是什么。
5. 可回滚：每轮必须保留 accepted 快照和被删除实体。
6. 可复用：最终输出规则文件，而不是只得到一个清理后的样本文件。

## 总体架构

建议新增根目录实验脚本：

- `experiments/dxf_self_clean_experiment.py`

该脚本复用现有 `src` 内模块：

- `room_extractor.cad.dxf_loader.load_dxf`
- `room_extractor.cad.layer_analyzer.analyze_layers`
- `room_extractor.cad.entity_filter.is_entity_visible`
- `room_extractor.cad.dxf_line_deduper`
- `room_extractor.ai.local_ai_client.LocalAiClient`
- `room_extractor.ai.local_ai_client.LocalAiConfig`

后续如需要可继续把成熟逻辑下沉到 `src/room_extractor/cad/` 或 `src/room_extractor/workflows/`。

## 输出目录结构

实验输出建议放在：

```text
log/dxf_cleaning_experiment/
  index.html
  manifest.json
  rules_candidate.json
  current.dxf
  steps/
    000_baseline/
      source_stats.json
      reference_stats.json
      source.png
      reference.png
      report.html
    001_exact_duplicate_linework/
      input.dxf
      accepted_after.dxf
      rejected_after.dxf
      before_stats.json
      after_stats.json
      removed_entities.json
      removed_entities.dxf
      before.png
      after.png
      reference.png
      diff.png
      ai_check.json
      report.html
    002_hidden_layer_entities/
      ...
  rollback/
    rollback_to_step_000.ps1
    rollback_to_step_001.ps1
```

说明：

- `manifest.json` 记录所有步骤、状态、输入输出路径、是否接受、回滚点。
- `rules_candidate.json` 记录已验证通过和被拒绝的清理规则。
- `current.dxf` 指向或复制当前已接受的最新 DXF。
- `removed_entities.dxf` 保存本轮被删除的数据，便于 CAD 中人工查看。
- `removed_entities.json` 保存被删除实体的 handle、类型、图层、几何签名和删除原因。
- `index.html` 汇总所有轮次，可进入单轮 `report.html`。

## 单轮清理事务

每一轮按事务处理：

1. 从 `current.dxf` 复制生成本轮 `input.dxf`。
2. 执行一个清理候选动作。
3. 把被删除数据保存为 `removed_entities.dxf` 和 `removed_entities.json`。
4. 写出候选结果 DXF。
5. 统计清理前后结构数据。
6. 渲染参考图、清理前图、清理后图和差异图。
7. 执行结构化保护检查。
8. 调用本地 AI 做视觉验证。
9. 生成本轮 HTML 报告。
10. 如果验证通过，将候选结果保存为 `accepted_after.dxf` 并更新 `current.dxf`。
11. 如果验证失败，保留 `rejected_after.dxf` 和报告，但不更新 `current.dxf`。

## 清理策略顺序

### 1. 完全重复线类实体

目标实体：

- `LINE`
- `LWPOLYLINE`
- `POLYLINE`
- `ARC`

依据：

- 几何签名完全一致。
- 可分为图层敏感和纯几何两种 scope。

风险：

- 最低。

验证重点：

- 文件大小下降。
- 重复实体数量下降。
- 渲染图无变化。
- 文本和关键闭合多段线数量不异常下降。

### 2. 不可见实体

目标：

- 关闭图层实体。
- 冻结图层实体。
- DXF invisible 标记实体。

风险：

- 低到中。

验证重点：

- CAD 当前显示应不受影响。
- 但可能影响后续规则，因此必须保存被删除实体并验证。

### 3. 未引用块和空块定义

目标：

- 没有被 `INSERT` 引用的 block 定义。
- 空 block。
- 明显无绘制贡献的残留 block。

风险：

- 中。

验证重点：

- 引用关系必须先完整统计。
- 删除后不能破坏 remaining INSERT。

### 4. 非绘制贡献对象和表记录

目标：

- `OBJECTS` section 中膨胀明显但不参与当前视觉显示的数据。
- 无引用 table record。
- 代理对象或扩展数据。

风险：

- 中。

验证重点：

- 文件大小可能显著下降。
- modelspace 实体数可能不变。
- 必须确认 DXF 仍能打开。

### 5. 参考文件不存在的额外图层或实体类型

目标：

- `test.dxf` 有而 `test1.dxf` 没有的图层。
- `test.dxf` 有而参考文件没有的实体类型。

风险：

- 中到高。

验证重点：

- 只能分图层、分类型小批处理。
- 每次必须保存删除数据。

### 6. 近似重复线类实体

目标：

- 坐标在容差范围内几乎重合的线、弧、多段线。

风险：

- 高。

验证重点：

- 从极小容差开始。
- 每轮只清理一档容差。
- 一旦出现边界缺失或 AI 判断不确定，应停止或降低容差。

## 比较指标

每轮至少统计：

1. 文件大小。
2. DXF section 体积：`HEADER`、`TABLES`、`BLOCKS`、`ENTITIES`、`OBJECTS`。
3. modelspace 实体总数。
4. block 定义数量和 block 内实体数量。
5. 图层数量。
6. 每个图层的实体数量。
7. 每种 entity type 数量。
8. 可见实体和不可见实体数量。
9. 文本数量：`TEXT`、`MTEXT`。
10. 线类实体数量：`LINE`、`LWPOLYLINE`、`POLYLINE`、`ARC`。
11. 闭合 polyline 数量。
12. exact duplicate 数量。
13. near duplicate 数量。
14. 被删除实体数量和类型分布。

## 渲染与视觉验证

每轮生成：

- `reference.png`
- `before.png`
- `after.png`
- `diff.png`

如整图过大，可切分为 tile：

```text
tiles/
  reference_00_00.png
  before_00_00.png
  after_00_00.png
  diff_00_00.png
```

优先使用确定性图像差异判断：

- 像素差异比例。
- 差异区域数量。
- 差异区域 bbox。
- 是否在主要房间边界区域出现大块差异。

本地 AI 只看图像，不直接读 DXF。

AI 输入建议：

- 参考图。
- 清理前图。
- 清理后图。
- 差异图。
- 本轮清理动作摘要。

AI 输出必须是 JSON：

```json
{
  "visual_same": true,
  "missing_walls": false,
  "missing_text": false,
  "extra_noise_removed": true,
  "needs_review": false,
  "confidence": 0.86,
  "notes": "清理后与参考图主要线框一致，未发现明显房间边界丢失"
}
```

## HTML 报告要求

每轮 `report.html` 至少包含：

1. 本轮状态：accepted、rejected、needs_manual_review。
2. 清理动作名称。
3. 清理原因。
4. 文件大小变化。
5. 实体数量变化。
6. 图层变化 Top N。
7. entity type 变化 Top N。
8. 被删除数据入口：`removed_entities.dxf` 和 `removed_entities.json`。
9. 清理前、清理后、参考图、差异图。
10. 结构化保护检查结果。
11. 本地 AI 判断和原始 JSON。
12. 回滚目标和恢复路径。
13. 下一步建议。

总览 `index.html` 至少包含：

1. 每轮状态列表。
2. 从原始文件到当前文件的体积曲线。
3. 实体数量曲线。
4. 重复实体数量曲线。
5. 已接受规则列表。
6. 被拒绝规则列表。
7. 当前最佳 DXF 路径。

## 回滚机制

不使用真实 git 管理 DXF 中间文件，避免大文件污染仓库。

采用实验目录内的事务快照：

- 回滚到第 0 步：恢复原始 `test.dxf`。
- 回滚到第 N 步：恢复 `steps/N/accepted_after.dxf`。

每个可回滚点生成 PowerShell 脚本：

```powershell
Copy-Item -LiteralPath "steps/001_exact_duplicate_linework/accepted_after.dxf" -Destination "current.dxf" -Force
```

`manifest.json` 中同步记录：

```json
{
  "current_step": 1,
  "current_dxf": "log/dxf_cleaning_experiment/current.dxf",
  "rollback_points": [
    {
      "step": 0,
      "label": "original test.dxf",
      "path": "data/input/dxf_exploded/test.dxf"
    },
    {
      "step": 1,
      "label": "after exact duplicate linework",
      "path": "log/dxf_cleaning_experiment/steps/001_exact_duplicate_linework/accepted_after.dxf"
    }
  ]
}
```

## 可复用规则文件

最终生成：

- `log/dxf_cleaning_experiment/rules_candidate.json`

示例：

```json
{
  "accepted_steps": [
    {
      "name": "remove_exact_duplicate_linework",
      "entity_types": ["LINE", "LWPOLYLINE", "POLYLINE", "ARC"],
      "signature_scope": "geometry",
      "tolerance": 1e-9,
      "reason": "视觉一致，删除大量完全重复线"
    }
  ],
  "rejected_steps": [
    {
      "name": "remove_near_duplicate_linework",
      "tolerance": 5.0,
      "reason": "局部边界疑似丢失"
    }
  ]
}
```

后续复用时，应按 `accepted_steps` 的顺序逐步清理，并保留同样的验证与报告机制。

## 本地 AI 接入

项目已有本地 AI 客户端：

- `src/room_extractor/ai/local_ai_client.py`

配置来源：

- `common.env`
- `config.yaml`
- 环境变量

实验脚本应支持：

- `--dry-run-ai`：不实际调用 AI，只生成待校验结构。
- `--skip-ai`：完全跳过 AI，仅做结构和图像差异校验。
- `--base-url`
- `--model`
- `--timeout-seconds`
- `--max-tokens`

如果本地 AI 不可用，脚本不应静默接受高风险清理步骤。可接受策略：

- 低风险 exact duplicate 可在结构和像素验证通过后接受。
- 中高风险步骤必须标记为 `needs_manual_review` 或 `rejected`。

## 命令行草案

第一版入口：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --source data/input/dxf_exploded/test.dxf `
  --reference data/input/dxf_exploded/test1.dxf `
  --out-dir log/dxf_cleaning_experiment `
  --max-steps 1 `
  --dry-run-ai
```

继续实验：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --max-steps 3
```

回滚：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --rollback-to 1
```

只生成报告，不清理：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --source data/input/dxf_exploded/test.dxf `
  --reference data/input/dxf_exploded/test1.dxf `
  --out-dir log/dxf_cleaning_experiment `
  --analyze-only
```

## 分阶段实施计划

### 阶段 1：实验器骨架

交付内容：

1. 实验脚本 `experiments/dxf_self_clean_experiment.py`。
2. baseline 分析。
3. 实验目录和 manifest。
4. 单轮事务目录。
5. exact duplicate 清理。
6. 保存 `removed_entities.json`。
7. 保存 `removed_entities.dxf`。
8. 生成每轮 HTML 报告。
9. 支持回滚到指定 step。

验收：

1. 能读取 `test.dxf` 和 `test1.dxf`。
2. 能生成 baseline 报告。
3. 能执行第一轮 exact duplicate 清理。
4. 原始 DXF 不被覆盖。
5. 可以通过命令回滚。

### 阶段 2：渲染与视觉差异

交付内容：

1. DXF 渲染为 PNG。
2. 生成 before / after / reference / diff 图。
3. HTML 报告中展示图像对比。
4. 像素差异统计。

验收：

1. 每轮报告能看到视觉差异。
2. 结构验证和图像差异能共同决定低风险步骤是否接受。

### 阶段 3：本地 AI 验证

交付内容：

1. 调用本地多模态 AI。
2. AI 返回 JSON。
3. 保存 `ai_check.json`。
4. HTML 报告展示 AI 判断。
5. 支持 `--dry-run-ai` 和 `--skip-ai`。

验收：

1. AI 可用时能参与验证。
2. AI 不可用时不会静默接受高风险清理。

### 阶段 4：扩展清理策略

交付内容：

1. 不可见实体清理。
2. 未引用 block 清理。
3. 非绘制贡献对象分析。
4. 图层差异清理候选。
5. near duplicate 小容差清理。

验收：

1. 每种策略可单独启用和禁用。
2. 每种策略都有独立报告和回滚点。
3. 高风险策略不会批量无验证执行。

### 阶段 5：规则沉淀与复用

交付内容：

1. 生成 `rules_candidate.json`。
2. 支持从规则文件重放清理流程。
3. 支持对新 DXF 应用同样的分步清理和验证。

验收：

1. 能对其他 DXF 复用已验证规则。
2. 复用时仍保留每轮报告、被删数据和回滚点。

## 风险与防护

### 风险：视觉一致但业务数据被删

防护：

- 保留文本、房号、面积等关键元素数量检查。
- 对房间识别关键图层设置保护规则。
- 被删数据保存为 DXF，允许人工查看。

### 风险：AI 判断不稳定

防护：

- AI 不作为唯一验收条件。
- 结构化指标和像素差异优先。
- AI confidence 低时标记人工复查。

### 风险：near duplicate 误删边界

防护：

- 从极小容差开始。
- 每轮只清理一种容差。
- 差异图和 AI 检查必须通过。

### 风险：中间 DXF 文件过多

防护：

- 输出目录放在 `log/`。
- 默认只保留 accepted 快照和 rejected 摘要。
- 可增加 `--prune-rejected-dxf` 清理被拒绝的大文件，但保留报告和 JSON。

### 风险：渲染环境不稳定

防护：

- 第一阶段不依赖渲染。
- 渲染失败时报告标记为 `needs_manual_review`。
- 不因渲染失败接受中高风险清理。

## 当前推荐下一步

先实现阶段 1，不接复杂渲染和本地 AI：

1. 新增 `experiments/dxf_self_clean_experiment.py`。
2. 完成 baseline 统计和 HTML 报告。
3. 完成 exact duplicate 清理事务。
4. 保存被清理实体。
5. 支持 manifest 和 rollback。

阶段 1 跑通后，再接入阶段 2 的渲染和阶段 3 的本地 AI 验证。

## 当前实现状态

截至 2026-06-11，已新增实验脚本：

- `experiments/dxf_self_clean_experiment.py`

已完成并用真实样本执行：

1. baseline 分析。
2. 每轮事务目录。
3. `manifest.json`。
4. `index.html`。
5. 每轮 `report.html`。
6. 被清理数据保存。
7. 回滚点记录。
8. `rules_candidate.json`。
9. 最终参考图 / 当前图渲染。
10. 最终图像差异 JSON / HTML。

真实样本执行结果：

- 原始 `test.dxf`：约 155.8 MB。
- 参考 `test1.dxf`：约 0.3 MB。
- 第 1 轮 `remove_exact_duplicate_linework`：未发现完全重复线，拒绝，删除 0 个实体。
- 第 2 轮 `remove_invisible_modelspace_entities`：接受，删除 56,512 个不可见 modelspace 实体，体积降至约 103.8 MB，可见实体保持 1,436 不变。
- 第 3 轮 `remove_acad_layerstates`：接受，删除 `ACAD_LAYERSTATES` 历史图层状态对象分支，体积降至约 28.6 MB，modelspace 仍保持 1,436 个可见实体。
- 第 4 轮 `rebuild_visible_modelspace`：已撤销为 rejected。该轮从当前 DXF 重建只包含可见 modelspace 实体的新 DXF，ezdxf 可解析且体积降至 343,972 bytes，但 AutoCAD 2024 无法打开，因此不能作为 accepted 规则。后续若继续走重建路线，必须拆成更小步骤，并把 AutoCAD 2024 打开/保存作为硬验收。
- 第 5 轮 `remove_unused_appids`：候选，状态 `needs_manual_review`。该轮删除 43,129 个未被任何 XDATA 引用的 APPID 表记录，体积从 28,581,514 bytes 降至 23,125,822 bytes；before/after 渲染图像差异为 0，但尚未通过 AutoCAD 2024 人工打开验证，因此未接受。

当前最佳 DXF：

- `log/dxf_cleaning_experiment/steps/003_acad_layerstates/accepted_after.dxf`

当前总览报告：

- `log/dxf_cleaning_experiment/index.html`

最终视觉验证报告：

- `log/dxf_cleaning_experiment/final_visual_check/report.html`

当前可复用规则：

1. 删除关闭/冻结图层或 invisible flag 导致的不可见 modelspace 实体，前提是清理后可见实体数量不变。
2. 删除 `ACAD_LAYERSTATES` 历史图层状态对象分支，前提是 modelspace 实体数量和可见实体数量不变。
3. APPID 表清理目前只能作为候选规则：删除未被 XDATA 引用的 APPID 记录，前提是 modelspace 指标和渲染图保持不变，并且 AutoCAD 2024 可打开保存。

当前被拒绝或暂不自动化的策略：

1. 完全重复线清理：样本中未发现重复线，已记录为 rejected。
2. 未引用块清理：ezdxf 内置 `delete_all_blocks()` 会删除 DIMSTYLE 仍引用的箭头块并导致保存失败，因此暂不纳入自动接受步骤。后续如继续做，需要实现更严格的块引用追踪，至少覆盖 INSERT、DIMSTYLE、DIMENSION、MLEADER、TABLE、匿名块和扩展数据引用。
3. 可见 modelspace 重建：虽然能将文件压到约 344 KB，并且 ezdxf 可解析，但 AutoCAD 2024 无法打开。因此该策略必须拆成更细步骤，不能整体 accepted。

当前对剩余差异的判断：

- `test1.dxf` 为 323,576 bytes。
- 当前 accepted 最佳文件为 28,581,514 bytes。
- 第 5 轮 APPID 候选文件为 23,125,822 bytes，待 AutoCAD 2024 验证。
- 第 4 轮重建结果虽然为 343,972 bytes，但 AutoCAD 2024 无法打开，已撤销。
- 继续缩小空间主要来自 `BLOCKS`、`TABLES`、`OBJECTS`，应继续拆分为 APPID、未使用图层、未使用文字样式、未使用线型、纸空间布局、未引用块定义等独立候选，每个候选都需要保存图片并通过 AutoCAD 打开验证。

当前图片输出：

- 每个 step 目录下已生成 `reference.png`、`before.png`、`after.png`、`diff.png`、`comparison.png`、`visual_check.json`。
- 这些图片用于人工校验，也可作为后续本地 AI 视觉判断输入。

当前本地 AI 状态：

- 脚本已保留 `--dry-run-ai` 和 `--skip-ai` 参数。
- 本轮真实执行使用 `--dry-run-ai`，未实际调用本地多模态模型。
- 最终图像已生成，后续可以在此基础上接入 `LocalAiClient.chat_with_image()`，但需要先设计多图输入或拼接图输入格式。

## 2026-06-11 继续分析结论

用户确认第 4 轮约 344 KB 的 `accepted_after.dxf` 无法用 AutoCAD 2024 打开，因此该路线不能作为可复用清理逻辑。脚本已将第 4 轮标记为 rejected，当前 accepted 仍停在第 3 轮：

- `log/dxf_cleaning_experiment/steps/003_acad_layerstates/accepted_after.dxf`

当前 accepted 文件约 28,581,514 bytes，距离 `test1.dxf` 的 323,576 bytes 仍有明显差距。新增审计报告：

- `log/dxf_cleaning_experiment/bloat_audit/report.html`
- `log/dxf_cleaning_experiment/bloat_audit/bloat_audit.json`

审计结果说明剩余体积主要不是 modelspace 可见实体，而是以下历史数据：

1. `BLOCKS`：约 13.17 MB，比参考文件多约 13.17 MB。
2. `OBJECTS`：约 7.87 MB，比参考文件多约 7.77 MB。
3. `TABLES`：约 7.07 MB，比参考文件多约 7.06 MB。
4. `ENTITIES`：约 0.33 MB，只比参考文件多约 0.14 MB，已经不是主要问题。

更细分的来源：

1. 当前 accepted 有 8,998 个 block，其中 8,951 个从布局、嵌套 INSERT、DIMENSION geometry、DIMSTYLE 箭头块不可达，包含约 49,730 个块内实体。
2. `APPID` 表有 43,179 条，只有少量被 XDATA 使用。第 5 轮候选删除 43,129 条后，文件降至 23,125,822 bytes，但必须通过 AutoCAD 2024 打开验证后才能接受。
3. `OBJECTS/DBCOLOR` 有 404 个颜色书对象，约 5.96 MB。
4. `OBJECTS/SORTENTSTABLE` 有 13 个绘图排序对象，约 1.62 MB。
5. 当前还有大量未使用符号表记录：约 361 个未使用图层、64 个未使用文字样式、72 个未使用线型、14 个未使用标注样式。

探针结果显示，若每一步都通过 AutoCAD 验证，理论压缩路径如下：

1. 第 5 轮 `remove_unused_appids`：28.6 MB -> 23.1 MB。
2. 后续候选 `remove_unreachable_blocks`：23.1 MB -> 约 9.0 MB。
3. 后续候选 `remove_acad_color_branch`：约 9.0 MB -> 约 3.05 MB。
4. 后续候选 `remove_sortents_tables`：约 3.05 MB -> 约 1.43 MB。
5. 后续候选 `remove_unused_symbol_table_records`：约 1.43 MB -> 约 1.18 MB。

这些探针仅证明 ezdxf 可重新读取且 modelspace 统计不变，不等价于 AutoCAD 2024 可打开。后续每一步都必须独立生成 step、图片和报告，并经 AutoCAD 验证后用人工命令接受。

新增脚本能力：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --write-bloat-audit
```

用于在 `bloat_audit/` 下生成剩余膨胀原因报告。

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --mark-step-accepted 5 `
  --accept-reason "AutoCAD 2024 can open and save candidate_after.dxf"
```

用于在人工确认第 5 轮候选可被 AutoCAD 2024 打开后，将其提升为 accepted。只有接受第 5 轮后，脚本才会继续生成下一轮累计候选。

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --max-steps 1 `
  --dry-run-ai
```

用于继续生成下一轮候选。脚本已改为：只要存在 `needs_manual_review` step，就不会自动继续下一轮，避免未验证候选被当作已确认结果继续叠加。

## 2026-06-11 分段候选输出

用户已确认第 5 轮 `remove_unused_appids` 的 `candidate_after.dxf` 可以被 AutoCAD 2024 打开，因此第 5 轮已手动接受：

- `log/dxf_cleaning_experiment/steps/005_remove_unused_appids/accepted_after.dxf`
- 大小：23,125,822 bytes

随后按用户要求生成三个连续候选文件，顺序为 `BLOCKS -> OBJECTS -> TABLES`。这些步骤是基于前一步 candidate 继续生成的候选链，当前 accepted 仍停在第 5 轮，后续每个 candidate 都需要用 AutoCAD 2024 打开确认。

### 第 6 轮：BLOCKS

- 清理动作：`remove_unreachable_blocks`
- 输出：`log/dxf_cleaning_experiment/steps/006_remove_unreachable_blocks/candidate_after.dxf`
- 大小：9,017,851 bytes
- 删除：8,951 个不可达 block definition
- 状态：`needs_manual_review`
- 结构保护：passed
- 渲染：passed，before/after 像素差异 0

### 第 7 轮：OBJECTS

- 清理动作：`remove_object_metadata`
- 输出：`log/dxf_cleaning_experiment/steps/007_remove_object_metadata/candidate_after.dxf`
- 大小：1,434,063 bytes
- 删除：418 个对象，主要包含 `ACAD_COLOR` 颜色书分支和 `SORTENTSTABLE`
- 状态：`needs_manual_review`
- 结构保护：passed
- 渲染：passed，before/after 像素差异 0

### 第 8 轮：TABLES

- 清理动作：`remove_unused_symbol_table_records`
- 输出：`log/dxf_cleaning_experiment/steps/008_remove_unused_symbol_table_records/candidate_after.dxf`
- 大小：1,181,968 bytes
- 删除：551 条未使用符号表记录，包括未使用图层、文字样式、线型、标注样式
- 状态：`needs_manual_review`
- 结构保护：passed
- 渲染：passed，before/after 像素差异 0

三轮候选均已生成：

- `reference.png`
- `before.png`
- `after.png`
- `diff.png`
- `comparison.png`
- `visual_check.json`
- `report.html`

注意：第 7 轮删除 `SORTENTSTABLE` 后，ezdxf 默认渲染器会因残留 draw-order 映射格式触发异常。脚本已加入 fallback：当 draw-order 映射损坏时按 modelspace 实体顺序渲染，因此第 7、8 轮图片已补齐。这个 fallback 只影响实验报告渲染，不修改 DXF 内容。

## 2026-06-11 第 8 轮 AutoCAD 验证通过

用户确认以下文件可以用 AutoCAD 打开：

- `log/dxf_cleaning_experiment/steps/008_remove_unused_symbol_table_records/candidate_after.dxf`

由于第 8 轮文件是基于第 6 轮 BLOCKS 清理和第 7 轮 OBJECTS 清理继续生成的累计结果，因此已按链路顺序将第 6、7、8 轮全部标记为 accepted。当前最佳 DXF 已推进到：

- `log/dxf_cleaning_experiment/steps/008_remove_unused_symbol_table_records/accepted_after.dxf`
- 大小：1,181,968 bytes

当前 accepted 清理链：

1. 删除不可见 modelspace 实体。
2. 删除 `ACAD_LAYERSTATES` 历史图层状态对象分支。
3. 删除未被 XDATA 引用的 APPID 表记录。
4. 删除不可达 block definitions。
5. 删除 `ACAD_COLOR` 颜色书元数据和 `SORTENTSTABLE` 绘图排序对象。
6. 删除未使用的 `LAYER`、`STYLE`、`LTYPE`、`DIMSTYLE` 符号表记录。

当前 rejected 策略：

1. 完全重复线清理：样本中无收益。
2. 可见 modelspace 整体重建：可压到约 344 KB，但 AutoCAD 2024 无法打开，禁止作为自动规则复用。

## 2026-06-11 AI 图片裁剪修正

用户指出每个 step 下生成的 PNG 画布过大、有效图形过小，不适合作为本地 AI 视觉判断输入。原因是早期渲染直接使用 ezdxf/matplotlib 的默认视图范围，`POINT`、`XLINE`、`RAY`、不可见图层实体或不同坐标原点的参考文件会把画布范围撑大。

脚本已调整渲染策略：

1. PNG 渲染模式改为 `cropped_ai_review`。
2. 计算 bbox 时排除 `POINT`、`XLINE`、`RAY`。
3. 计算 bbox 和绘制时都过滤关闭图层、冻结图层和 invisible flag 实体。
4. before/after 如果处于同一坐标区域，使用共享 bbox，保证像素差异可比。
5. baseline 中 `test.dxf` 与 `test1.dxf` 坐标原点不同，因此自动使用独立裁剪，避免两个坐标系 union 后产生大空白。
6. 每个 `visual_check.json` 记录裁剪 bbox、渲染模式和被排除实体类型。

已重新生成 step PNG。当前每个 step 的 `after.png` 内容 bbox 占整图约 86%，图形已经填满主要画布，适合后续本地 AI 视觉校验。

## 2026-06-11 第 9 轮候选

用户确认：

1. 第 8 轮 `candidate_after.dxf` 已通过 AutoCAD 人工打开验证。
2. step002 到 step008 下的 PNG 已通过人工验证。
3. step000 下 `reference.png`、`diff.png`、`comparison.png` 正常；`before.png`、`after.png` 仍存在历史画布问题但不影响当前流程。

在第 8 轮 accepted 文件基础上继续瘦身，生成第 9 轮候选：

- 清理动作：`remove_paperspace_layouts`
- 输出：`log/dxf_cleaning_experiment/steps/009_remove_paperspace_layouts/candidate_after.dxf`
- 大小：924,487 bytes
- 输入大小：1,181,968 bytes
- 删除内容：6 个 paper-space layout，并清空保留的 paper-space layout 中的 5 个实体
- 保留 layout：`L2`，但其 paper-space entity count 已清零
- 当前 layout：`L2` 和 `Model`
- 当前 blocks：41
- 当前 objects：524
- modelspace 实体数：1,436，保持不变
- 状态：`needs_manual_review`
- 结构保护：passed
- 渲染：passed，before/after 像素差异 0

第 9 轮尚未 accepted，必须先用 AutoCAD 打开 `candidate_after.dxf` 验证。验证通过后可执行：

```powershell
python experiments/dxf_self_clean_experiment.py `
  --resume log/dxf_cleaning_experiment `
  --mark-step-accepted 9 `
  --accept-reason "AutoCAD can open candidate_after.dxf in step 9"
```

## 2026-06-11 第 9 到第 16 轮自动瘦身结果

用户确认第 9 轮 `candidate_after.dxf` 可用 AutoCAD 2024 打开。此后用户授权后续步骤不再逐轮人工打开 AutoCAD，而是由脚本自驱动执行：每轮生成 DXF、HTML、PNG、删除记录、结构保护检查和 rollback point，最后由用户统一做 AutoCAD 验证。

### 当前最终 accepted 文件

- 路径：`log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`
- 大小：437,346 bytes
- 对比原始 `test.dxf`：约 155 MB -> 437 KB
- 对比参考 `test1.dxf`：323,576 bytes
- 当前状态：脚本内部验证通过，AutoCAD 2024 人工打开验证通过

### 第 9 到第 16 轮 accepted 链

| Step | 动作 | 输入大小 | 输出大小 | 主要删除内容 | 验证 |
|---:|---|---:|---:|---|---|
| 009 | `remove_paperspace_layouts` | 1,181,968 | 924,487 | paper-space layouts 和纸空间实体 | AutoCAD 人工确认 |
| 010 | `remove_remaining_object_metadata` | 924,487 | 799,702 | scale list、visual style、image/detail/section view、plot/render/sheet/ezdxf 等对象元数据 | modelspace 不变，PNG before/after 0 差异 |
| 011 | `strip_classes_and_acdsdata_sections` | 799,702 | 668,708 | `CLASSES`、`ACDSDATA` 原始 DXF 段 | reload 成功，modelspace 不变，PNG 0 差异 |
| 012 | `remove_auxiliary_points_and_xlines` | 668,708 | 527,340 | 937 个 `POINT`、3 个 `XLINE` | 非辅助几何不变，实体数对齐参考文件 496，PNG 0 差异 |
| 013 | `remove_unreachable_blocks_after_auxiliary` | 527,340 | 489,806 | 删除辅助实体后变成不可达的 22 个 block | modelspace 不变，PNG 0 差异 |
| 014 | `remove_unused_tables_after_auxiliary` | 489,806 | 483,708 | 无用 layer、linetype、style、APPID | modelspace 不变，表记录下降，PNG 0 差异 |
| 015 | `remove_large_null_dictionary_shells` | 483,708 | 439,266 | handle `73` 和 `B6` 两个大型空字典壳，共 497 条指向 `0` 的无效记录 | OBJECTS 数下降，modelspace 不变，PNG 0 差异 |
| 016 | `strip_regenerated_classes_section` | 439,266 | 437,346 | ezdxf 最后保存再生成的 `CLASSES` 段 | reload 成功，modelspace 不变，PNG 0 差异 |

### 为什么 step012 是关键

第 12 轮删除的 940 个实体全部是 `POINT/XLINE/RAY` 类辅助或无限构造实体，其中实际删除：

- `POINT`: 937
- `XLINE`: 3
- `RAY`: 0

参考 DXF 的 modelspace 实体数为 496；第 12 轮后，当前 DXF 的 modelspace 实体数也变为 496，且保留下来的实体类型完全一致：

- `LINE`: 409
- `LWPOLYLINE`: 33
- `ARC`: 20
- `MTEXT`: 18
- `HATCH`: 16

这一步没有采用之前失败的“重建可见 modelspace”方案，而是在原 DXF 结构中增量删除辅助实体，因此比 335 KB 重建文件更保守。每轮报告中的 before/after PNG 使用共享 bbox，删除前后像素差异为 0。

### 当前最终 DXF 结构

`accepted_after.dxf` 当前主要 section 体积：

- `ENTITIES`: 184,714 bytes
- `TABLES`: 107,360 bytes
- `OBJECTS`: 91,918 bytes
- `BLOCKS`: 45,812 bytes
- `HEADER`: 7,397 bytes

当前表和对象概况：

- layers: 14
- appids: 38
- linetypes: 5
- styles: 5
- dimstyles: 2
- blocks: 19
- layouts: 2
- objects: 389

### 剩余差距判断

最终文件仍比 `test1.dxf` 大约 114 KB，主要来自：

1. `TABLES` 仍比参考文件大很多，尤其 APPID 和部分 AutoCAD/AEC/TCH 表记录仍存在。
2. `BLOCKS` 仍保留 19 个 block、673 个 block 内实体；脚本目前只删除不可达 block，没有强删仍被布局/样式引用的 block。
3. `OBJECTS` 仍包含 AutoCAD/AEC/TCH/MATERIAL/DICTIONARYVAR/XRECORD 等对象。继续删除这些可能影响 AutoCAD 打开或样式语义，当前不作为自动规则。

当前建议停止在 step016：它已经接近参考体积，同时没有重走已知会破坏 AutoCAD 打开的 335 KB 重建路径。用户已确认该文件可用 AutoCAD 2024 打开：

- `log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`

由于 AutoCAD 验证已经通过，step010-step016 的规则可以进入可复用清理链。后续如果在其他样本上复用时失败，优先回滚到上一轮：

- `log/dxf_cleaning_experiment/steps/015_remove_large_null_dictionary_shells/accepted_after.dxf`

或更保守地回滚到：

- `log/dxf_cleaning_experiment/steps/014_remove_unused_tables_after_auxiliary/accepted_after.dxf`

### 视觉验证说明

每个 step 目录都保存：

- `reference.png`
- `before.png`
- `after.png`
- `diff.png`
- `comparison.png`
- `visual_check.json`
- `report.html`

每轮自动接受依据是 before/after 在同一坐标 bbox 下的像素差异为 0。最终 `final_visual_check` 是 reference/current 对比，由于 `test.dxf` 和 `test1.dxf` 原始坐标原点不同，最终 reference/current 差异不是 0；这个差异不用于逐轮清理判定，只作为最终人工检查辅助图。
