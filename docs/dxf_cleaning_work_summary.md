# DXF 自驱动清理工作总结

记录日期：2026-06-11

本文总结本轮对话完成的 DXF 清理实验、代码改造、验证结论和后续复用边界。详细计划和逐轮日志见 `docs/dxf_self_cleaning_plan.md`，实验产物见 `log/dxf_cleaning_experiment/`。

## 背景

用户在 `data/input/dxf_exploded/` 下提供了两个视觉内容相同但体积差异很大的 DXF：

- `test.dxf`：约 155 MB，数据量异常大。
- `test1.dxf`：323,576 bytes，可作为视觉和结构参考。

目标是分析大文件中无用数据来源，建立可审计、可回滚、可复用的清理流程，而不是一次性激进重建 DXF。此前曾生成约 335 KB 的重建文件，但 AutoCAD 2024 无法打开，因此该路线被明确标记为 rejected，不再作为自动规则使用。

## 主要代码产物

新增根目录脚本：

- `dxf_self_clean_experiment.py`

新增/更新文档：

- `docs/dxf_self_cleaning_plan.md`
- `docs/dxf_cleaning_work_summary.md`

实验输出目录：

- `log/dxf_cleaning_experiment/`

每个 step 目录保存：

- `input.dxf`
- `candidate_after.dxf`
- `accepted_after.dxf` 或 `rejected_after.dxf`
- `before_stats.json`
- `after_stats.json`
- `removed_*.json`
- `ai_check.json`
- `visual_check.json`
- `reference.png`
- `before.png`
- `after.png`
- `diff.png`
- `comparison.png`
- `report.html`

这些文件形成类似 git 的审计链。每个 accepted step 都有 rollback point，失败时可以回到上一轮 accepted DXF。

## 脚本能力

`dxf_self_clean_experiment.py` 当前支持：

- baseline 比较：分析 source/reference 的 section、modelspace、tables、objects、重复线等。
- 分步清理：每次只执行一个清理动作，生成独立 step 目录。
- 结构保护检查：确保 modelspace 实体数、可见实体数、实体类型、图层分布等未被误改。
- 图像验证：渲染 reference/before/after/diff/comparison PNG。
- 裁剪渲染：排除 `POINT`、`XLINE`、`RAY` 后计算有效 bbox，避免画布巨大、图形很小。
- 回滚：accepted step 保存 rollback 脚本和 manifest 记录。
- 人工验证记录：可把 AutoCAD 人工打开结果写入 manifest 和 rules candidate。
- 剩余体积审计：生成 bloat audit，用于定位下一轮清理空间。

重要命令：

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --max-steps 1 --dry-run-ai
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --mark-step-accepted <step>
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --mark-step-rejected <step>
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --write-bloat-audit
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --render-step-images
```

## 本地 AI 状态

本轮清理没有实际调用本地 AI，也没有调用 Qwen。

脚本里的 `--dry-run-ai` 只写入占位字段：

```json
{
  "status": "dry_run"
}
```

实际自动判断依据是：

- ezdxf 能否重新加载 DXF。
- modelspace/tables/objects 结构保护检查。
- 每轮 before/after PNG 像素差异是否为 0。
- 用户的 AutoCAD 2024 人工打开验证。

后续如果要接入 Qwen 或其他 OpenAI-compatible 本地视觉模型，可以复用每个 step 下的 `comparison.png`、`before.png`、`after.png` 和 `visual_check.json`。

## 最终结果

当前最终 accepted 文件：

- `log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`

最终大小：

- 437,346 bytes
- 约 427.1 KiB

用户已确认该文件可以用 AutoCAD 2024 打开。

压缩效果：

- 原始 `test.dxf`：约 155 MB
- 最终 `accepted_after.dxf`：437,346 bytes
- 参考 `test1.dxf`：323,576 bytes

最终 modelspace 实体数为 496，与参考文件一致。保留实体类型：

- `LINE`: 409
- `LWPOLYLINE`: 33
- `ARC`: 20
- `MTEXT`: 18
- `HATCH`: 16

最终主要 section：

- `ENTITIES`: 184,714 bytes
- `TABLES`: 107,360 bytes
- `OBJECTS`: 91,918 bytes
- `BLOCKS`: 45,812 bytes
- `HEADER`: 7,397 bytes

## 清理链摘要

| Step | 动作 | 状态 | 输入大小 | 输出大小 | 删除数量 | 说明 |
|---:|---|---|---:|---:|---:|---|
| 001 | `remove_exact_duplicate_linework` | rejected | 163,388,419 | 163,388,419 | 0 | 没有收益 |
| 002 | `remove_invisible_modelspace_entities` | accepted | 163,388,419 | 108,794,213 | 56,512 | 删除不可见 modelspace 实体 |
| 003 | `remove_acad_layerstates` | accepted | 108,794,213 | 28,581,514 | 1,368 | 删除历史图层状态 |
| 004 | `rebuild_visible_modelspace` | rejected | 28,581,514 | 343,972 | 0 | AutoCAD 2024 无法打开，禁用 |
| 005 | `remove_unused_appids` | accepted | 28,581,514 | 23,125,822 | 43,129 | 删除未被 XDATA 引用的 APPID |
| 006 | `remove_unreachable_blocks` | accepted | 23,125,822 | 9,017,851 | 8,951 | 删除不可达 block |
| 007 | `remove_object_metadata` | accepted | 9,017,851 | 1,434,063 | 418 | 删除颜色书和排序表等对象元数据 |
| 008 | `remove_unused_symbol_table_records` | accepted | 1,434,063 | 1,181,968 | 551 | 删除未使用符号表记录 |
| 009 | `remove_paperspace_layouts` | accepted | 1,181,968 | 924,487 | 11 | 删除/清空纸空间 layout |
| 010 | `remove_remaining_object_metadata` | accepted | 924,487 | 799,702 | 148 | 删除剩余非几何 OBJECTS 元数据 |
| 011 | `strip_classes_and_acdsdata_sections` | accepted | 799,702 | 668,708 | 2 | 剥离 `CLASSES` 和 `ACDSDATA` 段 |
| 012 | `remove_auxiliary_points_and_xlines` | accepted | 668,708 | 527,340 | 940 | 删除 `POINT`/`XLINE` 辅助实体 |
| 013 | `remove_unreachable_blocks_after_auxiliary` | accepted | 527,340 | 489,806 | 22 | 删除辅助实体移除后变不可达的 block |
| 014 | `remove_unused_tables_after_auxiliary` | accepted | 489,806 | 483,708 | 30 | 二次删除无用 layer/linetype/style/APPID |
| 015 | `remove_large_null_dictionary_shells` | accepted | 483,708 | 439,266 | 2 | 删除大型空字典壳 |
| 016 | `strip_regenerated_classes_section` | accepted | 439,266 | 437,346 | 1 | 剥离最终再生成的 `CLASSES` 段 |

## 关键清理规则

### 不可见实体

删除关闭图层、冻结图层或 invisible flag 导致不可见的 modelspace 实体。保护条件是可见实体数量和可见结构不被破坏。

### 对象元数据

删除不影响 modelspace 几何的对象分支，包括：

- `ACAD_LAYERSTATES`
- `ACAD_COLOR`
- `SORTENTSTABLE`
- `ACAD_SCALELIST`
- `ACAD_VISUALSTYLE`
- image/detail/section view 字典
- plot/render/sheet/ezdxf 相关元数据

这类清理收益很高，但必须保留分步验证和回滚。

### 原始 section 剥离

对 `CLASSES`、`ACDSDATA` 等非几何段使用 raw DXF 文本剥离。保护条件：

- 剥离后 ezdxf 仍可加载。
- 目标 section 从 scan 结果中消失。
- modelspace 结构不变。
- before/after PNG 差异为 0。

### 辅助实体清理

删除 `POINT`、`XLINE`、`RAY`。本样本中实际删除：

- 937 个 `POINT`
- 3 个 `XLINE`

删除后 modelspace 实体数从 1,436 变为 496，正好对齐参考文件。保留的可见几何类型和数量不变。

### 二次清理

删除辅助实体后，部分 block、layer、linetype、APPID 变成无用状态，因此进行了二次清理：

- 删除 22 个不可达 block。
- 删除 30 条无用表记录。

这说明清理流程需要迭代，而不是一次性删除所有候选。

### 大型空字典壳

删除两个大型 OBJECTS 字典壳：

- handle `73`：404 条记录，全部指向字符串 `0`。
- handle `B6`：93 条记录，全部指向字符串 `0`。

这些记录不指向真实 DXF 对象，删除后 modelspace 不变，AutoCAD 最终验证通过。

## 验证策略

每轮 accepted 至少满足：

- ezdxf reload 成功。
- modelspace 保护检查通过。
- 文件体积下降。
- before/after PNG 使用共享 bbox 且像素差异为 0。

人工验证节点：

- step008 用户确认 AutoCAD 2024 可打开。
- step009 用户确认 AutoCAD 2024 可打开。
- step016 用户确认 AutoCAD 2024 可打开。

最终 `final_visual_check` 中 reference/current 有少量像素差异，这是因为 `test.dxf` 和 `test1.dxf` 坐标原点不同，最终图像是 reference/current 独立裁剪对比。逐轮自动接受依据是同一 step 内 before/after 的共享 bbox 对比。

## 风险边界

当前明确禁用：

- `rebuild_visible_modelspace`

原因：虽然能压缩到约 344 KB，但 AutoCAD 2024 无法打开。

继续压缩到更接近 323 KB 可能需要进一步删除：

- 仍被布局/样式引用的 block。
- AEC/TCH/Material/DictionaryVar/XRecord 等对象。
- 更多 APPID 和表记录。

这些项目可能影响 AutoCAD 打开、样式、代理对象、AEC/TCH 语义或后续识别稳定性，因此不建议在没有更多样本和更强验证前作为自动规则。

## 当前可复用结论

step010-step016 已经通过脚本验证和最终 AutoCAD 2024 人工验证，可作为下一阶段可复用清理链候选。

复用时应保持以下原则：

1. 每轮只做一个清理动作。
2. 每轮保存被删除数据、候选 DXF、HTML 报告和 PNG。
3. before/after 必须共享 bbox 做像素对比。
4. 任何一步 AutoCAD 验证失败，优先回滚到上一轮 accepted。
5. 不启用整体重建 DXF 路线，除非后续找到 AutoCAD 兼容的重建方式。

## 当前下一步

建议基于 `rules_candidate.json` 整理正式 reusable cleaner，但不要立即扩大清理范围。下一阶段可做：

1. 把已验证规则从实验脚本中抽成 `src` 内可复用模块。
2. 添加命令：输入任意 DXF，输出分步清理报告和最终 DXF。
3. 接入可选本地视觉模型，仅作为辅助判读 `comparison.png`，不能替代结构保护和 AutoCAD 验证。
4. 用更多真实 DXF 样本验证规则稳定性。
