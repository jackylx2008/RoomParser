"""Project-root entrypoint for Workflow B: room extraction."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    project_root = Path(__file__).resolve().parent
    src_path = str(project_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def main() -> int:
    _ensure_src_on_path()
    from room_extractor.cli.room_extraction import main as workflow_main

    return workflow_main()


if __name__ == "__main__":
    raise SystemExit(main())
