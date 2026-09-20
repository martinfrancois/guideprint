"""Strict visual regression of the example guide against an approved baseline.

This is a gate, not a score. The example export is built into both variants,
the result and the approved baseline PDFs are rasterised by the same PyMuPDF
in the same run, and the check passes only when page counts and page sizes
are equal and every page is pixel-identical. There is no colour threshold, no
allowed pixel percentage and no ignored region. A dependency update that
moves a line break, a picture or a page break therefore fails CI instead of
merging on its own.

    python tools/visual_regression.py repeatability   build twice, must match
    python tools/visual_regression.py check           candidate vs. baseline
    python tools/visual_regression.py approve         make the candidate the baseline

The baseline is only ever replaced by `approve` in a reviewed change, never
by `check`. A missing baseline is a failure, not a skip.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops

from guideprint.export import load_export
from guideprint.render import RenderOptions, render_note

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "sample-guide"
BASELINE_DIR = REPO / "data" / "visual-regression"
BUILD_DIR = REPO / "build" / "visual-regression"
VARIANTS = {"print": RenderOptions(), "digital": RenderOptions(digital=True)}
# Baseline and candidate are always rasterised identically.
DPI = 144


@dataclass
class PageResult:
    page: int
    match: bool
    differing_pixels: int = 0
    reason: str | None = None


@dataclass
class VariantResult:
    variant: str
    passed: bool
    pages: list[PageResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def build_candidates(target: Path) -> dict[str, Path]:
    """Render the example into ``target`` and return the PDF per variant."""
    with tempfile.TemporaryDirectory(prefix="guideprint-vr-") as tmp:
        note = load_export(EXAMPLE, Path(tmp))[0]
        out: dict[str, Path] = {}
        for variant, options in VARIANTS.items():
            pdf = target / f"{variant}.pdf"
            render_note(note, pdf, options, build_dir=Path(tmp) / "build" / variant)
            out[variant] = pdf
    return out


def rasterise(pdf: Path, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    with pymupdf.open(pdf) as doc:
        for index, page in enumerate(doc, start=1):
            out = directory / f"page-{index:03d}.png"
            page.get_pixmap(dpi=DPI).save(out)
            files.append(out)
    return files


def page_sizes(pdf: Path) -> list[tuple[float, float]]:
    with pymupdf.open(pdf) as doc:
        return [(round(page.rect.width, 2), round(page.rect.height, 2)) for page in doc]


def compare_variant(
    variant: str, baseline: Path, candidate: Path, out: Path, *, baseline_label: str
) -> VariantResult:
    result = VariantResult(variant=variant, passed=True)
    fail = result.failures.append
    base_sizes = page_sizes(baseline)
    cand_sizes = page_sizes(candidate)
    if len(base_sizes) != len(cand_sizes):
        counts = f"{baseline_label} has {len(base_sizes)}, candidate {len(cand_sizes)}"
        fail(f"page count differs: {counts}")
    base_pngs = rasterise(baseline, out / variant / baseline_label)
    cand_pngs = rasterise(candidate, out / variant / "candidate")
    diff_dir = out / variant / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    for index, (base_png, cand_png) in enumerate(zip(base_pngs, cand_pngs, strict=False), start=1):
        if base_sizes[index - 1] != cand_sizes[index - 1]:
            result.pages.append(
                PageResult(
                    index, False, reason=f"size {base_sizes[index - 1]} vs {cand_sizes[index - 1]}"
                )
            )
            continue
        differing = diff_pages(base_png, cand_png, diff_dir / f"page-{index:03d}.png")
        result.pages.append(PageResult(index, differing == 0, differing))
    for page in result.pages:
        if not page.match:
            detail = page.reason or f"{page.differing_pixels} differing pixels"
            fail(f"page {page.page}: {detail}")
    write_contact_sheet(cand_pngs, out / variant / "candidate-pages.png")
    result.passed = not result.failures
    return result


def diff_pages(baseline_png: Path, candidate_png: Path, diff_out: Path) -> int:
    """Number of pixels that differ; a red overlay of them is written when > 0."""
    with Image.open(baseline_png) as a, Image.open(candidate_png) as b:
        base = a.convert("RGB")
        cand = b.convert("RGB")
    if base.size != cand.size:
        return max(base.size[0] * base.size[1], cand.size[0] * cand.size[1])
    mask = ImageChops.difference(base, cand).convert("L").point(lambda v: 255 if v else 0)
    differing = mask.histogram()[255]
    if differing:
        overlay = Image.new("RGB", cand.size, (255, 0, 0))
        faded = Image.blend(cand, Image.new("RGB", cand.size, "white"), 0.6)
        faded.paste(overlay, mask=mask)
        faded.save(diff_out)
    return differing


def write_contact_sheet(
    files: list[Path], output: Path, columns: int = 6, cell_width: int = 220
) -> None:
    """Thumbnails of every page so a reviewer can find the one to open."""
    if not files:
        return
    gap = 8
    with Image.open(files[0]) as first:
        cell_height = round(cell_width * first.height / first.width)
    rows = -(-len(files) // columns)
    sheet = Image.new(
        "RGB",
        (columns * cell_width + (columns + 1) * gap, rows * cell_height + (rows + 1) * gap),
        (0xDD, 0xDD, 0xDD),
    )
    for index, file in enumerate(files):
        with Image.open(file) as page:
            thumb = page.convert("RGB").resize((cell_width, cell_height))
        x = gap + (index % columns) * (cell_width + gap)
        y = gap + (index // columns) * (cell_height + gap)
        sheet.paste(thumb, (x, y))
    sheet.save(output)


def report(results: list[VariantResult], title: str) -> str:
    lines = [f"## {title}: {'PASS' if all(r.passed for r in results) else 'FAIL'}", ""]
    for result in results:
        lines.append(f"### {result.variant}: {'pass' if result.passed else 'fail'}")
        differing = sum(not p.match for p in result.pages)
        lines.append(f"{len(result.pages)} pages compared, {differing} differing.")
        lines.extend(f"- {failure}" for failure in result.failures)
        lines.append("")
    return "\n".join(lines)


def publish(text: str, results: list[VariantResult]) -> None:
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "report.json").write_text(
        json.dumps(
            [
                {
                    "variant": r.variant,
                    "passed": r.passed,
                    "failures": r.failures,
                    "pages": [p.__dict__ for p in r.pages],
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )


def command_check() -> int:
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    candidates = build_candidates(BUILD_DIR / "candidate")
    results = []
    for variant, candidate in candidates.items():
        baseline = BASELINE_DIR / f"expected-{variant}.pdf"
        if not baseline.is_file():
            results.append(
                VariantResult(
                    variant,
                    False,
                    failures=[
                        f"no approved baseline at {baseline}; its absence would switch the "
                        'gate off, so it counts as a failure. See README, "Changing the '
                        'approved baseline".'
                    ],
                )
            )
            continue
        results.append(
            compare_variant(variant, baseline, candidate, BUILD_DIR, baseline_label="baseline")
        )
    publish(report(results, "Strict visual regression"), results)
    return 0 if all(r.passed for r in results) else 1


def command_repeatability() -> int:
    """Build twice and require identical rasters, which qualifies the runner:
    a verdict from a renderer that does not repeat itself means nothing."""
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    first = build_candidates(BUILD_DIR / "first")
    second = build_candidates(BUILD_DIR / "second")
    results = [
        compare_variant(variant, first[variant], second[variant], BUILD_DIR, baseline_label="first")
        for variant in VARIANTS
    ]
    publish(report(results, "Repeatability qualification"), results)
    return 0 if all(r.passed for r in results) else 1


def command_approve() -> int:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for variant, candidate in build_candidates(BUILD_DIR / "candidate").items():
        target = BASELINE_DIR / f"expected-{variant}.pdf"
        shutil.copyfile(candidate, target)
        print(f"approved {target.relative_to(REPO)} ({len(page_sizes(target))} pages)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["check", "repeatability", "approve"])
    args = parser.parse_args(argv)
    return {
        "check": command_check,
        "repeatability": command_repeatability,
        "approve": command_approve,
    }[args.command]()


if __name__ == "__main__":
    sys.exit(main())
