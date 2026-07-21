from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Any

from .util import iso_utc, parse_datetime, utc_now


def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)


def check_youtube_url(connection, url: str, *, timeout_seconds: int = 6, cache_hours: int = 24) -> str:
    cached = connection.execute(
        "SELECT status, checked_at_utc FROM video_checks WHERE url=? ORDER BY checked_at_utc DESC LIMIT 1",
        (url,),
    ).fetchone()
    if cached:
        checked = parse_datetime(cached["checked_at_utc"])
        if checked and utc_now() - checked < timedelta(hours=cache_hours):
            return str(cached["status"])
    status, http_status, final_url, details = "unknown", None, None, None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "TrainLab/0.1 (+local health report)"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            http_status = response.status
            final_url = response.geturl()
            body = response.read(256_000).decode("utf-8", errors="ignore").lower()
            invalid_markers = ("video unavailable", "this video isn't available", "private video")
            status = "invalid" if any(marker in body for marker in invalid_markers) else ("valid" if response.status == 200 else "unknown")
    except urllib.error.HTTPError as error:
        http_status = error.code
        status = "invalid" if error.code in {404, 410} else "unknown"
        details = str(error)
    except Exception as error:
        details = f"{type(error).__name__}: {error}"[:1000]
    connection.execute(
        """INSERT INTO video_checks(url, checked_at_utc, status, http_status, final_url, details)
           VALUES(?,?,?,?,?,?)""",
        (url, iso_utc(), status, http_status, final_url, details),
    )
    return status


def select_video(connection, exercise: dict[str, Any]) -> dict[str, str]:
    for candidate in exercise.get("youtube_candidates", []):
        if check_youtube_url(connection, candidate) == "valid":
            return {"url": candidate, "kind": "video"}
    return {"url": youtube_search_url(exercise["youtube_search_query"]), "kind": "search"}
