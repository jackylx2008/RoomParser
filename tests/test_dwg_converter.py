from __future__ import annotations

from pathlib import Path

from room_extractor.cad.dwg_converter import DwgConversionResult, build_dxfout_script, convert_dwg_directory


class FakeConverter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, bool]] = []

    def convert(self, source_file: Path, output_file: Path, overwrite: bool = False) -> DwgConversionResult:
        self.calls.append((source_file, output_file, overwrite))
        return DwgConversionResult(source_file, output_file, "converted", None)


def test_convert_dwg_directory_uses_default_flat_output(tmp_path: Path) -> None:
    input_dir = tmp_path / "cad"
    output_dir = tmp_path / "dxf"
    input_dir.mkdir()
    first = input_dir / "A.dwg"
    second = input_dir / "B.DWG"
    first.write_bytes(b"dwg")
    second.write_bytes(b"dwg")
    converter = FakeConverter()

    results = convert_dwg_directory(input_dir, output_dir, converter=converter)

    assert [result.output_file for result in results] == [output_dir / "A.dxf", output_dir / "B.dxf"]
    assert converter.calls == [
        (first, output_dir / "A.dxf", False),
        (second, output_dir / "B.dxf", False),
    ]


def test_convert_dwg_directory_preserves_relative_paths_when_recursive(tmp_path: Path) -> None:
    input_dir = tmp_path / "cad"
    nested_dir = input_dir / "floor2"
    output_dir = tmp_path / "dxf"
    nested_dir.mkdir(parents=True)
    source = nested_dir / "L2.dwg"
    source.write_bytes(b"dwg")
    converter = FakeConverter()

    results = convert_dwg_directory(input_dir, output_dir, recursive=True, overwrite=True, converter=converter)

    assert results[0].output_file == output_dir / "floor2" / "L2.dxf"
    assert converter.calls == [(source, output_dir / "floor2" / "L2.dxf", True)]


def test_build_dxfout_script_contains_output_path(tmp_path: Path) -> None:
    output_file = tmp_path / "out.dxf"

    script = build_dxfout_script(output_file, precision=12)

    assert "FILEDIA\n0" in script
    assert "_DXFOUT" in script
    assert str(output_file.resolve()).replace("\\", "/") in script
    assert "\n12\n" in script
