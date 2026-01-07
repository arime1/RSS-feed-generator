import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from playwright.sync_api import sync_playwright

START_URL = "https://innsynpluss.onacos.no/lo/innsyn/sok"
OUTFILE = "docs/rss.xml"

# Sett f.eks. til "bolig" hvis du vil filtrere. La stå None for alt.
KEYWORD = None

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def parse_date(text: str):
    m = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
    if not m:
        return None
    dd, mm, yyyy = m.groups()
    try:
        return datetime(int(yyyy), int(mm), int(dd), tzinfo=timezone.utc)
    except ValueError:
        return None

def pick_items(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()

    for a in soup.select("a[href]"):
        title = norm(a.get_text(" "))
        href = a.get("href", "")
        if not title or len(title) < 4:
            continue

        link = urljoin(base_url, href)

        if link.rstrip("/") == base_url.rstrip("/"):
            continue
        if any(x in link.lower() for x in ["javascript:", "mailto:", "#"]):
            continue

        ok = (
            "innsynpluss.onacos.no" in link
            and (
                "/innsyn/" in link
                or "/postliste" in link
                or "/api/presentation/" in link
                or "/mote" in link
            )
        )
        if not ok or link in seen:
            continue

        context = norm(a.parent.get_text(" ")) if a.parent else ""
        if KEYWORD and KEYWORD.lower() not in (title + " " + context).lower():
            continue

        pub = parse_date(context) or parse_date(title)

        seen.add(link)
        items.append({
            "title": title,
            "link": link,
            "summary": context if context and context != title else "",
            "published": pub,
        })

    return items[:50]

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(START_URL, wait_until="networkidle", timeout=90000)

        # Prøv å trigge “Søk/Vis” hvis siden krever det
        for selector in [
            "button:has-text('Søk')",
            "button:has-text('SØK')",
            "button:has-text('Vis')",
            "button:has-text('Oppdater')",
            "input[type=submit]",
        ]:
            try:
                page.locator(selector).first.click(timeout=1500)
                page.wait_for_timeout(1200)
                break
            except Exception:
                pass

        page.wait_for_timeout(1500)
        html = page.content()
        browser.close()

    items = pick_items(html, START_URL)

    fg = FeedGenerator()
    fg.id(START_URL)
    fg.title("LO – InnsynPluss (auto-RSS)")
    fg.link(href=START_URL, rel="alternate")
    fg.language("no")
    fg.updated(datetime.now(timezone.utc))

    for it in items:
        fe = fg.add_entry()
        fe.id(it["link"])
        fe.title(it["title"])
        fe.link(href=it["link"])
        if it["summary"]:
            fe.description(it["summary"])
        fe.published(it["published"] or datetime.now(timezone.utc))

    import os
    os.makedirs("docs", exist_ok=True)
    fg.rss_file(OUTFILE)
    print(f"Wrote {OUTFILE} with {len(items)} items")

if __name__ == "__main__":
    main()
