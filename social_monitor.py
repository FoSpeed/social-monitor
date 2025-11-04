import json
import re
import time
import logging
from pathlib import Path
import threading
import os

import requests
from bs4 import BeautifulSoup
from flask import Flask

# ---------------- CONFIG -----------------
CHECK_INTERVAL_SECONDS = 10 * 60  # 10 دقائق
LAST_SEEN_FILE = Path("last_seen.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."  # ضع رابطك هنا
PAGES = {
    "facebook": "https://www.facebook.com/csgocasescom/",
    "instagram": "https://www.instagram.com/csgocasescom/",
    "x": "https://x.com/csgocasescom"
}
# ------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- Helper functions ----------------

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

def fetch_html(url: str, timeout: int = 20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception:
        logging.exception(f"Failed to fetch {url}")
        return None

# ---------------- Extractors ----------------

def extract_latest_from_facebook(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    og_url = soup.find("meta", property="og:url")
    if og_url and og_url.get("content"):
        return og_url["content"], (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)
    m = re.search(r"(/[^\s'\"]+/posts/\d+)", html)
    if m:
        url = requests.compat.urljoin(base_url, m.group(1))
        return url, None
    m = re.search(r"story_fbid=([0-9]+)", html)
    if m:
        url = f"{base_url.rstrip('/')}/posts/{m.group(1)}"
        return url, None
    return base_url, (soup.title.string if soup.title else None)

def extract_latest_from_instagram(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        return og["content"], (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)
    m = re.search(r"window\._sharedData\s*=\s*(\{.+?\});</script>", html, flags=re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            user = data.get("entry_data", {}).get("ProfilePage", [{}])[0]
            if user:
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
    m = re.search(r"(/p/[A-Za-z0-9_-]+)/", html)
    if m:
        url = requests.compat.urljoin(base_url, m.group(1) + "/")
        return url, None
    return base_url, None

def extract_latest_from_x(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        content = og["content"]
        if "/status/" in content or "/statuses/" in content:
            return content, (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)
    m = re.search(r"/(?:[A-Za-z0-9_]+)/status/([0-9]+)", html)
    if m:
        username = base_url.rstrip("/").split("/")[-1]
        url = f"https://x.com/{username}/status/{m.group(1)}"
        return url, None
    return base_url, None

EXTRACTORS = {
    "facebook": extract_latest_from_facebook,
    "instagram": extract_latest_from_instagram,
    "x": extract_latest_from_x
}

def detect_latest(page_key: str, url: str):
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

# ---------------- Discord Notification ----------------

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

def make_message(platform: str, detected_url: str, snippet: str) -> str:
    lines = [f"🔔 New post detected on **{platform}**"]
    if detected_url:
        lines.append(detected_url)
    if snippet:
        s = snippet.strip().replace("\n", " ")
        if len(s) > 300:
            s = s[:300] + "..."
        lines.append(f"> {s}")
    return "\n".join(lines)

# ---------------- Main background loop ----------------

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
            if previous is None:
                last_seen[key] = latest_id
                save_last_seen(last_seen)
            elif latest_id != previous:
                message = make_message(key, latest_id, snippet)
                ok = send_discord_notification(DISCORD_WEBHOOK_URL, message)
                if ok:
                    last_seen[key] = latest_id
                    save_last_seen(last_seen)
        time.sleep(CHECK_INTERVAL_SECONDS)

# ---------------- Flask web service (dummy) ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Social monitor is running!"

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
