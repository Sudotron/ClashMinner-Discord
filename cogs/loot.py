"""/loot — loot forecaster (static weekly model) + periodic channel updates."""
import json
import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import FORECASTER_FILE
from core.nav import Btn, Markup, NavError, Page, send_page
from core.perms import is_admin
from database import all_guild_configs, get_guild_config, save_guild_config

log = logging.getLogger(__name__)

BASE_EPOCH = 1680162300  # epoch for index 0 of the weekly data array
DISCLAIMER = ("⚠️ *Disclaimer: This data is not affiliated with Clash of Clans servers. It is calculated "
              "by a predictive algorithm and is not 100% reliable.*")
_data_cache = {}


def _forecaster_data() -> dict:
    if "d" not in _data_cache:
        try:
            with open(FORECASTER_FILE, "r", encoding="utf-8") as f:
                _data_cache["d"] = json.load(f)
        except Exception:
            _data_cache["d"] = {}
    return _data_cache["d"]


def get_current_loot_info():
    data = _forecaster_data()
    if not data or "totals" not in data:
        return None
    loot = data["totals"]["lootMinutes"]
    max_loot = float(data.get("maxLootMinute", 45494096))
    index = int((time.time() - BASE_EPOCH) // 60) % len(loot)
    idx = lambda i: round((loot[i % len(loot)] / max_loot) * 10, 1)
    cur, n1, n2 = idx(index), idx(index + 60), idx(index + 120)

    def status(v):
        if v >= 9.0: return "Excellent 🟢"
        if v >= 8.0: return "Great 🟢"
        if v >= 6.0: return "Good 🟡"
        if v >= 4.0: return "Okay 🟡"
        if v >= 2.0: return "Poor 🔴"
        return "Terrible 🔴"

    def trend(v):
        return "📈 Increasing" if v > cur else "📉 Decreasing" if v < cur else "➡️ Stable"

    return {"index": cur, "status": status(cur), "players_online": data["totals"]["playersOnline"][index],
            "shielded_players": data["totals"]["shieldedPlayers"][index],
            "next_hour_index": n1, "trend": trend(n1), "next_2hour_index": n2, "trend_2h": trend(n2)}


def most_active_region() -> str:
    h = datetime.now(timezone.utc).hour
    if 1 <= h < 7: return "North America 🇺🇸🇨🇦"
    if 7 <= h < 11: return "Asia / Oceania 🇦🇺🇯🇵"
    if 11 <= h < 16: return "Asia (China/India) 🇨🇳🇮🇳"
    if 16 <= h < 20: return "Europe & Africa 🇪🇺🌍"
    return "Americas & Europe 🌎🌍"


class Loot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.notify_loop.start()

    def cog_unload(self):
        self.notify_loop.cancel()

    async def _main_page(self, interaction: discord.Interaction, guild_id) -> Page:
        info = get_current_loot_info()
        if not info:
            return Page("Loot data not available.")
        text = (f"📊 **Loot Forecaster**\n\n"
                f"Current Loot Index: **{info['index']}/10.0** ({info['status']})\n"
                f"Forecast (1h): **{info['next_hour_index']}/10.0** ({info['trend']})\n"
                f"Forecast (2h): **{info['next_2hour_index']}/10.0** ({info['trend_2h']})\n\n")
        rows = [[Btn("🌍 Worldwide Stats", cb="loot_worldwide"), Btn("🗺️ Most Active Region", cb="loot_region")]]
        if guild_id:
            cfg = await get_guild_config(guild_id)
            text += f"Server notifications: {'✅ ON' if cfg['loot_enabled'] else '❌ OFF'}\n\n"
            rows.append([Btn("Toggle Notifications", cb="loot_toggle")])
        return Page(text + DISCLAIMER, Markup(rows))

    @app_commands.command(name="loot", description="Live loot forecaster: best times to farm")
    async def loot(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        guild_id = interaction.guild_id

        async def route(cb: str) -> Page:
            if cb == "loot_toggle":
                if not guild_id:
                    raise NavError("Notifications can only be toggled in a server.")
                if not is_admin(interaction):
                    raise NavError("❌ Only server admins (Manage Server) can change notification settings.")
                cfg = await get_guild_config(guild_id)
                cfg["loot_enabled"] = not cfg["loot_enabled"]
                await save_guild_config(cfg)
                return await self._main_page(interaction, guild_id)
            if cb == "loot_worldwide":
                info = get_current_loot_info() or {"players_online": 0, "shielded_players": 0}
                text = (f"🌍 **Worldwide Clash Stats**\n\n👤 Players Online: **{info['players_online']:,}**\n"
                        f"🛡️ Shielded Players: **{info['shielded_players']:,}**\n\n*Data based on cyclical forecaster model*")
                return Page(text, Markup([[Btn("⬅️ Back", cb="loot_back")]]))
            if cb == "loot_region":
                text = (f"🗺️ **Most Active Region**\n\nBased on current global timezones, the most active player "
                        f"base right now is likely in:\n\n🌟 **{most_active_region()}**")
                return Page(text, Markup([[Btn("⬅️ Back", cb="loot_back")]]))
            return await self._main_page(interaction, guild_id)

        await send_page(interaction, await self._main_page(interaction, guild_id), route)

    @tasks.loop(hours=4)
    async def notify_loop(self):
        info = get_current_loot_info()
        if not info:
            return
        text = (f"📊 **Loot Forecaster Update**\n\nCurrent Loot Index: **{info['index']}/10.0** ({info['status']})\n"
                f"Forecast (1h): **{info['next_hour_index']}/10.0** ({info['trend']})\n"
                f"Forecast (2h): **{info['next_2hour_index']}/10.0** ({info['trend_2h']})\n\n"
                f"*The best time to raid is when the index is above 8.0!*\n\n{DISCLAIMER}")
        for cfg in await all_guild_configs():
            if cfg["loot_enabled"] and cfg["channel_id"]:
                await self.bot.notify(cfg["channel_id"], text)

    @notify_loop.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Loot(bot))
