import requests, time, logging, threading
from bs4 import BeautifulSoup
from flask import Flask

# إعداد اللوجات
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# رابط Webhook الخاص بـ Discord
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"

# روابط الصفحات اللي البوت هيتابعها
PAGES = {
    "facebook": "https://www.facebook.com/csgocasescom/",
    "instagram": "https://www.instagram.com/csgocasescom/",
    "x": "https://x.com/csgocasescom"
}

# الفواصل الزمنية (بالثواني)
CHECK_INTERVALS = {
    "facebook": 10 * 60,   # 10 دقائق
    "instagram": 30 * 60,  # 30 دقيقة
    "x": 10 * 60           # 10 دقائق
}

# تخزين آخر ID منشور شافه البوت
last_seen = {}

# إعداد Flask (عشان Render ما يوقفوش)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running fine!"

# دالة ترسل إشعار إلى Discord
def send_discord_message(platform, post_url):
    data = {
        "content": f"📢 **منشور جديد على {platform.capitalize()}!**\n{post_url}"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        logger.info(f"Sent Discord notification for {platform}")
    except Exception as e:
        logger.error(f"Failed to send Discord message: {e}")

# دالة تجيب HTML الصفحة
def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.text

# دالة تحاول تكتشف أحدث بوست
def detect_latest(platform, url):
    try:
        html = fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        if platform == "facebook":
            snippet = soup.title.string if soup.title else ""
        elif platform == "instagram":
            snippet = soup.find("meta", property="og:title")
            snippet = snippet["content"] if snippet else ""
        elif platform == "x":
            snippet = soup.find("meta", property="og:title")
            snippet = snippet["content"] if snippet else ""
        else:
            snippet = ""
        return snippet.strip() if snippet else None
    except Exception as e:
        logger.warning(f"Could not detect latest for {platform}: {e}")
        return None

# اللوب الرئيسي
def main_loop():
    while True:
        for platform, url in PAGES.items():
            interval = CHECK_INTERVALS[platform]
            now = time.time()

            if platform in last_seen and (now - last_seen[platform]["time"]) < interval:
                logger.info(f"Skipping {platform} (interval not reached)")
                continue

            logger.info(f"Checking {platform} -> {url}")
            snippet = detect_latest(platform, url)

            if not snippet:
                logger.warning(f"Could not detect latest for {platform}")
            else:
                prev = last_seen.get(platform, {}).get("snippet")
                if prev != snippet:
                    logger.info(f"New post detected for {platform}!")
                    send_discord_message(platform, url)
                    last_seen[platform] = {"snippet": snippet, "time": now}
                else:
                    logger.info(f"No new posts for {platform}")

            last_seen.setdefault(platform, {"snippet": snippet or "", "time": now})
        time.sleep(60)

# تشغيل اللوب في thread منفصل
threading.Thread(target=main_loop, daemon=True).start()

if __name__ == "__main__":
    logger.info("Starting monitor.")
    app.run(host="0.0.0.0", port=10000)
