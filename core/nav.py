"""Discord-native navigation: pages = embed + buttons, routed by 'callback id' strings.

The original Telegram bot encoded state in inline-button callback_data
(e.g. "player_p2:#TAG"). We keep that idea: a Btn carries an id string, and each
cog supplies a `router(id) -> Page` coroutine. NavView renders a Page's buttons
and edits the message in place when one is clicked.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import discord

from core import state

log = logging.getLogger(__name__)
EMBED_COLOR = 0xFFB703
COMMAND_COLORS = {
    # Core & Account (Electric Gold, Cyan & Magenta)
    "help": 0xFFB703,             # Bright Clash Gold
    "link": 0x00E5FF,             # Electric Cyan
    "accounts": 0x00B4D8,         # Vivid Sky Blue
    "adminlink": 0xFF2A6D,        # Neon Rose Red
    "profile": 0xD946EF,          # Radiant Orchid

    # Player Stats & Progress (Luminous Blues, Mint & Sunset)
    "player": 0xFFD166,           # Warm Luminous Gold
    "todo": 0x06D6A0,             # Bright Mint Emerald
    "audit": 0xFF5400,            # Blazing Neon Orange
    "progress": 0x9D4EDD,         # Vivid Amethyst
    "poster": 0xFF4D8D,           # Hot Pink

    # Clan & Wars (Crimson, Lime & Royal Gold)
    "clan": 0xFF3B30,             # Crisp Crimson Red
    "clansorted": 0x00F5D4,       # Bright Aqua Teal
    "clanwar": 0xFF0055,          # Deep Neon Ruby
    "cwl": 0xFFBE0B,              # Champion Trophy Gold
    "waropt": 0x38B000,           # Vibrant Lime Green
    "missing-hits": 0xFF9E00,     # Bright Amber Warning

    # Economy, Capital & Leaderboards
    "cap_stats": 0xFB5607,        # Capital Forge Orange
    "activity": 0x3A86FF,         # Electric Cobalt
    "leaderboard": 0xC77DFF,      # Royal Neon Violet
    "loot": 0xFEE440,             # Bright Elixir/Gold Yellow
    "scrap": 0x2EC4B6,            # Bright Turquoise

    # Army & Base Layouts (Replaced dull grey/brown with crisp neon tones)
    "army": 0x00BBF9,             # Bright Azure Blue
    "autodecode": 0x72EFDD,       # Soft Neon Ice
    "bases": 0xFF758F,            # Coral Rose
    "basesave": 0x80ED99,         # Fresh Pastel Neon Green
    "basedelete": 0xE63946,       # Sharp Ruby Red

    # Server Tracking & Admin
    "clantrack": 0x4CC9F0,        # Bright Ice Blue
    "deltrack": 0xF72585,         # Vivid Magenta Pink
    "trackinfo": 0x8338EC,        # Deep Electric Indigo
    "setchannel": 0x10B981,       # Emerald Green

    # Reminders
    "reminders setup": 0xFF6B6B,  # Vibrant Coral
    "reminders toggle": 0xFF9F1C, # Bright Tangerine
    "reminders status": 0x48CAE4, # Crisp Cerulean
    "reminders remove": 0xEF476F, # Punchy Raspberry
}
NOOP = "noop"


def command_color(interaction: discord.Interaction) -> int:
    command = getattr(interaction, "command", None)
    names = []
    while command is not None and isinstance(getattr(command, "name", None), str):
        names.append(command.name)
        command = getattr(command, "parent", None)
    qualified_name = " ".join(reversed(names))
    return COMMAND_COLORS.get(qualified_name, COMMAND_COLORS.get(names[0] if names else "", EMBED_COLOR))


class NavError(Exception):
    """Raise inside a router to show an ephemeral message to the clicking user."""


@dataclass
class Btn:
    label: str
    cb: str


@dataclass
class Markup:
    rows: list = field(default_factory=list)  # list[list[Btn]]


@dataclass
class Page:
    text: str
    markup: Optional[Markup] = None
    title: Optional[str] = None
    thumb_path: Optional[str] = None   # local file, attached on first send
    thumb_url: Optional[str] = None    # remote image URL
    color: int = EMBED_COLOR

    def to_embed(self) -> discord.Embed:
        text = self.text if len(self.text) <= 4096 else self.text[:4090] + "\n…"
        e = discord.Embed(description=text, color=self.color, title=self.title)
        if self.thumb_path:
            e.set_thumbnail(url=f"attachment://{os.path.basename(self.thumb_path)}")
        elif self.thumb_url:
            e.set_thumbnail(url=self.thumb_url)
        return e


Router = Callable[[str], Awaitable[Optional[Page]]]


class NavView(discord.ui.View):
    def __init__(self, router: Router, markup: Optional[Markup], owner_id: int, timeout: float = 900,
                 color: int = EMBED_COLOR):
        super().__init__(timeout=timeout)
        self.router = router
        self.owner_id = owner_id
        self.color = color
        self.message: Optional[discord.Message] = None
        self.render(markup)

    def render(self, markup: Optional[Markup]):
        self.clear_items()
        if not markup:
            return
        for r, row in enumerate(markup.rows[:5]):
            for b in row[:5]:
                item = discord.ui.Button(
                    label=b.label[:80], row=r, disabled=(b.cb == NOOP),
                    style=discord.ButtonStyle.secondary)
                item.callback = self._make_callback(b.cb)
                self.add_item(item)

    def _make_callback(self, data: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            try:
                page = await self.router(data)
            except NavError as e:
                await interaction.followup.send(str(e), ephemeral=True)
                return
            except Exception:
                log.exception("Button handler failed for %s", data)
                page = Page("❌ Something went wrong. Please run the command again.")
            if page is None:
                return
            page.color = self.color
            self.render(page.markup)
            await interaction.edit_original_response(embed=page.to_embed(), view=self)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who ran this command can use these buttons. Run the command yourself.",
                ephemeral=True)
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


async def send_page(interaction: discord.Interaction, page: Page, router: Optional[Router] = None,
                    *, edit_loading: bool = False):
    """Send `page` as the (already deferred) reply to a slash command."""
    page.color = command_color(interaction)
    kwargs = {"embed": page.to_embed()}
    if page.thumb_path and os.path.isfile(page.thumb_path):
        kwargs["file"] = discord.File(page.thumb_path, filename=os.path.basename(page.thumb_path))
    view = None
    if page.markup and router:
        view = NavView(router, page.markup, interaction.user.id, color=page.color)
        kwargs["view"] = view
    msg = await interaction.followup.send(wait=True, **kwargs)
    if view:
        view.message = msg
    return msg


class TTLCache:
    """Small in-memory cache with per-entry expiry (replaces Telegram's bot_data)."""

    def __init__(self, ttl: float = 600, max_items: int = 200):
        self.ttl, self.max_items, self._d = ttl, max_items, {}

    def get(self, key):
        item = self._d.get(key)
        if not item:
            return None
        if time.time() - item[0] > self.ttl:
            self._d.pop(key, None)
            return None
        return item[1]

    def set(self, key, value):
        if len(self._d) >= self.max_items:
            oldest = min(self._d, key=lambda k: self._d[k][0])
            self._d.pop(oldest, None)
        self._d[key] = (time.time(), value)
