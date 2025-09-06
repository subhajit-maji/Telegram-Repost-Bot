#!/usr/bin/env python3
# repost_bot.py - Termux/Android-ready Telegram repost bot (ShrinkEarn-ready)

import os, base64, threading, re, requests, logging, asyncio
from pathlib import Path
from telethon import TelegramClient, events, errors
from dotenv import load_dotenv

# --- Load .env ---
ENV_PATH = '/storage/emulated/0/TelegramRepostBot/nano .env'
load_dotenv(dotenv_path=ENV_PATH)

# --- CONFIG from Environment ---
API_ID = int(os.getenv('API_ID') or 0)
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN') or None
SOURCE = os.getenv('SOURCE_CHANNEL')
TARGET = os.getenv('TARGET_CHANNEL')

# Termux-safe writable directories
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', '/storage/emulated/0/TelegramRepostBot')
SESSION_PATH = os.getenv('SESSION_PATH', '/storage/emulated/0/TelegramRepostBot/user_session.session')

# ShrinkEarn config
SHRINKEARN_DOMAIN = os.getenv('SHRINKEARN_DOMAIN')
SHRINKEARN_TOKEN = os.getenv('SHRINKEARN_TOKEN')
SHRINKEARN_API_PREFIX = os.getenv('SHRINKEARN_API_PREFIX')

# Session B64 (optional)
SESSION_B64 = os.getenv('SESSION_B64')

# Ensure directories exist
Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(os.path.dirname(SESSION_PATH)).mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger('repostbot')

# Debug: confirm API loaded
logger.info(f"API_ID={API_ID}, API_HASH={'set' if API_HASH else 'not set'}")

# Write session file from SESSION_B64 (if provided and not exist)
if SESSION_B64 and not Path(SESSION_PATH).exists():
    try:
        logger.info("Writing Telegram session to %s", SESSION_PATH)
        raw = base64.b64decode(SESSION_B64.encode('utf-8'))
        with open(SESSION_PATH, 'wb') as f:
            f.write(raw)
        os.chmod(SESSION_PATH, 0o600)
    except Exception as e:
        logger.exception("Failed to write session file: %s", e)

# URL regex
URL_RE = re.compile(r'https?://[^\s)]+')

# ShrinkEarn helpers
def try_shrinkearn_endpoint(ep_url):
    try:
        r = requests.get(ep_url, timeout=10)
        r.raise_for_status()
        try:
            j = r.json()
            for key in ('short','shorturl','shortenedUrl','short_link','url','result'):
                if isinstance(j, dict) and key in j and isinstance(j[key], str):
                    return j[key]
            if isinstance(j, dict) and 'data' in j and isinstance(j['data'], dict):
                for key in ('short','short_url','url','shortlink'):
                    if key in j['data'] and isinstance(j['data'][key], str):
                        return j['data'][key]
        except ValueError:
            txt = r.text.strip()
            m = re.search(r'https?://[^\s"\']+', txt)
            if m:
                return m.group(0)
            if txt and '/' in txt and SHRINKEARN_DOMAIN:
                return SHRINKEARN_DOMAIN.rstrip('/') + '/' + txt.lstrip('/')
    except Exception as e:
        logger.debug("ShrinkEarn probe failed for %s: %s", ep_url, e)
    return None

def shorten_with_shrinkearn(long_url):
    if not (SHRINKEARN_TOKEN or SHRINKEARN_API_PREFIX):
        return long_url
    enc = requests.utils.requote_uri(long_url)
    candidates = []
    if SHRINKEARN_API_PREFIX:
        candidates.append(SHRINKEARN_API_PREFIX + enc)
    if SHRINKEARN_DOMAIN and SHRINKEARN_TOKEN:
        d = SHRINKEARN_DOMAIN.rstrip('/')
        candidates += [
            f"{d}/tools/api?api={SHRINKEARN_TOKEN}&url={enc}",
            f"{d}/api?api={SHRINKEARN_TOKEN}&url={enc}",
            f"{d}/st/?api={SHRINKEARN_TOKEN}&url={enc}",
            f"{d}/shorten?api={SHRINKEARN_TOKEN}&url={enc}",
        ]
    for ep in candidates:
        short = try_shrinkearn_endpoint(ep)
        if short:
            return short
    logger.warning("ShrinkEarn failed for %s; returning original", long_url)
    return long_url

def replace_links(text):
    if not text:
        return text
    for u in URL_RE.findall(text):
        short = shorten_with_shrinkearn(u)
        if short and short != u:
            text = text.replace(u, short)
    return text

# Telethon client
SESSION_ARG = SESSION_PATH if not BOT_TOKEN else 'bot_session'
if BOT_TOKEN:
    client = TelegramClient(SESSION_ARG, API_ID, API_HASH).start(bot_token=BOT_TOKEN)
else:
    client = TelegramClient(SESSION_ARG, API_ID, API_HASH)

# Media helpers
async def download_media_safe(msg):
    if not msg.media:
        return None
    try:
        path = await msg.download_media(file=DOWNLOAD_DIR)
        logger.info("Downloaded media: %s", path)
        return path
    except Exception as e:
        logger.exception("download_media failed: %s", e)
        return None

async def send_with_retries(entity, text=None, file=None, attempts=3):
    for i in range(attempts):
        try:
            if file:
                await client.send_file(entity, file, caption=text)
            else:
                await client.send_message(entity, text or "")
            return True
        except Exception as e:
            logger.warning("Send attempt %s failed: %s", i+1, e)
            await asyncio.sleep(2*(i+1))
    return False

@client.on(events.NewMessage(incoming=True, chats=SOURCE))
async def handler(event):
    msg = event.message
    try:
        orig_text = msg.message or ""
        new_text = replace_links(orig_text)
        media_path = None
        if msg.media:
            media_path = await download_media_safe(msg)
        success = await send_with_retries(TARGET, text=new_text, file=media_path)
        if success:
            logger.info("Reposted message id=%s", msg.id)
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except:
                logger.exception("cleanup failed for %s", media_path)
    except errors.RPCError as rpc:
        logger.error("Telegram RPC error: %s", rpc)
    except Exception as e:
        logger.exception("Unhandled exception: %s", e)

# Main
def main():
    client.start()
    logger.info("Telethon client started; listening for messages.")
    client.run_until_disconnected()

if __name__ == '__main__':
    main()