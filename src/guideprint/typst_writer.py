"""Turn the normalized document tree into Typst source.

The layout rules that make the guide easy to follow live here. They are
written for the print variant; the digital variant has one page per part and
never hits a page end, so only the line-level rules show there:

* A paragraph followed by pictures is one unbreakable group, so a step's
  text never ends a page with its screenshot on the next one.
* A paragraph followed by a list sticks to that list, so an introduction such
  as "scan these barcodes:" never ends a page alone.
* A section (heading plus its content up to the next heading of the same or a
  higher level) that fits on one page is kept on one page, and so is a list
  item together with everything nested under it.
* A paragraph with manual line breaks keeps every line on one line, shrunk to
  fit if needed, so a list of commands copies out of the PDF line by line.
* A file path or URL stays on one line when it is narrower than the column.
* A barcode is placed beside its caption in a right-aligned column, and
  consecutive list items that contain barcodes stay on one page when they fit,
  because they are scanned in one go at the machine.
* Every level-1 heading after the first starts a new page.
* Headings stick to whatever follows them (Typst's default).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from guideprint.model import (
    Block,
    Code,
    CodeBlock,
    Document,
    Emph,
    Heading,
    Image,
    Inline,
    LineBreak,
    Link,
    ListBlock,
    ListItem,
    Paragraph,
    Strong,
    Text,
)

# Tokens that read badly when broken across lines: a quoted Windows path
# (which may contain spaces), a bare Windows path, a URL.
_NOWRAP_TOKEN = re.compile(
    r'"[A-Za-z]:\\[^"\n]*"'
    r"|[A-Za-z]:\\[^\s\"'<>|,;)]*[^\s\"'<>|,;).:]"
    r"|https?://[^\s<>\"')]+"
)
_COLUMN_WIDTH = "size.width"


@dataclass(frozen=True)
class Figure:
    """What the writer needs to place one picture. ``target_mm`` is the
    intended printed width; ``aspect`` is width divided by height. ``None``
    for both means "let Typst use the file's own size"."""

    typst_path: str
    target_mm: float | None
    aspect: float | None
    barcode: bool = False


@dataclass(frozen=True)
class MissingFigure:
    name: str


FigureResolver = Callable[[Image], Figure | MissingFigure]


def typst_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def text_run(text: str) -> str:
    """Plain text goes into the markup as a string expression. A string is
    never read as markup, so `=>`, `--`, `*` or `#` in a note print as typed."""
    return f"#{typst_string(text)}"


def mm(value: float) -> str:
    return f"{value:.2f}mm"


def write_document(
    doc: Document,
    resolve: FigureResolver,
    *,
    paper: str,
    margin_mm: float,
    font: str,
    font_size_pt: float,
    max_image_height_mm: float,
    lang: str | None,
    digital: bool = False,
) -> str:
    writer = _Writer(resolve, max_image_height_mm)
    header = [
        '#import "template.typ": *',
        "#show: guide.with(",
        f"  title: {typst_string(doc.title)},",
        f"  paper: {typst_string(paper)},",
        f"  margin: {mm(margin_mm)},",
        f"  font: {typst_string(font)},",
        f"  font-size: {font_size_pt:g}pt,",
        f"  lang: {typst_string(lang) if lang else 'none'},",
        f"  digital: {'true' if digital else 'false'},",
        ")",
        "",
    ]
    return "\n".join(header) + writer.sections(doc.blocks) + "\n"


class _Writer:
    def __init__(self, resolve: FigureResolver, max_image_height_mm: float) -> None:
        self._resolve = resolve
        self._max_height = max_image_height_mm
        self._seen_level1 = False

    def sections(self, blocks: list[Block]) -> str:
        """Top level: wrap every heading and its content in a `section`, with
        deeper headings nested as sections of their own."""
        parts: list[str] = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            if not isinstance(block, Heading):
                end = _run_end(blocks, index, lambda b: isinstance(b, Heading))
                parts.append(self.blocks(blocks[index:end]))
                index = end
                continue
            end = _run_end(blocks, index + 1, _closes_section(block.level))
            body = _join([self.heading(block), self.sections(blocks[index + 1 : end])])
            prefix = ""
            if block.level == 1:
                if self._seen_level1:
                    prefix = "#pagebreak(weak: true)\n"
                self._seen_level1 = True
            parts.append(f"{prefix}#section[\n{body}\n]")
            index = end
        return _join(parts)

    def blocks(self, blocks: list[Block]) -> str:
        parts: list[str] = []
        index = 0
        while index < len(blocks):
            block = blocks[index]
            following = blocks[index + 1 :]
            if isinstance(block, Paragraph):
                pictures = _leading_images(following)
                if len(pictures) == 1 and self.is_barcode(pictures[0]):
                    parts.append(self.barcode_row(block, pictures[0]))
                    index += 2
                    continue
                if pictures:
                    group = [self.paragraph(block), *map(self.figure, pictures)]
                    parts.append(f"#keep[\n{_join(group)}\n]")
                    index += 1 + len(pictures)
                    continue
                if following and isinstance(following[0], ListBlock):
                    parts.append(f"#lead[\n{self.paragraph(block)}\n]")
                else:
                    parts.append(self.paragraph(block))
            elif isinstance(block, Image):
                parts.append(f"#keep[\n{self.figure(block)}\n]")
            elif isinstance(block, ListBlock):
                parts.append(self.list_block(block))
            elif isinstance(block, CodeBlock):
                parts.append(f"#raw(block: true, {typst_string(block.text)})")
            elif isinstance(block, Heading):
                parts.append(self.heading(block))
            index += 1
        return _join(parts)

    def paragraph(self, paragraph: Paragraph) -> str:
        if any(isinstance(node, LineBreak) for node in paragraph.children):
            lines = ", ".join(
                f"[{self.inlines(line)}]" for line in _split_lines(paragraph.children)
            )
            return f"#lines({lines})"
        if _has_nowrap_token(paragraph.children):
            # `layout` hands the column width to every `nowrap` in the paragraph.
            return f"#layout(size => [{self.inlines(paragraph.children, nowrap=True)}])"
        return self.inlines(paragraph.children)

    def heading(self, heading: Heading) -> str:
        return f"#heading(level: {heading.level})[{self.inlines(heading.children)}]"

    def list_block(self, block: ListBlock) -> str:
        """Consecutive items that contain barcodes form one group that is kept
        on a page when it fits; the list is split around such a group and
        the numbering carries on."""
        parts: list[str] = []
        number = block.start
        for with_barcodes, run in itertools.groupby(block.items, key=self.contains_barcode):
            items = list(run)
            code = self.list_run(block.ordered, number, items)
            if with_barcodes and len(items) > 1:
                code = f"#together[\n{code}\n]"
            parts.append(code)
            number += len(items)
        return _join(parts)

    def list_run(self, ordered: bool, start: int, items: list[ListItem]) -> str:
        body = ",\n".join(f"[\n{self.item(item)}\n]" for item in items)
        if ordered:
            return f"#enum(start: {start}, tight: true,\n{body},\n)"
        return f"#list(tight: true,\n{body},\n)"

    def contains_barcode(self, item: ListItem) -> bool:
        return any(self.is_barcode(image) for image in _images_in(item.blocks))

    def is_barcode(self, image: Image) -> bool:
        figure = self._resolve(image)
        return isinstance(figure, Figure) and figure.barcode

    def barcode_row(self, caption: Paragraph, image: Image) -> str:
        figure = self._resolve(image)
        assert isinstance(figure, Figure) and figure.target_mm is not None
        path = typst_string(figure.typst_path)
        return f"#barcode-row([{self.inlines(caption.children)}], {path}, {mm(figure.target_mm)})"

    def item(self, item: ListItem) -> str:
        body = self.blocks(item.blocks)
        if any(isinstance(block, ListBlock) for block in item.blocks):
            return f"#together[\n{body}\n]"
        return body

    def figure(self, image: Image) -> str:
        figure = self._resolve(image)
        if isinstance(figure, MissingFigure):
            return f"#missing({typst_string(figure.name)})"
        path = typst_string(figure.typst_path)
        if figure.target_mm is None or figure.aspect is None:
            return f"#fig({path}, 100%, 1e9, {mm(self._max_height)})"
        return f"#fig({path}, {mm(figure.target_mm)}, {figure.aspect:.4f}, {mm(self._max_height)})"

    def inlines(self, nodes: list[Inline], *, nowrap: bool = False) -> str:
        out: list[str] = []
        for node in nodes:
            match node:
                case Text(text):
                    out.append(self.text(text, nowrap))
                case Strong(children):
                    out.append(f"#strong[{self.inlines(children, nowrap=nowrap)}]")
                case Emph(children):
                    out.append(f"#emph[{self.inlines(children, nowrap=nowrap)}]")
                case Code(text):
                    out.append(f"#raw({typst_string(text)})")
                case Link(href, children):
                    link = f"#link({typst_string(href)})[{self.inlines(children)}]"
                    out.append(_nowrap(link) if nowrap else link)
                case LineBreak():
                    out.append("#linebreak()")
        return "".join(out)

    def text(self, text: str, nowrap: bool) -> str:
        if not nowrap:
            return text_run(text)
        out: list[str] = []
        position = 0
        for match in _NOWRAP_TOKEN.finditer(text):
            if match.start() > position:
                out.append(text_run(text[position : match.start()]))
            out.append(_nowrap(text_run(match.group(0))))
            position = match.end()
        if position < len(text):
            out.append(text_run(text[position:]))
        return "".join(out)


def _closes_section(level: int) -> Callable[[Block], bool]:
    return lambda b: isinstance(b, Heading) and b.level <= level


def _run_end(blocks: list[Block], start: int, stop: Callable[[Block], bool]) -> int:
    """Index of the first block at or after ``start`` for which ``stop`` holds."""
    index = start
    while index < len(blocks) and not stop(blocks[index]):
        index += 1
    return index


def _nowrap(code: str) -> str:
    return f"#nowrap({_COLUMN_WIDTH})[{code}]"


def _has_nowrap_token(inlines: list[Inline]) -> bool:
    for node in inlines:
        match node:
            case Text(text):
                if _NOWRAP_TOKEN.search(text):
                    return True
            case Link():
                return True
            case Strong(children) | Emph(children):
                if _has_nowrap_token(children):
                    return True
    return False


def _split_lines(inlines: list[Inline]) -> list[list[Inline]]:
    lines: list[list[Inline]] = [[]]
    for node in inlines:
        if isinstance(node, LineBreak):
            lines.append([])
        else:
            lines[-1].append(node)
    return [_strip(line) for line in lines if any(not _blank(node) for node in line)]


def _strip(line: list[Inline]) -> list[Inline]:
    out = list(line)
    if out and isinstance(out[0], Text):
        out[0] = Text(out[0].text.lstrip())
    if out and isinstance(out[-1], Text):
        out[-1] = Text(out[-1].text.rstrip())
    return out


def _blank(node: Inline) -> bool:
    return isinstance(node, Text) and not node.text.strip()


def _images_in(blocks: list[Block]) -> Iterator[Image]:
    for block in blocks:
        if isinstance(block, Image):
            yield block
        elif isinstance(block, ListBlock):
            for item in block.items:
                yield from _images_in(item.blocks)


def _leading_images(blocks: list[Block]) -> list[Image]:
    pictures: list[Image] = []
    for block in blocks:
        if not isinstance(block, Image):
            break
        pictures.append(block)
    return pictures


def _join(parts: list[str]) -> str:
    return "\n\n".join(part for part in parts if part)
