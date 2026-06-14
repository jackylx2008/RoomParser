# 2026-06-14 工作交接记录

## 当前结论

- `room_recognition_experiment` 的真实房间识别规则已合并到正式 `room_extraction.py` 工作流相关模块。
- `dxf_self_clean_experiment` 的 16 阶段 DXF 自清理流程已合并到正式 `dxf_preparation.py self-clean-dxf` 工作流。
- 项目根目录下的实验性 Python 脚本已移动到 `experiments/`，正式入口保留为：
  - `dxf_preparation.py`
  - `room_extraction.py`
- 试验代码合入后测试通过：`python -m pytest`，结果为 `95 passed`。

## DXF 16 步清理结果

输入 DXF：

`data/input/dxf_exploded/L2_20.00m平面图.dxf`

清理输出目录：

`data/input/dxf_exploded/L2_20.00m平面图_self_clean`

关键产物：

- `manifest.json`
- `index.html`
- `steps/000_baseline` 到 `steps/016_strip_regenerated_classes_section`

清理状态汇总：

- baseline：1
- accepted：2
- rejected：14
- accepted 主线最终停在 step 003：`remove_acad_layerstates`
- step 016 候选文件已生成并保留：`steps/016_strip_regenerated_classes_section/candidate_after.dxf`

说明：

- 第 5 步以后多项清理触发 `needs_manual_review`，原因是这些候选需要外部 AutoCAD validation。
- 为了完整跑完 16 阶段并保留所有候选文件，人工确认类步骤均保守标记为 `rejected`，未推进 accepted 主线。
- 回滚机制和 rejected 候选均保留。

## 第 16 步 DXF 房间识别结果

用于识别的 DXF：

`data/input/dxf_exploded/L2_20.00m平面图_self_clean/steps/016_strip_regenerated_classes_section/candidate_after.dxf`

识别输出目录：

`output/L2_20m_step16_room_extraction_20260613_202433`

关键 HTML：

- `reports/recognized_rooms.html`
- `reports/room_candidates_review.html`
- `reports/json_review_room_extraction.html`
- `reports/review_tasks.html`

关键 JSON：

- `json/cad_raw_visible.json`
- `json/cad_raw_boundary_visible.json`
- `json/room_label_candidates.json`
- `json/room_candidates.json`
- `json/rooms_auto.json`
- `json/rooms_pdf_checked.json`
- `json/review_tasks.json`

识别结果摘要：

- 房间 label：563
- 边界候选：5244
- 房间候选：563
- 有 CAD 几何房间：290
- 无 CAD 几何房间：273
- PDF 校核后需人工审核任务：549
- 自动通过：14

重要处理细节：

- 直接使用完整 `cad_raw_visible.json` 跑 `build-room-candidates` 时，由于包含约 1,001,906 条 polyline，默认候选构造耗时过长。
- 后续生成了轻量输入 `cad_raw_boundary_visible.json`，只保留 `0-面积线`、`WALL`、`Defpoints` 相关 polyline，数量降到 21,958 条。
- 房间识别最终基于轻量边界输入完成。
- PDF 校核使用：`data/input/pdf/CNCCⅡ-A-207（L2_20.00m平面图）.pdf`。

## 后续工作建议

下一步应开启新的 DXF 数据清理分支，重点优化原始 DXF 数据：

- 继续分析哪些 DXF section、objects、symbol tables 可以安全移除。
- 对 `needs_manual_review` 的清理候选做 AutoCAD 打开验证。
- 将能通过 AutoCAD 验证的阶段从 rejected 提升为 accepted。
- 优化清理后的 DXF，使房间识别阶段不再需要额外裁剪 `cad_raw_visible.json`。
- 重点减少无关 polyline，例如通用详图、立面、家具、填充、非房间边界图层。

## Git 注意事项

- 根目录 `output/` 是本地运行产物，不应提交到 git。
- `data/input/**` 和 `data/output/**` 已在 `.gitignore` 中忽略。
- 当前工作应合并到 `main` 后，从 `main` 新建 DXF 数据清理分支继续。
