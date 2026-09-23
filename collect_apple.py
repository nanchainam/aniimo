"""Collect App Store reviews and ratings for TH, ID and VN."""
import json
import os
import time
import urllib.request
from html.parser import HTMLParser
from datetime import datetime, timezone
import gspread

APP_ID = os.environ["APPLE_APP_ID"].strip()
if not APP_ID.isdigit():
    raise ValueError("APPLE_APP_ID must be a numeric App Store ID")
SHEET_ID = os.environ["SHEET_ID"]
MARKETS = ["th", "id", "vn"]
MAX_PAGES = 5

def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)

def fetch_rss_reviews(country):
    entries = []
    for page in range(1, MAX_PAGES + 1):
        url = (f"https://itunes.apple.com/{country}/rss/customerreviews"
               f"/page={page}/id={APP_ID}/sortBy=mostRecent/json")
        batch = fetch_json(url)["feed"].get("entry", [])
        if not batch:
            break
        entries.extend(batch)
    return entries

class ReviewPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "serialized-server-data":
            self.capture = True
    def handle_endtag(self, tag):
        if tag == "script":
            self.capture = False
    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

def parse_web_reviews(html, country):
    parser = ReviewPageParser()
    parser.feed(html)
    if not parser.parts:
        raise ValueError("App Store review page schema missing")
    payload = json.loads("".join(parser.parts))
    entries = {}
    for page in payload.get("data", []):
        intent = page.get("intent", {})
        if str(intent.get("id")) != APP_ID or intent.get("storefront") != country:
            raise ValueError("App Store app or storefront mismatch")
        shelf = page.get("data", {}).get("shelfMapping", {}).get("allProductReviews")
        if shelf is None:
            raise ValueError("App Store review shelf missing")
        for item in shelf.get("items", []):
            r = item.get("review", {})
            if not r.get("id") or not str(r.get("contents", "")).strip():
                continue
            datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
            if r.get("rating") not in [1, 2, 3, 4, 5]:
                raise ValueError("Invalid review rating")
            entries[str(r["id"])] = {
                "id": {"label": str(r["id"])},
                "author": {"name": {"label": r.get("reviewerName", "")}},
                "title": {"label": r.get("title", "")},
                "content": {"label": r["contents"]},
                "im:rating": {"label": str(r["rating"])},
                "updated": {"label": r["date"]},
            }
    return list(entries.values())

def fetch_reviews(country):
    try:
        entries = fetch_rss_reviews(country)
    except Exception as e:
        print(f"RSS failed for {country.upper()}: {e}; trying public review page")
        entries = []
    if entries:
        print(f"{country.upper()}: {len(entries)} reviews from RSS")
        return entries
    url = f"https://apps.apple.com/{country}/app/aniimo/id{APP_ID}?see-all=reviews"
    with urllib.request.urlopen(url, timeout=30) as response:
        entries = parse_web_reviews(response.read().decode("utf-8"), country)
    print(f"{country.upper()}: {len(entries)} reviews from public page (page sample, not all reviews)")
    return entries

def fetch_detail(country):
    url = f"https://itunes.apple.com/lookup?id={APP_ID}&country={country}"
    for attempt in range(4):
        results = fetch_json(url).get("results", [])
        if results:
            return results[0]
        time.sleep(5 * (attempt + 1))
    return None

def main():
    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]))
    sheet = gc.open_by_key(SHEET_ID)
    mentions_ws = sheet.worksheet("raw_mentions")
    ratings_ws = sheet.worksheet("store_ratings")
    seen = set(mentions_ws.col_values(1))
    seen_reviews = {value.split("_", 2)[2] for value in seen if value.startswith("apple_") and len(value.split("_", 2)) == 3}
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows, rating_rows = [], []
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
            review_id = mention_id.split("_", 2)[2]
            if mention_id in seen or review_id in seen_reviews:
                continue
            seen.add(mention_id)
            seen_reviews.add(review_id)
            new_rows.append([
                mention_id, "app_store", market, listing_url,
                r["author"]["name"]["label"],
                f"{r['title']['label']}\n\n{r['content']['label']}",
                r["im:rating"]["label"], r["updated"]["label"], collected_at,
            ])
        try:
            detail = fetch_detail(country)
            if detail is None:
                print(f"rating snapshot unavailable for {market}: lookup returned nothing")
            else:
                rating_rows.append([
                    collected_at, "app_store", market,
                    detail.get("averageUserRating", ""),
                    detail.get("userRatingCount", ""), "", "", "", "", "",
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
