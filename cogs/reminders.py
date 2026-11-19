"""Automatic reminders (war, raid weekend, clan games) and /missing-hits.

Every REMINDER_LOOP_MINUTES the loop checks each configured clan. A reminder is sent once per
threshold (the duplicate guard is the sent_reminders table), pings linked members, and names
unlinked ones. Failed posts are retried on the next loop.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from coc_api import get_clan, get_current_raid, get_current_war_any, get_players_batch
from core import state
from core.autocomplete import linked_tag_choices
from core.clan_arg import resolve_clan
from core.helpers import normalize_tag
from core.nav import NavError, Page, send_page
from core.perms import channel_problem, is_admin
from core.reminder_logic import (format_missing, games_missing, games_points, games_window,
                                 human_duration, raid_missing, war_missing, war_tier)
from database import (ConfigError, claim_reminder, delete_reminder_config, get_games_baselines,
                      get_games_event, get_reminder_configs, linked_discord_ids,
                      prune_reminders, release_reminder, save_games_baselines, set_reminder_toggle,
                      upsert_reminder_config)

log = logging.getLogger(__name__)
KINDS = {"war": "⚔️ War", "raid": "🏰 Raid Weekend", "games": "🎮 Clan Games"}
_MENTIONS = discord.AllowedMentions(users=True, roles=False, everyone=False)


def _onoff(v: bool) -> str:
    return "✅ on" if v else "❌ off"


class RemindersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    # ── helpers ──────────────────────────────────────────────────────────────
    async def _clan_arg(self, interaction: discord.Interaction, clan: Optional[str]) -> str:
        return await resolve_clan(self.bot, interaction, clan)

    async def _guild_clan(self, interaction: discord.Interaction, clan: Optional[str]) -> dict:
        configs = await get_reminder_configs(interaction.guild_id)
        if not configs:
            raise NavError("No reminders are set up here yet. Use `/reminders setup` first.")
        if clan:
            for c in configs:
                if c["clan_tag"] == normalize_tag(clan):
                    return c
            raise NavError(f"`{normalize_tag(clan)}` has no reminders in this server. See `/reminders status`.")
        if len(configs) > 1:
            raise NavError("This server has several reminder clans; choose one with the `clan` option.")
        return configs[0]

    async def _guild_clan_ac(self, interaction: discord.Interaction, current: str):
        needle = current.strip().lower().lstrip("#")
        configs = await get_reminder_configs(interaction.guild_id) if interaction.guild_id else []
        return [app_commands.Choice(name=c["clan_tag"], value=c["clan_tag"])
                for c in configs if needle in c["clan_tag"].lower()][:25]

    # ── /reminders ───────────────────────────────────────────────────────────
    reminders = app_commands.Group(name="reminders", description="Automatic war / raid / clan games reminders",
                                   guild_only=True, default_permissions=discord.Permissions(manage_guild=True))

    @reminders.command(name="setup", description="Admin: start reminders for a clan in a channel")
    @app_commands.describe(clan="Clan tag (default: your linked or the tracked clan)",
                           channel="Where reminders are posted (default: this channel)")
    async def setup(self, interaction: discord.Interaction, clan: Optional[str] = None,
                    channel: Optional[discord.TextChannel] = None):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        if not self.bot.coc:
            await interaction.response.send_message("❌ CoC API is not connected. Check COC_EMAIL / COC_PASSWORD.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        tag = await self._clan_arg(interaction, clan)
        channel = channel or interaction.channel
        problem = channel_problem(channel, interaction.guild)
        if problem:
            raise NavError(problem)
        data = await get_clan(tag, self.bot.coc)
        if "error" in data:
            raise NavError(data["error"])
        try:
            cfg = await upsert_reminder_config(interaction.guild_id, tag, channel.id)
        except ConfigError as e:
            raise NavError(str(e))
        await send_page(interaction, Page(
            f"✅ Reminders for **{data.get('name', tag)}** (`{tag}`) go to {channel.mention}.\n\n"
            f"• {KINDS['war']}: {_onoff(cfg['war_alerts'])} — at {' and '.join(f'<{h}h' for h in config.WAR_REMINDER_HOURS)} left\n"
            f"• {KINDS['raid']}: {_onoff(cfg['raid_alerts'])} — under {config.RAID_REMINDER_HOURS}h left\n"
            f"• {KINDS['games']}: {_onoff(cfg['games_alerts'])} — under {config.GAMES_REMINDER_HOURS}h left, "
            f"below {config.GAMES_MAX_POINTS:,} points\n\n"
            "Linked members are pinged; others are named. Change this with `/reminders toggle`."))

    @reminders.command(name="toggle", description="Admin: turn war, raid or clan games reminders on or off")
    @app_commands.describe(type="Which reminder", enabled="Leave empty to flip it", clan="Clan (if the server has several)")
    @app_commands.choices(type=[app_commands.Choice(name=v, value=k) for k, v in KINDS.items()])
    async def toggle(self, interaction: discord.Interaction, type: app_commands.Choice[str],
                     enabled: Optional[bool] = None, clan: Optional[str] = None):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        cfg = await self._guild_clan(interaction, clan)
        new = (not cfg[f"{type.value}_alerts"]) if enabled is None else enabled
        await set_reminder_toggle(interaction.guild_id, cfg["clan_tag"], type.value, new)
        await send_page(interaction, Page(f"{KINDS[type.value]} reminders for `{cfg['clan_tag']}` are now {_onoff(new)}."))

    @toggle.autocomplete("clan")
    async def _toggle_clan_ac(self, interaction: discord.Interaction, current: str):
        return await self._guild_clan_ac(interaction, current)

    @reminders.command(name="status", description="Show this server's reminder settings")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        configs = await get_reminder_configs(interaction.guild_id)
        if not configs:
            await send_page(interaction, Page("No reminders are set up here yet. An admin can use `/reminders setup`."))
            return
        lines = ["⏰ **Reminders in this server**", ""]
        for c in configs:
            lines.append(f"`{c['clan_tag']}` → <#{c['channel_id']}>\n"
                         f"   war {_onoff(c['war_alerts'])} · raid {_onoff(c['raid_alerts'])} · "
                         f"games {_onoff(c['games_alerts'])}")
        await send_page(interaction, Page("\n".join(lines)))

    @reminders.command(name="remove", description="Admin: stop reminders for a clan")
    @app_commands.describe(clan="Clan (if the server has several)")
    async def remove(self, interaction: discord.Interaction, clan: Optional[str] = None):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        cfg = await self._guild_clan(interaction, clan)
        await delete_reminder_config(interaction.guild_id, cfg["clan_tag"])
        await send_page(interaction, Page(f"🗑️ Reminders for `{cfg['clan_tag']}` removed."))

    @remove.autocomplete("clan")
    async def _remove_clan_ac(self, interaction: discord.Interaction, current: str):
        return await self._guild_clan_ac(interaction, current)

    # ── /missing-hits ────────────────────────────────────────────────────────
    @app_commands.command(name="missing-hits", description="Who still has attacks left in the current war / raid weekend")
    @app_commands.describe(clan="Clan tag (optional if you linked a clan)", type="War or raid weekend (default: both)")
    @app_commands.choices(type=[app_commands.Choice(name="War", value="war"),
                                app_commands.Choice(name="Raid weekend", value="raid")])
    async def missing_hits(self, interaction: discord.Interaction, clan: Optional[str] = None,
                           type: Optional[app_commands.Choice[str]] = None):
        await interaction.response.defer(thinking=True)
        tag = await self._clan_arg(interaction, clan)
        kind = type.value if type else "both"
        parts = [f"🔎 **Missing hits — `{tag}`**", ""]
        if kind in ("war", "both"):
            parts.append(await self._war_section(tag))
        if kind in ("raid", "both"):
            parts.append(await self._raid_section(tag))
        await send_page(interaction, Page("\n".join(parts)))

    @missing_hits.autocomplete("clan")
    async def _missing_clan_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    async def _war_section(self, tag: str, war: dict | None = None, *, mentions: bool = True) -> str:
        war = war or await get_current_war_any(tag, self.bot.coc)
        if "error" in war:
            return f"⚔️ **War:** ❌ {war['error']}"
        info = war_missing(war)
        if info is None:
            return "⚔️ **War:** no war in battle day right now."
        kind = "CWL war" if info["is_cwl"] else "War"
        head = f"⚔️ **{kind}** — ends in {human_duration(info['remaining'])}"
        if not info["members"]:
            return head + "\n🎉 Everyone has used all attacks."
        ids = await linked_discord_ids([m["tag"] for m in info["members"]]) if mentions else {}
        return f"{head}\n{format_missing(info['members'], ids, unit='attacks')}"

    async def _raid_section(self, tag: str, raid: dict | None = None, clan: dict | None = None) -> str:
        raid = raid or await get_current_raid(tag, self.bot.coc)
        if "error" in raid:
            return f"🏰 **Raid weekend:** ❌ {raid['error']}"
        clan = clan or await get_clan(tag, self.bot.coc)
        members = clan.get("memberList") if "error" not in clan else None
        info = raid_missing(raid, members)
        if info is None:
            return "🏰 **Raid weekend:** none running right now."
        head = f"🏰 **Raid weekend** — ends in {human_duration(info['remaining'])}"
        if not info["members"]:
            return head + "\n🎉 Everyone has used all attacks."
        ids = await linked_discord_ids([m["tag"] for m in info["members"]])
        return f"{head}\n{format_missing(info['members'], ids, unit='attacks')}"

    # ── automatic reminders ──────────────────────────────────────────────────
    async def _send(self, cfg: dict, title: str, body: str, mention_ids: list) -> bool:
        channel = self.bot.get_channel(cfg["channel_id"])
        try:
            channel = channel or await self.bot.fetch_channel(cfg["channel_id"])
            content = " ".join(f"<@{i}>" for i in dict.fromkeys(mention_ids))[:1900] or None
            await channel.send(content=content, embed=discord.Embed(title=title, description=body[:4000],
                                                                    colour=discord.Colour.orange()),
                               allowed_mentions=_MENTIONS)
            return True
        except (discord.Forbidden, discord.NotFound, discord.HTTPException, AttributeError):
            log.warning("Could not post reminder for %s in channel %s", cfg["clan_tag"], cfg["channel_id"])
            return False

    async def _fire(self, cfg: dict, key: str, title: str, entries: list, unit: str):
        """Claim `key`, post the reminder, and give the claim back if posting failed or crashed."""
        if not entries or not await claim_reminder(key):
            return
        try:
            ids = await linked_discord_ids([e["tag"] for e in entries])
            body = format_missing(entries, ids, unit=unit)
            sent = await self._send(cfg, title, body, [ids[e["tag"]] for e in entries if e["tag"] in ids])
        except Exception:
            await release_reminder(key)
            raise
        if not sent:
            await release_reminder(key)

    async def process_clan(self, cfg: dict, cache: dict, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        tag, guild = cfg["clan_tag"], cfg["guild_id"]

        async def cached(name, fn):
            if (name, tag) not in cache:
                cache[(name, tag)] = await fn(tag, self.bot.coc)
            return cache[(name, tag)]

        if cfg["war_alerts"]:
            war = await cached("war", get_current_war_any)
            info = war_missing(war, now) if "error" not in war else None
            tier = war_tier(info["remaining"]) if info else None
            if tier:
                kind = "CWL war" if info["is_cwl"] else "War"
                await self._fire(cfg, f"war:{guild}:{tag}:{info['end_raw']}:{tier}h",
                                 f"⚔️ {kind} ends in under {tier}h — {info['clan_name'] or tag}",
                                 info["members"], "attacks")

        if cfg["raid_alerts"]:
            raid = await cached("raid", get_current_raid)
            if "error" not in raid and raid.get("state") == "ongoing":
                clan = await cached("clan", get_clan)
                info = raid_missing(raid, clan.get("memberList") if "error" not in clan else None, now)
                if info and 0 < info["remaining"] <= config.RAID_REMINDER_HOURS * 3600:
                    await self._fire(cfg, f"raid:{guild}:{tag}:{info['end_raw']}",
                                     f"🏰 Raid weekend ends in {human_duration(info['remaining'])} — {clan.get('name', tag)}",
                                     info["members"], "attacks")

        if cfg["games_alerts"]:
            await self._process_games(cfg, cache, now)

    async def _process_games(self, cfg: dict, cache: dict, now: datetime):
        window = games_window(now)
        if not window:
            return
        start, end, event_id = window
        tag, guild = cfg["clan_tag"], cfg["guild_id"]
        clan = cache.get(("clan", tag)) or await get_clan(tag, self.bot.coc)
        cache[("clan", tag)] = clan
        if "error" in clan:
            return
        member_tags = [m["tag"] for m in clan.get("memberList", [])]
        event = await get_games_event(tag, event_id)
        if event is None:               # first look at this event: record everyone's starting points
            players = await get_players_batch(member_tags, self.bot.coc, ttl=0)
            points = {t: p for t, d in players.items() if "error" not in d and (p := games_points(d)) is not None}
            ok = (now - start).total_seconds() <= config.GAMES_BASELINE_GRACE_HOURS * 3600
            await save_games_baselines(tag, event_id, points, ok)
            if not ok:
                log.info("Clan games baseline for %s taken late; no reminders for event %s", tag, event_id)
            return
        remaining = (end - now).total_seconds()
        if not event["baseline_ok"] or remaining > config.GAMES_REMINDER_HOURS * 3600:
            return
        key = f"games:{guild}:{tag}:{event_id}"
        if not await claim_reminder(key):
            return
        try:
            players = await get_players_batch(member_tags, self.bot.coc, ttl=0)
            now_points = {t: (d.get("name", "?"), p) for t, d in players.items()
                          if "error" not in d and (p := games_points(d)) is not None}
            entries = games_missing(now_points, await get_games_baselines(tag, event_id))
            if not entries:
                return
            ids = await linked_discord_ids([e["tag"] for e in entries])
            title = f"🎮 Clan Games end in {human_duration(remaining)} — {clan.get('name', tag)}"
            sent = await self._send(cfg, title, format_missing(entries, ids, unit="pts"),
                                    [ids[e["tag"]] for e in entries if e["tag"] in ids])
        except Exception:
            await release_reminder(key)
            raise
        if not sent:
            await release_reminder(key)

    @tasks.loop(minutes=config.REMINDER_LOOP_MINUTES)
    async def reminder_loop(self):
        if state.maintenance or not self.bot.coc:
            return
        cache: dict = {}
        for cfg in await get_reminder_configs():
            try:
                await self.process_clan(cfg, cache)
            except Exception:
                log.exception("Reminder check failed for %s", cfg.get("clan_tag"))
        await prune_reminders()

    @reminder_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(RemindersCog(bot))
