"""Pure reminder maths: who still has attacks / points left, and which threshold applies.

No network and no Discord objects here, so every rule can be tested directly.
"""
from collections import Counter
from datetime import datetime, timezone

import config
from core.builders import _parse_coc_time

DEFAULT_RAID_ATTACKS = 5          # used only when the API lists nobody to copy the limit from


def _now(now):
    return now or datetime.now(timezone.utc)


def human_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, m = divmod(seconds // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def war_tier(remaining: float, hours=None):
    """Smallest reminder threshold (in hours) already crossed, e.g. 1 when 40 min are left. None if too early."""
    if remaining <= 0:
        return None
    crossed = [h for h in (hours or config.WAR_REMINDER_HOURS) if remaining <= h * 3600]
    return min(crossed) if crossed else None


def war_missing(war: dict, now=None):
    """Members of a running war with attacks left. None unless the war is in battle day (state inWar)."""
    if not isinstance(war, dict) or war.get("state") != "inWar":
        return None
    end = _parse_coc_time(war.get("endTime", ""))
    if not end:
        return None
    allowance = war.get("attacksPerMember") or 2
    members = []
    for m in (war.get("clan") or {}).get("members", []):
        left = allowance - len(m.get("attacks") or [])
        if left > 0:
            members.append({"tag": m.get("tag", ""), "name": m.get("name", "?"),
                            "left": left, "total": allowance, "pos": m.get("mapPosition", 99)})
    members.sort(key=lambda x: (-x["left"], x["pos"]))
    return {"clan_name": (war.get("clan") or {}).get("name", ""), "end_raw": war.get("endTime", ""),
            "remaining": (end - _now(now)).total_seconds(), "allowance": allowance,
            "is_cwl": bool(war.get("isCwl")), "members": members}


def raid_missing(raid: dict, clan_members: list | None, now=None):
    """Clan members with raid attacks left. None unless a raid weekend is ongoing.

    The per-member allowance comes from the API (attackLimit + bonusAttackLimit). A current clan member
    the API does not list has not attacked yet and gets the most common listed limit.
    """
    if not isinstance(raid, dict) or raid.get("state") != "ongoing":
        return None
    end = _parse_coc_time(raid.get("endTime", ""))
    if not end:
        return None
    listed = {m.get("tag"): m for m in raid.get("members", [])}
    limits = Counter(m.get("attackLimit") for m in listed.values() if m.get("attackLimit"))
    default = limits.most_common(1)[0][0] if limits else DEFAULT_RAID_ATTACKS
    roster = ([(m.get("tag"), m.get("name")) for m in clan_members] if clan_members
              else [(t, m.get("name")) for t, m in listed.items()])
    members = []
    for tag, name in roster:
        m = listed.get(tag)
        total = (m.get("attackLimit", default) + m.get("bonusAttackLimit", 0)) if m else default
        used = m.get("attacks", 0) if m else 0
        if total - used > 0:
            members.append({"tag": tag, "name": name or "?", "left": total - used, "total": total})
    members.sort(key=lambda x: (-x["left"], x["name"].lower()))
    return {"end_raw": raid.get("endTime", ""), "remaining": (end - _now(now)).total_seconds(),
            "members": members}


def games_window(now=None):
    """(start, end, event_id) while a Clan Games event is running, else None. Schedule is set in config."""
    now = _now(now)
    start = datetime(now.year, now.month, config.GAMES_START_DAY, config.GAMES_HOUR_UTC, tzinfo=timezone.utc)
    end = datetime(now.year, now.month, config.GAMES_END_DAY, config.GAMES_HOUR_UTC, tzinfo=timezone.utc)
    return (start, end, f"{now.year:04d}-{now.month:02d}") if start <= now < end else None


def games_missing(points_now: dict, baselines: dict, cap: int | None = None) -> list:
    """Players below the points cap this event. points_now = {tag: (name, cumulative_points)}.

    Players with no baseline (joined after the event began) are skipped: their score is unknown.
    """
    cap = cap or config.GAMES_MAX_POINTS
    out = []
    for tag, (name, points) in points_now.items():
        if tag not in baselines:
            continue
        earned = max(0, points - baselines[tag])
        if earned < cap:
            out.append({"tag": tag, "name": name, "earned": earned, "left": cap - earned})
    out.sort(key=lambda x: (-x["left"], x["name"].lower()))
    return out


def games_points(player: dict) -> int | None:
    """Cumulative 'Games Champion' achievement value from a player payload."""
    for a in player.get("achievements", []):
        if a.get("name") == "Games Champion":
            return a.get("value", 0)
    return None


def format_missing(entries: list, mentions: dict | None = None, *, unit: str = "hits", limit: int = 50) -> str:
    """Bullet lines: @user (when the tag is linked) or the in-game name, plus what is left."""
    mentions = mentions or {}
    lines = []
    for e in entries[:limit]:
        who = f"<@{mentions[e['tag']]}> ({e['name']})" if e.get("tag") in mentions else f"**{e['name']}**"
        if "earned" in e:
            lines.append(f"• {who}: {e['earned']:,}/{config.GAMES_MAX_POINTS:,} {unit}")
        else:
            lines.append(f"• {who}: {e['left']}/{e['total']} {unit} left")
    if len(entries) > limit:
        lines.append(f"…and {len(entries) - limit} more")
    return "\n".join(lines)
