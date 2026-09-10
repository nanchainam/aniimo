"""Collect Thai and Indonesian YouTube discussion of Aniimo into Google Sheets."""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import gspread

API_KEY = os.environ["YOUTUBE_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
API = "https://www.googleapis.com/youtube/v3/"

SEARCHES = {
    "TH": [("Aniimo", "th", "TH"), ("Aniimo เกม", "th", "TH")],
    "ID": [("Aniimo", "id", "ID"), ("Aniimo game", "id", "ID")],
}

VIDEOS_PER_SEARCH = 10
COMMENTS_PER_VIDEO = 50
LOOKBACK_DAYS = 3


def api_get(endpoint, params):
    params["key"] = API_KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def search_videos(query, relevance_language, region):
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    data = api_get("search", {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": VIDEOS_PER_SEARCH,
        "order": "date",
        "publishedAfter": published_after,
        "relevanceLanguage": relevance_language,
        "regionCode": region,
    })
    return data.get("items", [])


def fetch_comments(video_id):
    try:
        data = api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": COMMENTS_PER_VIDEO,
            "order": "relevance",
            "textFormat": "plainText",
        })
    except Exception as e:
        # Comments disabled on a video is a 403 and is normal, not a failure.
        print(f"  comments unavailable for {video_id}: {e}")
        return []
    return data.get("items", [])


def main():
    gc = gspread.service_account_from_dict(
        json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    )
    ws = gc.open_by_key(SHEET_ID).worksheet("raw_mentions")

    seen = set(ws.col_values(1))
    collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows = []

    for market, searches in SEARCHES.items():
        video_ids = {}
        for query, lang, region in searches:
            try:
                items = search_videos(query, lang, region)
            except Exception as e:
                print(f"search failed for {market} '{query}': {e}")
                continue
            for item in items:
                video_ids[item["id"]["videoId"]] = item["snippet"]

        print(f"{market}: {len(video_ids)} videos")

        for video_id, snippet in video_ids.items():
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            mention_id = f"yt_{market}_video_{video_id}"
            if mention_id not in seen:
                seen.add(mention_id)
                title = snippet.get("title", "")
                description = snippet.get("description", "")
                new_rows.append([
                    mention_id,
                    "youtube_video",
                    market,
                    video_url,
                    snippet.get("channelTitle", ""),
                    f"{title}\n\n{description}",
                    "",
                    snippet.get("publishedAt", ""),
                    collected_at,
                ])

            for thread in fetch_comments(video_id):
                top = thread["snippet"]["topLevelComment"]
                comment_id = top["id"]
                mention_id = f"yt_{market}_comment_{comment_id}"
                if mention_id in seen:
                    continue
                seen.add(mention_id)
                c = top["snippet"]
                new_rows.append([
                    mention_id,
                    "youtube_comment",
                    market,
                    f"{video_url}&lc={comment_id}",
                    c.get("authorDisplayName", ""),
                    c.get("textOriginal", ""),
                    c.get("likeCount", ""),
                    c.get("publishedAt", ""),
                    collected_at,
                ])

    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")

    print(f"{len(new_rows)} new videos and comments")


if __name__ == "__main__":
    main()
