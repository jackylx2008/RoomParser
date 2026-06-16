"""Explode selected modelspace INSERT handles with AcCoreConsole."""

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
from room_extractor.extraction.room_text_parser import extract_room_name, extract_room_number


DEFAULT_TEMP_ROOT = Path("D:/TEMP")
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
OPENING_LAYER_KEYWORDS = ("DOOR", "门", "HOLE", "OPENING", "A-HOLE")
BOUNDARY_LAYER_KEYWORDS = ("0-面积线", "WALL", "Defpoints")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explode selected modelspace INSERT handles with AcCoreConsole.")
    parser.add_argument("--source", required=True, help="Input DXF.")
    parser.add_argument("--out", required=True, help="Output DXF.")
    parser.add_argument("--handle", action="append", required=True, help="INSERT handle to explode. Repeatable.")
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
    manifest = run_explode_handles(
        source=source,
        out=out,
        handles=[normalize_handle(handle) for handle in args.handle],
        timeout_seconds=int(args.timeout_seconds),
        accoreconsole=resolve_accoreconsole_path(args.accoreconsole),
        locale=str(args.locale),
        keep_work_dir=bool(args.keep_work_dir),
    )
    manifest_path = Path(args.manifest_out).resolve() if args.manifest_out else out.with_suffix(".handle_explode_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["status"] == "converted" and manifest["output_load_ok"] else 1


def run_explode_handles(
    source: Path,
    out: Path,
    handles: list[str],
    timeout_seconds: int,
    accoreconsole: Path,
    locale: str,
    keep_work_dir: bool,
) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)
    if out.exists():
        out.unlink()
    before = inspect_dxf(source, handles)
    work_root = DEFAULT_TEMP_ROOT
    work_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="room_extractor_handle_explode_", dir=work_root))
    started = time.monotonic()
    try:
        input_file = work_dir / "input.dxf"
        shutil.copy2(source, input_file)
        script_file = work_dir / "explode_insert_handles.scr"
        script_file.write_text(build_explode_script(out, handles), encoding="ascii")
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
                after = inspect_dxf(out, handles)
                output_load_ok = True
            except Exception as exc:
                output_error = f"{type(exc).__name__}: {exc}"
        return {
            "status": status,
            "source": str(source),
            "out": str(out),
            "handles": handles,
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
            "handles": handles,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "message": str(exc),
            "output_load_ok": False,
        }
    finally:
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def build_explode_script(out: Path, handles: list[str]) -> str:
    normalized_output = str(out.resolve()).replace("\\", "/")
    quoted_handles = " ".join(f'"{handle}"' for handle in handles)
    return f"""
FILEDIA
0
CMDDIA
0
ISAVEBAK
0
TILEMODE
1
(setq room_extractor_handles (list {quoted_handles}))
(setq room_extractor_selection (ssadd))
(setq room_extractor_selected 0)
(setq room_extractor_missing 0)
(foreach room_extractor_handle room_extractor_handles
  (setq room_extractor_entity (handent room_extractor_handle))
  (if room_extractor_entity
    (progn
      (ssadd room_extractor_entity room_extractor_selection)
      (setq room_extractor_selected (1+ room_extractor_selected))
      (princ (strcat "\\nROOM_EXTRACTOR_SELECTED_HANDLE " room_extractor_handle))
    )
    (progn
      (setq room_extractor_missing (1+ room_extractor_missing))
      (princ (strcat "\\nROOM_EXTRACTOR_MISSING_HANDLE " room_extractor_handle))
    )
  )
)
(if (> room_extractor_selected 0)
  (command "_.EXPLODE" room_extractor_selection "")
)
(princ (strcat "\\nROOM_EXTRACTOR_SELECTED_COUNT " (itoa room_extractor_selected)))
(princ (strcat "\\nROOM_EXTRACTOR_MISSING_COUNT " (itoa room_extractor_missing)))
_DXFOUT
"{normalized_output}"
16
_QUIT
Y

""".lstrip()


def inspect_dxf(path: Path, handles: list[str]) -> dict[str, Any]:
    doc = load_dxf(path)
    msp = doc.modelspace()
    counts = Counter(entity.dxftype() for entity in msp)
    existing_handles = set(doc.entitydb.keys())
    target_entities = []
    target_insert_counts: Counter[str] = Counter()
    for handle in handles:
        entity = doc.entitydb.get(handle)
        if entity is None:
            continue
        target_entities.append(
            {
                "handle": handle,
                "type": entity.dxftype(),
                "name": str(getattr(entity.dxf, "name", "")),
                "layer": str(getattr(entity.dxf, "layer", "")),
            }
        )
        if entity.dxftype() == "INSERT":
            target_insert_counts[str(entity.dxf.name)] += 1
    return {
        "file_size": path.stat().st_size,
        "layout_count": len(doc.layouts),
        "modelspace_entity_count": len(msp),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "insert_count": counts.get("INSERT", 0),
        "block_count": len(doc.blocks),
        "target_handle_count": len(handles),
        "remaining_target_handle_count": sum(1 for handle in handles if handle in existing_handles),
        "remaining_target_entities_sample": target_entities[:200],
        "remaining_target_insert_counts": dict(target_insert_counts.most_common(50)),
        "room_text": inspect_room_text(msp),
        "room_boundary_layers": inspect_keyword_layers(msp, BOUNDARY_LAYER_KEYWORDS),
        "room_opening_layers": inspect_keyword_layers(msp, OPENING_LAYER_KEYWORDS),
    }


def inspect_room_text(msp: Any) -> dict[str, Any]:
    room_number = 0
    room_name = 0
    parsed = 0
    for entity in msp:
        if entity.dxftype() not in TEXT_TYPES:
            continue
        text = entity_text(entity)
        has_number = extract_room_number(text) is not None
        has_name = extract_room_name(text) is not None
        room_number += int(has_number)
        room_name += int(has_name)
        parsed += int(has_number or has_name)
    return {"parsed_count": parsed, "room_number_count": room_number, "room_name_count": room_name}


def inspect_keyword_layers(msp: Any, keywords: tuple[str, ...]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for entity in msp:
        layer = str(getattr(entity.dxf, "layer", ""))
        if not any(keyword.upper() in layer.upper() for keyword in keywords):
            continue
        counts[layer] += 1
        type_counts[entity.dxftype()] += 1
    return {"total": sum(counts.values()), "layer_counts_top": dict(counts.most_common(50)), "type_counts": dict(type_counts.most_common())}


def entity_text(entity: Any) -> str:
    if entity.dxftype() == "MTEXT":
        return str(entity.text)
    return str(getattr(entity.dxf, "text", ""))


def normalize_handle(handle: str) -> str:
    return str(handle).strip().upper()


def safe_tail(raw: bytes, max_chars: int = 3000) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-30:])[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
