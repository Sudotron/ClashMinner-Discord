"""/cap_stats — Capital Gold contribution leaderboard (paginated)."""
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from coc_api import get_clan, get_player, get_player_stats
from core.builders import _build_cap_page
from core.helpers import current_season, normalize_tag, resolve_tag
from core.nav import Page, TTLCache, send_page


async def _fetch_member_capital_stats(tag: str, season: str) -> dict:
    """Capital stats for one member: this season via ClashK stats, else all-time from achievements."""
    stats = await get_player_stats(tag)
    if isinstance(stats, dict) and "error" not in stats:
        season_data = (stats.get("capital") or {}).get(season, {})
        return {"donated": season_data.get("donated", 0), "raided": season_data.get("raided", 0)}
    player = await get_player(tag)
    if isinstance(player, dict) and "error" not in player:
        ach = {a["name"]: a["value"] for a in player.get("achievements", [])}
        return {"donated": ach.get("Most Valuable Clanmate", 0),
                "raided": ach.get("Aggressive Capitalism", 0), "all_time": True}
    return {"donated": 0, "raided": 0, "error": True}


class CapitalCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache = TTLCache(900)

    async def route(self, cb: str) -> Page:
        _, page, norm_tag = cb.split(":", 2)
        cached = self.cache.get(f"cap:{norm_tag}")
        if not cached:
            return Page("❌ Session expired. Please run `/cap_stats` again.")
        text, markup = _build_cap_page(cached["stats"], cached["clan_name"], cached["data_label"],
                                       cached["total"], int(page), cached["clan_tag"])
        return Page(text, markup)

    @app_commands.command(name="cap_stats", description="Clan Capital Gold contribution leaderboard")
    @app_commands.describe(tag="Clan tag (optional if you linked an account)")
    async def cap_stats(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)  # this one makes many API calls
        t = await resolve_tag(interaction.user.id, tag, "clan")
        if not t:
            await interaction.followup.send("Please provide a clan tag, or link an account first with `/link`.")
            return
        t = normalize_tag(t)
        clan_data = await get_clan(t)
        if "error" in clan_data:
            pdata = await get_player(t)
            if "error" not in pdata and pdata.get("clan"):
                clan_data = await get_clan(pdata["clan"]["tag"])
            if "error" in clan_data:
                await send_page(interaction, Page(f"❌ Could not find clan: {clan_data.get('error', 'Unknown error')}"))
                return
        members = clan_data.get("memberList", [])
        if not members:
            await send_page(interaction, Page("❌ No members found in the clan."))
            return

        clan_name, clan_tag, season = clan_data.get("name", "Unknown"), clan_data.get("tag", t), current_season()
        tags = [m.get("tag", "") for m in members]
        results = {}
        for i in range(0, len(tags), 10):  # batches of 10 to stay polite to the API
            batch = tags[i:i + 10]
            for tg, r in zip(batch, await asyncio.gather(*[_fetch_member_capital_stats(x, season) for x in batch])):
                results[tg] = r
        stats = [{"name": m.get("name", "Unknown"), "tag": m.get("tag", ""),
                  "donated": results.get(m.get("tag", ""), {}).get("donated", 0),
                  "raided": results.get(m.get("tag", ""), {}).get("raided", 0),
                  "all_time": results.get(m.get("tag", ""), {}).get("all_time", False)} for m in members]
        stats.sort(key=lambda x: x["donated"], reverse=True)
        label = "All-Time" if any(m["all_time"] for m in stats) else f"Season {season}"
        norm = clan_tag.replace("#", "")
        self.cache.set(f"cap:{norm}", {"stats": stats, "clan_name": clan_name, "data_label": label,
                                       "total": len(members), "clan_tag": clan_tag})
        text, markup = _build_cap_page(stats, clan_name, label, len(members), 0, clan_tag)
        await send_page(interaction, Page(text, markup), self.route)


async def setup(bot):
    await bot.add_cog(CapitalCog(bot))
