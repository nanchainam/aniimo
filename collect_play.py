"""Collect Google Play reviews + rating snapshot for Aniimo (TH and ID) into Google Sheets."""

import json
import os
from datetime import datetime, timezone

import gspread
from google_play_scraper import Sort, app, reviews

PACKAGE_ID = os.environ["PLAY_PACKAGE_ID"]
SHEET_ID = os.environ["SHEET_ID"]
MARKETS = [("th", "th"), ("id", "id")]
REVIEWS_PER_RUN = 200


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

    for country, lang in MARKETS:
        market = country.upper()
        listing_url = (
            f"https://play.google.com/store/apps/details"
            f"?id={PACKAGE_ID}&hl={lang}&gl={country}"
        )

        try:
            result, _ = reviews(
                PACKAGE_ID,
                lang=lang,
                country=country,
                sort=Sort.NEWEST,
                count=REVIEWS_PER_RUN,
            )
        except Exception as e:
            print(f"review fetch failed for {market}: {e}")
            result = []

        for r in result:
            mention_id = f"play_{market}_{r['reviewId']}"
            if mention_id in seen:
                continue
            seen.add(mention_id)
            new_rows.append([
                mention_id,
                "google_play",
                market,
                listing_url,
                r["userName"],
                r["content"] or "",
                r["score"],
                r["at"].isoformat(timespec="seconds"),
                collected_at,
            ])

        try:
            detail = app(PACKAGE_ID, lang=lang, country=country)
            one, two, three, four, five = detail["histogram"]
            rating_rows.append([
                collected_at,
                "google_play",
                market,
                detail["score"],
                detail["ratings"],
                one, two, three, four, five,
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
