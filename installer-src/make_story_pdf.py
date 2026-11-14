"""Renders docs/The-Story-of-RF-Noise-Map.md to docs/guides/The-Story-of-RF-Noise-Map.pdf
(needs:  pip install markdown playwright && playwright install chromium)."""
import os, re, markdown
from playwright.sync_api import sync_playwright
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(REPO, "docs", "The-Story-of-RF-Noise-Map.md")
tmp = os.path.join(REPO, "docs", "_story_tmp.html")
out = os.path.join(REPO, "docs", "guides", "The-Story-of-RF-Noise-Map.pdf")
md = open(src, encoding="utf-8").read()
body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
css = """
body{font-family:Georgia,'Times New Roman',serif;font-size:11.5pt;line-height:1.5;color:#1b1b1b;max-width:7in;margin:0 auto}
h1{font-size:26pt;margin:0 0 .3em;color:#12355b}
h2{font-size:17pt;color:#12355b;border-bottom:1px solid #c9d3df;padding-bottom:.15em;margin-top:1.6em;page-break-after:avoid}
h3{font-size:13pt;color:#12355b;page-break-after:avoid}
img{max-width:100%;border:1px solid #ccd;margin:.6em 0;page-break-inside:avoid}
table{border-collapse:collapse;width:100%;font-size:10pt;margin:.8em 0;page-break-inside:avoid}
th,td{border:1px solid #b8c2cf;padding:4px 7px;text-align:left;vertical-align:top}
th{background:#e8eef5}
code,pre{font-family:Consolas,Menlo,monospace;font-size:9.5pt;background:#f3f5f8}
pre{padding:8px;white-space:pre-wrap;page-break-inside:avoid}
blockquote{border-left:4px solid #9db4cf;margin:1em 0;padding:.2em 1em;background:#f4f7fb;color:#333}
a{color:#12559b;text-decoration:none}
"""
open(tmp, "w", encoding="utf-8").write(
    "<!doctype html><html><head><meta charset='utf-8'><title>The Story of RF Noise Map</title><style>%s</style></head><body>%s</body></html>" % (css, body))
os.makedirs(os.path.dirname(out), exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("file://" + tmp)
    pg.wait_for_timeout(500)
    pg.pdf(path=out, format="Letter", print_background=True, display_header_footer=True,
           header_template="<span></span>",
           footer_template="<div style='font-size:8pt;width:100%;text-align:center;color:#666'>The Story of RF Noise Map - page <span class='pageNumber'></span> of <span class='totalPages'></span></div>",
           margin={"top": "0.7in", "bottom": "0.8in", "left": "0.7in", "right": "0.7in"})
    b.close()
os.remove(tmp)
print(out, os.path.getsize(out))
