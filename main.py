# main.py
import os
import asyncio
import logging
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("8370593149:AAHte_8ZopT602FMSaxOnz54WCO17PLTJ8I")
ADMIN_CHAT_ID = int(os.getenv("7258628659", "0"))

TELEGRAM_MAX_FILESIZE = 50 * 1024 * 1024  # 50 MB
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= Helper Functions ==================
def is_absolute(url):
    return bool(urlparse(url).netloc)

def make_abs(link, base):
    return link if is_absolute(link) else urljoin(base, link)

async def get_file_size(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=10) as resp:
                size = resp.headers.get("Content-Length")
                return int(size) if size and size.isdigit() else None
    except:
        return None

async def download_file(url, local_path):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=60) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                while True:
                    chunk = await resp.content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
    return local_path

async def fetch_page(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; Bot/1.0)"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=30) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return text, str(resp.url)

async def extract_media(url):
    html_text, base_url = await fetch_page(url)
    soup = BeautifulSoup(html_text, "lxml")

    images, videos, iframes = [], [], []

    # Images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src:
            images.append(make_abs(src, base_url))

    # Videos
    for video in soup.find_all("video"):
        src = video.get("src")
        if src:
            videos.append(make_abs(src, base_url))
        for source in video.find_all("source"):
            s = source.get("src")
            if s:
                videos.append(make_abs(s, base_url))

    # Iframes
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src")
        if src:
            iframes.append(make_abs(src, base_url))

    # Deduplicate
    return {
        "images": list(dict.fromkeys(images)),
        "videos": list(dict.fromkeys(videos)),
        "iframes": list(dict.fromkeys(iframes))
    }

# ================= Bot Handlers ===================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me any website/blog URL and I'll fetch public images/videos.\n"
        "For YouTube/TikTok/Facebook/Terebox links, I'll directly provide the video."
    )

async def process_url_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Send like this:\n/fetch <url>")
        return
    url = context.args[0].strip()
    msg = await update.message.reply_text(f"Processing: {url}")

    # Special handling for YouTube/TikTok/Facebook/Terebox
    if any(domain in url for domain in ["youtube.com", "youtu.be", "tiktok.com", "facebook.com", "tere.box"]):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Direct link detected: {url}")
        await msg.edit_text("Video link detected. Admin can download directly if under limit.")
        return

    try:
        media = await extract_media(url)
        images, videos, iframes = media["images"], media["videos"], media["iframes"]

        keyboard = [
            [InlineKeyboardButton(f"Images ({len(images)})", callback_data=f"show_images|{url}")],
            [InlineKeyboardButton(f"Videos ({len(videos)})", callback_data=f"show_videos|{url}")],
            [InlineKeyboardButton(f"Embeds ({len(iframes)})", callback_data=f"show_iframes|{url}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text("Choose what you want to see:", reply_markup=reply_markup)
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"Error: {str(e)}")

# ================= Callback Handler =================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    action, url = data[0], data[1]

    media = await extract_media(url)

    if action == "show_images":
        imgs = media["images"]
        if not imgs:
            await query.edit_message_text("No images found.")
            return
        for idx, img_url in enumerate(imgs[:10]):  # limit 10 for safety
            try:
                size = await get_file_size(img_url)
                if size and size > TELEGRAM_MAX_FILESIZE:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"[Too large] {img_url}")
                    continue
                local = f"tmp_img_{idx}.jpg"
                await download_file(img_url, local)
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(local, "rb"))
                os.remove(local)
            except Exception as e:
                logger.exception(e)
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Failed image: {img_url}")

    elif action == "show_videos":
        vids = media["videos"]
        if not vids:
            await query.edit_message_text("No videos found.")
            return
        text = ""
        for idx, v_url in enumerate(vids):
            text += f"{idx+1}. {v_url}\n[Download]({v_url})\n\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

    elif action == "show_iframes":
        embeds = media["iframes"]
        if not embeds:
            await query.edit_message_text("No embedded videos found.")
            return
        text = ""
        for idx, e_url in enumerate(embeds):
            text += f"{idx+1}. {e_url}\n[Download]({e_url})\n\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

# ================= Manual URL Handler =================
async def manual_url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        context.args = [text]
        await process_url_cmd(update, context)
    else:
        await update.message.reply_text("Send a valid URL to fetch media.")

# ================= Main =================
async def main():
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        print("Set BOT_TOKEN and ADMIN_CHAT_ID in .env")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("fetch", process_url_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_url_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^show_"), button_callback))
    print("Bot started...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())