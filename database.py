"""SQLite storage. A fresh DB is created on first start (no Telegram data is imported).

Tables
  reminder_configs / sent_reminders / games_events / games_baselines – automatic reminders
  player_snapshots – activity tracker and season leaderboards (one row per player)
  saved_bases / base_votes / guild_flags – base library, upvotes, auto-decode switch
  schema_version – single row: how many numbered migrations have been applied
  user_tags     – game tags (player/clan) linked to a Discord user ID, with
                  is_primary / is_verified flags and a cached display label
  guild_config  – per-server settings: notification channel, tracked clan,
                  notification toggles, loot toggle, and tracker state (JSON)
"""
import json
from datetime import datetime, timedelta, timezone

import aiosqlite

from config import DB_PATH

DEFAULT_STATE = {"members": {}, "last_war_opponent": "", "last_war_attacks": []}


MAX_LINKED_PER_TYPE = 25   # Discord autocomplete shows at most 25 choices


class LinkError(Exception):
    """A link/unlink request that cannot be done; the message is safe to show to users."""


class ConfigError(Exception):
    """A settings / library change that cannot be done; the message is safe to show to users."""


async def _columns(db, table: str) -> set:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        return {r[1] for r in await cur.fetchall()}


async def _migration_1(db):
    """user_tags: primary / verified flags + cached label. Existing newest link stays the default."""
    cols = await _columns(db, "user_tags")
    if "is_primary" not in cols:
        await db.execute("ALTER TABLE user_tags ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0")
    if "is_verified" not in cols:
        await db.execute("ALTER TABLE user_tags ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
    if "label" not in cols:
        await db.execute("ALTER TABLE user_tags ADD COLUMN label TEXT")
    # Backfill: the row that used to win (highest rowid) per user and type becomes primary.
    await db.execute("""
        UPDATE user_tags SET is_primary = 1
        WHERE rowid IN (SELECT MAX(rowid) FROM user_tags GROUP BY discord_id, entity_type)""")


async def _migration_2(db):
    """Reminders (war / raid weekend / clan games) and their duplicate guard."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS reminder_configs (
            guild_id     INTEGER NOT NULL,
            clan_tag     TEXT    NOT NULL,
            channel_id   INTEGER NOT NULL,
            war_alerts   INTEGER NOT NULL DEFAULT 1,
            raid_alerts  INTEGER NOT NULL DEFAULT 1,
            games_alerts INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, clan_tag)
        )""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sent_reminders (
            reminder_key TEXT PRIMARY KEY,
            sent_at      TEXT NOT NULL
        )""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS games_events (
            clan_tag    TEXT NOT NULL,
            event_id    TEXT NOT NULL,
            baseline_ok INTEGER NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY (clan_tag, event_id)
        )""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS games_baselines (
            clan_tag   TEXT NOT NULL,
            event_id   TEXT NOT NULL,
            player_tag TEXT NOT NULL,
            points     INTEGER NOT NULL,
            PRIMARY KEY (clan_tag, event_id, player_tag)
        )""")


async def _migration_3(db):
    """Activity tracker and season leaderboards: one snapshot row per player."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS player_snapshots (
            player_tag            TEXT PRIMARY KEY,
            clan_tag              TEXT,
            name                  TEXT,
            town_hall             INTEGER,
            first_seen_at         TEXT NOT NULL,
            last_active_at        TEXT,
            last_fingerprint      TEXT,
            season_id             TEXT,
            donations             INTEGER NOT NULL DEFAULT 0,
            donations_received    INTEGER NOT NULL DEFAULT 0,
            war_stars             INTEGER NOT NULL DEFAULT 0,
            gold                  INTEGER NOT NULL DEFAULT 0,
            elixir                INTEGER NOT NULL DEFAULT 0,
            dark_elixir           INTEGER NOT NULL DEFAULT 0,
            capital               INTEGER NOT NULL DEFAULT 0,
            war_stars_baseline    INTEGER NOT NULL DEFAULT 0,
            gold_baseline         INTEGER NOT NULL DEFAULT 0,
            elixir_baseline       INTEGER NOT NULL DEFAULT 0,
            dark_elixir_baseline  INTEGER NOT NULL DEFAULT 0,
            capital_baseline      INTEGER NOT NULL DEFAULT 0,
            baseline_at           TEXT,
            updated_at            TEXT NOT NULL
        )""")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_clan ON player_snapshots (clan_tag)")


async def _migration_4(db):
    """Base layout library, one-vote-per-user upvotes, and per-server feature flags."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS saved_bases (
            base_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id     INTEGER NOT NULL,
            submitted_by INTEGER NOT NULL,
            th_level     INTEGER NOT NULL,
            category     TEXT    NOT NULL,
            layout_url   TEXT    NOT NULL,
            notes        TEXT,
            upvotes      INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT    NOT NULL,
            UNIQUE (guild_id, layout_url)
        )""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS base_votes (
            base_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (base_id, user_id)
        )""")
    await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_flags (
            guild_id    INTEGER PRIMARY KEY,
            auto_decode INTEGER NOT NULL DEFAULT 0
        )""")


# Append new steps here; never edit or reorder an applied one. Step N runs once, in order.
MIGRATIONS = [_migration_1, _migration_2, _migration_3, _migration_4]


async def _migrate(db):
    await db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    async with db.execute("SELECT version FROM schema_version") as cur:
        row = await cur.fetchone()
    current = row[0] if row else 0
    if not row:
        await db.execute("INSERT INTO schema_version (version) VALUES (0)")
    await db.commit()
    for number, step in enumerate(MIGRATIONS, start=1):
        if number <= current:
            continue
        await db.execute("BEGIN")
        try:
            await step(db)
            await db.execute("UPDATE schema_version SET version=?", (number,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_tags (
                discord_id  INTEGER NOT NULL,
                tag         TEXT    NOT NULL,
                entity_type TEXT    NOT NULL CHECK (entity_type IN ('player','clan')),
                PRIMARY KEY (discord_id, tag)
            )""")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id         INTEGER PRIMARY KEY,
                channel_id       INTEGER,
                tracked_tag      TEXT,
                notif_join_leave INTEGER NOT NULL DEFAULT 1,
                notif_war        INTEGER NOT NULL DEFAULT 1,
                loot_enabled     INTEGER NOT NULL DEFAULT 1,
                initiated_by     TEXT,
                state_json       TEXT NOT NULL DEFAULT '{}'
            )""")
        await db.commit()
        await _migrate(db)


# ── Linked accounts ──────────────────────────────────────────────────────────
# One primary row per (user, entity_type). The primary is what commands use when no
# tag is typed. The first account a user links becomes primary; later ones do not
# take over unless make_primary=True.
async def link_account(discord_id: int, tag: str, entity_type: str = "player", *,
                       make_primary: bool = False, verified: bool = False,
                       label: str | None = None, force: bool = False) -> dict:
    """Add (or refresh) a linked tag. Returns {"is_primary", "is_verified", "new"}.

    Re-linking an existing tag never removes its verified badge or primary flag.
    Raises LinkError when the per-type account limit is reached or the tag is
    already verified by a different user and `verified` is False (`force=True`,
    used by the owner-only /adminlink, skips that second check).
    A fresh `verified=True` takes the badge away from any other user's link to the
    same tag: the newest proof of ownership wins.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT is_primary, is_verified FROM user_tags WHERE discord_id=? AND tag=?",
                (discord_id, tag)) as cur:
            existing = await cur.fetchone()
        if not existing:
            async with db.execute(
                    "SELECT COUNT(*) FROM user_tags WHERE discord_id=? AND entity_type=?",
                    (discord_id, entity_type)) as cur:
                if (await cur.fetchone())[0] >= MAX_LINKED_PER_TYPE:
                    raise LinkError(f"You can link at most {MAX_LINKED_PER_TYPE} "
                                    f"{entity_type} accounts. Unlink one with `/accounts` first.")
        if not verified and not force:
            async with db.execute(
                    "SELECT 1 FROM user_tags WHERE tag=? AND is_verified=1 AND discord_id<>?",
                    (tag, discord_id)) as cur:
                if await cur.fetchone():
                    raise LinkError("This tag is already **verified** by another user, so it can't be "
                                    "linked without an API token. To link it, use `/link` and add the "
                                    "API token from your in-game settings.")
        async with db.execute(
                "SELECT COUNT(*) FROM user_tags WHERE discord_id=? AND entity_type=? AND is_primary=1 AND tag<>?",
                (discord_id, entity_type, tag)) as cur:
            other_primary = (await cur.fetchone())[0] > 0

        was_primary = bool(existing[0]) if existing else False
        was_verified = bool(existing[1]) if existing else False
        primary = was_primary or make_primary or not other_primary
        is_verified = was_verified or verified
        if primary:
            await db.execute("UPDATE user_tags SET is_primary=0 WHERE discord_id=? AND entity_type=?",
                             (discord_id, entity_type))
        await db.execute("""
            INSERT INTO user_tags (discord_id, tag, entity_type, is_primary, is_verified, label)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(discord_id, tag) DO UPDATE SET
                is_primary=excluded.is_primary, is_verified=excluded.is_verified,
                label=COALESCE(excluded.label, user_tags.label)""",
            (discord_id, tag, entity_type, int(primary), int(is_verified), label))
        if verified:
            await db.execute("UPDATE user_tags SET is_verified=0 WHERE tag=? AND discord_id<>?", (tag, discord_id))
        await db.commit()
    return {"is_primary": primary, "is_verified": is_verified, "new": existing is None}


async def get_linked_account(discord_id: int, entity_type: str = "player"):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tag FROM user_tags WHERE discord_id=? AND entity_type=? "
            "ORDER BY is_primary DESC, rowid DESC LIMIT 1",
            (discord_id, entity_type)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_all_linked_tags(discord_id: int, entity_type: str | None = None) -> list:
    return [a["tag"] for a in await get_linked_accounts(discord_id, entity_type)]


async def get_linked_accounts(discord_id: int, entity_type: str | None = None) -> list:
    """Full rows, primary first, then oldest link first."""
    q = "SELECT tag, entity_type, is_primary, is_verified, label FROM user_tags WHERE discord_id=?"
    params = [discord_id]
    if entity_type:
        q += " AND entity_type=?"
        params.append(entity_type)
    q += " ORDER BY entity_type, is_primary DESC, rowid"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return [{"tag": r[0], "entity_type": r[1], "is_primary": bool(r[2]),
                     "is_verified": bool(r[3]), "label": r[4]} for r in await cur.fetchall()]


async def set_primary(discord_id: int, tag: str) -> bool:
    """Make `tag` the primary of its type. False if the user hasn't linked it."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT entity_type FROM user_tags WHERE discord_id=? AND tag=?",
                              (discord_id, tag)) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await db.execute("UPDATE user_tags SET is_primary=0 WHERE discord_id=? AND entity_type=?",
                         (discord_id, row[0]))
        await db.execute("UPDATE user_tags SET is_primary=1 WHERE discord_id=? AND tag=?", (discord_id, tag))
        await db.commit()
    return True


async def unlink_account(discord_id: int, tag: str) -> bool:
    """Remove a link. If it was the primary, the oldest remaining account of that type is promoted."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT entity_type, is_primary FROM user_tags WHERE discord_id=? AND tag=?",
                (discord_id, tag)) as cur:
            row = await cur.fetchone()
        if not row:
            return False
        await db.execute("DELETE FROM user_tags WHERE discord_id=? AND tag=?", (discord_id, tag))
        if row[1]:
            await db.execute("""
                UPDATE user_tags SET is_primary=1 WHERE rowid = (
                    SELECT MIN(rowid) FROM user_tags WHERE discord_id=? AND entity_type=?)""",
                (discord_id, row[0]))
        await db.commit()
    return True


async def set_label(discord_id: int, tag: str, label: str):
    """Cache a display name (player/clan name) used by autocomplete."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_tags SET label=? WHERE discord_id=? AND tag=?", (label, discord_id, tag))
        await db.commit()


# ── Per-server config ────────────────────────────────────────────────────────
def _row_to_cfg(row) -> dict:
    return {
        "guild_id": row[0], "channel_id": row[1], "tracked_tag": row[2],
        "notif_join_leave": bool(row[3]), "notif_war": bool(row[4]),
        "loot_enabled": bool(row[5]), "initiated_by": row[6],
        "state": {**DEFAULT_STATE, **json.loads(row[7] or "{}")},
    }


_COLS = "guild_id, channel_id, tracked_tag, notif_join_leave, notif_war, loot_enabled, initiated_by, state_json"


async def get_guild_config(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {_COLS} FROM guild_config WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
    if row:
        return _row_to_cfg(row)
    return {"guild_id": guild_id, "channel_id": None, "tracked_tag": None,
            "notif_join_leave": True, "notif_war": True, "loot_enabled": True,
            "initiated_by": None, "state": dict(DEFAULT_STATE)}


async def all_guild_configs() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {_COLS} FROM guild_config") as cur:
            return [_row_to_cfg(r) for r in await cur.fetchall()]


async def save_guild_config(cfg: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
            INSERT INTO guild_config ({_COLS}) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id=excluded.channel_id, tracked_tag=excluded.tracked_tag,
                notif_join_leave=excluded.notif_join_leave, notif_war=excluded.notif_war,
                loot_enabled=excluded.loot_enabled, initiated_by=excluded.initiated_by,
                state_json=excluded.state_json""",
            (cfg["guild_id"], cfg["channel_id"], cfg["tracked_tag"],
             int(cfg["notif_join_leave"]), int(cfg["notif_war"]), int(cfg["loot_enabled"]),
             cfg["initiated_by"], json.dumps(cfg["state"])))
        await db.commit()


# ── Reminders ────────────────────────────────────────────────────────────────
MAX_REMINDER_CLANS_PER_GUILD = 5
_REMINDER_KINDS = {"war": "war_alerts", "raid": "raid_alerts", "games": "games_alerts"}


def _iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _rem_row(r) -> dict:
    return {"guild_id": r[0], "clan_tag": r[1], "channel_id": r[2],
            "war_alerts": bool(r[3]), "raid_alerts": bool(r[4]), "games_alerts": bool(r[5])}


async def upsert_reminder_config(guild_id: int, clan_tag: str, channel_id: int) -> dict:
    """Create the config (all alerts on) or move an existing one to a new channel (toggles kept)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM reminder_configs WHERE guild_id=? AND clan_tag=?",
                              (guild_id, clan_tag)) as cur:
            exists = await cur.fetchone()
        if not exists:
            async with db.execute("SELECT COUNT(*) FROM reminder_configs WHERE guild_id=?", (guild_id,)) as cur:
                if (await cur.fetchone())[0] >= MAX_REMINDER_CLANS_PER_GUILD:
                    raise ConfigError(f"A server can have at most {MAX_REMINDER_CLANS_PER_GUILD} reminder clans. "
                                      "Remove one with `/reminders remove` first.")
        await db.execute("""
            INSERT INTO reminder_configs (guild_id, clan_tag, channel_id) VALUES (?,?,?)
            ON CONFLICT(guild_id, clan_tag) DO UPDATE SET channel_id=excluded.channel_id""",
            (guild_id, clan_tag, channel_id))
        await db.commit()
    return (await get_reminder_configs(guild_id, clan_tag))[0]


async def get_reminder_configs(guild_id: int | None = None, clan_tag: str | None = None) -> list:
    q, params = ("SELECT guild_id, clan_tag, channel_id, war_alerts, raid_alerts, games_alerts "
                 "FROM reminder_configs WHERE 1=1"), []
    if guild_id is not None:
        q += " AND guild_id=?"; params.append(guild_id)
    if clan_tag is not None:
        q += " AND clan_tag=?"; params.append(clan_tag)
    q += " ORDER BY guild_id, clan_tag"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return [_rem_row(r) for r in await cur.fetchall()]


async def set_reminder_toggle(guild_id: int, clan_tag: str, kind: str, enabled: bool) -> bool:
    col = _REMINDER_KINDS[kind]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(f"UPDATE reminder_configs SET {col}=? WHERE guild_id=? AND clan_tag=?",
                               (int(enabled), guild_id, clan_tag))
        await db.commit()
        return cur.rowcount > 0


async def delete_reminder_config(guild_id: int, clan_tag: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM reminder_configs WHERE guild_id=? AND clan_tag=?", (guild_id, clan_tag))
        await db.commit()
        return cur.rowcount > 0


async def claim_reminder(key: str) -> bool:
    """Atomically record that `key` was sent. True only for the first caller, so a reminder never repeats."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT OR IGNORE INTO sent_reminders (reminder_key, sent_at) VALUES (?,?)",
                               (key, _iso()))
        await db.commit()
        return cur.rowcount == 1


async def release_reminder(key: str):
    """Forget a claim (used when posting failed so the next loop can retry)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sent_reminders WHERE reminder_key=?", (key,))
        await db.commit()


async def prune_reminders(days: int = 14) -> int:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=days))
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM sent_reminders WHERE sent_at < ?", (cutoff,))
        await db.execute("DELETE FROM games_baselines WHERE (clan_tag, event_id) IN "
                         "(SELECT clan_tag, event_id FROM games_events WHERE captured_at < ?)", (cutoff,))
        await db.execute("DELETE FROM games_events WHERE captured_at < ?", (cutoff,))
        await db.commit()
        return cur.rowcount


async def get_games_event(clan_tag: str, event_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT baseline_ok, captured_at FROM games_events WHERE clan_tag=? AND event_id=?",
                              (clan_tag, event_id)) as cur:
            row = await cur.fetchone()
    return {"baseline_ok": bool(row[0]), "captured_at": parse_iso(row[1])} if row else None


async def save_games_baselines(clan_tag: str, event_id: str, points: dict, ok: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO games_events (clan_tag, event_id, baseline_ok, captured_at) "
                         "VALUES (?,?,?,?)", (clan_tag, event_id, int(ok), _iso()))
        await db.executemany(
            "INSERT OR REPLACE INTO games_baselines (clan_tag, event_id, player_tag, points) VALUES (?,?,?,?)",
            [(clan_tag, event_id, t, int(v)) for t, v in points.items()])
        await db.commit()


async def get_games_baselines(clan_tag: str, event_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT player_tag, points FROM games_baselines WHERE clan_tag=? AND event_id=?",
                              (clan_tag, event_id)) as cur:
            return {r[0]: r[1] for r in await cur.fetchall()}


async def linked_discord_ids(tags: list) -> dict:
    """{player_tag: discord_id} for the given tags. A verified link wins over an unverified one."""
    if not tags:
        return {}
    out: dict = {}
    async with aiosqlite.connect(DB_PATH) as db:
        marks = ",".join("?" * len(tags))
        async with db.execute(
                f"SELECT tag, discord_id FROM user_tags WHERE entity_type='player' AND tag IN ({marks}) "
                "ORDER BY is_verified, rowid", list(tags)) as cur:
            for tag, discord_id in await cur.fetchall():
                out[tag] = discord_id          # later rows (verified last) overwrite earlier ones
    return out


# ── Activity snapshots ───────────────────────────────────────────────────────
SNAPSHOT_COLS = ["player_tag", "clan_tag", "name", "town_hall", "first_seen_at", "last_active_at",
                 "last_fingerprint", "season_id", "donations", "donations_received", "war_stars", "gold",
                 "elixir", "dark_elixir", "capital", "war_stars_baseline", "gold_baseline", "elixir_baseline",
                 "dark_elixir_baseline", "capital_baseline", "baseline_at", "updated_at"]


async def save_snapshots(rows: list):
    if not rows:
        return
    marks = ",".join("?" * len(SNAPSHOT_COLS))
    updates = ",".join(f"{c}=excluded.{c}" for c in SNAPSHOT_COLS[1:])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            f"INSERT INTO player_snapshots ({','.join(SNAPSHOT_COLS)}) VALUES ({marks}) "
            f"ON CONFLICT(player_tag) DO UPDATE SET {updates}",
            [tuple(r.get(c) for c in SNAPSHOT_COLS) for r in rows])
        await db.commit()


async def get_snapshots(tags: list) -> dict:
    if not tags:
        return {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        marks = ",".join("?" * len(tags))
        async with db.execute(f"SELECT * FROM player_snapshots WHERE player_tag IN ({marks})", list(tags)) as cur:
            return {r["player_tag"]: dict(r) for r in await cur.fetchall()}


async def watched_clan_tags() -> list:
    """Clans the hourly activity poll covers: every server's tracked clan plus every reminder clan."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT tracked_tag FROM guild_config WHERE tracked_tag IS NOT NULL AND tracked_tag<>'' "
                              "UNION SELECT clan_tag FROM reminder_configs") as cur:
            return sorted({r[0] for r in await cur.fetchall()})


# ── Base library ─────────────────────────────────────────────────────────────
MAX_BASES_PER_GUILD = 300


async def add_base(guild_id: int, submitted_by: int, th_level: int, category: str,
                   layout_url: str, notes: str | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM saved_bases WHERE guild_id=?", (guild_id,)) as cur:
            if (await cur.fetchone())[0] >= MAX_BASES_PER_GUILD:
                raise ConfigError(f"This server's base library is full ({MAX_BASES_PER_GUILD} layouts).")
        async with db.execute("SELECT base_id FROM saved_bases WHERE guild_id=? AND layout_url=?",
                              (guild_id, layout_url)) as cur:
            dup = await cur.fetchone()
        if dup:
            raise ConfigError(f"This layout is already saved (base #{dup[0]}).")
        cur = await db.execute(
            "INSERT INTO saved_bases (guild_id, submitted_by, th_level, category, layout_url, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?)", (guild_id, submitted_by, th_level, category, layout_url, notes, _iso()))
        await db.commit()
        return cur.lastrowid


_BASE_COLS = "base_id, guild_id, submitted_by, th_level, category, layout_url, notes, upvotes"


def _base_row(r) -> dict:
    return dict(zip(["base_id", "guild_id", "submitted_by", "th_level", "category", "layout_url", "notes",
                     "upvotes"], r))


async def list_bases(guild_id: int, th_level: int | None = None, category: str | None = None,
                     limit: int = 10, offset: int = 0) -> tuple:
    """(rows, total) ordered by upvotes then newest."""
    where, params = "guild_id=?", [guild_id]
    if th_level:
        where += " AND th_level=?"; params.append(th_level)
    if category:
        where += " AND category=?"; params.append(category)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT COUNT(*) FROM saved_bases WHERE {where}", params) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
                f"SELECT {_BASE_COLS} FROM saved_bases WHERE {where} "
                "ORDER BY upvotes DESC, base_id DESC LIMIT ? OFFSET ?", params + [limit, offset]) as cur:
            return [_base_row(r) for r in await cur.fetchall()], total


async def get_base(guild_id: int, base_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {_BASE_COLS} FROM saved_bases WHERE guild_id=? AND base_id=?",
                              (guild_id, base_id)) as cur:
            row = await cur.fetchone()
    return _base_row(row) if row else None


async def delete_base(guild_id: int, base_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM saved_bases WHERE guild_id=? AND base_id=?", (guild_id, base_id))
        if cur.rowcount:
            await db.execute("DELETE FROM base_votes WHERE base_id=?", (base_id,))
        await db.commit()
        return cur.rowcount > 0


async def toggle_base_vote(guild_id: int, base_id: int, user_id: int) -> tuple | None:
    """Upvote, or take the upvote back. Returns (new_count, voted_now) or None if the base doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM saved_bases WHERE guild_id=? AND base_id=?", (guild_id, base_id)) as cur:
            if not await cur.fetchone():
                return None
        async with db.execute("SELECT 1 FROM base_votes WHERE base_id=? AND user_id=?", (base_id, user_id)) as cur:
            had = await cur.fetchone()
        if had:
            await db.execute("DELETE FROM base_votes WHERE base_id=? AND user_id=?", (base_id, user_id))
        else:
            await db.execute("INSERT INTO base_votes (base_id, user_id) VALUES (?,?)", (base_id, user_id))
        await db.execute("UPDATE saved_bases SET upvotes=(SELECT COUNT(*) FROM base_votes WHERE base_id=?) "
                         "WHERE base_id=?", (base_id, base_id))
        async with db.execute("SELECT upvotes FROM saved_bases WHERE base_id=?", (base_id,)) as cur:
            count = (await cur.fetchone())[0]
        await db.commit()
    return count, not had


async def get_auto_decode(guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT auto_decode FROM guild_flags WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
    return bool(row[0]) if row else False


async def set_auto_decode(guild_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO guild_flags (guild_id, auto_decode) VALUES (?,?) "
                         "ON CONFLICT(guild_id) DO UPDATE SET auto_decode=excluded.auto_decode",
                         (guild_id, int(enabled)))
        await db.commit()
