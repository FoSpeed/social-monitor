import json
import re
import time
import logging
from pathlib import Path
import threading
import random
import os

import requests
from bs4 import BeautifulSoup
from flask import Flask

# ---------------- CONFIG -----------------
CHECK_INTERVAL_SECONDS = 10 * 60  # 10 دقائق لباقي الصفحات
INSTAGRAM_INTERVAL_SECONDS = 20 * 60  # 20 دقيقة لإنستاجرام
LAST_SEEN_FILE = Path("last_seen.json")
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"  # ضع رابطك هنا

PAGES = {
    "facebook": "https://www.facebook.com/csgocasescom/",
    "instagram": "https://www.instagram.com/csgocasescom/",
    "x": "https://x.com/csgocasescom"
}

# Rotate user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
]

# Optional: proxies from env
PROXIES = [p.strip() for p in os.environ.get("PROXIES", "").split(",") if p.strip()]

# Cooldown dict to avoid hammering 429
COOLDOWNS = {}  # url -> timestamp

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

# ---------------- Fetch with retries, UA rotation, cooldown ----------------
def fetch_html(url: str, timeout: int = 20, max_retries: int = 4):
    now = time.time()
    if COOLDOWNS.get(url, 0) > now:
        logging.warning("In cooldown for %s until %s", url, time.ctime(COOLDOWNS[url]))
        return None

    attempt = 0
    backoff = 1.0
    while attempt < max_retries:
        attempt += 1
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.google.com/"
        }
        proxies = {"http": random.choice(PROXIES), "https": random.choice(PROXIES)} if PROXIES else None

        try:
            r = requests.get(url, headers=headers, timeout=timeout, proxies=proxies)
            if r.status_code == 429:
                # dynamic cooldown: يزيد حسب عدد المحاولات
                COOLDOWNS[url] = time.time() + min(1800, 60*attempt)  
                logging.warning("Received 429 from %s — setting cooldown until %s", url, time.ctime(COOLDOWNS[url]))
                return None
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            logging.warning("Request failed for %s (attempt %s): %s", url, attempt, e)

        sleep_time = backoff + random.random()*0.5
        logging.info("Retrying %s in %.1f seconds...", url, sleep_time)
        time.sleep(sleep_time)
        backoff *= 2

    logging.error("Failed to fetch %s after %s attempts", url, max_retries)
    COOLDOWNS[url] = time.time() + 300  # short cooldown
    return None

# ---------------- Extractors ----------------
def extract_latest_from_facebook(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    og_url = soup.find("meta", property="og:url")
    if og_url and og_url.get("content"):
        return og_url["content"], (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)
    m = re.search(r"(/[^\s'\"]+/posts/\d+)", html)
    if m:
        return requests.compat.urljoin(base_url, m.group(1)), None
    m = re.search(r"story_fbid=([0-9]+)", html)
    if m:
        return f"{base_url.rstrip('/')}/posts/{m.group(1)}", None
    return base_url, (soup.title.string if soup.title else None)

def extract_latest_from_instagram(html, base_url):
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
            logging.exception("Failed to parse Instagram JSON")
    m = re.search(r"(/p/[A-Za-z0-9_-]+)/", html)
    if m:
        return requests.compat.urljoin(base_url, m.group(1) + "/"), None
    return base_url, None

def extract_latest_from_x(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        content = og["content"]
        if "/status/" in content or "/statuses/" in content:
            return content, (soup.find("meta", property="og:description").get("content") if soup.find("meta", property="og:description") else None)
    m = re.search(r"/(?:[A-Za-z0-9_]+)/status/([0-9]+)", html)
    if m:
        username = base_url.rstrip("/").split("/")[-1]
        return f"https://x.com/{username}/status/{m.group(1)}", None
    return base_url, None

EXTRACTORS = {
    "facebook": extract_latest_from_facebook,
    "instagram": extract_latest_from_instagram,
    "x": extract_latest_from_x
}

def detect_latest(page_key, url):
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

# ---------------- Discord ----------------
def send_discord_notification(webhook_url, content, username="SocialMonitor"):
    if not webhook_url or "REPLACE_WITH_YOURS" in webhook_url:
        logging.error("Discord webhook URL not set!")
        return False
    try:
        r = requests.post(webhook_url, json={"content": content, "username": username}, timeout=10)
        r.raise_for_status()
        return True
    except Exception:
        logging.exception("Failed to send Discord notification")
        return False

def make_message(platform, detected_url, snippet):
    lines = [f"🔔 New post detected on **{platform}**"]
    if detected_url:
        lines.append(detected_url)
    if snippet:
        s = snippet.strip().replace("\n"," ")
        if len(s) > 300:
            s = s[:300]+"..."
        lines.append(f"> {s}")
    return "\n".join(lines)

# ---------------- Main Loop ----------------
def main_loop():
    last_seen = load_last_seen()
    logging.info("Starting monitor.")
    last_checked = {}
    while True:
        now = time.time()
        for key, url in PAGES.items():
            interval = INSTAGRAM_INTERVAL_SECONDS if key == "instagram" else CHECK_INTERVAL_SECONDS
            if last_checked.get(key, 0) + interval > now:
                logging.info("Skipping %s (interval not reached)", key)
                continue
            last_checked[key] = now
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
                if send_discord_notification(DISCORD_WEBHOOK_URL, message):
                    last_seen[key] = latest_id
                    save_last_seen(last_seen)
        time.sleep(5)  # small sleep to prevent tight loop

# ---------------- Flask ----------------
app = Flask(__name__)
@app.route("/")
def home():
    return "Social monitor is running!"

if __name__ == "__main__":
    threading.Thread(target=main_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
