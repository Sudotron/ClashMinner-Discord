"""/scrap — refresh Town Hall max levels from clash.ninja (owner only) + weekly auto-refresh."""
import asyncio
import json
import logging
import os
import urllib.request

import bs4
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.perms import is_owner

log = logging.getLogger(__name__)
URL = "https://www.clash.ninja/guides/max-levels-for-each-th"


def scrape_max_levels() -> dict:
    """Blocking: fetch + parse the max-level tables. Run via asyncio.to_thread."""
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=20).read()
    soup = bs4.BeautifulSoup(html, "html.parser")
    data = {}
    for idx, table in enumerate(soup.find_all("table", class_="all-th-overview")):
        if idx < 5:  # skip Defenses, Traps, Army Buildings, Resources, Walls
            continue
        headers = table.find("tr").find_all("th")
        if len(headers) <= 2:
            continue
        th_levels = []
        for h in headers[2:]:
            try:
                th_levels.append(int(h.text.strip()))
            except ValueError:
                pass
        for row in table.find_all("tr")[1:]:
            tds = row.find_all("td")
            if not tds:
                continue
            unit = tds[0].text.strip()
            if unit in ("Walls", "TH", "None"):
                continue
            levels = {}
            for i, td in enumerate(tds[1:]):
                val = td.text.strip()
                if i < len(th_levels) and val != "-":
                    try:
                        levels[str(th_levels[i])] = int(val)
                    except ValueError:
                        pass
            if levels:
                data[unit] = levels
    return data


def compute_diff(old: dict, new: dict) -> list:
    changes = []
    for unit, levels in new.items():
        if unit not in old:
            changes.append(f"• 🆕 **{unit}** added.")
            continue
        for th, lvl in levels.items():
            o = old[unit].get(th)
            if o is None:
                changes.append(f"• **{unit}**: TH{th} added (max {lvl}).")
            elif o != lvl:
                changes.append(f"• **{unit}**: TH{th} changed from {o} to {lvl}.")
    changes += [f"• ❌ **{u}** removed." for u in old if u not in new]
    return changes


def _load_old() -> dict:
    try:
        with open(config.TH_MAX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    tmp = config.TH_MAX_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, config.TH_MAX_FILE)  # atomic: never leaves a half-written file


async def refresh() -> tuple[dict, list]:
    """Scrape, sanity-check, save. Returns (new_data, changes)."""
    old = _load_old()
    new = await asyncio.to_thread(scrape_max_levels)
    if not new:
        raise RuntimeError("No data could be extracted (page layout may have changed).")
    if old and len(new) < len(old) * 0.5:
        raise RuntimeError(f"Scraped only {len(new)} units vs {len(old)} before — refusing to overwrite "
                           "(page layout probably changed).")
    changes = compute_diff(old, new)
    if changes or not old:
        _save(new)
    return new, changes


class Scraper(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.weekly.start()

    def cog_unload(self):
        self.weekly.cancel()

    @app_commands.command(name="scrap", description="Owner only: refresh Town Hall max levels from Clash Ninja")
    async def scrap(self, interaction: discord.Interaction):
        if not is_owner(interaction.user.id):
            await interaction.response.send_message("❌ This command is available for the owner only.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            data, changes = await refresh()
        except Exception as e:
            log.error("Scrape error: %s", e)
            await interaction.followup.send(f"❌ Failed to scrape data: {e}")
            return
        if not changes:
            await interaction.followup.send(f"✅ Successfully scraped {len(data)} units. No level changes detected.")
            return
        diff = "\n".join(changes)
        if len(diff) > 3000:
            diff = diff[:3000] + "\n... (truncated)"
        await interaction.followup.send(embed=discord.Embed(
            description=f"✅ Successfully scraped! Changes detected:\n\n{diff}", color=0x5CB85C))

    @tasks.loop(hours=168)
    async def weekly(self):
        if not config.OWNER_ID:
            return
        try:
            _, changes = await refresh()
        except Exception as e:
            log.error("Auto-scraper error: %s", e)
            return
        if changes:
            diff = "\n".join(changes)[:3000]
            try:
                owner = await self.bot.fetch_user(config.OWNER_ID)
                await owner.send(embed=discord.Embed(
                    description=f"🔄 **Automated Scraper Update!**\nChanges detected in max levels:\n\n{diff}"))
            except discord.HTTPException:
                log.warning("Could not DM the owner about scraper changes.")

    @weekly.before_loop
    async def _wait(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Scraper(bot))
