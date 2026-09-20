"""Turn a Notesnook markdown export into step-by-step guide PDFs.

One PDF is laid out for paper, the other has a tall page per part for the
screen.
"""

from guideprint.render import RenderOptions, render_note

__all__ = ["RenderOptions", "render_note"]
