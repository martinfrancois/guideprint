"""The document tree the renderer works on.

The markdown parser produces this tree and the normalizer rewrites it, so the
Typst writer never has to know how Notesnook lays out its export.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Text:
    text: str


@dataclass
class Strong:
    children: list[Inline]


@dataclass
class Emph:
    children: list[Inline]


@dataclass
class Code:
    text: str


@dataclass
class Link:
    href: str
    children: list[Inline]


@dataclass
class LineBreak:
    pass


Inline = Text | Strong | Emph | Code | Link | LineBreak


@dataclass
class Heading:
    level: int
    children: list[Inline]


@dataclass
class Paragraph:
    children: list[Inline]


@dataclass
class Image:
    """An image that stands on its own line. ``path`` is relative to the note."""

    path: str
    alt: str = ""


@dataclass
class CodeBlock:
    text: str


@dataclass
class ListItem:
    blocks: list[Block] = field(default_factory=list)


@dataclass
class ListBlock:
    ordered: bool
    items: list[ListItem]
    start: int = 1


Block = Heading | Paragraph | Image | CodeBlock | ListBlock


@dataclass
class Document:
    title: str
    blocks: list[Block]
    meta: dict[str, object] = field(default_factory=dict)


def plain_text(inlines: list[Inline]) -> str:
    """Flatten inline content to a plain string, used for comparisons and logs."""
    parts: list[str] = []
    for node in inlines:
        match node:
            case Text(text) | Code(text):
                parts.append(text)
            case Strong(children) | Emph(children) | Link(_, children):
                parts.append(plain_text(children))
            case LineBreak():
                parts.append("\n")
    return "".join(parts)
