"""SQLite storage. A fresh DB is created on first start (no Telegram data is imported).

Tables
  user_tags     – game tags (player/clan) linked to a Discord user ID
  guild_config  – per-server settings: notification channel, tracked clan,
                  notification toggles, loot toggle, and tracker state (JSON)
"""
import json
import aiosqlite

from config import DB_PATH

DEFAULT_STATE = {"members": {}, "last_war_opponent": "", "last_war_attacks": []}


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


# ── Linked accounts ──────────────────────────────────────────────────────────
async def link_account(discord_id: int, tag: str, entity_type: str = "player"):
    async with aiosqlite.connect(DB_PATH) as db:
        # REPLACE gives the row a new rowid, so the newest link becomes the default.
        await db.execute(
            "INSERT OR REPLACE INTO user_tags (discord_id, tag, entity_type) VALUES (?,?,?)",
            (discord_id, tag, entity_type))
        await db.commit()


async def get_linked_account(discord_id: int, entity_type: str = "player"):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tag FROM user_tags WHERE discord_id=? AND entity_type=? ORDER BY rowid DESC LIMIT 1",
            (discord_id, entity_type)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def get_all_linked_tags(discord_id: int, entity_type: str | None = None) -> list:
    q = "SELECT tag FROM user_tags WHERE discord_id=?"
    params = [discord_id]
    if entity_type:
        q += " AND entity_type=?"
        params.append(entity_type)
    q += " ORDER BY rowid"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q, params) as cur:
            return [r[0] for r in await cur.fetchall()]


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
