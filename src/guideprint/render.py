"""Build one note into a PDF: parse, normalize, resolve pictures, write Typst,
compile."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import typst

from guideprint.export import Note
from guideprint.images import (
    ImageInfo,
    ensure_typst_readable,
    inspect_image,
    name_scale,
    natural_width_mm,
)
from guideprint.markdown import parse_note
from guideprint.model import Image
from guideprint.normalize import normalize
from guideprint.typst_writer import Figure, MissingFigure, write_document

log = logging.getLogger(__name__)

PAPER_HEIGHT_MM = {"a4": 297.0, "a5": 210.0, "a3": 420.0, "us-letter": 279.4, "us-legal": 355.6}


@dataclass(frozen=True)
class RenderOptions:
    barcode_width_mm: float = 33.5
    paper: str = "a4"
    margin_mm: float = 14.0
    font: str = "Inter"
    font_size_pt: float = 12.0
    # A picture taller than this share of the text area is shrunk. Above about
    # half a page a picture no longer leaves room for its own step and the
    # steps around it, so the section it belongs to cannot stay on one page.
    max_image_height_fraction: float = 0.55
    default_dpi: float = 96.0
    lang: str | None = None
    # One page per level-1 section, as tall as the section needs, for reading
    # on a screen instead of on paper.
    digital: bool = False

    @property
    def max_image_height_mm(self) -> float:
        height = PAPER_HEIGHT_MM.get(self.paper, PAPER_HEIGHT_MM["a4"])
        footer_mm = 6.0
        text_area = height - 2 * self.margin_mm - footer_mm
        return text_area * self.max_image_height_fraction


def render_note(
    note: Note,
    output: Path,
    options: RenderOptions,
    *,
    build_dir: Path,
) -> Path:
    """Compile ``note`` into ``output``. ``build_dir`` receives the Typst
    sources and the pictures; it is left in place for inspection."""
    build_dir.mkdir(parents=True, exist_ok=True)
    doc = normalize(parse_note(note.path.read_text(encoding="utf-8"), note.path.stem))
    resolver = _FigureResolver(note, build_dir, options)
    source = write_document(
        doc,
        resolver.resolve,
        paper=options.paper,
        margin_mm=options.margin_mm,
        font=options.font,
        font_size_pt=options.font_size_pt,
        max_image_height_mm=options.max_image_height_mm,
        lang=options.lang,
        digital=options.digital,
    )
    package = resources.files("guideprint")
    (build_dir / "template.typ").write_text(
        package.joinpath("template.typ").read_text(encoding="utf-8"), encoding="utf-8"
    )
    main = build_dir / "main.typ"
    main.write_text(source, encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(package.joinpath("fonts")) as fonts:
        typst.compile(main, output=output, root=build_dir, font_paths=[fonts])
    log.info("wrote %s", output)
    return output


class _FigureResolver:
    def __init__(self, note: Note, build_dir: Path, options: RenderOptions) -> None:
        self._note = note
        self._build_dir = build_dir
        self._options = options
        self._cache: dict[str, Figure | MissingFigure] = {}

    def resolve(self, image: Image) -> Figure | MissingFigure:
        if image.path not in self._cache:
            self._cache[image.path] = self._resolve(image)
        return self._cache[image.path]

    def _resolve(self, image: Image) -> Figure | MissingFigure:
        relative = Path(image.path)
        source = (self._note.directory / relative).resolve()
        if not source.is_file() or not source.is_relative_to(self._note.directory.resolve()):
            log.warning("%s: attachment not found", image.path)
            return MissingFigure(relative.name)
        target = self._build_dir / "attachments" / relative.name
        if target.exists() and target.read_bytes() != source.read_bytes():
            target = target.with_stem(f"{target.stem}-{abs(hash(image.path)) % 10_000:04d}")
        written = ensure_typst_readable(source, target)
        typst_path = written.relative_to(self._build_dir).as_posix()
        info = inspect_image(written)
        if info is None:
            log.info("%s: size unknown, Typst decides", relative.name)
            return Figure(typst_path, None, None)
        width = self._target_width(info, relative.name)
        return Figure(typst_path, width, info.aspect, barcode=info.barcode)

    def _target_width(self, info: ImageInfo, name: str) -> float:
        if info.barcode:
            log.info("%s: barcode, %.1f mm", name, self._options.barcode_width_mm)
            return self._options.barcode_width_mm
        width = natural_width_mm(info, name, self._options.default_dpi)
        dpi = f"{info.dpi:g}" if info.dpi else f"{self._options.default_dpi:g} (assumed)"
        scale = name_scale(name)
        if scale != 1:
            dpi += f" x{scale:g}"
        log.info("%s: %dx%d px at %s dpi, %.1f mm", name, info.width_px, info.height_px, dpi, width)
        return width


def clean_build_dir(build_dir: Path) -> None:
    shutil.rmtree(build_dir, ignore_errors=True)
