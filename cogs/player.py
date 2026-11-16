"""Player commands: /player (3 pages + clan history), /todo, /audit."""
import asyncio
import os
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from coc_api import get_player, get_player_stats, get_player_warhits, get_player_join_leave
from core.builders import (
    _build_player_page1, _build_player_page2, _build_player_page3, _build_todo_page,
)
from core.helpers import (
    E, ApiError, fmt_number, get_scraped_th_max, get_th_max, normalize_tag, resolve_tag,
)
from core.nav import Btn, Markup, Page, TTLCache, send_page


def th_image(th_level) -> Optional[str]:
    path = os.path.join(config.TH_IMAGE_DIR, f"TownHall_{th_level}.png")
    return path if os.path.isfile(path) else None


class PlayerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache = TTLCache(600)

    async def _bundle(self, tag: str):
        key = f"p:{tag}"
        cached = self.cache.get(key)
        if cached:
            return cached
        data, stats, warhits = await asyncio.gather(
            get_player(tag), get_player_stats(tag), get_player_warhits(tag))
        if "error" in data:
            raise ApiError(data["error"])
        self.cache.set(key, (data, stats, warhits))
        return data, stats, warhits

    # ── /player ──────────────────────────────────────────────────────────────
    async def route_player(self, cb: str) -> Page:
        action, _, tag = cb.partition(":")
        try:
            data, stats, warhits = await self._bundle(tag)
        except ApiError as e:
            return Page(f"❌ {e}")
        thumb = th_image(data.get("townHallLevel", 1))

        if action == "player_p2":
            return Page(_build_player_page2(data),
                        Markup([[Btn(f"{E['back']} Season Stats", cb=f"player_p1:{tag}"),
                                 Btn(f"{E['next']} Heroes", cb=f"player_p3:{tag}")]]), thumb_path=thumb)
        if action == "player_p3":
            return Page(_build_player_page3(data),
                        Markup([[Btn(f"{E['back']} Troops & Spells", cb=f"player_p2:{tag}")]]), thumb_path=thumb)
        if action == "player_history":
            return await self._history_page(data, tag, thumb)
        return Page(_build_player_page1(data, stats, warhits, tag),
                    Markup([[Btn("🛡️ Clan History", cb=f"player_history:{tag}")],
                            [Btn(f"{E['next']} Troops & Spells", cb=f"player_p2:{tag}")]]), thumb_path=thumb)

    async def _history_page(self, data, tag, thumb) -> Page:
        back = Markup([[Btn(f"{E['back']} Back to Profile", cb=f"player_p1:{tag}")]])
        hist = await get_player_join_leave(tag, limit=15)
        if isinstance(hist, dict) and "error" in hist:
            return Page(f"❌ {hist['error']}", back, thumb_path=thumb)
        history = hist.get("items", []) if isinstance(hist, dict) else hist if isinstance(hist, list) else []
        if not history:
            return Page(f"❌ No clan history found for {tag}.", back, thumb_path=thumb)
        text = f"🛡️ **Clan History for {data.get('name', tag)}** `{tag}`\n\n"
        for item in history[:15]:
            c_tag = item.get("clan", "").replace("#", "")
            c_name = item.get("clan_name", "Unknown")
            t_type = item.get("type", "join").capitalize()
            t_str = str(item.get("time", ""))[:16].replace("T", " ")
            link = f"https://link.clashofclans.com/en?action=OpenClanProfile&tag=%23{c_tag}"
            emoji = "🟢" if t_type.lower() == "join" else "🔴"
            text += f"{emoji} **{t_type}** | [{c_name}]({link}) `#{c_tag}`\n📅 {t_str}\n\n"
        return Page(text, back, thumb_path=thumb)

    @app_commands.command(name="player", description="Full player stats, troops, heroes and clan history")
    @app_commands.describe(tag="Player tag, e.g. #YY8PQY28 (optional if you linked an account)")
    async def player(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "player")
        if not t:
            await interaction.followup.send("Please provide a tag, or link an account first with `/link`.")
            return
        page = await self.route_player(f"player_p1:{normalize_tag(t)}")
        await send_page(interaction, page, self.route_player)

    # ── /todo ────────────────────────────────────────────────────────────────
    async def route_todo(self, cb: str) -> Page:
        _, category, tag = cb.split(":", 2)
        key = f"todo:{tag}"
        cached = self.cache.get(key)
        if not cached:
            data = await get_player(tag)
            if "error" in data:
                return Page(f"❌ {data['error']}")
            th_max = await get_th_max(self.bot.coc, tag, data.get("townHallLevel", 1))
            cached = (data, th_max)
            self.cache.set(key, cached)
        data, th_max = cached
        text, markup = _build_todo_page(data, category, tag, th_max)
        return Page(text, markup)

    @app_commands.command(name="todo", description="Upgrade to-do list: heroes, troops, spells, siege, pets")
    @app_commands.describe(tag="Player tag (optional if you linked an account)")
    async def todo(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "player")
        if not t:
            await interaction.followup.send("Please provide a tag, or link an account first with `/link`.")
            return
        page = await self.route_todo(f"todo_p:heroes:{normalize_tag(t)}")
        await send_page(interaction, page, self.route_todo)

    # ── /audit ───────────────────────────────────────────────────────────────
    @app_commands.command(name="audit", description="Rush audit: heroes, troops and spells vs your Town Hall max")
    @app_commands.describe(tag="Player tag (optional if you linked an account)")
    async def audit(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "player")
        if not t:
            await interaction.followup.send("Please provide a player tag, or link an account first with `/link`.")
            return
        t = normalize_tag(t)
        data = await get_player(t)
        if "error" in data:
            await send_page(interaction, Page(f"❌ {data['error']}"))
            return
        th = data.get("townHallLevel", 1)
        norm_tag = data.get("tag", t).strip().upper()
        th_max = await get_th_max(self.bot.coc, norm_tag, th)
        await send_page(interaction, Page(self._audit_text(data, th, norm_tag, th_max)))

    @staticmethod
    def _audit_text(data: dict, th: int, norm_tag: str, th_max: dict) -> str:
        tag = norm_tag
        name = data.get("name", "Unknown")
        th = data.get("townHallLevel", 1)
        norm_tag = data.get("tag", tag).strip().upper()
        clean_tag = norm_tag.replace("#", "")
        p_link = f"https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=%23{clean_tag}"


        # ── Heroes Analysis ──────────────────────────────────────────────────
        heroes = [h for h in data.get("heroes", []) if h.get("village") == "home"]
        hero_lines = []
        rushed_heroes = []

        for h in heroes:
            hname = h.get("name", "Unknown")
            lvl = h.get("level", 0)
            max_lvl = get_scraped_th_max(hname, th) or th_max.get(hname) or h.get("maxLevel", 1)
            pct = round(lvl / max_lvl * 100) if max_lvl > 0 else 100

            if pct >= 90:
                status = "✅"
            elif pct >= 75:
                status = "⚠️"
            else:
                status = "❌"
                if hname not in rushed_heroes:
                    rushed_heroes.append(hname)

            hero_lines.append(f"  • {hname}: {lvl}/{max_lvl} ({pct}%) {status}")

        # ── Troops Analysis ──────────────────────────────────────────────────
        home_troops = [
            t for t in data.get("troops", [])
            if t.get("village") == "home"
            and "Super" not in t.get("name", "")
            and not t.get("name", "").startswith("Super")
        ]
        total_troops = len(home_troops)
        troop_sum = 0
        maxed_troops = 0
        for t in home_troops:
            t_ml = get_scraped_th_max(t.get("name", ""), th) or th_max.get(t.get("name", "")) or t.get("maxLevel", 1)
            troop_sum += (t.get("level", 0) / t_ml * 100) if t_ml > 0 else 100
            if t.get("level", 0) >= t_ml:
                maxed_troops += 1
    
        troop_pct = round(troop_sum / total_troops) if total_troops > 0 else 100
        troop_status = "✅" if troop_pct >= 80 else "⚠️" if troop_pct >= 60 else "❌"

        # ── Spells Analysis ──────────────────────────────────────────────────
        home_spells = [s for s in data.get("spells", []) if s.get("village") == "home"]
        total_spells = len(home_spells)
        spell_sum = 0
        maxed_spells = 0
        for s in home_spells:
            s_ml = get_scraped_th_max(s.get("name", ""), th) or th_max.get(s.get("name", "")) or s.get("maxLevel", 1)
            spell_sum += (s.get("level", 0) / s_ml * 100) if s_ml > 0 else 100
            if s.get("level", 0) >= s_ml:
                maxed_spells += 1
            
        spell_pct = round(spell_sum / total_spells) if total_spells > 0 else 100
        spell_status = "✅" if spell_pct >= 80 else "⚠️" if spell_pct >= 60 else "❌"


        # ── Overall Verdict ──────────────────────────────────────────────────
        hero_avg_pct = 0
        if heroes:
            def _hero_ml(h):
                hname = h.get("name", "")
                return get_scraped_th_max(hname, th) or th_max.get(hname) or h.get("maxLevel", 1)
            hero_avg_pct = round(sum(
                h.get("level", 0) / _hero_ml(h) * 100
                for h in heroes if _hero_ml(h) > 0
            ) / len(heroes))

        overall_score = (hero_avg_pct * 0.5) + (troop_pct * 0.3) + (spell_pct * 0.2)

        if overall_score >= 85:
            verdict = "✅ **NOT RUSHED** — Solid account!"
            verdict_color = "🟢"
        elif overall_score >= 70:
            verdict = "⚠️ **SLIGHTLY RUSHED** — Some areas need work"
            verdict_color = "🟡"
        elif overall_score >= 50:
            verdict = "❌ **RUSHED** — Significant upgrades needed"
            verdict_color = "🔴"
        else:
            verdict = "💀 **HEAVILY RUSHED** — Major recovery needed"
            verdict_color = "🔴"

        # ── Build Output ─────────────────────────────────────────────────────
        text = (
            f"🔍 **Rush Audit — [{name}]({p_link})**\n"
            f"{E['th']} Town Hall: **{th}** | Score: **{round(overall_score)}%** {verdict_color}\n"
            f"`{norm_tag}`\n"
            f"{'─' * 30}\n"
        )

        if hero_lines:
            text += f"\n{E['hero']} **Heroes** (avg {hero_avg_pct}% of TH{th} max):\n"
            text += "\n".join(hero_lines) + "\n"
        else:
            text += f"\n{E['hero']} **Heroes:** None unlocked\n"

        text += (
            f"\n{E['troop']} Troops: {maxed_troops}/{total_troops} maxed ({troop_pct}%) {troop_status}"
            f"\n{E['spell']} Spells: {maxed_spells}/{total_spells} maxed ({spell_pct}%) {spell_status}"
        )

        text += (
            f"\n\n{'─' * 30}\n"
            f"📊 **Verdict:** {verdict}\n"
        )

        if rushed_heroes:
            text += f"⚠️ Heroes need attention: {', '.join(rushed_heroes)}\n"

        return text


async def setup(bot):
    await bot.add_cog(PlayerCog(bot))
