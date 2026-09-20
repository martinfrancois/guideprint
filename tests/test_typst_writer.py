from guideprint.model import (
    Code,
    Document,
    Heading,
    Image,
    Link,
    ListBlock,
    ListItem,
    Paragraph,
    Strong,
    Text,
)
from guideprint.typst_writer import Figure, MissingFigure, text_run, typst_string, write_document


def _write(blocks: list) -> str:  # type: ignore[type-arg]
    def resolve(image: Image) -> Figure | MissingFigure:
        if image.path == "missing.png":
            return MissingFigure("missing.png")
        barcode = image.path.startswith("barcode")
        return Figure(f"attachments/{image.path}", 33.5, 2.8, barcode=barcode)

    return write_document(
        Document(title="T", blocks=blocks),
        resolve,
        paper="a4",
        margin_mm=14,
        font="Inter",
        font_size_pt=12,
        max_image_height_mm=170,
        lang=None,
    )


def test_text_is_a_string_expression_so_markup_never_applies() -> None:
    assert text_run('a "=>" b\\c') == '#"a \\"=>\\" b\\\\c"'
    assert typst_string("line\nbreak") == '"line\\nbreak"'


def test_caption_and_picture_are_one_unbreakable_group() -> None:
    out = _write([Paragraph([Text("Open the cover:")]), Image("photo.jpg")])
    expected = (
        '#keep[\n#"Open the cover:"\n\n#fig("attachments/photo.jpg", 33.50mm, 2.8000, 170.00mm)\n]'
    )
    assert expected in out


def test_paragraph_before_list_sticks_to_it() -> None:
    out = _write(
        [
            Paragraph([Text("Scan:")]),
            ListBlock(ordered=False, items=[ListItem([Paragraph([Text("one")])])]),
        ]
    )
    assert '#lead[\n#"Scan:"\n]' in out
    assert '#list(tight: true,\n[\n#"one"\n],\n)' in out


def test_second_level_one_heading_starts_a_new_page() -> None:
    out = _write([Heading(1, [Text("A")]), Paragraph([Text("x")]), Heading(1, [Text("B")])])
    assert out.count("#pagebreak(weak: true)") == 1
    assert '#pagebreak(weak: true)\n#section[\n#heading(level: 1)[#"B"]\n]' in out


def test_headings_nest_into_sections() -> None:
    out = _write(
        [
            Paragraph([Text("intro")]),
            Heading(1, [Text("A")]),
            Heading(2, [Text("A.1")]),
            Paragraph([Text("x")]),
            Heading(2, [Text("A.2")]),
            Paragraph([Text("y")]),
            Heading(1, [Text("B")]),
        ]
    )
    expected = (
        '#"intro"\n\n'
        '#section[\n#heading(level: 1)[#"A"]\n\n'
        '#section[\n#heading(level: 2)[#"A.1"]\n\n#"x"\n]\n\n'
        '#section[\n#heading(level: 2)[#"A.2"]\n\n#"y"\n]\n]\n\n'
        '#pagebreak(weak: true)\n#section[\n#heading(level: 1)[#"B"]\n]'
    )
    assert expected in out


def test_item_with_sub_items_is_kept_together_when_it_fits() -> None:
    inner = ListBlock(ordered=False, items=[ListItem([Paragraph([Text("sub")])])])
    out = _write([ListBlock(ordered=True, items=[ListItem([Paragraph([Text("step")]), inner])])])
    assert '[\n#together[\n#lead[\n#"step"\n]\n\n#list(tight: true,\n[\n#"sub"\n],\n)\n]\n]' in out


def test_barcode_sits_beside_its_caption() -> None:
    out = _write([Paragraph([Text("Scan")]), Image("barcode1.png")])
    assert '#barcode-row([#"Scan"], "attachments/barcode1.png", 33.50mm)' in out
    assert "#keep" not in out


def test_consecutive_barcode_steps_form_one_group_and_numbering_carries_on() -> None:
    def step(text: str, picture: str) -> ListItem:
        sub = ListBlock(ordered=False, items=[ListItem([Paragraph([Text("c")]), Image(picture)])])
        return ListItem([Paragraph([Text(text)]), sub])

    out = _write(
        [
            ListBlock(
                ordered=True,
                items=[
                    step("plain", "shot.png"),
                    step("scan a", "barcode1.png"),
                    step("scan b", "barcode2.png"),
                    step("plain again", "shot.png"),
                ],
            )
        ]
    )
    assert out.count("#enum(start: 1, tight: true,") == 1
    assert "#together[\n#enum(start: 2, tight: true," in out
    assert "#enum(start: 4, tight: true," in out


def test_ordered_list_keeps_its_start_number() -> None:
    out = _write([ListBlock(ordered=True, start=3, items=[ListItem([Paragraph([Text("c")])])])])
    assert "#enum(start: 3, tight: true," in out


def test_inline_markup() -> None:
    out = _write(
        [Paragraph([Strong([Text("b")]), Code("x=1"), Link("https://e.x/?a=1", [Text("l")])])]
    )
    expected = '#strong[#"b"]#raw("x=1")#nowrap(size.width)[#link("https://e.x/?a=1")[#"l"]]'
    assert f"#layout(size => [{expected}])" in out


def test_manual_line_breaks_keep_one_line_per_line() -> None:
    from guideprint.model import LineBreak

    out = _write([Paragraph([Text("setx A 1"), LineBreak(), Text(" setx B 2 "), LineBreak()])])
    assert '#lines([#"setx A 1"], [#"setx B 2"])' in out


def test_windows_paths_and_urls_are_nowrap_tokens_with_the_column_width() -> None:
    out = _write([Paragraph([Text('path "C:\\Dropbox\\Club 2021\\x.csv" or C:\\Data.')])])
    assert out.startswith("#layout(size => [", out.index("#layout"))
    assert '#nowrap(size.width)[#"\\"C:\\\\Dropbox\\\\Club 2021\\\\x.csv\\""]' in out
    assert '#nowrap(size.width)[#"C:\\\\Data"]#"."' in out
    plain = _write([Paragraph([Text("no path here")])])
    assert "#layout" not in plain and "#nowrap" not in plain


def test_links_are_nowrap_tokens() -> None:
    out = _write([Paragraph([Text("see "), Link("https://e.x/a", [Text("https://e.x/a")])])])
    assert '#nowrap(size.width)[#link("https://e.x/a")[#"https://e.x/a"]]' in out


def test_missing_attachment_gets_a_placeholder() -> None:
    out = _write([Image("missing.png")])
    assert '#missing("missing.png")' in out
