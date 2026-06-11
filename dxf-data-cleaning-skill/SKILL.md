---
name: dxf-data-cleaning
description: Use this skill when cleaning bloated DXF files that look visually equivalent to a smaller reference DXF, especially when the task requires self-driven iterative cleanup, per-step HTML/PNG reports, rollback, AutoCAD validation, and reusable cleaning rules.
---

# DXF Data Cleaning

This skill guides an AI agent through conservative, auditable DXF cleanup. Use it when a large DXF contains visually redundant or non-geometric data and must be slimmed without breaking AutoCAD or downstream room recognition.

## Core Rule

Never do a one-shot aggressive rebuild unless explicitly requested and independently validated in AutoCAD. Prefer small reversible steps:

1. Compare data sources.
2. Remove one class of bloat.
3. Save deleted data and rollback files.
4. Render before/after PNGs.
5. Check structure and pixels.
6. Accept, reject, or stop.

## Project Context

In this project, the experimental implementation is:

- `dxf_self_clean_experiment.py`

Primary reports:

- `docs/dxf_self_cleaning_plan.md`
- `docs/dxf_cleaning_work_summary.md`

Experiment output:

- `log/dxf_cleaning_experiment/`

If these files exist, read them before making new cleanup decisions.

## Workflow

### 1. Establish Baseline

Compare bloated source DXF and small reference DXF:

- File size.
- DXF section sizes: `ENTITIES`, `TABLES`, `OBJECTS`, `BLOCKS`, `CLASSES`, `ACDSDATA`, `HEADER`.
- Modelspace entity counts by type and layer.
- Visible vs invisible entities.
- Table counts: layers, APPIDs, linetypes, styles, dimstyles, blocks, layouts.
- Object counts and large dictionaries.

Use a reference DXF only as a guide. Do not assume byte-level or coordinate-level equality.

### 2. Build an Auditable Step

Each cleanup step must create a directory like:

```text
steps/NNN_action_name/
  input.dxf
  candidate_after.dxf
  accepted_after.dxf or rejected_after.dxf
  before_stats.json
  after_stats.json
  removed_*.json
  ai_check.json
  visual_check.json
  reference.png
  before.png
  after.png
  diff.png
  comparison.png
  report.html
```

The deleted data must be represented in JSON and the original `input.dxf` must be preserved so the step can be rolled back.

### 3. Validate Before Accepting

A step can be accepted only if the relevant checks pass:

- DXF reload succeeds with ezdxf or the project loader.
- File size decreases.
- Modelspace visible geometry is unchanged unless the step explicitly targets auxiliary entities.
- Entity type counts and layer counts are unchanged for protected entity types.
- before/after PNG uses a shared bbox and has zero or justified pixel delta.
- High-risk milestones are opened in AutoCAD.

For this project, per-step visual checks should render cropped images. Exclude `POINT`, `XLINE`, and `RAY` from bbox calculation when they are known auxiliary data.

### 4. Accept, Reject, or Stop

Accept when checks pass and the step is within the intended risk level.

Reject when:

- Removed count is zero.
- Structure checks fail.
- AutoCAD cannot open the candidate.
- The candidate relies on a known-bad strategy.

Stop when the remaining bloat is mostly semantic AutoCAD/AEC/TCH object structure and further deletion would likely risk compatibility.

## Recommended Cleanup Order

Use the smallest safe cleanup first. A proven order for this project:

1. Exact duplicate linework.
2. Invisible modelspace entities.
3. `ACAD_LAYERSTATES`.
4. Unused APPID table records.
5. Unreachable block definitions.
6. Non-geometric OBJECTS metadata, such as color books and sort tables.
7. Unused symbol table records.
8. Paper-space layouts and paper-space-only entities.
9. Remaining OBJECTS metadata: scale lists, visual styles, image/detail/section/plot/render/sheet/ezdxf metadata.
10. Raw section stripping for `CLASSES` and `ACDSDATA`.
11. Auxiliary modelspace `POINT`, `XLINE`, `RAY` removal.
12. Second-pass unreachable blocks.
13. Second-pass unused tables.
14. Large null dictionary shells.
15. Strip regenerated non-geometric sections at the end.

Do not combine many of these in one step. Iteration is part of the method.

## High-Value Bloat Patterns

### Invisible Geometry

Entities on off/frozen layers or with invisible flags can massively inflate files. Delete only after proving visible entity counts are unchanged.

### Object Metadata

Common removable candidates:

- `ACAD_LAYERSTATES`
- `ACAD_COLOR`
- `SORTENTSTABLE`
- `ACAD_SCALELIST`
- `ACAD_VISUALSTYLE`
- image/detail/section view dictionaries
- plot/render settings
- sheet set data
- ezdxf metadata

Treat object metadata as medium/high risk. Keep rollback and require visual checks.

### Raw Sections

`CLASSES` and `ACDSDATA` often contain non-geometric custom data. Strip only as a raw DXF section operation and then reload/render the result.

### Auxiliary Entities

`POINT`, `XLINE`, and `RAY` can make canvases huge and can hurt visual or room recognition. Delete them only when:

- Reference DXF lacks them or they are known construction entities.
- Protected geometry types are unchanged.
- before/after cropped PNG diff is zero.

### Large Null Dictionaries

Large dictionaries whose values are mostly string `0` are likely broken shells. A conservative rule:

- `DICTIONARY` object.
- At least 50 entries.
- At least 80% of entries point to string `0`.
- Delete only after removing parent references if needed.

## Known Bad Path

In this project, rebuilding a new DXF from visible modelspace compressed the file to about 344 KB but AutoCAD 2024 could not open it.

Therefore:

- Do not use `rebuild_visible_modelspace` as a reusable automatic rule.
- Prefer incremental deletion inside the existing DXF structure.

## Local AI / Vision Guidance

Do not claim local AI validation unless a real model is called.

In the current implementation, `--dry-run-ai` only writes a placeholder. The real validation is:

- structural checks,
- ezdxf reload,
- PNG pixel comparison,
- manual AutoCAD validation.

If a local VLM such as Qwen is available later, use it only as an assistant to inspect `comparison.png`; it must not replace structural checks or AutoCAD validation.

## Stop Criteria

Stop the cleanup when:

- The candidate opens in AutoCAD.
- Modelspace matches the reference at the intended semantic level.
- Remaining size is dominated by `TABLES`, `OBJECTS`, or `BLOCKS` that may affect AutoCAD semantics.
- Further reduction would require deleting AEC/TCH/material/proxy/style objects without enough sample coverage.

For the current project, the validated stopping point is:

- `log/dxf_cleaning_experiment/steps/016_strip_regenerated_classes_section/accepted_after.dxf`
- Size: 437,346 bytes.
- AutoCAD 2024 manual validation: passed.

## Commands

Run one cleanup step:

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --max-steps 1 --dry-run-ai
```

Accept a reviewed step:

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --mark-step-accepted <step>
```

Reject a bad step:

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --mark-step-rejected <step>
```

Write remaining bloat audit:

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --write-bloat-audit
```

Regenerate step images:

```powershell
python dxf_self_clean_experiment.py --resume log/dxf_cleaning_experiment --render-step-images
```

## Future Refactor Target

Once the experiment stabilizes, move reusable logic from `dxf_self_clean_experiment.py` into `src` modules:

- DXF stats scanner.
- Cleanup action implementations.
- Protection checks.
- Rendering and visual diff.
- Report writer.
- Rollback manifest manager.

Keep the experiment runner as an orchestration layer, not the permanent library boundary.
