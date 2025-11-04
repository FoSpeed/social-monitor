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

# ---------------- Extractors (مثل الكود الأصلي) ----------------
# ضع هنا كل دوال extract_latest_from_facebook، instagram، x
# مع EXTRACTORS و detect_latest كما في سكربتك الأصلي

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
    # نبدأ الثريد الخلفي
    threading.Thread(target=main_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
