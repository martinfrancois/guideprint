from pathlib import Path

from PIL import Image

from guideprint.images import (
    ImageInfo,
    ensure_typst_readable,
    inspect_image,
    looks_like_barcode,
    name_scale,
    natural_width_mm,
)
from tests.conftest import synthetic_barcode, synthetic_photo, synthetic_screenshot


def test_barcode_is_recognised() -> None:
    assert looks_like_barcode(synthetic_barcode())
    assert looks_like_barcode(synthetic_barcode(width=1600, height=560, seed=5))


def test_screenshot_and_photo_are_not_barcodes() -> None:
    assert not looks_like_barcode(synthetic_screenshot())
    assert not looks_like_barcode(synthetic_photo())


def test_portrait_and_tiny_pictures_are_not_barcodes() -> None:
    assert not looks_like_barcode(synthetic_barcode().rotate(90, expand=True))
    assert not looks_like_barcode(Image.new("L", (30, 8), 0))


def test_inspect_reads_dpi_only_when_trustworthy(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted.png"
    synthetic_screenshot().save(trusted, dpi=(154, 154))
    info = inspect_image(trusted)
    assert info == ImageInfo(400, 300, 154.0, False)

    jfif_default = tmp_path / "default.jpg"
    synthetic_screenshot().save(jfif_default, dpi=(72, 72))
    assert inspect_image(jfif_default) == ImageInfo(400, 300, None, False)


def test_inspect_returns_none_for_undecodable(tmp_path: Path) -> None:
    bogus = tmp_path / "x.png"
    bogus.write_bytes(b"not an image")
    assert inspect_image(bogus) is None


def test_natural_width_uses_dpi_then_css_default_then_retina_suffix() -> None:
    assert natural_width_mm(ImageInfo(384, 100, 192.0, False), "a.png") == 50.8
    assert natural_width_mm(ImageInfo(384, 100, None, False), "a.png") == 101.6
    assert natural_width_mm(ImageInfo(384, 100, None, False), "a@2x.png") == 50.8
    assert name_scale("shot@3x.png") == 3.0
    assert name_scale("shot.png") == 1.0


def test_unsupported_format_is_converted_to_png(tmp_path: Path) -> None:
    source = tmp_path / "shot.bmp"
    synthetic_screenshot().save(source)
    written = ensure_typst_readable(source, tmp_path / "out" / "shot.bmp")
    assert written.suffix == ".png"
    assert inspect_image(written) == ImageInfo(400, 300, None, False)


def test_supported_format_is_copied_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "shot.png"
    synthetic_screenshot().save(source)
    written = ensure_typst_readable(source, tmp_path / "out" / "shot.png")
    assert written.read_bytes() == source.read_bytes()
