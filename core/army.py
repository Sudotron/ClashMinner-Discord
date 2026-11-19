"""Clash of Clans link reading: army links (CopyArmy) and base layout links (OpenLayout).

Only https://link.clashofclans.com links are ever read, and nothing is fetched from the network: an
army link is decoded locally with coc.py's bundled game data, a layout link is just validated and stored.
"""
import re
from urllib.parse import parse_qs, quote, urlparse

import coc
from coc.game_data import EQUIPMENT_BASE_ID, HERO_BASE_ID, PET_BASE_ID, SPELL_BASE_ID, TROOP_BASE_ID

LINK_HOST = "link.clashofclans.com"
_URL_RE = re.compile(r"https://link\.clashofclans\.com/[^\s<>()\[\]|]*", re.I)
_PATH_RE = re.compile(r"^/?(?:[a-z]{2}(?:[-_][A-Za-z]{2,4})?)?/?$")
_ARMY_RE = re.compile(r"^[0-9A-Za-z_-]{1,800}$")
_LAYOUT_RE = re.compile(r"^[0-9A-Za-z:_\-=+/.]{1,1800}$")
MAX_LAYOUT_URL = 1900              # must fit in a Discord message together with a short caption
CATEGORIES = ["War", "CWL", "Farming", "Trophy", "Legend"]


def extract_links(text: str, limit: int = 3) -> list:
    """Distinct link.clashofclans.com URLs in a message, trailing punctuation removed, at most `limit`."""
    found = []
    for raw in _URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?'\"")
        if url not in found:
            found.append(url)
    return found[:limit]


def _params(url: str):
    """(action, query) for a strictly valid link.clashofclans.com URL, else None."""
    try:
        p = urlparse(url)
        if (p.scheme != "https" or (p.hostname or "").lower() != LINK_HOST or p.port is not None
                or p.username or p.password or not _PATH_RE.match(p.path)):
            return None
        q = parse_qs(p.query, keep_blank_values=True)
    except ValueError:
        return None
    action = q.get("action", [])
    return (action[0], q) if len(action) == 1 else None


def link_kind(url: str):
    """'army', 'layout', or None."""
    parsed = _params(url)
    if not parsed:
        return None
    return {"CopyArmy": "army", "OpenLayout": "layout"}.get(parsed[0])


def army_link(url: str):
    """Normalised CopyArmy URL, or None if it isn't a valid one."""
    parsed = _params(url)
    if not parsed or parsed[0] != "CopyArmy":
        return None
    army = parsed[1].get("army", [])
    if len(army) != 1 or not _ARMY_RE.match(army[0]):
        return None
    return f"https://{LINK_HOST}/en?action=CopyArmy&army={army[0]}"


def layout_link(url: str):
    """(normalised URL, town hall level or None) for a valid OpenLayout link, else None."""
    parsed = _params(url)
    if not parsed or parsed[0] != "OpenLayout":
        return None
    ids = parsed[1].get("id", [])
    if len(ids) != 1 or not _LAYOUT_RE.match(ids[0]):
        return None
    normalised = f"https://{LINK_HOST}/en?action=OpenLayout&id={quote(ids[0], safe='')}"
    if len(normalised) > MAX_LAYOUT_URL:
        return None
    m = re.match(r"^TH(\d{1,2})\b", ids[0], re.I)
    return normalised, (int(m.group(1)) if m else None)


# ── decoding ─────────────────────────────────────────────────────────────────
_offline_client = None


def decoder_client(bot_client=None):
    """A coc.py client with game data loaded. Uses the bot's logged-in client when there is one."""
    global _offline_client
    client = bot_client
    if client is None:
        if _offline_client is None:
            _offline_client = coc.Client(load_game_data=coc.LoadGameData(always=True))
        client = _offline_client
    if not getattr(client, "_translations", None):  # unit names; a logged-in client already has them
        client._load_static()                      # offline: bundled with coc.py, no API call
    return client


_SECTION_RE = re.compile(r"h(?P<h>[^idus]+)|i(?P<i>[\d+x-]+)|d(?P<d>[\d+x-]+)|u(?P<u>[\d+x-]+)|s(?P<s>[\d+x-]+)")
_HERO_RE = re.compile(r"(?P<hero>\d+)(?:m\d+)?(?:p(?P<pet>\d+))?(?:e(?P<eq1>\d+)(?:_(?P<eq2>\d+))?)?")
MAX_UNIT_QUANTITY = 400            # no real army holds more of one unit; stops absurd numbers


def _check_ids(client, army: str):
    """coc.py silently swaps unknown ids for a default unit (Barbarian / Lightning Spell), so check them first."""
    known = client._static_data
    for m in _SECTION_RE.finditer(army):
        for kind in "idus":
            body = m.group(kind)
            if not body:
                continue
            base = TROOP_BASE_ID if kind in "iu" else SPELL_BASE_ID
            for item in body.split("-"):
                qty, _, uid = item.partition("x")
                if not (qty.isdigit() and uid.isdigit() and 1 <= int(qty) <= MAX_UNIT_QUANTITY
                        and base + int(uid) in known):
                    raise ValueError("That army link has units I don't recognise. It may be from a newer game version.")
        if m.group("h"):
            for entry in m.group("h").split("-"):
                h = _HERO_RE.fullmatch(entry)
                if not h or HERO_BASE_ID + int(h.group("hero")) not in known:
                    raise ValueError("That army link has a hero I don't recognise. It may be from a newer game version.")
                for base, key in ((PET_BASE_ID, "pet"), (EQUIPMENT_BASE_ID, "eq1"), (EQUIPMENT_BASE_ID, "eq2")):
                    if h.group(key) and base + int(h.group(key)) not in known:
                        raise ValueError("That army link has a pet or equipment I don't recognise. "
                                         "It may be from a newer game version.")


def _lines(pairs) -> list:
    return [(q, t.name, t.housing_space) for t, q in pairs]


def decode_army(client, url: str) -> dict:
    """Decode a CopyArmy link into plain data. Raises ValueError with a user-safe message."""
    link = army_link(url)
    if not link:
        raise ValueError("That isn't a valid Clash of Clans army link.")
    _check_ids(client, link.split("army=", 1)[1])
    try:
        army = client.parse_army_link(link)
    except Exception:
        raise ValueError("I couldn't read that army link. It may be from a newer game version.")
    troops = [(q, t.name, t.housing_space) for t, q in army.troops if not t.is_siege_machine]
    siege = [(q, t.name, t.housing_space) for t, q in army.troops if t.is_siege_machine]
    spells = _lines(army.spells)
    cc_troops, cc_spells = _lines(army.clan_castle_troops), _lines(army.clan_castle_spells)
    heroes = []
    for h in army.heroes_loadout:
        heroes.append({"hero": h.hero.name, "pet": h.pet.name if h.pet else None,
                       "equipment": [e.name for e in h.equipment]})
    space = lambda items: sum(q * s for q, _, s in items)
    if not (troops or siege or spells or cc_troops or cc_spells or heroes):
        raise ValueError("That army link is empty.")
    return {"link": link, "troops": troops, "siege": siege, "spells": spells, "cc_troops": cc_troops,
            "cc_spells": cc_spells, "heroes": heroes, "troop_space": space(troops),
            "siege_count": sum(q for q, _, _ in siege), "spell_space": space(spells),
            "cc_troop_space": space(cc_troops), "cc_spell_space": space(cc_spells)}


def format_units(items: list) -> str:
    return "\n".join(f"{q}× {name}" for q, name, _ in items)


def army_fields(info: dict) -> list:
    """[(field name, text)] for an embed; only non-empty sections."""
    fields = []
    if info["troops"]:
        fields.append((f"Troops · {info['troop_space']} space", format_units(info["troops"])))
    if info["spells"]:
        fields.append((f"Spells · {info['spell_space']} space", format_units(info["spells"])))
    if info["siege"]:
        fields.append((f"Siege machines · {info['siege_count']}", format_units(info["siege"])))
    if info["heroes"]:
        lines = []
        for h in info["heroes"]:
            extras = ", ".join(([h["pet"]] if h["pet"] else []) + h["equipment"])
            lines.append(f"{h['hero']}" + (f" — {extras}" if extras else ""))
        fields.append(("Heroes", "\n".join(lines)))
    if info["cc_troops"] or info["cc_spells"]:
        parts = []
        if info["cc_troops"]:
            parts.append(f"**Troops · {info['cc_troop_space']} space**\n{format_units(info['cc_troops'])}")
        if info["cc_spells"]:
            parts.append(f"**Spells · {info['cc_spell_space']} space**\n{format_units(info['cc_spells'])}")
        fields.append(("Clan Castle", "\n".join(parts)))
    return fields


# ── base library input rules ─────────────────────────────────────────────────
def normalise_category(text: str) -> str:
    wanted = (text or "").strip().lower()
    for c in CATEGORIES:
        if c.lower() == wanted:
            return c
    raise ValueError(f"Category must be one of: {', '.join(CATEGORIES)}.")


def parse_th(text) -> int:
    try:
        value = int(str(text).strip().upper().removeprefix("TH"))
    except ValueError:
        raise ValueError("Town Hall level must be a number, e.g. 15.")
    if not 1 <= value <= 25:
        raise ValueError("Town Hall level must be between 1 and 25.")
    return value
