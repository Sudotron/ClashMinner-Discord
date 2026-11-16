"""Permission helpers. Owner = OWNER_ID; admin = owner or 'Manage Server' in the guild."""
import discord

import config


def is_owner(user_id: int) -> bool:
    return config.OWNER_ID != 0 and user_id == config.OWNER_ID


def is_admin(interaction: discord.Interaction) -> bool:
    if is_owner(interaction.user.id):
        return True
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.manage_guild)


def channel_problem(channel, guild: discord.Guild):
    """Return a human-readable problem if the bot can't post embeds in `channel`, else None."""
    perms = channel.permissions_for(guild.me)
    missing = [n for n, ok in (("View Channel", perms.view_channel),
                               ("Send Messages", perms.send_messages),
                               ("Embed Links", perms.embed_links)) if not ok]
    return f"I'm missing permissions in {channel.mention}: {', '.join(missing)}." if missing else None
