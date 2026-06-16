"""Run AutoCAD EXPLODE only for visible modelspace INSERT entities.

This is an experiment helper for validating pre-explode DXF cleanup. It differs
from the current Workflow A explode command by filtering INSERT entities whose
own invisible flag is set or whose layer is off/frozen.
"""

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
from room_extractor.cad.entity_filter import is_entity_visible


DEFAULT_TEMP_ROOT = Path("D:/TEMP")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explode only visible modelspace INSERT entities with AcCoreConsole.")
    parser.add_argument("--source", required=True, help="Input DXF.")
    parser.add_argument("--out", required=True, help="Final output DXF.")
    parser.add_argument("--passes", type=int, default=1, help="Maximum visible-only explode passes.")
    parser.add_argument("--timeout-seconds", type=int, default=1200, help="Per-pass AcCoreConsole timeout.")
    parser.add_argument("--accoreconsole", help="Path to AcCoreConsole.exe.")
    parser.add_argument("--locale", default="en-US", help="Locale passed to AcCoreConsole.")
    parser.add_argument("--manifest-out", help="Optional JSON manifest path.")
    parser.add_argument("--keep-intermediate", action="store_true", help="Keep pass_N.dxf files next to the final output.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Keep temporary AutoCAD work directories.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source).resolve()
    out = Path(args.out).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = run_visible_only_explode(
        source=source,
        out=out,
        passes=max(1, int(args.passes)),
        timeout_seconds=int(args.timeout_seconds),
        accoreconsole=resolve_accoreconsole_path(args.accoreconsole),
        locale=str(args.locale),
        keep_intermediate=bool(args.keep_intermediate),
        keep_work_dir=bool(args.keep_work_dir),
    )
    manifest_path = Path(args.manifest_out).resolve() if args.manifest_out else out.with_suffix(".visible_explode_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["status"] == "completed" else 1


def run_visible_only_explode(
    source: Path,
    out: Path,
    passes: int,
    timeout_seconds: int,
    accoreconsole: Path,
    locale: str,
    keep_intermediate: bool,
    keep_work_dir: bool,
) -> dict[str, Any]:
    current = source
    steps: list[dict[str, Any]] = []
    status = "completed"
    for index in range(1, passes + 1):
        pass_out = out if index == passes else out.with_name(f"{out.stem}_pass{index}{out.suffix}")
        before = count_inserts(current)
        step = run_one_pass(
            source=current,
            out=pass_out,
            timeout_seconds=timeout_seconds,
            accoreconsole=accoreconsole,
            locale=locale,
            keep_work_dir=keep_work_dir,
        )
        after = count_inserts(pass_out) if pass_out.exists() else None
        step.update({"pass": index, "before": before, "after": after})
        steps.append(step)
        if step["status"] != "converted":
            status = "failed"
            break
        current = pass_out
        if after and int(after.get("visible_insert_count", 0)) == 0:
            if pass_out != out:
                shutil.copy2(pass_out, out)
            break
    if not keep_intermediate:
        for step in steps[:-1]:
            path = Path(step.get("out", ""))
            if path.exists() and path != out:
                path.unlink()
    return {
        "status": status,
        "source": str(source),
        "out": str(out),
        "passes_requested": passes,
        "passes_completed": sum(1 for step in steps if step["status"] == "converted"),
        "steps": steps,
    }


def run_one_pass(
    source: Path,
    out: Path,
    timeout_seconds: int,
    accoreconsole: Path,
    locale: str,
    keep_work_dir: bool,
) -> dict[str, Any]:
    if out.exists():
        out.unlink()
    work_root = DEFAULT_TEMP_ROOT
    work_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="room_extractor_visible_explode_", dir=work_root))
    started = time.monotonic()
    try:
        input_file = work_dir / "input.dxf"
        shutil.copy2(source, input_file)
        script_file = work_dir / "visible_explode.scr"
        script_file.write_text(build_visible_explode_script(out), encoding="ascii")
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
        return {
            "status": status,
            "source": str(source),
            "out": str(out),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "returncode": completed.returncode,
            "out_size": out.stat().st_size if out.exists() else None,
            "stdout_tail": safe_tail(completed.stdout),
            "stderr_tail": safe_tail(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "source": str(source),
            "out": str(out),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "message": str(exc),
        }
    finally:
        if not keep_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def build_visible_explode_script(out: Path) -> str:
    normalized_output = str(out.resolve()).replace("\\", "/")
    return f"""
FILEDIA
0
CMDDIA
0
ISAVEBAK
0
TILEMODE
1
(command "_.-LAYER" "_Unlock" "*" "")
(defun re-layer-visible-p (lname / rec flags color) (setq rec (tblsearch "LAYER" lname)) (if rec (progn (setq flags (cdr (assoc 70 rec))) (setq color (cdr (assoc 62 rec))) (and (>= color 0) (= 0 (logand flags 1)))) T))
(setq room_extractor_insert_ss (ssget "_X" (list (cons 0 "INSERT") (cons 410 "Model"))))
(if room_extractor_insert_ss (progn (setq room_extractor_insert_total (sslength room_extractor_insert_ss)) (setq room_extractor_insert_done 0) (setq room_extractor_insert_visible 0) (princ (strcat "\\nROOM_EXTRACTOR_VISIBLE_EXPLODE_TOTAL " (itoa room_extractor_insert_total))) (setq room_extractor_insert_index 0) (repeat room_extractor_insert_total (setq room_extractor_insert_entity (ssname room_extractor_insert_ss room_extractor_insert_index)) (setq room_extractor_insert_data (entget room_extractor_insert_entity)) (setq room_extractor_insert_layer (cdr (assoc 8 room_extractor_insert_data))) (setq room_extractor_insert_invisible (cdr (assoc 60 room_extractor_insert_data))) (if (and (or (not room_extractor_insert_invisible) (= room_extractor_insert_invisible 0)) (re-layer-visible-p room_extractor_insert_layer)) (progn (setq room_extractor_insert_visible (1+ room_extractor_insert_visible)) (command "_.EXPLODE" room_extractor_insert_entity))) (setq room_extractor_insert_done (1+ room_extractor_insert_done)) (setq room_extractor_insert_index (1+ room_extractor_insert_index)) (if (or (= (rem room_extractor_insert_done 100) 0) (= room_extractor_insert_done room_extractor_insert_total)) (princ (strcat "\\nROOM_EXTRACTOR_VISIBLE_EXPLODE_PROGRESS " (itoa room_extractor_insert_done) "/" (itoa room_extractor_insert_total) " visible=" (itoa room_extractor_insert_visible)))))))
_DXFOUT
"{normalized_output}"
16
_QUIT
Y

""".lstrip()


def count_inserts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing"}
    doc = load_dxf(path)
    counts = Counter(entity.dxftype() for entity in doc.modelspace())
    visible = 0
    hidden = 0
    for entity in doc.modelspace():
        if entity.dxftype() != "INSERT":
            continue
        if is_entity_visible(doc, entity):
            visible += 1
        else:
            hidden += 1
    return {
        "file_size": path.stat().st_size,
        "modelspace_entity_count": sum(counts.values()),
        "entity_type_counts_top": dict(counts.most_common(20)),
        "insert_count": counts.get("INSERT", 0),
        "visible_insert_count": visible,
        "hidden_insert_count": hidden,
    }


def safe_tail(raw: bytes, max_chars: int = 3000) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = text.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-30:])[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
