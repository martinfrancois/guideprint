// Page layout for a step-by-step guide, on paper or on a screen. The generated document calls
// `guide` through a show rule and then uses `keep`, `lead`, `fig` and
// `missing` to express which things must stay together on a page.

#let heading-above = 1.3em

#let guide(
  title: "",
  paper: "a4",
  margin: 14mm,
  font: "Inter",
  font-size: 12pt,
  lang: none,
  // Digital variant: a page is as tall as its content, so every level-1
  // section is one page to scroll through. Page numbers are pointless there.
  digital: false,
  body,
) = {
  set document(title: title)
  set page(
    paper: paper,
    margin: (x: margin, top: margin, bottom: margin + 6mm),
    footer: context align(center, text(size: 0.7em, counter(page).display("1"))),
  )
  set page(height: auto, margin: margin, footer: none) if digital
  // Contextual alternates off: Inter would otherwise draw "=>" and "->" as
  // arrows, and a guide has to show what the reader will type.
  set text(font: font, size: font-size, hyphenate: false, features: (calt: 0))
  if lang != none {
    set text(lang: lang)
  }
  set smartquote(enabled: false)
  set par(leading: 0.5em, spacing: 0.65em)
  // Absolute sizes: Typst's own heading rule already scales by level, and an
  // em value here would multiply with it.
  show heading.where(level: 1): set text(size: font-size * 2, weight: "bold")
  show heading.where(level: 2): set text(size: font-size * 1.6, weight: "bold")
  show heading.where(level: 3): set text(size: font-size * 1.25, weight: "bold")
  show heading.where(level: 4): set text(size: font-size, weight: "bold")
  show heading: set block(above: heading-above, below: 0.6em)
  set enum(indent: 0.6em, body-indent: 0.6em, numbering: "1.", spacing: 0.45em)
  set list(indent: 0.6em, body-indent: 0.6em, marker: ([•], [◦], [▪]), spacing: 0.45em)
  show link: underline
  show raw.where(block: true): set block(fill: luma(245), inset: 6pt, radius: 2pt, width: 100%)

  block(below: 0.8em, text(size: font-size * 2, weight: "bold", title))
  body
}

// A caption and its picture, or any group that is useless when split.
#let keep(body) = block(breakable: false, width: 100%, body)

// A line that introduces the block after it ("Scan these barcodes:") and must
// not be stranded at the bottom of a page.
#let lead(body) = block(sticky: true, width: 100%, body)

// A picture printed `target` wide, shrunk to the column and to `max-height`
// without distortion. `aspect` is width divided by height.
#let fig(path, target, aspect, max-height) = block(
  above: 0.5em,
  below: 0.65em,
  width: 100%,
  layout(size => image(path, width: calc.min(target, size.width, max-height * aspect))),
)

// Content that is kept on one page when it fits there, which may leave the
// end of the previous page empty. Content taller than the page's text area
// (`size.height`) flows across pages as usual.
#let together(body) = layout(size => {
  let height = measure(block(width: size.width, body)).height
  block(breakable: height > size.height, width: 100%, body)
})

// A heading with everything under it, up to the next heading of the same or a
// higher level. Kept on one page when it fits, like every list item with
// sub-items, so a checklist is read in one view instead of around a page
// break. The heading's own spacing collapses at the start of a block, so the
// outer block carries it instead.
#let section(body) = block(width: 100%, above: heading-above, together(body))

// A caption with its barcode beside it. Every barcode sits in one
// right-aligned column of the page, so rows read as a table and the scanner
// finds them all at the same place. The padding under the row keeps
// neighbouring barcodes apart so the scanner reads one at a time; padding
// above would push the caption away from its list marker.
#let barcode-row(caption, path, width) = block(
  width: 100%,
  grid(
    columns: (1fr, width),
    column-gutter: 1.5em,
    inset: (bottom: 5mm),
    align: (left + top, right + top),
    caption,
    image(path, width: width),
  ),
)

// A paragraph the author broke into lines by hand, such as a list of shell
// commands. Each line becomes a paragraph of its own: that keeps it on one
// line, and it gives the line its own paragraph tag in the PDF, which is
// what Adobe Reader goes by when copying (a stack of lines inside one tag is
// copied as a single line). A line wider than the column is shrunk to fit,
// down to `min-line-scale` of the text size, beyond which it wraps like prose.
#let min-line-scale = 0.55
#let lines(..items) = layout(size => {
  for line in items.pos() {
    let natural = measure(line).width
    let scale = calc.min(1, size.width / natural)
    let sized = if scale >= min-line-scale { text(size: scale * 1em, line) } else { line }
    par(spacing: 0.35em, sized)
  }
})

// A token such as a file path or a URL that must not wrap, unless it is
// wider than the column, in which case it wraps like any text rather than
// running into the margin. `width` is the column width, which the writer
// obtains by wrapping the paragraph in `layout`.
#let nowrap(width, body) = context {
  if measure(body).width <= width { box(body) } else { body }
}

// Placeholder for an attachment the export does not contain.
#let missing(name) = block(
  above: 0.5em,
  below: 0.65em,
  stroke: 0.5pt + luma(150),
  inset: 6pt,
  text(fill: luma(100), size: 0.85em)[missing image: #raw(name)],
)
