"""Collect Thai, Indonesian and Vietnamese news coverage of Aniimo into Google Sheets."""

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import gspread

SHEET_ID = os.environ["SHEET_ID"]

# Add or remove query strings here as the client confirms name variants.
QUERIES = {
    "TH": [("Aniimo", "th", "TH"), ("Aniimo เกม", "th", "TH"), ("Aniimo มือถือ", "th", "TH")],
    "ID": [("Aniimo", "id", "ID"), ("Aniimo game", "id", "ID"), ("Aniimo rilis", "id", "ID")],
    "VN": [("Aniimo", "vi", "VN"), ("Aniimo ra mắt", "vi", "VN"), ("Aniimo đánh giá", "vi", "VN")],
}


def fetch_feed(query, hl, gl):
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + f"&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    )
    with urllib.request.urlopen(url, timeout=30) as resp:
        return ET.fromstring(resp.read())


def clean(text):
    return " ".join((text or "").split())


def main():
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    )
    ws = gc.open_by_key(SHEET_ID).worksheet("raw_mentions")

    seen = set(ws.col_values(1))
    seen_articles = {value.split("_", 2)[2] for value in seen if value.startswith("news_") and len(value.split("_", 2)) == 3}
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows = []

    for market, queries in QUERIES.items():
        for query, hl, gl in queries:
            try:
                feed = fetch_feed(query, hl, gl)
            except Exception as e:
                print(f"feed failed for {market} '{query}': {e}")
                continue

            for item in feed.findall(".//item"):
                title = clean(item.findtext("title"))
                link = clean(item.findtext("link"))
                if not title or not link:
                    continue

                # Dedupe on the headline, since the same article surfaces
                # under several query strings with different redirect URLs.
                digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
                mention_id = f"news_{market}_{digest}"
                if mention_id in seen or digest in seen_articles:
                    continue
                seen.add(mention_id)
                seen_articles.add(digest)

                source_el = item.find("source")
                outlet = clean(source_el.text) if source_el is not None else ""

                new_rows.append([
                    mention_id,
                    "news",
                    market,
                    link,
                    outlet,
                    title,
                    "",
                    clean(item.findtext("pubDate")),
                    collected_at,
                ])
            time.sleep(1)

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")

    print(f"{len(new_rows)} new articles")


if __name__ == "__main__":
    main()
