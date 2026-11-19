"""Offline smoke tests: no Discord or Clash API access needed (all network calls are mocked).

Run:  python tests/test_smoke.py
"""
import asyncio
import logging
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["OWNER_ID"] = "42"

import discord  # noqa: E402

import config  # noqa: E402
from core import helpers  # noqa: E402
from core.nav import COMMAND_COLORS, NavError, NavView, Page, command_color, send_page  # noqa: E402
import database as db  # noqa: E402

SEASON = helpers.current_season()
PLAYER = {
    "tag": "#PTAG", "name": "Tester", "townHallLevel": 16, "expLevel": 200, "trophies": 5000,
    "bestTrophies": 5500, "builderBaseTrophies": 3000, "bestBuilderBaseTrophies": 3200, "warStars": 1000,
    "role": "leader", "clan": {"tag": "#CTAG", "name": "TestClan"}, "league": {"name": "Legend League"},
    "attackWins": 10, "defenseWins": 2, "donations": 500, "donationsReceived": 300,
    "troops": [
        {"name": "Barbarian", "level": 10, "maxLevel": 11, "village": "home"},
        {"name": "Super Barbarian", "level": 10, "maxLevel": 11, "village": "home", "superTroopIsActive": True},
        {"name": "Wall Wrecker", "level": 4, "maxLevel": 5, "village": "home"},
        {"name": "L.A.S.S.I", "level": 10, "maxLevel": 15, "village": "home"}],
    "spells": [{"name": "Rage Spell", "level": 5, "maxLevel": 6, "village": "home"}],
    "heroes": [{"name": "Barbarian King", "level": 90, "maxLevel": 95, "village": "home"},
               {"name": "Battle Machine", "level": 30, "maxLevel": 35, "village": "builderBase"}],
    "heroEquipment": [{"name": "Giant Gauntlet", "level": 18, "maxLevel": 27}],
    "achievements": [{"name": "Friend in Need", "value": 100000}, {"name": "Games Champion", "value": 50000},
                     {"name": "Most Valuable Clanmate", "value": 9000}, {"name": "Aggressive Capitalism", "value": 8000},
                     {"name": "War League Legend", "value": 300}],
}
STATS = {"capital": {SEASON: {"donated": 1000, "raided": 500}}, "clan_games": {SEASON: 4000}}
WARHITS = {"items": [{"stars": 3}, {"stars": 2}, {"stars": 1}]}
MEMBERS = [{"tag": f"#M{i}", "name": f"Member{i}", "role": r, "townHallLevel": 16 - i % 3, "trophies": 5000 - i * 10,
            "clanRank": i + 1, "donations": i * 5, "donationsReceived": i * 3, "expLevel": 100 + i}
           for i, r in enumerate(["leader", "coLeader", "admin"] + ["member"] * 22)]
CLAN = {"tag": "#CTAG", "name": "TestClan", "clanLevel": 15, "members": 25, "clanPoints": 40000,
        "clanBuilderBasePoints": 30000, "requiredTrophies": 3000, "requiredTownhallLevel": 12,
        "location": {"name": "India"}, "description": "A test clan", "warWins": 100, "warWinStreak": 5,
        "isWarLogPublic": True, "warLosses": 20, "warTies": 1, "warFrequency": "always",
        "warLeague": {"name": "Crystal League I"}, "capitalLeague": {"name": "Gold I"},
        "clanCapital": {"capitalHallLevel": 9}, "memberList": MEMBERS, "badgeUrls": {"large": "https://example.com/b.png"}}


def war(state="inWar", atk=True):
    mem = lambda p, n: {"tag": f"#{p}{n}", "name": f"{p}{n}", "townhallLevel": 16, "mapPosition": n,
                        "attacks": ([{"order": n, "stars": 3 - n % 3, "destructionPercentage": 90 + n,
                                      "defenderTag": f"#O{n}"}] if atk and p == "C" else [])}
    return {"state": state, "teamSize": 3, "attacksPerMember": 2,
            "startTime": "29990101T000000.000Z", "endTime": "29990102T000000.000Z",
            "clan": {"tag": "#CTAG", "name": "TestClan", "stars": 5, "destructionPercentage": 80.5,
                     "members": [mem("C", i) for i in range(1, 4)]},
            "opponent": {"tag": "#OTAG", "name": "EnemyClan", "stars": 3, "destructionPercentage": 70.2,
                         "members": [mem("O", i) for i in range(1, 4)]}}


def ok(name):
    print(f"  ✓ {name}")


def check_page(page: Page, label: str):
    assert isinstance(page, Page), f"{label}: not a Page ({page!r})"
    emb = page.to_embed()
    assert 0 < len(emb.description) <= 4096, f"{label}: bad length {len(emb.description)}"
    is_error = page.text.startswith("❌") and not page.text.startswith("❌ **")
    assert not is_error, f"{label}: error page: {page.text[:120]}"
    if page.markup:
        assert len(page.markup.rows) <= 5, f"{label}: >5 button rows"
        for row in page.markup.rows:
            assert len(row) <= 5, f"{label}: >5 buttons in a row"
            for b in row:
                assert len(b.label) <= 80
    return emb


async def main():
    await db.init_db()

    # ── database ─────────────────────────────────────────────────────────────
    r1 = await db.link_account(1, "#AAA", "player", label="Alpha")
    r2 = await db.link_account(1, "#BBB", "player")
    await db.link_account(1, "#CCC", "clan")
    assert r1["is_primary"] and r1["new"] and not r2["is_primary"]
    assert await db.get_linked_account(1, "player") == "#AAA"      # the first link stays primary
    assert await db.get_all_linked_tags(1, "player") == ["#AAA", "#BBB"]
    assert await db.get_linked_account(1, "clan") == "#CCC"
    assert await db.get_linked_account(2, "player") is None
    await db.link_account(3, "#PLAYER", "player")
    cfg = await db.get_guild_config(99)
    cfg.update(tracked_tag="#X", channel_id=5); cfg["state"]["members"] = {"#1": {"name": "a"}}
    await db.save_guild_config(cfg)
    again = await db.get_guild_config(99)
    assert again["tracked_tag"] == "#X" and again["state"]["members"] == {"#1": {"name": "a"}}
    assert len(await db.all_guild_configs()) == 1
    ok("database (links, first-link-primary, guild config round-trip)")

    # ── helpers ──────────────────────────────────────────────────────────────
    assert helpers.normalize_tag(" yy8pqy28 ") == "#YY8PQY28"
    assert helpers.get_scraped_th_max("Barbarian King", 16) > 0
    assert await helpers.resolve_tag(1, None, "player") == "#AAA"
    assert await helpers.resolve_tag(1, "abc", "clan") == "#ABC"
    assert await helpers.resolve_tag(2, None, "player") is None
    assert await helpers.resolve_tag(3, None, "clan") is None
    from core.clan_arg import resolve_clan
    try:
        await resolve_clan(None, SimpleNamespace(user=SimpleNamespace(id=3), guild_id=None), None)
    except NavError:
        pass
    else:
        raise AssertionError("A linked player must not be used to infer a clan")
    ok("helpers (tags, scraped max levels, resolve_tag)")

    # ── bot + cogs load, commands register ──────────────────────────────────
    import bot as botmod
    import coc_api as A
    bot = botmod.OttoBot()
    bot.coc = None
    _never = asyncio.Event()
    bot.wait_until_ready = _never.wait   # background loops stay parked; we call their logic directly
    for name in botmod.COGS:
        await bot.load_extension(f"cogs.{name}")
    names = sorted(c.name for c in bot.tree.get_commands())
    expected = sorted(["help", "link", "adminlink", "profile", "player", "todo", "audit", "clan", "clansorted",
                       "clanwar", "cwl", "cap_stats", "loot", "accounts", "progress", "poster", "waropt", "reminders", "missing-hits",
                       "activity", "leaderboard", "army", "autodecode", "bases", "basesave", "basedelete", "Read Clash link", "clantrack", "deltrack", "trackinfo", "setchannel", "scrap"])
    assert names == expected, f"commands differ: {set(names) ^ set(expected)}"
    ok(f"all {len(names)} slash commands register")

    general = bot.get_cog("General")
    help_interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock()))
    await general.help.callback(general, help_interaction)
    help_interaction.response.send_message.assert_awaited_once()
    assert "file" not in help_interaction.response.send_message.await_args.kwargs
    ok("/help sends no animation file")

    # ── official API adapter ─────────────────────────────────────────────────
    official = SimpleNamespace(
        get_player=AsyncMock(return_value=SimpleNamespace(_raw_data=PLAYER)),
        get_clan=AsyncMock(return_value=SimpleNamespace(_raw_data=CLAN)),
        get_clan_war=AsyncMock(return_value=SimpleNamespace(
            _raw_data={"clan": {"tag": "#OTAG"}, "opponent": {"tag": "#CTAG"}},
            clan=SimpleNamespace(tag="#CTAG"))))
    assert await A.get_player("ptag", official) == PLAYER
    official.get_player.assert_awaited_once_with("#PTAG")
    assert await A.get_clan("ctag", official, lookup_cache=False) == CLAN
    official.get_clan.assert_awaited_once_with("#CTAG", lookup_cache=False)
    war_data = await A.get_clan_war("ctag", official, lookup_cache=False)
    official.get_clan_war.assert_awaited_once_with("#CTAG", lookup_cache=False)
    assert war_data["clan"]["tag"] == "#CTAG" and war_data["opponent"]["tag"] == "#OTAG"
    ok("official player/clan/war lookups normalize tags and preserve API payloads")

    # ── player pages ─────────────────────────────────────────────────────────
    import cogs.player as P
    P.get_player = AsyncMock(return_value=PLAYER)
    P.get_player_warhits = AsyncMock(return_value=WARHITS)
    P.get_player_join_leave = AsyncMock(return_value={"items": [
        {"clan": "#CTAG", "clan_name": "TestClan", "type": "join", "time": "2026-11-01T10:00:00"}]})
    pc = bot.get_cog("PlayerCog")
    for cb in ("player_p1", "player_p2", "player_p3", "player_history"):
        page = await pc.route_player(f"{cb}:#PTAG")
        check_page(page, cb)
    p1 = await pc.route_player("player_p1:#PTAG")
    assert p1.thumb_path and os.path.isfile(p1.thumb_path), "TH image missing"
    t = await pc.route_todo("todo_p:troops:#PTAG"); check_page(t, "todo")
    assert "Barbarian" in t.text
    for cat in ("heroes", "spells", "siege", "pets"):
        check_page(await pc.route_todo(f"todo_p:{cat}:#PTAG"), f"todo {cat}")
    text = pc._audit_text(PLAYER, 16, "#PTAG", {})
    assert "Rush Audit" in text and "Verdict" in text
    ok("/player (4 pages), /todo (5 categories), /audit")

    P.get_player = AsyncMock(return_value={"error": "Not Found. Tag might be incorrect."})
    pc.cache = type(pc.cache)(1)
    err = await pc.route_player("player_p1:#NOPE")
    assert err.text.startswith("❌") and err.markup is None
    ok("player lookup error → friendly page")

    # ── clan pages ───────────────────────────────────────────────────────────
    import cogs.clan as C
    C.get_clan = AsyncMock(return_value=CLAN)
    C.get_player = AsyncMock(return_value=PLAYER)
    C.get_clan_war = AsyncMock(return_value=war("inWar"))
    C.get_previous_wars = AsyncMock(return_value={"items": [war("warEnded"), war("warEnded")]})
    cc = bot.get_cog("ClanCog")
    for cb in ("clan_p1:#CTAG", "clan_p2:#CTAG", "clan_members:#CTAG:1"):
        e = check_page(await cc.route_clan(cb), cb)
    for s in ("trophies", "th", "donations", "role", "xplevel"):
        check_page(await cc.route_sorted(f"clansort:{s}:#CTAG"), s)
    page = await cc._clanwar_page("#CTAG"); check_page(page, "clanwar live")
    for v in ("home", "missed", "3star", "stars", "attacks"):
        check_page(await cc.route_war(f"cwar_a:{v}:#CTAG:live:0"), f"war {v}")
    C.get_clan_war = AsyncMock(return_value={"state": "notInWar", "clan": {"tag": "#CTAG"}})
    page = await cc._clanwar_page("#CTAG"); check_page(page, "clanwar history")
    check_page(await cc.route_war("cwar_a:home:#CTAG:0:0"), "war history analytics")
    C.get_clan_war = AsyncMock(return_value={"error": "x"})
    C.get_clan = AsyncMock(return_value={**CLAN, "isWarLogPublic": False})
    page = await cc._clanwar_page("#CTAG"); assert "PRIVATE" in page.text
    ok("/clan, /clansorted, /clanwar (live/history/private) + analytics")

    # ── CWL with coc.py-style objects ───────────────────────────────────────
    def cmem(p, n, atk):
        return SimpleNamespace(tag=f"#{p}{n}", name=f"{p}{n}", town_hall=16, map_position=n,
                               attacks=[SimpleNamespace(stars=2, destruction=88, order=n, defender_tag=f"#O{n}")] if atk else [])
    side = lambda tag, name, p, atk: SimpleNamespace(tag=tag, name=name, stars=5, destruction=77.5,
                                                    members=[cmem(p, i, atk) for i in range(1, 4)])
    cwl_war = SimpleNamespace(clan=side("#CTAG", "TestClan", "C", True), opponent=side("#OTAG", "Enemy", "O", False),
                              state="inWar", team_size=3, attacks_per_member=1,
                              start_time=SimpleNamespace(time=None), end_time=SimpleNamespace(time=None))
    group = SimpleNamespace(season="2026-11", rounds=[["#W1"], ["#0"]],
                            clans=[SimpleNamespace(tag="#CTAG", name="TestClan", level=15),
                                   SimpleNamespace(tag="#OTAG", name="Enemy", level=14)])
    bot.coc = SimpleNamespace(get_league_group=AsyncMock(return_value=group), get_league_war=AsyncMock(return_value=cwl_war))
    for v in ("round", "overview", "missed", "all_members", "leaderboard", "attacks"):
        check_page(await cc.route_cwl(f"cwl_r:{v}:#CTAG:0"), f"cwl {v}")
    assert "hasn't started" in (await cc.route_cwl("cwl_r:round:#CTAG:1")).text
    ok("/cwl (round, overview, missed, roster, leaderboard, attacks, not-started)")

    # ── capital ──────────────────────────────────────────────────────────────
    import cogs.capital as K
    K.get_player = AsyncMock(return_value=PLAYER)
    res = await K._fetch_member_capital_stats("#M1", None)
    assert res["all_time"] and res["donated"] == 9000
    K.get_player = AsyncMock(return_value={"error": "x"})
    res = await K._fetch_member_capital_stats("#M1", None)
    assert res["error"] and res["donated"] == 0
    from core.builders import _build_cap_page
    stats = [{"name": f"M{i}", "tag": f"#M{i}", "donated": 100 * (25 - i), "raided": 5} for i in range(25)]
    t1, m1 = _build_cap_page(stats, "TestClan", "Season", 25, 0, "#CTAG")
    assert m1 and "Next" in m1.rows[0][0].label
    ok("/cap_stats (official all-time stats and pagination)")

    # ── loot ────────────────────────────────────────────────────────────────
    import cogs.loot as L
    info = L.get_current_loot_info()
    assert info and 0 <= info["index"] <= 10, info
    ok(f"/loot forecaster (current index {info['index']}/10)")

    # ── scraper diff ─────────────────────────────────────────────────────────
    import cogs.scraper as S
    d = S.compute_diff({"A": {"1": 5}, "B": {"1": 1}}, {"A": {"1": 6}, "C": {"1": 1}})
    assert len(d) == 3
    ok("/scrap diff logic")

    # ── NavView: simulate a real button click ───────────────────────────────
    async def router(cb):
        return Page(f"clicked {cb}", None)
    view = NavView(router, p1.markup, owner_id=7, color=COMMAND_COLORS["player"])
    assert len(view.children) == 2
    inter = MagicMock(); inter.response.defer = AsyncMock(); inter.edit_original_response = AsyncMock()
    await view.children[0].callback(inter)
    inter.edit_original_response.assert_awaited_once()
    emb = inter.edit_original_response.await_args.kwargs["embed"]
    assert emb.description.startswith("clicked player_history")
    assert emb.color.value == COMMAND_COLORS["player"]
    stranger = MagicMock(); stranger.user.id = 8; stranger.response.send_message = AsyncMock()
    assert await view.interaction_check(stranger) is False
    owner = MagicMock(); owner.user.id = 7
    assert await view.interaction_check(owner) is True
    ok("NavView: click edits message; non-owner blocked")

    sent = MagicMock(); sent.followup.send = AsyncMock(return_value=MagicMock()); sent.user.id = 7
    sent.command = SimpleNamespace(name="player", parent=None)
    await send_page(sent, p1, router)
    kw = sent.followup.send.await_args.kwargs
    assert isinstance(kw["file"], discord.File) and kw["view"] and kw["embed"].thumbnail.url.startswith("attachment://")
    assert kw["embed"].color.value == COMMAND_COLORS["player"]
    assert kw["view"].color == COMMAND_COLORS["player"]
    assert COMMAND_COLORS["player"] != COMMAND_COLORS["clan"]
    reminders_setup = SimpleNamespace(
        command=SimpleNamespace(name="setup", parent=SimpleNamespace(name="reminders", parent=None)))
    assert command_color(reminders_setup) == COMMAND_COLORS["reminders setup"]
    ok("send_page attaches TH image + view")

    # ── tracking scanner ────────────────────────────────────────────────────
    import cogs.tracking as T
    T.get_clan_war = AsyncMock(return_value={"state": "notInWar"})
    sent_msgs = []
    async def notify(ch, text, color=0): sent_msgs.append(text)
    bot.notify = notify
    tr = bot.get_cog("Tracking")
    mk = lambda tag, name, role: SimpleNamespace(tag=tag, name=name, role=role, town_hall=16, exp_level=100)
    clan_obj = SimpleNamespace(name="TestClan", members=[mk("#A", "Alice", "Member"), mk("#B", "Bob", "Elder")])
    bot.coc = SimpleNamespace(get_clan=AsyncMock(return_value=clan_obj))
    cfg = {"guild_id": 99, "channel_id": 5, "tracked_tag": "#CTAG", "notif_join_leave": True, "notif_war": True,
           "loot_enabled": True, "initiated_by": "t", "state": {"members": {}, "last_war_opponent": "", "last_war_attacks": []}}
    await tr._scan(cfg); assert cfg["state"]["members"] and not sent_msgs      # first run: silent snapshot
    clan_obj.members = [mk("#A", "Alice", "Elder"), mk("#C", "Carol", "Member")]  # B left, C joined, A promoted
    await tr._scan(cfg)
    bot.coc.get_clan.assert_any_await("#CTAG", lookup_cache=False)
    T.get_clan_war.assert_any_await("#CTAG", bot.coc, lookup_cache=False)
    joined = "\n".join(sent_msgs)
    assert "has left" in joined and "has joined" in joined and "promoted" in joined, joined
    sent_msgs.clear()
    T.get_clan_war = AsyncMock(return_value=war("preparation", atk=False))
    await tr._scan(cfg); assert any("War Found" in m for m in sent_msgs)
    sent_msgs.clear()
    T.get_clan_war = AsyncMock(return_value=war("inWar"))
    await tr._scan(cfg); assert sum("War Attack" in m for m in sent_msgs) == 3
    sent_msgs.clear(); await tr._scan(cfg); assert not sent_msgs                 # no duplicate attack posts
    T.get_clan_war = AsyncMock(return_value=war("warEnded"))
    await tr._scan(cfg); assert any("VICTORY" in m for m in sent_msgs)
    ok("tracker: first-run snapshot, join/leave/promote, war found, attack feed (no dupes), result")

    # ══ Phase 0 + 1: migrations, accounts, verification, batch fetch, autocomplete ══
    import aiosqlite
    import coc
    import cogs.general as G
    from core.autocomplete import build_choices, linked_tag_choices

    # migration: an old-schema DB upgrades once, keeps data, newest link stays the default
    old_path = os.path.join(tempfile.mkdtemp(), "old.db")
    async with aiosqlite.connect(old_path) as raw:
        await raw.execute("CREATE TABLE user_tags (discord_id INTEGER NOT NULL, tag TEXT NOT NULL, entity_type TEXT "
                          "NOT NULL CHECK (entity_type IN ('player','clan')), PRIMARY KEY (discord_id, tag))")
        for row in [(1, "#OLD1", "player"), (1, "#OLD2", "player"), (1, "#OC", "clan"), (2, "#OTHER", "player")]:
            await raw.execute("INSERT INTO user_tags VALUES (?,?,?)", row)
        await raw.commit()
    saved_path, db.DB_PATH = db.DB_PATH, old_path
    try:
        await db.init_db(); await db.init_db()                       # second run must be a no-op
        assert await db.get_linked_account(1, "player") == "#OLD2"
        assert await db.get_linked_account(1, "clan") == "#OC"
        assert [a["is_primary"] for a in await db.get_linked_accounts(1, "player")] == [True, False]
        assert await db.get_linked_account(2, "player") == "#OTHER"
        async with aiosqlite.connect(old_path) as raw:
            async with raw.execute("SELECT version FROM schema_version") as cur:
                assert await cur.fetchall() == [(len(db.MIGRATIONS),)]
    finally:
        db.DB_PATH = saved_path
    ok("migration: old DB upgraded once, data kept, newest link became primary")

    await db.link_account(1, "#BBB", "player", make_primary=True)
    assert await db.get_linked_account(1, "player") == "#BBB"
    accts = await db.get_linked_accounts(1, "player")
    assert [a["tag"] for a in accts] == ["#BBB", "#AAA"] and accts[1]["label"] == "Alpha"
    await db.link_account(10, "#V1", "player", verified=True)
    again = await db.link_account(10, "#V1", "player")                # re-link keeps badge + primary
    assert again["is_verified"] and again["is_primary"] and not again["new"]
    try:
        await db.link_account(11, "#V1", "player"); raise AssertionError("verified tag was linkable")
    except db.LinkError:
        pass
    await db.link_account(11, "#V1", "player", force=True)           # owner /adminlink bypass
    await db.link_account(11, "#V1", "player", verified=True)        # newest proof of ownership wins
    assert not (await db.get_linked_accounts(10, "player"))[0]["is_verified"]
    assert (await db.get_linked_accounts(11, "player"))[0]["is_verified"]
    for tag in ("#X1", "#X2", "#X3"):
        await db.link_account(12, tag, "player")
    assert await db.set_primary(12, "#X3") and await db.get_linked_account(12, "player") == "#X3"
    assert not await db.set_primary(12, "#NOPE")
    assert await db.unlink_account(12, "#X3") and await db.get_linked_account(12, "player") == "#X1"
    assert not await db.unlink_account(12, "#X3")
    for i in range(db.MAX_LINKED_PER_TYPE):
        await db.link_account(13, f"#L{i}", "player")
    try:
        await db.link_account(13, "#LX", "player"); raise AssertionError("limit not enforced")
    except db.LinkError:
        pass
    await db.link_account(13, "#L0", "player")                       # re-linking an existing one is fine
    await db.link_account(13, "#CL", "clan")                         # the limit is per type
    ok("accounts db: primary, verified exclusivity, force, set_primary, unlink promotion, limit")

    # /link flow with mocked API
    general = bot.get_cog("General")
    G.get_player = AsyncMock(return_value={"name": "Tester", "townHallLevel": 16, "expLevel": 200})
    G.verify_player_token = AsyncMock(return_value={"verified": True})
    text = await general._link(20, "#T1", token="abc")
    assert "verified" in text and "primary" in text
    G.verify_player_token.assert_awaited_once()
    assert (await db.get_linked_accounts(20, "player"))[0]["is_verified"]
    text = await general._link(20, "#T2")                             # alt: not primary
    assert "linked" in text and "/accounts" in text and await db.get_linked_account(20, "player") == "#T1"
    text = await general._link(20, "#T2", make_primary=True)
    assert await db.get_linked_account(20, "player") == "#T2"
    G.verify_player_token = AsyncMock(return_value={"verified": False})
    text = await general._link(21, "#T3", token="wrong")
    assert text.startswith("❌") and await db.get_linked_account(21, "player") is None   # nothing linked
    G.verify_player_token = AsyncMock(return_value={"error": "Clash of Clans is under maintenance."})
    assert (await general._link(21, "#T3", token="x")).startswith("❌")
    G.get_player = AsyncMock(return_value={"error": "Player not found. Check the tag and try again."})
    assert "only work with player tags" in await general._link(21, "#CLANTAG", token="x")
    G.get_clan = AsyncMock(return_value={"name": "TestClan", "clanLevel": 15, "memberList": []})
    assert "Clan **TestClan**" in await general._link(21, "#CLANTAG")
    G.get_player = AsyncMock(return_value={"name": "Tester", "townHallLevel": 16, "expLevel": 200})
    assert "already **verified**" in await general._link(22, "#T1")   # verified by user 20 → blocked
    assert "linked" in await general._link(22, "#T1", force=True)    # owner bypass
    ok("/link: token verified/refused, alt not primary, clan, verified-elsewhere guard")

    # coc_api: verify_player_token adapter and batch fetch
    class FakeCoc:
        def __init__(self, result=None, exc=None): self.result, self.exc, self.calls = result, exc, []
        async def verify_player_token(self, tag, token):
            self.calls.append((tag, token))
            if self.exc: raise self.exc
            return self.result
    fc = FakeCoc(True)
    assert await A.verify_player_token("t1", " tok ", fc) == {"verified": True} and fc.calls == [("#T1", "tok")]
    assert await A.verify_player_token("t1", "x", FakeCoc(False)) == {"verified": False}
    assert "not found" in (await A.verify_player_token("t1", "x", FakeCoc(exc=coc.NotFound("gone"))))["error"].lower()
    assert "maintenance" in (await A.verify_player_token("t1", "x", FakeCoc(exc=coc.Maintenance("m"))))["error"].lower()
    assert "error" in await A.verify_player_token("t1", "   ", fc)
    assert "error" in await A.verify_player_token("t1", "x", None)
    ok("verify_player_token adapter (match, mismatch, not found, maintenance, empty, no client)")

    orig_get_player, calls, inflight, peak = A.get_player, [], [0], [0]
    async def fake_get_player(tag, client=None):
        calls.append(tag); inflight[0] += 1; peak[0] = max(peak[0], inflight[0])
        await asyncio.sleep(0); inflight[0] -= 1
        if tag == "#BAD": return {"error": "Player not found."}
        if tag == "#BOOM": raise RuntimeError("boom")
        return {"tag": tag, "name": tag[1:]}
    A.get_player = fake_get_player
    A._PLAYER_CACHE.clear()
    try:
        res = await A.get_players_batch(["#a1", "a1", " ", "#bad", "#boom", "#c3", "#d4", "#e5"], None, batch_size=2)
        assert list(res) == ["#A1", "#BAD", "#BOOM", "#C3", "#D4", "#E5"]
        assert res["#BAD"]["error"] and "boom" in res["#BOOM"]["error"] and res["#C3"]["name"] == "C3"
        assert len(calls) == 6 and peak[0] <= 2, (len(calls), peak)       # deduped + batched
        calls.clear()
        await A.get_players_batch(["#a1", "#bad"], None)
        assert calls == ["#BAD"]                                          # success cached, error retried
        calls.clear()
        await A.get_players_batch(["#a1"], None, ttl=0)
        assert calls == ["#A1"]                                           # ttl=0 bypasses the cache
    finally:
        A.get_player = orig_get_player
        A._PLAYER_CACHE.clear()
    ok("get_players_batch: dedupe, batching limit, failures isolated, cache rules")

    # autocomplete
    rows = [{"tag": "#AAA", "entity_type": "player", "is_primary": True, "is_verified": True, "label": "Alpha"},
            {"tag": "#BBB", "entity_type": "player", "is_primary": False, "is_verified": False, "label": None}]
    ch = build_choices(rows, "")
    assert [c.value for c in ch] == ["#AAA", "#BBB"] and ch[0].name.startswith("★ ✔ Alpha")
    assert [c.value for c in build_choices(rows, "alp")] == ["#AAA"]
    assert [c.value for c in build_choices(rows, "#bb")] == ["#BBB"]
    assert len(build_choices(rows * 20, "")) == 25
    fake_i = SimpleNamespace(user=SimpleNamespace(id=1))
    assert [c.value for c in await linked_tag_choices(fake_i, "", "player")] == ["#BBB", "#AAA"]
    assert [c.value for c in await linked_tag_choices(fake_i, "", "clan")] == ["#CCC"]
    for cmd in ("player", "todo", "audit", "clan", "clansorted", "clanwar", "cwl", "cap_stats"):
        assert bot.tree.get_command(cmd)._params["tag"].autocomplete is not None, cmd
    ok("autocomplete: filter, marks, 25 cap, per-type lookup, wired on all 8 tag commands")

    # /accounts view + dropdown actions
    G.get_players_batch = AsyncMock(return_value={"#BBB": {"name": "Beta", "townHallLevel": 15},
                                                   "#AAA": {"error": "boom"}})
    G.get_clan = AsyncMock(return_value={"name": "TestClan", "clanLevel": 15})
    user = SimpleNamespace(id=1, display_name="Tester", display_avatar=SimpleNamespace(url="https://x/a.png"))
    page, view = await general._accounts_view(user, manage=True)
    assert "★" in page.text and "Beta" in page.text and "unable to fetch" in page.text and "TestClan" in page.text
    assert view is not None and len(view.children) == 2
    page_ro, view_ro = await general._accounts_view(user, manage=False)
    assert view_ro is None
    assert (await db.get_linked_accounts(1, "player"))[0]["label"] == "Beta"      # label cache refreshed
    edits = []
    async def edit_original_response(**kw): edits.append(kw); return SimpleNamespace()
    inter = SimpleNamespace(user=user, response=SimpleNamespace(defer=AsyncMock()),
                            edit_original_response=edit_original_response)
    prim_sel = view.children[0]; prim_sel._values = ["#AAA"]
    await prim_sel.callback(inter)
    assert await db.get_linked_account(1, "player") == "#AAA" and edits
    unlink_sel = view.children[1]; unlink_sel._values = ["#AAA"]
    await unlink_sel.callback(inter)
    assert await db.get_linked_account(1, "player") == "#BBB"                     # promoted after unlinking primary
    stranger = SimpleNamespace(user=SimpleNamespace(id=999), response=SimpleNamespace(send_message=AsyncMock()))
    assert await view.interaction_check(stranger) is False
    stranger.response.send_message.assert_awaited_once()
    ok("/accounts: view, read-only mode, switch primary, unlink + promote, non-owner blocked")

    # TH19 asset
    from PIL import Image
    th19 = os.path.join(config.TH_IMAGE_DIR, "TownHall_19.png")
    assert os.path.isfile(th19)
    with Image.open(th19) as im19:
        assert im19.size == (512, 512)
    assert P.th_image(19) == th19
    ok("TownHall_19.png present (512x512)")


    # ══ Phases 2-5: cards, war preference, reminders, activity, army + bases ══
    import io
    import json
    from datetime import datetime, timedelta, timezone
    import aiosqlite
    from discord import app_commands as ac
    from PIL import Image

    def fake_inter(user_id=1, guild_id=100, admin=False, channel=None):
        sent = []
        async def followup_send(*a, **kw):
            sent.append({**kw, **({"content": a[0]} if a else {})})
            return SimpleNamespace(edit=AsyncMock())
        user = SimpleNamespace(id=user_id, display_name="U", display_avatar=SimpleNamespace(url="https://x/a.png"),
                               guild_permissions=SimpleNamespace(manage_guild=admin))
        resp = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), send_modal=AsyncMock(),
                               edit_message=AsyncMock(), is_done=lambda: False)
        guild = SimpleNamespace(me=SimpleNamespace(), id=guild_id)
        return SimpleNamespace(user=user, guild_id=guild_id, guild=guild, channel=channel, response=resp,
                               followup=SimpleNamespace(send=followup_send), sent=sent, message=None,
                               edit_original_response=AsyncMock())

    def text_of(inter):
        e = inter.sent[-1]["embed"]
        return e.description or ""

    # ── /progress + /poster ──────────────────────────────────────────────────
    from core.progress import compute_progress
    from core.image_cards import render_poster_card, render_progress_card
    prog = compute_progress(PLAYER, {})
    keys = [c["key"] for c in prog["categories"]]
    assert keys == ["heroes", "equipment", "troops", "spells", "siege", "pets"], keys
    troops_cat = next(c for c in prog["categories"] if c["key"] == "troops")
    assert troops_cat["units"] == 1, "super troops must be excluded"
    assert next(c for c in prog["categories"] if c["key"] == "equipment")["max_levels"] == 27
    assert 0 < prog["overall_pct"] <= 100 and all(0 <= c["pct"] <= 100 for c in prog["categories"])
    over = compute_progress({**PLAYER, "heroes": [{"name": "Archer Queen", "level": 999, "maxLevel": 10, "village": "home"}]}, {})
    assert next(c for c in over["categories"] if c["key"] == "heroes")["pct"] <= 100       # never above 100%
    empty = compute_progress({"name": "New", "townHallLevel": 1}, {})
    assert empty["categories"] == [] and empty["overall_pct"] == 0
    for payload in (prog, empty, {**prog, "name": "N" * 80, "clan": "C" * 80}):
        png = render_progress_card(payload, os.path.join(config.TH_IMAGE_DIR, "TownHall_16.png"))
        im = Image.open(io.BytesIO(png)); assert png[:8] == b"\x89PNG\r\n\x1a\n" and im.size[0] == 1000 and im.size[1] > 300
    for p in (PLAYER, {"name": "New"}, {**PLAYER, "heroes": [], "heroEquipment": [], "clan": None}):
        im = Image.open(io.BytesIO(render_poster_card(p, None))); assert im.size == (1000, 620)
    import cogs.cards as K
    K.get_player = AsyncMock(return_value=PLAYER)
    cards = bot.get_cog("CardsCog")
    for cmd in (cards.progress, cards.poster):
        inter = fake_inter()
        await cmd.callback(cards, inter, "#PTAG")
        f = inter.sent[-1]["file"]
        assert isinstance(f, discord.File) and f.filename in ("progress.png", "poster.png")
        with Image.open(f.fp) as fim:
            assert fim.size[0] == 1000
    K.get_player = AsyncMock(return_value={"error": "Player not found."})
    try:
        await cards.poster.callback(cards, fake_inter(), "#NOPE"); raise AssertionError("no error")
    except helpers.ApiError as e:
        assert "not found" in str(e)
    ok("/progress + /poster: maths (super excluded, cap 100%), PNG output, errors")

    # ── coc_api: current war (regular / CWL) + current raid wrappers ──────────
    class FakeWar:
        def __init__(self, raw, our_tag, is_cwl=False):
            self._raw_data, self.clan, self.is_cwl = raw, SimpleNamespace(tag=our_tag), is_cwl
    class FakeCocWar:
        def __init__(self, result=None, exc=None, raid=None): self.result, self.exc, self.raid = result, exc, raid
        async def get_current_war(self, tag):
            if self.exc: raise self.exc
            return self.result
        async def get_raid_log(self, tag, limit=1):
            if self.exc: raise self.exc
            return self.raid
    reg = {"state": "inWar", "clan": {"tag": "#OUR", "members": []}, "opponent": {"tag": "#THEM"}, "attacksPerMember": 2}
    w = await A.get_current_war_any("our", FakeCocWar(FakeWar(reg, "#OUR")))
    assert w["clan"]["tag"] == "#OUR" and w["isCwl"] is False and w["attacksPerMember"] == 2
    cwl_raw = {"state": "inWar", "clan": {"tag": "#THEM"}, "opponent": {"tag": "#OUR", "members": [{"tag": "#X"}]}}
    w = await A.get_current_war_any("#OUR", FakeCocWar(FakeWar(cwl_raw, "#OUR", is_cwl=True)))
    assert w["clan"]["tag"] == "#OUR" and w["opponent"]["tag"] == "#THEM" and w["isCwl"] and w["attacksPerMember"] == 1
    assert cwl_raw["clan"]["tag"] == "#THEM"                                              # the API payload isn't mutated
    assert (await A.get_current_war_any("#OUR", FakeCocWar(None)))["state"] == "notInWar"
    assert "not found" in (await A.get_current_war_any("#X", FakeCocWar(exc=coc.NotFound("x"))))["error"].lower()
    assert "maintenance" in (await A.get_current_war_any("#X", FakeCocWar(exc=coc.Maintenance("x"))))["error"].lower()
    assert "error" in await A.get_current_war_any("#X", FakeCocWar(exc=coc.PrivateWarLog("private"))) if hasattr(coc, "PrivateWarLog") else True
    assert "error" in await A.get_current_war_any("#X", None)
    raid_raw = {"state": "ongoing", "members": [{"tag": "#A", "attacks": 1}]}
    got = await A.get_current_raid("#X", FakeCocWar(raid=[SimpleNamespace(_raw_data=raid_raw)]))
    assert got == raid_raw and got is not raid_raw
    assert (await A.get_current_raid("#X", FakeCocWar(raid=[])))["state"] == "none"
    assert "maintenance" in (await A.get_current_raid("#X", FakeCocWar(exc=coc.Maintenance("m"))))["error"].lower()
    assert "error" in await A.get_current_raid("#X", None)
    ok("coc_api: current war (regular, CWL swap, none, errors) and current raid wrappers")

    # ── /waropt ──────────────────────────────────────────────────────────────
    from core.war_pref import format_war_preference, group_war_preference
    mem = [{"tag": "#A", "name": "Ann*", "townHallLevel": 16}, {"tag": "#B", "name": "Bob", "townHallLevel": 15},
           {"tag": "#C", "name": "Cy", "townHallLevel": 16}, {"tag": "#D", "name": "Di", "townHallLevel": 14}]
    pl = {"#A": {"warPreference": "in"}, "#B": {"warPreference": "out"}, "#C": {"error": "x"}, "#D": {"name": "Di"}}
    groups = group_war_preference(mem, pl)
    assert [e["tag"] for e in groups["in"]] == ["#A"] and [e["tag"] for e in groups["out"]] == ["#B"]
    assert sorted(e["tag"] for e in groups["unknown"]) == ["#C", "#D"]          # failed lookup / missing field
    txt = format_war_preference("My Clan", "#CT", groups)
    assert "Opted IN" in txt and "Opted OUT" in txt and "Unavailable" in txt and "Ann\\*" in txt and "**TH16** (1)" in txt
    C.get_clan = AsyncMock(return_value={**CLAN, "memberList": mem})
    C.get_players_batch = AsyncMock(return_value=pl)
    inter = fake_inter(); await cc.waropt.callback(cc, inter, "#CTAG")
    assert "Opted IN" in text_of(inter)
    C.get_players_batch.assert_awaited_once()
    assert C.get_players_batch.await_args.args[0] == ["#A", "#B", "#C", "#D"]
    C.get_clan = AsyncMock(return_value={"error": "Clan not found."})
    try:
        await cc.waropt.callback(cc, fake_inter(), "#CTAG"); raise AssertionError("no error")
    except helpers.ApiError:
        pass
    C.get_clan = AsyncMock(return_value=CLAN)
    ok("/waropt: grouping, unknown never guessed, escaping, one lookup per member")

    # ── reminder maths ───────────────────────────────────────────────────────
    from core import reminder_logic as R
    T = lambda *a: datetime(*a, tzinfo=timezone.utc)
    assert (R.war_tier(9000), R.war_tier(7000), R.war_tier(3000), R.war_tier(0), R.war_tier(-5)) == (None, 2, 1, None, None)
    war_inwar = {"state": "inWar", "endTime": "20261118T120000.000Z", "attacksPerMember": 2, "clan": {
        "name": "TestClan", "tag": "#C", "members": [
            {"tag": "#P1", "name": "A", "mapPosition": 1, "attacks": [{}]}, {"tag": "#P2", "name": "B", "mapPosition": 2,
             "attacks": [{}, {}]}, {"tag": "#P3", "name": "C", "mapPosition": 3}]}}
    wm = R.war_missing(war_inwar, T(2026, 11, 18, 11, 30))
    assert wm["remaining"] == 1800 and [(m["name"], m["left"]) for m in wm["members"]] == [("C", 2), ("A", 1)]
    assert R.war_missing({**war_inwar, "state": "preparation"}) is None and R.war_missing({"state": "notInWar"}) is None
    assert R.war_missing({**war_inwar, "attacksPerMember": 1}, T(2026, 11, 18, 11, 0))["members"][0]["left"] == 1   # CWL
    raid = {"state": "ongoing", "endTime": "20261116T070000.000Z", "members": [
        {"tag": "#A", "name": "a", "attacks": 5, "attackLimit": 5, "bonusAttackLimit": 1},
        {"tag": "#B", "name": "b", "attacks": 5, "attackLimit": 5, "bonusAttackLimit": 0},
        {"tag": "#X", "name": "left clan", "attacks": 0, "attackLimit": 5, "bonusAttackLimit": 0}]}
    rm = R.raid_missing(raid, [{"tag": "#A", "name": "a"}, {"tag": "#B", "name": "b"}, {"tag": "#C", "name": "c"}],
                        T(2026, 11, 16, 2))
    assert rm["remaining"] == 5 * 3600 and [(m["name"], m["left"], m["total"]) for m in rm["members"]] == [("c", 5, 5), ("a", 1, 6)]
    assert [m["name"] for m in R.raid_missing(raid, None, T(2026, 11, 16, 2))["members"]] == ["left clan", "a"]
    assert R.raid_missing({**raid, "state": "ended"}, []) is None
    assert R.games_window(T(2026, 11, 22, 7, 59)) is None and R.games_window(T(2026, 11, 22, 8))[2] == "2026-11"
    assert R.games_window(T(2026, 11, 28, 7, 59)) and R.games_window(T(2026, 11, 28, 8)) is None
    gm = R.games_missing({"#A": ("a", 5000), "#B": ("b", 1500), "#N": ("new", 10)}, {"#A": 1000, "#B": 1000})
    assert [(g["name"], g["earned"], g["left"]) for g in gm] == [("b", 500, 3500)]      # capped + no-baseline skipped
    assert R.games_points({"achievements": [{"name": "Games Champion", "value": 77}]}) == 77 and R.games_points({}) is None
    fm = R.format_missing([{"tag": "#A", "name": "a", "left": 1, "total": 2}, {"tag": "#B", "name": "b", "left": 2, "total": 2}], {"#A": 5})
    assert "<@5> (a)" in fm and "**b**" in fm and R.human_duration(5400) == "1h 30m" and R.human_duration(90) == "1m"
    ok("reminder maths: tiers, war/CWL allowance, raid bonus + absent members, games window/cap")

    # ── reminder + games + snapshot + base storage ───────────────────────────
    cfg1 = await db.upsert_reminder_config(100, "#C1", 555)
    assert cfg1["war_alerts"] and cfg1["raid_alerts"] and cfg1["games_alerts"]
    assert await db.set_reminder_toggle(100, "#C1", "raid", False)
    moved = await db.upsert_reminder_config(100, "#C1", 556)
    assert moved["channel_id"] == 556 and not moved["raid_alerts"]                 # move keeps toggles
    assert not await db.set_reminder_toggle(100, "#NOPE", "war", False)
    for i in range(2, db.MAX_REMINDER_CLANS_PER_GUILD + 1):
        await db.upsert_reminder_config(100, f"#C{i}", 556)
    try:
        await db.upsert_reminder_config(100, "#CX", 556); raise AssertionError("limit")
    except db.ConfigError:
        pass
    assert await db.delete_reminder_config(100, "#C5") and not await db.delete_reminder_config(100, "#C5")
    assert [c["clan_tag"] for c in await db.get_reminder_configs(100, "#C1")] == ["#C1"]
    assert await db.claim_reminder("k1") and not await db.claim_reminder("k1")
    await db.release_reminder("k1"); assert await db.claim_reminder("k1")
    async with aiosqlite.connect(db.DB_PATH) as raw:
        await raw.execute("UPDATE sent_reminders SET sent_at='2020-01-01T00:00:00Z' WHERE reminder_key='k1'")
        await raw.commit()
    assert await db.prune_reminders(14) == 1 and await db.claim_reminder("k1")
    await db.save_games_baselines("#G", "2026-11", {"#A": 5, "#B": 7}, True)
    assert await db.get_games_baselines("#G", "2026-11") == {"#A": 5, "#B": 7}
    ev = await db.get_games_event("#G", "2026-11"); assert ev["baseline_ok"] and ev["captured_at"]
    assert await db.get_games_event("#G", "2099-01") is None
    await db.link_account(61, "#SHARED", "player"); await db.link_account(62, "#SHARED", "player", verified=True)
    await db.link_account(63, "#SHARED", "player", force=True)
    assert (await db.linked_discord_ids(["#SHARED", "#NONE"]))["#SHARED"] == 62 and "#NONE" not in await db.linked_discord_ids(["#NONE"])
    assert await db.linked_discord_ids([]) == {}
    cfgg = await db.get_guild_config(101); cfgg.update(tracked_tag="#TRACKED", channel_id=1); await db.save_guild_config(cfgg)
    assert "#TRACKED" in await db.watched_clan_tags() and "#C1" in await db.watched_clan_tags()
    b1 = await db.add_base(100, 1, 15, "War", "https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AAAA", "n")
    try:
        await db.add_base(100, 2, 15, "War", "https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AAAA"); raise AssertionError
    except db.ConfigError as e:
        assert f"#{b1}" in str(e)
    assert await db.add_base(200, 2, 15, "War", "https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AAAA")  # other guild ok
    b2 = await db.add_base(100, 1, 14, "Farming", "https://link.clashofclans.com/en?action=OpenLayout&id=TH14%3AHV%3ABBB")
    assert await db.toggle_base_vote(100, b2, 5) == (1, True) and await db.toggle_base_vote(100, b2, 6) == (2, True)
    assert await db.toggle_base_vote(100, b2, 5) == (1, False) and await db.toggle_base_vote(100, 9999, 5) is None
    assert await db.toggle_base_vote(200, b2, 5) is None                                # other guild's base
    rows, total = await db.list_bases(100); assert total == 2 and rows[0]["base_id"] == b2          # most upvotes first
    assert (await db.list_bases(100, th_level=15))[1] == 1 and (await db.list_bases(100, category="Farming"))[1] == 1
    assert await db.get_auto_decode(100) is False
    await db.set_auto_decode(100, True); assert await db.get_auto_decode(100)
    assert not await db.delete_base(200, b2) and await db.delete_base(100, b2) and await db.get_base(100, b2) is None
    async with aiosqlite.connect(db.DB_PATH) as raw:
        async with raw.execute("SELECT COUNT(*) FROM base_votes WHERE base_id=?", (b2,)) as cur:
            assert (await cur.fetchone())[0] == 0                                        # votes removed with the base
        async with raw.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
            tables = {r[0] for r in await cur.fetchall()}
        async with raw.execute("SELECT version FROM schema_version") as cur:
            assert (await cur.fetchone())[0] == len(db.MIGRATIONS) == 4
    assert {"reminder_configs", "sent_reminders", "games_events", "games_baselines", "player_snapshots",
            "saved_bases", "base_votes", "guild_flags"} <= tables
    ok("storage: reminders, claim/release/prune, games baselines, verified-first mentions, bases + votes, migration 4")

    # ── reminders cog ────────────────────────────────────────────────────────
    import cogs.reminders as RM
    rem = bot.get_cog("RemindersCog")
    posts, fail = [], {"on": False}
    class FakeChannel:
        id = 555
        async def send(self, **kw):
            if fail["on"]:
                raise discord.Forbidden(SimpleNamespace(status=403, reason="no"), "missing access")
            posts.append(kw)
    chan = FakeChannel()
    bot.get_channel = lambda cid: chan
    await db.link_account(777, "#P3", "player")
    base_cfg = {"guild_id": 100, "clan_tag": "#WARC", "channel_id": 555, "war_alerts": True, "raid_alerts": False, "games_alerts": False}
    RM.get_current_war_any = AsyncMock(return_value=war_inwar)
    await rem.process_clan(base_cfg, {}, T(2026, 11, 18, 9, 0))            # 3h left: too early
    assert posts == []
    await rem.process_clan(base_cfg, {}, T(2026, 11, 18, 10, 30))          # 1h30m: the 2h reminder
    assert len(posts) == 1 and posts[0]["content"] == "<@777>" and "<@777> (C)" in posts[0]["embed"].description
    assert posts[0]["allowed_mentions"].users is True and posts[0]["allowed_mentions"].everyone is False
    await rem.process_clan(base_cfg, {}, T(2026, 11, 18, 10, 45)); assert len(posts) == 1          # no repeat
    await rem.process_clan(base_cfg, {}, T(2026, 11, 18, 11, 30)); assert len(posts) == 2          # the 1h reminder
    await rem.process_clan(base_cfg, {}, T(2026, 11, 18, 11, 45)); assert len(posts) == 2
    other_guild = {**base_cfg, "guild_id": 101}
    await rem.process_clan(other_guild, {}, T(2026, 11, 18, 11, 40)); assert len(posts) == 3       # each server gets its own
    cwl = {**war_inwar, "isCwl": True, "attacksPerMember": 1}
    RM.get_current_war_any = AsyncMock(return_value=cwl)
    await rem.process_clan({**base_cfg, "clan_tag": "#CWLC"}, {}, T(2026, 11, 18, 11, 30))
    assert "CWL war" in posts[-1]["embed"].title and "1/1 attacks left" in posts[-1]["embed"].description
    done = json.loads(json.dumps(war_inwar)); [m.__setitem__("attacks", [{}, {}]) for m in done["clan"]["members"]]
    RM.get_current_war_any = AsyncMock(return_value=done); n = len(posts)
    await rem.process_clan({**base_cfg, "clan_tag": "#DONEC"}, {}, T(2026, 11, 18, 11, 30)); assert len(posts) == n   # nobody missing
    RM.get_current_war_any = AsyncMock(return_value=war_inwar); fail["on"] = True; n = len(posts)
    await rem.process_clan({**base_cfg, "clan_tag": "#FAILC"}, {}, T(2026, 11, 18, 11, 30)); assert len(posts) == n
    fail["on"] = False
    await rem.process_clan({**base_cfg, "clan_tag": "#FAILC"}, {}, T(2026, 11, 18, 11, 40)); assert len(posts) == n + 1   # retried
    orig_send = rem._send
    async def boom(*a, **k): raise RuntimeError("unexpected")
    rem._send = boom
    try:
        await rem.process_clan({**base_cfg, "clan_tag": "#CRASHC"}, {}, T(2026, 11, 18, 11, 30)); raise AssertionError("no raise")
    except RuntimeError:
        pass
    rem._send = orig_send; n2 = len(posts)
    await rem.process_clan({**base_cfg, "clan_tag": "#CRASHC"}, {}, T(2026, 11, 18, 11, 35)); assert len(posts) == n2 + 1   # claim was released
    n = n + 1
    RM.get_current_war_any = AsyncMock(return_value={"error": "boom"})
    await rem.process_clan({**base_cfg, "clan_tag": "#ERRC"}, {}, T(2026, 11, 18, 11, 30)); assert len(posts) == n + 1
    ok("war reminders: tiers once each, per-server, linked ping, CWL, nobody-missing, failed post retried, API error")

    raid_cfg = {**base_cfg, "clan_tag": "#RAIDC", "war_alerts": False, "raid_alerts": True}
    RM.get_current_raid = AsyncMock(return_value=raid)
    RM.get_clan = AsyncMock(return_value={"name": "RC", "memberList": [{"tag": "#A", "name": "a"}, {"tag": "#C", "name": "c"}]})
    n = len(posts)
    await rem.process_clan(raid_cfg, {}, T(2026, 11, 15, 12)); assert len(posts) == n               # 19h left
    await rem.process_clan(raid_cfg, {}, T(2026, 11, 16, 2)); assert len(posts) == n + 1
    assert "**c**" in posts[-1]["embed"].description and "<@" not in (posts[-1]["content"] or "")
    await rem.process_clan(raid_cfg, {}, T(2026, 11, 16, 3)); assert len(posts) == n + 1
    RM.get_current_raid = AsyncMock(return_value={**raid, "state": "ended"})
    await rem.process_clan({**raid_cfg, "clan_tag": "#RAIDEND"}, {}, T(2026, 11, 16, 2)); assert len(posts) == n + 1
    ok("raid reminders: window, once, ended raid ignored")

    games_cfg = {**base_cfg, "clan_tag": "#GAMEC", "war_alerts": False, "games_alerts": True}
    mk = lambda pts: {"#P1": {"name": "A", "achievements": [{"name": "Games Champion", "value": pts[0]}]},
                      "#P2": {"name": "B", "achievements": [{"name": "Games Champion", "value": pts[1]}]},
                      "#P9": {"name": "Late joiner", "achievements": [{"name": "Games Champion", "value": 0}]}}
    RM.get_clan = AsyncMock(return_value={"name": "GC", "memberList": [{"tag": "#P1"}, {"tag": "#P2"}]})
    RM.get_players_batch = AsyncMock(side_effect=lambda tags, *a, **k: {t: d for t, d in mk((1000, 2000)).items() if t in tags})
    n = len(posts)
    await rem.process_clan(games_cfg, {}, T(2026, 11, 21, 12)); assert (await db.get_games_event("#GAMEC", "2026-11")) is None
    await rem.process_clan(games_cfg, {}, T(2026, 11, 22, 9))                    # 1h after start: baselines taken, trusted
    assert (await db.get_games_event("#GAMEC", "2026-11"))["baseline_ok"] and len(posts) == n
    RM.get_clan = AsyncMock(return_value={"name": "GC", "memberList": [{"tag": "#P1"}, {"tag": "#P2"}, {"tag": "#P9"}]})
    RM.get_players_batch = AsyncMock(side_effect=lambda tags, *a, **k: {t: d for t, d in mk((5000, 2500)).items() if t in tags})
    await rem.process_clan(games_cfg, {}, T(2026, 11, 27, 12)); assert len(posts) == n          # 20h left
    await rem.process_clan(games_cfg, {}, T(2026, 11, 28, 2)); assert len(posts) == n + 1       # 6h left
    body = posts[-1]["embed"].description
    assert "**B**" in body and "500/4,000" in body and "A" not in body.replace("**B**", "") and "Late joiner" not in body
    await rem.process_clan(games_cfg, {}, T(2026, 11, 28, 3)); assert len(posts) == n + 1
    late_cfg = {**games_cfg, "clan_tag": "#LATEC"}
    await rem.process_clan(late_cfg, {}, T(2026, 11, 22, 18))                    # bot started 10h late: baseline untrusted
    assert not (await db.get_games_event("#LATEC", "2026-11"))["baseline_ok"]
    await rem.process_clan(late_cfg, {}, T(2026, 11, 28, 2)); assert len(posts) == n + 1
    ok("clan games reminders: baseline at start, cap + late-joiner skipped, once, late baseline never pings")

    # /reminders and /missing-hits commands
    ch_perms = SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    textch = SimpleNamespace(id=900, mention="<#900>", permissions_for=lambda me: ch_perms)
    bot.coc = SimpleNamespace()
    RM.get_clan = AsyncMock(return_value={"name": "Setup Clan", "memberList": []})
    inter = fake_inter(admin=False, channel=textch)
    await rem.setup.callback(rem, inter, "#SETC", None)
    inter.response.send_message.assert_awaited_once()                                    # non-admin refused
    assert await db.get_reminder_configs(100, "#SETC") == []
    inter = fake_inter(user_id=1, admin=True, channel=textch)
    await rem.setup.callback(rem, inter, "#setc", None)
    cfg = (await db.get_reminder_configs(100, "#SETC"))[0]
    assert cfg["channel_id"] == 900 and "Setup Clan" in text_of(inter) and "<#900>" in text_of(inter)
    await rem.toggle.callback(rem, fake_inter(admin=True), ac.Choice(name="War", value="war"), None, "#SETC")
    assert not (await db.get_reminder_configs(100, "#SETC"))[0]["war_alerts"]
    await rem.toggle.callback(rem, fake_inter(admin=True), ac.Choice(name="War", value="war"), True, "#SETC")
    assert (await db.get_reminder_configs(100, "#SETC"))[0]["war_alerts"]
    for bad in ("#NOTSET",):
        try:
            await rem.toggle.callback(rem, fake_inter(admin=True), ac.Choice(name="War", value="war"), None, bad); raise AssertionError
        except RM.NavError as e:
            assert "no reminders" in str(e).lower()
    inter = fake_inter(); await rem.status.callback(rem, inter)
    assert "#SETC" in text_of(inter) and "<#900>" in text_of(inter)
    inter = fake_inter(guild_id=555); await rem.status.callback(rem, inter); assert "No reminders" in text_of(inter)
    try:
        await rem.remove.callback(rem, fake_inter(admin=True, guild_id=555), None); raise AssertionError
    except RM.NavError:
        pass
    await rem.remove.callback(rem, fake_inter(admin=True), "#SETC")
    assert await db.get_reminder_configs(100, "#SETC") == []
    RM.get_current_war_any = AsyncMock(return_value=war_inwar); RM.get_current_raid = AsyncMock(return_value={"state": "none"})
    inter = fake_inter(); await rem.missing_hits.callback(rem, inter, "#C", None)
    t = text_of(inter); assert "ends in" in t and "<@777>" in t and "no" in t.lower() and "Raid weekend" in t
    inter = fake_inter(); await rem.missing_hits.callback(rem, inter, "#C", ac.Choice(name="War", value="war"))
    assert "Raid weekend" not in text_of(inter)
    RM.get_current_war_any = AsyncMock(return_value={"error": "This clan's war log is private."})
    inter = fake_inter(); await rem.missing_hits.callback(rem, inter, "#C", ac.Choice(name="War", value="war"))
    assert "private" in text_of(inter)
    bot.coc = None
    ok("/reminders setup/toggle/status/remove (admin gate, limits) + /missing-hits")

    # ── activity maths + cog ─────────────────────────────────────────────────
    from core import activity_logic as AL
    from core.seasons import season_id
    def pl_(tag="#M1", gold=100, stars=10, don=50, got=25, clan="#AC", name="Mem1"):
        return {"tag": tag, "name": name, "townHallLevel": 16, "expLevel": 100, "warStars": stars, "donations": don,
                "donationsReceived": got, "clan": {"tag": clan}, "achievements": [
                    {"name": "Gold Grab", "value": gold}, {"name": "Elixir Escapade", "value": 5},
                    {"name": "Heroic Heist", "value": 6}, {"name": "Aggressive Capitalism", "value": 7}]}
    n0 = T(2026, 11, 10, 12)
    r0 = AL.observe(None, pl_(), "2026-11", n0)
    assert r0["last_active_at"] is None and r0["gold_baseline"] == 100 and r0["first_seen_at"] == "2026-11-10T12:00:00Z"
    r1 = AL.observe(r0, pl_(), "2026-11", n0 + timedelta(hours=1)); assert r1["last_active_at"] is None   # nothing changed
    r2 = AL.observe(r1, pl_(gold=900), "2026-11", n0 + timedelta(hours=2))
    assert r2["last_active_at"] == "2026-11-10T14:00:00Z" and r2["gold_baseline"] == 100 and AL.season_gain(r2, "gold") == 800
    r3 = AL.observe(r2, pl_(gold=900, don=60, got=40), "2026-11", n0 + timedelta(hours=3))     # donations alone: not activity
    assert r3["last_active_at"] == r2["last_active_at"] and r3["donations"] == 60
    r4 = AL.observe(r3, pl_(gold=950, don=0, got=0), "2026-12", n0 + timedelta(days=30))        # new season
    assert r4["last_active_at"] == r2["last_active_at"] and r4["gold_baseline"] == 950 and AL.season_gain(r4, "gold") == 0
    assert AL.donation_ratio({"donations": 10, "donations_received": 0}) == 10 and AL.donation_ratio({"donations": 3, "donations_received": 2}) == 1.5
    assert AL.last_seen_label(r2, n0 + timedelta(hours=5)) == "3h ago" and "none since tracking began (1d)" in AL.last_seen_label(r0, n0 + timedelta(days=1, hours=2))
    seen_old = {**r0, "player_tag": "#O", "last_active_at": "2026-11-01T00:00:00Z", "first_seen_at": "2026-10-01T00:00:00Z"}
    order = AL.sort_by_activity([r0, seen_old, r2])
    assert [r["last_active_at"] for r in order] == ["2026-11-10T14:00:00Z", "2026-11-01T00:00:00Z", None]
    assert AL.is_inactive(seen_old, n0) and not AL.is_inactive(r2, n0) and AL.is_inactive(r0, n0 + timedelta(days=8))
    assert AL.fingerprint(pl_()) == AL.fingerprint(pl_(don=999, got=999)) != AL.fingerprint(pl_(stars=11))
    assert season_id(T(2026, 11, 30, 4)) == "2026-11" and season_id(T(2026, 11, 30, 5)) == "2026-12"
    ok("activity maths: first sight, activity detection, donations ignored, season rollover, ordering")

    import cogs.activity as AC
    act = bot.get_cog("ActivityCog")
    members = [{"tag": "#M1", "name": "Mem1"}, {"tag": "#M2", "name": "Mem2"}]
    AC.get_clan = AsyncMock(return_value={"name": "ActClan", "memberList": members})
    state_pl = {"#M1": pl_(), "#M2": pl_("#M2", gold=10, stars=1, don=900, got=100, name="Mem2")}
    AC.get_players_batch = AsyncMock(side_effect=lambda tags, *a, **k: dict(state_pl))
    rows = await act.poll_clan("#AC", None, n0)
    snaps = await db.get_snapshots(["#M1", "#M2"]); assert len(rows) == 2 and snaps["#M1"]["last_active_at"] is None
    state_pl["#M1"] = pl_(gold=500)
    await act.poll_clan("#AC", None, n0 + timedelta(hours=1))
    assert (await db.get_snapshots(["#M1"]))["#M1"]["last_active_at"] == "2026-11-10T13:00:00Z"
    AC.get_players_batch = AsyncMock(return_value={"#M1": pl_(), "#M2": {"error": "x"}})
    assert len(await act.poll_clan("#AC", None, n0 + timedelta(hours=2))) == 1                 # one failure doesn't break the poll
    AC.get_clan = AsyncMock(return_value={"error": "Clan not found."})
    try:
        await act.poll_clan("#AC"); raise AssertionError
    except helpers.ApiError:
        pass
    AC.get_clan = AsyncMock(return_value={"name": "ActClan", "memberList": members})
    AC.get_players_batch = AsyncMock(side_effect=lambda tags, *a, **k: dict(state_pl))
    bot.coc = SimpleNamespace()
    act._last_poll.clear()
    inter = fake_inter(); await act.activity.callback(act, inter, "#AC")
    t = text_of(inter); assert "ActClan" in t and "Mem1" in t and "Mem2" in t and "watch list" in t
    cfgg = await db.get_guild_config(102); cfgg.update(tracked_tag="#AC", channel_id=1); await db.save_guild_config(cfgg)
    inter = fake_inter(); await act.activity.callback(act, inter, "#AC"); assert "watch list" not in text_of(inter)
    for key in AL.STATS:
        inter = fake_inter(); await act.leaderboard.callback(act, inter, "#AC", ac.Choice(name=key, value=key))
        t = text_of(inter); assert "1." in t and "2." in t and AL.STATS[key][0] in t, key
    inter = fake_inter(); await act.leaderboard.callback(act, inter, "#AC", ac.Choice(name="d", value="donations"))
    assert text_of(inter).index("Mem2") < text_of(inter).index("Mem1")                          # 900 donated > 50
    bot.coc = None
    ok("activity cog: poll + persistence, failure isolation, /activity, /leaderboard (all 7 stats), watch-list note")

    # ── army links + decoding ────────────────────────────────────────────────
    from core import army as AR
    good = "https://link.clashofclans.com/en?action=CopyArmy&army=h0p1e5_6-1p2e7u10x0-5x1-20x23s3x9-1x2i1x4d2x1"
    cli = AR.decoder_client()
    info = AR.decode_army(cli, good)
    assert info["troop_space"] == 10 * 1 + 5 * 1 + 20 * 10 and info["spell_space"] == 3 * 1 + 1 * 2
    assert info["cc_troop_space"] == 2 and info["cc_spell_space"] == 4 and info["siege_count"] == 0
    assert [h["hero"] for h in info["heroes"]] == ["Barbarian King", "Archer Queen"] and info["heroes"][0]["pet"] == "Mighty Yak"
    siege_id = None
    for i in range(0, 120):
        try:
            t0 = cli.parse_army_link(f"https://link.clashofclans.com/en?action=CopyArmy&army=u1x{i}").troops
        except Exception:
            continue
        if t0 and t0[0][0].is_siege_machine:
            siege_id = i; break
    assert siege_id is not None
    sinfo = AR.decode_army(cli, f"https://link.clashofclans.com/en?action=CopyArmy&army=u2x{siege_id}-10x0")
    assert sinfo["siege_count"] == 2 and sinfo["troops"] and not any(n == sinfo["siege"][0][1] for _, n, _ in sinfo["troops"])
    fields = dict(AR.army_fields(info)); assert any(k.startswith("Troops · 215") for k in fields) and "Clan Castle" in fields
    for bad in ("https://evil.com/en?action=CopyArmy&army=u1x1", "http://link.clashofclans.com/en?action=CopyArmy&army=u1x1",
                "https://link.clashofclans.com.evil.com/en?action=CopyArmy&army=u1x1",
                "https://user@link.clashofclans.com/en?action=CopyArmy&army=u1x1",
                "https://link.clashofclans.com:8443/en?action=CopyArmy&army=u1x1",
                "https://link.clashofclans.com/evil/path?action=CopyArmy&army=u1x1",
                "https://link.clashofclans.com/en?action=CopyArmy&action=OpenLayout&army=u1x1",
                "https://link.clashofclans.com/en?action=CopyArmy&army=u1x1&army=u2x2",
                "https://link.clashofclans.com/en?action=CopyArmy&army=" + "u" * 900,
                "https://link.clashofclans.com/en?action=CopyArmy&army=u1x1%0Aevil", "not a url"):
        assert AR.army_link(bad) is None, bad
    for bad in ("u999x999", "zzz", "u1x1-999x5", "u0x0", "u401x0", "u10x0s3x999", "i5x999", "h999", "h0p999", "h0e999"):
        bad = "https://link.clashofclans.com/en?action=CopyArmy&army=" + bad
        try:
            AR.decode_army(cli, bad); raise AssertionError(f"decoded {bad}")
        except ValueError:
            pass
    lay = "https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AAAAAXYZ"
    assert AR.layout_link(lay) == ("https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AAAAAXYZ", 15)
    assert AR.layout_link(lay.replace("TH15", "BH9"))[1] is None and AR.layout_link(lay + "&id=2") is None
    assert AR.layout_link("https://link.clashofclans.com/en?action=OpenLayout&id=" + "A" * 2000) is None
    assert AR.layout_link("https://link.clashofclans.com/en?action=OpenLayout&id=<script>") is None
    assert AR.link_kind(good) == "army" and AR.link_kind(lay) == "layout" and AR.link_kind("https://link.clashofclans.com/en?action=Other") is None
    assert AR.extract_links(f"look {good}, and {lay}! also {good} https://evil.com/x") == [good, lay]
    assert len(AR.extract_links(" ".join(f"https://link.clashofclans.com/en?action=CopyArmy&army=u1x{i}" for i in range(9)))) == 3
    assert AR.normalise_category(" cwl ") == "CWL" and AR.parse_th("TH15") == 15 and AR.parse_th(" 9 ") == 9
    for bad in ("0", "26", "x", ""):
        try:
            AR.parse_th(bad); raise AssertionError(bad)
        except ValueError:
            pass
    try:
        AR.normalise_category("Fun"); raise AssertionError
    except ValueError:
        pass
    ok("army: decoder (space, siege split, CC, heroes), strict link validation, layout parsing, input rules")

    # ── army cog: /army, menu, auto reader, /bases ───────────────────────────
    import cogs.army as AM
    am = bot.get_cog("ArmyCog")
    inter = fake_inter(); await am.army.callback(am, inter, good)
    e = inter.sent[-1]["embed"]; v = inter.sent[-1]["view"]
    assert "215 troop space" in e.title and any(f.name == "Heroes" for f in e.fields)
    assert v.children[0].url == AR.army_link(good) and v.children[0].label == "Copy Army"
    inter = fake_inter(); await am.army.callback(am, inter, "https://evil.com/x"); assert "valid" in text_of(inter)
    class Msg:
        def __init__(self, content, guild=True, bot_author=False):
            self.content, self.author = content, SimpleNamespace(bot=bot_author)
            self.guild = SimpleNamespace(id=100, me=SimpleNamespace()) if guild else None
            self.channel = SimpleNamespace(id=1, permissions_for=lambda me: SimpleNamespace(send_messages=True, embed_links=True))
            self.replies = []
        async def reply(self, **kw): self.replies.append(kw)
    inter = fake_inter(); await am.read_link_menu(inter, Msg("no link")); inter.response.send_message.assert_awaited_once()
    inter = fake_inter(); await am.read_link_menu(inter, Msg(f"{good} {lay}"))
    assert len(inter.sent) == 2 and isinstance(inter.sent[1]["view"], AM.SaveBaseView)
    config.ENABLE_MESSAGE_CONTENT = True
    await db.set_auto_decode(100, True)
    m = Msg(f"check {good}"); await am.on_message(m)
    assert len(m.replies) == 1 and m.replies[0]["mention_author"] is False and m.replies[0]["allowed_mentions"].users is False
    am._last_reply.clear()
    m = Msg(f"see {lay}"); await am.on_message(m); assert isinstance(m.replies[0]["view"], AM.SaveBaseView)
    for case in (Msg(good, bot_author=True), Msg(good, guild=False), Msg("nothing here"), Msg("https://link.clashofclans.com/en?action=CopyArmy&army=u999x999")):
        am._last_reply.clear(); await am.on_message(case); assert case.replies == []
    am._last_reply.clear(); m = Msg(good); await am.on_message(m); await am.on_message(m); assert len(m.replies) == 1       # per-channel throttle
    await db.set_auto_decode(100, False); am._last_reply.clear(); m = Msg(good); await am.on_message(m); assert m.replies == []
    await db.set_auto_decode(100, True); config.ENABLE_MESSAGE_CONTENT = False; am._last_reply.clear()
    m = Msg(good); await am.on_message(m); assert m.replies == []
    inter = fake_inter(admin=False); await am.autodecode.callback(am, inter, True); assert "Manage Server" in inter.response.send_message.await_args.args[0]
    inter = fake_inter(admin=True); await am.autodecode.callback(am, inter, False)
    assert not await db.get_auto_decode(100)
    inter = fake_inter(admin=True); await am.autodecode.callback(am, inter, True)
    assert await db.get_auto_decode(100) and "not enabled message reading" in inter.response.send_message.await_args.args[0]
    assert botmod._intents().message_content is False
    config.ENABLE_MESSAGE_CONTENT = True; assert botmod._intents().message_content is True; config.ENABLE_MESSAGE_CONTENT = False
    ok("army cog: /army, context menu, auto reader (guild opt-in, bot/DM ignored, throttle, flag), intents switch")

    # SaveBaseModal + /bases browsing + save/delete
    layout = AR.layout_link(lay)
    def modal_for(cat, th, notes=""):
        mo = AM.SaveBaseModal(layout[0], layout[1]); mo.category._value, mo.th._value, mo.notes._value = cat, th, notes
        return mo
    assert modal_for("x", "15").th.default == "15"
    m_ = modal_for("x", "15")
    assert len(m_.title) <= 45 and all(len(i.label) <= 45 for i in (m_.category, m_.th, m_.notes))      # Discord limits
    inter = fake_inter(user_id=7, guild_id=300)
    await modal_for("farming", "TH15", "my note").on_submit(inter); assert "Saved as base" in inter.response.send_message.await_args.args[0]
    inter = fake_inter(user_id=7, guild_id=300); await modal_for("farming", "15").on_submit(inter)
    assert "already saved" in inter.response.send_message.await_args.args[0]
    for cat, th in (("nope", "15"), ("war", "abc"), ("war", "99")):
        inter = fake_inter(user_id=7, guild_id=300); await modal_for(cat, th).on_submit(inter)
        assert inter.response.send_message.await_args.args[0].startswith("❌")
    sv = AM.SaveBaseView(layout[0], layout[1]); dm = fake_inter(guild_id=None)
    await sv.save.callback(dm); dm.response.send_message.assert_awaited_once()
    gi = fake_inter(guild_id=300); await sv.save.callback(gi); gi.response.send_modal.assert_awaited_once()
    for i in range(1, 12):                                                    # 12 bases -> 2 pages
        await db.add_base(300, 7, 15 if i % 2 else 14, "War", f"https://link.clashofclans.com/en?action=OpenLayout&id=TH15%3AWB%3AN{i}", f"note {i}")
    inter = fake_inter(user_id=7, guild_id=300); await am.bases.callback(am, inter, None, None)
    e, v = inter.sent[-1]["embed"], inter.sent[-1]["view"]
    assert "Page 1/2" in e.description and "12 layouts" in e.description and len(v.children) == 4
    assert v.children[0].disabled and not v.children[1].disabled
    nxt = fake_inter(user_id=7, guild_id=300); nxt.message = SimpleNamespace(); await v.children[1].callback(nxt)
    e2, v2 = nxt.response.edit_message.await_args.kwargs["embed"], nxt.response.edit_message.await_args.kwargs["view"]
    assert "Page 2/2" in e2.description and v2.children[1].disabled
    stranger = fake_inter(user_id=8, guild_id=300); await v.children[1].callback(stranger)
    assert "Only the person" in stranger.response.send_message.await_args.args[0] and not stranger.response.edit_message.await_args
    top = v.children[2].options[0].value
    v.children[2]._values = [top]; op = fake_inter(user_id=8, guild_id=300); await v.children[2].callback(op)
    assert "action=OpenLayout" in op.response.send_message.await_args.args[0] and op.response.send_message.await_args.kwargs["ephemeral"]
    v.children[3]._values = [top]; vt = fake_inter(user_id=8, guild_id=300); vt.message = SimpleNamespace()
    await v.children[3].callback(vt); assert "Upvoted" in vt.sent[-1]["content"] and "(now 1)" in vt.sent[-1]["content"]
    vt2 = fake_inter(user_id=8, guild_id=300); vt2.message = SimpleNamespace(); await v.children[3].callback(vt2)
    assert "removed" in vt2.sent[-1]["content"] and "(now 0)" in vt2.sent[-1]["content"]
    inter = fake_inter(guild_id=300); await am.bases.callback(am, inter, 14, ac.Choice(name="War", value="War"))
    assert "TH14 · War" in inter.sent[-1]["embed"].description and "5 layouts" in inter.sent[-1]["embed"].description
    inter = fake_inter(guild_id=301); await am.bases.callback(am, inter, None, None)
    assert "No layouts saved yet" in inter.sent[-1]["embed"].description and len(inter.sent[-1]["view"].children) == 2
    inter = fake_inter(user_id=9, guild_id=300)
    await am.basesave.callback(am, inter, lay.replace("TH15", "BH9") + "Q", ac.Choice(name="War", value="War"), None, None)
    assert "Town Hall" in inter.response.send_message.await_args.args[0]
    inter = fake_inter(user_id=9, guild_id=300)
    await am.basesave.callback(am, inter, lay.replace("TH15", "BH9") + "Q", ac.Choice(name="War", value="War"), 13, "x" * 500)
    new_id = int(inter.response.send_message.await_args.args[0].split("#")[1].split("*")[0])
    assert (await db.get_base(300, new_id))["th_level"] == 13 and len((await db.get_base(300, new_id))["notes"]) == 300
    inter = fake_inter(user_id=9, guild_id=300); await am.basesave.callback(am, inter, "https://evil.com", ac.Choice(name="War", value="War"), 15, None)
    assert "valid" in inter.response.send_message.await_args.args[0]
    inter = fake_inter(user_id=11, guild_id=300); await am.basedelete.callback(am, inter, new_id)
    assert "Only the person" in inter.response.send_message.await_args.args[0] and await db.get_base(300, new_id)
    inter = fake_inter(user_id=9, guild_id=300); await am.basedelete.callback(am, inter, new_id); assert await db.get_base(300, new_id) is None
    inter = fake_inter(user_id=9, guild_id=300); await am.basedelete.callback(am, inter, new_id); assert "no base" in inter.response.send_message.await_args.args[0]
    adm_target = (await db.list_bases(300))[0][0]["base_id"]
    inter = fake_inter(user_id=11, guild_id=300, admin=True); await am.basedelete.callback(am, inter, adm_target)
    assert await db.get_base(300, adm_target) is None
    ok("bases: modal validation + duplicates, paging (owner only), open/upvote toggle, filters, save/delete permissions")

    # ── global error handler + command definitions ───────────────────────────
    inter = fake_inter(); inter.command = SimpleNamespace(name="x"); inter.response.is_done = lambda: True     # after defer
    await bot.tree.on_error(inter, ac.CommandInvokeError(SimpleNamespace(name="x"), helpers.ApiError("Clan not found.")))
    assert inter.sent[-1]["content"] == "❌ Clan not found." and inter.sent[-1]["ephemeral"]
    inter = fake_inter(); inter.command = SimpleNamespace(name="x")                                           # before any reply
    await bot.tree.on_error(inter, ac.CommandInvokeError(SimpleNamespace(name="x"), db.LinkError("Too many.")))
    assert inter.response.send_message.await_args.args[0] == "❌ Too many."
    logging.disable(logging.CRITICAL)
    inter = fake_inter(); inter.command = SimpleNamespace(name="x"); inter.response.is_done = lambda: True
    await bot.tree.on_error(inter, ac.CommandInvokeError(SimpleNamespace(name="x"), RuntimeError("secret detail")))
    logging.disable(logging.NOTSET)
    assert "secret" not in inter.sent[-1]["content"] and "Something went wrong" in inter.sent[-1]["content"]
    import re as _re
    payloads = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
    assert len(payloads) == len(bot.tree.get_commands())
    chat = [p for p in payloads if p["type"] == 1]
    assert len(chat) <= 100 and all(_re.fullmatch(r"[a-z0-9_-]{1,32}", p["name"]) for p in chat), [p["name"] for p in chat]
    def walk(p):
        assert len(p["description"]) <= 100 if p["type"] == 1 else True, p["name"]
        opts = p.get("options", [])
        assert len(opts) <= 25 and len({o["name"] for o in opts}) == len(opts), p["name"]
        required_seen_optional = False
        for o in opts:
            if o["type"] in (1, 2):
                walk(o); continue
            assert len(o["description"]) <= 100 and _re.fullmatch(r"[a-z0-9_-]{1,32}", o["name"]), o["name"]
            assert len(o.get("choices", [])) <= 25
            required_seen_optional = required_seen_optional or not o.get("required")
            assert not (o.get("required") and required_seen_optional), f"required after optional in /{p['name']}"
    [walk(p) for p in chat]
    menus = [p for p in payloads if p["type"] == 3]
    assert [m["name"] for m in menus] == ["Read Clash link"] and len(menus[0]["name"]) <= 32
    for cmd, param in ((cc.waropt, "clan"), (act.activity, "clan"), (act.leaderboard, "clan"), (rem.missing_hits, "clan"),
                       (cards.progress, "tag"), (cards.poster, "tag"), (rem.toggle, "clan"), (rem.remove, "clan")):
        assert cmd._params[param].autocomplete is not None, cmd.name
    assert rem.reminders.default_permissions.manage_guild and rem.reminders.guild_only
    assert len(rem.reminders.commands) == 4 and {c.name for c in rem.reminders.commands} == {"setup", "toggle", "status", "remove"}
    ok(f"error handler (user errors shown, internals hidden) + all {len(chat)} commands valid for Discord (names, limits, options)")

    # ── cross-checks against coc.py's own game data ──────────────────────────
    with open(os.path.join(os.path.dirname(__import__("coc").__file__), "static", "static_data.json")) as fh:
        sd = json.load(fh)
    known = set()
    def collect(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str): known.add(o["name"])
            [collect(v) for v in o.values()]
        elif isinstance(o, list):
            [collect(v) for v in o]
    collect(sd)
    from core.image_cards import HEROES_SHORT
    from core.progress import SUPER_TROOPS
    assert set(AL.ACTIVITY_ACHIEVEMENTS) <= known, set(AL.ACTIVITY_ACHIEVEMENTS) - known
    assert set(HEROES_SHORT) <= known and set(SUPER_TROOPS) <= known
    ok("names cross-checked against coc.py game data (achievements, heroes, super troops)")

    for cog in list(bot.cogs.values()):
        for attr in ("scan_loop", "notify_loop", "check", "weekly", "reminder_loop", "poll_loop"):
            if hasattr(cog, attr):
                getattr(cog, attr).cancel()
    print("\nALL SMOKE TESTS PASSED")


asyncio.run(main())
