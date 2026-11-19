# Clash OTTO — Discord Bot

Clash of Clans analytics and clan tracking for Discord. This is a full port of the Clash OTTO Telegram bot to
Discord slash commands, embeds and buttons. (The Player Tracking bot is a separate project and is not included.)

## Commands

| Command | What it does | Who |
|---|---|---|
| `/help` | Command list | everyone |
| `/link tag [api_token] [primary]` | Link a player or clan tag. Add the in-game API token to verify you own the account (✔) | everyone |
| `/accounts [user]` | List linked accounts; switch your primary account or unlink an alt | everyone |
| `/profile` | Your Discord identity, linked accounts and clans | everyone |
| `/player [tag]` | Season/all-time stats, troops & spells, heroes & equipment, clan history | everyone |
| `/todo [tag]` | Upgrade to-do list (heroes, troops, spells, siege, pets) for your Town Hall | everyone |
| `/audit [tag]` | Rush audit with score and verdict | everyone |
| `/clan [tag]` | Clan profile + paginated roster | everyone |
| `/clansorted [tag] [sort]` | Roster sorted by trophies / TH / donations / role / XP | everyone |
| `/clanwar [tag]` | Current war or last 2 wars; analytics (missed, 3-stars, attacks) | everyone |
| `/cwl [tag]` | CWL rounds, roster, missed hits, season leaderboard | everyone |
| `/cap_stats [tag]` | All-time Capital Gold contribution leaderboard | everyone |
| `/progress [tag]` | Picture card: % of Town Hall max for heroes, equipment, troops, spells, siege, pets | everyone |
| `/poster [tag]` | Shareable profile card (Town Hall render, trophies, war stars, heroes) | everyone |
| `/waropt [clan]` | Clan members grouped by war preference (in / out), by Town Hall | everyone |
| `/missing-hits [clan] [type]` | Who still has attacks left in the current war (incl. CWL) / raid weekend | everyone |
| `/activity [clan]` | Members ranked by last detected activity; flags 7+ days inactive | everyone |
| `/leaderboard [clan] [stat]` | Season donations, donation ratio, war stars, loot, capital gold | everyone |
| `/army link` · **Read Clash link** (message menu) | Decode an army link: units, housing space, spells, siege, heroes, clan castle | everyone |
| `/bases [th] [category]`, `/basesave`, `/basedelete` | Server library of base layouts with one-vote upvotes | everyone (delete: owner of the entry or admin) |
| `/reminders setup / toggle / status / remove` | Automatic war, raid weekend and clan games reminders that ping linked members | Manage Server |
| `/autodecode enabled` | Read army and base links pasted in chat (needs `ENABLE_MESSAGE_CONTENT=1`) | Manage Server |
| `/loot` | Loot forecaster; toggle server notifications | everyone (toggle: admin) |
| `/clantrack tag [channel]` | Start join/leave/promotion/war-feed logs | Manage Server |
| `/deltrack`, `/trackinfo`, `/setchannel` | Stop / inspect tracking, set notice channel | Manage Server |
| `/adminlink user tag`, `/scrap` | Link a tag for someone / refresh max-level data | bot owner |

Embeds use a distinct color for each command, including across paginated results. When a tag is omitted, player
commands use your linked player and clan commands use your linked clan. Clan commands do not infer a clan from a
linked player; provide a clan tag or link one with `/link`. Commands with a `[clan]` option may use the server's
tracked clan when no tag or linked clan is available.

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
- The **primary** account (★) is the default for commands without a tag. Your first link becomes primary; later links are alts until you pick `primary:True` on `/link` or switch in `/accounts`.
- A tag verified with an API token (✔) can't be linked by anyone else without their own token. Using `/link` with a token makes the whole reply private.
- Up to 25 players and 25 clans per user. The `tag` option of `/player`, `/todo`, `/audit` and the clan commands suggests your linked accounts as you type.
- The database upgrades itself on start (numbered migrations in `database.py`).
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

## Reminders, activity and the base library — how they work

- **Reminders** run every 15 minutes per configured clan and post once per threshold (the duplicate guard lives in the
  database, so a restart never repeats one). War: under 2 h and under 1 h left (regular and CWL wars). Raid weekend:
  under 6 h left; the per-member attack limit (including bonus attacks) comes from the API. Clan Games: under 12 h left
  and below 4000 points. The API has no Clan Games timing or per-event points, so the bot uses the monthly schedule in
  `config.py` (22nd 08:00 → 28th 08:00 UTC) and takes everyone's "Games Champion" score at the start as a baseline. If
  the bot was offline at the start (baseline taken more than 2 h late) it skips games reminders for that event rather
  than ping people wrongly. Members who joined after the baseline are skipped. Linked members are pinged, others are named.
- **Activity** has no "last online" in the game API, so the bot polls every hour (clans from `/clantrack` and
  `/reminders`; other clans only when someone runs the command) and counts a member as active when war stars, XP,
  loot achievements or donation achievements change. Trophies and season donations are ignored on purpose (they change
  without the player doing anything, or reset). Leaderboards for war stars / loot / capital count from the moment the
  bot first saw each player this season; donations are exact from the first look.
- **Base library** stores `link.clashofclans.com` layout links per server (max 300). Only that exact host is accepted
  and nothing is fetched from the network.
- **Army decoding** uses the game data bundled with coc.py (no extra data file, no API call). Links from a game update
  newer than the installed coc.py are reported as unreadable instead of guessed.
- **Message reader** (`/autodecode`): off unless the owner sets `ENABLE_MESSAGE_CONTENT=1`, enables the *Message Content
  Intent* in the Discord Developer Portal, and an admin turns it on per server.
