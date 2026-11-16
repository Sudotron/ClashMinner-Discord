# Clash OTTO — Discord Bot

Clash of Clans analytics and clan tracking for Discord. This is a full port of the Clash OTTO Telegram bot to
Discord slash commands, embeds and buttons. (The Player Tracking bot is a separate project and is not included.)

## Commands

| Command | What it does | Who |
|---|---|---|
| `/help` | Command list | everyone |
| `/link tag` | Link your player or clan tag to your Discord account | everyone |
| `/profile` | Your Discord identity, linked accounts and clans | everyone |
| `/player [tag]` | Season/all-time stats, troops & spells, heroes & equipment, clan history | everyone |
| `/todo [tag]` | Upgrade to-do list (heroes, troops, spells, siege, pets) for your Town Hall | everyone |
| `/audit [tag]` | Rush audit with score and verdict | everyone |
| `/clan [tag]` | Clan profile + paginated roster | everyone |
| `/clansorted [tag] [sort]` | Roster sorted by trophies / TH / donations / role / XP | everyone |
| `/clanwar [tag]` | Current war or last 2 wars; analytics (missed, 3-stars, attacks) | everyone |
| `/cwl [tag]` | CWL rounds, roster, missed hits, season leaderboard | everyone |
| `/cap_stats [tag]` | All-time Capital Gold contribution leaderboard | everyone |
| `/loot` | Loot forecaster; toggle server notifications | everyone (toggle: admin) |
| `/clantrack tag [channel]` | Start join/leave/promotion/war-feed logs | Manage Server |
| `/deltrack`, `/trackinfo`, `/setchannel` | Stop / inspect tracking, set notice channel | Manage Server |
| `/adminlink user tag`, `/scrap` | Link a tag for someone / refresh max-level data | bot owner |

If you leave out `tag`, the bot uses the account you linked with `/link`.

## Setup

1. **Create the Discord app:** https://discord.com/developers/applications → New Application → **Bot** tab →
   Reset Token (copy it). No privileged intents are needed.
2. **Invite it:** OAuth2 → URL Generator → scopes `bot` + `applications.commands`; permissions
   *View Channels, Send Messages, Embed Links, Attach Files*. Open the generated URL and pick your server.
3. **Configure:** `cp .env.example .env` and fill in `DISCORD_TOKEN`, `OWNER_ID`, `COC_EMAIL`, `COC_PASSWORD`.
   For development set `DEV_GUILD_ID` to your test server's ID so commands appear instantly.
4. **Run:**
   ```
   python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   python bot.py
   ```
5. In your server run `/clantrack #YOURCLAN` (in the channel where logs should go) and `/link #YOURTAG`.

The database (`otto.db`) is created automatically. Users link their accounts fresh; nothing is imported from Telegram.

## Hosting and cost

- Slash commands only work while `bot.py` is running.
- The tracker (join/leave/war feed), loot updates and maintenance alerts need the process running **continuously**.
  Running on your own PC works for development; for 24/7 tracking you need an always-on machine.
- Back up `otto.db` and `th_max_levels.json` by copying the files.

## Differences from the Telegram version

- Buttons only respond to the person who ran the command (others get a private hint).
- Tracking, notification toggles and the loot toggle are **per server**; each server picks its own log channel.
- Admin actions require **Manage Server** (or being the bot owner) instead of a single owner ID. If `OWNER_ID` is unset,
  owner-only commands are disabled rather than open to everyone.
- Times (war end) use Discord timestamps, shown in each viewer's own time zone instead of fixed IST.
- Tags are normalised (`yy8pqy28` → `#YY8PQY28`) so the same account can't be linked twice.
- The newest linked account is the default for commands without a tag.
- `/clantrack` records the current war opponent so it doesn't announce an old war as "found".
- `/scrap` refuses to overwrite `th_max_levels.json` if the scrape returns less than half the previous units.
- Removed: `/getid` (Discord shows IDs natively) and the unused `troops_cmd`.

## Layout

```
bot.py            entry point, command guard, error handling
config.py         .env loading
database.py       SQLite (user_tags, guild_config)
coc_api.py        Official profile/war API adapter and ClashKing history endpoints
core/             nav.py (embed + button framework), builders.py (text pages), helpers.py, perms.py
cogs/             one file per feature group
tests/            offline smoke tests (python tests/test_smoke.py)
```

## Data sources

- Player/clan profiles, current wars, tracking, `/cwl` and TH max levels use the official Clash of Clans API.
- Player war hits, player clan history, and previous-war analytics use ClashKing's documented custom endpoints.
- `/cap_stats` uses all-time contribution/raid achievements from official player profiles; the old ClashKing season-stats endpoint is no longer available.
- The clash.ninja scraper (`/scrap`) — page layout may have changed.
- `forecaster_data.json` is a static weekly model from 2023; the loot index is a rough estimate.
