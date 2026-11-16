"""Offline smoke tests: no Discord or Clash API access needed (all network calls are mocked).

Run:  python tests/test_smoke.py
"""
import asyncio
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
from core.nav import NavView, Page, send_page  # noqa: E402
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
    await db.link_account(1, "#AAA", "player")
    await db.link_account(1, "#BBB", "player")
    await db.link_account(1, "#CCC", "clan")
    assert await db.get_linked_account(1, "player") == "#BBB"      # newest link is the default
    assert await db.get_all_linked_tags(1, "player") == ["#AAA", "#BBB"]
    assert await db.get_linked_account(2, "player") is None
    cfg = await db.get_guild_config(99)
    cfg.update(tracked_tag="#X", channel_id=5); cfg["state"]["members"] = {"#1": {"name": "a"}}
    await db.save_guild_config(cfg)
    again = await db.get_guild_config(99)
    assert again["tracked_tag"] == "#X" and again["state"]["members"] == {"#1": {"name": "a"}}
    assert len(await db.all_guild_configs()) == 1
    ok("database (links, newest-default, guild config round-trip)")

    # ── helpers ──────────────────────────────────────────────────────────────
    assert helpers.normalize_tag(" yy8pqy28 ") == "#YY8PQY28"
    assert helpers.get_scraped_th_max("Barbarian King", 16) > 0
    assert await helpers.resolve_tag(1, None, "player") == "#BBB"
    assert await helpers.resolve_tag(1, "abc", "clan") == "#ABC"
    assert await helpers.resolve_tag(2, None, "player") is None
    ok("helpers (tags, scraped max levels, resolve_tag)")

    # ── bot + cogs load, commands register ──────────────────────────────────
    import bot as botmod
    bot = botmod.OttoBot()
    bot.coc = None
    _never = asyncio.Event()
    bot.wait_until_ready = _never.wait   # background loops stay parked; we call their logic directly
    for name in botmod.COGS:
        await bot.load_extension(f"cogs.{name}")
    names = sorted(c.name for c in bot.tree.get_commands())
    expected = sorted(["help", "link", "adminlink", "profile", "player", "todo", "audit", "clan", "clansorted",
                       "clanwar", "cwl", "cap_stats", "loot", "clantrack", "deltrack", "trackinfo", "setchannel", "scrap"])
    assert names == expected, f"commands differ: {set(names) ^ set(expected)}"
    ok(f"all {len(names)} slash commands register")

    # ── player pages ─────────────────────────────────────────────────────────
    import cogs.player as P
    P.get_player = AsyncMock(return_value=PLAYER)
    P.get_player_stats = AsyncMock(return_value=STATS)
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
    K.get_player_stats = AsyncMock(return_value=STATS)
    res = await K._fetch_member_capital_stats("#M1", SEASON)
    assert res == {"donated": 1000, "raided": 500}
    K.get_player_stats = AsyncMock(return_value={"error": "x"}); K.get_player = AsyncMock(return_value=PLAYER)
    res = await K._fetch_member_capital_stats("#M1", SEASON)
    assert res["all_time"] and res["donated"] == 9000
    from core.builders import _build_cap_page
    stats = [{"name": f"M{i}", "tag": f"#M{i}", "donated": 100 * (25 - i), "raided": 5} for i in range(25)]
    t1, m1 = _build_cap_page(stats, "TestClan", "Season", 25, 0, "#CTAG")
    assert m1 and "Next" in m1.rows[0][0].label
    ok("/cap_stats (season stats, all-time fallback, pagination)")

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
    view = NavView(router, p1.markup, owner_id=7)
    assert len(view.children) == 2
    inter = MagicMock(); inter.response.defer = AsyncMock(); inter.edit_original_response = AsyncMock()
    await view.children[0].callback(inter)
    inter.edit_original_response.assert_awaited_once()
    emb = inter.edit_original_response.await_args.kwargs["embed"]
    assert emb.description.startswith("clicked player_history")
    stranger = MagicMock(); stranger.user.id = 8; stranger.response.send_message = AsyncMock()
    assert await view.interaction_check(stranger) is False
    owner = MagicMock(); owner.user.id = 7
    assert await view.interaction_check(owner) is True
    ok("NavView: click edits message; non-owner blocked")

    sent = MagicMock(); sent.followup.send = AsyncMock(return_value=MagicMock()); sent.user.id = 7
    await send_page(sent, p1, router)
    kw = sent.followup.send.await_args.kwargs
    assert isinstance(kw["file"], discord.File) and kw["view"] and kw["embed"].thumbnail.url.startswith("attachment://")
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

    for cog in list(bot.cogs.values()):
        for attr in ("scan_loop", "notify_loop", "check", "weekly"):
            if hasattr(cog, attr):
                getattr(cog, attr).cancel()
    print("\nALL SMOKE TESTS PASSED")


asyncio.run(main())
