# Implementation notes — ClashKing features ported to ClashMinner

Status of the roadmap (`clashminner_feature_porting_roadmap_v2.txt`): **all five phases are implemented.**

| Phase | Delivered | Where |
|---|---|---|
| 0 | Numbered DB migrations, batch player fetcher with cache, `run_blocking` | `database.py`, `coc_api.py`, `core/helpers.py` |
| 1 | `/link` (+ API token verification), `/accounts`, primary/verified flags, autocomplete on every `tag` option | `cogs/general.py`, `core/autocomplete.py` |
| 2 | `/progress`, `/poster` (Pillow), TH19 asset, bundled DejaVu font | `cogs/cards.py`, `core/progress.py`, `core/image_cards.py` |
| 3 | `/waropt`, `/reminders setup\|toggle\|status\|remove`, `/missing-hits`, war + CWL + raid + clan games reminders | `cogs/clan.py`, `cogs/reminders.py`, `core/reminder_logic.py`, `core/war_pref.py` |
| 4 | `/activity`, `/leaderboard` (7 stats), hourly polling, season handling | `cogs/activity.py`, `core/activity_logic.py`, `core/seasons.py` |
| 5 | `/army`, "Read Clash link" menu, `/autodecode`, `/bases`, `/basesave`, `/basedelete` with upvotes | `cogs/army.py`, `core/army.py` |

## Where this differs from the roadmap (and why)

- **No `army_ids.json`.** coc.py 4.0.0 already decodes CopyArmy links (`client.parse_army_link`) with unit names and housing
  space. The link format is `army=` with `h` (heroes), `u` (troops), `s` (spells), `i`/`d` (clan castle troops/spells) and
  items written `{quantity}x{id}`. coc.py silently replaces unknown ids with Barbarian / Lightning Spell, so
  `core/army.py` checks every id and quantity first.
- **Raid attack limits come from the API** (`attackLimit + bonusAttackLimit` per member), not a fixed number.
- **Reminders use their own 15-minute loop** instead of the 30-second war tracker, because a reminder clan can differ
  from a server's tracked clan, and it costs only 1–3 API calls per clan per tick (cached per tick across servers).
- **Primary account**: the first link is primary; later links are alts unless `primary:True` / switched in `/accounts`.
  (Before, the newest link silently became the default.)
- **Verified tags are exclusive**: nobody else can link a tag verified by someone else without their own token; a newer
  verification takes the badge. Owner `/adminlink` bypasses the check.
- **Activity ignores trophies and season donations** (they change without the player acting, or reset). Fingerprint:
  war stars, XP, and the achievements Gold Grab, Elixir Escapade, Heroic Heist, Friend in Need, Sharing is caring,
  Aggressive Capitalism, Games Champion, Conqueror. All names were checked against coc.py's game data.
- **Clan Games** use the schedule in `config.py` and a start-of-event baseline; a baseline taken more than 2 h late disables
  that event's reminders (no false pings).
- **Hero equipment** progress uses the `maxLevel` the API reports for each item (`th_max_levels.json` has no equipment).
- `/progress` and `/todo` count only units the player owns (same rule as `/audit`).

## What was verified, and what was not

Verified here (`python tests/test_smoke.py`: 39 test groups, 287 assertions; passes on the newest dependencies — discord.py 2.7.1, Pillow 13 — and on the oldest allowed by `requirements.txt` — discord.py 2.4.0, Pillow 10.1, aiosqlite 0.19): every command registers and serialises to a valid Discord payload
(names, descriptions, option limits, required-before-optional order), DB migration from an old-schema file, all storage
rules, the reminder state machine (tiers, duplicates, per-server, failed posts retried, crashes release the claim),
activity/season maths, link validation against spoofed hosts/ports/credentials/duplicate parameters, army decoding of
valid and garbage links, base library permissions, image output, and API-wrapper behaviour with fake coc.py clients.
Names of achievements, heroes and super troops were cross-checked against coc.py's bundled game data.

**Not verifiable from the build environment** (needs your real credentials/servers — please try once):
1. The live API token check (`/link tag api_token`): coc.py calls `POST /players/{tag}/verifytoken`.
2. A real reminder post in a real channel (permissions, pings landing on the right users).
3. `Message Content` intent behaviour for `/autodecode` (only if you enable `ENABLE_MESSAGE_CONTENT=1`).
4. The Clan Games schedule (22nd 08:00 → 28th 08:00 UTC) — adjust `GAMES_*` in `config.py` if the game changes it.
5. Very new units: links from a game update newer than coc.py 4.0.0's data are reported as unreadable. Same for
   Sky Wagon / Greedy Raven, which are in this bot's lists but not in coc.py's data yet.

Notes: discord.py ≥ 2.6 prints a DeprecationWarning for `TextInput(label=...)`; it still works. The new commands add 12 to the
slash-command tree (31 total, well under Discord's 100 limit); the first start syncs them automatically.
