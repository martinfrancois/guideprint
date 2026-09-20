"""Find the notes inside whatever the user hands over.

Accepted inputs: a Notesnook export zip, a directory containing one or more
exported notes, or a single markdown file next to its ``attachments`` folder.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Note:
    path: Path

    @property
    def directory(self) -> Path:
        return self.path.parent


def load_export(source: Path, workdir: Path) -> list[Note]:
    if source.is_dir():
        return _notes_under(source)
    if source.suffix.lower() == ".md":
        return [Note(source)]
    if zipfile.is_zipfile(source):
        target = workdir / "export"
        _extract(source, target)
        return _notes_under(target)
    raise ValueError(f"{source}: not a zip, a directory or a markdown file")


def _notes_under(root: Path) -> list[Note]:
    notes = [Note(path) for path in sorted(root.rglob("*.md")) if not path.name.startswith(".")]
    if not notes:
        raise ValueError(f"{root}: no markdown notes found")
    return notes


def _extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            destination = (target / member.filename).resolve()
            if not destination.is_relative_to(resolved_target):
                raise ValueError(f"{archive}: refusing to extract {member.filename!r}")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, destination.open("wb") as dst:
                dst.write(src.read())
