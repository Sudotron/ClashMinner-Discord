"""Image cards: /progress (upgrade progress to Town Hall max) and /poster (shareable profile card)."""
import io
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.player import th_image
from coc_api import get_player
from core.autocomplete import linked_tag_choices
from core.helpers import ApiError, get_th_max, normalize_tag, resolve_tag, run_blocking
from core.image_cards import render_poster_card, render_progress_card
from core.progress import compute_progress


class CardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _player(self, interaction: discord.Interaction, tag: Optional[str]) -> dict:
        t = await resolve_tag(interaction.user.id, tag, "player")
        if not t:
            raise ApiError("Please provide a tag, or link an account first with `/link`.")
        data = await get_player(normalize_tag(t), self.bot.coc)
        if "error" in data:
            raise ApiError(data["error"])
        return data

    @app_commands.command(name="progress", description="Picture card: upgrade progress for heroes, troops, spells and more")
    @app_commands.describe(tag="Player tag (optional if you linked an account)")
    async def progress(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        data = await self._player(interaction, tag)
        th_max = await get_th_max(self.bot.coc, data.get("tag", tag or ""), data.get("townHallLevel", 1))
        result = compute_progress(data, th_max)
        png = await run_blocking(render_progress_card, result, th_image(result["th"]))
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="progress.png"))

    @progress.autocomplete("tag")
    async def _progress_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "player")

    @app_commands.command(name="poster", description="Shareable profile card: Town Hall, trophies, war stars, heroes")
    @app_commands.describe(tag="Player tag (optional if you linked an account)")
    async def poster(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        data = await self._player(interaction, tag)
        png = await run_blocking(render_poster_card, data, th_image(data.get("townHallLevel")))
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="poster.png"))

    @poster.autocomplete("tag")
    async def _poster_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "player")


async def setup(bot):
    await bot.add_cog(CardsCog(bot))
