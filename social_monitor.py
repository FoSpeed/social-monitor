import time
import random
import requests
from flask import Flask
import logging

# إعداد اللوج
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Flask App
app = Flask(__name__)

# رابط Discord Webhook (بدّله بالرابط بتاعك)
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"

# المنصات والـ interval لكل واحدة (بالثواني)
PLATFORMS = {
    "facebook": {"url": "https://www.facebook.com/csgocasescom/", "interval": 600, "last_checked": 0},
    "instagram": {"url": "https://www.instagram.com/csgocasescom/", "interval": 1800, "last_checked": 0},  # 30 دقيقة
    "x": {"url": "https://x.com/csgocasescom", "interval": 600, "last_checked": 0},
}

# قائمة User-Agents للتبديل العشوائي
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0 Safari/537.36",
]

# بروكسي اختياري (سيبه None لو مش عايز تستخدمه)
PROXY = None
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None


# إرسال إشعار لديسكورد
def send_discord_message(message):
    try:
        payload = {"content": message}
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        logging.warning(f"Failed to send Discord message: {e}")


# فحص المنصة
def fetch_platform(platform):
    now = time.time()
    info = PLATFORMS[platform]

    # لو لسه ما عداش الوقت المحدد
    if now - info["last_checked"] < info["interval"]:
        logging.info(f"⏳ Skipping {platform} (interval not reached)")
        return

    info["last_checked"] = now
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    try:
        response = requests.get(info["url"], headers=headers, proxies=PROXIES, timeout=10)
        response.raise_for_status()
        logging.info(f"✅ Checked {platform} -> {info['url']}")
        send_discord_message(f"✅ {platform.capitalize()} check successful: {info['url']}")
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            logging.warning(f"⚠️ 429 Too Many Requests from {info['url']}")
            send_discord_message(f"⚠️ {platform.capitalize()} returned 429 (rate limit). Will retry later.")
        else:
            logging.warning(f"❌ HTTP error for {platform}: {e}")
            send_discord_message(f"❌ {platform.capitalize()} HTTP error: {e}")
    except Exception as e:
        logging.warning(f"❌ Request failed for {platform}: {e}")
        send_discord_message(f"❌ {platform.capitalize()} failed: {e}")


# الصفحة الرئيسية للـ Render
@app.route("/")
def home():
    return "✅ Social Monitor is running and checking pages periodically."


# Main loop
if __name__ == "__main__":
    logging.info("🚀 Starting social monitor service...")
    send_discord_message("🟢 Social Monitor started successfully!")

    while True:
        for platform in PLATFORMS:
            fetch_platform(platform)
        time.sleep(5)
