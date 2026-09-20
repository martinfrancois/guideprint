from itertools import pairwise
from pathlib import Path

import pikepdf
import pymupdf
import pytest

from guideprint.cli import main, slugify
from guideprint.export import Note, load_export
from guideprint.markdown import parse_note
from guideprint.model import Heading, plain_text
from guideprint.normalize import normalize
from guideprint.render import RenderOptions, render_note
from tests.conftest import synthetic_barcode, synthetic_screenshot, write_note

BARCODE_MM = 33.5
PT_PER_MM = 72 / 25.4


def _title_and_parts(note: Note) -> tuple[str, list[str]]:
    """The note's title and the level-1 headings after the first, which are
    the parts that start a new page. Read from the note, so the tests do not
    care what language the example is written in."""
    doc = normalize(parse_note(note.path.read_text(encoding="utf-8"), note.path.stem))
    level_one = [b for b in doc.blocks if isinstance(b, Heading) and b.level == 1]
    headings = [plain_text(b.children) for b in level_one]
    return doc.title, headings[1:]


def _images_by_page(pdf: Path) -> list[list[tuple[int, int, float, float]]]:
    """Per page: (pixel width, pixel height, placed width mm, placed height mm)."""
    out = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            placed = []
            for entry in page.get_images(full=True):
                for rect in page.get_image_rects(entry[0]):
                    placed.append(
                        (entry[2], entry[3], rect.width / PT_PER_MM, rect.height / PT_PER_MM)
                    )
            out.append(placed)
    return out


def _page_texts(pdf: Path) -> list[str]:
    with pymupdf.open(pdf) as doc:
        return [page.get_text() for page in doc]


def test_example_builds_with_barcodes_at_scanner_size(example_dir: Path, tmp_path: Path) -> None:
    note = load_export(example_dir, tmp_path)[0]
    pdf = render_note(note, tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "build")
    pages = _images_by_page(pdf)
    barcodes = [img for page in pages for img in page if abs(img[2] - BARCODE_MM) < 0.1]
    assert len(barcodes) == 12
    assert all(2 < px_w / px_h < 4 for px_w, px_h, _, _ in barcodes)
    texts = _page_texts(pdf)
    title, parts = _title_and_parts(note)
    assert title in texts[0]
    for part in parts:
        assert any(text.lstrip().startswith(part) for text in texts), "new page per part"


def test_example_screenshots_print_at_natural_size(example_dir: Path, tmp_path: Path) -> None:
    note = load_export(example_dir, tmp_path)[0]
    pdf = render_note(note, tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "build")
    placed = {img[0:2]: img[2] for page in _images_by_page(pdf) for img in page}
    # screenshot-05.jpg is 332x212 px without density, so 96 px per inch.
    assert placed[(332, 212)] == pytest.approx(332 / 96 * 25.4, abs=0.1)
    # screenshot-03@2x.png is 902 px wide at twice the logical resolution, but
    # taller than the page allows, so the height cap decides its width.
    natural_mm = 902 / 192 * 25.4
    capped_mm = RenderOptions().max_image_height_mm * 902 / 1388
    assert capped_mm < natural_mm
    assert placed[(902, 1388)] == pytest.approx(capped_mm, abs=0.1)


def test_caption_and_picture_share_a_page(tmp_path: Path) -> None:
    filler = "\n\n".join(
        f"{n}. Filler step number {n} with enough words to fill a line." for n in range(1, 40)
    )
    markdown = (
        f"# Guide\n\n{filler}\n\n"
        "40. Look at this dialog:\n\n    - \n\n    ![shot](<./attachments/shot.png>)\n\n"
        "41. Then scan:\n\n    - \n\n    ![code](<./attachments/code.png>)\n"
    )
    note = write_note(
        tmp_path / "note",
        markdown,
        {"shot.png": synthetic_screenshot(400, 900), "code.png": synthetic_barcode()},
    )
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    texts = _page_texts(pdf)
    pages = _images_by_page(pdf)
    assert len(texts) >= 2
    for caption, size in (("Look at this dialog:", (400, 900)), ("Then scan:", (600, 200))):
        page_of_caption = next(i for i, text in enumerate(texts) if caption in text)
        assert any(img[0:2] == size for img in pages[page_of_caption]), caption


def test_barcodes_line_up_in_one_column_with_room_between_them(tmp_path: Path) -> None:
    filler = "\n\n".join(f"Paragraph {n} of filler text." for n in range(1, 21))
    steps = "\n\n".join(
        f"- Barcode {n}\n\n- \n\n![b{n}](<./attachments/b{n}.png>)" for n in range(1, 5)
    )
    markdown = (
        f"# Guide\n\n{filler}\n\n1. Scan these:\n\n"
        + "\n".join("    " + line for line in steps.splitlines())
        + "\n\n2. And these:\n\n"
        + "\n".join("    " + line for line in steps.splitlines())
        + "\n"
    )
    images = {f"b{n}.png": synthetic_barcode(seed=n) for n in range(1, 5)}
    note = write_note(tmp_path / "note", markdown, images)
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    pages = _images_by_page(pdf)
    texts = _page_texts(pdf)
    with pymupdf.open(pdf) as doc:
        rects = [
            (i, r)
            for i, page in enumerate(doc)
            for entry in page.get_images(full=True)
            for r in page.get_image_rects(entry[0])
        ]
    assert len(rects) == 8
    assert len({i for i, _ in rects}) == 1, "both barcode steps on one page"
    page_index = rects[0][0]
    assert "Scan these:" in texts[page_index] and "And these:" in texts[page_index]
    # Paragraph 20 introduces the list, so it moves along with the group.
    assert "Paragraph 19" not in texts[page_index], "the group moved to a fresh page as a whole"
    assert len({round(r.x0, 1) for _, r in rects}) == 1, "one column"
    ordered = sorted((r for _, r in rects), key=lambda r: r.y0)
    for above, below in pairwise(ordered):
        assert (below.y0 - above.y1) / PT_PER_MM >= 5
    assert pages[page_index][0][2] == pytest.approx(BARCODE_MM, abs=0.1)


def test_intro_line_is_not_stranded_before_a_page_break(tmp_path: Path) -> None:
    filler = "\n\n".join(
        f"Paragraph {n} of filler text that takes up one line." for n in range(1, 41)
    )
    steps = "\n\n".join(
        f"- Barcode {n}\n\n- \n\n![b{n}](<./attachments/b{n}.png>)" for n in range(1, 4)
    )
    markdown = f"# Guide\n\n{filler}\n\nScan all of these barcodes now:\n\n{steps}\n"
    images = {f"b{n}.png": synthetic_barcode(seed=n) for n in range(1, 4)}
    note = write_note(tmp_path / "note", markdown, images)
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    texts = _page_texts(pdf)
    intro_page = next(i for i, text in enumerate(texts) if "Scan all of these" in text)
    assert "Barcode 1" in texts[intro_page]


def test_short_section_moves_to_a_fresh_page_as_a_whole(tmp_path: Path) -> None:
    filler = "\n\n".join(f"Paragraph {n} of filler text." for n in range(1, 30))
    markdown = (
        f"# Guide\n\n## Long part\n\n{filler}\n\n"
        "## Short part\n\n1. Plug in\n\n2. Look:\n\n"
        "    - \n\n    ![shot](<./attachments/shot.png>)\n\n3. Done\n"
    )
    note = write_note(tmp_path / "note", markdown, {"shot.png": synthetic_screenshot(400, 700)})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    texts = _page_texts(pdf)
    assert len(texts) == 2
    assert "Paragraph 29" in texts[0] and "Short part" not in texts[0]
    assert all(part in texts[1] for part in ("Short part", "Plug in", "Look:", "Done"))


def test_section_longer_than_a_page_still_flows(tmp_path: Path) -> None:
    filler = "\n\n".join(f"Paragraph {n} of filler text." for n in range(1, 120))
    note = write_note(tmp_path / "note", f"# Guide\n\n## Long part\n\n{filler}\n", {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    texts = _page_texts(pdf)
    assert len(texts) >= 3
    assert "Paragraph 1 " in texts[0]


def test_hand_broken_lines_copy_out_one_per_line(tmp_path: Path) -> None:
    long = 'setx URL "jdbc:postgresql://' + "x" * 70 + '.example.com:5432/db"'
    first, last = '# Guide\n\n1. Run:\n\n    - setx A "1"  \n', '        setx B "2"\n'
    markdown = first + f"        {long}  \n" + last
    note = write_note(tmp_path / "note", markdown, {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    lines = [line for line in _page_texts(pdf)[0].splitlines() if "setx" in line]
    # The bullet belongs to the list item the note put the commands in.
    assert lines == ['• setx A "1"', long, 'setx B "2"']


def test_hand_broken_lines_are_separate_paragraphs_in_the_tag_tree(tmp_path: Path) -> None:
    """Adobe Reader copies by structure tags: lines inside one paragraph tag
    come out as one line, so each hand-broken line needs a tag of its own."""
    markdown = "# Guide\n\n1. Run:\n\n    - setx A 1  \n        setx B 2  \n        setx C 3\n"
    note = write_note(tmp_path / "note", markdown, {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    with pikepdf.open(pdf) as doc:
        root = doc.Root.StructTreeRoot
        assert isinstance(root, pikepdf.Dictionary)
        bodies = [n for n in _struct_nodes(root) if str(n.get("/S")) == "/LBody"]
    paragraphs_per_body = [
        sum(1 for kid in _kids(body) if str(kid.get("/S")) == "/P") for body in bodies
    ]
    assert 3 in paragraphs_per_body


def _kids(node: pikepdf.Dictionary) -> list[pikepdf.Dictionary]:
    kids = node.get("/K")
    if isinstance(kids, pikepdf.Dictionary):
        return [kids]
    if isinstance(kids, pikepdf.Array):
        return [kid for kid in kids if isinstance(kid, pikepdf.Dictionary)]
    return []


def _struct_nodes(node: pikepdf.Dictionary) -> list[pikepdf.Dictionary]:
    out = [node]
    for kid in _kids(node):
        out.extend(_struct_nodes(kid))
    return out


def test_path_moves_to_the_next_line_whole_but_an_overlong_one_still_wraps(tmp_path: Path) -> None:
    path = "C:\\Dropbox\\Club 2021\\Data\\20210821.csv"
    overlong = "C:\\" + "\\".join(f"Folder {n:02d}" for n in range(30)) + "\\file.csv"
    markdown = (
        "# Guide\n\n"
        + "\n\n".join(f'{prefix} the path: "{path}" and on' for prefix in _PREFIXES)
        + f'\n\nLong path: "{overlong}" end\n'
    )
    note = write_note(tmp_path / "note", markdown, {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    with pymupdf.open(pdf) as doc:
        page = doc[0]
        lines = [
            "".join(span["text"] for span in line["spans"])
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
        ]
        right_edge = page.rect.width - 14 / 25.4 * 72
        assert all(block[2] <= right_edge + 0.5 for block in page.get_text("blocks"))
    assert sum(1 for line in lines if f'"{path}"' in line) == len(_PREFIXES)
    assert not any(overlong in line for line in lines), "an overlong path wraps"
    assert any("Folder 00" in line for line in lines)


# Prefixes of different lengths push the path to different positions in the
# line, so at least one of them would have split it without the rule.
_PREFIXES = [("Text " * n).strip() for n in range(1, 12)]


def test_non_ascii_text_survives_to_the_pdf(tmp_path: Path) -> None:
    # German umlauts and a few other non-ASCII characters, as a guide in
    # another language would contain them.
    sample = "Grüße aus Zürich: Ärger, Öl, Übung, ß, 5 €, naïve, señor"
    note = write_note(tmp_path / "note", f"# Guide\n\n{sample}\n", {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    assert sample in _page_texts(pdf)[0]


def test_missing_attachment_still_builds(tmp_path: Path) -> None:
    note = write_note(tmp_path / "note", "# G\n\n![gone](<./attachments/gone.png>)\n", {})
    pdf = render_note(Note(note), tmp_path / "out.pdf", RenderOptions(), build_dir=tmp_path / "b")
    assert "missing image: gone.png" in _page_texts(pdf)[0]


def test_digital_variant_has_one_page_per_part(example_dir: Path, tmp_path: Path) -> None:
    note = load_export(example_dir, tmp_path)[0]
    options = RenderOptions(digital=True)
    pdf = render_note(note, tmp_path / "d.pdf", options, build_dir=tmp_path / "build")
    with pymupdf.open(pdf) as doc:
        heights = [page.rect.height for page in doc]
        firsts = [page.get_text().strip().splitlines()[0] for page in doc]
        widths = {round(page.rect.width) for page in doc}
    title, parts = _title_and_parts(note)
    assert firsts == [title, *parts]
    assert all(height > 842 for height in heights), "taller than A4"
    assert widths == {595}, "still as wide as A4"


def test_cli_writes_both_variants_by_default(example_zip: Path, tmp_path: Path) -> None:
    out = tmp_path / "guide.pdf"
    assert main([str(example_zip), "-o", str(out)]) == 0
    written = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert written == ["guide-digital.pdf", "guide-print.pdf"]


def test_cli_builds_from_zip(
    example_zip: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "guide.pdf"
    assert main([str(example_zip), "-o", str(out), "--variant", "print"]) == 0
    written = tmp_path / "guide-print.pdf"
    assert written.exists()
    assert capsys.readouterr().out.strip() == str(written)


def test_cli_writes_one_pdf_per_note_into_a_directory(tmp_path: Path) -> None:
    export = tmp_path / "export"
    write_note(export / "a", "---\ntitle: First note\n---\n\ntext\n", {})
    write_note(export / "b", "---\ntitle: Second / note\n---\n\ntext\n", {})
    out = tmp_path / "pdfs"
    assert main([str(export), "-o", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "First-note-digital.pdf",
        "First-note-print.pdf",
        "Second-note-digital.pdf",
        "Second-note-print.pdf",
    ]


def test_cli_rejects_unknown_input(tmp_path: Path) -> None:
    bogus = tmp_path / "x.txt"
    bogus.write_text("nope")
    assert main([str(bogus)]) == 2


def test_slugify() -> None:
    assert slugify("Range guide 2021") == "Range-guide-2021"
    assert slugify("  ///  ") == "note"
