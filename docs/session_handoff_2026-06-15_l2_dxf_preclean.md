# L2 DXF 预炸块清理交接记录

记录日期：2026-06-15

本文记录 `data/input/dxf/L2_20.00m平面图.dxf` 的房间识别前 DXF 清理进展。目标是从原始 DXF 中尽早清除 AutoCAD 模型空间肉眼不可见但数据层面保留的隐藏内容，并在炸块后保留房间边界、门洞、房间名称和房间编号。

## 当前状态

实验目录：

- `log/dxf_pre_explode_clean_experiment/steps`

当前人工处理后的继续工作基准：

- `log/dxf_pre_explode_clean_experiment/steps/014_keep_only_added_column_geometry_after_explode/candidate_after.dxf`

说明：

- 该文件已经被用户用 AutoCAD 人工处理并保存，时间戳为 2026-06-15 09:50 左右。
- 同目录 `candidate_after.bak` 是人工处理前的自动产物。
- 对人工处理后的 `candidate_after.dxf` 已运行项目根目录房间识别流程，输出在：
  `log/dxf_pre_explode_clean_experiment/steps/014_keep_only_added_column_geometry_after_explode/room_recognition_after_autocad_manual`

房间识别结果摘要：

- CAD 抽取：texts 1763，polylines 108297，blocks 3208，columns 884。
- 标签候选：550。
- 房间候选：568。
- 有边界匹配：370。
- 无边界匹配：198。
- 最终 rooms：568，其中带 polygon 的 370。
- 置信度范围：0.25 到 0.97。

## 已合入主流程

根目录入口：

```powershell
python dxf_preparation.py prepare-l2-room-dxf
```

正式实现位置：

- `dxf_preparation.py`
- `src/room_extractor/workflows/dxf_preparation.py`
- `src/room_extractor/cad/l2_room_dxf_precleaner.py`

默认输出：

- `log/dxf_pre_explode_clean_experiment/main_flow`

默认输入：

- `log/dxf_pre_explode_clean_experiment/steps/009_explode_largest_two_modelspace_blocks/candidate_after.dxf`

原因：step009 之前包含 AutoCAD 炸开最大两个 modelspace 图块的操作，目前尚未完全用 ezdxf 等价复现。`prepare-l2-room-dxf` 固化的是 step009 之后已经验证可自动重放的部分。

可覆盖参数：

```powershell
python dxf_preparation.py prepare-l2-room-dxf `
  --source <已完成最大图块炸开的DXF> `
  --out-dir <输出目录>
```

如果输入文件已经经过部分处理，且部分默认 INSERT handle 不存在，可临时使用：

```powershell
python dxf_preparation.py prepare-l2-room-dxf --allow-missing-handles
```

默认不建议开启该参数，因为缺失 handle 可能代表输入阶段不一致。

## 主流程阶段

`prepare-l2-room-dxf` 当前重放以下阶段，每个阶段生成 `candidate_after.dxf` 和 `manifest.json`：

1. `001_delete_furniture_layers`
   删除用户确认可删的家具图层：
   - `活动家具`
   - `1-活动家具细线`
   - `1-活动家具粗线`
   - `家具`
   - `P-家具`

   代码中使用的是 ezdxf 读取后的真实 Unicode 中文 exact layer name；PowerShell 某些输出会把这些图层名显示成乱码，不要按终端乱码手工复制。

2. `002_explode_remaining_wall_inserts`
   炸开剩余墙体 INSERT handle：
   - `498936`
   - `DF2884`
   - `E02923`

3. `003_explode_remaining_column_inserts`
   炸开剩余柱子相关 INSERT，共 78 个 handle。来源为 step011 的 `selected_insert_handles.json`。

4. `004_explode_review_wall_inserts`
   炸开后续人工复核中发现的 3 个小墙体/洞口相关 INSERT：
   - 两个 `墙半开洞口/消火栓/矩形` INSERT，通过名称 token 和图层 `05-L2-WALL$1$VT-WALL-总包` 动态选择。
   - `D38BC`，仍按固定 handle 选择。

   注意：实验 manifest 中这两个半开洞口 INSERT 的 handle 是 `113EDD8` 和 `113EDDA`，但重新用 ezdxf 从 step009 重放时会变成别的 handle。因此主流程不能硬编码这两个生成 handle。

5. `005_remove_added_layer0_after_explode`
   以 step002 输出作为 baseline，仅删除后续炸块新增的 `0` 图层残留。实验中删除 208 个新增实体，主要是原始隐藏数据在炸块后暴露出来的无用线段/文字/填充。

6. `006_keep_only_added_column_geometry_after_explode`
   同样以 step002 输出作为 baseline，删除后续炸块新增的非柱子细部层：
   - `05-L2-WALL$0$面积平面 - 会议2F- 20.00m平面图$0$A-DETL-GENF`

   实验中删除 14 个新增非柱子实体，保留新增的 `A-STR-COLM` 柱子几何。

最终文件复制为：

- `<out-dir>/candidate_after.dxf`

总 manifest：

- `<out-dir>/run_manifest.json`

2026-06-15 已用默认参数实际重放验证通过：

- 输出目录：`log/dxf_pre_explode_clean_experiment/main_flow`
- 最终文件：`log/dxf_pre_explode_clean_experiment/main_flow/candidate_after.dxf`
- `final_load_ok`: `true`
- stage001 删除家具图层实体：16075。
- stage002 炸开剩余墙体 INSERT：3。
- stage003 炸开剩余柱子 INSERT：78。
- stage004 炸开复核墙/洞口 INSERT：3。
- stage005 删除新增 `0` 图层隐藏残留：208。
- stage006 删除新增非柱子细部实体：14。

## 已验证的重要结论

- step003 到 step004 曾经误删门洞元素，因此 step005 改为保留门洞，用户人工确认通过。
- step005 的 `accepted_after.dxf` 可作为“墙体/门洞不被破坏”的早期基准。
- step005 之后发现多余纸空间 layout 和巨大图块；删除多余 layout 与炸开最大两个 modelspace 图块后继续清理。
- `活动家具`、`1-活动家具细线/粗线`、`家具`、`P-家具` 图层内容可删除，用户已用 AutoCAD 确认 `candidate_after_no_furniture_layers.dxf` 没问题。
- 炸开剩余墙/柱图块后会暴露原始隐藏线段，这些线段并非用户肉眼可见模型空间内容，需要用 baseline 差异删除。
- step014 自动版保留了新增柱子几何并删除新增非柱子残留；用户随后又在 AutoCAD 中人工处理了 step014 的 `candidate_after.dxf`，该人工版是当前最新识别基准。

## 房间识别复跑命令

人工处理后的 step014 已经跑过以下链路。后续如果替换了 `candidate_after.dxf`，可重新执行：

```powershell
$out = "log/dxf_pre_explode_clean_experiment/steps/014_keep_only_added_column_geometry_after_explode/room_recognition_after_autocad_manual"
$dxf = "log/dxf_pre_explode_clean_experiment/steps/014_keep_only_added_column_geometry_after_explode/candidate_after.dxf"

python .\room_extraction.py extract-cad --dxf $dxf --out "$out/cad_raw.json" *> "$out/extract_cad.log"
python .\room_extraction.py extract-cad --dxf $dxf --out "$out/cad_raw_columns.json" --columns-only *> "$out/extract_columns.log"
python .\room_extraction.py build-room-labels --cad "$out/cad_raw.json" --out "$out/room_label_candidates.json" --floor L2 *> "$out/build_room_labels.log"
python .\room_extraction.py build-room-candidates --cad "$out/cad_raw.json" --labels "$out/room_label_candidates.json" --columns "$out/cad_raw_columns.json" --out "$out/room_candidates.json" --floor L2 *> "$out/build_room_candidates.log"
python .\room_extraction.py build-rooms --candidates "$out/room_candidates.json" --out "$out/rooms_auto.json" *> "$out/build_rooms.log"
python .\room_extraction.py export-review-map --cad "$out/cad_raw.json" --rooms "$out/room_candidates.json" --out "$out/room_candidates_review.html" --title "step014 AutoCAD人工后 房间候选检查图" *> "$out/export_review_map.log"
python .\room_extraction.py export-json-review-html --json "$out/room_candidates.json" --out "$out/json_review_room_candidates.html" --include-boundaries *> "$out/export_json_review.log"
```

## 未完成事项

- 目前主流程尚未从 `data/input/dxf/L2_20.00m平面图.dxf` 原始文件一键复现到 step014；缺口是 AutoCAD 最大两个 modelspace 图块炸开和用户最后一次 AutoCAD 手工处理。
- step014 人工版 polyline 数量明显大于自动版，推测 AutoCAD 保存时展开或重写了更多几何。该变化未破坏当前房间识别数量，但后续应继续观察是否影响性能。
- 如要把流程扩展到其他楼层，不能直接复用这些 handle；应重新生成 `selected_insert_handles.json` 并走人工审计。
