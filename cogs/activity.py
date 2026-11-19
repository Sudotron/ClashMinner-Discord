"""Clan activity tracker (/activity) and season leaderboards (/leaderboard).

The API has no "last online" value. We poll each watched clan every ACTIVITY_LOOP_MINUTES and call a
member active when their play-only counters change (see core/activity_logic.py). Clans on the watch
list: every server's /clantrack clan and every /reminders clan. Other clans are polled on demand.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from coc_api import get_clan, get_players_batch
from core import state
from core.activity_logic import STATS, LIVE_STATS, is_inactive, last_seen_label, observe, sort_by_activity
from core.autocomplete import linked_tag_choices
from core.clan_arg import resolve_clan
from core.helpers import ApiError, fmt_number
from core.nav import Page, send_page
from core.seasons import season_id
from database import get_snapshots, save_snapshots, watched_clan_tags

log = logging.getLogger(__name__)
ON_DEMAND_COOLDOWN = 300          # seconds between on-demand polls of the same clan
STALE_AFTER = 2 * config.ACTIVITY_LOOP_MINUTES * 60


class ActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_poll: dict = {}
        self.poll_loop.start()

    def cog_unload(self):
        self.poll_loop.cancel()

    # ── polling ──────────────────────────────────────────────────────────────
    async def poll_clan(self, clan_tag: str, clan: dict | None = None, now: datetime | None = None) -> list:
        """Fetch every member, update their snapshots, and return the fresh rows."""
        now = now or datetime.now(timezone.utc)
        clan = clan or await get_clan(clan_tag, self.bot.coc)
        if "error" in clan:
            raise ApiError(clan["error"])
        tags = [m["tag"] for m in clan.get("memberList", [])]
        players = await get_players_batch(tags, self.bot.coc, ttl=0)
        prev = await get_snapshots(tags)
        season = season_id(now)
        rows = [observe(prev.get(t), d, season, now) for t, d in players.items() if "error" not in d]
        await save_snapshots(rows)
        self._last_poll[clan_tag] = time.monotonic()
        return rows

    async def _fresh_rows(self, clan_tag: str, clan: dict) -> tuple:
        """Snapshot rows for the clan's current members, polling now if data is missing or stale."""
        tags = [m["tag"] for m in clan.get("memberList", [])]
        snaps = await get_snapshots(tags)
        newest = max((s["updated_at"] for s in snaps.values()), default=None)
        stale = newest is None or (datetime.now(timezone.utc) - datetime.strptime(
            newest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() > STALE_AFTER
        incomplete = any(t not in snaps for t in tags)
        cooled = time.monotonic() - self._last_poll.get(clan_tag, 0) > ON_DEMAND_COOLDOWN
        polled = False
        if (stale or incomplete) and cooled and self.bot.coc:
            rows = await self.poll_clan(clan_tag, clan)
            snaps, polled = {r["player_tag"]: r for r in rows}, True
        return [snaps[t] for t in tags if t in snaps], polled

    async def _watch_note(self, clan_tag: str) -> str:
        if clan_tag in await watched_clan_tags():
            return ""
        return ("\n\n_This clan is not on the hourly watch list, so the data only refreshes when someone runs this "
                "command. An admin can run `/clantrack` or `/reminders setup` to keep it up to date._")

    @tasks.loop(minutes=config.ACTIVITY_LOOP_MINUTES)
    async def poll_loop(self):
        if state.maintenance or not self.bot.coc:
            return
        for tag in await watched_clan_tags():
            try:
                await self.poll_clan(tag)
            except Exception:
                log.exception("Activity poll failed for %s", tag)
            await asyncio.sleep(1)

    @poll_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    # ── /activity ────────────────────────────────────────────────────────────
    @app_commands.command(name="activity", description="Who is active and who is not: last activity per clan member")
    @app_commands.describe(clan="Clan tag (optional if you linked a clan)")
    async def activity(self, interaction: discord.Interaction, clan: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        tag = await resolve_clan(self.bot, interaction, clan)
        data = await get_clan(tag, self.bot.coc)
        if "error" in data:
            raise ApiError(data["error"])
        rows, polled = await self._fresh_rows(tag, data)
        if not rows:
            raise ApiError("No activity data yet. Try again in a few minutes.")
        now = datetime.now(timezone.utc)
        lines = [f"📊 **Activity — {data.get('name', tag)}** (`{tag}`)", ""]
        for r in sort_by_activity(rows)[:50]:
            flag = "🔴" if is_inactive(r, now) else "🟢"
            lines.append(f"{flag} **{r['name']}** — {last_seen_label(r, now)}")
        inactive = sum(1 for r in rows if is_inactive(r, now))
        lines += ["", f"🔴 inactive ≥ {config.INACTIVE_DAYS} days: **{inactive}** of {len(rows)} tracked",
                  "_Activity = a change in war stars, XP, loot or donation achievements. The game has no real "
                  "“last online” value, so this is a close estimate that starts when tracking began._"]
        await send_page(interaction, Page("\n".join(lines) + await self._watch_note(tag)))

    @activity.autocomplete("clan")
    async def _activity_clan_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    # ── /leaderboard ─────────────────────────────────────────────────────────
    @app_commands.command(name="leaderboard", description="Clan season leaderboard: donations, war stars, loot, capital gold")
    @app_commands.describe(clan="Clan tag (optional if you linked a clan)", stat="What to rank by (default: donations)")
    @app_commands.choices(stat=[app_commands.Choice(name=v[0][:100], value=k) for k, v in STATS.items()])
    async def leaderboard(self, interaction: discord.Interaction, clan: Optional[str] = None,
                          stat: Optional[app_commands.Choice[str]] = None):
        await interaction.response.defer(thinking=True)
        key = stat.value if stat else "donations"
        label, fn = STATS[key]
        tag = await resolve_clan(self.bot, interaction, clan)
        data = await get_clan(tag, self.bot.coc)
        if "error" in data:
            raise ApiError(data["error"])
        rows, _ = await self._fresh_rows(tag, data)
        if not rows:
            raise ApiError("No data yet. Try again in a few minutes.")
        ranked = sorted(rows, key=fn, reverse=True)[:25]
        fmt = (lambda v: f"{v:.2f}") if key == "ratio" else (lambda v: fmt_number(v))
        lines = [f"🏆 **{label}** — {data.get('name', tag)}", f"Season {season_id()} · `{tag}`", ""]
        for i, r in enumerate(ranked, 1):
            lines.append(f"**{i}.** {r['name']} — {fmt(fn(r))}")
        if key not in LIVE_STATS and all(fn(r) == 0 for r in rows):
            lines += ["", "_No gains seen yet: this stat counts from when the bot first saw each player this season._"]
        elif key not in LIVE_STATS:
            lines += ["", "_Counted from when the bot first saw each player this season._"]
        await send_page(interaction, Page("\n".join(lines) + await self._watch_note(tag)))

    @leaderboard.autocomplete("clan")
    async def _leaderboard_clan_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")


async def setup(bot):
    await bot.add_cog(ActivityCog(bot))
