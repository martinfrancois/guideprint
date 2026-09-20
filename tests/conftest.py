import random
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "sample-guide"


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE_DIR


@pytest.fixture
def example_zip(tmp_path: Path) -> Path:
    """The example note packed the way Notesnook exports it."""
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXAMPLE_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(EXAMPLE_DIR).as_posix())
    return archive


def synthetic_barcode(width: int = 600, height: int = 200, seed: int = 1) -> Image.Image:
    """Black bars of random width on white, with a number printed underneath
    like the labels a barcode generator adds."""
    rng = random.Random(seed)
    im = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(im)
    x = 20
    ink = True
    bar_bottom = int(height * 0.7)
    while x < width - 20:
        w = rng.randint(3, 12)
        if ink:
            draw.rectangle((x, 10, x + w - 1, bar_bottom), fill=0)
        x += w
        ink = not ink
    draw.text((width // 2, int(height * 0.85)), "99077401(47)", fill=0, anchor="mm", font_size=24)
    return im


def synthetic_screenshot(width: int = 400, height: int = 300) -> Image.Image:
    """A dialog-like picture: frame, title bar and lines of text."""
    im = Image.new("RGB", (width, height), (240, 240, 240))
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, width - 1, 28), fill=(30, 60, 120))
    draw.text((8, 6), "Settings", fill="white", font_size=16)
    for row in range(6):
        y = 50 + row * 36
        draw.rectangle((16, y, 30, y + 14), outline="black")
        draw.text((40, y - 2), f"Option {row + 1}: value {row * 7}", fill="black", font_size=16)
    draw.rectangle((width - 110, height - 40, width - 20, height - 12), outline="black")
    draw.text((width - 65, height - 26), "OK", fill="black", anchor="mm", font_size=16)
    return im


def synthetic_photo(width: int = 800, height: int = 600, seed: int = 2) -> Image.Image:
    """Smooth gradient with noise, the kind of picture a camera produces."""
    rng = random.Random(seed)
    im = Image.new("RGB", (width, height))
    px = im.load()
    assert px is not None
    for y in range(height):
        for x in range(width):
            base = int(80 + 120 * x / width)
            px[x, y] = (base + rng.randint(-20, 20), base // 2 + rng.randint(-20, 20), 90)
    return im


def write_note(directory: Path, markdown: str, images: dict[str, Image.Image]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "attachments").mkdir(exist_ok=True)
    for name, image in images.items():
        image.save(directory / "attachments" / name)
    note = directory / "note.md"
    note.write_text(markdown, encoding="utf-8")
    return note
