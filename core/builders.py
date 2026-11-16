"""Pure text/markup builders ported from the Telegram bot (no Telegram dependency).

Text uses Discord-compatible Markdown. Button rows use core.nav.Btn / Markup.
"""
from collections import Counter
from datetime import datetime, timezone

from core.helpers import E, fmt_number, current_season, get_scraped_th_max
from core.nav import Btn, Markup, NOOP

CAP_PER_PAGE = 10

def _build_player_page1(data: dict, stats: dict, warhits: dict, tag: str) -> str:
    """Build page 1: Season stats + All-time stats."""
    name = data.get('name', 'Unknown')
    th = data.get('townHallLevel', '?')
    exp = data.get('expLevel', '?')
    trophies = data.get('trophies', 0)
    best_trophies = data.get('bestTrophies', 0)
    builder_trophies = data.get('builderBaseTrophies', 0)
    best_builder = data.get('bestBuilderBaseTrophies', 0)
    war_stars = data.get('warStars', 0)
    clan_info = data.get('clan', {})
    clan_name = clan_info.get('name', 'None') if clan_info else 'None'
    role = data.get('role', 'none').capitalize() if data.get('role') else 'None'
    league = data.get('league', {}).get('name', 'Unranked') if data.get('league') else 'Unranked'

    # ── Current season values from the official player profile ──
    atk_wins = data.get('attackWins', 0)
    def_wins = data.get('defenseWins', 0)
    donated = data.get('donations', 0)
    received = data.get('donationsReceived', 0)
    don_ratio = round(donated / received, 1) if received > 0 else float(donated)

    # ── Optional ClashKing seasonal stats (not currently provided) ──
    season = current_season()
    stats_capital = stats.get('capital', {})
    stats_clan_games = stats.get('clan_games', {})

    # Current-season Clan Capital and Clan Games totals are not in the official profile.
    event_stats_available = bool(stats_capital or stats_clan_games)
    cg_donated = stats_capital.get(season, {}).get('donated', 0) if stats_capital else 0
    cg_raided = stats_capital.get(season, {}).get('raided', 0) if stats_capital else 0
    cg_points = stats_clan_games.get(season, 0) if stats_clan_games else 0
    if isinstance(cg_points, dict):
        cg_points = cg_points.get('points', 0)

    # ── War stats from /player/{tag}/warhits ──
    war_items = warhits.get('items', []) if isinstance(warhits, dict) else []
    total_atks = len(war_items)
    total_war_stars = sum(h.get('stars', 0) for h in war_items)
    avg_stars = round(total_war_stars / total_atks, 1) if total_atks > 0 else 0.0
    hits = sum(1 for h in war_items if h.get('stars', 0) >= 2)
    hitrate = round(hits / total_atks * 100, 1) if total_atks > 0 else 0.0

    # ── Super Troops ──
    active_supers = [
        t['name'] for t in data.get('troops', [])
        if t.get('superTroopIsActive') and t.get('village') == 'home'
    ]
    super_text = ""
    if active_supers:
        super_text = "\n✨ **Super Troops:**\n" + "".join(f"  • {s}\n" for s in active_supers)

    # ── All-time stats from achievements ──
    ach = {a['name']: a['value'] for a in data.get('achievements', [])}
    total_donated = ach.get('Friend in Need', 0)
    total_cg_points = ach.get('Games Champion', 0)
    total_cg_raided_raw = ach.get('Aggressive Capitalism', 0)
    total_cg_donated_raw = ach.get('Most Valuable Clanmate', 0)
    cwl_stars = ach.get('War League Legend', 0)

    clean_tag = tag.replace('#', '')
    p_link = f"https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=%23{clean_tag}"
    
    c_clean_tag = clan_info.get('tag', '').replace('#', '') if clan_info else ''
    c_link = f"https://link.clashofclans.com/en?action=OpenClanProfile&tag=%23{c_clean_tag}" if c_clean_tag else ""
    clan_name_str = f"[{clan_name}]({c_link})" if c_link else clan_name

    text = (
        f"{E['player']} **[{name}]({p_link})** | {E['th']} TH{th} | {E['level']} Lvl {exp}\n"
        f"{E['clan']} {clan_name_str}  •  {role}  •  {league}\n"
        f"`{tag}`\n"
        f"{'─' * 30}\n"
        f"\n📅 **Season Stats:**\n"
        f"{E['trophy']} Trophies: {fmt_number(trophies)}\n"
        f"{E['sword']} Attack Wins: {atk_wins}\n"
        f"{E['shield']} Defense Wins: {def_wins}\n"
        f"\n{E['war']} **War:**\n"
        f"{E['ratio']} Hitrate: {hitrate}%\n"
        f"{E['star']} Avg Stars: {avg_stars}\n"
        f"{E['star']} Total Stars: {total_war_stars}, {total_atks} atks\n"
        f"\n{E['troop']} **Donations:**\n"
        f"{E['donup']} Donated: {fmt_number(donated)}\n"
        f"{E['dondown']} Received: {fmt_number(received)}\n"
        f"{E['ratio']} Donation Ratio: {don_ratio}\n"
    )
    if event_stats_available:
        text += (
            f"\n🎉 **Event Stats:**\n"
            f"{E['gold']} CG Donated: {fmt_number(cg_donated)}\n"
            f"{E['raid']} CG Raided: {fmt_number(cg_raided)}\n"
            f"{E['games']} Clan Games: {fmt_number(cg_points)}\n"
        )
    else:
        text += "\n🎉 **Event Stats:** Not available from the current APIs.\n"
    text += super_text
    text += (
        f"\n{'─' * 30}\n"
        f"🏛️ **All Time Stats:**\n"
        f"Best: {E['trophy']}{fmt_number(best_trophies)} | {E['versus']}{fmt_number(best_builder)}\n"
        f"War: {E['star']}{fmt_number(war_stars)}\n"
        f"CWL: {E['cwl']}{fmt_number(cwl_stars)}\n"
        f"{E['troop']} Donos: {fmt_number(total_donated)}\n"
        f"{E['games']} Clan Games: {fmt_number(total_cg_points)}\n"
        f"{E['raid']} CG Raided: {fmt_number(total_cg_raided_raw)}\n"
        f"{E['gold']} CG Donated: {fmt_number(total_cg_donated_raw)}\n"
    )
    return text


def _build_player_page2(data: dict) -> str:
    """Build page 2: Troops, Siege Machines & Spells."""
    name = data.get('name', 'Unknown')
    th = data.get('townHallLevel', '?')

    troops_all = data.get('troops', [])
    spells_all = data.get('spells', [])

    # Home village troops (exclude super-troop duplicates)
    home_troops = [t for t in troops_all if t.get('village') == 'home' and 'Super' not in t.get('name','') and not t.get('name','').startswith('Super')]
    siege_machines = [t for t in troops_all if t.get('village') == 'home' and t.get('name') in [
        'Wall Wrecker','Battle Blimp','Stone Slammer','Siege Barracks','Log Launcher','Flame Flinger','Battle Drill'
    ]]
    # Remove sieges from home troops display
    siege_names = {s['name'] for s in siege_machines}
    home_troops = [t for t in home_troops if t['name'] not in siege_names]

    home_spells = [s for s in spells_all if s.get('village') == 'home']

    def troop_lines(items: list) -> str:
        if not items:
            return "  None\n"
        lines = ""
        for i, t in enumerate(items):
            lvl = t.get('level', '?')
            ml = t.get('maxLevel', '?')
            maxed = "✅" if lvl == ml else ""
            lines += f"  • {t.get('name')}: {lvl}/{ml} {maxed}\n"
            if len(lines) > 2000:
                lines += "  ...(trimmed)\n"
                break
        return lines

    text = (
        f"{E['th']} **{name} | TH{th} — Troops & Spells**\n"
        f"{'─' * 30}\n"
        f"\n{E['troop']} **Home Troops:**\n"
    )
    text += troop_lines(home_troops)

    if siege_machines:
        text += f"\n{E['siege']} **Siege Machines:**\n"
        text += troop_lines(siege_machines)

    text += f"\n{E['spell']} **Spells:**\n"
    text += troop_lines(home_spells)

    return text


def _build_player_page3(data: dict) -> str:
    """Build page 3: Heroes, Hero Equipment & Builder Base Heroes."""
    name = data.get('name', 'Unknown')
    th = data.get('townHallLevel', '?')
    th_int = th if isinstance(th, int) else 0

    heroes_all = data.get('heroes', [])
    equipment = data.get('heroEquipment', [])

    home_heroes = [h for h in heroes_all if h.get('village') == 'home']

    text = (
        f"{E['th']} **{name} | TH{th} — Heroes & Equipment**\n"
        f"{'─' * 30}\n"
        f"\n{E['hero']} **Heroes:**\n"
    )
    if home_heroes:
        for h in home_heroes:
            lvl = h.get('level', '?')
            hname = h.get('name', '')
            th_ml = get_scraped_th_max(hname, th_int) if th_int else 0
            ml = th_ml if th_ml else h.get('maxLevel', '?')
            maxed = "✅" if lvl == ml else ""
            text += f"  • {hname}: {lvl}/{ml} {maxed}\n"
    else:
        text += "  None\n"

    if equipment:
        text += f"\n🔮 **Hero Equipment:**\n"
        for e in equipment:
            lvl = e.get('level', '?')
            ml = e.get('maxLevel', '?')
            maxed = "✅" if lvl == ml else ""
            text += f"  • {e.get('name')}: {lvl}/{ml} {maxed}\n"

    # Builder base heroes
    bb_heroes = [h for h in heroes_all if h.get('village') == 'builderBase']
    if bb_heroes:
        text += f"\n🔨 **Builder Base Heroes:**\n"
        for h in bb_heroes:
            lvl = h.get('level', '?')
            ml = h.get('maxLevel', '?')
            text += f"  • {h.get('name')}: {lvl}/{ml}\n"

    return text


def _role_icon(role: str) -> str:
    return {"leader": "👑", "coLeader": "🥇", "admin": "🥈", "member": "🥉"}.get(role, "👤")


def _build_clan_page1(data: dict) -> str:
    """Build clan page 1: all clan details."""
    name = data.get('name', 'Unknown')
    tag  = data.get('tag', '?')
    lvl  = data.get('clanLevel', '?')
    members = data.get('members', 0)
    pts  = data.get('clanPoints', 0)
    bb_pts = data.get('clanBuilderBasePoints', 0)
    req_trophies = data.get('requiredTrophies', 0)
    req_th = data.get('requiredTownhallLevel', 1)
    location = data.get('location', {}).get('name', 'International') if data.get('location') else 'International'
    desc = (data.get('description') or 'No description.').strip()

    # War stats
    war_wins   = data.get('warWins', 0)
    war_streak = data.get('warWinStreak', 0)
    is_public  = data.get('isWarLogPublic', False)
    war_losses = data.get('warLosses', '?') if is_public else 'Hidden Log'
    war_freq   = data.get('warFrequency', '?').capitalize()

    # Leagues
    cwl_league = data.get('warLeague', {}).get('name', 'Unranked') if data.get('warLeague') else 'Unranked'
    cap_league = data.get('capitalLeague', {}).get('name', '') if data.get('capitalLeague') else ''
    cap_hall   = data.get('clanCapital', {}).get('capitalHallLevel', '?') if data.get('clanCapital') else '?'

    # Find leader from memberList
    leader_name = 'Unknown'
    for m in data.get('memberList', []):
        if m.get('role') == 'leader':
            leader_name = m.get('name', 'Unknown')
            break

    # Win ratio (only if war log public)
    if is_public:
        total_wars = war_wins + (data.get('warLosses', 0) + data.get('warTies', 0))
        ratio = f"{round(war_wins / total_wars * 100, 1)}%" if total_wars > 0 else "0%"
    else:
        ratio = "Hidden Log"

    clean_tag = tag.replace('#', '')
    c_link = f"https://link.clashofclans.com/en?action=OpenClanProfile&tag=%23{clean_tag}"

    text = (
        f"🛡️ **[{name}]({c_link})**\n"
        f"`{tag}`\n"
        f"{'─'*30}\n"
        f"🏆 {fmt_number(pts)} | 🏅 {fmt_number(bb_pts)}\n"
        f"Required: 🏆 {req_trophies}  •  🏯 TH{req_th}+\n"
        f"🌏 Location: {location}\n"
        f"\n"
        f"👑 Leader: {leader_name}\n"
        f"📈 Level: {lvl}\n"
        f"👥 Members: {members}/50\n"
        f"\n"
        f"🌟 CWL: {cwl_league}\n"
        f"🏛️ Capital Hall: Lv{cap_hall}  •  {cap_league}\n"
        f"⚔️ War Freq: {war_freq}\n"
        f"⬆️ Wars Won: {war_wins}\n"
        f"⬇️ Wars Lost: {war_losses}\n"
        f"🔥 War Streak: {war_streak}\n"
        f"📊 Win Ratio: {ratio}\n"
        f"\n"
        f"📖 *Description:*\n"
        f"_{desc}_\n"
    )
    return text


MEMBERS_PER_PAGE = 15


def _build_members_page(data: dict, page: int) -> tuple:
    """Build a paginated member page. Returns (caption_text, Markup)."""
    name     = data.get('name', 'Unknown')
    norm_tag = data.get('tag', '').strip().upper()
    all_members = sorted(data.get('memberList', []), key=lambda m: m.get('clanRank', 99))
    total        = len(all_members)
    total_pages  = max(1, (total + MEMBERS_PER_PAGE - 1) // MEMBERS_PER_PAGE)
    page         = max(0, min(page, total_pages - 1))

    start        = page * MEMBERS_PER_PAGE
    end          = min(start + MEMBERS_PER_PAGE, total)
    page_members = all_members[start:end]

    # ── Caption text ──────────────────────────────────────────────────────
    text = (
        f"👥 *{name} — Members ({total}/50)*\n"
        f"Page {page + 1}/{total_pages}  •  #{start + 1}–{end}\n"
        f"{'─' * 28}\n"
    )
    for m in page_members:
        rank  = m.get('clanRank', '?')
        icon  = _role_icon(m.get('role', 'member'))
        mname = m.get('name', 'Unknown')[:14]
        th    = m.get('townHallLevel', '?')
        troph = m.get('trophies', 0)
        mtag  = m.get('tag', '?')
        text += f"`{rank}.`{icon} *{mname}*  TH{th} 🏆{troph}\n`    {mtag}`\n"

    # ── Keyboard ──────────────────────────────────────────────────────────
    nav_row = []
    if page > 0:
        nav_row.append(Btn("◀️ Prev", cb=f"clan_members:{norm_tag}:{page - 1}"))
    nav_row.append(Btn(f"📄 {page + 1}/{total_pages}", cb=NOOP))
    if page < total_pages - 1:
        nav_row.append(Btn("▶️ Next", cb=f"clan_members:{norm_tag}:{page + 1}"))

    keyboard = [nav_row, [Btn("◀️ Clan Details", cb=f"clan_p1:{norm_tag}")]]
    return text, Markup(keyboard)

PET_LIST = [
    "L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn", "Frosty", "Diggy", 
    "Poison Lizard", "Phoenix", "Spirit Fox", "Angry Jelly", "Sneezy", "Greedy Raven"
]
SIEGE_LIST = [
    "Wall Wrecker", "Battle Blimp", "Stone Slammer", "Siege Barracks", 
    "Log Launcher", "Flame Flinger", "Battle Drill", "Troop Launcher", "Sky Wagon"
]

def _build_todo_page(data: dict, category: str, tag: str, th_max: dict = None) -> tuple:
    name = data.get('name', 'Unknown')
    th = data.get('townHallLevel', '?')
    if th_max is None:
        th_max = {}

    to_upgrade_heroes = []
    to_upgrade_troops = []
    to_upgrade_spells = []
    to_upgrade_siege = []
    to_upgrade_pets = []

    for h in data.get('heroes', []):
        if h.get('village') == 'home':
            hname = h.get('name', '')
            lvl = h.get('level', 0)
            th_int = th if isinstance(th, int) else 0
            ml = get_scraped_th_max(hname, th_int) or th_max.get(hname) or h.get('maxLevel', lvl)
            if lvl < ml:
                to_upgrade_heroes.append({'name': hname, 'level': lvl, 'maxLevel': ml})
            
    for t in data.get('troops', []):
        if t.get('village') == 'home':
            tname = t.get('name', '')
            lvl = t.get('level', 0)
            th_int = th if isinstance(th, int) else 0
            ml = get_scraped_th_max(tname, th_int) or th_max.get(tname) or t.get('maxLevel', lvl)
            
            if lvl < ml:
                item = {'name': tname, 'level': lvl, 'maxLevel': ml}
                if tname in SIEGE_LIST:
                    to_upgrade_siege.append(item)
                elif tname in PET_LIST:
                    to_upgrade_pets.append(item)
                else:
                    to_upgrade_troops.append(item)
            
    for s in data.get('spells', []):
        if s.get('village') == 'home':
            sname = s.get('name', '')
            lvl = s.get('level', 0)
            th_int = th if isinstance(th, int) else 0
            ml = get_scraped_th_max(sname, th_int) or th_max.get(sname) or s.get('maxLevel', lvl)
            if lvl < ml:
                to_upgrade_spells.append({'name': sname, 'level': lvl, 'maxLevel': ml})

    text = f"📋 **To-Do List for {name} (TH{th}):**\n\n"
    
    if category == "heroes":
        emoji = E.get('hero', '👑')
        items = to_upgrade_heroes
        title = "Heroes"
    elif category == "troops":
        emoji = E.get('troop', '🪖')
        items = to_upgrade_troops
        title = "Troops"
    elif category == "siege":
        emoji = E.get('siege', '🚜')
        items = to_upgrade_siege
        title = "Siege Machines"
    elif category == "pets":
        emoji = E.get('pet', '🐾')
        items = to_upgrade_pets
        title = "Hero Pets"
    else:
        category = "spells"
        emoji = E.get('spell', '🧪')
        items = to_upgrade_spells
        title = "Spells"
        
    if not items:
        text += f"🎉 **All {title} are maxed for TH{th}!**"
    else:
        text += f"{emoji} **{title} to Max for TH{th} ({len(items)}):**\n"
        for i in items:
            text += f" • {i.get('name')}: Lvl {i.get('level')} → {i.get('maxLevel')}\n"

    keyboard = [
        [
            Btn(f"{'✅ ' if category=='heroes' else ''}👑 Heroes", cb=f"todo_p:heroes:{tag}"),
            Btn(f"{'✅ ' if category=='troops' else ''}🪖 Troops", cb=f"todo_p:troops:{tag}"),
            Btn(f"{'✅ ' if category=='spells' else ''}🧪 Spells", cb=f"todo_p:spells:{tag}"),
        ],
        [
            Btn(f"{'✅ ' if category=='siege' else ''}🚜 Siege", cb=f"todo_p:siege:{tag}"),
            Btn(f"{'✅ ' if category=='pets' else ''}🐾 Pets", cb=f"todo_p:pets:{tag}"),
        ]
    ]

    return text, Markup(keyboard)

def _th_roster(members: list) -> str:
    """Build TH breakdown from war members list, e.g. 'TH16×5 | TH15×8'."""
    if not members:
        return ""
    if hasattr(members[0], 'town_hall'):
        th_counts = Counter(m.town_hall for m in members if getattr(m, 'town_hall', 0) > 0)
    else:
        th_counts = Counter(m.get('townhallLevel', 0) for m in members)
    parts = [f"TH{th}×{count}" for th, count in sorted(th_counts.items(), reverse=True) if th > 0]
    return "  " + " | ".join(parts) if parts else ""



def _parse_coc_time(ts: str) -> datetime | None:
    """Parse CoC API timestamp '20250501T120000.000Z' -> UTC datetime."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fmt_remaining(dt: datetime | None, state: str) -> str:
    """Return a human-readable time remaining string, or empty string."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff = dt - now
    total_sec = int(diff.total_seconds())
    if total_sec <= 0:
        return ""
    hours, rem = divmod(total_sec, 3600)
    minutes = rem // 60
    if hours >= 24:
        days = hours // 24
        t_str = f"{days}d {hours % 24}h"
    else:
        t_str = f"{hours}h {minutes}m"
        
    if state == 'preparation':
        return f"\n⏳ Preparation time left: *{t_str}*"
    else:
        return f"\n⏰ Remaining time: *{t_str}*"


def _cwar_analytics_markup(view: str, tag: str, war_index: str, current_page: int, total_pages: int):
    nav_row = []
    if current_page > 0:
        nav_row.append(Btn("◀️ Prev", cb=f"cwar_a:{view}:{tag}:{war_index}:{current_page-1}"))
    if current_page < total_pages - 1:
        nav_row.append(Btn("Next ▶️", cb=f"cwar_a:{view}:{tag}:{war_index}:{current_page+1}"))
        
    keyboard = []
    if nav_row:
        keyboard.append(nav_row)
        
    act_tag = tag.strip().upper()
    keyboard.extend([
        [
            Btn("❌ Missed", cb=f"cwar_a:missed:{act_tag}:{war_index}:0"),
            Btn("🌟 3-Stars", cb=f"cwar_a:3star:{act_tag}:{war_index}:0"),
            Btn("⭐ Stars", cb=f"cwar_a:stars:{act_tag}:{war_index}:0")
        ],
        [
            Btn("🗡️ All Attacks", cb=f"cwar_a:attacks:{act_tag}:{war_index}:0"),
            Btn("◀️ War Overview", cb=f"cwar_a:home:{act_tag}:{war_index}:0")
        ]
    ])
    return Markup(keyboard)

def _clansorted_markup(tag: str):
    return Markup([
        [
            Btn("🏆 Trophies", cb=f"clansort:trophies:{tag}"),
            Btn("🏯 Town Hall", cb=f"clansort:th:{tag}"),
            Btn("🔼 Donations", cb=f"clansort:donations:{tag}")
        ],
        [
            Btn("👑 Role", cb=f"clansort:role:{tag}"),
            Btn("🎖️ XP Level", cb=f"clansort:xplevel:{tag}")
        ]
    ])

def _cwl_round_markup(tag: str, round_idx: int, total_rounds: int, view: str = "round") -> Markup:
    """Navigation keyboard for CWL rounds."""
    keyboard = []
    
    # Pagination for rounds
    nav = []
    if round_idx > 0:
        nav.append(Btn("◀️ Prev Round", cb=f"cwl_r:{view}:{tag}:{round_idx - 1}"))
    if round_idx < total_rounds - 1:
        nav.append(Btn("Next Round ▶️", cb=f"cwl_r:{view}:{tag}:{round_idx + 1}"))
    if nav:
        keyboard.append(nav)

    # Overview Pages
    keyboard.append([
        Btn("🏆 Leaderboard", cb=f"cwl_r:leaderboard:{tag}:{round_idx}")
    ])
    keyboard.append([
        Btn("❌ Missed Hits", cb=f"cwl_r:missed:{tag}:{round_idx}")
    ])
    keyboard.append([
        Btn("👥 Members roster", cb=f"cwl_r:all_members:{tag}:{round_idx}")
    ])
    if view != "round" and view != "overview":
        keyboard.append([Btn("◀️ Back to Round", cb=f"cwl_r:round:{tag}:{round_idx}")])
        
    return Markup(keyboard)


def _cwl_overview_text(group, clan_tag: str) -> str:
    """Build CWL group overview: season, participating clans, round info."""
    season = group.season if group else 'Unknown Season'
    clans  = group.clans if group else []
    rounds = group.rounds if group else []
    total_rounds = len(rounds)
    completed = sum(1 for r in rounds if any(wt != "#0" for wt in r))

    text = (
        f"🌟 **Clan War League — {season}**\n"
        f"{'─' * 30}\n"
        f"📅 Rounds: {completed}/{total_rounds} completed\n"
        f"👥 Participating Clans ({len(clans)}):\n"
    )
    for i, c in enumerate(clans):
        ctag  = c.tag
        cname = c.name
        clvl  = c.level
        icon  = "🏆" if ctag.upper() == clan_tag.upper() else "🛡️"
        text += f"  {icon} `{i+1}.` **{cname}** (Lvl {clvl}) `{ctag}`\n"
    return text



def _build_cap_page(member_stats: list, clan_name: str, data_label: str, total: int, page: int, clan_tag: str) -> tuple:
    """Build a single page of cap_stats output."""
    contributors = [m for m in member_stats if m["donated"] > 0]
    zero_donors = [m for m in member_stats if m["donated"] == 0]
    total_pages = max(1, -(-len(contributors) // CAP_PER_PAGE))  # ceil division

    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0

    start = page * CAP_PER_PAGE
    end = start + CAP_PER_PAGE
    page_members = contributors[start:end]

    medals = ["🥇", "🥈", "🥉"]

    text = (
        f"💰 **Capital Gold Stats — {clan_name}**\n"
        f"📅 {data_label} | 👥 {total} members\n"
        f"{'─' * 30}\n\n"
    )

    if page_members:
        for i, m in enumerate(page_members):
            rank = start + i
            medal = medals[rank] if rank < 3 else f"`{rank + 1}.`"
            clean_tag = m["tag"].replace("#", "")
            plink = f"https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=%23{clean_tag}"
            text += (
                f"{medal} [{m['name']}]({plink})\n"
                f"   💰 Donated: {fmt_number(m['donated'])} | 🗡️ Raided: {fmt_number(m['raided'])}\n"
            )
    else:
        text += "⚠️ **No contributions recorded.**\n"

    # Show zero donors on the last page
    if page == total_pages - 1 and zero_donors:
        text += f"\n{'─' * 30}\n"
        text += f"⚠️ **Zero Contributions ({len(zero_donors)}):**\n"
        zero_names = [m["name"] for m in zero_donors]
        if len(zero_names) > 15:
            text += ", ".join(zero_names[:15]) + f"... (+{len(zero_names) - 15} more)"
        else:
            text += ", ".join(zero_names)
        text += "\n"

    text += f"\n📄 Page {page + 1}/{total_pages}"

    # Build navigation buttons
    norm_tag = clan_tag.replace("#", "")
    buttons = []
    if page > 0:
        buttons.append(Btn("◀️ Prev", cb=f"capst:{page - 1}:{norm_tag}"))
    if page < total_pages - 1:
        buttons.append(Btn("Next ▶️", cb=f"capst:{page + 1}:{norm_tag}"))

    keyboard = [buttons] if buttons else []
    return text, Markup(keyboard) if keyboard else None
