"""Renders app/guide.html to docs/guides/RFNoise-Mapping-guide.pdf (needs:  pip install playwright && playwright install chromium)."""
import os
from playwright.sync_api import sync_playwright
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(REPO, "app", "guide.html")
out = os.path.join(REPO, "docs", "guides", "RFNoise-Mapping-guide.pdf")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto("file://" + src)
    pg.wait_for_timeout(500)
    pg.pdf(path=out, format="Letter", print_background=True,
           margin={"top": "0.6in", "bottom": "0.6in", "left": "0.6in", "right": "0.6in"})
    b.close()
print(out, os.path.getsize(out))
