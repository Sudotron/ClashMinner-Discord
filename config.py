"""Central configuration, loaded from environment / .env (never commit .env)."""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, default) or default)
    except ValueError:
        return default


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
OWNER_ID = _int("OWNER_ID")              # Discord user ID of the bot owner
DEV_GUILD_ID = _int("DEV_GUILD_ID")      # optional: instant command sync to one server
COC_EMAIL = os.getenv("COC_EMAIL", "")
COC_PASSWORD = os.getenv("COC_PASSWORD", "")
OWNER_CONTACT = os.getenv("OWNER_CONTACT", "")  # optional text shown in /help

DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "otto.db"))
TH_IMAGE_DIR = os.path.join(BASE_DIR, "TownHalls_processed")
TH_MAX_FILE = os.path.join(BASE_DIR, "th_max_levels.json")
FORECASTER_FILE = os.path.join(BASE_DIR, "forecaster_data.json")
HELP_ANIMATION = os.path.join(BASE_DIR, "gif", "animation.gif.mp4")
