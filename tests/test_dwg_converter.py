from __future__ import annotations

from pathlib import Path

import ezdxf

from room_extractor.cad.dwg_converter import (
    AcCoreConsoleDwgConverter,
    DEFAULT_ACCORECONSOLE_TEMP_ROOT,
    DwgConversionResult,
    build_dxfout_script,
    convert_dwg_directory,
    count_modelspace_inserts,
    explode_dxf_directory,
)


class FakeConverter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, bool, bool, int]] = []

    def convert(
        self,
        source_file: Path,
        output_file: Path,
        overwrite: bool = False,
        explode_blocks: bool = False,
        max_explode_passes: int = 0,
    ) -> DwgConversionResult:
        self.calls.append((source_file, output_file, overwrite, explode_blocks, max_explode_passes))
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
        (first, output_dir / "A.dxf", False, False, 0),
        (second, output_dir / "B.dxf", False, False, 0),
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
    assert converter.calls == [(source, output_dir / "floor2" / "L2.dxf", True, False, 0)]


def test_convert_dwg_directory_passes_explode_options(tmp_path: Path) -> None:
    input_dir = tmp_path / "cad"
    output_dir = tmp_path / "dxf"
    input_dir.mkdir()
    source = input_dir / "A.dwg"
    source.write_bytes(b"dwg")
    converter = FakeConverter()

    convert_dwg_directory(input_dir, output_dir, overwrite=True, converter=converter, explode_blocks=True, max_explode_passes=4)

    assert converter.calls == [(source, output_dir / "A.dxf", True, True, 4)]


def test_build_dxfout_script_contains_output_path(tmp_path: Path) -> None:
    output_file = tmp_path / "out.dxf"

    script = build_dxfout_script(output_file, precision=12)

    assert "FILEDIA\n0" in script
    assert "_DXFOUT" in script
    assert str(output_file.resolve()).replace("\\", "/") in script
    assert "\n12\n" in script


def test_build_dxfout_script_can_explode_before_export(tmp_path: Path) -> None:
    output_file = tmp_path / "out.dxf"

    script = build_dxfout_script(output_file, precision=12, explode_passes=2)

    assert script.count("_.EXPLODE") == 2
    assert script.count('"_Unlock" "*"') == 2
    assert script.count('(cons 0 "INSERT")') == 2
    assert script.count("(ssname room_extractor_insert_ss room_extractor_insert_index)") == 2
    assert "room_extractor_insert_entity" in script
    assert script.count("ROOM_EXTRACTOR_EXPLODE_PROGRESS") == 4
    assert '(rem room_extractor_insert_index 100)' in script
    assert "ROOM_EXTRACTOR_EXPLODE_PROGRESS 0/" in script
    assert script.index('"_Unlock" "*"') < script.index("_.EXPLODE")
    assert script.index("_.EXPLODE") < script.index("_DXFOUT")


def test_explode_dxf_directory_passes_repeated_explode_options(tmp_path: Path) -> None:
    input_dir = tmp_path / "dxf"
    output_dir = tmp_path / "exploded"
    input_dir.mkdir()
    source = input_dir / "A.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    converter = FakeConverter()

    explode_dxf_directory(input_dir, output_dir, overwrite=True, converter=converter, max_explode_passes=6)

    assert converter.calls == [(source, output_dir / "A.dxf", True, True, 6)]


def test_explode_dxf_accepts_single_file_input(tmp_path: Path) -> None:
    source = tmp_path / "A.dxf"
    output_dir = tmp_path / "exploded"
    source.write_text("0\nEOF\n", encoding="ascii")
    converter = FakeConverter()

    explode_dxf_directory(source, output_dir, overwrite=True, converter=converter, max_explode_passes=6)

    assert converter.calls == [(source, output_dir / "A.dxf", True, True, 6)]


def test_count_modelspace_inserts_reads_generated_dxf(tmp_path: Path) -> None:
    dxf_path = tmp_path / "with_block.dxf"
    doc = ezdxf.new()
    doc.blocks.new("ROOM_TAG")
    doc.modelspace().add_blockref("ROOM_TAG", (0, 0))
    doc.saveas(dxf_path)

    assert count_modelspace_inserts(dxf_path) == 1


def test_converter_continues_exploding_until_insert_count_is_zero(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.dxf"
    output = tmp_path / "out.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    monkeypatch.setattr("room_extractor.cad.dwg_converter.resolve_accoreconsole_path", lambda explicit: Path("C:/fake/AcCoreConsole.exe"))
    converter = AcCoreConsoleDwgConverter(accoreconsole_path=Path("C:/fake/AcCoreConsole.exe"), timeout_seconds=1)
    counts = iter([3, 1, 0])
    calls: list[tuple[str, int]] = []

    def fake_completed(command, timeout, progress_interval_seconds, label, temp_dir=None, env=None):
        script_path = Path(next(arg for arg in command if str(arg).endswith(".scr")))
        script_text = script_path.read_text(encoding="ascii")
        output_line = next(line for line in script_text.splitlines() if line.startswith('"') and line.endswith('.dxf"'))
        Path(output_line.strip('"')).write_text("0\nEOF\n", encoding="ascii")
        calls.append((label, script_text.count("_.EXPLODE")))
        import subprocess

        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("room_extractor.cad.dwg_converter._run_with_progress", fake_completed)
    monkeypatch.setattr("room_extractor.cad.dwg_converter.count_modelspace_inserts", lambda path: next(counts))

    result = converter.convert(source, output, overwrite=True, explode_blocks=True, max_explode_passes=5)

    assert result.status == "converted"
    assert result.remaining_insert_count == 0
    assert result.explode_passes == 2
    assert [explode_count for _, explode_count in calls] == [0, 1, 1]


def test_converter_places_accoreconsole_temp_files_under_default_temp_root(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.dxf"
    output = tmp_path / "out" / "out.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    monkeypatch.setattr("room_extractor.cad.dwg_converter.resolve_accoreconsole_path", lambda explicit: Path("C:/fake/AcCoreConsole.exe"))
    converter = AcCoreConsoleDwgConverter(accoreconsole_path=Path("C:/fake/AcCoreConsole.exe"), timeout_seconds=1)
    seen: dict[str, object] = {}

    def fake_completed(command, timeout, progress_interval_seconds, label, temp_dir=None, env=None):
        script_path = Path(next(arg for arg in command if str(arg).endswith(".scr")))
        output_line = next(line for line in script_path.read_text(encoding="ascii").splitlines() if line.startswith('"') and line.endswith('.dxf"'))
        Path(output_line.strip('"')).write_text("0\nEOF\n", encoding="ascii")
        seen["temp_dir"] = Path(temp_dir)
        seen["env"] = env
        import subprocess

        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("room_extractor.cad.dwg_converter._run_with_progress", fake_completed)
    monkeypatch.setattr("room_extractor.cad.dwg_converter.count_modelspace_inserts", lambda path: 0)

    result = converter.convert(source, output, overwrite=True)

    temp_dir = seen["temp_dir"]
    env = seen["env"]
    assert result.status == "converted"
    assert isinstance(temp_dir, Path)
    assert temp_dir.parent == DEFAULT_ACCORECONSOLE_TEMP_ROOT
    assert isinstance(env, dict)
    assert env["TEMP"] == str(temp_dir.resolve())
    assert env["TMP"] == str(temp_dir.resolve())
    assert env["TMPDIR"] == str(temp_dir.resolve())


def test_converter_uses_default_explode_limit_when_enabled_without_explicit_pass_count(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.dxf"
    output = tmp_path / "out.dxf"
    source.write_text("0\nEOF\n", encoding="ascii")
    monkeypatch.setattr("room_extractor.cad.dwg_converter.resolve_accoreconsole_path", lambda explicit: Path("C:/fake/AcCoreConsole.exe"))
    converter = AcCoreConsoleDwgConverter(accoreconsole_path=Path("C:/fake/AcCoreConsole.exe"), timeout_seconds=1)
    counts = iter([2, 0])
    calls: list[int] = []

    def fake_completed(command, timeout, progress_interval_seconds, label, temp_dir=None, env=None):
        script_path = Path(next(arg for arg in command if str(arg).endswith(".scr")))
        script_text = script_path.read_text(encoding="ascii")
        output_line = next(line for line in script_text.splitlines() if line.startswith('"') and line.endswith('.dxf"'))
        Path(output_line.strip('"')).write_text("0\nEOF\n", encoding="ascii")
        calls.append(script_text.count("_.EXPLODE"))
        import subprocess

        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("room_extractor.cad.dwg_converter._run_with_progress", fake_completed)
    monkeypatch.setattr("room_extractor.cad.dwg_converter.count_modelspace_inserts", lambda path: next(counts))

    result = converter.convert(source, output, overwrite=True, explode_blocks=True, max_explode_passes=0)

    assert result.status == "converted"
    assert result.remaining_insert_count == 0
    assert result.explode_passes == 1
    assert calls == [0, 1]
