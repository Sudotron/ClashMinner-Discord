"""Army link decoder and base layout library.

  /army <link>          decode a CopyArmy link (troops, spells, siege, heroes, clan castle, housing space)
  Read Clash link       message context menu: the same for army links, and "save" for base layout links
  /autodecode           admin: read links pasted in chat automatically (needs ENABLE_MESSAGE_CONTENT=1)
  /bases /basesave /basedelete   the server's base layout library with one-vote upvotes
"""
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.army import (CATEGORIES, army_fields, decode_army, decoder_client, extract_links,
                       layout_link, link_kind, normalise_category, parse_th)
from core.nav import EMBED_COLOR, Page, command_color, send_page
from core.perms import is_admin
from database import (ConfigError, add_base, delete_base, get_auto_decode, get_base, list_bases,
                      set_auto_decode, toggle_base_vote)

log = logging.getLogger(__name__)
PER_PAGE = 8
COLOUR = EMBED_COLOR
_NO_MENTIONS = discord.AllowedMentions.none()


def army_embed(info: dict, color: int = COLOUR) -> discord.Embed:
    embed = discord.Embed(title=f"⚔️ Army · {info['troop_space']} troop space · {info['spell_space']} spell space",
                          colour=color)
    for name, value in army_fields(info):
        embed.add_field(name=name, value=value[:1024], inline=False)
    return embed


def army_view(info: dict) -> Optional[discord.ui.View]:
    if len(info["link"]) > 512:                    # Discord's limit for a link button
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Copy Army", style=discord.ButtonStyle.link, url=info["link"]))
    return view


# ── saving a base ────────────────────────────────────────────────────────────
class SaveBaseModal(discord.ui.Modal, title="Save base layout"):
    category = discord.ui.TextInput(label="Category: War, CWL, Farming, Trophy, Legend", max_length=10, default="War")
    th = discord.ui.TextInput(label="Town Hall level", max_length=4)
    notes = discord.ui.TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph,
                                 required=False, max_length=300)

    def __init__(self, url: str, th: Optional[int]):
        super().__init__()
        self.url = url
        if th:
            self.th.default = str(th)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            base_id = await add_base(interaction.guild_id, interaction.user.id, parse_th(self.th.value),
                                     normalise_category(self.category.value), self.url, (self.notes.value or "").strip() or None)
        except (ValueError, ConfigError) as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Saved as base **#{base_id}**. Browse with `/bases`.", ephemeral=True)


class SaveBaseView(discord.ui.View):
    def __init__(self, url: str, th: Optional[int]):
        super().__init__(timeout=86400)
        self.url, self.th = url, th

    @discord.ui.button(label="Save to base library", emoji="💾", style=discord.ButtonStyle.primary)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild_id:
            await interaction.response.send_message("The base library only works inside a server.", ephemeral=True)
            return
        await interaction.response.send_modal(SaveBaseModal(self.url, self.th))


# ── browsing the library ─────────────────────────────────────────────────────
def render_bases(rows: list, total: int, page: int, th: Optional[int], category: Optional[str],
                 color: int = COLOUR) -> discord.Embed:
    pages = max(1, -(-total // PER_PAGE))
    scope = " · ".join(x for x in (f"TH{th}" if th else None, category) if x) or "all"
    lines = [f"🏰 **Base library — {scope}**", f"Page {page + 1}/{pages} · {total} layout{'s' if total != 1 else ''}", ""]
    if not rows:
        lines.append("No layouts saved yet. Paste a base link in chat and press **Save**, or use `/basesave`.")
    for b in rows:
        note = f" — {b['notes'][:80]}" if b.get("notes") else ""
        lines.append(f"`#{b['base_id']}` **TH{b['th_level']} · {b['category']}** · 👍 {b['upvotes']}{note} · <@{b['submitted_by']}>")
    return discord.Embed(description="\n".join(lines)[:4000], colour=color)


class BasesView(discord.ui.View):
    def __init__(self, owner_id: int, guild_id: int, th, category, page: int, rows: list, total: int,
                 color: int = COLOUR):
        super().__init__(timeout=900)
        self.owner_id, self.guild_id, self.th, self.category, self.page = owner_id, guild_id, th, category, page
        self.color = color
        self.message = None
        pages = max(1, -(-total // PER_PAGE))
        prev = discord.ui.Button(emoji="◀️", style=discord.ButtonStyle.secondary, disabled=page <= 0, row=0)
        nxt = discord.ui.Button(emoji="▶️", style=discord.ButtonStyle.secondary, disabled=page >= pages - 1, row=0)
        prev.callback, nxt.callback = self._turn(-1), self._turn(1)
        self.add_item(prev), self.add_item(nxt)
        if rows:
            def opts():                                   # each select gets its own option objects
                return [discord.SelectOption(label=f"#{b['base_id']} · TH{b['th_level']} {b['category']}",
                                             value=str(b["base_id"]), description=(b.get("notes") or "No notes")[:100])
                        for b in rows]
            open_sel = discord.ui.Select(placeholder="Open a layout…", options=opts(), row=1)
            vote_sel = discord.ui.Select(placeholder="👍 Upvote / remove upvote…", options=opts(), row=2)
            open_sel.callback, vote_sel.callback = self._open(open_sel), self._vote(vote_sel)
            self.add_item(open_sel), self.add_item(vote_sel)

    @staticmethod
    async def build(owner_id, guild_id, th, category, page, color=COLOUR):
        rows, total = await list_bases(guild_id, th, category, PER_PAGE, page * PER_PAGE)
        last = max(0, -(-total // PER_PAGE) - 1)
        if page > last:                                   # e.g. the last row of a page was deleted
            page = last
            rows, total = await list_bases(guild_id, th, category, PER_PAGE, page * PER_PAGE)
        return (render_bases(rows, total, page, th, category, color),
                BasesView(owner_id, guild_id, th, category, page, rows, total, color))

    def _turn(self, step: int):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner_id:
                await interaction.response.send_message("Only the person who ran `/bases` can turn the page. "
                                                        "Run it yourself to browse.", ephemeral=True)
                return
            embed, view = await self.build(self.owner_id, self.guild_id, self.th, self.category,
                                           self.page + step, self.color)
            view.message = interaction.message
            await interaction.response.edit_message(embed=embed, view=view)
        return cb

    def _open(self, select):
        async def cb(interaction: discord.Interaction):
            base = await get_base(self.guild_id, int(select.values[0]))
            if not base:
                await interaction.response.send_message("❌ That layout was removed.", ephemeral=True)
                return
            await interaction.response.send_message(
                f"🏰 Base #{base['base_id']} — TH{base['th_level']} {base['category']}\n{base['layout_url']}",
                ephemeral=True)
        return cb

    def _vote(self, select):
        async def cb(interaction: discord.Interaction):
            base_id = int(select.values[0])
            result = await toggle_base_vote(self.guild_id, base_id, interaction.user.id)
            if result is None:
                await interaction.response.send_message("❌ That layout was removed.", ephemeral=True)
                return
            count, voted = result
            embed, view = await self.build(self.owner_id, self.guild_id, self.th, self.category,
                                           self.page, self.color)
            view.message = interaction.message
            await interaction.response.edit_message(embed=embed, view=view)
            await interaction.followup.send(f"{'👍 Upvoted' if voted else 'Upvote removed from'} base #{base_id} (now {count}).",
                                            ephemeral=True)
        return cb

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ArmyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_reply: dict = {}
        self.menu = app_commands.ContextMenu(name="Read Clash link", callback=self.read_link_menu)
        bot.tree.add_command(self.menu)

    def cog_unload(self):
        self.bot.tree.remove_command(self.menu.name, type=self.menu.type)

    def _client(self):
        return decoder_client(self.bot.coc)

    async def _embed_for(self, url: str, *, quiet: bool, color: int = COLOUR):
        """(embed, view) for an army or layout link; None for anything else. quiet=True hides decode errors."""
        kind = link_kind(url)
        if kind == "army":
            try:
                info = decode_army(self._client(), url)
            except ValueError as e:
                return None if quiet else (discord.Embed(description=f"❌ {e}", colour=color), None)
            return army_embed(info, color), army_view(info)
        if kind == "layout":
            parsed = layout_link(url)
            if not parsed:
                return None if quiet else (discord.Embed(description="❌ That base link is invalid or too long.",
                                                         colour=color), None)
            normalised, th = parsed
            title = f"🏰 Base layout{f' · TH{th}' if th else ''}"
            embed = discord.Embed(title=title, description="Open it in game with the link below, or save it to the library.",
                                  colour=color)
            return embed, SaveBaseView(normalised, th)
        return None

    # ── /army ────────────────────────────────────────────────────────────────
    @app_commands.command(name="army", description="Decode a Clash of Clans army link: units, space, spells, heroes")
    @app_commands.describe(link="The army link from the game (link.clashofclans.com…)")
    async def army(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer(thinking=True)
        try:
            info = decode_army(self._client(), link.strip())
        except ValueError as e:
            await send_page(interaction, Page(f"❌ {e}"))
            return
        kwargs = {"embed": army_embed(info, command_color(interaction))}
        view = army_view(info)
        if view:
            kwargs["view"] = view
        await interaction.followup.send(**kwargs)

    async def read_link_menu(self, interaction: discord.Interaction, message: discord.Message):
        links = extract_links(message.content)
        if not links:
            await interaction.response.send_message(
                "❌ I found no Clash of Clans link in that message (or I can't read it).", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        sent = 0
        for url in links:
            result = await self._embed_for(url, quiet=False, color=command_color(interaction))
            if result:
                embed, view = result
                await interaction.followup.send(embed=embed, **({"view": view} if view else {}))
                sent += 1
        if not sent:
            await interaction.followup.send("❌ That link isn't an army or base link I can read.")

    # ── automatic reader ─────────────────────────────────────────────────────
    @app_commands.command(name="autodecode", description="Admin: read army and base links pasted in chat automatically")
    @app_commands.describe(enabled="Turn the automatic reader on or off for this server")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def autodecode(self, interaction: discord.Interaction, enabled: bool):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ You need the **Manage Server** permission.", ephemeral=True)
            return
        await set_auto_decode(interaction.guild_id, enabled)
        text = f"🔗 Automatic link reading is now **{'on' if enabled else 'off'}** for this server."
        if enabled and not config.ENABLE_MESSAGE_CONTENT:
            text += ("\n⚠️ The bot owner has not enabled message reading yet (set `ENABLE_MESSAGE_CONTENT=1` and turn on "
                     "the Message Content intent), so nothing is read for now. `/army` and the **Read Clash link** "
                     "message menu work either way.")
        await interaction.response.send_message(text, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not config.ENABLE_MESSAGE_CONTENT or message.author.bot or not message.guild:
            return
        links = extract_links(message.content, limit=2)
        if not links or not await get_auto_decode(message.guild.id):
            return
        perms = message.channel.permissions_for(message.guild.me)
        if not (perms.send_messages and perms.embed_links):
            return
        now = time.monotonic()
        if now - self._last_reply.get(message.channel.id, 0) < 2:        # at most one reply burst per 2s per channel
            return
        self._last_reply[message.channel.id] = now
        for url in links:
            result = await self._embed_for(url, quiet=True)
            if not result:
                continue
            embed, view = result
            try:
                await message.reply(embed=embed, mention_author=False, allowed_mentions=_NO_MENTIONS,
                                    **({"view": view} if view else {}))
            except discord.HTTPException:
                log.warning("Could not reply with a decoded link in channel %s", message.channel.id)
                return

    # ── base library ─────────────────────────────────────────────────────────
    @app_commands.command(name="bases", description="Browse this server's saved base layouts")
    @app_commands.describe(th="Town Hall level", category="Layout type")
    @app_commands.choices(category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES])
    @app_commands.guild_only()
    async def bases(self, interaction: discord.Interaction, th: Optional[app_commands.Range[int, 1, 25]] = None,
                    category: Optional[app_commands.Choice[str]] = None):
        await interaction.response.defer(thinking=True)
        embed, view = await BasesView.build(interaction.user.id, interaction.guild_id, th,
                                            category.value if category else None, 0,
                                            command_color(interaction))
        view.message = await interaction.followup.send(embed=embed, view=view, wait=True)

    @app_commands.command(name="basesave", description="Save a base layout link to this server's library")
    @app_commands.describe(link="The layout link from the game", category="Layout type",
                           th="Town Hall level (read from the link when possible)", notes="Optional notes")
    @app_commands.choices(category=[app_commands.Choice(name=c, value=c) for c in CATEGORIES])
    @app_commands.guild_only()
    async def basesave(self, interaction: discord.Interaction, link: str, category: app_commands.Choice[str],
                       th: Optional[app_commands.Range[int, 1, 25]] = None, notes: Optional[str] = None):
        parsed = layout_link(link.strip())
        if not parsed:
            await interaction.response.send_message(
                "❌ That isn't a valid base layout link from `link.clashofclans.com` (it may also be too long).", ephemeral=True)
            return
        url, link_th = parsed
        level = th or link_th
        if not level:
            await interaction.response.send_message("❌ I can't tell the Town Hall level from this link. "
                                                    "Add the `th` option.", ephemeral=True)
            return
        base_id = await add_base(interaction.guild_id, interaction.user.id, level, category.value, url,
                                 (notes or "").strip()[:300] or None)
        await interaction.response.send_message(f"✅ Saved as base **#{base_id}** (TH{level} · {category.value}).")

    @app_commands.command(name="basedelete", description="Remove a base from the library (your own, or any as an admin)")
    @app_commands.describe(base_id="The number shown as #id in /bases")
    @app_commands.guild_only()
    async def basedelete(self, interaction: discord.Interaction, base_id: int):
        base = await get_base(interaction.guild_id, base_id)
        if not base:
            await interaction.response.send_message(f"❌ There is no base #{base_id} in this server.", ephemeral=True)
            return
        if base["submitted_by"] != interaction.user.id and not is_admin(interaction):
            await interaction.response.send_message("❌ Only the person who saved it, or an admin, can remove a base.",
                                                    ephemeral=True)
            return
        await delete_base(interaction.guild_id, base_id)
        await interaction.response.send_message(f"🗑️ Base #{base_id} removed.")


async def setup(bot):
    await bot.add_cog(ArmyCog(bot))
