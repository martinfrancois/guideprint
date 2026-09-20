from guideprint.markdown import parse_note
from guideprint.model import Document, Heading, Image, ListBlock, ListItem, Paragraph, Text
from guideprint.normalize import normalize, normalize_blocks

NOTESNOOK_PHOTO_STEP = """\
- Open the cover:

    -\x20

    ![photo](<./attachments/photo.jpg>)

- Plug in the cable
"""

NOTESNOOK_BARCODE_LIST = """\
1. Scan these barcodes:

    - "**User number => On**"

    -\x20

    ![b1](<./attachments/b1.jpg>)
    - "**Repeat => Off**"

    -\x20

    ![b2](<./attachments/b2.jpg>)

2. Done
"""


def test_image_after_empty_bullet_lands_in_the_step() -> None:
    doc = normalize(parse_note(NOTESNOOK_PHOTO_STEP, "f"))
    outer = doc.blocks[0]
    assert isinstance(outer, ListBlock)
    assert len(outer.items) == 2
    first = outer.items[0].blocks
    assert isinstance(first[0], Paragraph)
    assert first[1] == Image(path="./attachments/photo.jpg", alt="photo")
    assert len(first) == 2


def test_barcode_list_is_one_list_with_an_image_per_item() -> None:
    doc = normalize(parse_note(NOTESNOOK_BARCODE_LIST, "f"))
    outer = doc.blocks[0]
    assert isinstance(outer, ListBlock)
    step = outer.items[0].blocks
    assert isinstance(step[0], Paragraph)
    inner = step[1]
    assert isinstance(inner, ListBlock)
    assert len(step) == 2
    assert [type(b).__name__ for item in inner.items for b in item.blocks] == [
        "Paragraph",
        "Image",
        "Paragraph",
        "Image",
    ]


def test_title_heading_is_dropped_once() -> None:
    doc = Document(
        title="Guide",
        blocks=[
            Heading(1, [Text("Guide")]),
            Heading(1, [Text("Part one")]),
            Heading(1, [Text("Guide")]),
        ],
    )
    assert [b.children[0].text for b in normalize(doc).blocks] == ["Part one", "Guide"]  # type: ignore[union-attr]


def test_empty_lists_disappear() -> None:
    blocks = normalize_blocks([ListBlock(ordered=False, items=[ListItem([]), ListItem([])])])
    assert blocks == []


def test_lists_of_different_kind_are_not_merged() -> None:
    blocks = normalize_blocks(
        [
            ListBlock(ordered=True, items=[ListItem([Paragraph([Text("a")])])]),
            ListBlock(ordered=False, items=[ListItem([Paragraph([Text("b")])])]),
        ]
    )
    assert len(blocks) == 2
