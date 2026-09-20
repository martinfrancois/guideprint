import zipfile
from pathlib import Path

import pytest

from guideprint.export import load_export


def test_zip_slip_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.md", "# no")
    with pytest.raises(ValueError, match="refusing"):
        load_export(archive, tmp_path / "work")


def test_export_without_notes_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="no markdown notes"):
        load_export(tmp_path / "empty", tmp_path / "work")
