from __future__ import annotations

import argparse
import json
from pathlib import Path

from room_extractor.cad import (
    AcCoreConsoleDwgConverter,
    add_dedupe_dxf_lines_arguments,
    add_dxf_self_clean_arguments,
    convert_dwg_directory,
    explode_dxf_directory,
    run_dedupe_dxf_lines,
    run_dxf_self_clean,
)


def register_dxf_preparation_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    convert_parser = subparsers.add_parser("convert-dwg", help="Convert DWG files to DXF with AcCoreConsole.")
    convert_parser.add_argument("--input-dir", default="data/input/cad", help="Directory containing input DWG files.")
    convert_parser.add_argument("--output-dir", default="data/input/dxf", help="Directory for generated DXF files.")
    convert_parser.add_argument("--recursive", action="store_true", help="Scan input directory recursively.")
    convert_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing DXF outputs.")
    convert_parser.add_argument("--accoreconsole", help="Path to AcCoreConsole.exe. Defaults to PATH/common install folders.")
    convert_parser.add_argument("--locale", default="en-US", help="Locale passed to AcCoreConsole /l.")
    convert_parser.add_argument("--keep-scripts", action="store_true", help="Keep generated SCR files for debugging.")
    convert_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Seconds to wait for each DXF output file.",
    )
    convert_parser.add_argument(
        "--progress-interval-seconds",
        type=int,
        default=30,
        help="Seconds between AcCoreConsole progress log messages.",
    )
    convert_parser.add_argument(
        "--dxf-precision",
        type=int,
        default=16,
        help="DXFOUT decimal precision.",
    )
    convert_parser.add_argument("--explode-blocks", action="store_true", help="Explode block INSERTs after DWG opens and before DXFOUT.")
    convert_parser.add_argument(
        "--max-explode-passes",
        type=int,
        default=5,
        help="Safety cap for automatic repeated explode passes when --explode-blocks is enabled.",
    )
    convert_parser.set_defaults(func=_run_convert_dwg)

    explode_dxf_parser = subparsers.add_parser("explode-dxf", help="Explode block INSERTs in DXF files with AcCoreConsole.")
    explode_dxf_parser.add_argument("--input-dir", default="data/input/dxf", help="Directory containing DXF files, or one DXF file path.")
    explode_dxf_parser.add_argument("--output-dir", default="data/input/dxf_exploded", help="Directory for exploded DXF outputs.")
    explode_dxf_parser.add_argument("--recursive", action="store_true", help="Scan input directory recursively.")
    explode_dxf_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing DXF outputs.")
    explode_dxf_parser.add_argument("--accoreconsole", help="Path to AcCoreConsole.exe. Defaults to PATH/common install folders.")
    explode_dxf_parser.add_argument("--locale", default="en-US", help="Locale passed to AcCoreConsole /l.")
    explode_dxf_parser.add_argument("--keep-scripts", action="store_true", help="Keep generated SCR files for debugging.")
    explode_dxf_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Seconds to wait for each DXF output file.",
    )
    explode_dxf_parser.add_argument(
        "--progress-interval-seconds",
        type=int,
        default=30,
        help="Seconds between AcCoreConsole progress log messages.",
    )
    explode_dxf_parser.add_argument(
        "--dxf-precision",
        type=int,
        default=16,
        help="DXFOUT decimal precision.",
    )
    explode_dxf_parser.add_argument(
        "--max-explode-passes",
        type=int,
        default=5,
        help="Safety cap for automatic repeated explode passes.",
    )
    explode_dxf_parser.set_defaults(func=_run_explode_dxf)

    dedupe_parser = subparsers.add_parser(
        "dedupe-dxf-lines",
        help="Analyze and optionally remove duplicate line-like entities in exploded DXF files.",
    )
    add_dedupe_dxf_lines_arguments(dedupe_parser)
    dedupe_parser.set_defaults(func=_run_dedupe_dxf_lines)

    self_clean_parser = subparsers.add_parser(
        "self-clean-dxf",
        help="Run the auditable 16-stage DXF cleaner with per-step rollback artifacts.",
    )
    add_dxf_self_clean_arguments(self_clean_parser)
    self_clean_parser.set_defaults(func=_run_self_clean_dxf)


def _run_convert_dwg(args: argparse.Namespace) -> int:
    converter = AcCoreConsoleDwgConverter(
        accoreconsole_path=args.accoreconsole,
        locale=str(args.locale),
        timeout_seconds=int(args.timeout_seconds),
        dxf_precision=int(args.dxf_precision),
        keep_scripts=bool(args.keep_scripts),
        progress_interval_seconds=int(args.progress_interval_seconds),
    )
    results = convert_dwg_directory(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        recursive=bool(args.recursive),
        overwrite=bool(args.overwrite),
        converter=converter,
        explode_blocks=bool(args.explode_blocks),
        max_explode_passes=int(args.max_explode_passes),
    )
    payload = {
        "input_dir": str(Path(args.input_dir)),
        "output_dir": str(Path(args.output_dir)),
        "total": len(results),
        "converted": sum(1 for result in results if result.status == "converted"),
        "skipped": sum(1 for result in results if result.status == "skipped"),
        "failed": sum(1 for result in results if result.status == "failed"),
        "results": [result.to_dict() for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["failed"] else 0


def _run_explode_dxf(args: argparse.Namespace) -> int:
    converter = AcCoreConsoleDwgConverter(
        accoreconsole_path=args.accoreconsole,
        locale=str(args.locale),
        timeout_seconds=int(args.timeout_seconds),
        dxf_precision=int(args.dxf_precision),
        keep_scripts=bool(args.keep_scripts),
        progress_interval_seconds=int(args.progress_interval_seconds),
    )
    results = explode_dxf_directory(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        recursive=bool(args.recursive),
        overwrite=bool(args.overwrite),
        converter=converter,
        max_explode_passes=int(args.max_explode_passes),
    )
    payload = {
        "input_dir": str(Path(args.input_dir)),
        "output_dir": str(Path(args.output_dir)),
        "total": len(results),
        "converted": sum(1 for result in results if result.status == "converted"),
        "skipped": sum(1 for result in results if result.status == "skipped"),
        "failed": sum(1 for result in results if result.status == "failed"),
        "remaining_insert_total": sum(result.remaining_insert_count or 0 for result in results),
        "results": [result.to_dict() for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["failed"] else 0


def _run_dedupe_dxf_lines(args: argparse.Namespace) -> int:
    return run_dedupe_dxf_lines(args)


def _run_self_clean_dxf(args: argparse.Namespace) -> int:
    return run_dxf_self_clean(args)
