"""Detects Clash of Clans API maintenance, freezes commands, and posts notices."""
import logging

import coc
import discord
import httpx
from discord.ext import commands, tasks

from core import state
from database import all_guild_configs

log = logging.getLogger(__name__)
PROBE_URL = "https://api.clashk.ing/v1/locations?limit=1"

MAINTENANCE_MSG = (
    "🛑 **Clash of Clans is Under Maintenance!**\n\n"
    "🔧 Supercell's servers are currently down for maintenance.\n"
    "⚔️ All bot commands are **frozen** until the game is back online.\n\n"
    "⏳ *Sit tight, Chief! Your village will be waiting...*\n\n"
    "🔔 I'll notify you the moment the servers are back up!")
BACK_ONLINE_MSG = (
    "✅ **Clash of Clans is Back Online!**\n\n"
    "⚔️ The servers are back up and running!\n"
    "🚀 All bot commands are now **active** again.\n\n"
    "👑 Go crush your enemies, Chief! 💪")


async def _proxy_is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(PROBE_URL, headers={"Accept": "application/json"})
            return r.status_code != 503
    except Exception:
        return True  # network trouble is not the same as game maintenance


class Maintenance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check.start()

    def cog_unload(self):
        self.check.cancel()

    @tasks.loop(minutes=2)
    async def check(self):
        was = state.maintenance
        now = False
        if self.bot.coc:
            try:
                await self.bot.coc.get_location(32000000)  # Europe: cheap official-API probe
            except coc.Maintenance:
                now = True
            except Exception as e:
                log.debug("coc probe failed (%s); falling back to proxy", e)
                now = not await _proxy_is_up()
        else:
            now = not await _proxy_is_up()
        state.maintenance = now

        if now != was:
            log.warning("CoC API maintenance %s", "STARTED — commands frozen" if now else "ENDED — commands resumed")
            for cfg in await all_guild_configs():
                if cfg["channel_id"]:
                    await self.bot.notify(cfg["channel_id"], MAINTENANCE_MSG if now else BACK_ONLINE_MSG,
                                          color=0xD9534F if now else 0x5CB85C)

    @check.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Maintenance(bot))
