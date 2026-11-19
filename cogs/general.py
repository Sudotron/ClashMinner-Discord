"""General commands: /help, /link, /accounts, /adminlink, /profile."""

import asyncio
import logging

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from coc_api import get_clan, get_player, get_players_batch, verify_player_token
from core.helpers import normalize_tag
from core import state
from core.autocomplete import MAX_CHOICES
from core.nav import Btn, Markup, Page, command_color, send_page
from core.perms import is_owner
from database import (LinkError, get_all_linked_tags, get_linked_accounts, link_account,
                      set_label, set_primary, unlink_account)

log = logging.getLogger(__name__)


class AccountsView(discord.ui.View):
    """Dropdowns to switch the primary account or unlink one. Only the account owner can use it."""

    def __init__(self, cog: "General", owner_id: int, accounts: list, names: dict):
        super().__init__(timeout=600)
        self.cog, self.owner_id = cog, owner_id
        self.message = None
        if not accounts:
            return
        def option(a, desc):
            name = names.get(a["tag"]) or a.get("label") or a["tag"]
            return discord.SelectOption(label=f"{name} ({a['tag']})"[:100], value=a["tag"],
                                        description=desc[:100])
        make = [option(a, f"Make this your primary {a['entity_type']}") for a in accounts if not a["is_primary"]]
        if make:
            sel = discord.ui.Select(placeholder="★ Make primary…", options=make[:MAX_CHOICES], row=0)
            sel.callback = self._on_primary(sel)
            self.add_item(sel)
        rm = [option(a, f"Unlink this {a['entity_type']}") for a in accounts]
        sel = discord.ui.Select(placeholder="🗑️ Unlink…", options=rm[:MAX_CHOICES], row=1)
        sel.callback = self._on_unlink(sel)
        self.add_item(sel)

    def _on_primary(self, select):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            await set_primary(self.owner_id, select.values[0])
            await self.cog._refresh(interaction, self.owner_id)
        return cb

    def _on_unlink(self, select):
        async def cb(interaction: discord.Interaction):
            await interaction.response.defer()
            await unlink_account(self.owner_id, select.values[0])
            await self.cog._refresh(interaction, self.owner_id)
        return cb

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can change these accounts.", ephemeral=True)
            return False
        if state.maintenance:
            await interaction.response.send_message(
                "🛑 Bot is frozen — Clash servers are under maintenance!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /help ────────────────────────────────────────────────────────────────
    @app_commands.command(name="help", description="What Clash OTTO can do")
    async def help(self, interaction: discord.Interaction):
        text = (
            "**A high-performance bot for Clash of Clans tracking and analytics.**\n\n"
            "📊 **Commands**\n"
            "• `/link` — Link a player or clan tag (add `api_token` to verify ownership)\n"
            "• `/accounts` — Your linked accounts: switch primary, unlink alts\n"
            "• `/profile` — Your Discord profile and linked accounts\n"
            "• `/player` — Full player stats\n"
            "• `/todo` — Upgrade progress (TH-specific)\n"
            "• `/audit` — Player rush audit\n"
            "• `/progress` — Picture card: % of Town Hall max per category\n"
            "• `/poster` — Shareable profile card\n"
            "• `/clan` — Clan profile and roster\n"
            "• `/clansorted` — Roster sorting\n"
            "• `/clanwar` — War info and analytics\n"
            "• `/cwl` — CWL group and war details\n"
            "• `/cap_stats` — Capital Gold rankings\n"
            "• `/waropt` — Who is opted in / out of war\n"
            "• `/missing-hits` — Who still has war or raid attacks left\n"
            "• `/activity` — Last activity per clan member\n"
            "• `/leaderboard` — Season donations, war stars, loot, capital gold\n"
            "• `/army` — Decode an army link (or use the **Read Clash link** message menu)\n"
            "• `/bases`, `/basesave`, `/basedelete` — This server's base layout library\n"
            "• `/loot` — Loot forecaster statistics\n\n"
            "👑 **Admin** (Manage Server)\n"
            "• `/clantrack` — Start join/leave/war logs in a channel\n"
            "• `/deltrack` — Stop tracking\n"
            "• `/trackinfo` — Tracked clan details and notification toggles\n"
            "• `/setchannel` — Channel for loot and maintenance notices\n"
            "• `/reminders` — Automatic war / raid weekend / clan games reminders\n"
            "• `/autodecode` — Read army and base links pasted in chat\n\n"
            "🛠️ **Owner**\n"
            "• `/adminlink` — Link a tag to another user\n"
            "• `/scrap` — Scrape latest Town Hall max levels\n\n"
            "🔔 **Automated:** war feed, join/leave/promotion logs, loot updates, maintenance alerts, reminders, activity tracking"
        )
        if config.OWNER_CONTACT:
            text += f"\n\n👑 **Owner:** {config.OWNER_CONTACT}"
        embed = discord.Embed(title="Welcome to Clash OTTO ⚔️", description=text, color=command_color(interaction))
        await interaction.response.send_message(embed=embed)

    # ── /link ────────────────────────────────────────────────────────────────
    async def _link(self, user_id: int, tag: str, who: str = "your account", *, token: str | None = None,
                    make_primary: bool = False, force: bool = False) -> str:
        """Validate `tag` as a player or a clan, store it, return the reply text."""
        pdata = await get_player(tag, self.bot.coc)
        if "error" not in pdata:
            verified = False
            if token:
                check = await verify_player_token(tag, token, self.bot.coc)
                if "error" in check:
                    return f"❌ Could not verify this account: {check['error']}"
                if not check["verified"]:
                    return ("❌ That API token doesn't match this player, so nothing was linked. "
                            "Copy a fresh token from the game (Settings → More Settings → API Token); "
                            "it is single-use.")
                verified = True
            name = pdata.get("name", "Unknown")
            try:
                res = await link_account(user_id, tag, "player", make_primary=make_primary,
                                         verified=verified, label=name, force=force)
            except LinkError as e:
                return f"❌ {e}"
            notes = []
            if res["is_verified"]:
                notes.append("✔ verified")
            if res["is_primary"]:
                notes.append("★ primary")
            suffix = f" ({', '.join(notes)})" if notes else " — use `/accounts` to make it your primary"
            return (f"✅ Player **{name}** (TH{pdata.get('townHallLevel', '?')} | "
                    f"Lvl {pdata.get('expLevel', '?')}) linked to {who}!{suffix}")
        if not pdata["error"].startswith("Player not found"):
            return f"❌ Could not check this tag: {pdata['error']}"
        if token:
            return "❌ API tokens only work with player tags, and no player was found with this tag."
        cdata = await get_clan(tag, self.bot.coc)
        if "error" not in cdata:
            leader = next((m.get("name") for m in cdata.get("memberList", []) if m.get("role") == "leader"), "Unknown")
            try:
                res = await link_account(user_id, tag, "clan", make_primary=make_primary,
                                         label=cdata.get("name"), force=force)
            except LinkError as e:
                return f"❌ {e}"
            suffix = " (★ primary)" if res["is_primary"] else " — use `/accounts` to make it your primary"
            return (f"✅ Clan **{cdata.get('name', 'Unknown')}** "
                    f"(Lvl {cdata.get('clanLevel', '?')} | Leader: {leader}) linked to {who}!{suffix}")
        if not cdata["error"].startswith("Clan not found"):
            return f"❌ Could not check this tag: {cdata['error']}"
        return f"❌ Invalid tag! Could not find any player or clan with `{tag}`."

    @app_commands.command(name="link", description="Link a Clash of Clans player or clan tag")
    @app_commands.describe(tag="Player or clan tag, e.g. #YY8PQY28",
                           api_token="Player tags only: in-game API token to verify you own the account",
                           primary="Make this your primary account (used when you leave the tag blank)")
    async def link(self, interaction: discord.Interaction, tag: str,
                   api_token: Optional[str] = None, primary: bool = False):
        # A token must never be visible to the channel: the whole reply is ephemeral when one is given.
        await interaction.response.defer(thinking=True, ephemeral=bool(api_token))
        text = await self._link(interaction.user.id, normalize_tag(tag), token=api_token, make_primary=primary)
        await send_page(interaction, Page(text))

    # ── /accounts ────────────────────────────────────────────────────────────
    async def _accounts_view(self, user: discord.abc.User, *, manage: bool):
        accounts = await get_linked_accounts(user.id)
        players = [a for a in accounts if a["entity_type"] == "player"]
        clans = [a for a in accounts if a["entity_type"] == "clan"]
        pdata, *cdata = await asyncio.gather(
            get_players_batch([a["tag"] for a in players], self.bot.coc),
            *(get_clan(a["tag"], self.bot.coc) for a in clans))
        names = {}
        lines = [f"👥 **Linked accounts — {user.display_name}**", "★ primary · ✔ verified", ""]
        if players:
            lines.append("**Players**")
            for a in players:
                d = pdata.get(a["tag"], {})
                marks = ("★ " if a["is_primary"] else "") + ("✔ " if a["is_verified"] else "")
                if "error" in d:
                    lines.append(f"{marks}`{a['tag']}` — ❌ unable to fetch data")
                else:
                    names[a["tag"]] = d.get("name", "Unknown")
                    lines.append(f"{marks}**{names[a['tag']]}** (TH{d.get('townHallLevel', '?')}) `{a['tag']}`")
            lines.append("")
        if clans:
            lines.append("**Clans**")
            for a, d in zip(clans, cdata):
                marks = ("★ " if a["is_primary"] else "") + ("✔ " if a["is_verified"] else "")
                if "error" in d:
                    lines.append(f"{marks}`{a['tag']}` — ❌ unable to fetch data")
                else:
                    names[a["tag"]] = d.get("name", "Unknown")
                    lines.append(f"{marks}**{names[a['tag']]}** (Lvl {d.get('clanLevel', '?')}) `{a['tag']}`")
        if not accounts:
            lines.append("No linked accounts yet. Use `/link`." if manage else "This user has no linked accounts.")
        for tag, name in names.items():           # keep autocomplete names fresh
            try:
                await set_label(user.id, tag, name)
            except Exception:
                log.exception("Could not cache label for %s", tag)
        view = AccountsView(self, user.id, accounts, names) if manage and accounts else None
        return Page("\n".join(lines), thumb_url=user.display_avatar.url), view

    async def _refresh(self, interaction: discord.Interaction, user_id: int):
        page, view = await self._accounts_view(interaction.user, manage=True)
        kwargs = {"embed": page.to_embed(), "view": view}
        if view is None:
            kwargs["view"] = discord.utils.MISSING
        msg = await interaction.edit_original_response(**kwargs)
        if view:
            view.message = msg

    @app_commands.command(name="accounts", description="Your linked accounts: switch primary or unlink alts")
    @app_commands.describe(user="Look at someone else's linked accounts (read-only)")
    async def accounts(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        await interaction.response.defer(thinking=True)
        target = user or interaction.user
        page, view = await self._accounts_view(target, manage=target.id == interaction.user.id)
        kwargs = {"embed": page.to_embed(), "wait": True}
        if view:
            kwargs["view"] = view
        msg = await interaction.followup.send(**kwargs)
        if view:
            view.message = msg

    @app_commands.command(name="adminlink", description="Owner only: link a tag to another user")
    @app_commands.describe(user="Who to link the tag to", tag="Player or clan tag")
    async def adminlink(self, interaction: discord.Interaction, user: discord.User, tag: str):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ This command is available for the owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        text = await self._link(user.id, normalize_tag(tag), who=f"{user.mention} by owner", force=True)
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
