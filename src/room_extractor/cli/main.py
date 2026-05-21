from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from room_extractor import __version__
from room_extractor.cad import AcCoreConsoleDwgConverter, analyze_layers, convert_dwg_directory, extract_cad_raw, load_dxf
from room_extractor.utils.logger import setup_logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="room-extractor", description="Building Room Extractor command line tools.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze-layers", help="Analyze DXF layers and entity counts.")
    analyze_parser.add_argument("--dxf", required=True, help="Path to the input DXF file.")
    analyze_parser.set_defaults(func=_run_analyze_layers)

    extract_parser = subparsers.add_parser("extract-cad", help="Extract raw CAD entities to JSON.")
    extract_parser.add_argument("--dxf", required=True, help="Path to the input DXF file.")
    extract_parser.add_argument("--out", required=True, help="Path to the output cad_raw.json file.")
    extract_parser.set_defaults(func=_run_extract_cad)

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
        "--dxf-precision",
        type=int,
        default=16,
        help="DXFOUT decimal precision.",
    )
    convert_parser.set_defaults(func=_run_convert_dwg)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logger(log_level="INFO")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def _run_analyze_layers(args: argparse.Namespace) -> int:
    dxf_path = Path(args.dxf)
    doc = load_dxf(dxf_path)
    result = analyze_layers(doc, dxf_path)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _run_extract_cad(args: argparse.Namespace) -> int:
    dxf_path = Path(args.dxf)
    out_path = Path(args.out)
    doc = load_dxf(dxf_path)
    result = extract_cad_raw(doc, dxf_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _run_convert_dwg(args: argparse.Namespace) -> int:
    converter = AcCoreConsoleDwgConverter(
        accoreconsole_path=args.accoreconsole,
        locale=str(args.locale),
        timeout_seconds=int(args.timeout_seconds),
        dxf_precision=int(args.dxf_precision),
        keep_scripts=bool(args.keep_scripts),
    )
    results = convert_dwg_directory(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        recursive=bool(args.recursive),
        overwrite=bool(args.overwrite),
        converter=converter,
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


if __name__ == "__main__":
    raise SystemExit(main())
