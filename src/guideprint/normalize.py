"""Rewrite the parsed tree into the shape the print layout wants.

Notesnook attaches an image to a list by emitting an empty bullet and then the
image as a paragraph on the parent level, which splits one list into several
and leaves an empty item behind. The rules here undo that so every image ends
up inside the list item it illustrates:

1. Empty list items are dropped, and a list with no items left is dropped.
2. An image that directly follows a list is moved into that list's last item.
3. Two adjacent lists of the same kind are merged into one.
4. A leading level-1 heading that repeats the note title is dropped, since
   the title is printed as the document header.
"""

from __future__ import annotations

from guideprint.model import Block, Document, Heading, Image, ListBlock, ListItem, plain_text


def normalize(doc: Document) -> Document:
    blocks = _drop_title_heading(doc.blocks, doc.title)
    return Document(title=doc.title, blocks=normalize_blocks(blocks), meta=doc.meta)


def _drop_title_heading(blocks: list[Block], title: str) -> list[Block]:
    if (
        blocks
        and isinstance(blocks[0], Heading)
        and blocks[0].level == 1
        and plain_text(blocks[0].children).strip().casefold() == title.strip().casefold()
    ):
        return blocks[1:]
    return blocks


def normalize_blocks(blocks: list[Block]) -> list[Block]:
    out: list[Block] = []
    for block in blocks:
        if isinstance(block, ListBlock):
            items = [ListItem(normalize_blocks(item.blocks)) for item in block.items]
            items = [item for item in items if item.blocks]
            if not items:
                continue
            block = ListBlock(ordered=block.ordered, items=items, start=block.start)
        previous = out[-1] if out else None
        if isinstance(block, Image) and isinstance(previous, ListBlock):
            previous.items[-1].blocks.append(block)
            continue
        if (
            isinstance(block, ListBlock)
            and isinstance(previous, ListBlock)
            and previous.ordered == block.ordered
        ):
            previous.items.extend(block.items)
            continue
        out.append(block)
    return out
