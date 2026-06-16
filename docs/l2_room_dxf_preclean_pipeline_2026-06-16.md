# L2 房间 DXF 预清理流程变更记录

记录日期：2026-06-16

本文记录当前未提交的 L2 房间识别前 DXF 预清理相关代码、实验脚本和验证结果。详细交接信息见 `docs/session_handoff_2026-06-15_l2_dxf_preclean.md`。

## 目标

针对 `data/input/dxf/L2_20.00m平面图.dxf`，在房间识别前清理会干扰边界识别的数据：

- 删除已人工确认可删除的家具图层。
- 炸开剩余墙体、柱子和人工复核发现的小墙体/洞口 INSERT。
- 删除炸块后暴露出的隐藏残留。
- 保留房间边界、门洞、房间名称、房间编号和新增柱子几何。

## 正式入口

新增命令：

```powershell
python dxf_preparation.py prepare-l2-room-dxf
```

注册位置：

- `dxf_preparation.py`
- `src/room_extractor/workflows/dxf_preparation.py`
- `src/room_extractor/cad/__init__.py`

正式实现：

- `src/room_extractor/cad/l2_room_dxf_precleaner.py`

默认输入：

`log/dxf_pre_explode_clean_experiment/steps/009_explode_largest_two_modelspace_blocks/candidate_after.dxf`

默认输出：

`log/dxf_pre_explode_clean_experiment/main_flow`

说明：默认输入从 step009 开始，是因为 step009 之前包含 AutoCAD 炸开最大两个 modelspace 图块的人工/AutoCAD-only 操作，目前未完全用 ezdxf 一键复现。

## 主流程阶段

`prepare-l2-room-dxf` 固化 step009 之后已经验证可重放的自动链路：

1. `001_delete_furniture_layers`
   删除 `活动家具`、`1-活动家具细线`、`1-活动家具粗线`、`家具`、`P-家具`。

2. `002_explode_remaining_wall_inserts`
   炸开 3 个剩余墙体 INSERT：`498936`、`DF2884`、`E02923`。

3. `003_explode_remaining_column_inserts`
   炸开 78 个剩余柱子 INSERT，handle 来自已验证实验过程。

4. `004_explode_review_wall_inserts`
   炸开 3 个复核墙体/洞口 INSERT。其中两个半开洞口 INSERT 使用图层和名称 token 动态选择，避免依赖重放时会变化的生成 handle；另一个使用固定 handle `D38BC`。

5. `005_remove_added_layer0_after_explode`
   以 stage002 输出为 baseline，只删除后续炸块新增的 `0` 图层隐藏残留。

6. `006_keep_only_added_column_geometry_after_explode`
   以 stage002 输出为 baseline，删除后续炸块新增的非柱子细部层，保留新增柱子几何。

最终文件复制为：

`<out-dir>/candidate_after.dxf`

总 manifest：

`<out-dir>/run_manifest.json`

## 已验证结果

默认参数已经实际重放通过，输出目录为：

`log/dxf_pre_explode_clean_experiment/main_flow`

`run_manifest.json` 关键结果：

- `final_load_ok`: `true`
- stage001 删除家具图层实体：`16075`
- stage002 炸开墙体 INSERT：`3`
- stage003 炸开柱子 INSERT：`78`
- stage004 炸开复核墙/洞口 INSERT：`3`
- stage005 删除新增 `0` 图层隐藏残留：`208`
- stage006 删除新增非柱子细部实体：`14`
- 最终文件大小：`249875001` bytes

验证命令：

```powershell
python -m py_compile dxf_preparation.py src/room_extractor/cad/l2_room_dxf_precleaner.py src/room_extractor/workflows/dxf_preparation.py
python dxf_preparation.py prepare-l2-room-dxf --help
```

## 实验脚本

以下脚本保留在 `experiments/`，用于审计、人工验证辅助或复现实验路径，不作为普通生产入口：

- `dxf_pre_explode_clean_experiment.py`：预炸块清理的审计实验主脚本，支持 baseline、候选 step、人工 accept/reject、rollback 和渲染。
- `autocad_visible_only_explode.py`：通过 AcCoreConsole 只炸开可见 modelspace INSERT。
- `autocad_delete_extra_layouts.py`：通过 AcCoreConsole 删除多余 paper-space layout。
- `autocad_explode_named_blocks.py`：通过 AcCoreConsole 按 block name 炸开 INSERT。
- `autocad_explode_insert_handles.py`：通过 AcCoreConsole 按 INSERT handle 炸开。
- `explode_insert_handles_ezdxf.py`：通过 ezdxf 按 INSERT handle 炸开。
- `delete_exact_layer_contents.py`：删除指定 exact layer 上的实体。
- `delete_added_entities_by_layer.py`：基于 baseline，只删除新增实体中指定 layer 的内容。

## 使用边界

- `prepare-l2-room-dxf` 只保证当前 L2 图纸、当前已验证 handle 集合和 step009 输入条件下可复用。
- 如果源 DXF 被重新导出、AutoCAD 保存方式变化或 handle 改变，需要重新审计 handle 和动态选择规则。
- `--allow-missing-handles` 只用于排查或已知输入阶段不同的临时重放，默认不建议开启。
- 当前流程不会覆盖用户最后一次 AutoCAD 手工处理；该人工基准在交接文档中单独记录。
