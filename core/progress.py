"""Upgrade-progress maths for /progress (pure functions, no network)."""
from core.builders import PET_LIST, SIEGE_LIST
from core.helpers import get_scraped_th_max

SUPER_TROOPS = {
    "Super Barbarian", "Super Archer", "Super Giant", "Sneaky Goblin", "Super Wall Breaker", "Rocket Balloon",
    "Super Wizard", "Inferno Dragon", "Super Minion", "Super Valkyrie", "Super Witch", "Ice Hound",
    "Super Bowler", "Super Miner", "Super Hog Rider", "Super Yeti", "Super Dragon",
}

CATEGORIES = [("heroes", "Heroes"), ("equipment", "Hero Equipment"), ("troops", "Troops"),
              ("spells", "Spells"), ("siege", "Siege Machines"), ("pets", "Hero Pets")]


def _max_level(item: dict, th: int, th_max: dict) -> int:
    name, lvl = item.get("name", ""), item.get("level", 0)
    return get_scraped_th_max(name, th) or th_max.get(name) or item.get("maxLevel") or lvl


def _is_super(item: dict) -> bool:
    name = item.get("name", "")
    return name in SUPER_TROOPS or name.startswith("Super ")


def compute_progress(data: dict, th_max: dict | None = None) -> dict:
    """Home-village progress per category against the player's Town Hall maximums.

    Every unit the player owns counts level/max (capped at its max). Units not unlocked yet are not
    counted, exactly like /audit and /todo. Equipment uses the max level the API reports for it.
    """
    th_max = th_max or {}
    th = data.get("townHallLevel") if isinstance(data.get("townHallLevel"), int) else 0
    buckets = {key: [] for key, _ in CATEGORIES}

    def add(key, item):
        ml = _max_level(item, th, th_max)
        lvl = min(item.get("level", 0), ml) if ml else item.get("level", 0)
        buckets[key].append((item.get("name", "?"), lvl, ml))

    for h in data.get("heroes", []):
        if h.get("village") == "home":
            add("heroes", h)
    for e in data.get("heroEquipment", []):
        if e.get("village", "home") == "home":
            ml = e.get("maxLevel") or e.get("level", 0)
            buckets["equipment"].append((e.get("name", "?"), min(e.get("level", 0), ml), ml))
    for t in data.get("troops", []):
        if t.get("village") != "home" or _is_super(t):
            continue
        name = t.get("name", "")
        add("siege" if name in SIEGE_LIST else "pets" if name in PET_LIST else "troops", t)
    for s in data.get("spells", []):
        if s.get("village") == "home":
            add("spells", s)

    cats, tot_l, tot_m = [], 0, 0
    for key, label in CATEGORIES:
        units = buckets[key]
        if not units:
            continue
        levels = sum(u[1] for u in units)
        maxes = sum(u[2] for u in units)
        cats.append({"key": key, "label": label, "levels": levels, "max_levels": maxes, "units": len(units),
                     "maxed": sum(1 for u in units if u[1] >= u[2]),
                     "pct": (100.0 * levels / maxes) if maxes else 100.0})
        tot_l += levels
        tot_m += maxes
    return {"name": data.get("name", "Unknown"), "tag": data.get("tag", ""), "th": th,
            "clan": (data.get("clan") or {}).get("name"), "categories": cats,
            "overall_pct": (100.0 * tot_l / tot_m) if tot_m else 0.0}
