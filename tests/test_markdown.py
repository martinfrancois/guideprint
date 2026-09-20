from guideprint.markdown import isolate_image_lines, parse_note, repair_strong
from guideprint.model import Image, ListBlock, Paragraph, Strong, Text, plain_text


def test_title_comes_from_front_matter() -> None:
    doc = parse_note('---\ntitle: "My guide"\n---\n\n# Something else\n', "file")
    assert doc.title == "My guide"
    assert doc.meta["title"] == "My guide"


def test_title_falls_back_to_first_heading_then_file_name() -> None:
    assert parse_note("# Heading\n\ntext\n", "file").title == "Heading"
    assert parse_note("just text\n", "file").title == "file"


def test_image_only_paragraph_becomes_image_block() -> None:
    doc = parse_note("![alt](<./attachments/a b.png>)\n", "f")
    assert doc.blocks == [Image(path="./attachments/a b.png", alt="alt")]


def test_bold_with_trailing_space_is_repaired() -> None:
    doc = parse_note("Do this **before **the program starts\n", "f")
    paragraph = doc.blocks[0]
    assert isinstance(paragraph, Paragraph)
    assert Strong([Text("before")]) in paragraph.children
    assert plain_text(paragraph.children) == "Do this before the program starts"


def test_empty_bold_and_glued_bold_are_repaired() -> None:
    assert plain_text(repair_strong("mit** **x")) == "mit x"
    assert repair_strong("20210821**_2**.csv") == [
        Text("20210821"),
        Strong([Text("_2")]),
        Text(".csv"),
    ]


def test_bold_repair_leaves_plain_text_alone() -> None:
    assert repair_strong("a * b ** c") == [Text("a * b ** c")]


def test_list_marker_directly_under_image_starts_a_list() -> None:
    markdown = "1. Step\n\n    ![x](<./a.png>)\n    2. Next\n\n    3. Last\n"
    doc = parse_note(markdown, "f")
    outer = doc.blocks[0]
    assert isinstance(outer, ListBlock)
    blocks = outer.items[0].blocks
    assert isinstance(blocks[1], Image)
    inner = blocks[2]
    assert isinstance(inner, ListBlock)
    assert inner.start == 2
    assert [plain_text(i.blocks[0].children) for i in inner.items] == ["Next", "Last"]  # type: ignore[union-attr]


def test_isolate_image_lines_skips_fenced_code() -> None:
    fenced = "```\n![x](a.png)\nnext\n```\n"
    assert isolate_image_lines(fenced) == fenced


def test_angle_bracket_placeholder_is_kept_as_text() -> None:
    doc = parse_note('setx PASSWORD "<password>"\n', "f")
    paragraph = doc.blocks[0]
    assert isinstance(paragraph, Paragraph)
    assert plain_text(paragraph.children) == 'setx PASSWORD "<password>"'


def test_table_rows_become_paragraphs() -> None:
    doc = parse_note("| a | b |\n|---|---|\n| 1 | 2 |\n", "f")
    # CommonMark preset has no tables, so the rows print as written.
    assert all(isinstance(block, Paragraph) for block in doc.blocks)
