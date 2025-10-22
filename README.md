LyricFinder Bot
================

This is a small Telegram lyrics bot. Your IDE reported unresolved imports for `requests`, `dotenv`, `telegram`, and `lyricsgenius`. Those are third-party packages and need to be installed into your Python environment.

Quick setup (Windows, using bash):

1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/Scripts/activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set `TELEGRAM_TOKEN` (and optional `GENIUS_TOKEN`).

4. Run the bot

```bash
python bot.py
```

If your editor (e.g., VS Code + Pylance) still shows unresolved imports, ensure the workspace Python interpreter is set to the virtual environment you created. See the `.vscode/settings.json` helper added in this repo.

Notes
-----
- `python-telegram-bot` v20 uses asyncio; the code in `bot.py` targets that API.
- Installing the packages will resolve the import errors in the editor and at runtime.
