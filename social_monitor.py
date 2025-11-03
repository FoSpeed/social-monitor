"""
Social media monitor (Facebook, Instagram, X) - HTML scraping version
Sends notifications to a Discord webhook when a new post is detected on any of the three accounts.

How it works
- Periodically (every 10 minutes by default) downloads the public page HTML for each account URL.
- Attempts multiple heuristics to extract a stable "latest post id / url":
  * Open Graph tags (og:url / og:description)
  * JSON blobs embedded in the page (e.g. window._sharedData for Instagram)
  * Search for typical post URLs ("/username/status/", "/p/", "/posts/")
- Compares to the last seen value saved in last_seen.json. If different => new post.
- Sends a message to a configured Discord webhook with the account name, detected post url (if found) and snippet.

Notes & limitations
- Scraping public HTML is brittle: sites can change markup, and some pages may require JavaScript to render.
- Facebook/Instagram/X often obfuscate content; this script tries reasonable fallbacks but may need tweaks per account.
- Don't run scraping too frequently. You're using 10 minutes which is reasonable.

Requirements
- Python 3.8+
- pip install requests beautifulsoup4 schedule

Usage
1. Edit the CONFIG section below to set DISCORD_WEBHOOK_URL and the list of monitored URLs.
2. Run: python social_monitor.py

"""

import json
import re
import time
import logging
from pathlib import Path
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ---------------- CONFIG -----------------
CHECK_INTERVAL_SECONDS = 10 * 60  # 10 minutes
LAST_SEEN_FILE = Path("last_seen.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Replace with your Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"

# The three pages you asked to monitor
PAGES = {
    "facebook": "https://www.facebook.com/csgocasescom/",
    "instagram": "https://www.instagram.com/csgocasescom/",
    "x": "https://x.com/csgocasescom"
}
# ------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def load_last_seen() -> dict:
    if LAST_SEEN_FILE.exists():
        try:
            return json.loads(LAST_SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            logging.exception("Failed to read last_seen.json, starting fresh")
            return {}
    return {}


def save_last_seen(data: dict):
    LAST_SEEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_html(url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception:
        logging.exception(f"Failed to fetch {url}")
        return None


def extract_latest_from_facebook(html: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to extract a stable latest-post identifier and a human snippet from a Facebook page HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Try og:url
    og_url = soup.find("meta", property="og:url")
    if og_url and og_url.get("content"):
        return og_url["content"], soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None

    # Look for links that look like /{page}/posts/{id} or /story.php?story_fbid=
    text = html
    m = re.search(r"(/[^\s'\"]+/posts/\d+)", text)
    if m:
        candidate = m.group(1)
        url = requests.compat.urljoin(base_url, candidate)
        return url, None

    m = re.search(r"story_fbid=([0-9]+)", text)
    if m:
        url = f"{base_url.rstrip('/')}/posts/{m.group(1)}"
        return url, None

    # Fallback: use first large div id or page html hash
    snippet = (soup.title.string if soup.title else None)
    return base_url, snippet


def extract_latest_from_instagram(html: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) og:url
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        return og["content"], (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)

    # 2) Look for window._sharedData JSON
    m = re.search(r"window\._sharedData\s*=\s*(\{.+?\});</script>", html, flags=re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            # traverse to entry data if available
            user = data.get("entry_data", {}).get("ProfilePage", [{}])[0]
            if user:
                # try to find latest media
                timeline_media = user.get("graphql", {}).get("user", {}).get("edge_owner_to_timeline_media", {}).get("edges", [])
                if timeline_media:
                    node = timeline_media[0].get("node", {})
                    shortcode = node.get("shortcode")
                    if shortcode:
                        url = f"https://www.instagram.com/p/{shortcode}/"
                        caption = node.get("edge_media_to_caption", {}).get("edges", [])
                        text = caption[0]["node"]["text"] if caption else None
                        return url, text
        except Exception:
            logging.exception("Failed to parse window._sharedData JSON")

    # 3) Fallbacks: look for /p/{shortcode}/ links
    m = re.search(r"(/p/[A-Za-z0-9_-]+)/", html)
    if m:
        url = requests.compat.urljoin(base_url, m.group(1) + "/")
        return url, None

    return base_url, None


def extract_latest_from_x(html: str, base_url: str) -> Tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # 1) og:url often points to profile or latest tweet
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        content = og["content"]
        # If og:url points at a status, return that
        if "/status/" in content or "/statuses/" in content:
            return content, (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)

    # 2) search for /{user}/status/{id}
    m = re.search(r"/(?:[A-Za-z0-9_]+)/status/([0-9]+)", html)
    if m:
        status_id = m.group(1)
        # Try to extract username from base_url
        username = base_url.rstrip("/").split("/")[-1]
        url = f"https://x.com/{username}/status/{status_id}"
        return url, None

    # 3) fallback: return profile url
    return base_url, None


EXTRACTORS = {
    "facebook": extract_latest_from_facebook,
    "instagram": extract_latest_from_instagram,
    "x": extract_latest_from_x
}


def detect_latest(page_key: str, url: str) -> Tuple[Optional[str], Optional[str]]:
    html = fetch_html(url)
    if not html:
        return None, None
    extractor = EXTRACTORS.get(page_key)
    if not extractor:
        return None, None
    try:
        return extractor(html, url)
    except Exception:
        logging.exception(f"Extractor failed for {page_key} {url}")
        return None, None


def send_discord_notification(webhook_url: str, content: str, username: str = "SocialMonitor") -> bool:
    if not webhook_url or "REPLACE_WITH_YOURS" in webhook_url:
        logging.error("Discord webhook URL not set. Edit DISCORD_WEBHOOK_URL in the script.")
        return False
    payload = {"content": content, "username": username}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
        return True
    except Exception:
        logging.exception("Failed to send Discord notification")
        return False


def make_message(platform: str, detected_url: Optional[str], snippet: Optional[str]) -> str:
    lines = [f"🔔 New post detected on **{platform}**"]
    if detected_url:
        lines.append(f"{detected_url}")
    if snippet:
        # shorten snippet
        s = snippet.strip().replace("\n", " ")
        if len(s) > 300:
            s = s[:300] + "..."
        lines.append(f"> {s}")
    return "\n".join(lines)


def main_loop():
    last_seen = load_last_seen()

    logging.info("Starting monitor. Will check every %s seconds", CHECK_INTERVAL_SECONDS)

    while True:
        for key, url in PAGES.items():
            logging.info("Checking %s -> %s", key, url)
            latest_id, snippet = detect_latest(key, url)
            if latest_id is None:
                logging.warning("Could not detect latest for %s", key)
                continue

            previous = last_seen.get(key)
            # If we have a previous and it's different => new post
            if previous is None:
                logging.info("No previous record for %s - saving current as baseline", key)
                last_seen[key] = latest_id
                save_last_seen(last_seen)
            elif latest_id != previous:
                logging.info("New post on %s detected: %s", key, latest_id)
                message = make_message(key, latest_id, snippet)
                ok = send_discord_notification(DISCORD_WEBHOOK_URL, message)
                if ok:
                    last_seen[key] = latest_id
                    save_last_seen(last_seen)
                else:
                    logging.error("Notification failed for %s", key)
            else:
                logging.info("No new post on %s", key)

        logging.info("Sleeping %s seconds...", CHECK_INTERVAL_SECONDS)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logging.info("Stopped by user")
