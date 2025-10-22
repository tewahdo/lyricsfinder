# bot.py
import logging
import os
import sqlite3
import asyncio
from typing import Optional

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Genius fallback
try:
    import lyricsgenius
except Exception:
    lyricsgenius = None

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")  # optional

if not TELEGRAM_TOKEN:
    raise SystemExit("TELEGRAM_TOKEN not set in .env")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# SQLite DB for favorites (also used for caching)
DB_PATH = "favorites.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT,
            artist TEXT,
            lyrics TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_favorite(user_id: int, title: str, artist: str, lyrics: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO favorites (user_id, title, artist, lyrics) VALUES (?, ?, ?, ?)",
        (user_id, title, artist, lyrics),
    )
    conn.commit()
    conn.close()


def get_user_favorites(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, title, artist FROM favorites WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_favorite_lyrics(fav_id: int, user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT lyrics FROM favorites WHERE id = ? AND user_id = ?",
        (fav_id, user_id),
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# --- Lyrics fetching functions ---
def fetch_lyrics_ovh(artist: str, title: str) -> Optional[str]:
    try:
        url = f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist)}/{requests.utils.quote(title)}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("lyrics")
        return None
    except Exception as e:
        logger.exception("Lyrics.ovh error: %s", e)
        return None


def fetch_lyrics_genius(query: str) -> Optional[tuple]:
    if not GENIUS_TOKEN or not lyricsgenius:
        return None
    try:
        genius = lyricsgenius.Genius(
            GENIUS_TOKEN,
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)"]
        )
        genius.timeout = 10
        song = genius.search_song(query)
        if song:
            return song.title, song.artist, song.lyrics
    except Exception as e:
        logger.exception("Genius error: %s", e)
    return None


# --- Split long messages ---
async def split_and_send_text(text: str, send_func):
    max_len = 4000
    if len(text) <= max_len:
        await send_func(text)
        return

    paragraphs = text.split("\n\n")
    current = ""
    parts = []

    for p in paragraphs:
        if len(current) + len(p) + 2 <= max_len:
            current += (p + "\n\n")
        else:
            if current:
                parts.append(current)
            if len(p) <= max_len:
                current = p + "\n\n"
            else:
                for i in range(0, len(p), max_len):
                    parts.append(p[i:i + max_len])
                current = ""
    if current:
        parts.append(current)

    for part in parts:
        await send_func(part)


# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎵 *LyricsFinder Bot*\n\n"
        "Send a message like `Title - Artist` or just a song title.\n"
        "Example: `Hello - Adele`\n\n"
        "Commands:\n"
        "/favorite - save last fetched lyrics\n"
        "/myfavorites - list your favorites\n"
        "/getfav <id> - get saved favorite lyrics"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎶 Usage:\n"
        "`Shape of You - Ed Sheeran`\n"
        "`Adele - Hello`\n"
        "`Bohemian Rhapsody`\n\n"
        "Commands:\n"
        "/favorite - save last lyrics\n"
        "/myfavorites - list favorites\n"
        "/getfav <id> - view favorite lyrics"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# Keep last lyrics per user
LAST_LYRICS = {}  # user_id -> dict(title, artist, lyrics)


# --- Improved instant reply handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Send a song title and/or artist.")
        return

    # Parse user input
    if "-" in text:
        left, right = [part.strip() for part in text.split("-", 1)]
        title_candidate = left
        artist_candidate = right
    else:
        title_candidate = text
        artist_candidate = ""

    # Instant feedback (no delay)
    await update.message.reply_text(f"🎶 Finding lyrics for *{text}*...", parse_mode="Markdown")

    # Check cache first (instant)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT title, artist, lyrics FROM favorites WHERE LOWER(title)=LOWER(?) AND LOWER(artist)=LOWER(?)",
        (title_candidate, artist_candidate),
    )
    row = c.fetchone()
    conn.close()

    if row:
        title, artist, lyrics = row
        LAST_LYRICS[user_id] = {"title": title, "artist": artist, "lyrics": lyrics}
        header = f"🎵 *{title}* — _{artist}_ (cached)\n\n"
        await update.message.reply_text(header, parse_mode="Markdown")
        await split_and_send_text(lyrics, update.message.reply_text)
        return

    # Run API fetch in background (no delay to user)
    async def fetch_and_send():
        await asyncio.sleep(0)  # yield to event loop

        lyrics = None
        found_title = found_artist = None

        # Try lyrics.ovh
        if artist_candidate:
            lyrics = fetch_lyrics_ovh(artist_candidate, title_candidate)
            if lyrics:
                found_title, found_artist = title_candidate, artist_candidate

        # Swap order if not found
        if not lyrics and artist_candidate:
            lyrics = fetch_lyrics_ovh(title_candidate, artist_candidate)
            if lyrics:
                found_title, found_artist = artist_candidate, title_candidate

        # Genius fallback
        if not lyrics:
            queries = [f"{title_candidate} {artist_candidate}", f"{artist_candidate} {title_candidate}"] if artist_candidate else [title_candidate]
            for q in queries:
                res = fetch_lyrics_genius(q)
                if res:
                    found_title, found_artist, lyrics = res
                    break

        if not lyrics:
            await update.message.reply_text("❌ Sorry, I couldn't find lyrics.")
            return

        # Save in cache and DB
        LAST_LYRICS[user_id] = {"title": found_title, "artist": found_artist, "lyrics": lyrics}
        save_favorite(user_id, found_title, found_artist, lyrics)

        header = f"🎶 *{found_title}* — _{found_artist}_\n\n"
        await update.message.reply_text(header, parse_mode="Markdown")
        await split_and_send_text(lyrics, update.message.reply_text)

    asyncio.create_task(fetch_and_send())


# --- Favorites commands ---
async def favorite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    last = LAST_LYRICS.get(user_id)
    if not last:
        await update.message.reply_text("No recently fetched lyrics to save.")
        return
    save_favorite(user_id, last["title"], last["artist"], last["lyrics"])
    await update.message.reply_text(f"Saved *{last['title']}* — _{last['artist']}_", parse_mode="Markdown")


async def myfavorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = get_user_favorites(user_id)
    if not rows:
        await update.message.reply_text("You have no favorites yet.")
        return
    lines = ["Your favorites:"]
    for r in rows:
        fid, title, artist = r
        lines.append(f"{fid}: *{title}* — _{artist}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def getfav_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /getfav <id>")
        return
    try:
        fid = int(args[0])
    except ValueError:
        await update.message.reply_text("ID must be a number.")
        return
    lyrics = get_favorite_lyrics(fid, user_id)
    if not lyrics:
        await update.message.reply_text("Favorite not found.")
        return
    async def send_chunk(chunk):
        await update.message.reply_text(chunk)
    await split_and_send_text(lyrics, send_chunk)


# --- Main ---
def main():
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("favorite", favorite_cmd))
    app.add_handler(CommandHandler("myfavorites", myfavorites_cmd))
    app.add_handler(CommandHandler("getfav", getfav_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
