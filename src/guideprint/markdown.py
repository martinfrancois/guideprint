"""Parse Notesnook's markdown flavour into the document tree.

Notesnook exports CommonMark with a YAML front matter block. Only the block
types a note can contain are mapped; anything else is flattened to its text so
an unexpected construct degrades to readable output rather than an error.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote

import frontmatter
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

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

log = logging.getLogger(__name__)


def parse_note(source: str, fallback_title: str) -> Document:
    """Parse one note. The title comes from the front matter, else the first
    level-1 heading, else ``fallback_title``."""
    post = frontmatter.loads(source)
    meta: dict[str, Any] = dict(post.metadata)
    tree = SyntaxTreeNode(MarkdownIt("commonmark").parse(isolate_image_lines(post.content)))
    blocks = _blocks(tree)
    title = str(meta.get("title") or _first_heading(blocks) or fallback_title)
    return Document(title=title, blocks=blocks, meta=meta)


_IMAGE_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def isolate_image_lines(markdown: str) -> str:
    """Put a blank line after every line that holds nothing but an image.

    Notesnook writes the next list item directly under such a line. CommonMark
    then reads "2. next step" as a lazy continuation of the image's paragraph,
    which prints the marker as text and leaves the image under the wrong step.
    Fenced code is left alone.
    """
    out: list[str] = []
    lines = markdown.split("\n")
    in_fence = False
    for index, line in enumerate(lines):
        out.append(line)
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not _IMAGE_LINE.match(line):
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if following.strip():
            out.append("")
    return "\n".join(out)


# Notesnook writes a bold run that ends in a space as `**before **`, an empty
# one as `** **`, and a bold run glued to a word as `20210821**\_2**.csv`.
# CommonMark rejects all three, so the asterisks survive parsing as literal
# text. Only unmatched pairs reach this point, which is what makes repairing
# them in the parsed text safe.
_BROKEN_STRONG = re.compile(r"\*\*(\S(?:[^*]*?\S)?)([ \t]*)\*\*")
_EMPTY_STRONG = re.compile(r"\*\*[ \t]+\*\*")


def repair_strong(text: str) -> list[Inline]:
    text = _EMPTY_STRONG.sub(" ", text)
    out: list[Inline] = []
    position = 0
    for match in _BROKEN_STRONG.finditer(text):
        if match.start() > position:
            out.append(Text(text[position : match.start()]))
        out.append(Strong([Text(match.group(1))]))
        if match.group(2):
            out.append(Text(" "))
        position = match.end()
    if position < len(text):
        out.append(Text(text[position:]))
    return out


def _first_heading(blocks: list[Block]) -> str | None:
    for block in blocks:
        if isinstance(block, Heading) and block.level == 1:
            from guideprint.model import plain_text

            return plain_text(block.children).strip()
    return None


def _blocks(node: SyntaxTreeNode) -> list[Block]:
    out: list[Block] = []
    for child in node.children:
        out.extend(_block(child))
    return out


def _block(node: SyntaxTreeNode) -> list[Block]:
    match node.type:
        case "heading":
            level = int(node.tag[1:])
            return [Heading(level, _inlines(node.children[0]))]
        case "paragraph":
            return _paragraph(node.children[0])
        case "bullet_list" | "ordered_list":
            ordered = node.type == "ordered_list"
            start = int(node.attrs.get("start", 1)) if ordered else 1
            items = [ListItem(_blocks(item)) for item in node.children]
            return [ListBlock(ordered=ordered, items=items, start=start)]
        case "fence" | "code_block":
            return [CodeBlock(node.content.rstrip("\n"))]
        case "blockquote":
            return _blocks(node)
        case "hr" | "html_block":
            return []
        case "table":
            return _table_rows(node)
        case _:
            log.warning("unsupported block %r flattened to text", node.type)
            text = _collect_text(node)
            return [Paragraph([Text(text)])] if text.strip() else []


def _table_rows(node: SyntaxTreeNode) -> list[Block]:
    """A table has no natural print layout for a guide, so each row becomes a
    paragraph with the cells separated by a pipe."""
    rows: list[Block] = []
    for section in node.children:
        for row in section.children:
            cells = [_collect_text(cell).strip() for cell in row.children]
            rows.append(Paragraph([Text(" | ".join(cells))]))
    return rows


def _collect_text(node: SyntaxTreeNode) -> str:
    if node.type in {"text", "code_inline"}:
        return node.content
    if node.type in {"softbreak", "hardbreak"}:
        return "\n"
    return "".join(_collect_text(child) for child in node.children)


def _paragraph(inline: SyntaxTreeNode) -> list[Block]:
    """Images become blocks of their own. A paragraph that is nothing but
    images (the Notesnook way of attaching a picture) yields no text block."""
    text_children: list[SyntaxTreeNode] = []
    images: list[Image] = []
    for child in inline.children:
        if child.type == "image":
            # markdown-it percent-encodes the target; the model keeps the real path.
            source = unquote(str(child.attrs.get("src", "")))
            images.append(Image(path=source, alt=_collect_text(child)))
        else:
            text_children.append(child)
    out: list[Block] = []
    inlines = _inline_nodes(text_children)
    if inlines and _has_visible_text(inlines):
        out.append(Paragraph(inlines))
    out.extend(images)
    return out


def _has_visible_text(inlines: list[Inline]) -> bool:
    from guideprint.model import plain_text

    return bool(plain_text(inlines).strip())


def _inlines(inline: SyntaxTreeNode) -> list[Inline]:
    return _inline_nodes(inline.children)


def _inline_nodes(nodes: list[SyntaxTreeNode]) -> list[Inline]:
    return _merge_text(_convert_inline_nodes(nodes))


def _merge_text(inlines: list[Inline]) -> list[Inline]:
    """Join neighbouring text runs, then repair Notesnook's broken bold
    markers, which only match up once the runs are joined."""
    merged: list[Inline] = []
    for node in inlines:
        if isinstance(node, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].text + node.text)
        else:
            merged.append(node)
    out: list[Inline] = []
    for node in merged:
        out.extend(repair_strong(node.text) if isinstance(node, Text) else [node])
    return out


def _convert_inline_nodes(nodes: list[SyntaxTreeNode]) -> list[Inline]:
    out: list[Inline] = []
    for node in nodes:
        match node.type:
            case "text":
                out.append(Text(node.content))
            case "softbreak":
                out.append(Text(" "))
            case "hardbreak":
                out.append(LineBreak())
            case "code_inline":
                out.append(Code(node.content))
            case "strong":
                out.append(Strong(_inline_nodes(node.children)))
            case "em":
                out.append(Emph(_inline_nodes(node.children)))
            case "link":
                out.append(Link(str(node.attrs.get("href", "")), _inline_nodes(node.children)))
            case "image":
                # An image inside mixed text is shown as its alt text; the
                # standalone form is the one Notesnook produces.
                out.append(Text(_collect_text(node)))
            case "html_inline":
                # Notes are not HTML: `<passwort>` is a placeholder the reader
                # must see, not a tag.
                out.append(Text(node.content))
            case _:
                out.append(Text(_collect_text(node)))
    return out
