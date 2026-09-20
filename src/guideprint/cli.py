"""Command line entry point."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import re
import sys
import tempfile
from pathlib import Path

from guideprint.export import load_export
from guideprint.render import RenderOptions, render_note

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    defaults = RenderOptions()
    parser = argparse.ArgumentParser(
        prog="guideprint",
        description="Turn a Notesnook markdown export into step-by-step guide PDFs, one laid "
        "out for paper and one with a tall page per part for the screen.",
    )
    parser.add_argument("source", type=Path, help="export zip, directory, or a single .md file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="PDF file for a single note, or a directory when the export has several; "
        "each variant adds its suffix, so guide.pdf becomes guide-print.pdf and "
        "guide-digital.pdf (default: <note title> in the current directory)",
    )
    parser.add_argument("--note", help="only build the note with this title")
    parser.add_argument(
        "--variant",
        choices=["both", "print", "digital"],
        default="both",
        help="print: pages of the chosen paper size; digital: one page per level-1 "
        "section, as tall as it needs to be; both: write both (default: %(default)s)",
    )
    parser.add_argument(
        "--barcode-width",
        type=float,
        default=defaults.barcode_width_mm,
        metavar="MM",
        help="printed width of every barcode (default: %(default)s)",
    )
    parser.add_argument(
        "--paper",
        default=defaults.paper,
        choices=["a4", "a5", "a3", "us-letter", "us-legal"],
        help="page size (default: %(default)s)",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=defaults.margin_mm,
        metavar="MM",
        help="page margin (default: %(default)s)",
    )
    parser.add_argument(
        "--font", default=defaults.font, help="font family (default: %(default)s, bundled)"
    )
    parser.add_argument(
        "--font-size",
        type=float,
        default=defaults.font_size_pt,
        metavar="PT",
        help="body text size (default: %(default)s)",
    )
    parser.add_argument(
        "--max-image-height",
        type=float,
        default=defaults.max_image_height_fraction,
        metavar="FRACTION",
        help="tallest picture as a share of the page's text area (default: %(default)s)",
    )
    parser.add_argument(
        "--default-dpi",
        type=float,
        default=defaults.default_dpi,
        help="density assumed for pictures without DPI metadata (default: %(default)s)",
    )
    parser.add_argument("--lang", help="language code for the text, e.g. de")
    parser.add_argument(
        "--keep-build",
        type=Path,
        metavar="DIR",
        help="write the generated Typst sources and pictures to DIR",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every sizing decision")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s"
    )
    options = RenderOptions(
        barcode_width_mm=args.barcode_width,
        paper=args.paper,
        margin_mm=args.margin,
        font=args.font,
        font_size_pt=args.font_size,
        max_image_height_fraction=args.max_image_height,
        default_dpi=args.default_dpi,
        lang=args.lang,
    )
    with tempfile.TemporaryDirectory(prefix="guideprint-") as tmp:
        workdir = Path(tmp)
        try:
            notes = load_export(args.source, workdir)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
        if args.note:
            notes = [note for note in notes if _title_of(note.path) == args.note]
            if not notes:
                print(f"no note titled {args.note!r}", file=sys.stderr)
                return 2
        single_file = len(notes) == 1 and args.output is not None and args.output.suffix == ".pdf"
        for index, note in enumerate(notes):
            title = _title_of(note.path)
            if single_file:
                output = args.output
            else:
                output = (args.output or Path.cwd()) / f"{slugify(title)}.pdf"
            build_root = args.keep_build or workdir / "build"
            build_dir = build_root / slugify(title) if len(notes) > 1 else build_root
            for variant in VARIANTS[args.variant]:
                target = _with_suffix(output, f"-{variant}")
                variant_options = dataclasses.replace(options, digital=variant == "digital")
                render_note(note, target, variant_options, build_dir=build_dir / variant)
                print(target)
            if index == 0 and args.keep_build:
                log.info("Typst sources kept in %s", args.keep_build)
    return 0


VARIANTS = {"print": ["print"], "digital": ["digital"], "both": ["print", "digital"]}


def _with_suffix(path: Path, suffix: str) -> Path:
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def _title_of(path: Path) -> str:
    from guideprint.markdown import parse_note

    return parse_note(path.read_text(encoding="utf-8"), path.stem).title


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", title, flags=re.UNICODE).strip("-.")
    return slug or "note"


if __name__ == "__main__":
    sys.exit(main())
