from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_LOCALE = "en-US"
DEFAULT_DXF_PRECISION = 16


@dataclass(frozen=True)
class DwgConversionResult:
    """One DWG to DXF conversion result."""

    source_file: Path
    output_file: Path
    status: str
    message: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "source_file": str(self.source_file),
            "output_file": str(self.output_file),
            "status": self.status,
            "message": self.message,
        }


class DwgConverter(Protocol):
    def convert(self, source_file: Path, output_file: Path, overwrite: bool = False) -> DwgConversionResult:
        """Convert one DWG file to DXF."""


class AcCoreConsoleDwgConverter:
    """Convert DWG files by running local AutoCAD AcCoreConsole with a temporary SCR script."""

    def __init__(
        self,
        accoreconsole_path: str | Path | None = None,
        locale: str = DEFAULT_LOCALE,
        timeout_seconds: int = 300,
        dxf_precision: int = DEFAULT_DXF_PRECISION,
        keep_scripts: bool = False,
    ) -> None:
        self.accoreconsole_path = resolve_accoreconsole_path(accoreconsole_path)
        self.locale = locale
        self.timeout_seconds = timeout_seconds
        self.dxf_precision = dxf_precision
        self.keep_scripts = keep_scripts

    def convert(self, source_file: Path, output_file: Path, overwrite: bool = False) -> DwgConversionResult:
        source_file = source_file.resolve()
        output_file = output_file.resolve()
        if output_file.exists() and not overwrite:
            return DwgConversionResult(source_file, output_file, "skipped", "Output already exists.")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            output_file.unlink()

        work_dir = Path(tempfile.mkdtemp(prefix="room_extractor_acad_"))
        work_input = work_dir / "input.dwg"
        work_output = work_dir / "output.dxf"
        shutil.copy2(source_file, work_input)
        script_file = self._write_script(work_output, work_dir)
        command = [str(self.accoreconsole_path), "/i", str(work_input), "/s", str(script_file), "/l", self.locale]
        try:
            logger.info("Converting DWG to DXF with AcCoreConsole: %s -> %s", source_file, output_file)
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            if work_output.exists() and work_output.stat().st_size > 0:
                shutil.move(str(work_output), str(output_file))
                return DwgConversionResult(source_file, output_file, "converted", _summarize_process(completed))

            message = _build_failure_message(completed)
            logger.warning("AcCoreConsole DWG conversion failed: %s", message)
            return DwgConversionResult(source_file, output_file, "failed", message)
        except subprocess.TimeoutExpired as exc:
            message = f"Timed out after {self.timeout_seconds} seconds: {exc}"
            logger.warning(message)
            return DwgConversionResult(source_file, output_file, "failed", message)
        except Exception as exc:
            message = f"AcCoreConsole DWG conversion failed: {exc}"
            logger.warning(message)
            return DwgConversionResult(source_file, output_file, "failed", message)
        finally:
            if not self.keep_scripts:
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                except OSError as exc:
                    logger.debug("Failed to remove temporary AutoCAD work dir %s: %s", work_dir, exc)

    def _write_script(self, output_file: Path, script_dir: Path) -> Path:
        script_text = build_dxfout_script(output_file, precision=self.dxf_precision)
        script_file = script_dir / "dwg_to_dxf.scr"
        script_file.write_text(script_text, encoding="ascii")
        return script_file


AutoCadDwgConverter = AcCoreConsoleDwgConverter


def build_dxfout_script(output_file: Path, precision: int = DEFAULT_DXF_PRECISION) -> str:
    """Build an AutoCAD SCR script that exports the opened DWG as DXF."""
    normalized_output = str(output_file.resolve()).replace("\\", "/")
    return "\n".join(
        [
            "FILEDIA",
            "0",
            "CMDDIA",
            "0",
            "ISAVEBAK",
            "0",
            "_DXFOUT",
            f'"{normalized_output}"',
            str(precision),
            "_QUIT",
            "Y",
            "",
        ]
    )


def resolve_accoreconsole_path(explicit_path: str | Path | None = None) -> Path:
    """Resolve AcCoreConsole.exe from an explicit path, PATH, or common AutoCAD install folders."""
    if explicit_path:
        path = Path(explicit_path).expanduser()
        if path.exists() and path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"AcCoreConsole.exe not found: {path}")

    from_path = shutil.which("AcCoreConsole.exe") or shutil.which("accoreconsole.exe")
    if from_path:
        return Path(from_path).resolve()

    candidates: list[Path] = []
    for root in (Path("C:/Program Files/Autodesk"), Path("C:/Program Files")):
        if root.exists():
            candidates.extend(root.glob("AutoCAD 20*/AcCoreConsole.exe"))
            candidates.extend(root.glob("Autodesk/AutoCAD 20*/AcCoreConsole.exe"))

    if candidates:
        return sorted(candidates, reverse=True)[0].resolve()

    raise FileNotFoundError(
        "AcCoreConsole.exe was not found. Pass --accoreconsole or add the AutoCAD install directory to PATH."
    )


def collect_dwg_files(input_dir: Path, recursive: bool = False, pattern: str = "*.dwg") -> list[Path]:
    """Collect DWG files from a directory."""
    if not input_dir.exists():
        raise FileNotFoundError(f"DWG input directory not found: {input_dir}")
    if not input_dir.is_dir():
        raise ValueError(f"DWG input path is not a directory: {input_dir}")
    if pattern == "*.dwg":
        iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
        return sorted(path for path in iterator if path.is_file() and path.suffix.lower() == ".dwg")
    iterator = input_dir.rglob(pattern) if recursive else input_dir.glob(pattern)
    return sorted(path for path in iterator if path.is_file())


def convert_dwg_directory(
    input_dir: Path,
    output_dir: Path,
    recursive: bool = False,
    overwrite: bool = False,
    converter: DwgConverter | None = None,
) -> list[DwgConversionResult]:
    """Convert all DWG files under an input directory to DXF files."""
    converter = converter or AcCoreConsoleDwgConverter()
    dwg_files = collect_dwg_files(input_dir, recursive=recursive)
    results: list[DwgConversionResult] = []
    for source_file in dwg_files:
        relative_file = source_file.relative_to(input_dir) if recursive else Path(source_file.name)
        output_file = output_dir / relative_file.with_suffix(".dxf")
        results.append(converter.convert(source_file, output_file, overwrite=overwrite))
    return results


def _build_failure_message(completed: subprocess.CompletedProcess[bytes]) -> str:
    stdout = _decode_process_output(completed.stdout).strip()
    stderr = _decode_process_output(completed.stderr).strip()
    parts = [f"exit_code={completed.returncode}"]
    if stdout:
        parts.append(f"stdout={_tail(stdout)}")
    if stderr:
        parts.append(f"stderr={_tail(stderr)}")
    return "; ".join(parts)


def _summarize_process(completed: subprocess.CompletedProcess[bytes]) -> str | None:
    if completed.returncode == 0:
        return None
    return f"DXF output exists but AcCoreConsole exited with code {completed.returncode}."


def _tail(text: str, max_chars: int = 1000) -> str:
    return text[-max_chars:]


def _decode_process_output(raw_output: bytes | str | None) -> str:
    if raw_output is None:
        return ""
    if isinstance(raw_output, str):
        return raw_output
    if b"\x00" in raw_output[:200]:
        try:
            return raw_output.decode("utf-16le")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "gbk", "cp936", "mbcs"):
        try:
            return raw_output.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_output.decode("utf-8", errors="replace")
