# Building Room Extractor

建筑图纸房间信息自动提取与 PDF 校核系统。当前实现范围限定为 Phase 0/Phase 1：基础工程结构和 DXF 原始对象解析。

## 当前能力

- `room-extractor --version` 输出版本号。
- `room-extractor analyze-layers --dxf <file>` 输出 DXF 图层清单和实体统计。
- `room-extractor extract-cad --dxf <file> --out <file>` 输出 `cad_raw.json`，包含图层、文字、块属性和多段线基础信息。

本阶段不包含 OCR、VLM、PDF 坐标映射、Streamlit 人工校核界面或高级房间匹配。

## 安装

```powershell
python -m pip install -e .[dev]
```

## 示例命令

```powershell
room-extractor --version
room-extractor analyze-layers --dxf data/input/dxf/sample.dxf
room-extractor extract-cad --dxf data/input/dxf/sample.dxf --out data/output/json/cad_raw.json
```

## 输出结构

`cad_raw.json` 至少包含：

```json
{
  "source_file": "sample.dxf",
  "layers": [],
  "texts": [],
  "blocks": [],
  "polylines": [],
  "issues": []
}
```

## 测试

```powershell
python -m pytest
```

