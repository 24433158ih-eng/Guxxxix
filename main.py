main.py - Final Modified Media Extractor Bot (Video/Embed Only, No Blocking)

import os
import re
import json
import logging
import asyncio
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
ContextTypes, filters
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")      # BotFather token
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # তোমার টেলিগ্রাম আইডি (admin)

সতর্কতা: টেলিগ্রামের|max file size| তথ্য পরিবর্তিত হতে পারে — বড় ভিডিও লিংক পাঠাও

TELEGRAM_MAX_FILESIZE = 50 * 1024 * 1024  # 50 MB (approx)
USER_AGENT = "Mozilla/5.0 (compatible; Bot/1.0; FinalVideoExtractor)"

Simple in-memory storage for results (Replacing DB/File storage)

Format: {cache_id: {"url": "...", "videos": [...]}}

RESULTS_CACHE = {}
CACHE_COUNTER = 1

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(name)

--- Utility & Cache Functions ---

def get_unique_cache_id():
"""Generates a unique ID for cache storage."""
global CACHE_COUNTER
CACHE_COUNTER += 1
return CACHE_COUNTER - 1

def save_to_cache(url, video_links):
"""Saves results to cache and returns a unique ID."""
cache_id = get_unique_cache_id()
RESULTS_CACHE[cache_id] = {"url": url, "videos": video_links}
return cache_id

def load_from_cache(cache_id):
"""Loads results from cache by ID."""
return RESULTS_CACHE.get(cache_id)

def is_absolute(url):
try:
return bool(urlparse(url).netloc)
except:
return False

def make_abs(link, base):
if not link: return None
try:
return urljoin(base, link).strip()
except:
return None

def is_video_link(url):
"""Checks if a URL has common video file extensions."""
if not isinstance(url, str): return False
# Use split to ignore query parameters like ?m=1
url = url.lower().split('?')[0].split('#')[0]
if re.search(r'.(mp4|webm|mov|mkv|avi|flv|m3u8|ts|mpd|ogg|ogv|vtt)$', url):
return True
return False

def uniq(seq):
"""Returns unique elements while preserving order."""
seen = set()
out = []
for x in seq:
if x and x not in seen:
seen.add(x)
out.append(x)
return out

--- Network & Parsing ---

async def fetch_and_parse(url):
"""Fetches a URL and returns the text content and final URL."""
headers = {"User-Agent": USER_AGENT}
# Using requests synchronously within an async environment
r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
r.raise_for_status()
return r.text, r.url

def extract_all_video_links(html_text, base_url):
"""
Extracts all requested video links from HTML, including direct links and iframes.
"""
soup = BeautifulSoup(html_text, "lxml")
found_links = []

# --- 1. Requested Tags and Attributes ---  
tags_and_attrs = {  
    "video": ["src"],  
    "source": ["src"],  
    "embed": ["src"],  
    "object": ["data"],  
    "track": ["src"],  
    "a": ["href"], # Filtered later for video extensions  
    "iframe": ["src"], # Filtered later  
    # The first code also looked for <video src> and <source src> which are included here  
}  

for tag_name, attrs in tags_and_attrs.items():  
    for tag in soup.find_all(tag_name):  
        for attr in attrs:  
            link = tag.get(attr)  
            if link:  
                abs_link = make_abs(link, base_url)  
                  
                if tag_name == "a":  
                    # Only include <a> tags that link directly to a video file  
                    if is_video_link(abs_link):  
                         found_links.append(abs_link)  
                elif tag_name == "iframe":  
                    # Add all iframes (embeds), as requested by the original code logic  
                    found_links.append(abs_link)  
                else:  
                    # Include direct video tags  
                    found_links.append(abs_link)  


# --- 2. Metadata: Open Graph (og:video) ---  
for meta in soup.find_all("meta"):  
    prop = meta.get("property")  
    content = meta.get("content")  
    if prop and content:  
        if prop in ["og:video", "og:video:url", "og:video:secure_url"]:  
            found_links.append(make_abs(content, base_url))  
              
# --- 3. Heuristic/JS Patterns ---  
# Search for common video link patterns in the whole HTML text  
video_link_pattern = r'(https?://[^\s\'"]*?\.(mp4|webm|mov|mkv|avi|flv|m3u8|ts|mpd|ogg|ogv|vtt))'  
  
# Search for generic variable assignments (e.g., "file": "...", video_url = "...")  
generic_url_pattern = r'["\'](file|src|contentUrl|streamUrl)["\']\s*:\s*["\'](https?://[^\s\'"]+?)(["\'])'  
  
all_text = html_text   
  
# Search for direct video files embedded in JS/text  
for match in re.finditer(video_link_pattern, all_text, re.IGNORECASE):  
    potential_link = match.group(0).strip()  
    if len(potential_link) > 10 and is_absolute(potential_link):  
        found_links.append(potential_link)  
          
# Search for generic URL patterns   
for match in re.finditer(generic_url_pattern, all_text):  
    potential_link = match.group(2).strip()  
    if len(potential_link) > 10 and is_absolute(potential_link):  
         # Only add if it looks like a video link or a generic URL (like a stream link)  
         if is_video_link(potential_link) or re.search(r'\b(stream|video|cdn)\b', potential_link, re.IGNORECASE):  
            found_links.append(potential_link)  
  
# --- Final Cleanup ---  
all_media_links = uniq(found_links)  
  
# Remove any None values from the list  
all_media_links = [link for link in all_media_links if link]  
  
return all_media_links

--- Telegram Handlers ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("👋 হাই — যেকোনো Blogger/ওয়েবসাইট লিংক পাঠান। আমি ভিডিও/এমবেড লিংক খুঁজে বের করব এবং ফলাফল দেবো।")

async def fetch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
# usage: /fetch <url>
if not context.args:
await update.message.reply_text("ব্যবহার করুন: /fetch <blog_post_url>")
return

url = context.args[0].strip()  
  
# --- Deletion System (from 2nd code) ---  
try:  
    # Delete user's message  
    await update.message.delete()  
except Exception as e:  
    logger.warning(f"Failed to delete user message: {e}")  

msg = await update.message.reply_text(f"🌐 স্ক্যান করা হচ্ছে: `{url}`...", parse_mode='Markdown')  
  
try:  
    html_text, final_url = await fetch_and_parse(url)  
    all_links = extract_all_video_links(html_text, final_url)  

    total_links = len(all_links)  
      
    # Save to cache  
    cache_id = save_to_cache(final_url, all_links)  

    # --- Inline Button Logic (from 2nd code) ---  
    summary = f"✅ স্ক্যান শেষ\nSource: `{final_url}`\n\nমোট ভিডিও/এমবেড: **{total_links}**"  
      
    keyboard = [  
        [InlineKeyboardButton("🎞️ ভিডিও লিস্ট দেখুন", callback_data=f"show_videos:{cache_id}")]  
    ]  
    reply_markup = InlineKeyboardMarkup(keyboard)  

    await msg.edit_text(summary, reply_markup=reply_markup, parse_mode='Markdown')  

    # --- Admin Notification (Simplified from 1st code) ---  
    if ADMIN_CHAT_ID:  
        # Send the URL and summary to the admin  
        await context.bot.send_message(  
            chat_id=ADMIN_CHAT_ID,   
            text=f"Fetched URL: {final_url}\nFound {total_links} video/embed links. Sent list to user."  
        )  
        # Send the first few direct video links to admin (optional, for checking)  
        direct_videos = [v for v in all_links if is_video_link(v)]  
        for i, v_url in enumerate(direct_videos[:5]): # Send max 5 direct links  
             await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"[Direct Video File Link] {v_url}")  
          

except Exception as e:  
    logger.exception(e)  
    await msg.edit_text(f"❌ সমস্যা: {str(e)}")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
"""Handles the 'Show Videos' button click."""
q = update.callback_query
data = q.data or ""
await q.answer() # Acknowledge the query

if data.startswith("show_videos:"):  
    _, sid = data.split(":",1)  
    try:  
        rid = int(sid)  
    except:  
        await q.answer("ত্রুটি: অবৈধ ID।")  
        return  

    rec = load_from_cache(rid)  
    if not rec:  
        await q.message.reply_text("রেজাল্ট পাওয়া যায়নি (সম্ভবত পুরোনো)।")  
        return  

    videos = rec["videos"]  
    url = rec["url"]  

    if not videos:  
        await q.message.reply_text(f"কোন ভিডিও পাওয়া যায়নি\nSource: `{url}`", parse_mode='Markdown')  
        return  

    await q.message.reply_text(f"📹 মোট {len(videos)}টি ভিডিও/এমবেড লিংক পাওয়া গেছে:")  

    max_messages = 50 # Limit to prevent spam  
    for i, v in enumerate(videos, start=1):  
        if i > max_messages:  
            await q.message.reply_text(f"⚠️ প্রথম {max_messages}টি দেখানো হলো।")  
            break  

        try:  
            await q.message.reply_text(  
                f"📹 লিংক {i}\n{v}",  
                parse_mode='Markdown',  
                disable_web_page_preview=False # Show a preview if available  
            )  
            await asyncio.sleep(0.5) # Throttle messages  
        except Exception as e:  
            logger.error(f"Failed to send link: {e}")  
            pass # Continue to the next link

async def manual_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
# if non-command message and looks like URL, auto-process
text = update.message.text.strip()
if text.startswith("http://") or text.startswith("https://"):
# reuse fetch logic
context.args = [text]
await fetch_cmd(update, context)
else:
await update.message.reply_text("Blogger/ওয়েবসাইট লিংক পাঠান।")

async def main():
if not BOT_TOKEN or not ADMIN_CHAT_ID:
print("BOT_TOKEN এবং ADMIN_CHAT_ID এনভায়রনমেন্ট ভেরিয়েবলে সেট করুন।")
return

app = ApplicationBuilder().token(BOT_TOKEN).build()  
  
app.add_handler(CommandHandler("start", start_cmd))  
app.add_handler(CommandHandler("fetch", fetch_cmd))  
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_to_admin))  
app.add_handler(CallbackQueryHandler(callback_handler))  

print("Bot started...")  
await app.run_polling()

if name == "main":
import asyncio
try:
asyncio.run(main())
except KeyboardInterrupt:
print("Bot stopped by user.")    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out

# ----------------- HTML Extraction (single page) -----------------
def extract_all_video_links_from_html(html_text, base_url):
    # (Preserved original single-page extraction logic)
    soup = BeautifulSoup(html_text, "lxml")
    found_links = []

    tags_and_attrs = {
        "video": ["src"],
        "source": ["src"],
        "embed": ["src"],
        "object": ["data"],
        "track": ["src"],
        "a": ["href"],
        "iframe": ["src"],
    }

    for tag_name, attrs in tags_and_attrs.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                link = tag.get(attr)
                if link:
                    abs_link = make_abs(link, base_url)
                    if tag_name == "a":
                        if is_video_link(abs_link):
                            found_links.append(abs_link)
                    elif tag_name == "iframe":
                        found_links.append(abs_link)
                    else:
                        found_links.append(abs_link)

    for meta in soup.find_all("meta"):
        prop = meta.get("property")
        content = meta.get("content")
        if prop and content:
            if prop in ["og:video", "og:video:url", "og:video:secure_url"]:
                found_links.append(make_abs(content, base_url))

    video_link_pattern = r'(https?://[^\s\'"]*?\.(mp4|webm|mov|mkv|avi|flv|m3u8|ts|mpd|ogg|ogv|vtt))'
    generic_url_pattern = r'["\'](file|src|contentUrl|streamUrl)["\']\s*:\s*["\'](https?://[^\s\'"]+?)(["\'])'

    all_text = html_text
    for match in re.finditer(video_link_pattern, all_text, re.IGNORECASE):
        potential_link = match.group(0).strip()
        if len(potential_link) > 10 and is_absolute(potential_link):
            found_links.append(potential_link)

    for match in re.finditer(generic_url_pattern, all_text):
        potential_link = match.group(2).strip()
        if len(potential_link) > 10 and is_absolute(potential_link):
            if is_video_link(potential_link) or re.search(r'\b(stream|video|cdn)\b', potential_link, re.IGNORECASE):
                found_links.append(potential_link)

    all_media_links = uniq(found_links)
    all_media_links = [link for link in all_media_links if link]
    return all_media_links

# ----------------- HTML Extraction (crawler uses broader extraction) -----------------
def extract_links_from_html(html_text, base_url):
    soup = BeautifulSoup(html_text, "lxml")
    found_links = []

    tags_and_attrs = {
        "a": ["href"],
        "iframe": ["src"],
        "video": ["src"],
        "source": ["src"],
        "embed": ["src"],
        "object": ["data"],
        "track": ["src"],
        "script": ["src"],
        "link": ["href"],
    }

    for tag_name, attrs in tags_and_attrs.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                link = tag.get(attr)
                if link:
                    abs_link = make_abs(link, base_url)
                    if abs_link:
                        found_links.append(abs_link)

    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if prop and content:
            if prop in ["og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"]:
                found_links.append(make_abs(content, base_url))

    for script in soup.find_all("script", {"type": "application/ld+json"}):
        try:
            txt = script.string
            if txt:
                for match in re.finditer(r'https?://[^\s\'"<>]+', txt):
                    found_links.append(make_abs(match.group(0), base_url))
        except Exception:
            pass

    for comment in soup.find_all(string=lambda text:isinstance(text, type(soup.Comment))):
        try:
            for match in re.finditer(r'https?://[^\s\'"<>]+', comment):
                found_links.append(make_abs(match.group(0), base_url))
        except Exception:
            pass

    for match in re.finditer(r'["\'](https?://[^\s\'"]+?)["\']', html_text):
        found_links.append(make_abs(match.group(1), base_url))

    all_links = uniq(found_links)
    all_links = [l for l in all_links if l]
    return all_links

# ----------------- Async HTTP helpers -----------------
async def fetch_text(session, url):
    headers = {"User-Agent": USER_AGENT}
    try:
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                text = await resp.text(errors='ignore')
                final = str(resp.url)
                return text, final
    except Exception as e:
        logger.debug(f"[fetch_text] failed {url} -> {e}")
        return None, url

async def head_check(session, url):
    headers = {"User-Agent": USER_AGENT}
    try:
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with session.head(url, headers=headers, allow_redirects=True) as resp:
                return resp.headers
    except Exception as e:
        logger.debug(f"[head_check] HEAD failed for {url}: {e}")
        return None

async def small_get_bytes(session, url, num_bytes=1024):
    headers = {"User-Agent": USER_AGENT, "Range": f"bytes=0-{num_bytes}"}
    try:
        async with async_timeout.timeout(REQUEST_TIMEOUT):
            async with session.get(url, headers=headers, allow_redirects=True) as resp:
                content = await resp.content.read(num_bytes)
                return resp.headers, content
    except Exception as e:
        logger.debug(f"[small_get_bytes] failed {url}: {e}")
        return None, None

# ----------------- Deep crawler (BFS, domain-limited) -----------------
async def crawl_site(start_url, max_pages=MAX_PAGES, max_depth=MAX_DEPTH, concurrency=MAX_CONCURRENT_REQUESTS):
    parsed = urlparse(start_url)
    base_domain = parsed.netloc

    collected_links = []
    visited_pages = set()
    found_pages = 0

    queue = asyncio.Queue()
    await queue.put((start_url, 0))

    sem = asyncio.Semaphore(concurrency)
    session_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT+5)

    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        async def worker():
            nonlocal found_pages
            while True:
                try:
                    page_url, depth = await queue.get()
                except asyncio.CancelledError:
                    return
                if page_url in visited_pages:
                    queue.task_done()
                    continue
                if found_pages >= max_pages:
                    queue.task_done()
                    continue
                visited_pages.add(page_url)
                found_pages += 1

                try:
                    async with sem:
                        text, final_url = await fetch_text(session, page_url)
                    if not text:
                        queue.task_done()
                        continue

                    links = extract_links_from_html(text, final_url)
                    for l in links:
                        if l and l not in collected_links:
                            collected_links.append(l)

                    if depth < max_depth:
                        for l in links:
                            try:
                                lp = urlparse(l)
                                if lp.netloc:
                                    if lp.netloc == base_domain:
                                        if l not in visited_pages:
                                            await queue.put((l, depth + 1))
                                else:
                                    if l not in visited_pages:
                                        await queue.put((l, depth + 1))
                            except Exception:
                                pass

                except Exception as e:
                    logger.debug(f"[crawl worker] error fetching {page_url}: {e}")
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await queue.join()
        for w in workers:
            w.cancel()

    collected_links = uniq(collected_links)
    return collected_links

# ----------------- Video verification -----------------
async def verify_videos_from_links(links, concurrency=MAX_CONCURRENT_REQUESTS):
    verified = []
    sem = asyncio.Semaphore(concurrency)
    session_timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT+5)

    async with aiohttp.ClientSession(timeout=session_timeout) as session:
        async def check(url):
            try:
                async with sem:
                    # extension hint
                    if is_video_link(url):
                        headers = await head_check(session, url)
                        if headers:
                            ct = headers.get("Content-Type", "")
                            if ct and "video" in ct.lower():
                                verified.append(url); return
                            if any(x in ct.lower() for x in ["application/vnd.apple.mpegurl","application/x-mpegurl","application/dash+xml","application/octet-stream"]):
                                verified.append(url); return
                        headers2, _ = await small_get_bytes(session, url, num_bytes=2048)
                        if headers2:
                            ct2 = headers2.get("Content-Type","")
                            if ct2 and ("video" in ct2.lower() or "mpegurl" in ct2.lower() or "dash" in ct2.lower()):
                                verified.append(url); return
                        # fallback: accept extension-only matches
                        verified.append(url); return
                    else:
                        headers = await head_check(session, url)
                        if headers:
                            ct = headers.get("Content-Type","")
                            if ct and "video" in ct.lower():
                                verified.append(url); return
                            if any(x in ct.lower() for x in ["application/vnd.apple.mpegurl","application/x-mpegurl","application/dash+xml"]):
                                verified.append(url); return
                        headers2, _ = await small_get_bytes(session, url, num_bytes=2048)
                        if headers2:
                            ct2 = headers2.get("Content-Type","")
                            if ct2 and ("video" in ct2.lower() or "mpegurl" in ct2.lower() or "dash" in ct2.lower()):
                                verified.append(url); return
            except Exception as e:
                logger.debug(f"[verify check] {url} -> {e}")
            return

        tasks = [asyncio.create_task(check(u)) for u in links]
        await asyncio.gather(*tasks, return_exceptions=True)

    return uniq(verified)

# ----------------- Backwards-compatible synchronous fetch (preserved) -----------------
def fetch_and_parse(url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url

# ----------------- Telegram handlers -----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 হাই — ওয়েবসাইট লিংক পাঠান (বা /deepfetch <url>)। আমি পুরো সাইট ক্রল করে শুধু ভিডিও লিংকগুলোই দেখাব।")

# Single-page fetch (preserved behavior)
async def fetch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ব্যবহার করুন: /fetch <blog_post_url>")
        return
    url = context.args[0].strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    msg = await update.message.reply_text(f"🌐 single-page স্ক্যান চলছে: `{url}`...", parse_mode='Markdown')
    try:
        # Synchronous fetch here (original code)
        html_text, final_url = await asyncio.to_thread(fetch_and_parse, url)
        
        all_links = extract_all_video_links_from_html(html_text, final_url)
        # verify automatically for single-page too
        verified = []
        if all_links:
            verified = await verify_videos_from_links(all_links, concurrency=5)
        cache_id = save_to_cache(final_url, all_links, verified=verified, meta={"mode":"single"})
        # ONLY show persistent video list button (main summary)
        keyboard = [
            [InlineKeyboardButton("🎞️ ভিডিও লিস্ট", callback_data=f"show_verified:{cache_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(f"✅ single-page স্ক্যান শেষ\nSource: `{final_url}`\nমোট লিংক: **{len(all_links)}**\nভিডিও হিসেবে মিলেছে: **{len(verified)}**", reply_markup=reply_markup, parse_mode='Markdown')
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"Single fetch {final_url} -> {len(all_links)} links, {len(verified)} verified. CacheID: {cache_id}")
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ সমস্যা: {str(e)}")

# Deep fetch (full site) - now performs verification automatically and DOES NOT remove the main buttons
async def deepfetch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ব্যবহার করুন: /deepfetch <site_start_url>")
        return
    start_url = context.args[0].strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    msg = await update.message.reply_text(f"🔎 Full site crawl শুরু হচ্ছে: `{start_url}`\n(ডোমেইন-লিমিটেড)", parse_mode='Markdown')
    try:
        start_time = time.time()
        all_links = await crawl_site(start_url, max_pages=MAX_PAGES, max_depth=MAX_DEPTH, concurrency=MAX_CONCURRENT_REQUESTS)
        crawl_time = time.time() - start_time

        # Auto-verify only the collected links (second scan)
        verified = []
        if all_links:
            # optionally filter duplicates and non-http
            candidates = [l for l in uniq(all_links) if l and (l.startswith("http://") or l.startswith("https://"))]
            verified = await verify_videos_from_links(candidates, concurrency=MAX_CONCURRENT_REQUESTS)

        cache_id = save_to_cache(start_url, all_links, verified=verified, meta={"crawl_time": crawl_time, "collected_count": len(all_links), "mode":"deep"})
        # Main persistent button (never deleted)
        keyboard = [
            [InlineKeyboardButton("🎞️ ভিডিও লিস্ট", callback_data=f"show_verified:{cache_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await msg.edit_text(
            f"✅ Full crawl শেষ\nSource: `{start_url}`\nমোট লিংক সংগ্রহ: **{len(all_links)}**\nক্রল সময়: {int(crawl_time)}s\nভিডিও হিসেবে মিলেছে (auto-verified): **{len(verified)}**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        if ADMIN_CHAT_ID:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"DeepFetch: {start_url}\nCollected {len(all_links)} links in {int(crawl_time)}s. Verified {len(verified)}. CacheID: {cache_id}")
    except Exception as e:
        logger.exception(e)
        await msg.edit_text(f"❌ সমস্যা (crawl): {str(e)}")

# Helper to split long text into chunks (Telegram ~4096 char limit)
def chunk_text_lines(lines, max_chars=3800):
    chunks = []
    cur = []
    cur_len = 0
    for line in lines:
        if cur_len + len(line) + 1 > max_chars and cur:
            chunks.append("\n".join(cur))
            cur = []
            cur_len = 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks

# Callback handler: DOES NOT edit/delete the main summary message (so main button persists)
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    await q.answer()  # acknowledge

    # Show verified videos (send numbered list messages, store their message ids so they can be deleted later)
    if data.startswith("show_verified:"):
        _, sid = data.split(":",1)
        try:
            rid = int(sid)
        except:
            await q.message.reply_text("ত্রুটি: অবৈধ ID।")
            return

        rec = load_from_cache(rid)
        if not rec:
            await q.message.reply_text("রেজাল্ট পাওয়া যায়নি (সম্ভবত পুরোনো)।")
            return

        vids = rec.get
