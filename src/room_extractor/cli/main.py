from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from room_extractor import __version__
from room_extractor.cad import AcCoreConsoleDwgConverter, analyze_layers, convert_dwg_directory, extract_cad_raw, load_dxf
from room_extractor.export import export_room_candidate_review_html
from room_extractor.extraction import build_room_candidates, build_room_label_candidates, build_rooms_auto
from room_extractor.extraction.room_json_builder import RoomsAutoBuild
from room_extractor.models.drawing import CadRawExtraction
from room_extractor.models.room_candidate import RoomCandidateSet
from room_extractor.models.room_label import RoomLabelCandidateSet
from room_extractor.pdf import RoomsPdfCheck, check_rooms_against_pdf, render_review_images
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

    labels_parser = subparsers.add_parser("build-room-labels", help="Build Phase 2 room label candidates from cad_raw.json.")
    labels_parser.add_argument("--cad", required=True, help="Path to Phase 1 cad_raw.json.")
    labels_parser.add_argument("--out", required=True, help="Path to output room_label_candidates.json.")
    labels_parser.add_argument("--floor", help="Optional floor value written to candidates.")
    labels_parser.set_defaults(func=_run_build_room_labels)

    rooms_parser = subparsers.add_parser("build-room-candidates", help="Build Phase 3 room candidates by matching labels to CAD boundaries.")
    rooms_parser.add_argument("--cad", required=True, help="Path to Phase 1 cad_raw.json.")
    rooms_parser.add_argument("--labels", required=True, help="Path to Phase 2 room_label_candidates.json.")
    rooms_parser.add_argument("--out", required=True, help="Path to output room_candidates.json.")
    rooms_parser.add_argument("--floor", help="Optional floor value written to candidates.")
    rooms_parser.add_argument("--min-boundary-area", type=float, default=1_000_000.0, help="Minimum CAD polygon area kept as a boundary.")
    rooms_parser.add_argument("--max-boundary-area", type=float, default=2_000_000_000.0, help="Maximum CAD polygon area kept as a boundary.")
    rooms_parser.set_defaults(func=_run_build_room_candidates)

    review_map_parser = subparsers.add_parser("export-review-map", help="Export an HTML/SVG visual QA map for room candidates.")
    review_map_parser.add_argument("--cad", required=True, help="Path to Phase 1 cad_raw.json.")
    review_map_parser.add_argument("--rooms", required=True, help="Path to Phase 3 room_candidates.json.")
    review_map_parser.add_argument("--out", required=True, help="Path to output HTML review map.")
    review_map_parser.add_argument("--title", default="房间边界阶段检查图", help="HTML report title.")
    review_map_parser.set_defaults(func=_run_export_review_map)

    build_rooms_parser = subparsers.add_parser("build-rooms", help="Build Phase 4 initial rooms_auto.json from room_candidates.json.")
    build_rooms_parser.add_argument("--candidates", required=True, help="Path to Phase 3 room_candidates.json.")
    build_rooms_parser.add_argument("--out", required=True, help="Path to output rooms_auto.json.")
    build_rooms_parser.set_defaults(func=_run_build_rooms)

    check_pdf_parser = subparsers.add_parser("check-pdf", help="Check rooms_auto.json against vector PDF text.")
    check_pdf_parser.add_argument("--rooms", required=True, help="Path to Phase 4 rooms_auto.json.")
    check_pdf_parser.add_argument("--pdf", required=True, help="Path to source PDF drawing.")
    check_pdf_parser.add_argument("--out", required=True, help="Path to output rooms_pdf_checked.json.")
    check_pdf_parser.add_argument("--page", type=int, default=1, help="1-based PDF page number to check.")
    check_pdf_parser.add_argument("--margin-ratio", type=float, default=0.2, help="PDF bbox expansion ratio for local text lookup.")
    check_pdf_parser.set_defaults(func=_run_check_pdf)

    review_images_parser = subparsers.add_parser("render-review-images", help="Render PDF crop images for downstream room review.")
    review_images_parser.add_argument("--rooms", required=True, help="Path to Phase 5 rooms_pdf_checked.json.")
    review_images_parser.add_argument("--pdf", required=True, help="Path to source PDF drawing.")
    review_images_parser.add_argument("--output-dir", required=True, help="Directory for generated PNG crop images.")
    review_images_parser.add_argument("--out", required=True, help="Path to output rooms_with_review_images.json.")
    review_images_parser.add_argument("--dpi", type=int, default=200, help="Render DPI for crop images.")
    review_images_parser.add_argument("--margin-ratio", type=float, default=0.2, help="Extra bbox expansion ratio for crop images.")
    review_images_parser.add_argument("--all", action="store_true", help="Render all rooms with PDF bbox, not only review-required rooms.")
    review_images_parser.set_defaults(func=_run_render_review_images)

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


def _run_build_room_labels(args: argparse.Namespace) -> int:
    cad_path = Path(args.cad)
    out_path = Path(args.out)
    cad_raw = CadRawExtraction.model_validate_json(cad_path.read_text(encoding="utf-8"))
    result = build_room_label_candidates(cad_raw, floor=args.floor)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _run_build_room_candidates(args: argparse.Namespace) -> int:
    cad_path = Path(args.cad)
    labels_path = Path(args.labels)
    out_path = Path(args.out)
    cad_raw = CadRawExtraction.model_validate_json(cad_path.read_text(encoding="utf-8"))
    labels = RoomLabelCandidateSet.model_validate_json(labels_path.read_text(encoding="utf-8"))
    result = build_room_candidates(
        cad_raw,
        labels,
        floor=args.floor,
        min_boundary_area=float(args.min_boundary_area),
        max_boundary_area=float(args.max_boundary_area),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _run_export_review_map(args: argparse.Namespace) -> int:
    cad_path = Path(args.cad)
    rooms_path = Path(args.rooms)
    cad_raw = CadRawExtraction.model_validate_json(cad_path.read_text(encoding="utf-8"))
    rooms = RoomCandidateSet.model_validate_json(rooms_path.read_text(encoding="utf-8"))
    out_path = export_room_candidate_review_html(cad_raw, rooms, out_path=args.out, title=str(args.title))
    print(f"Wrote {out_path}")
    return 0


def _run_build_rooms(args: argparse.Namespace) -> int:
    candidates_path = Path(args.candidates)
    out_path = Path(args.out)
    candidates = RoomCandidateSet.model_validate_json(candidates_path.read_text(encoding="utf-8"))
    result = build_rooms_auto(candidates)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _run_check_pdf(args: argparse.Namespace) -> int:
    rooms_path = Path(args.rooms)
    out_path = Path(args.out)
    rooms_auto = RoomsAutoBuild.model_validate_json(rooms_path.read_text(encoding="utf-8"))
    result = check_rooms_against_pdf(
        rooms_auto,
        pdf_path=Path(args.pdf),
        page_number=int(args.page),
        margin_ratio=float(args.margin_ratio),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


def _run_render_review_images(args: argparse.Namespace) -> int:
    rooms_path = Path(args.rooms)
    out_path = Path(args.out)
    rooms_pdf_checked = RoomsPdfCheck.model_validate_json(rooms_path.read_text(encoding="utf-8"))
    result = render_review_images(
        rooms_pdf_checked,
        pdf_path=Path(args.pdf),
        output_dir=Path(args.output_dir),
        dpi=int(args.dpi),
        margin_ratio=float(args.margin_ratio),
        only_review_required=not bool(args.all),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
