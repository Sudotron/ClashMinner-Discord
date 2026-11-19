"""Shared 'which clan did the user mean' rule for commands with an optional clan option."""
from core.helpers import normalize_tag
from core.nav import NavError
from database import get_guild_config, get_linked_account


async def resolve_clan(bot, interaction, clan) -> str:
    """Typed tag, else the user's linked clan, else the server's tracked clan."""
    if clan and clan.strip():
        return normalize_tag(clan)
    tag = await get_linked_account(interaction.user.id, "clan")
    if not tag and interaction.guild_id:
        tag = (await get_guild_config(interaction.guild_id)).get("tracked_tag")
    if not tag:
        raise NavError("Please give a clan tag, link a clan with `/link`, or set up `/clantrack` first.")
    return normalize_tag(tag)
