import time
import logging
import requests
from pathlib import Path
import json

# ---------------- CONFIG -----------------
CHECK_INTERVAL_SECONDS = {
    "facebook": 600,    # كل 10 دقائق
    "instagram": 1200,  # كل 20 دقيقة
    "x": 600            # كل 10 دقائق
}
LAST_SEEN_FILE = Path("last_seen.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"

# الصفحات اللي هنتابعها
PAGES = {
    "facebook": "https://www.facebook.com/csgocasescom/",
    "instagram": "https://www.instagram.com/csgocasescom/",
    "x": "https://x.com/csgocasescom"
}
# ------------------------------------------

logging.basicConfig(level=logging.INFO)

def load_last_seen():
    if LAST_SEEN_FILE.exists():
        with open(LAST_SEEN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_last_seen(data):
    with open(LAST_SEEN_FILE, "w") as f:
        json.dump(data, f)

def fetch_html(url):
    try:
        r = requests.get(url, headers=HEADERS)
        r.raise_for_status()
        return r.text
    except requests.exceptions.HTTPError as e:
        logging.warning("Request failed for %s: %s", url, e)
        return None
    except Exception as e:
        logging.warning("Error fetching %s: %s", url, e)
        return None

# دالة وهمية لتحديد أحدث بوست (ضع دالتك هنا)
def detect_latest(platform, url):
    html = fetch_html(url)
    if html is None:
        return None, None
    # مثال: ترجع id و snippet (لازم تعدل حسب HTML)
    return "dummy_id", "Latest post snippet"

def make_message(platform, latest_id, snippet):
    return f"New post on {platform}: {latest_id}\n{snippet}"

def send_discord_notification(webhook_url, message):
    try:
        r = requests.post(webhook_url, json={"content": message})
        r.raise_for_status()
        return True
    except Exception as e:
        logging.warning("Failed to send Discord message: %s", e)
        return False

def main_loop():
    last_seen = load_last_seen()
    last_checked = {key: 0 for key in PAGES}  # آخر مرة اتعمل فيها فحص لكل منصة

    logging.info("Starting monitor.")

    while True:
        now = time.time()
        for key, url in PAGES.items():
            interval = CHECK_INTERVAL_SECONDS.get(key, 600)
            if now - last_checked[key] < interval:
                logging.info("Skipping %s (interval not reached)", key)
                continue

            logging.info("Checking %s -> %s", key, url)
            latest_id, snippet = detect_latest(key, url)
            last_checked[key] = now

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
        time.sleep(5)  # منع اللوب من الدوران بسرعة كبيرة

if __name__ == "__main__":
    main_loop()
