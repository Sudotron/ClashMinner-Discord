"""Clan commands: /clan, /clansorted, /clanwar, /cwl."""
import asyncio
from datetime import timezone
from typing import Optional

import coc
import discord
from discord import app_commands
from discord.ext import commands

from coc_api import get_clan, get_clan_war, get_players_batch, get_previous_wars
from core.builders import (
    _build_clan_page1, _build_members_page, _clansorted_markup, _cwar_analytics_markup,
    _cwl_overview_text, _cwl_round_markup, _fmt_remaining, _parse_coc_time, _th_roster,
)
from core.helpers import ApiError, E, clan_url, normalize_tag, resolve_tag
from core.autocomplete import linked_tag_choices
from core.clan_arg import resolve_clan
from core.war_pref import format_war_preference, group_war_preference
from core.nav import Btn, Markup, Page, TTLCache, send_page

NO_TAG = "Please provide a clan tag, or link a clan with `/link`."


def _ts(dt, style: str = "t") -> str:
    """Discord timestamp: renders in each viewer's own time zone."""
    return f"<t:{int(dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp())}:{style}>"


def _plink(tag: str) -> str:
    t = tag.strip("#")
    return f"https://link.clashofclans.com/en?action=OpenPlayerProfile&tag={t}"


class ClanCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache = TTLCache(600)

    # ═════════════════════════ /clan ═════════════════════════════════════════
    async def _clan_data(self, tag: str) -> dict:
        cached = self.cache.get(f"c:{tag}")
        if cached:
            return cached
        data = await get_clan(tag, self.bot.coc)
        if "error" in data:
            if not data["error"].startswith("Clan not found"):
                raise ApiError(data["error"])
            raise ApiError("Could not find clan details. Is it a valid clan tag?")
        self.cache.set(f"c:{tag}", data)
        self.cache.set(f"c:{data.get('tag', tag).strip().upper()}", data)
        return data

    async def route_clan(self, cb: str) -> Page:
        parts = cb.split(":", 2)
        action, tag = parts[0], (parts[1] if len(parts) > 1 else "")
        try:
            page_no = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            page_no = 0
        try:
            data = await self._clan_data(tag)
        except ApiError as e:
            return Page(f"❌ {e}")
        badge = (data.get("badgeUrls") or {}).get("large")
        if action == "clan_p2":
            text, markup = _build_members_page(data, 0)
        elif action == "clan_members":
            text, markup = _build_members_page(data, page_no)
        else:
            text = _build_clan_page1(data)
            markup = Markup([[Btn("👥 Members List", cb=f"clan_p2:{tag}")]])
        return Page(text, markup, thumb_url=badge)

    @app_commands.command(name="clan", description="Clan profile with a paginated member roster")
    @app_commands.describe(tag="Clan tag (optional if you linked a clan)")
    async def clan(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "clan")
        if not t:
            await interaction.followup.send(NO_TAG)
            return
        try:
            data = await self._clan_data(normalize_tag(t))
        except ApiError as e:
            await send_page(interaction, Page(f"❌ {e}"))
            return
        page = await self.route_clan(f"clan_p1:{data.get('tag', t).strip().upper()}")
        await send_page(interaction, page, self.route_clan)

    @clan.autocomplete("tag")
    async def _clan_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    # ═════════════════════════ /clansorted ═══════════════════════════════════
    async def route_sorted(self, cb: str) -> Page:
        _, sort_type, tag = cb.split(":", 2)
        try:
            data = await self._clan_data(tag)
        except ApiError as e:
            return Page(f"❌ {e}", _clansorted_markup(tag))
        members = data.get("memberList", [])
        if sort_type == "trophies":
            members = sorted(members, key=lambda x: x.get("trophies", 0), reverse=True)
            title, fmt = "🏆 Trophies", lambda m: f"🏆 {m.get('trophies', 0):,}"
        elif sort_type == "th":
            members = sorted(members, key=lambda x: x.get("townHallLevel", 0), reverse=True)
            title, fmt = "🏯 Town Hall", lambda m: f"TH{m.get('townHallLevel', '?')}"
        elif sort_type == "donations":
            members = sorted(members, key=lambda x: x.get("donations", 0), reverse=True)
            title, fmt = "🔼 Donations", lambda m: f"🔼 {m.get('donations', 0):,} / 🔽 {m.get('donationsReceived', 0):,}"
        elif sort_type == "role":
            role_map = {"leader": 4, "coLeader": 3, "admin": 2, "member": 1}
            members = sorted(members, key=lambda x: role_map.get(x.get("role", "member"), 0), reverse=True)
            title, fmt = "👑 Role", lambda m: f"Role: {m.get('role', 'member').capitalize()}"
        elif sort_type == "xplevel":
            members = sorted(members, key=lambda x: x.get("expLevel", 0), reverse=True)
            title, fmt = "🎖️ XP Level", lambda m: f"Lvl {m.get('expLevel', 0)}"
        else:
            members = sorted(members, key=lambda x: x.get("clanRank", 99))
            title, fmt = "Rank", lambda m: f"Rank #{m.get('clanRank')}"
        text = f"👥 **{data.get('name', 'Unknown')} — Sorted by {title}**\n{'─' * 28}\n"
        for i, m in enumerate(members[:50]):
            text += f"`{i + 1}.` {m.get('name', 'Unknown')} — {fmt(m)}\n"
        return Page(text, _clansorted_markup(tag), thumb_url=(data.get("badgeUrls") or {}).get("large"))

    @app_commands.command(name="clansorted", description="Clan roster sorted by trophies, TH, donations, role or XP")
    @app_commands.describe(tag="Clan tag (optional if you linked a clan)", sort="What to sort by")
    @app_commands.choices(sort=[
        app_commands.Choice(name="Trophies", value="trophies"),
        app_commands.Choice(name="Town Hall", value="th"),
        app_commands.Choice(name="Donations", value="donations"),
        app_commands.Choice(name="Role", value="role"),
        app_commands.Choice(name="XP Level", value="xplevel"),
    ])
    async def clansorted(self, interaction: discord.Interaction, tag: Optional[str] = None,
                         sort: Optional[app_commands.Choice[str]] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "clan")
        if not t:
            await interaction.followup.send(NO_TAG)
            return
        page = await self.route_sorted(f"clansort:{sort.value if sort else 'trophies'}:{normalize_tag(t)}")
        await send_page(interaction, page, self.route_sorted)

    @clansorted.autocomplete("tag")
    async def _clansorted_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    # ═════════════════════════ /clanwar ══════════════════════════════════════
    @staticmethod
    def _result_line(cs, os_, cd, od, tiebreak=True) -> str:
        if cs > os_:
            return "\n🏆 **Result: VICTORY!**"
        if os_ > cs:
            return "\n💀 **Result: DEFEAT**"
        if cd > od:
            return "\n🏆 **Result: VICTORY! (Destruction tiebreak)**"
        if od > cd:
            return "\n💀 **Result: DEFEAT (Destruction tiebreak)**"
        return "\n🤝 **Result: DRAW**"

    async def _clanwar_page(self, tag: str) -> Page:
        war_data = await get_clan_war(tag, self.bot.coc)
        if "error" in war_data:
            clan_data = await get_clan(tag, self.bot.coc)
            if "error" not in clan_data and not clan_data.get("isWarLogPublic", False):
                ctag = clan_data.get("tag", tag)
                text = (f"🛡️ **{clan_data.get('name', 'Clan')}** `{ctag}`\n\n"
                        f"📖 *{clan_data.get('description', 'No description.')}*\n\n"
                        f"🔗 [Open in Clash of Clans]({clan_url(ctag)})\n\n"
                        f"⚠️ **THE CLAN WAR LOG IS PRIVATE**")
                return Page(text, thumb_url=(clan_data.get("badgeUrls") or {}).get("large"))
            if "error" in war_data:
                return Page(f"❌ Could not find war details.\nReason: *{war_data.get('error')}*\n"
                            "*(If you just made your log public, the Clash API may take a few minutes to update its cache!)*")

        norm_tag = war_data.get("clan", {}).get("tag", tag).strip().upper()
        state = war_data.get("state")
        if state == "notInWar":
            items = (await get_previous_wars(norm_tag, limit=2)).get("items", [])
            if not items:
                return Page("⚔️ The clan is not currently in a standard war (or is in CWL) and no previous war data was found.")
            text = f"⚔️ **Clan is not in war. Displaying last {len(items)} wars:**\n\n"
            rows = []
            for i, w in enumerate(items):
                ws, os_ = w.get("clan", {}).get("stars", 0), w.get("opponent", {}).get("stars", 0)
                res = "🏆 Victory" if ws > os_ else "💀 Defeat" if os_ > ws else "🤝 Draw"
                text += (f"**War {i + 1}: {w.get('clan', {}).get('name', 'Clan')} vs "
                         f"{w.get('opponent', {}).get('name', 'Opponent')}**\n{res} | ⭐ {ws} — {os_}\n\n")
                rows.append([Btn(f"📊 War {i + 1} Analytics", cb=f"cwar_a:home:{norm_tag}:{i}:0")])
            return Page(text, Markup(rows))

        c, o = war_data.get("clan", {}), war_data.get("opponent", {})
        cs, cd = c.get("stars", 0), c.get("destructionPercentage", 0)
        os_, od = o.get("stars", 0), o.get("destructionPercentage", 0)
        size = war_data.get("teamSize", "?")
        if state == "preparation":
            time_str, label = _fmt_remaining(_parse_coc_time(war_data.get("startTime", "")), "preparation"), "⚙️ Preparation"
        elif state == "inWar":
            time_str, label = _fmt_remaining(_parse_coc_time(war_data.get("endTime", "")), "inWar"), "🔥 In War"
        elif state == "warEnded":
            end_dt = _parse_coc_time(war_data.get("endTime", ""))
            time_str = f"\n⏰ War ended at: {_ts(end_dt)}" if end_dt else "\n⏰ War ended"
            label = "War Ended"
        else:
            time_str, label = "", state.capitalize() if state else "Unknown"
        result = self._result_line(cs, os_, cd, od) if state == "warEnded" else ""
        text = (
            f"⚔️ **Clan War — {label}**\n👥 Size: {size}v{size}{time_str}{result}\n{'─' * 30}\n"
            f"🛡️ **{c.get('name', 'Unknown')}**\n  ⭐ Stars: {cs}   💥 Dest: {cd:.1f}%\n{_th_roster(c.get('members', []))}\n\n"
            f"🏴 **{o.get('name', 'Unknown')}**\n  ⭐ Stars: {os_}   💥 Dest: {od:.1f}%\n{_th_roster(o.get('members', []))}\n"
        )
        return Page(text, Markup([[Btn("📊 Analytics", cb=f"cwar_a:home:{norm_tag}:live:0"),
                                   Btn("🗡️ Attacks", cb=f"cwar_a:attacks:{norm_tag}:live:0")]]))

    async def route_war(self, cb: str) -> Page:
        parts = cb.split(":")
        view, norm_tag = parts[1], parts[2].upper()
        war_index = parts[3] if len(parts) > 3 else "live"
        page_no = int(parts[4]) if len(parts) > 4 else 0

        if war_index == "live":
            war_data = await get_clan_war(norm_tag, self.bot.coc)
        else:
            items = (await get_previous_wars(norm_tag, limit=2)).get("items", [])
            idx = int(war_index)
            war_data = items[idx] if len(items) > idx else {"error": "War not found."}
        if "error" in war_data:
            return Page(f"❌ Failed to fetch data: {war_data['error']}")

        c, o = war_data.get("clan", {}), war_data.get("opponent", {})
        if view == "home":
            state = war_data.get("state", "Unknown")
            size = war_data.get("teamSize", "?")
            text = (
                f"⚔️ **Clan War — {state.capitalize() if state else 'Unknown'}**\n👥 Size: {size}v{size}\n\n"
                f"🛡️ **{c.get('name', 'Unknown')}**\n  ⭐ Stars: {c.get('stars', 0)}   💥 Dest: {c.get('destructionPercentage', 0):.1f}%\n"
                f"{_th_roster(c.get('members', []))}\n\n"
                f"🏴 **{o.get('name', 'Unknown')}**\n  ⭐ Stars: {o.get('stars', 0)}   💥 Dest: {o.get('destructionPercentage', 0):.1f}%\n"
                f"{_th_roster(o.get('members', []))}\n")
            return Page(text, _cwar_analytics_markup(view, norm_tag, war_index, 0, 1))

        members = c.get("members", [])
        per = war_data.get("attacksPerMember", 2)
        lines = []
        if view == "missed":
            lines.append(f"📊 **War Analytics — Missed Attacks**\n{'─' * 28}\n")
            missed = [f"• {m.get('name')} (TH{m.get('townhallLevel', '?')}) [{m.get('tag')}]({_plink(m.get('tag', ''))}) — {per - len(m.get('attacks', []))} missed"
                      for m in members if len(m.get("attacks", [])) < per]
            lines.extend(missed or ["✅ **All attacks have been used!**"])
        elif view == "3star":
            lines.append(f"📊 **War Analytics — 🌟 3-Star Specialists**\n{'─' * 28}\n")
            hits = [f"• {m.get('name')} (TH{m.get('townhallLevel', '?')}) [{m.get('tag')}]({_plink(m.get('tag', ''))})"
                    for m in members for a in m.get("attacks", []) if a.get("stars", 0) == 3]
            lines.extend(hits or ["❌ **No 3-star attacks.**"])
        elif view == "stars":
            lines.append(f"📊 **War Analytics — ⭐ Other Attacks**\n{'─' * 28}\n")
            hits = [f"• {m.get('name')} (TH{m.get('townhallLevel', '?')}) [{m.get('tag')}]({_plink(m.get('tag', ''))}) — {a.get('stars', 0)}⭐ ({a.get('destructionPercentage', 0)}%)"
                    for m in members for a in m.get("attacks", []) if a.get("stars", 0) < 3]
            lines.extend(hits or ["❌ **No 2-Star or lower attacks.**"])
        elif view == "attacks":
            lines.append(f"🗡️ **War Analytics — All Attacks**\n{'─' * 28}\n")
            member_map = {m.get("tag", ""): m for m in c.get("members", []) + o.get("members", [])}
            raw = []
            for side, own in ((c, True), (o, False)):
                for m in side.get("members", []):
                    for a in m.get("attacks", []):
                        d = member_map.get(a.get("defenderTag", ""), {})
                        stars = "⭐" * a.get("stars", 0) if a.get("stars", 0) > 0 else "☆"
                        order = a.get("order", 999)
                        mine = f"{m.get('name', 'Unknown')}(Th{m.get('townhallLevel', '?')})"
                        theirs = f"{d.get('name', 'Unknown')}(Th{d.get('townhallLevel', '?')})"
                        arrow = f"{mine} ─────> {theirs}" if own else f"{theirs} <───── {mine}"
                        raw.append((order, f"`{order}.` {arrow} {stars} ({a.get('destructionPercentage', 0)}%)"))
            raw.sort(key=lambda x: x[0])
            lines.extend([x[1] for x in raw] or ["❌ No attacks recorded yet."])

        chunks, cur = [], ""
        for ln in lines:
            if len(cur) + len(ln) > 3800:
                chunks.append(cur)
                cur = ln + "\n"
            else:
                cur += ln + "\n"
        if cur:
            chunks.append(cur)
        total = len(chunks) or 1
        safe = min(page_no, total - 1)
        text = chunks[safe] if chunks else "No data."
        if total > 1:
            text += f"\n*Page {safe + 1} of {total}*"
        return Page(text, _cwar_analytics_markup(view, norm_tag, war_index, safe, total))

    @app_commands.command(name="clanwar", description="Current clan war info and analytics")
    @app_commands.describe(tag="Clan tag (optional if you linked a clan)")
    async def clanwar(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "clan")
        if not t:
            await interaction.followup.send(NO_TAG)
            return
        await send_page(interaction, await self._clanwar_page(normalize_tag(t)), self.route_war)

    @clanwar.autocomplete("tag")
    async def _clanwar_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    # ═════════════════════════ /cwl ══════════════════════════════════════════
    async def _group(self, tag: str):
        group = self.cache.get(f"cwl:{tag}")
        if not group:
            group = await self.bot.coc.get_league_group(tag)
            self.cache.set(f"cwl:{tag}", group)
        return group

    async def route_cwl(self, cb: str) -> Page:
        parts = cb.split(":", 3)  # cwl_r:view:tag:round_idx
        view = parts[1] if len(parts) > 1 else "overview"
        norm_tag = (parts[2] if len(parts) > 2 else "").strip().upper()
        round_idx = int(parts[3]) if len(parts) > 3 else 0
        if not self.bot.coc:
            return Page("❌ Bot is not connected to the Clash of Clans API.")
        try:
            group = await self._group(norm_tag)
        except Exception:
            return Page("❌ CWL data expired. Run `/cwl` again.")
        rounds = group.rounds if group else []
        total = len(rounds)
        nav = lambda: _cwl_round_markup(norm_tag, round_idx, total, view)

        if view == "overview":
            return Page(_cwl_overview_text(group, norm_tag), nav())
        if round_idx >= total:
            return Page("❌ Round not found.")
        war_tags = [wt for wt in rounds[round_idx] if wt != "#0"]
        if not war_tags:
            return Page(f"⏳ Round {round_idx + 1} hasn't started yet.", nav())

        our_war = None
        for wt in war_tags:
            try:
                w = await self.bot.coc.get_league_war(wt)
                if norm_tag in (w.clan.tag, w.opponent.tag):
                    our_war = w
                    break
            except Exception:
                pass
        if not our_war:
            try:
                our_war = await self.bot.coc.get_league_war(war_tags[0])
            except Exception:
                return Page(f"❌ Could not load Round {round_idx + 1} war data.", nav())

        mine, opp = (our_war.clan, our_war.opponent) if our_war.clan.tag == norm_tag else (our_war.opponent, our_war.clan)
        c_members, o_members = mine.members or [], opp.members or []
        c_attacks, o_attacks = sum(len(m.attacks) for m in c_members), sum(len(m.attacks) for m in o_members)
        w_state, w_size = our_war.state, our_war.team_size
        season = group.season if group else "Unknown Season"

        if w_state == "preparation":
            time_str, label = _fmt_remaining(getattr(our_war.start_time, "time", None), "preparation"), "In Prep"
        elif w_state == "inWar":
            time_str, label = _fmt_remaining(getattr(our_war.end_time, "time", None), "inWar"), "In War"
        elif w_state == "warEnded":
            end_t = getattr(our_war.end_time, "time", None)
            time_str = f"\n⏰ Ended at: {_ts(end_t)}" if end_t else "\n⏰ War ended"
            label = "War Ended"
        else:
            time_str, label = "", w_state.capitalize()
        result = ""
        if w_state == "warEnded":
            result = f"\n{'🏆 Victory' if mine.stars > opp.stars else '💀 Defeat' if opp.stars > mine.stars else '🤝 Draw'}"

        if view == "attacks":
            lines = [f"🗡️ **CWL Round {round_idx + 1} — All Attacks**\n{'─' * 28}\n"]
            member_map = {m.tag: m for m in list(c_members) + list(o_members)}
            raw = []
            for members, own in ((c_members, True), (o_members, False)):
                for m in members:
                    for a in m.attacks:
                        d = member_map.get(a.defender_tag)
                        stars = "⭐" * a.stars if a.stars > 0 else "☆"
                        mine_s = f"{m.name}(Th{m.town_hall})"
                        theirs = f"{d.name if d else 'Unknown'}(Th{d.town_hall if d else '?'})"
                        arrow = f"{mine_s} ─────> {theirs}" if own else f"{theirs} <───── {mine_s}"
                        raw.append((a.order, f"`{a.order}.` {arrow} {stars} ({a.destruction}%)"))
            raw.sort(key=lambda x: x[0])
            lines.extend([x[1] for x in raw] or ["❌ No attacks recorded for this round yet."])
            text = "\n".join(lines)
        elif view == "missed":
            lines = [f"❌ **CWL Round {round_idx + 1} — Missed Hits**\n{'─' * 28}\n"]
            missed = [f"• {m.name} (TH{m.town_hall}) [{m.tag}]({_plink(m.tag)}) — {our_war.attacks_per_member - len(m.attacks)} missed"
                      for m in c_members if len(m.attacks) < our_war.attacks_per_member]
            lines.extend(missed or ["✅ **All attacks have been used!**"])
            text = "\n".join(lines)
        elif view == "all_members":
            lines = [f"👥 **CWL Round {round_idx + 1} — Members roster**\n{'─' * 28}\n"]
            cs, os_ = sorted(c_members, key=lambda x: x.map_position), sorted(o_members, key=lambda x: x.map_position)
            for pos in range(w_size):
                def disp(lst):
                    if pos >= len(lst):
                        return "❓ Unknown"
                    return f"[{lst[pos].name}]({_plink(lst[pos].tag)})"
                lines.append(f"`{pos + 1}.` {disp(cs)} <-> {disp(os_)}")
            text = "\n".join(lines)
        elif view in ("leaderboard", "rankings"):
            wars = self.cache.get(f"cwlw:{norm_tag}")
            if not wars:
                all_tags = [wt for r in group.rounds for wt in r if wt != "#0"]
                results = await asyncio.gather(*[self.bot.coc.get_league_war(wt) for wt in all_tags], return_exceptions=True)
                wars = [r for r in results if not isinstance(r, Exception)]
                self.cache.set(f"cwlw:{norm_tag}", wars)
            stats = {cl.tag: {"name": cl.name, "stars": 0, "dest": 0.0} for cl in group.clans}
            for w in wars:
                if w.state != "preparation":
                    for side in (w.clan, w.opponent):
                        if side.tag in stats:
                            stats[side.tag]["stars"] += side.stars
                            stats[side.tag]["dest"] += side.destruction
            ranked = sorted(stats.values(), key=lambda x: (x["stars"], x["dest"]), reverse=True)
            lines = [f"🏆 **Season Leaderboard ({season})**\n{'─' * 28}\n"]
            for i, cl in enumerate(ranked):
                lines.append(f"`{i + 1}.` **{cl['name']}**")
                lines.append(f"   {'🌟' if i == 0 else '⭐'} Stars: `{cl['stars']}` | 💥 Dest: `{cl['dest']:.1f}%`\n")
            text = "\n".join(lines)
        else:
            text = (
                f"**{mine.name}**\n\n**War Against**\n[{opp.name} ({opp.tag})]({clan_url(opp.tag)})\n\n"
                f"**War State**\nCWL {season} - Round {round_idx + 1}/{total}\n{label} ({w_size} vs {w_size}){time_str}{result}\n\n"
                f"**War Stats**\n⚔️ `{c_attacks}/{w_size}`  —  `{o_attacks}/{w_size}`\n"
                f"⭐ `{mine.stars}`  —  `{opp.stars}`\n💥 `{mine.destruction:.1f}%`  —  `{opp.destruction:.1f}%`\n\n"
                f"**War Composition**\n🛡️ **{mine.name}**\n{_th_roster(c_members)}\n🏴 **{opp.name}**\n{_th_roster(o_members)}\n")
        return Page(text, nav())

    @app_commands.command(name="cwl", description="Clan War League dashboard: rounds, roster, missed hits, leaderboard")
    @app_commands.describe(tag="Clan tag (optional if you linked a clan)")
    async def cwl(self, interaction: discord.Interaction, tag: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        t = await resolve_tag(interaction.user.id, tag, "clan")
        if not t:
            await interaction.followup.send(NO_TAG)
            return
        if not self.bot.coc:
            await interaction.followup.send("❌ Bot is not connected to the Clash of Clans API.")
            return
        t = normalize_tag(t)
        try:
            group = await self._group(t)
        except coc.NotFound:
            await interaction.followup.send(
                "❌ CWL data not available.\n\n*CWL only runs for the first ~10 days of each month. "
                "Outside that window, or if the clan is not participating, no data is returned.*")
            return
        except coc.Maintenance:
            await interaction.followup.send("❌ Clash of Clans API is currently under maintenance.")
            return
        except coc.PrivateWarLog:
            await interaction.followup.send("❌ This clan's war log is private.")
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Error fetching CWL data: {e}")
            return
        latest = 0
        for i, r in enumerate(group.rounds if group else []):
            if any(wt != "#0" for wt in r):
                latest = i
        page = await self.route_cwl(f"cwl_r:round:{t.upper()}:{latest}")
        await send_page(interaction, page, self.route_cwl)

    @cwl.autocomplete("tag")
    async def _cwl_tag_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")

    # ═══ /waropt ═════════════════════════════════════════════════════════════
    @app_commands.command(name="waropt", description="Clan members grouped by war preference (opted in / out)")
    @app_commands.describe(clan="Clan tag (optional if you linked a clan)")
    async def waropt(self, interaction: discord.Interaction, clan: Optional[str] = None):
        await interaction.response.defer(thinking=True)
        tag = await resolve_clan(self.bot, interaction, clan)
        data = await get_clan(tag, self.bot.coc)
        if "error" in data:
            raise ApiError(data["error"])
        members = data.get("memberList", [])
        # warPreference is only on the player payload, so this is one lookup per member (batched + cached).
        players = await get_players_batch([m["tag"] for m in members], self.bot.coc)
        text = format_war_preference(data.get("name", tag), tag, group_war_preference(members, players))
        await send_page(interaction, Page(text))

    @waropt.autocomplete("clan")
    async def _waropt_clan_ac(self, interaction: discord.Interaction, current: str):
        return await linked_tag_choices(interaction, current, "clan")


async def setup(bot):
    await bot.add_cog(ClanCog(bot))
