from __future__ import annotations

import argparse
import sys
from typing import Sequence

from room_extractor import __version__
from room_extractor.utils.logger import setup_logger
from room_extractor.workflows.dxf_preparation import register_dxf_preparation_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dxf-preparation",
        description="DXF preparation workflow: DWG/DXF normalization, AutoCAD conversion, explode, and line dedupe.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_dxf_preparation_commands(subparsers)
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


if __name__ == "__main__":
    raise SystemExit(main())
