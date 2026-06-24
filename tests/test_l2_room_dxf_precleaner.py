from __future__ import annotations

import json
from pathlib import Path

import ezdxf

from room_extractor.cad.l2_room_dxf_precleaner import (
    dedupe_linework,
    enable_all_layers,
    iterative_explode_reference_clean,
    reference_guided_prune,
    reference_guided_block_content_prune,
    remove_reference_absent_unreachable_blocks,
    remove_paperspace_layouts,
)


def test_remove_paperspace_layouts_keeps_empty_l2_and_preserves_modelspace(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    manifest_path = tmp_path / "manifest.json"

    doc = ezdxf.new()
    doc.layouts.rename("Layout1", "L2")
    extra = doc.layouts.new("Flow diagram")
    msp = doc.modelspace()
    line = msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_circle((5, 5), 2, dxfattribs={"layer": "A-COLUMN"})
    doc.layouts.get("L2").add_text("sheet title")
    extra.add_line((0, 0), (1, 1))
    expected_handle = line.dxf.handle
    doc.saveas(source)

    result = remove_paperspace_layouts(
        source=source,
        out=out,
        keep_layout="L2",
        manifest_path=manifest_path,
    )

    cleaned = ezdxf.readfile(out)
    assert {layout.name for layout in cleaned.layouts} == {"L2", "Model"}
    assert len(cleaned.layouts.get("L2")) == 0
    assert len(cleaned.modelspace()) == 2
    assert cleaned.entitydb.get(expected_handle) is not None
    assert result["removed_layout_count"] == 1
    assert result["cleared_kept_paperspace_entity_count"] == 1
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["stage"] == "remove_paperspace_layouts"
    assert manifest["kept_paperspace_layout"] == "L2"
    assert manifest["after"]["layout_count"] == 2


def test_remove_reference_absent_unreachable_blocks_preserves_modelspace(tmp_path: Path) -> None:
    reference = tmp_path / "reference.dxf"
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    report_path = tmp_path / "removed_blocks.json"
    manifest_path = tmp_path / "manifest.json"

    ref_doc = ezdxf.new()
    ref_doc.blocks.new("KEEP_BLOCK").add_line((0, 0), (1, 0))
    ref_doc.modelspace().add_blockref("KEEP_BLOCK", (0, 0))
    ref_doc.saveas(reference)

    src_doc = ezdxf.new()
    src_doc.blocks.new("KEEP_BLOCK").add_line((0, 0), (1, 0))
    src_doc.blocks.new("EXTRA_BLOCK").add_circle((0, 0), 1)
    src_doc.modelspace().add_blockref("KEEP_BLOCK", (0, 0))
    src_doc.saveas(source)

    result = remove_reference_absent_unreachable_blocks(
        source=source,
        reference=reference,
        out=out,
        report_path=report_path,
        manifest_path=manifest_path,
    )

    cleaned = ezdxf.readfile(out)
    assert cleaned.blocks.get("KEEP_BLOCK") is not None
    assert "EXTRA_BLOCK" not in {block.name for block in cleaned.blocks}
    assert len(cleaned.modelspace()) == 1
    assert result["removed_block_count"] == 1
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False


def test_remove_reference_absent_unreachable_blocks_preserves_anonymous_blocks(tmp_path: Path) -> None:
    reference = tmp_path / "reference.dxf"
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    report_path = tmp_path / "removed_blocks.json"
    manifest_path = tmp_path / "manifest.json"

    ezdxf.new().saveas(reference)

    src_doc = ezdxf.new()
    src_doc.blocks.new("*D123").add_line((0, 0), (1, 0))
    src_doc.blocks.new("EXTRA_BLOCK").add_circle((0, 0), 1)
    src_doc.saveas(source)

    result = remove_reference_absent_unreachable_blocks(
        source=source,
        reference=reference,
        out=out,
        report_path=report_path,
        manifest_path=manifest_path,
    )

    cleaned = ezdxf.readfile(out)
    block_names = {block.name for block in cleaned.blocks}
    assert "*D123" in block_names
    assert "EXTRA_BLOCK" not in block_names
    assert result["removed_block_count"] == 1
    assert result["preserved_anonymous_reference_absent_unreachable_count"] == 1
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["preserved_anonymous_reference_absent_unreachable"] == ["*D123"]


def test_reference_guided_block_content_prune_removes_extra_nested_content(tmp_path: Path) -> None:
    reference = tmp_path / "reference.dxf"
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    report_path = tmp_path / "block_content_prune_report.json"
    manifest_path = tmp_path / "manifest.json"

    ref_doc = ezdxf.new()
    ref_doc.blocks.new("SHARED").add_line((0, 0), (1, 0))
    ref_doc.modelspace().add_blockref("SHARED", (0, 0))
    ref_doc.saveas(reference)

    src_doc = ezdxf.new()
    shared = src_doc.blocks.new("SHARED")
    shared.add_line((0, 0), (1, 0))
    shared.add_hatch()
    src_doc.modelspace().add_blockref("SHARED", (0, 0))
    src_doc.saveas(source)

    result = reference_guided_block_content_prune(
        source=source,
        reference=reference,
        out=out,
        report_path=report_path,
        manifest_path=manifest_path,
        tolerance=1.0,
    )

    cleaned = ezdxf.readfile(out)
    assert [entity.dxftype() for entity in cleaned.blocks.get("SHARED")] == ["LINE"]
    assert len(cleaned.modelspace()) == 1
    assert result["removed_count"] == 1
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False


def test_iterative_explode_reference_clean_prunes_after_each_level(tmp_path: Path) -> None:
    reference = tmp_path / "reference.dxf"
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    stage_dir = tmp_path / "stage"

    ref_doc = ezdxf.new()
    ref_doc.blocks.new("INNER").add_line((0, 0), (10, 0))
    ref_doc.blocks.new("OUTER").add_blockref("INNER", (0, 0))
    ref_doc.modelspace().add_blockref("OUTER", (0, 0))
    ref_doc.saveas(reference)

    src_doc = ezdxf.new()
    inner = src_doc.blocks.new("INNER")
    inner.add_line((0, 0), (10, 0))
    inner.add_circle((5, 5), 2)
    src_doc.blocks.new("OUTER").add_blockref("INNER", (0, 0))
    src_doc.modelspace().add_blockref("OUTER", (0, 0))
    src_doc.saveas(source)

    result = iterative_explode_reference_clean(
        source=source,
        reference=reference,
        out=out,
        stage_dir=stage_dir,
        manifest_path=stage_dir / "manifest.json",
        max_passes=5,
    )

    cleaned = ezdxf.readfile(out)
    assert [entity.dxftype() for entity in cleaned.modelspace()] == ["LINE"]
    assert result["completed_passes"] == 2
    assert result["stop_reason"] == "no_remaining_inserts"
    assert result["final_insert_count"] == 0
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False

    resumed = iterative_explode_reference_clean(
        source=source,
        reference=reference,
        out=out,
        stage_dir=stage_dir,
        manifest_path=stage_dir / "manifest.json",
        max_passes=5,
    )
    assert [item["resumed"] for item in resumed["passes"]] == [True, True]


def test_enable_all_layers_turns_on_and_thaws_without_changing_entities(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    manifest_path = tmp_path / "manifest.json"
    doc = ezdxf.new()
    off = doc.layers.add("OFF")
    off.off()
    frozen = doc.layers.add("FROZEN")
    frozen.freeze()
    doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"layer": "OFF"})
    doc.modelspace().add_line((0, 1), (1, 1), dxfattribs={"layer": "FROZEN"})
    doc.saveas(source)

    result = enable_all_layers(source=source, out=out, manifest_path=manifest_path)

    cleaned = ezdxf.readfile(out)
    assert all(not layer.is_off() and not layer.is_frozen() for layer in cleaned.layers)
    assert len(cleaned.modelspace()) == 2
    assert result["changed_layer_count"] == 2
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False


def test_dedupe_linework_uses_validated_near_geometry_rule(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    report_path = tmp_path / "duplicate_report.json"
    manifest_path = tmp_path / "manifest.json"
    doc = ezdxf.new()
    doc.layers.add("A")
    doc.layers.add("B")
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "A"})
    msp.add_line((0.2, 0), (10.2, 0), dxfattribs={"layer": "B"})
    msp.add_circle((5, 5), 2)
    doc.saveas(source)

    result = dedupe_linework(
        source=source,
        out=out,
        report_path=report_path,
        manifest_path=manifest_path,
        mode="near",
        signature_scope="geometry",
        near_tolerance=1.0,
    )

    cleaned = ezdxf.readfile(out)
    assert len(cleaned.modelspace()) == 2
    assert sum(1 for entity in cleaned.modelspace() if entity.dxftype() == "LINE") == 1
    assert sum(1 for entity in cleaned.modelspace() if entity.dxftype() == "CIRCLE") == 1
    assert result["removed_count"] == 1
    assert result["protection"]["status"] == "passed"
    assert json.loads(report_path.read_text(encoding="utf-8"))["dedupe_mode"] == "near"


def test_reference_guided_prune_removes_layers_types_and_signature_excess(tmp_path: Path) -> None:
    reference = tmp_path / "reference.dxf"
    source = tmp_path / "source.dxf"
    out = tmp_path / "out.dxf"
    report_path = tmp_path / "reference_prune_report.json"
    manifest_path = tmp_path / "manifest.json"

    ref_doc = ezdxf.new()
    ref_doc.layers.add("KEEP")
    ref_doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "KEEP"})
    ref_doc.modelspace().add_text("Room 101", dxfattribs={"layer": "KEEP", "insert": (5, 5)})
    ref_doc.saveas(reference)

    src_doc = ezdxf.new()
    src_doc.layers.add("KEEP")
    src_doc.layers.add("EXTRA")
    src_doc.modelspace().add_line((0.2, 0), (10.2, 0), dxfattribs={"layer": "KEEP"})
    src_doc.modelspace().add_line((0, 2), (10, 2), dxfattribs={"layer": "KEEP"})
    src_doc.modelspace().add_text("Room 101", dxfattribs={"layer": "KEEP", "insert": (5, 5)})
    src_doc.modelspace().add_circle((2, 2), 1, dxfattribs={"layer": "KEEP"})
    src_doc.modelspace().add_hatch(dxfattribs={"layer": "EXTRA"})
    src_doc.modelspace().add_xline((0, 0), (1, 0), dxfattribs={"layer": "EXTRA"})
    src_doc.saveas(source)

    result = reference_guided_prune(
        source=source,
        reference=reference,
        out=out,
        report_path=report_path,
        manifest_path=manifest_path,
        tolerance=1.0,
    )

    cleaned = ezdxf.readfile(out)
    assert [entity.dxftype() for entity in cleaned.modelspace()] == ["LINE", "TEXT"]
    assert result["removed_count"] == 4
    assert result["removed_reason_counts"] == {
        "entity_signature_exceeds_reference_budget": 1,
        "entity_type_absent_from_reference_layer": 1,
        "layer_absent_from_reference": 2,
    }
    assert result["protection"]["status"] == "passed"
    assert result["failed"] is False
