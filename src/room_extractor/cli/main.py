from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from room_extractor import __version__
from room_extractor.cad import analyze_layers, extract_cad_raw, load_dxf
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logger(log_level="INFO")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


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


if __name__ == "__main__":
    raise SystemExit(main())
