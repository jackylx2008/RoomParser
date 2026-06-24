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

7. `007_remove_paperspace_layouts`
   复用已通过 AutoCAD 2024 人工确认的 `remove_paperspace_layouts` 规则：删除多余
   paper-space layout，保留并清空 `L2` layout。该阶段不执行 L2 实验中已被拒绝的
   “同时删除不可达块”操作，并通过实体数、可见性、类型、图层及实体身份指纹保护
   modelspace。

8. `008_enable_all_layers`
   打开并解冻全部图层；通过实体数、类型、图层和实体身份指纹确认 modelspace
   几何未被修改。

9. `009_dedupe_linework`
   复用正式 `dxf_line_deduper` 和真实 L2 样本已验证参数，默认使用
   `dedupe_mode=near`、`signature_scope=geometry`、`near_tolerance=1.0` 清理
   `LINE / LWPOLYLINE / POLYLINE / ARC` 完全及近似重线。阶段目录同时输出
   `duplicate_report.json`。

10. `010_reference_guided_prune`
    以人工确认的 step014 DXF 为目标，通过图层、实体类型以及 handle 无关的几何、
    文字、块名和插入点签名删除参照外实体。输出必须是参照实体签名 multiset 的
    子集；不会从参照复制当前文件缺少的实体。

11. `011_remove_reference_absent_unreachable_blocks`
    删除不再被布局、实体、嵌套块或标注样式引用，且块名不在参照中的非匿名块定义。
    该规则来自实验中 accepted 的不可达非房间块清理原则，并增加参照名称约束；
    不执行实验中 rejected 的无保护不可达块删除。所有 `*` 开头匿名块默认保留，
    因为 AutoCAD 可能仍通过 DIMENSION 内部标注块名依赖 `*D...` 几何块。

12. `012_reference_guided_block_content_prune`
    对当前与参照同名的非布局块定义执行实体签名预算清理，删除参照外块内标注、
    填充、文字、嵌套 INSERT 等内容。DIMENSION 使用块内图层数量预算，因为 AutoCAD
    往返保存会重生成其 bbox；modelspace 必须完全不变。

13. `013_remove_reference_absent_unreachable_blocks`
    块内清理后再次删除新变成不可达的参照外非匿名块。`*` 开头匿名块继续保留，
    尤其是 `*D...` 标注几何块，名称差异通常来自 AutoCAD 重生成。

14. `014_iterative_explode_reference_clean`
    当前文件和参照文件同步逐层炸开一次 modelspace INSERT；每一轮用同样炸一层后
    的参照执行实体签名清理，再执行 near/geometry 去重。循环直到当前 INSERT 清零、
    无法继续炸开或达到 `--max-reference-explode-passes`。每轮保留炸块文件、参照文件、
    清理报告、去重报告及独立 manifest，并支持从完整 pass 检查点恢复。

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

2026-06-21 更新：正式主流程已增加 stage007。可通过 `--keep-layout` 覆盖默认保留的
`L2` layout；每次运行会在 stage007 manifest 中记录删除布局、清空实体及 modelspace
保护检查结果。

同日增加 stage008-stage009。可通过 `--dedupe-mode`、`--dedupe-signature-scope`、
`--exact-tolerance` 和 `--near-tolerance` 覆盖默认去重参数。

对 `data/test/L2_20.00m平面图-ROOM_WALL.dxf` 的九阶段正式流程实跑结果：

- 输出目录：`data/test/L2_20.00m平面图-ROOM_WALL_formal_full_clean`
- `final_load_ok`: `true`
- 9 个阶段全部通过。
- stage008 打开或解冻图层：162 个；最终关闭/冻结图层均为 0。
- stage009 删除 near/geometry 重线：22,468 个。
- 最终 modelspace 实体：113,486 个。
- 最终仅保留 `Model` 和实体数为 0 的 `L2` layout。
- 使用相同参数复扫：exact 与 near 重线均为 0，跳过实体为 0。
- 最终文件大小：293,749,614 bytes。

继续以人工 step014 文件进行参照引导清理：

- stage010 删除参照外 modelspace 实体：16,640 个，其中 DIMENSION 1,424 个、
  多余 HATCH 1,059 个；输出实体签名全部属于参照子集。
- stage011 删除参照外且不可达块：515 个，块内实体 23,389 个；modelspace 不变。
- stage011 输出大小：273,566,218 bytes。
- stage012 删除参照外块内实体：26,621 个，影响 2,387 个共享块；共享块签名
  超额归零，modelspace 不变。
- stage013 再删除参照外不可达块：158 个，块内实体 1,364 个。
- stage013 输出大小：260,553,444 bytes。
- stage014 共执行 4 轮同步炸块：当前 INSERT 数量按
  `2398 -> 8680 -> 4407 -> 374 -> 0` 变化，炸块错误为 0。
- 四轮参照清理删除 32 个额外实体，逐轮去重共删除 22,982 个实体。
- stage014 输出大小：347,127,851 bytes；停止原因 `no_remaining_inserts`。

2026-06-24 AutoCAD 复核更新：

- 从 `data/test/L2_20.00m平面图-ROOM_WALL.dxf` 重新运行 001-014，并在每个
  step 目录保存 `input.dxf` 与 `candidate_after.dxf`。
- 001-010 使用 AutoCAD 2024 AcCoreConsole 打开/退出验证通过。
- 原始 011 在 AutoCAD 打开时失败，日志报 `ErrorStatus=53`、`无效的标注块名`；
  根因是清理删除了 AutoCAD 仍依赖的 `*D...` 匿名标注块。
- 已将正式 011/013 策略改为默认保留所有 `*` 匿名块，仅删除参照缺失且不可达的
  普通块，并在 manifest/report 中记录保留的匿名块数量。
- 保守链路 `011_safe`、`012_safe`、`013_safe`、`014_safe` 均通过 AutoCAD 2024
  AcCoreConsole 打开验证；阶段性最终文件为
  `data/test/L2_20.00m平面图-ROOM_WALL_autocad_recheck/candidate_after_autocad_validated.dxf`。
- 该结果只是阶段性成果：AutoCAD 可打开问题已解决，但图面仍未达到目标文件的清洁度，
  还需要继续做 GUI 目检、图层/标注/填充/图块差异分析和小步清理。

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
