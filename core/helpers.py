"""Shared helpers: emoji table, formatting, tag handling, max-level lookups."""
import asyncio
import functools
import json
import os
from datetime import datetime, timezone

from config import TH_MAX_FILE
from database import get_linked_account

# ── Emoji constants ──────────────────────────────────────────────────────────
# ── Emoji constants ──────────────────────────────────────────────────────────
E = {
    "trophy":       "🏆",
    "versus":       "🏅",
    "shield":       "🛡️",
    "sword":        "⚔️",
    "star":         "⭐",
    "ratio":        "📊",
    "up":           "🔼",
    "down":         "🔽",
    "gold":         "💰",
    "raid":         "🗡️",
    "games":        "🎮",
    "troop":        "🪖",
    "hero":         "👑",
    "spell":        "🧪",
    "siege":        "🚜",
    "pet":          "🐾",
    "super":        "✨",
    "warning":      "⚠️",
    "player":       "👤",
    "clan":         "🛡️",
    "th":           "🏯",
    "level":        "🎖️",
    "war":          "⚔️",
    "donup":        "⬆️",
    "dondown":      "⬇️",
    "page":         "📄",
    "back":         "◀️",
    "next":         "▶️",
    "fire":         "🔥",
    "cwl":          "🌟",
}

async def run_blocking(fn, *args, **kwargs):
    """Run CPU-heavy or blocking work (Pillow, big JSON) off the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))


def fmt_number(n) -> str:
    """Format number with commas."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def current_season() -> str:
    """Return current season key like '2026-11'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def normalize_tag(tag: str) -> str:
    """'  yy8pqy28 ' -> '#YY8PQY28'."""
    tag = (tag or "").strip().upper()
    return tag if tag.startswith("#") else "#" + tag


def player_url(tag: str) -> str:
    return f"https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=%23{tag.replace('#', '')}"


def clan_url(tag: str) -> str:
    return f"https://link.clashofclans.com/en?action=OpenClanProfile&tag=%23{tag.replace('#', '')}"


_th_cache = {"mtime": None, "data": {}}


def _load_th_max() -> dict:
    try:
        mtime = os.path.getmtime(TH_MAX_FILE)
    except OSError:
        return {}
    if _th_cache["mtime"] != mtime:
        try:
            with open(TH_MAX_FILE, "r", encoding="utf-8") as f:
                _th_cache["data"] = json.load(f)
        except Exception:
            _th_cache["data"] = {}
        _th_cache["mtime"] = mtime
    return _th_cache["data"]


def get_scraped_th_max(unit_name: str, th: int) -> int:
    """Max level for a unit at a Town Hall, from the scraped th_max_levels.json (0 if unknown)."""
    unit_data = _load_th_max().get(unit_name)
    if not unit_data:
        return 0
    max_lvl = 0
    for req_th_str, lvl in sorted(unit_data.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        try:
            if int(req_th_str) <= th:
                max_lvl = lvl
        except ValueError:
            continue
    return max_lvl


async def resolve_tag(discord_id: int, tag_arg, entity_type: str = "player"):
    """Tag from the command option, else from the user's linked account of that type."""
    if tag_arg and tag_arg.strip():
        return normalize_tag(tag_arg)
    return await get_linked_account(discord_id, entity_type)


async def get_th_max(coc_client, tag: str, th_level) -> dict:
    """Town-Hall-specific max levels via coc.py game data (best effort, {} on any failure)."""
    th_max = {}
    if not coc_client or not isinstance(th_level, int):
        return th_max
    try:
        player = await coc_client.get_player(normalize_tag(tag))
        for h in player.heroes:
            if h.is_home_base:
                ml = get_scraped_th_max(h.name, th_level)
                if ml:
                    th_max[h.name] = ml
        for t in player.troops:
            if t.is_home_base and not t.is_super_troop:
                ml = t.get_max_level_for_townhall(th_level)
                if ml:
                    th_max[t.name] = ml
        for s in player.spells:
            if s.is_home_base:
                ml = s.get_max_level_for_townhall(th_level)
                if ml:
                    th_max[s.name] = ml
    except Exception:
        pass
    return th_max


class ApiError(Exception):
    """Raised when a Clash API lookup fails; the message is safe to show to users."""
