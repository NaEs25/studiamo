import re
import httpx
from typing import Optional
from app.config import get_config

def extract_video_id(url: str) -> str:
    """Extracts the YouTube 11-character video ID from various link formats using regex
    and query string parsing fallbacks to support desktop, mobile, shorts, and music URLs."""
    if not url:
        return ""
        
    url = url.strip()
    
    # 1. Regex patterns for different URL formats
    patterns = [
        r'(?:v=|\/v\/|embed\/|youtu\.be\/|shorts\/|watch\?v=)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
            
    # 2. Query string parsing fallback
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        if parsed.netloc in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            query = parse_qs(parsed.query)
            if 'v' in query and len(query['v']) > 0:
                return query['v'][0]
        elif parsed.netloc == 'youtu.be':
            return parsed.path.strip('/')
    except Exception:
        pass
        
    return ""

def is_valid_duration(duration_str: str) -> bool:
    """Checks a scraped MM:SS/H:MM:SS duration string falls within the 3-30 minute
    recommendation window. Missing or unparseable durations are allowed through
    deliberately, since this filter can't call a video unreasonable without a value."""
    if not duration_str or duration_str == "N/A":
        return True
    parts = str(duration_str).split(":")
    try:
        if len(parts) == 2:
            sec = int(parts[0]) * 60 + int(parts[1])
            return 180 <= sec <= 1800
        elif len(parts) == 3:
            sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 180 <= sec <= 1800
    except Exception:
        pass
    return True

def get_video_metadata(video_id: str) -> dict:
    """Fetches video metadata (title, author, thumbnail) using the YouTube Data API if key is present,
    otherwise falls back to the keyless YouTube OEmbed endpoint."""
    api_key = get_config("YOUTUBE_API_KEY")
    
    if api_key:
        try:
            url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={api_key}"
            response = httpx.get(url, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("items"):
                    snippet = data["items"][0]["snippet"]
                    return {
                        "title": snippet.get("title", ""),
                        "author": snippet.get("channelTitle", ""),
                        "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"),
                        "description": snippet.get("description", "")
                    }
        except Exception as e:
            print(f"YouTube Data API error: {e}")

    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = httpx.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            return {
                "title": data.get("title", f"YouTube Video ({video_id})"),
                "author": data.get("author_name", "Unknown Channel"),
                "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                "description": ""
            }
    except Exception as e:
        print(f"OEmbed metadata extraction error: {e}")
        
    return {
        "title": f"YouTube Video ({video_id})",
        "author": "YouTube Creator",
        "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
        "description": ""
    }



def _parse_iso8601_duration(duration: str) -> Optional[int]:
    """Parses a YouTube contentDetails duration string (e.g. 'PT1H2M3S') into total seconds."""
    if not duration:
        return None
    match = re.match(r'^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$', duration)
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def get_video_duration_seconds(video_id: str) -> Optional[int]:
    """Fetches a video's duration via the official YouTube Data API. Returns None if no
    YOUTUBE_API_KEY is configured or the lookup fails , callers must treat that as 'unknown',
    not 'short enough', since there's no keyless official way to get exact duration."""
    api_key = get_config("YOUTUBE_API_KEY")
    if not api_key or not video_id:
        return None
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails&id={video_id}&key={api_key}"
        response = httpx.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            items = data.get("items")
            if items:
                iso_duration = items[0].get("contentDetails", {}).get("duration")
                return _parse_iso8601_duration(iso_duration)
    except Exception as e:
        print(f"YouTube duration lookup error: {e}")
    return None


def _format_duration_seconds(total_seconds: Optional[int]) -> str:
    """Formats a second count into 'MM:SS' or 'H:MM:SS', matching the shape is_valid_duration
    expects. Returns 'N/A' when the length couldn't be determined."""
    if total_seconds is None:
        return "N/A"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_view_count(view_count) -> str:
    """Formats a raw statistics.viewCount value into a compact display like '1.2M views'."""
    try:
        n = int(view_count)
    except (TypeError, ValueError):
        return "N/A"
    for divisor, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= divisor:
            value = f"{n / divisor:.1f}".rstrip("0").rstrip(".")
            return f"{value}{suffix} views"
    return f"{n} views"


def is_configured() -> bool:
    """Whether a YOUTUBE_API_KEY is set. Admin-only, env-only (see config.get_config), so
    this never varies by user."""
    return bool(get_config("YOUTUBE_API_KEY"))


def search_youtube_recommendations(query: str, max_results: int = 3) -> list:
    """Searches YouTube via the official Data API v3 (search.list, then videos.list for
    duration/views/age-rating), requesting strict safe search and dropping any age-restricted
    result. Returns an empty list if no YOUTUBE_API_KEY is configured or the API call fails:
    there is no scraping fallback, which was a ban/ToS risk this deliberately does not carry."""
    api_key = get_config("YOUTUBE_API_KEY")
    if not api_key:
        print("YouTube recommendations skipped: no YOUTUBE_API_KEY configured")
        return []

    try:
        search_url = "https://www.googleapis.com/youtube/v3/search"
        search_params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "safeSearch": "strict",
            "key": api_key,
        }
        search_response = httpx.get(search_url, params=search_params, timeout=10.0)
        if search_response.status_code != 200:
            print(f"YouTube search API error: {search_response.status_code} {search_response.text}")
            return []

        video_ids = [
            item["id"]["videoId"]
            for item in search_response.json().get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return []

        details_url = "https://www.googleapis.com/youtube/v3/videos"
        details_params = {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": api_key,
        }
        details_response = httpx.get(details_url, params=details_params, timeout=10.0)
        if details_response.status_code != 200:
            print(f"YouTube videos API error: {details_response.status_code} {details_response.text}")
            return []
        details_by_id = {item["id"]: item for item in details_response.json().get("items", [])}

        results = []
        for video_id in video_ids:
            details = details_by_id.get(video_id)
            if not details:
                continue
            content_details = details.get("contentDetails", {})
            if content_details.get("contentRating", {}).get("ytRating") == "ytAgeRestricted":
                continue

            snippet = details.get("snippet", {})
            duration_seconds = _parse_iso8601_duration(content_details.get("duration"))
            results.append({
                "title": snippet.get("title") or f"YouTube Video ({video_id})",
                "youtube_id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url")
                    or f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                "duration": _format_duration_seconds(duration_seconds),
                "views": _format_view_count(details.get("statistics", {}).get("viewCount")),
                "channel": snippet.get("channelTitle", ""),
            })
        return results
    except Exception as e:
        print(f"YouTube recommendations search error: {e}")
        return []
