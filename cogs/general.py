"""General commands: /help, /link, /adminlink, /profile."""

import discord
from discord import app_commands
from discord.ext import commands

import config
from coc_api import get_player, get_clan
from core.helpers import normalize_tag
from core.nav import Btn, Markup, NavError, Page, send_page
from core.perms import is_owner
from database import link_account, get_all_linked_tags


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /help ────────────────────────────────────────────────────────────────
    @app_commands.command(name="help", description="What Clash OTTO can do")
    async def help(self, interaction: discord.Interaction):
        text = (
            "**A high-performance bot for Clash of Clans tracking and analytics.**\n\n"
            "📊 **Commands**\n"
            "• `/link` — Link your CoC account (player or clan tag)\n"
            "• `/profile` — Your Discord profile and linked accounts\n"
            "• `/player` — Full player stats\n"
            "• `/todo` — Upgrade progress (TH-specific)\n"
            "• `/audit` — Player rush audit\n"
            "• `/clan` — Clan profile and roster\n"
            "• `/clansorted` — Roster sorting\n"
            "• `/clanwar` — War info and analytics\n"
            "• `/cwl` — CWL group and war details\n"
            "• `/cap_stats` — Capital Gold rankings\n"
            "• `/loot` — Loot forecaster statistics\n\n"
            "👑 **Admin** (Manage Server)\n"
            "• `/clantrack` — Start join/leave/war logs in a channel\n"
            "• `/deltrack` — Stop tracking\n"
            "• `/trackinfo` — Tracked clan details and notification toggles\n"
            "• `/setchannel` — Channel for loot and maintenance notices\n\n"
            "🛠️ **Owner**\n"
            "• `/adminlink` — Link a tag to another user\n"
            "• `/scrap` — Scrape latest Town Hall max levels\n\n"
            "🔔 **Automated:** war feed, join/leave/promotion logs, loot updates, maintenance alerts"
        )
        if config.OWNER_CONTACT:
            text += f"\n\n👑 **Owner:** {config.OWNER_CONTACT}"
        embed = discord.Embed(title="Welcome to Clash OTTO ⚔️", description=text, color=0xE8A317)
        await interaction.response.send_message(embed=embed)

    # ── /link ────────────────────────────────────────────────────────────────
    async def _link(self, user_id: int, tag: str, who: str = "your account") -> str:
        """Validate `tag` as a player or a clan, store it, return the reply text."""
        pdata = await get_player(tag, self.bot.coc)
        if "error" not in pdata:
            await link_account(user_id, tag, "player")
            return (f"✅ Player **{pdata.get('name', 'Unknown')}** "
                    f"(TH{pdata.get('townHallLevel', '?')} | Lvl {pdata.get('expLevel', '?')}) linked to {who}!")
        if not pdata["error"].startswith("Player not found"):
            return f"❌ Could not check this tag: {pdata['error']}"
        cdata = await get_clan(tag, self.bot.coc)
        if "error" not in cdata:
            leader = next((m.get("name") for m in cdata.get("memberList", []) if m.get("role") == "leader"), "Unknown")
            await link_account(user_id, tag, "clan")
            return (f"✅ Clan **{cdata.get('name', 'Unknown')}** "
                    f"(Lvl {cdata.get('clanLevel', '?')} | Leader: {leader}) linked to {who}!")
        if not cdata["error"].startswith("Clan not found"):
            return f"❌ Could not check this tag: {cdata['error']}"
        return f"❌ Invalid tag! Could not find any player or clan with `{tag}`."

    @app_commands.command(name="link", description="Link your Clash of Clans player or clan tag")
    @app_commands.describe(tag="Player or clan tag, e.g. #YY8PQY28")
    async def link(self, interaction: discord.Interaction, tag: str):
        await interaction.response.defer(thinking=True)
        text = await self._link(interaction.user.id, normalize_tag(tag))
        await send_page(interaction, Page(text))

    @app_commands.command(name="adminlink", description="Owner only: link a tag to another user")
    @app_commands.describe(user="Who to link the tag to", tag="Player or clan tag")
    async def adminlink(self, interaction: discord.Interaction, user: discord.User, tag: str):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ This command is available for the owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        text = await self._link(user.id, normalize_tag(tag), who=f"{user.mention} by owner")
        await send_page(interaction, Page(text))

    # ── /profile ─────────────────────────────────────────────────────────────
    @app_commands.command(name="profile", description="Your Discord identity and linked Clash accounts")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        user = interaction.user
        markup = Markup([[Btn("👤 Profile", cb="myid:home"), Btn("🔗 Linked Accounts", cb="myid:accounts")],
                         [Btn("🛡️ Linked Clan", cb="myid:clan")]])

        async def route(cb: str) -> Page:
            action = cb.split(":")[1]
            if action == "accounts":
                tags = await get_all_linked_tags(user.id, "player")
                if not tags:
                    return Page("❌ You don't have any linked player accounts. Use `/link`.", markup, thumb_url=user.display_avatar.url)
                text = "👥 **Your Linked Accounts:**\n\n"
                for tag in tags:
                    d = await get_player(tag, self.bot.coc)
                    if "error" in d:
                        text += f"• `{tag}` — ❌ Unable to fetch data\n"
                    else:
                        text += f"• **{d.get('name', 'Unknown')}** (TH{d.get('townHallLevel', '?')}) 🏆 {d.get('trophies', 0)}\n   `{tag}`\n"
                return Page(text, markup, thumb_url=user.display_avatar.url)
            if action == "clan":
                tags = await get_all_linked_tags(user.id, "clan")
                if not tags:
                    return Page("❌ You don't have any linked clans. Use `/link`.", markup, thumb_url=user.display_avatar.url)
                text = "🛡️ **Your Linked Clans:**\n\n"
                for tag in tags:
                    d = await get_clan(tag, self.bot.coc)
                    if "error" in d:
                        text += f"• `{tag}` — ❌ Unable to fetch data\n"
                    else:
                        text += f"• **{d.get('name', 'Unknown')}** (Lvl {d.get('clanLevel', '?')})\n   `{tag}`\n"
                return Page(text, markup, thumb_url=user.display_avatar.url)
            return Page(f"👤 **User Identity**\nName: {user.display_name}\nID: `{user.id}`\n",
                        markup, thumb_url=user.display_avatar.url)

        await send_page(interaction, await route("myid:home"), route)


async def setup(bot):
    await bot.add_cog(General(bot))
