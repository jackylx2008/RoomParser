from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import ezdxf

from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_LOCALE = "en-US"
DEFAULT_DXF_PRECISION = 16
DEFAULT_PROGRESS_INTERVAL_SECONDS = 30
DEFAULT_MAX_EXPLODE_PASSES = 5
DEFAULT_ACCORECONSOLE_TEMP_ROOT = Path("D:/TEMP")


@dataclass(frozen=True)
class DwgConversionResult:
    """One DWG to DXF conversion result."""

    source_file: Path
    output_file: Path
    status: str
    message: str | None = None
    explode_passes: int = 0
    remaining_insert_count: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "source_file": str(self.source_file),
            "output_file": str(self.output_file),
            "status": self.status,
            "message": self.message,
            "explode_passes": self.explode_passes,
            "remaining_insert_count": self.remaining_insert_count,
        }


class DwgConverter(Protocol):
    def convert(
        self,
        source_file: Path,
        output_file: Path,
        overwrite: bool = False,
        explode_blocks: bool = False,
        max_explode_passes: int = 0,
    ) -> DwgConversionResult:
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
        progress_interval_seconds: int = DEFAULT_PROGRESS_INTERVAL_SECONDS,
    ) -> None:
        self.accoreconsole_path = resolve_accoreconsole_path(accoreconsole_path)
        self.locale = locale
        self.timeout_seconds = timeout_seconds
        self.dxf_precision = dxf_precision
        self.keep_scripts = keep_scripts
        self.progress_interval_seconds = max(1, int(progress_interval_seconds))

    def convert(
        self,
        source_file: Path,
        output_file: Path,
        overwrite: bool = False,
        explode_blocks: bool = False,
        max_explode_passes: int = 0,
    ) -> DwgConversionResult:
        source_file = source_file.resolve()
        output_file = output_file.resolve()
        if output_file.exists() and not overwrite:
            return DwgConversionResult(source_file, output_file, "skipped", "Output already exists.")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            output_file.unlink()

        work_root = DEFAULT_ACCORECONSOLE_TEMP_ROOT
        work_root.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix="room_extractor_acad_", dir=work_root))
        current_input = work_dir / f"input{source_file.suffix.lower() or '.dwg'}"
        shutil.copy2(source_file, current_input)
        completed: subprocess.CompletedProcess[bytes] | None = None
        pass_count = _explode_pass_limit(explode_blocks=explode_blocks, max_explode_passes=max_explode_passes)
        remaining_insert_count: int | None = None
        try:
            total_explode_passes = 0
            for pass_index in range(pass_count + 1):
                work_output = work_dir / f"output_{pass_index}.dxf"
                explode_this_pass = 1 if explode_blocks and pass_index > 0 else 0
                total_explode_passes += explode_this_pass
                script_file = self._write_script(work_output, work_dir, explode_passes=explode_this_pass)
                command = [str(self.accoreconsole_path), "/i", str(current_input), "/s", str(script_file), "/l", self.locale]
                action = "explode+dxfout" if explode_this_pass else "dxfout"
                label = f"AcCoreConsole pass {pass_index + 1}/{pass_count + 1} ({action})"
                if explode_this_pass:
                    logger.info("%s will unlock all layers before exploding INSERT entities", label)
                logger.info("%s started: %s -> %s", label, current_input, work_output)
                completed = _run_with_progress(
                    command,
                    timeout=self.timeout_seconds,
                    progress_interval_seconds=self.progress_interval_seconds,
                    label=label,
                    temp_dir=work_dir,
                    env=_build_accoreconsole_env(work_dir),
                )
                if not work_output.exists() or work_output.stat().st_size <= 0:
                    message = _build_failure_message(completed)
                    logger.warning("AcCoreConsole CAD conversion failed: %s", message)
                    return DwgConversionResult(
                        source_file,
                        output_file,
                        "failed",
                        message,
                        explode_passes=total_explode_passes,
                        remaining_insert_count=remaining_insert_count,
                    )

                logger.info("%s output ready: %s bytes", label, work_output.stat().st_size)
                remaining_insert_count = count_modelspace_inserts(work_output)
                if remaining_insert_count is None:
                    logger.warning("%s INSERT count could not be verified", label)
                else:
                    logger.info("%s remaining modelspace INSERT count: %s", label, remaining_insert_count)
                if not explode_blocks or remaining_insert_count in {0, None} or pass_index >= pass_count:
                    shutil.move(str(work_output), str(output_file))
                    message = _summarize_process(completed)
                    if explode_blocks and remaining_insert_count:
                        message = _append_message(message, f"remaining INSERT count after explode={remaining_insert_count}")
                        logger.warning(
                            "Stopping explode after %s pass(es) because max_explode_passes was reached; %s INSERT entities remain",
                            total_explode_passes,
                            remaining_insert_count,
                        )
                    if explode_blocks and remaining_insert_count is None:
                        message = _append_message(message, "remaining INSERT count could not be verified")
                    return DwgConversionResult(
                        source_file,
                        output_file,
                        "converted",
                        message,
                        explode_passes=total_explode_passes,
                        remaining_insert_count=remaining_insert_count,
                    )
                current_input = work_output
                logger.info(
                    "Continuing explode because %s INSERT entities remain; completed %s/%s explode pass(es)",
                    remaining_insert_count,
                    total_explode_passes,
                    pass_count,
                )

            message = "Unexpected conversion loop exit."
            logger.warning("AcCoreConsole CAD conversion failed: %s", message)
            return DwgConversionResult(source_file, output_file, "failed", message)
        except subprocess.TimeoutExpired as exc:
            message = f"Timed out after {self.timeout_seconds} seconds: {exc}"
            logger.warning(message)
            return DwgConversionResult(source_file, output_file, "failed", message, remaining_insert_count=remaining_insert_count)
        except Exception as exc:
            message = f"AcCoreConsole DWG conversion failed: {exc}"
            logger.warning(message)
            return DwgConversionResult(source_file, output_file, "failed", message, remaining_insert_count=remaining_insert_count)
        finally:
            if not self.keep_scripts:
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                except OSError as exc:
                    logger.debug("Failed to remove temporary AutoCAD work dir %s: %s", work_dir, exc)

    def _write_script(self, output_file: Path, script_dir: Path, explode_passes: int = 0) -> Path:
        script_text = build_dxfout_script(output_file, precision=self.dxf_precision, explode_passes=explode_passes)
        script_file = script_dir / f"cad_to_dxf_{len(list(script_dir.glob('cad_to_dxf_*.scr'))):02d}.scr"
        script_file.write_text(script_text, encoding="ascii")
        return script_file


AutoCadDwgConverter = AcCoreConsoleDwgConverter


def build_dxfout_script(output_file: Path, precision: int = DEFAULT_DXF_PRECISION, explode_passes: int = 0) -> str:
    """Build an AutoCAD SCR script that exports the opened DWG as DXF."""
    normalized_output = str(output_file.resolve()).replace("\\", "/")
    commands = [
        "FILEDIA",
        "0",
        "CMDDIA",
        "0",
        "ISAVEBAK",
        "0",
    ]
    for _ in range(max(0, explode_passes)):
        commands.extend(
            [
                "TILEMODE",
                "1",
                '(command "_.-LAYER" "_Unlock" "*" "")',
                '(setq room_extractor_insert_ss (ssget "_X" (list (cons 0 "INSERT") (cons 410 "Model"))))',
                '(if room_extractor_insert_ss (progn (setq room_extractor_insert_total (sslength room_extractor_insert_ss)) (princ (strcat "\\nROOM_EXTRACTOR_EXPLODE_PROGRESS 0/" (itoa room_extractor_insert_total))) (setq room_extractor_insert_index 0) (repeat room_extractor_insert_total (setq room_extractor_insert_entity (ssname room_extractor_insert_ss room_extractor_insert_index)) (command "_.EXPLODE" room_extractor_insert_entity) (setq room_extractor_insert_index (1+ room_extractor_insert_index)) (if (or (= (rem room_extractor_insert_index 100) 0) (= room_extractor_insert_index room_extractor_insert_total)) (princ (strcat "\\nROOM_EXTRACTOR_EXPLODE_PROGRESS " (itoa room_extractor_insert_index) "/" (itoa room_extractor_insert_total)))))))',
            ]
        )
    commands.extend(
        [
            "_DXFOUT",
            f'"{normalized_output}"',
            str(precision),
            "_QUIT",
            "Y",
            "",
        ]
    )
    return "\n".join(commands)


def count_modelspace_inserts(dxf_file: Path) -> int | None:
    """Return modelspace INSERT count for a generated DXF, or None if it cannot be read."""
    try:
        doc = ezdxf.readfile(dxf_file)
    except Exception as exc:
        logger.warning("Failed to count INSERT entities in %s: %s", dxf_file, exc)
        return None
    return sum(1 for entity in doc.modelspace() if entity.dxftype() == "INSERT")


def _explode_pass_limit(explode_blocks: bool, max_explode_passes: int) -> int:
    if not explode_blocks:
        return 0
    return max(1, int(max_explode_passes) if max_explode_passes > 0 else DEFAULT_MAX_EXPLODE_PASSES)


def _run_with_progress(
    command: list[str],
    timeout: int,
    progress_interval_seconds: int,
    label: str,
    temp_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    stdout_fd, stdout_name = tempfile.mkstemp(prefix="room_extractor_accore_stdout_", suffix=".log", dir=temp_dir)
    stderr_fd, stderr_name = tempfile.mkstemp(prefix="room_extractor_accore_stderr_", suffix=".log", dir=temp_dir)
    os.close(stdout_fd)
    os.close(stderr_fd)
    stdout_path = Path(stdout_name)
    stderr_path = Path(stderr_name)
    started = time.monotonic()
    try:
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle, env=env)
            while True:
                elapsed = time.monotonic() - started
                remaining = max(0.0, timeout - elapsed)
                if remaining <= 0:
                    process.kill()
                    process.wait()
                    stdout_handle.flush()
                    stderr_handle.flush()
                    stdout = stdout_path.read_bytes()
                    stderr = stderr_path.read_bytes()
                    logger.warning("%s timed out after %.1fs; process killed", label, elapsed)
                    _log_process_feedback(label, stdout_path, stderr_path)
                    raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr)
                try:
                    process.wait(timeout=min(progress_interval_seconds, remaining))
                    stdout_handle.flush()
                    stderr_handle.flush()
                    stdout = stdout_path.read_bytes()
                    stderr = stderr_path.read_bytes()
                    elapsed = time.monotonic() - started
                    logger.info("%s finished in %.1fs with exit code %s", label, elapsed, process.returncode)
                    _log_process_feedback(label, stdout_path, stderr_path)
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - started
                    logger.info("%s still running: %.0fs elapsed / %ss timeout", label, elapsed, timeout)
                    _log_process_feedback(label, stdout_path, stderr_path)
    finally:
        for path in (stdout_path, stderr_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def _build_accoreconsole_env(temp_dir: Path) -> dict[str, str]:
    """Build an environment that keeps AutoCAD temporary writes off the system drive."""
    env = os.environ.copy()
    resolved_temp = str(temp_dir.resolve())
    env["TEMP"] = resolved_temp
    env["TMP"] = resolved_temp
    env["TMPDIR"] = resolved_temp
    return env


def _log_process_feedback(label: str, stdout_path: Path, stderr_path: Path) -> None:
    stdout_tail = _tail_process_output(stdout_path)
    stderr_tail = _tail_process_output(stderr_path)
    if stdout_tail:
        logger.info("%s AcCoreConsole stdout tail:\n%s", label, stdout_tail)
    if stderr_tail:
        logger.info("%s AcCoreConsole stderr tail:\n%s", label, stderr_tail)


def _tail_process_output(path: Path, max_bytes: int = 3000) -> str:
    try:
        size = path.stat().st_size
        if size <= 0:
            return ""
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except OSError:
        return ""
    text = _decode_process_output(raw)
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-20:])


def _append_message(message: str | None, addition: str) -> str:
    return f"{message}; {addition}" if message else addition


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


def collect_dxf_files(input_dir: Path, recursive: bool = False, pattern: str = "*.dxf") -> list[Path]:
    """Collect DXF files from a directory, or return a single DXF file path."""
    if not input_dir.exists():
        raise FileNotFoundError(f"DXF input directory not found: {input_dir}")
    if input_dir.is_file():
        if input_dir.suffix.lower() != ".dxf":
            raise ValueError(f"DXF input file must have .dxf suffix: {input_dir}")
        return [input_dir]
    if not input_dir.is_dir():
        raise ValueError(f"DXF input path is not a directory: {input_dir}")
    if pattern == "*.dxf":
        iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
        return sorted(path for path in iterator if path.is_file() and path.suffix.lower() == ".dxf")
    iterator = input_dir.rglob(pattern) if recursive else input_dir.glob(pattern)
    return sorted(path for path in iterator if path.is_file())


def convert_dwg_directory(
    input_dir: Path,
    output_dir: Path,
    recursive: bool = False,
    overwrite: bool = False,
    converter: DwgConverter | None = None,
    explode_blocks: bool = False,
    max_explode_passes: int = 0,
) -> list[DwgConversionResult]:
    """Convert all DWG files under an input directory to DXF files."""
    converter = converter or AcCoreConsoleDwgConverter()
    dwg_files = collect_dwg_files(input_dir, recursive=recursive)
    results: list[DwgConversionResult] = []
    for source_file in dwg_files:
        relative_file = source_file.relative_to(input_dir) if recursive else Path(source_file.name)
        output_file = output_dir / relative_file.with_suffix(".dxf")
        results.append(
            converter.convert(
                source_file,
                output_file,
                overwrite=overwrite,
                explode_blocks=explode_blocks,
                max_explode_passes=max_explode_passes,
            )
        )
    return results


def explode_dxf_directory(
    input_dir: Path,
    output_dir: Path,
    recursive: bool = False,
    overwrite: bool = False,
    converter: DwgConverter | None = None,
    max_explode_passes: int = 5,
) -> list[DwgConversionResult]:
    """Explode block INSERTs in all DXF files under an input directory and write new DXF files."""
    converter = converter or AcCoreConsoleDwgConverter()
    dxf_files = collect_dxf_files(input_dir, recursive=recursive)
    results: list[DwgConversionResult] = []
    for source_file in dxf_files:
        relative_file = source_file.relative_to(input_dir) if recursive and input_dir.is_dir() else Path(source_file.name)
        output_file = output_dir / relative_file.with_suffix(".dxf")
        results.append(
            converter.convert(
                source_file,
                output_file,
                overwrite=overwrite,
                explode_blocks=True,
                max_explode_passes=max_explode_passes,
            )
        )
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
