"""Collect Thai and Indonesian YouTube discussion of Aniimo into Google Sheets.

Market is deliberately left blank. YouTube's relevanceLanguage and regionCode are
hints, not filters, so the search that found a video says nothing reliable about
who is watching or commenting. Enrichment detects the real language of each row
and fills market in afterwards.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import gspread

API_KEY = os.environ["YOUTUBE_API_KEY"]
SHEET_ID = os.environ["SHEET_ID"]
API = "https://www.googleapis.com/youtube/v3/"

SEARCHES = [
    ("Aniimo", "th", "TH"),
    ("Aniimo เกม", "th", "TH"),
    ("Aniimo", "id", "ID"),
    ("Aniimo game", "id", "ID"),
]

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
        # Comments disabled on a video returns 403. Normal, not a failure.
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

    # One pool across all searches, so a video found by several queries is
    # collected once rather than duplicated per market.
    videos = {}
    for query, lang, region in SEARCHES:
        try:
            for item in search_videos(query, lang, region):
                videos[item["id"]["videoId"]] = item["snippet"]
        except Exception as e:
            print(f"search failed for '{query}' ({region}): {e}")

    print(f"{len(videos)} unique videos")

    for video_id, snippet in videos.items():
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        mention_id = f"yt_video_{video_id}"
        if mention_id not in seen:
            seen.add(mention_id)
            new_rows.append([
                mention_id,
                "youtube_video",
                "",
                video_url,
                snippet.get("channelTitle", ""),
                f"{snippet.get('title', '')}\n\n{snippet.get('description', '')}",
                "",
                snippet.get("publishedAt", ""),
                collected_at,
            ])

        for thread in fetch_comments(video_id):
            top = thread["snippet"]["topLevelComment"]
            comment_id = top["id"]
            mention_id = f"yt_comment_{comment_id}"
            if mention_id in seen:
                continue
            seen.add(mention_id)
            c = top["snippet"]
            new_rows.append([
                mention_id,
                "youtube_comment",
                "",
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
