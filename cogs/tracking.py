"""Clan tracking: /clantrack, /deltrack, /trackinfo, /setchannel + the 30-second change scanner.

Per-server: each Discord server can track one clan and posts to its own channel.
Announces joins, leaves, promotions/demotions, war found, live war attacks and war results.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import coc
import discord
from discord import app_commands
from discord.ext import commands, tasks

from coc_api import get_clan_war
from core.builders import _parse_coc_time
from core.helpers import normalize_tag, clan_url
from core.nav import Btn, Markup, NavError, Page, send_page
from core.perms import channel_problem, is_admin
from database import all_guild_configs, get_guild_config, save_guild_config

log = logging.getLogger(__name__)

ROLE_ORDER = {"Member": 0, "Elder": 1, "Co-Leader": 2, "Leader": 3}


def _plink(name: str, tag: str) -> str:
    return f"[{name}](https://link.clashofclans.com/en?action=OpenPlayerProfile&tag={tag.replace('#', '%23')})"


def _snapshot(members) -> dict:
    return {m.tag: {"name": m.name, "role": str(m.role),
                    "town_hall": getattr(m, "town_hall", "N/A"),
                    "exp_level": getattr(m, "exp_level", "N/A")} for m in members}


def _toggle_markup(cfg: dict) -> Markup:
    jl, war = cfg["notif_join_leave"], cfg["notif_war"]
    return Markup([[Btn(f"{'✅' if jl else '❌'} Join/Leave", cb="tkcfg:join_leave"),
                    Btn(f"{'✅' if war else '❌'} War", cb="tkcfg:war")],
                   [Btn(f"{'✅' if jl and war else '⬜'} All", cb="tkcfg:all")]])


class Tracking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.scan_loop.start()

    def cog_unload(self):
        self.scan_loop.cancel()

    # ── commands ─────────────────────────────────────────────────────────────
    @app_commands.command(name="clantrack", description="Admin: start join/leave/promotion/war logs for a clan")
    @app_commands.describe(tag="Clan tag to track", channel="Channel for the logs (default: this channel)")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def clantrack(self, interaction: discord.Interaction, tag: str,
                        channel: Optional[discord.TextChannel] = None):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        if not self.bot.coc:
            await interaction.response.send_message(
                "❌ CoC API is not connected. Check COC_EMAIL / COC_PASSWORD in `.env`.", ephemeral=True)
            return
        channel = channel or interaction.channel
        problem = channel_problem(channel, interaction.guild)
        if problem:
            await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        tag = normalize_tag(tag)
        try:
            clan = await self.bot.coc.get_clan(tag)
        except Exception as e:
            await interaction.followup.send(f"❌ Error finding clan: {e}")
            return

        war = await get_clan_war(tag, self.bot.coc)
        opponent = war.get("opponent", {}).get("tag", "") if "error" not in war and war.get("state") == "preparation" else ""
        cfg = await get_guild_config(interaction.guild_id)
        cfg.update(tracked_tag=tag, channel_id=channel.id, initiated_by=interaction.user.display_name,
                   notif_join_leave=True, notif_war=True,
                   state={"members": _snapshot(clan.members), "last_war_opponent": opponent, "last_war_attacks": []})
        await save_guild_config(cfg)

        text = (f"✅ Now tracking **{clan.name}** (`{tag}`) in {channel.mention}\n\n"
                f"🔔 **Notification Settings:**\nUse the buttons below to toggle what you receive.")
        thumb = getattr(clan.badge, "url", None)
        await send_page(interaction, Page(text, _toggle_markup(cfg), thumb_url=thumb),
                        self._make_router(interaction, text, thumb))
        log.info("Guild %s now tracking %s", interaction.guild_id, tag)

    @app_commands.command(name="deltrack", description="Admin: stop tracking the clan")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def deltrack(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        cfg = await get_guild_config(interaction.guild_id)
        cfg.update(tracked_tag=None, initiated_by=None, state={"members": {}, "last_war_opponent": "", "last_war_attacks": []})
        await save_guild_config(cfg)
        await interaction.response.send_message(f"🛑 Tracking stopped by {interaction.user.mention}.")

    @app_commands.command(name="trackinfo", description="Show the tracked clan and notification settings")
    @app_commands.guild_only()
    async def trackinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        cfg = await get_guild_config(interaction.guild_id)
        if not cfg["tracked_tag"]:
            await interaction.followup.send("No clan is currently being tracked. Use `/clantrack`.")
            return
        if not self.bot.coc:
            await interaction.followup.send("❌ CoC API is not connected.")
            return
        try:
            clan = await self.bot.coc.get_clan(cfg["tracked_tag"])
        except Exception as e:
            await interaction.followup.send(f"❌ Error fetching clan details: {e}")
            return
        ch = f"<#{cfg['channel_id']}>" if cfg["channel_id"] else "not set"
        text = (f"🛡️ **Currently Tracked Clan**\n\n🏷️ **Name:** {clan.name}\n📎 **Tag:** {clan.tag}\n"
                f"📝 **Bio:** {clan.description or 'No bio available'}\n\n"
                f"📣 **Log channel:** {ch}\n👤 **Tracking initiated by:** {cfg['initiated_by'] or 'System'}\n\n"
                f"🔔 **Notifications:**\n{'✅' if cfg['notif_join_leave'] else '❌'} Join/Leave  |  {'✅' if cfg['notif_war'] else '❌'} War")
        thumb = getattr(clan.badge, "url", None)
        await send_page(interaction, Page(text, _toggle_markup(cfg), thumb_url=thumb),
                        self._make_router(interaction, text, thumb))

    @app_commands.command(name="setchannel", description="Admin: channel for loot updates and maintenance alerts")
    @app_commands.describe(channel="Channel to post in")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        problem = channel_problem(channel, interaction.guild)
        if problem:
            await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
            return
        cfg = await get_guild_config(interaction.guild_id)
        cfg["channel_id"] = channel.id
        await save_guild_config(cfg)
        await interaction.response.send_message(f"✅ Notifications (loot, maintenance, tracking) will post in {channel.mention}.")

    def _make_router(self, interaction: discord.Interaction, text: str, thumb: Optional[str]):
        async def route(cb: str) -> Page:
            if not is_admin(interaction):
                raise NavError("❌ Only server admins can change tracking settings.")
            action = cb.split(":", 1)[1]
            cfg = await get_guild_config(interaction.guild_id)
            if not cfg["tracked_tag"]:
                raise NavError("No clan is being tracked.")
            if action == "all":
                new = not (cfg["notif_join_leave"] and cfg["notif_war"])
                cfg["notif_join_leave"] = cfg["notif_war"] = new
            elif action == "join_leave":
                cfg["notif_join_leave"] = not cfg["notif_join_leave"]
            elif action == "war":
                cfg["notif_war"] = not cfg["notif_war"]
            await save_guild_config(cfg)
            return Page(text, _toggle_markup(cfg), thumb_url=thumb)  # only the button states change
        return route

    # ── scanner ──────────────────────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def scan_loop(self):
        if not self.bot.coc:
            return
        from core import state as rt
        if rt.maintenance:
            return
        for cfg in await all_guild_configs():
            if cfg["tracked_tag"] and cfg["channel_id"]:
                try:
                    await self._scan(cfg)
                except Exception:
                    log.exception("Tracking scan failed for guild %s", cfg["guild_id"])

    @scan_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()

    async def _scan(self, cfg: dict):
        tag, st, ch = cfg["tracked_tag"], cfg["state"], cfg["channel_id"]
        clan = await self.bot.coc.get_clan(tag)
        current = {m.tag: m for m in clan.members}
        notify = lambda text: self.bot.notify(ch, text)

        if not st.get("members"):  # first run for this clan: just remember the roster
            st["members"] = _snapshot(current.values())
            war = await get_clan_war(tag, self.bot.coc)
            st["last_war_opponent"] = war.get("opponent", {}).get("tag", "") if "error" not in war and war.get("state") == "preparation" else ""
            await save_guild_config(cfg)
            return

        prev = st["members"]
        prev_tags, curr_tags = set(prev), set(current)
        changed = False

        for t in prev_tags - curr_tags:                       # left
            if cfg["notif_join_leave"]:
                p = prev[t]
                await notify(f"❌ {_plink(p['name'], t)} has left the clan.\n🏠 Town Hall: {p.get('town_hall', 'N/A')}\n⭐ XP Level: {p.get('exp_level', 'N/A')}")
        for t in curr_tags - prev_tags:                       # joined
            if cfg["notif_join_leave"]:
                m = current[t]
                await notify(f"✅ {_plink(m.name, t)} has joined the clan!\n🏠 Town Hall: {getattr(m, 'town_hall', 'N/A')}\n⭐ XP Level: {getattr(m, 'exp_level', 'N/A')}")
        for t in prev_tags & curr_tags:                       # promoted / demoted
            old, new = prev[t].get("role", "Member"), str(current[t].role)
            if old != new:
                changed = True
                if cfg["notif_join_leave"]:
                    verb = "promoted" if ROLE_ORDER.get(new, 0) > ROLE_ORDER.get(old, 0) else "demoted"
                    icon = "🎖️" if verb == "promoted" else "📉"
                    await notify(f"{icon} {_plink(current[t].name, t)} has been *{verb}* to {new}{'!' if verb == 'promoted' else '.'}")

        war = await get_clan_war(tag, self.bot.coc)
        if "error" not in war:
            changed |= await self._scan_war(cfg, st, clan, war, notify)

        if prev_tags != curr_tags or changed:
            st["members"] = _snapshot(current.values())
            await save_guild_config(cfg)

    async def _scan_war(self, cfg, st, clan, war, notify) -> bool:
        state, o = war.get("state"), war.get("opponent", {})
        o_tag, wn = o.get("tag", ""), cfg["notif_war"]
        changed = False

        if state == "preparation":
            if st.get("last_war_opponent") != o_tag:
                st["last_war_opponent"] = o_tag
                changed = True
                if wn:
                    start = _parse_coc_time(war.get("startTime", ""))
                    if start:
                        secs = int((start - datetime.now(timezone.utc)).total_seconds())
                        h, rem = divmod(max(secs, 0), 3600)
                        prep = f"{h} hours" if h > 0 else f"{rem // 60} minutes"
                    else:
                        prep = "Unknown"
                    size = war.get("teamSize", "?")
                    await notify(f"⚔️ **War Found!**\n**{clan.name}** vs **[{o.get('name', 'Unknown')}]({clan_url(o_tag)})**\n"
                                 f"👥 Size: {size}v{size}\n⏳ Preparation Time: {prep}")
        elif state == "inWar":
            known = set(st.get("last_war_attacks", []))
            cm, om = war.get("clan", {}).get("members", []), o.get("members", [])
            lookup = {m.get("tag", ""): m for m in cm + om}
            new = []
            for members, own in ((cm, True), (om, False)):
                for m in members:
                    for a in m.get("attacks", []):
                        if a.get("order", 0) not in known:
                            d = lookup.get(a.get("defenderTag", ""), {})
                            new.append((a.get("order", 0), own, m, a, d))
            new.sort(key=lambda x: x[0])
            for order, own, m, a, d in new:
                stars = "⭐" * a.get("stars", 0) + "☆" * (3 - a.get("stars", 0))
                head, icon = ("War Attack!", "⚔️") if own else ("Enemy Attack!", "🏴")
                if wn:
                    await notify(f"{icon} **{head}**\n{'🛡️' if own else '🏴'} **{m.get('name', 'Unknown')}** (TH{m.get('townhallLevel', '?')}) attacked "
                                 f"**{d.get('name', 'Unknown')}** (TH{d.get('townhallLevel', '?')}) — Base #{d.get('mapPosition', '?')}\n"
                                 f"{stars} | 💥 {a.get('destructionPercentage', 0)}%")
                known.add(order)
            if new:
                st["last_war_attacks"] = list(known)
                changed = True
        elif state == "warEnded":
            if st.pop("last_war_attacks", None) is not None:
                changed = True
            if st.get("last_war_opponent", ""):
                c = war.get("clan", {})
                cs, cd, os_, od = c.get("stars", 0), c.get("destructionPercentage", 0), o.get("stars", 0), o.get("destructionPercentage", 0)
                if cs != os_:
                    result = "🏆 **VICTORY!**" if cs > os_ else "💀 **DEFEAT**"
                elif cd != od:
                    result = "🏆 **VICTORY (Destruction Tiebreak)!**" if cd > od else "💀 **DEFEAT (Destruction Tiebreak)**"
                else:
                    result = "🤝 **DRAW**"
                end = _parse_coc_time(war.get("endTime", ""))
                when = f"<t:{int(end.timestamp())}:t>" if end else "Unknown"
                if wn:
                    await notify(f"🛑 **War Ended!** ({when})\n**{clan.name}** vs **{o.get('name', 'Unknown')}**\n\n{result}\n"
                                 f"🛡️ **{clan.name}**: {cs} ⭐ ({cd:.1f}%)\n🏴 **{o.get('name', 'Unknown')}**: {os_} ⭐ ({od:.1f}%)")
                st["last_war_opponent"] = ""
                changed = True
        elif state == "notInWar":
            if st.pop("last_war_attacks", None) is not None:
                changed = True
            if st.get("last_war_opponent", ""):
                st["last_war_opponent"] = ""
                changed = True
        return changed


async def setup(bot):
    await bot.add_cog(Tracking(bot))
