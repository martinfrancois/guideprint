# guideprint

Turns a [Notesnook](https://notesnook.com) markdown export into step-by-step
guide PDFs: one laid out for printing, and one with a single tall page per
part for reading on a screen.

Notesnook's own PDF export shows every picture at whatever size the editor
uses and breaks pages wherever the text happens to end. For an illustrated
how-to that is the wrong trade: a barcode has to come out at the size a scanner
reads, a screenshot has to stay next to the step that mentions it, and the line
"scan all of these:" must not be the last line of a page. guideprint applies
those rules and leaves the writing to Notesnook.

## Install

Python 3.12 or newer. The Typst compiler and the Inter font ship inside the
package, nothing else is needed.

```sh
uv tool install git+https://github.com/martinfrancois/guideprint
# or
pipx install git+https://github.com/martinfrancois/guideprint
```

## Use

In Notesnook, export the note (or the notebook) as Markdown with frontmatter.
That gives you a zip. Then:

```sh
guideprint "My guide.zip"
```

This writes `My-guide-print.pdf` and `My-guide-digital.pdf` in the current
directory, one pair per note in the export. A directory or a single `.md`
file next to its `attachments` folder works as input as well.

Two kinds of output exist and both are written by default. The print variant
lays the guide out on A4 pages with the page-break rules below. The digital
variant makes one page per level-1 heading, exactly as tall as that part
needs, for scrolling through on a screen. Each file carries its variant as a
suffix, `-print` or `-digital`, also when `--variant print` or
`--variant digital` writes only one of them.

Useful options:

| Option | Default | What it does |
| --- | --- | --- |
| `-o PATH` | `<title>.pdf` | Output file, or output directory when the export holds several notes; the variant suffix is inserted before `.pdf` |
| `--variant` | `both` | `both`, `print`, or `digital` |
| `--barcode-width MM` | `33.5` | Printed width of every barcode |
| `--paper` | `a4` | `a4`, `a5`, `a3`, `us-letter` or `us-legal` |
| `--margin MM` | `14` | Page margin |
| `--font-size PT` | `12` | Body text size, headings scale with it |
| `--font NAME` | `Inter` | Any font Typst can find on the system, Inter is bundled |
| `--max-image-height FRACTION` | `0.55` | Tallest picture as a share of the page's text area |
| `--default-dpi` | `96` | Density assumed for pictures without DPI metadata |
| `--keep-build DIR` | | Keep the generated Typst sources for inspection or hand tuning |
| `-v` | | Print how every picture was classified and sized |

Run `guideprint examples/sample-guide` for a complete sample. That
folder is what a Notesnook export looks like once unzipped: the note is a
real guide's structure with its prose replaced by lorem ipsum, the barcodes
are real, and the screenshots and the photo are placeholders of the original
pixel sizes and densities.

## What it does with pictures

**Barcodes** are printed 33.5 mm wide (`--barcode-width`), beside their
caption in one right-aligned column, with room below each so a scanner reads
one at a time. They are recognised from their pixels, not their file
names: three horizontal lines through the
upper part of the picture must be black-and-white with many transitions and
agree with each other, which is true of vertical bars and false of screenshots,
photos and text. Run with `-v` to see the verdict for each file.

**Everything else** is printed at its natural size: the pixel count divided by
the DPI stored in the file, or by 96 when the file has none. A file name ending
in `@2x` (macOS retina screenshots) counts as twice the density. A picture wider
than the column shrinks to the column, one taller than `--max-image-height` of
the page shrinks to that, both without distortion.

Formats Typst cannot open (BMP, TIFF, HEIC and so on) are converted to PNG on
the way. An attachment missing from the export prints as a framed placeholder
with the file name, so the guide still builds.

## Where pages break

These rules shape the print variant. The digital variant has one page per
part and never reaches a page end, so only the line-level rules (paths,
hand-broken lines, barcode rows) are visible there.

* A step's text and the pictures under it are one block that never splits
  across a page.
* A line followed by a list (headings and "do all of these:" intros) moves to
  the next page together with the first item rather than ending a page alone.
* A section, meaning a heading and everything under it up to the next heading
  of the same or a higher level, that fits on one page is printed on one page.
  The same goes for a list item together with everything nested under it, so
  a step like "scan these barcodes on every target" with its six barcodes is
  never split. Nested sections and items apply the rule on their own when the
  outer one is too long. The end of the previous page stays empty in that
  case, which is the point: the reader gets the whole checklist in one view.
* A paragraph with manual line breaks (Shift+Enter in Notesnook), such as a
  list of shell commands, keeps every line on one line and shrinks a line that
  is too wide, so copying from the PDF gives one command per line. Each line
  also gets its own paragraph tag in the PDF. This works in viewers built on
  Chrome's or Firefox's PDF engine and in the Google Drive viewer on Android.
  Adobe Acrobat Reader for Android joins every selected line into one when
  copying, whatever the PDF contains, so copy from another viewer there.
* A Windows path (quoted, so spaces inside it count) or a URL stays on one
  line and moves to the next line whole when it does not fit at the end of
  the current one. Only a path wider than the column wraps.
* Consecutive steps that contain barcodes are kept on one page when they fit,
  so all the codes for one trip to the machine are on one sheet.
* Every level-1 heading after the first starts a new page.
* The level-1 heading that repeats the note title is dropped; the title is the
  document header.

The rest follows normal Typst layout.

## Notesnook quirks that are handled

Notesnook's markdown differs from what a CommonMark parser expects in a few
places. guideprint repairs them so the printed text matches what the editor
shows:

* A picture attached to a list item comes out as an empty bullet followed by
  the picture on the parent level, which splits the list in two. The picture is
  moved back into the item it illustrates and the list is joined again.
* A list marker directly under a picture line, without a blank line between,
  would otherwise be read as text continuing the picture's paragraph.
* Bold runs that end in a space (`**before **`), are empty (`** **`), or are
  glued to a word (`20210821**\_2**.csv`) are invalid CommonMark and would print
  with their asterisks.
* `<placeholder>` in the text is printed as written instead of being treated
  as an HTML tag.

## Tuning the layout

`--keep-build DIR` leaves `main.typ`, `template.typ` and the pictures in
`DIR`. `template.typ` holds the page setup and the four helpers the generated
document uses (`keep`, `lead`, `fig`, `missing`). Edit it and rebuild with
`typst compile DIR/main.typ`, or change `src/guideprint/template.typ` in a
checkout to make the change permanent.

## Development

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

The tests build real PDFs and read them back with PyMuPDF to check picture
sizes and which page each caption and picture landed on. `tests/conftest.py`
draws synthetic barcodes, screenshots and photos, so no test depends on the
example's pictures beyond the example tests themselves.

### Visual regression

`data/visual-regression/expected-print.pdf` and `expected-digital.pdf` are
the approved output of the example. CI builds the example, rasterises both
the result and the baseline with the same PyMuPDF at 144 dpi, and fails
unless page counts and page sizes are equal and every page is
pixel-identical. There is no tolerance, so a dependency update that moves a
line break or a picture cannot merge on its own. Before the comparison the
runner builds the example twice and requires identical rasters, which
proves the verdict comes from a deterministic renderer.

```sh
uv run python tools/visual_regression.py repeatability
uv run python tools/visual_regression.py check
```

On a failure, `build/visual-regression/` holds the candidate pages, the
baseline pages, a red-overlay diff per differing page and a contact sheet;
CI uploads that folder as an artifact.

Changing the approved baseline is a reviewed change: after a layout change
you intend, run `uv run python tools/visual_regression.py approve`, look at
`build/visual-regression/candidate/` and commit the two PDFs together with
the change that caused them. `check` never writes the baseline, and a
missing baseline is a failure, not a skip.

### Release-age cooldown

`[tool.uv] exclude-newer = "7 days"` in `pyproject.toml` keeps every file
uploaded in the last seven days out of any lock uv makes, including
Renovate's weekly lock file maintenance. A security fix should not wait that
long. When Renovate raises a security pull request (label `security`, branch
ending in `-vulnerability`) whose fixed version is younger than the cooldown,
`.github/workflows/security-cooldown-exception.yml` adds an entry for it to
`[tool.uv.exclude-newer-package]` with `tools/uv_cooldown.py`, re-locks, and
pushes the result to the pull request. It pushes with a GitHub App's token
(repository variable `COOLDOWN_APP_ID`, secret `COOLDOWN_APP_PRIVATE_KEY`),
because a push made with the workflow's own token would not start CI. The
App's commit email is in `gitIgnoredAuthors` in `renovate.json`, so Renovate
still treats the branch as its own and keeps rebasing and automerging it.

The entry admits the fixed version and nothing uploaded after it, and has to
go once it is a cooldown old, because until then it holds the package at
that version. `uv_cooldown.py prune` removes matured entries; the scheduled
prune in [dependency-watchdog](https://github.com/martinfrancois/dependency-watchdog)
opens a pull request for them.

For a security fix Renovate did not raise, or a transitive one with no pin
to compare, run the workflow by hand with the pull request's number and the
fixed versions:

```sh
gh workflow run security-cooldown-exception.yml -f pull-request=123 -f packages="iniconfig==2.3.1"
```

The workflow runs every `uv lock` with `--no-build`, because the job then
holds a token that can push: a source distribution's build is code from the
new release, and it could change the files the job commits. A fix published
only as an sdist therefore fails the workflow. Add the entry on the pull
request branch by hand instead:

```sh
python tools/uv_cooldown.py exempt iniconfig==2.3.1 --reason "security fix, <pull request URL>"
uv lock --upgrade-package iniconfig==2.3.1
```

This is a workaround until Renovate writes these entries itself, tracked in
[#40](https://github.com/martinfrancois/guideprint/issues/40).

## License

MIT. The bundled Inter font is under the SIL Open Font License, see
`src/guideprint/fonts/LICENSE-Inter.txt`.
