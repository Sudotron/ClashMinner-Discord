"""Clash OTTO — Discord bot entry point."""
import asyncio
import logging
import logging.handlers
import os
import sys

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import state
from core.helpers import ApiError
from core.nav import NavError
from database import ConfigError, LinkError, init_db

USER_ERRORS = (NavError, ApiError, ConfigError, LinkError)   # raised on purpose with a user-safe message
COGS = ["general", "player", "clan", "capital", "loot", "tracking", "maintenance", "scraper",
        "cards", "reminders", "activity", "army"]
log = logging.getLogger("otto")


def _intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = config.ENABLE_MESSAGE_CONTENT   # only for the optional army/base link reader
    return intents


class OttoTree(app_commands.CommandTree):
    """Global guard: freeze all commands (except /help) while the game API is in maintenance."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if state.maintenance and not (interaction.command and interaction.command.name == "help"):
            await interaction.response.send_message(
                "🛑 **Bot is Frozen — Game Under Maintenance**\n\n"
                "⚔️ Clash of Clans servers are currently down.\n"
                "❄️ All commands are suspended until maintenance ends.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", error)
        if isinstance(original, USER_ERRORS):          # expected problems: show the message, no traceback
            msg = f"❌ {original}"
        else:
            log.exception("Command error in /%s", getattr(interaction.command, "name", "?"), exc_info=error)
            msg = "❌ Something went wrong. Please try again in a moment."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException:
            pass


class OttoBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned,
                         intents=_intents(),   # slash commands need no privileged intents
                         tree_cls=OttoTree,
                         activity=discord.Game("Clash of Clans"))
        self.coc = None  # coc.py client (official API); None if login failed / not configured

    async def setup_hook(self):
        await init_db()
        await self._login_coc()
        for name in COGS:
            await self.load_extension(f"cogs.{name}")
        if config.DEV_GUILD_ID:  # instant sync for development
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:                      # global sync can take up to an hour to appear
            synced = await self.tree.sync()
        log.info("Synced %d slash commands", len(synced))

    async def _login_coc(self):
        if not (config.COC_EMAIL and config.COC_PASSWORD):
            log.warning("COC_EMAIL / COC_PASSWORD not set — tracking, /cwl and TH-max lookups disabled.")
            return
        import coc
        client = coc.Client(load_game_data=coc.LoadGameData(always=True), raw_attribute=True)
        try:
            await client.login(config.COC_EMAIL, config.COC_PASSWORD)
            self.coc = client
            log.info("Logged into the Clash of Clans API.")
        except Exception as e:
            log.error("CoC login failed: %s", e)

    async def notify(self, channel_id: int, text: str, color: int = 0xE8A317):
        """Post an embed to a channel; never raises (a missing channel must not break a loop)."""
        try:
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            await channel.send(embed=discord.Embed(description=text[:4096], color=color))
        except (discord.Forbidden, discord.NotFound):
            log.warning("Cannot post in channel %s (missing access or deleted)", channel_id)
        except discord.HTTPException as e:
            log.warning("Failed to post in channel %s: %s", channel_id, e)

    async def close(self):
        if self.coc:
            await self.coc.close()
        await super().close()

    async def on_ready(self):
        log.info("Ready as %s (%d servers)", self.user, len(self.guilds))


def setup_logging():
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    os.makedirs(os.path.join(config.BASE_DIR, "logs"), exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(os.path.join(config.BASE_DIR, "logs", "otto.log"),
                                              maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


def main():
    setup_logging()
    if not config.DISCORD_TOKEN or config.DISCORD_TOKEN == "your_discord_bot_token_here":
        log.error("No valid DISCORD_TOKEN found in .env!")
        sys.exit(1)
    OttoBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
