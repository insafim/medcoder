#!/usr/bin/env bash
# Build docs/DESIGN.pdf from docs/DESIGN.md via pandoc → HTML → Chrome headless.
# Works on macOS without a LaTeX install. Targets ~2 pages letter / 0.5in margins.

set -euo pipefail

cd "$(dirname "$0")/.."

SRC="docs/DESIGN.md"
HTML="/tmp/medcoder_design.html"
PDF="docs/DESIGN.pdf"

cat > /tmp/medcoder_pdf.css <<'CSS'
@page { size: Letter; margin: 0.32in; }
html, body {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, sans-serif;
  font-size: 8pt; line-height: 1.16; color: #111; margin: 0; padding: 0;
}
h1 { font-size: 12pt; margin: 5pt 0 3pt; border-bottom: 1px solid #888; padding-bottom: 1pt; }
h2 { font-size: 10pt; margin: 4pt 0 1pt; }
h3 { font-size: 9pt; margin: 3pt 0 1pt; }
p  { margin: 1pt 0; }
ul, ol { margin: 1pt 0 1pt 13pt; padding: 0; }
li { margin: 0.5pt 0; }
strong { color: #000; }
code, pre {
  font-family: "SF Mono", Menlo, Consolas, monospace;
  font-size: 8pt; background: #f4f4f4; border-radius: 2pt;
}
code { padding: 0 2pt; }
pre { padding: 4pt 6pt; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; margin: 3pt 0; font-size: 8pt; }
th, td { border: 1px solid #bbb; padding: 2pt 4pt; vertical-align: top; text-align: left; }
th { background: #eee; }
blockquote { border-left: 2pt solid #999; padding-left: 6pt; color: #444; margin: 3pt 0; }
hr { border: 0; border-top: 1px solid #888; margin: 6pt 0; }
header.title-block-header { margin-bottom: 6pt; }
.title { font-size: 14pt; font-weight: 600; margin-bottom: 1pt; }
.subtitle { font-size: 10pt; color: #444; margin-bottom: 1pt; }
.author, .date { font-size: 9pt; color: #555; }
CSS

pandoc "$SRC" \
  -o "$HTML" \
  --standalone \
  --css=/tmp/medcoder_pdf.css \
  --embed-resources

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  CHROME="$(command -v google-chrome || true)"
fi
if [ -z "$CHROME" ]; then
  echo "No Chrome found — install Google Chrome or use 'make pdf' (pandoc + xelatex)."
  exit 1
fi

"$CHROME" --headless --disable-gpu --no-pdf-header-footer --no-margins \
  --print-to-pdf="$PDF" "file://$HTML" 2>/dev/null

echo "wrote $PDF ($(du -h "$PDF" | cut -f1))"
