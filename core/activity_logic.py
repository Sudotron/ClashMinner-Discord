"""Pure activity-tracker maths: fingerprints, season handling, last-seen and leaderboard values."""
import hashlib
from datetime import datetime, timezone

import config

# Cumulative achievements that only grow when the player actually plays. Donations and trophies are
# left out on purpose: donations reset every season and trophies move when someone attacks you.
ACTIVITY_ACHIEVEMENTS = ("Gold Grab", "Elixir Escapade", "Heroic Heist", "Friend in Need", "Sharing is caring",
                         "Aggressive Capitalism", "Games Champion", "Conqueror")


def _ach(player: dict, name: str) -> int:
    for a in player.get("achievements", []):
        if a.get("name") == name:
            return a.get("value", 0)
    return 0


def fingerprint(player: dict) -> str:
    parts = [player.get("warStars", 0), player.get("expLevel", 0)] + [_ach(player, n) for n in ACTIVITY_ACHIEVEMENTS]
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def values(player: dict) -> dict:
    return {"war_stars": player.get("warStars", 0), "gold": _ach(player, "Gold Grab"),
            "elixir": _ach(player, "Elixir Escapade"), "dark_elixir": _ach(player, "Heroic Heist"),
            "capital": _ach(player, "Aggressive Capitalism")}


def observe(prev: dict | None, player: dict, season: str, now: datetime) -> dict:
    """New snapshot row from a fresh player payload and the previous row (None the first time we see them).

    - First sighting: baselines = current values, last_active unknown (None).
    - Season rollover: baselines reset and the fingerprint is refreshed WITHOUT counting as activity.
    - Otherwise: a changed fingerprint means the player did something, so last_active_at = now.
    """
    now_s = _iso(now)
    vals = values(player)
    row = {"player_tag": player.get("tag"), "clan_tag": (player.get("clan") or {}).get("tag"),
           "name": player.get("name"), "town_hall": player.get("townHallLevel"),
           "donations": player.get("donations", 0), "donations_received": player.get("donationsReceived", 0),
           "last_fingerprint": fingerprint(player), "season_id": season, "updated_at": now_s, **vals}
    if prev is None:
        row.update(first_seen_at=now_s, last_active_at=None, baseline_at=now_s,
                   **{f"{k}_baseline": v for k, v in vals.items()})
        return row
    row["first_seen_at"] = prev["first_seen_at"]
    if prev.get("season_id") != season:
        row.update(last_active_at=prev.get("last_active_at"), baseline_at=now_s,
                   **{f"{k}_baseline": v for k, v in vals.items()})
        return row
    row["last_active_at"] = now_s if row["last_fingerprint"] != prev.get("last_fingerprint") else prev.get("last_active_at")
    row["baseline_at"] = prev.get("baseline_at")
    for k in vals:
        row[f"{k}_baseline"] = prev.get(f"{k}_baseline", vals[k])
    return row


def season_gain(row: dict, stat: str) -> int:
    """Season gain for a cumulative stat; never negative."""
    return max(0, row[stat] - row[f"{stat}_baseline"])


def donation_ratio(row: dict) -> float:
    given, got = row.get("donations", 0), row.get("donations_received", 0)
    return given / got if got else float(given)


STATS = {
    "donations": ("Season donations", lambda r: r["donations"]),
    "ratio": ("Donation ratio (given ÷ received)", donation_ratio),
    "war_stars": ("War stars this season", lambda r: season_gain(r, "war_stars")),
    "gold": ("Gold looted this season", lambda r: season_gain(r, "gold")),
    "elixir": ("Elixir looted this season", lambda r: season_gain(r, "elixir")),
    "dark_elixir": ("Dark Elixir looted this season", lambda r: season_gain(r, "dark_elixir")),
    "capital": ("Capital Gold contributed this season", lambda r: season_gain(r, "capital")),
}
LIVE_STATS = {"donations", "ratio"}        # correct from the very first look (the API resets them per season)


def last_seen_label(row: dict, now: datetime | None = None) -> str:
    """'3h ago' / '2d ago' / 'none since tracking began (5d)'."""
    now = now or datetime.now(timezone.utc)

    def ago(iso):
        secs = (now - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
        return "just now" if secs < 3600 else f"{int(secs // 3600)}h ago" if secs < 86400 else f"{int(secs // 86400)}d ago"
    if row.get("last_active_at"):
        return ago(row["last_active_at"])
    return f"none since tracking began ({ago(row['first_seen_at']).replace(' ago', '')})"


def sort_by_activity(rows: list) -> list:
    """Most recently active first; members never seen active go last, longest-tracked (most suspicious) first."""
    seen = sorted((r for r in rows if r.get("last_active_at")), key=lambda r: r["last_active_at"], reverse=True)
    unseen = sorted((r for r in rows if not r.get("last_active_at")), key=lambda r: r["first_seen_at"])
    return seen + unseen


def is_inactive(row: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    ref = row.get("last_active_at") or row["first_seen_at"]
    age = (now - datetime.strptime(ref, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).days
    return age >= config.INACTIVE_DAYS
