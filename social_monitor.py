import time
import threading
import requests
import logging
from flask import Flask
from bs4 import BeautifulSoup
from datetime import datetime
import traceback

# إعداد اللوجز
logging.basicConfig(level=logging.INFO)

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435043389669376061/VOvGXZs2XUz3-B9WKkd432u8EUVop5AWL3ro8GJJksKrnLqQ9AGfvOUAPON66ZkbjHih"

# الصفحات اللي المراقبة
SOURCES = {
    "facebook": {
        "url": "https://www.facebook.com/csgocasescom/",
        "interval": 15 * 60,  # 15 دقيقة
        "last_post": None,
    },
    "instagram": {
        "url": "https://www.instagram.com/csgocasescom/",
        "interval": 30 * 60,  # 30 دقيقة
        "last_post": None,
    },
    "x": {
        "url": "https://x.com/csgocasescom",
        "interval": 20 * 60,  # 20 دقيقة
        "last_post": None,
    },
}

# لتقليل احتمالات الحظر
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
]

last_activity_time = time.time()


def send_discord_notification(source, message):
    """إرسال إشعار لديسكورد"""
    data = {"content": message}
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=10)
        if r.status_code == 204:
            logging.info(f"Sent Discord notification for {source}")
        else:
            logging.warning(f"Discord response ({r.status_code}): {r.text}")
    except Exception as e:
        logging.error(f"Failed to send Discord notification: {e}")


def fetch_html(url):
    """تحميل الصفحة وارجاع محتواها"""
    headers = {"User-Agent": USER_AGENTS[int(time.time()) % len(USER_AGENTS)]}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.text


def detect_latest(source, html):
    """استخراج آخر بوست أو تحديث"""
    soup = BeautifulSoup(html, "html.parser")

    if source == "facebook":
        posts = soup.find_all("a", href=True)
        for p in posts:
            if "/posts/" in p["href"]:
                return p["href"]

    elif source == "instagram":
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if '"@type": "ImageObject"' in script.text:
                return script.text.strip()[:200]

    elif source == "x":
        links = soup.find_all("a", href=True)
        for l in links:
            if "/status/" in l["href"]:
                return l["href"]

    return None


def monitor_loop():
    """حلقة المراقبة الرئيسية"""
    global last_activity_time
    logging.info("Starting monitor.")
    send_discord_notification(
        "system",
        f"🟢 **Monitor restarted!**\nRender service was redeployed or restarted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    )

    while True:
        try:
            now = time.time()
            activity_happened = False

            for name, data in SOURCES.items():
                url = data["url"]
                interval = data["interval"]
                last_check = data.get("last_check", 0)

                if now - last_check < interval:
                    logging.info(f"Skipping {name} (interval not reached)")
                    continue

                logging.info(f"Checking {name} -> {url}")
                SOURCES[name]["last_check"] = now

                html = fetch_html(url)
                latest_post = detect_latest(name, html)

                if latest_post and latest_post != data["last_post"]:
                    SOURCES[name]["last_post"] = latest_post
                    logging.info(f"New post detected for {name}!")
                    send_discord_notification(
                        name,
                        f"🔔 **New post detected on {name}!**\n@everyone\n{url}\n{latest_post}",
                    )
                    activity_happened = True
                else:
                    logging.info(f"No new posts for {name}")

            # تحديث آخر نشاط
            if activity_happened:
                last_activity_time = now

            # لو مر أكتر من ساعة من غير أي نشاط أو تحديث
            if now - last_activity_time > 3600:
                send_discord_notification(
                    "system", "🔄 **No updates detected for 1 hour!**\nThe monitor is still running fine."
                )
                last_activity_time = now

            time.sleep(60)

        except Exception:
            error_msg = f"❌ **Error occurred in monitor loop:**\n```\n{traceback.format_exc()}\n```"
            logging.error(error_msg)
            send_discord_notification("error", error_msg)
            time.sleep(60)


# Flask للتشغيل على Render
app = Flask(__name__)


@app.route("/")
def home():
    return "✅ Social monitor is running! " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def keep_alive():
    """Ping ذاتي كل 10 دقايق"""
    while True:
        try:
            requests.get("https://social-monitor.onrender.com", timeout=10)
            logging.info("Self-ping successful.")
        except Exception as e:
            logging.warning(f"Self-ping failed: {e}")
        time.sleep(600)  # كل 10 دقايق


if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    app.run(host="0.0.0.0", port=10000)
