#!/usr/bin/env bash
# Build docs/DESIGN.pdf from docs/DESIGN.md via pandoc → HTML → Chrome headless.
# Works on macOS without a LaTeX install. Targets ~2 pages letter / 0.5in margins.

set -euo pipefail

cd "$(dirname "$0")/.."

# Optional first argument selects the source Markdown (default: docs/DESIGN.md).
# The output PDF and temp HTML are derived from the source name, so this script
# builds either the full design doc or the concise 2-page version.
SRC="${1:-docs/DESIGN.md}"
PDF="${SRC%.md}.pdf"
HTML="/tmp/$(basename "${SRC%.md}").html"

cat > /tmp/medcoder_pdf.css <<'CSS'
@page { size: Letter; margin: 0.5in; }
html, body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 9pt; line-height: 1.24; color: #1c2530; margin: 0; padding: 0;
  -webkit-font-smoothing: antialiased;
}
h1 {
  font-size: 12.5pt; font-weight: 650; color: #1d3a5f;
  margin: 7.5pt 0 3pt; padding-bottom: 2pt; border-bottom: 1.5px solid #cdd8e4;
}
h1:first-of-type { margin-top: 1pt; }
h2 { font-size: 10.5pt; font-weight: 600; color: #234e70; margin: 5pt 0 2pt; }
h3 { font-size: 9.5pt; font-weight: 600; color: #234e70; margin: 5pt 0 1pt; }
p  { margin: 2pt 0; }
ul, ol { margin: 2pt 0 2pt 17pt; padding: 0; }
li { margin: 0.5pt 0; }
strong { color: #14202c; font-weight: 650; }
em { color: #2c3a48; }
code, pre {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: 8.2pt; background: #f1f4f8; border-radius: 3pt; color: #2a3744;
}
code { padding: 0.5pt 3pt; }
pre { padding: 5pt 7pt; overflow-x: auto; border: 1px solid #e3e9f0; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0; font-size: 8.3pt; }
th, td { border: 1px solid #d6dde6; padding: 2.5pt 6pt; vertical-align: top; text-align: left; }
th { background: #eef2f7; color: #1d3a5f; font-weight: 600; }
tr:nth-child(even) td { background: #f8fafc; }
blockquote {
  border-left: 3pt solid #3fa392; background: #f3faf8;
  padding: 3pt 11pt; color: #234; margin: 4pt 0; border-radius: 0 3pt 3pt 0;
}
img { display: block; max-width: 84%; margin: 5pt auto 1pt; }
em { display: inline; }
hr { border: 0; border-top: 1px solid #cdd8e4; margin: 8pt 0; }
header.title-block-header { margin-bottom: 8pt; padding-bottom: 5pt; border-bottom: 2px solid #1d3a5f; }
.title { font-size: 18pt; font-weight: 700; color: #1d3a5f; margin-bottom: 1pt; }
.subtitle { font-size: 11pt; color: #56657a; font-weight: 400; margin-bottom: 2pt; }
.author, .date { font-size: 9pt; color: #6b7a8d; }
CSS

pandoc "$SRC" \
  -o "$HTML" \
  --from=markdown-implicit_figures \
  --standalone \
  --resource-path=docs \
  --css=/tmp/medcoder_pdf.css \
  --embed-resources

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  CHROME="$(command -v google-chrome || true)"
fi
if [ -z "$CHROME" ]; then
  echo "No Chrome found — install Google Chrome, or use 'make pdf-latex' (pandoc + xelatex)."
  exit 1
fi

"$CHROME" --headless --disable-gpu --no-pdf-header-footer --no-margins \
  --print-to-pdf="$PDF" "file://$HTML" 2>/dev/null

echo "wrote $PDF ($(du -h "$PDF" | cut -f1))"
