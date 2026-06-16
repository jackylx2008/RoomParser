"""Explode selected modelspace INSERT block names with AcCoreConsole."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


_ensure_src_on_path()

from room_extractor.cad.dwg_converter import resolve_accoreconsole_path
from room_extractor.cad.dxf_loader import load_dxf


DEFAULT_TEMP_ROOT = Path("D:/TEMP")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explode selected modelspace block INSERT names with AcCoreConsole.")
    parser.add_argument("--source", required=True, help="Input DXF.")
    parser.add_argument("--out", required=True, help="Output DXF.")
    parser.add_argument("--block", action="append", required=True, help="Block name to explode. Repeatable.")
    parser.add_argument("--timeout-seconds", type=int, default=1200, help="AcCoreConsole timeout.")
    parser.add_argument("--accoreconsole", help="Path to AcCoreConsole.exe.")
    parser.add_argument("--locale", default="en-US", help="Locale passed to AcCoreConsole.")
    parser.add_argument("--manifest-out", help="Optional JSON manifest path.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Keep temporary AutoCAD work directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = run_explode_named_blocks(
        source=source,
        out=out,
        block_names=[str(name) for name in args.block],
        timeout_seconds=int(args.timeout_seconds),
        accoreconsole=resolve_accoreconsole_path(args.accoreconsole),
        locale=str(args.locale),
        keep_work_dir=bool(args.keep_work_dir),
    )
    manifest_path = Path(args.manifest_out).resolve() if args.manifest_out else out.with_suffix(".named_explode_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["status"] == "converted" and manifest["output_load_ok"] else 1


def run_explode_named_blocks(
    source: Path,
    out: Path,
    block_names: list[str],
    timeout_seconds: int,
    accoreconsole: Path,
    locale: str,
    keep_work_dir: bool,
) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    if out.exists():
        out.unlink()
    before = inspect_dxf(source, block_names)
    work_root = DEFAULT_TEMP_ROOT
    work_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="room_extractor_named_explode_", dir=work_root))
    started = time.monotonic()
    try:
        input_file = work_dir / "input.dxf"
        shutil.copy2(source, input_file)
        script_file = work_dir / "explode_named_blocks.scr"
        script_file.write_text(build_explode_script(out, block_names), encoding="ascii")
        env = os.environ.copy()
        for key in ("TEMP", "TMP", "TMPDIR"):
            env[key] = str(work_dir)
        completed = subprocess.run(
            [str(accoreconsole), "/i", str(input_file), "/s", str(script_file), "/l", locale],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout_seconds,
        )
        status = "converted" if completed.returncode == 0 and out.exists() and out.stat().st_size > 0 else "failed"
        output_load_ok = False
        output_error = None
        after: dict[str, Any] | None = None
        if out.exists():
            try:
                after = inspect_dxf(out, block_names)
                output_load_ok = True
            except Exception as exc:
                output_error = f"{type(exc).__name__}: {exc}"
        return {
            "status": status,
            "source": str(source),
            "out": str(out),
            "block_names": block_names,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "returncode": completed.returncode,
            "out_size": out.stat().st_size if out.exists() else None,
            "output_load_ok": output_load_ok,
            "output_error": output_error,
            "before": before,
            "after": after,
            "stdout_tail": safe_tail(completed.stdout),
            "stderr_tail": safe_tail(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "source": str(source),
            "out": str(out),
            "block_names": block_names,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "message": str(exc),
            "output_load_ok": False,
        }
    finally:
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def build_explode_script(out: Path, block_names: list[str]) -> str:
    normalized_output = str(out.resolve()).replace("\\", "/")
    quoted_names = " ".join(f'"{name.replace("\\", "\\\\").replace(chr(34), chr(92) + chr(34))}"' for name in block_names)
    return f"""
FILEDIA
0
CMDDIA
0
ISAVEBAK
0
TILEMODE
1
(setq room_extractor_target_blocks (list {quoted_names}))
(defun room_extractor_member_p (name values / hit item)
  (setq hit nil)
  (foreach item values
    (if (= (strcase name) (strcase item)) (setq hit T))
  )
  hit
)
(setq room_extractor_insert_ss (ssget "_X" (list (cons 0 "INSERT") (cons 410 "Model"))))
(if room_extractor_insert_ss
  (progn
    (setq room_extractor_total (sslength room_extractor_insert_ss))
    (setq room_extractor_index 0)
    (setq room_extractor_exploded 0)
    (repeat room_extractor_total
      (setq room_extractor_entity (ssname room_extractor_insert_ss room_extractor_index))
      (setq room_extractor_data (entget room_extractor_entity))
      (setq room_extractor_name (cdr (assoc 2 room_extractor_data)))
      (if (room_extractor_member_p room_extractor_name room_extractor_target_blocks)
        (progn
          (setq room_extractor_exploded (1+ room_extractor_exploded))
          (princ (strcat "\\nROOM_EXTRACTOR_EXPLODE_BLOCK " room_extractor_name))
          (command "_.EXPLODE" room_extractor_entity)
        )
      )
      (setq room_extractor_index (1+ room_extractor_index))
    )
    (princ (strcat "\\nROOM_EXTRACTOR_EXPLODED_COUNT " (itoa room_extractor_exploded)))
  )
)
_DXFOUT
"{normalized_output}"
16
_QUIT
Y

""".lstrip()


def inspect_dxf(path: Path, block_names: list[str]) -> dict[str, Any]:
    doc = load_dxf(path)
    counts = Counter(entity.dxftype() for entity in doc.modelspace())
    target_insert_counts: Counter[str] = Counter()
    for entity in doc.modelspace():
        if entity.dxftype() == "INSERT":
            target_insert_counts[str(entity.dxf.name)] += 1
    return {
        "file_size": path.stat().st_size,
        "layout_count": len(doc.layouts),
        "modelspace_entity_count": len(doc.modelspace()),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "insert_count": counts.get("INSERT", 0),
        "target_insert_counts": {name: target_insert_counts.get(name, 0) for name in block_names},
        "block_count": len(doc.blocks),
    }


def safe_tail(raw: bytes, max_chars: int = 3000) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-30:])[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
