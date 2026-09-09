
"""Collect App Store reviews + rating snapshot for Aniimo (TH and ID) into Google Sheets."""

import json
import os
import urllib.request
from datetime import datetime, timezone

import gspread

APP_ID = os.environ["APPLE_APP_ID"]
SHEET_ID = os.environ["SHEET_ID"]
MARKETS = ["th", "id"]
MAX_PAGES = 5


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def fetch_reviews(country):
    entries = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"https://itunes.apple.com/{country}/rss/customerreviews"
            f"/page={page}/id={APP_ID}/sortBy=mostRecent/json"
        )
        batch = fetch_json(url)["feed"].get("entry", [])
        if not batch:
            break
        entries.extend(batch)
    return entries


def main():
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    )
    sheet = gc.open_by_key(SHEET_ID)
    mentions_ws = sheet.worksheet("raw_mentions")
    ratings_ws = sheet.worksheet("store_ratings")

    seen = set(mentions_ws.col_values(1))
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows = []
    rating_rows = []

    for country in MARKETS:
        market = country.upper()
        listing_url = f"https://apps.apple.com/{country}/app/id{APP_ID}"

        try:
            entries = fetch_reviews(country)
        except Exception as e:
            print(f"review fetch failed for {market}: {e}")
            entries = []

        for r in entries:
            mention_id = f"apple_{market}_{r['id']['label']}"
            if mention_id in seen:
                continue
            seen.add(mention_id)
            title = r["title"]["label"]
            body = r["content"]["label"]
            new_rows.append([
                mention_id,
                "app_store",
                market,
                listing_url,
                r["author"]["name"]["label"],
                f"{title}\n\n{body}",
                r["im:rating"]["label"],
                r["updated"]["label"],
                collected_at,
            ])

        try:
            lookup = fetch_json(
                f"https://itunes.apple.com/lookup?id={APP_ID}&country={country}"
            )
            detail = lookup["results"][0]
            rating_rows.append([
                collected_at,
                "app_store",
                market,
                detail.get("averageUserRating", ""),
                detail.get("userRatingCount", ""),
                "", "", "", "", "",
            ])
        except Exception as e:
            print(f"rating snapshot failed for {market}: {e}")

    if new_rows:
        mentions_ws.append_rows(new_rows, value_input_option="RAW")
    if rating_rows:
        ratings_ws.append_rows(rating_rows, value_input_option="RAW")

    print(f"{len(new_rows)} new reviews, {len(rating_rows)} rating snapshots")


if __name__ == "__main__":
    main()
