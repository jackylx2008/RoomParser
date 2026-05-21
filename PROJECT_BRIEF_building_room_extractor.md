# 建筑图纸房间信息自动提取与人工校核系统项目策划

## 一、项目名称

**Building Room Extractor**

建筑图纸房间信息自动提取与 PDF 校核系统。

---

## 二、项目目标

本项目用于从建筑专业 CAD / DXF 图纸中自动提取房间信息，并结合对应的矢量 PDF 图纸进行校核，最终生成结构化 JSON 数据。

系统目标是提取每个房间的：

1. 房间名称
2. 房间编号
3. 房间面积
4. 所在楼层
5. 房间坐标范围
6. 房间 polygon 边界
7. 数据来源
8. 识别置信度
9. 校核状态
10. 人工修正记录

最终输出标准 JSON，并支持低置信度房间进入人工校核流程。人工可以根据 PDF 局部截图识别房间信息，并手动绘制或修正房间边界，系统将人工结果重新写回 JSON，同时形成校核记录，用于后续提高识别准确度。

---

## 三、总体技术路线

本项目采用：

```text
CAD / DXF 自动提取为主
PDF 矢量文字校核为辅
局部截图 OCR / VLM 校核为补充
低置信度房间进入人工校核
人工绘制边界后回写 JSON
人工结果沉淀为规则优化和训练样本
```

总体流程如下：

```text
原始 CAD / DXF 图纸
  ↓
解析图层、文字、块属性、多段线、闭合区域
  ↓
提取房间名称、编号、面积、楼层、CAD 坐标
  ↓
生成初始 room JSON
  ↓
读取对应矢量 PDF
  ↓
建立 CAD 坐标到 PDF 坐标的映射
  ↓
用 PDF 矢量文字校核房间信息
  ↓
必要时生成 PDF 局部截图
  ↓
OCR / VLM 对局部截图进行辅助校核
  ↓
计算综合置信度
  ↓
高置信度房间自动通过
  ↓
低置信度房间进入人工校核任务池
  ↓
人工修正文字信息并绘制房间边界
  ↓
人工结果转换为 CAD / PDF 坐标
  ↓
重新生成最终 JSON
  ↓
输出校核记录、截图、人工样本库
```

---

## 四、项目核心原则

### 1. CAD 优先

如果有原始 CAD / DXF 文件，应优先从 CAD 中读取房间信息，不应直接从 PDF 或图片中识别。

原因：

1. CAD 坐标更准确
2. CAD 可能保留图层信息
3. CAD 可能包含房间块属性
4. CAD 中可能已有闭合房间边界
5. CAD 数据更适合生成 polygon 和 bbox

### 2. PDF 用于校核

PDF 不作为主数据源，而作为校核依据。

PDF 校核包括：

1. PDF 矢量文字提取校核
2. PDF 局部截图 OCR 校核
3. PDF 局部截图 VLM 校核
4. PDF 局部截图人工校核

### 3. AI 不做主抽取

AI 模型不负责从整张图纸中重新识别所有房间。

AI 只作为局部校核器，用于回答：

```text
CAD 提取的这个房间，在 PDF 局部截图中是否一致？
```

### 4. 必须保留证据链

每个房间 JSON 必须保留：

1. CAD 来源
2. PDF 来源
3. 自动识别结果
4. 校核结果
5. 截图路径
6. 人工修改前后记录
7. 置信度
8. 最终数据状态

### 5. 人工校核结果必须回写

人工校核不是备注，而是正式数据来源之一。

人工校核后，应重新生成该房间的正式 JSON。

---

## 五、推荐技术栈

### 后端语言

```text
Python 3.11+
```

### CAD / DXF 解析

```text
ezdxf
```

用途：

1. 读取 DXF 文件
2. 提取 TEXT / MTEXT
3. 提取 INSERT / BLOCK / ATTRIB
4. 提取 LWPOLYLINE / POLYLINE
5. 提取 HATCH
6. 读取图层信息

### PDF 解析

```text
PyMuPDF / fitz
pdfplumber
```

用途：

1. 提取 PDF 矢量文字
2. 提取 PDF 文字坐标
3. 渲染 PDF 局部截图
4. 生成人工校核截图

### 几何处理

```text
shapely
numpy
```

用途：

1. polygon 计算
2. bbox 计算
3. 面积计算
4. 点是否在 polygon 内
5. polygon IoU
6. CAD / PDF 坐标变换

### 数据结构校验

```text
pydantic
jsonschema
```

用途：

1. 定义 Room 数据结构
2. 定义 Drawing 数据结构
3. 定义 ReviewRecord 数据结构
4. 确保输出 JSON 格式稳定

### OCR，可后续接入

```text
PaddleOCR / RapidOCR
```

### VLM，可后续接入

```text
Qwen2.5-VL-7B-Instruct
InternVL3 / InternVL3.5 8B
```

### 人工校核界面，后续阶段

可选方案：

```text
方案 A：Streamlit
方案 B：FastAPI + Vue / React
方案 C：本地 HTML + Canvas 标注
```

MVP 阶段建议先使用：

```text
Streamlit
```

原因是开发快，适合本地人工校核。

---

## 六、项目目录结构建议

```text
building-room-extractor/
│
├── README.md
├── PROJECT_BRIEF.md
├── pyproject.toml
├── requirements.txt
├── .gitignore
│
├── data/
│   ├── input/
│   │   ├── cad/
│   │   ├── dxf/
│   │   └── pdf/
│   │
│   ├── output/
│   │   ├── json/
│   │   ├── reports/
│   │   ├── review_images/
│   │   ├── manual_polygons/
│   │   └── logs/
│   │
│   └── samples/
│
├── src/
│   └── room_extractor/
│       │
│       ├── __init__.py
│       │
│       ├── config/
│       │   ├── settings.py
│       │   └── layer_rules.yaml
│       │
│       ├── models/
│       │   ├── room.py
│       │   ├── drawing.py
│       │   ├── geometry.py
│       │   ├── review.py
│       │   └── confidence.py
│       │
│       ├── cad/
│       │   ├── dxf_loader.py
│       │   ├── layer_analyzer.py
│       │   ├── text_extractor.py
│       │   ├── block_extractor.py
│       │   ├── polyline_extractor.py
│       │   └── room_candidate_builder.py
│       │
│       ├── pdf/
│       │   ├── pdf_loader.py
│       │   ├── pdf_text_extractor.py
│       │   ├── pdf_renderer.py
│       │   ├── pdf_cropper.py
│       │   └── pdf_checker.py
│       │
│       ├── geometry/
│       │   ├── bbox.py
│       │   ├── polygon.py
│       │   ├── transform.py
│       │   ├── matcher.py
│       │   └── area.py
│       │
│       ├── extraction/
│       │   ├── floor_detector.py
│       │   ├── room_text_parser.py
│       │   ├── room_label_grouper.py
│       │   ├── room_boundary_detector.py
│       │   └── room_json_builder.py
│       │
│       ├── validation/
│       │   ├── confidence_scorer.py
│       │   ├── consistency_checker.py
│       │   ├── issue_detector.py
│       │   └── review_selector.py
│       │
│       ├── review/
│       │   ├── review_task_builder.py
│       │   ├── manual_review_loader.py
│       │   ├── manual_polygon_converter.py
│       │   └── review_record_writer.py
│       │
│       ├── export/
│       │   ├── json_exporter.py
│       │   ├── report_exporter.py
│       │   └── sample_exporter.py
│       │
│       ├── cli/
│       │   └── main.py
│       │
│       └── utils/
│           ├── logger.py
│           ├── file_utils.py
│           ├── regex_utils.py
│           └── text_normalizer.py
│
├── apps/
│   └── review_app/
│       ├── streamlit_app.py
│       └── components/
│
├── tests/
│   ├── test_cad_parser.py
│   ├── test_room_text_parser.py
│   ├── test_geometry.py
│   ├── test_confidence.py
│   └── test_json_schema.py
│
└── docs/
    ├── json_schema.md
    ├── workflow.md
    ├── manual_review.md
    └── development_plan.md
```

---

## 七、核心数据结构设计

### 1. Room JSON

每个房间最终应输出如下结构：

```json
{
  "room_uid": "B1_p01_r0023",
  "basic_info": {
    "floor": "B1",
    "room_number": "B1-023",
    "room_name": "库房",
    "room_type": "storage"
  },
  "area": {
    "text_value": 25.6,
    "calculated_value": 25.82,
    "unit": "m2",
    "deviation_percent": 0.86
  },
  "geometry": {
    "polygon_cad": [
      [35200, 18500],
      [41800, 18500],
      [41800, 23600],
      [35200, 23600]
    ],
    "bbox_cad": [35200, 18500, 41800, 23600],
    "polygon_pdf": [
      [122.5, 306.2],
      [168.8, 306.2],
      [168.8, 346.7],
      [122.5, 346.7]
    ],
    "bbox_pdf": [122.5, 306.2, 168.8, 346.7],
    "coordinate_unit": "mm",
    "geometry_source": "cad_auto"
  },
  "evidence": {
    "cad_source": {
      "file": "B1.dxf",
      "layout": "Model",
      "layer": "A-ROOM-TEXT",
      "entities": []
    },
    "pdf_source": {
      "file": "B1建筑平面图.pdf",
      "page": 1,
      "crop_image": "data/output/review_images/B1/B1_p01_r0023.png"
    }
  },
  "confidence": {
    "room_number": 0.92,
    "room_name": 0.88,
    "area": 0.96,
    "geometry": 0.81,
    "cad_pdf_consistency": 0.9,
    "overall": 0.89
  },
  "review": {
    "required": false,
    "status": "auto_passed",
    "reviewer": null,
    "review_time": null,
    "changes": []
  },
  "issues": [],
  "final_status": "approved"
}
```

### 2. Review Record JSON

人工校核记录结构：

```json
{
  "review_id": "review_B1_p01_r0023_001",
  "room_uid": "B1_p01_r0023",
  "review_type": "manual_geometry_and_text_correction",
  "reviewer": "manual_user_001",
  "review_time": "2026-05-21 10:30:00",
  "before": {
    "room_number": "B1-023",
    "room_name": "储藏间",
    "area": 25.6,
    "geometry_source": "auto_failed"
  },
  "after": {
    "room_number": "B1-023",
    "room_name": "库房",
    "area": 25.6,
    "geometry_source": "manual_drawn"
  },
  "changes": [
    {
      "field": "room_name",
      "before": "储藏间",
      "after": "库房",
      "reason": "PDF局部截图显示房间名称为库房"
    },
    {
      "field": "geometry",
      "before": null,
      "after": "manual_polygon",
      "reason": "自动边界识别失败，人工绘制房间边界"
    }
  ],
  "review_image": "data/output/review_images/B1/B1_p01_r0023.png",
  "manual_polygon_file": "data/output/manual_polygons/B1/B1_p01_r0023.json",
  "status": "approved"
}
```

### 3. Issue 结构

```json
{
  "issue_code": "ROOM_NAME_MISMATCH",
  "severity": "medium",
  "field": "room_name",
  "cad_value": "储藏间",
  "pdf_value": "库房",
  "message": "CAD 与 PDF 房间名称不一致",
  "need_manual_review": true
}
```

---

## 八、房间状态设计

每个房间必须有明确状态。

```text
auto_passed              自动校核通过
pending_manual_review    等待人工校核
manual_verified          人工确认无误
manual_corrected         人工已修改
rejected                 数据无效
unresolved               人工也无法确认
final                    最终成果状态
```

---

## 九、置信度规则

系统应计算综合置信度。

### 置信度字段

```text
room_number
room_name
area
geometry
cad_pdf_consistency
overall
```

### 建议规则

```text
overall >= 0.85
并且没有严重 issue
则自动通过。

overall < 0.85
或出现严重 issue
则进入人工校核。
```

### 需要人工校核的典型条件

1. 综合置信度 < 0.85
2. 房间边界置信度 < 0.80
3. CAD 与 PDF 房名不一致
4. CAD 与 PDF 面积不一致，偏差超过 3% 或 5%
5. 房号缺失
6. 面积缺失
7. polygon 不闭合
8. 一个截图内识别出多个房间名
9. 房间标签落在多个 polygon 边界附近
10. 走廊、大堂、异形空间识别困难
11. CAD 与 PDF 坐标映射失败

---

## 十、人工校核流程设计

### 1. 生成待校核任务

系统自动生成：

```text
data/output/review_tasks.json
```

内容包括：

1. room_uid
2. 楼层
3. 房号
4. 房名
5. 面积
6. 问题类型
7. 置信度
8. 局部截图路径
9. 自动 polygon
10. 待人工填写字段

### 2. 生成局部截图

低置信度房间自动生成 PDF 局部截图。

截图策略：

```text
普通房间：bbox 外扩 20%
小房间：bbox 外扩 50%
大厅/走廊：以房间文字点为中心截图
异形房间：polygon 外接矩形外扩 20%
边界不确定房间：扩大到相邻房间范围
```

截图信息写入 JSON：

```json
{
  "review_image": {
    "path": "data/output/review_images/B1/B1_p01_r0023.png",
    "pdf_page": 1,
    "crop_bbox": [100.5, 220.3, 190.8, 310.6],
    "dpi": 400,
    "margin_ratio": 0.2
  }
}
```

### 3. 人工修正字段

人工应能够修改：

1. 房间编号
2. 房间名称
3. 房间面积
4. 房间类型
5. 房间边界 polygon
6. 错误原因
7. 备注

### 4. 人工绘制房间边界

人工在局部截图上手动画 polygon。

绘制后保存：

```text
data/output/manual_polygons/{floor}/{room_uid}.json
```

结构：

```json
{
  "room_uid": "B1_p01_r0023",
  "polygon_image": [
    [120, 180],
    [360, 180],
    [360, 420],
    [120, 420]
  ],
  "polygon_pdf": [
    [122.5, 306.2],
    [168.8, 306.2],
    [168.8, 346.7],
    [122.5, 346.7]
  ],
  "polygon_cad": [
    [35200, 18500],
    [41800, 18500],
    [41800, 23600],
    [35200, 23600]
  ],
  "source": "manual_drawn"
}
```

### 5. 回写最终 JSON

人工确认后，系统重新生成该房间 JSON。

字段来源优先级：

```text
人工校核结果 > PDF 矢量校核结果 > CAD 自动提取结果 > OCR / VLM 辅助结果
```

---

## 十一、错误原因分类

人工校核时应记录错误原因。

```text
A. CAD 与 PDF 版本不一致
B. CAD 房间名称提取错误
C. CAD 房间编号提取错误
D. CAD 面积提取错误
E. PDF 文字识别错误
F. 房间边界自动识别失败
G. 房间标签与边界匹配错误
H. 走廊/异形空间识别困难
I. 多房间文字聚类错误
J. 图层不规范
K. 面积文字缺失
L. 房号缺失
M. 人工无法确认
```

---

## 十二、开发阶段规划

### Phase 0：项目初始化

目标：搭建基础项目结构。

任务：

1. 创建 Python 项目结构
2. 配置 pyproject.toml / requirements.txt
3. 配置日志
4. 配置命令行入口
5. 创建 data/input 和 data/output 目录
6. 创建基础 Pydantic 数据模型
7. 创建 README

验收标准：

1. 项目可以安装依赖
2. CLI 可以运行
3. 可以输出版本号
4. 基础测试可以通过

---

### Phase 1：DXF 基础解析

目标：从 DXF 中读取图层、文字、块、多段线。

任务：

1. 实现 DXF 文件加载
2. 输出图层清单
3. 提取 TEXT / MTEXT
4. 提取 INSERT / BLOCK / ATTRIB
5. 提取 LWPOLYLINE / POLYLINE
6. 识别 closed polyline
7. 输出 cad_raw.json

输出示例：

```text
data/output/json/cad_raw.json
```

验收标准：

1. 能列出所有图层及实体数量
2. 能提取所有文字及坐标
3. 能提取所有块属性
4. 能提取所有闭合多段线

---

### Phase 2：房间文字识别

目标：从 CAD 文字中识别房号、房名、面积。

任务：

1. 编写面积正则
2. 编写房号正则
3. 编写房间名称词库
4. 实现文本标准化
5. 实现同一房间文字聚类
6. 输出 room_label_candidates.json

面积识别正则：

```regex
(\d+(\.\d+)?)\s*(㎡|m²|m2|平方米)
```

验收标准：

1. 能识别面积
2. 能识别常见房号
3. 能识别常见房间名称
4. 能将相邻房号、房名、面积合并为 room label

---

### Phase 3：房间边界识别

目标：识别房间 polygon。

优先级：

```text
1. 从房间边界图层提取 closed polyline
2. 从面积线图层提取 closed polyline
3. 从 HATCH 提取边界
4. 从墙线 polygonize
5. 无法识别时标记为 auto_failed
```

任务：

1. 识别候选闭合多段线
2. 过滤过小 / 过大 polygon
3. 计算 polygon 面积
4. 计算 bbox
5. 将 room label 中心点匹配到 polygon
6. 输出 room_candidates.json

验收标准：

1. 每个 polygon 有 bbox
2. 每个 polygon 有面积
3. 可将房间文字绑定到 polygon
4. 失败时明确记录原因

---

### Phase 4：生成初始房间 JSON

目标：生成 CAD 自动识别版房间 JSON。

任务：

1. 根据 room label 和 polygon 生成 Room 对象
2. 计算面积偏差
3. 写入 CAD evidence
4. 写入初始 confidence
5. 输出 rooms_auto.json

验收标准：

1. JSON 格式符合 schema
2. 每个房间有 room_uid
3. 每个房间有 floor
4. 每个房间有 basic_info
5. 每个房间有 geometry
6. 每个房间有 confidence

---

### Phase 5：PDF 矢量文字校核

目标：用 PDF 文字对象校核 CAD JSON。

任务：

1. 加载 PDF
2. 提取每页文字及 bbox
3. 建立 CAD 到 PDF 坐标映射
4. 将 CAD 房间 bbox 转为 PDF bbox
5. 查询 PDF bbox 内文字
6. 解析 PDF 房号、房名、面积
7. 与 CAD 结果比对
8. 输出 rooms_pdf_checked.json

验收标准：

1. 能提取 PDF 矢量文字
2. 能基于 bbox 查找局部文字
3. 能判断 CAD 与 PDF 是否一致
4. 不一致时生成 issue

---

### Phase 6：局部截图生成

目标：为低置信度房间生成 PDF 局部截图。

任务：

1. 根据 PDF bbox 裁剪图片
2. 支持 bbox 外扩
3. 支持设置 DPI
4. 保存 review image
5. 将截图路径写入 JSON

验收标准：

1. 低置信度房间均有截图
2. 截图能看到房间标签和边界
3. 截图路径写入 room JSON

---

### Phase 7：置信度评分与人工校核任务池

目标：筛选需要人工校核的房间。

任务：

1. 实现 confidence_scorer
2. 实现 issue_detector
3. 实现 review_selector
4. 生成 review_tasks.json
5. 生成 review summary 报告

验收标准：

1. 高置信度房间 auto_passed
2. 低置信度房间 pending_manual_review
3. 每个待校核房间有问题原因
4. 每个待校核房间有局部截图

---

### Phase 8：人工校核 MVP

目标：建立本地人工校核界面。

建议使用 Streamlit。

功能：

1. 加载 review_tasks.json
2. 显示局部截图
3. 显示自动识别结果
4. 允许人工修改房号、房名、面积
5. 允许选择错误原因
6. 允许输入备注
7. 支持人工绘制 polygon
8. 保存 manual_review.json
9. 保存 manual_polygon.json

验收标准：

1. 人工可以逐个处理待校核房间
2. 修改结果可以保存
3. polygon 可以保存
4. review record 可以生成

---

### Phase 9：人工结果回写

目标：将人工校核结果写回最终 JSON。

任务：

1. 读取 rooms_pdf_checked.json
2. 读取 manual_review.json
3. 读取 manual_polygons
4. 将人工 polygon 转换为 PDF / CAD 坐标
5. 重新计算面积
6. 更新 room JSON
7. 写入 review record
8. 输出 rooms_final.json

验收标准：

1. 人工修改字段覆盖自动字段
2. 人工 polygon 成为正式 geometry
3. before / after 记录完整
4. 最终 JSON 可追溯

---

### Phase 10：报告输出

目标：输出工程可读的校核报告。

输出格式：

1. JSON
2. Excel
3. HTML

报告字段：

1. 楼层
2. 房号
3. 房名
4. CAD 面积
5. PDF 面积
6. 计算面积
7. 面积偏差
8. 状态
9. 置信度
10. 问题类型
11. 截图路径
12. 人工校核状态

---

## 十三、命令行设计

建议 CLI 设计如下：

```bash
room-extractor init
```

初始化项目目录。

```bash
room-extractor analyze-layers --dxf data/input/dxf/B1.dxf
```

分析图层。

```bash
room-extractor extract-cad --dxf data/input/dxf/B1.dxf --out data/output/json/cad_raw.json
```

提取 CAD 原始对象。

```bash
room-extractor build-rooms --cad data/output/json/cad_raw.json --out data/output/json/rooms_auto.json
```

生成初始房间 JSON。

```bash
room-extractor check-pdf --rooms data/output/json/rooms_auto.json --pdf data/input/pdf/B1.pdf --out data/output/json/rooms_pdf_checked.json
```

PDF 校核。

```bash
room-extractor build-review-tasks --rooms data/output/json/rooms_pdf_checked.json --out data/output/json/review_tasks.json
```

生成校核任务。

```bash
room-extractor run-review-app
```

启动人工校核界面。

```bash
room-extractor apply-manual-review --rooms data/output/json/rooms_pdf_checked.json --manual data/output/manual_reviews --out data/output/json/rooms_final.json
```

人工结果回写。

```bash
room-extractor export-report --rooms data/output/json/rooms_final.json --format excel
```

输出报告。

---

## 十四、配置文件设计

### layer_rules.yaml

```yaml
room_text_layers:
  - A-ROOM-TEXT
  - A-ROOM-NAME
  - A-ROOM-NO
  - A-AREA
  - 房间
  - 面积

room_boundary_layers:
  - A-ROOM-BOUNDARY
  - A-AREA-LINE
  - A-SPACE
  - 房间边界
  - 面积线

wall_layers:
  - A-WALL
  - 墙
  - WALL

ignore_layers:
  - A-AXIS
  - A-DIMS
  - DEFPOINTS
  - 轴网
  - 标注

area_units:
  - ㎡
  - m²
  - m2
  - 平方米

confidence_threshold:
  auto_pass: 0.85
  geometry_min: 0.80
  area_deviation_percent: 5.0
```

---

## 十五、测试要求

必须写基础测试。

### test_room_text_parser.py

测试：

1. 识别 `25.60㎡`
2. 识别 `25.60m²`
3. 识别 `面积：25.60`
4. 识别 `B1-023`
5. 识别 `101`
6. 识别 `办公室`

### test_geometry.py

测试：

1. bbox 计算
2. polygon 面积计算
3. 点是否在 polygon 内
4. polygon 是否闭合
5. polygon IoU

### test_confidence.py

测试：

1. CAD/PDF 一致时高置信度
2. 房名不一致时生成 issue
3. 面积偏差超限时进入人工校核
4. polygon 为空时进入人工校核

---

## 十六、MVP 优先级

不要一开始做全部功能。第一阶段 MVP 只做：

1. DXF 解析
2. 图层清单输出
3. 文字提取
4. 闭合多段线提取
5. 房间名称 / 编号 / 面积识别
6. 房间 label 聚类
7. 初始 JSON 输出

第二阶段再做：

1. PDF 矢量文字校核
2. 局部截图生成
3. 置信度评分
4. 人工校核任务池

第三阶段再做：

1. Streamlit 人工校核界面
2. 人工 polygon 绘制
3. 人工结果回写
4. 报告输出

第四阶段再接入：

1. OCR
2. VLM
3. 自动规则优化
4. 训练样本库

---

## 十七、给 Codex 的开发要求

请 Codex 按以下原则开发：

1. 先实现 MVP，不要一开始实现 OCR / VLM。
2. 所有核心数据结构使用 Pydantic。
3. 所有输出 JSON 必须格式稳定。
4. 所有文件路径不要写死，应使用配置。
5. 每个模块职责单一。
6. 几何计算统一使用 shapely。
7. DXF 解析统一使用 ezdxf。
8. PDF 解析统一封装在 pdf 模块内。
9. 每个阶段都要有命令行入口。
10. 每个阶段都要有中间 JSON 输出，便于调试。
11. 对无法识别的数据，不要静默跳过，必须写入 issues。
12. 对低置信度数据，不要强行自动通过，必须进入人工校核。
13. 人工校核结果必须保留 before / after。
14. 不要让 AI 或规则覆盖人工确认结果。
15. 代码要有类型注解。
16. 核心函数要有单元测试。

---

## 十八、Codex 第一轮任务建议

请 Codex 第一轮只完成以下内容：

1. 创建项目目录结构。
2. 创建 pyproject.toml。
3. 创建基础 Pydantic models：
   - Room
   - Drawing
   - Geometry
   - Confidence
   - Issue
   - ReviewRecord
4. 创建 CLI main.py。
5. 实现 analyze-layers 命令。
6. 实现 extract-cad 命令的基础版本：
   - 提取 layers
   - 提取 TEXT / MTEXT
   - 提取 INSERT attributes
   - 提取 closed LWPOLYLINE
7. 输出 cad_raw.json。
8. 编写最小单元测试。

第一轮不要做：

1. OCR
2. VLM
3. Streamlit 人工界面
4. PDF 坐标映射
5. 高级 polygon 匹配

---

## 十九、第一轮完成后的验收标准

运行：

```bash
room-extractor analyze-layers --dxf data/input/dxf/sample.dxf
```

应输出：

1. 图层名称
2. 每个图层实体数量
3. TEXT 数量
4. MTEXT 数量
5. INSERT 数量
6. LWPOLYLINE 数量
7. closed LWPOLYLINE 数量

运行：

```bash
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw.json
```

应生成：

```json
{
  "source_file": "sample.dxf",
  "layers": [],
  "texts": [],
  "blocks": [],
  "polylines": []
}
```

其中每个 text 至少包含：

```json
{
  "text": "办公室",
  "layer": "A-ROOM-TEXT",
  "position": [12000, 8500],
  "height": 350,
  "rotation": 0
}
```

每个 closed polyline 至少包含：

```json
{
  "layer": "A-ROOM-BOUNDARY",
  "closed": true,
  "points": [
    [35200, 18500],
    [41800, 18500],
    [41800, 23600],
    [35200, 23600]
  ],
  "bbox": [35200, 18500, 41800, 23600],
  "area": 33660000
}
```

---

## 二十、最终成果形式

项目最终应输出：

1. `rooms_final.json`
2. `review_records.json`
3. `review_images/`
4. `manual_polygons/`
5. `room_check_report.xlsx`
6. `room_check_report.html`
7. `training_samples/`

其中：

```text
rooms_final.json
```

是正式成果数据。

```text
review_records.json
```

用于追溯校核过程。

```text
training_samples/
```

用于后续优化规则或训练模型。

---

## 二十一、可直接给 Codex 的启动提示词

下面这段可以直接复制到 Codex 新对话中：

```text
你现在是本项目的 Python 工程开发助手。请先完整阅读 PROJECT_BRIEF.md，然后按照其中的“Phase 0”和“Phase 1”开始从 0 搭建项目。

本项目目标是：从建筑 CAD / DXF 图纸中自动提取房间名称、编号、面积、楼层、坐标范围和 polygon 边界，生成结构化 JSON；后续结合 PDF 进行矢量文字校核、局部截图校核和人工校核。

第一轮只做基础工程和 DXF 解析，不要实现 OCR、VLM、Streamlit 人工界面、PDF 坐标映射或高级房间匹配。

请完成：

1. 创建标准 Python 项目结构。
2. 创建 pyproject.toml 或 requirements.txt。
3. 创建 src/room_extractor 包。
4. 创建基础 Pydantic 数据模型：
   - Room
   - Drawing
   - Geometry
   - Confidence
   - Issue
   - ReviewRecord
5. 创建 CAD 解析模块：
   - dxf_loader.py
   - layer_analyzer.py
   - text_extractor.py
   - block_extractor.py
   - polyline_extractor.py
6. 创建 CLI：
   - analyze-layers
   - extract-cad
7. analyze-layers 命令需要输出 DXF 图层清单和各类实体数量。
8. extract-cad 命令需要输出 cad_raw.json，包含：
   - source_file
   - layers
   - texts
   - blocks
   - polylines
9. 每个 text 至少包含 text、layer、position、height、rotation。
10. 每个 block 至少包含 name、layer、position、attributes。
11. 每个 polyline 至少包含 layer、closed、points、bbox、area。
12. 使用 ezdxf 解析 DXF。
13. 使用 shapely 计算 polygon、bbox 和面积。
14. 所有核心函数要有类型注解。
15. 为 room_text_parser、geometry、cad_parser 写基础测试。
16. 所有异常不要静默跳过，应写入日志或 issues。

请先给出你准备创建的文件清单，然后开始实现代码。
```
