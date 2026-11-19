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

# ── Feature settings ─────────────────────────────────────────────────────────
FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")

# Reminder thresholds (hours before the end). War: the first one that is crossed fires once each.
WAR_REMINDER_HOURS = (2, 1)
RAID_REMINDER_HOURS = 6
GAMES_REMINDER_HOURS = 12
GAMES_MAX_POINTS = 4000            # per-player cap in Clan Games
# Clan Games run on a fixed monthly schedule (UTC); the API does not expose it.
GAMES_START_DAY, GAMES_END_DAY, GAMES_HOUR_UTC = 22, 28, 8
GAMES_BASELINE_GRACE_HOURS = 2     # baselines taken later than this after the start are not trusted
REMINDER_LOOP_MINUTES = 15
ACTIVITY_LOOP_MINUTES = 60
INACTIVE_DAYS = 7

# The /bases library and the automatic army/base link reader.
# The auto reader needs the privileged "Message Content" intent (Developer Portal -> Bot).
ENABLE_MESSAGE_CONTENT = os.getenv("ENABLE_MESSAGE_CONTENT", "0").strip().lower() in ("1", "true", "yes")
