"""Decide how large each picture is printed.

Two kinds of pictures occur in a guide and they need opposite treatment:

* A barcode must be printed at a fixed physical width so a scanner reads it.
  Barcodes are recognised from the pixels, not from file names, because
  Notesnook renames attachments to a hash prefix.
* Everything else (screenshots, photos) is printed at its natural size, taken
  from the DPI metadata when present and from the CSS convention of 96 px per
  inch otherwise. Retina screenshots carry an ``@2x`` suffix in the file name
  and are halved accordingly. The Typst side then clamps the width to the
  column and the height to a fraction of the page.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

MM_PER_INCH = 25.4
DEFAULT_DPI = 96.0
# JPEGs without a real density carry values like 1 or 72 in the JFIF header.
MIN_TRUSTED_DPI = 100.0
TYPST_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"})

_SCALE_SUFFIX = re.compile(r"@(\d+)x(?=\.[^.]+$)")


@dataclass(frozen=True)
class ImageInfo:
    width_px: int
    height_px: int
    dpi: float | None
    barcode: bool

    @property
    def aspect(self) -> float:
        return self.width_px / self.height_px


def inspect_image(path: Path) -> ImageInfo | None:
    """Read pixel size, density and barcode-ness. ``None`` when Pillow cannot
    decode the file (SVG for example), in which case the caller falls back to
    Typst's own sizing."""
    try:
        with Image.open(path) as im:
            im.load()
            dpi = _trusted_dpi(im.info.get("dpi"))
            return ImageInfo(im.width, im.height, dpi, looks_like_barcode(im))
    except (UnidentifiedImageError, OSError):
        return None


def _trusted_dpi(raw: object) -> float | None:
    if not isinstance(raw, tuple) or not raw:
        return None
    try:
        value = float(raw[0])
    except (TypeError, ValueError):
        return None
    # PNG stores pixels per metre, which comes back as 154.0002 for 154.
    return round(value, 1) if value >= MIN_TRUSTED_DPI else None


def name_scale(name: str) -> float:
    """``shot@2x.png`` was captured at twice the logical resolution."""
    match = _SCALE_SUFFIX.search(name)
    return float(match.group(1)) if match else 1.0


def natural_width_mm(info: ImageInfo, name: str, default_dpi: float = DEFAULT_DPI) -> float:
    dpi = (info.dpi or default_dpi) * name_scale(name)
    return info.width_px / dpi * MM_PER_INCH


# Barcode detection samples three horizontal lines through the upper part of
# the picture, where a 1D barcode has its bars and a printed label does not
# interfere. Bars are vertical, so the lines agree almost everywhere; a
# screenshot or photo changes from line to line.
_SAMPLE_ROWS = (0.2, 0.3, 0.4)
_MIN_TRANSITIONS = 12
_MIN_AGREEMENT = 0.97
_INK_RANGE = (0.2, 0.8)
_MAX_SAMPLE_WIDTH = 1200


def looks_like_barcode(im: Image.Image) -> bool:
    gray = im.convert("L")
    if gray.width < 40 or gray.height < 10 or gray.width <= gray.height:
        return False
    if gray.width > _MAX_SAMPLE_WIDTH:
        height = max(10, round(gray.height * _MAX_SAMPLE_WIDTH / gray.width))
        gray = gray.resize((_MAX_SAMPLE_WIDTH, height))
    width = gray.width
    rows = [_row_bits(gray, int(gray.height * fraction)) for fraction in _SAMPLE_ROWS]
    for row in rows:
        ink = sum(row) / width
        if not _INK_RANGE[0] <= ink <= _INK_RANGE[1]:
            return False
        if _transitions(row) < _MIN_TRANSITIONS:
            return False
    for first, second in ((0, 1), (1, 2), (0, 2)):
        agreement = sum(a == b for a, b in zip(rows[first], rows[second], strict=True)) / width
        if agreement < _MIN_AGREEMENT:
            return False
    return True


def _row_bits(gray: Image.Image, y: int) -> list[int]:
    row = gray.crop((0, y, gray.width, y + 1)).tobytes()
    return [1 if value < 128 else 0 for value in row]


def _transitions(bits: list[int]) -> int:
    return sum(a != b for a, b in pairwise(bits))


def ensure_typst_readable(source: Path, target: Path) -> Path:
    """Copy ``source`` to ``target``, converting formats Typst cannot open
    (HEIC, BMP, TIFF, ...) to PNG. Returns the path actually written."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in TYPST_IMAGE_SUFFIXES:
        target.write_bytes(source.read_bytes())
        return target
    converted = target.with_suffix(".png")
    try:
        with Image.open(source) as im:
            im.save(converted, format="PNG", dpi=im.info.get("dpi"))
    except (UnidentifiedImageError, OSError):
        log.warning("cannot decode %s, copying as-is", source.name)
        target.write_bytes(source.read_bytes())
        return target
    log.info("%s: converted to PNG for Typst", source.name)
    return converted
