"""The comparator itself is verified here: it must see a difference and it
must not see one where there is none."""

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import visual_regression as vr


def _pdf(path: Path, texts: list[str], height: float = 200) -> Path:
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page(width=200, height=height)
        page.insert_text((20, 40), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_identical_pdfs_pass(tmp_path: Path) -> None:
    a = _pdf(tmp_path / "a.pdf", ["one", "two"])
    b = _pdf(tmp_path / "b.pdf", ["one", "two"])
    result = vr.compare_variant("t", a, b, tmp_path / "out", baseline_label="baseline")
    assert result.passed and [p.match for p in result.pages] == [True, True]
    assert (tmp_path / "out" / "t" / "candidate-pages.png").exists()


def test_one_changed_glyph_fails_with_a_diff_image(tmp_path: Path) -> None:
    a = _pdf(tmp_path / "a.pdf", ["one", "two"])
    b = _pdf(tmp_path / "b.pdf", ["one", "twe"])
    result = vr.compare_variant("t", a, b, tmp_path / "out", baseline_label="baseline")
    assert not result.passed
    assert [p.match for p in result.pages] == [True, False]
    assert result.pages[1].differing_pixels > 0
    assert (tmp_path / "out" / "t" / "diffs" / "page-002.png").exists()
    assert "page 2" in result.failures[0]


def test_page_count_and_size_differences_fail(tmp_path: Path) -> None:
    a = _pdf(tmp_path / "a.pdf", ["one", "two"])
    fewer = _pdf(tmp_path / "c.pdf", ["one"])
    taller = _pdf(tmp_path / "d.pdf", ["one", "two"], height=300)
    assert (
        "page count differs"
        in vr.compare_variant("t", a, fewer, tmp_path / "o1", baseline_label="baseline").failures[0]
    )
    taller_result = vr.compare_variant("t", a, taller, tmp_path / "o2", baseline_label="baseline")
    assert any("size" in f for f in taller_result.failures)


def test_check_fails_without_a_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vr, "BASELINE_DIR", tmp_path / "none")
    monkeypatch.setattr(vr, "BUILD_DIR", tmp_path / "build")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert vr.command_check() == 1
