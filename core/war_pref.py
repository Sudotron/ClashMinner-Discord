"""War preference grouping for /waropt (pure functions)."""
from discord.utils import escape_markdown


def group_war_preference(members: list, players: dict) -> dict:
    """Split clan members into opted in / out / unknown using each player's own `warPreference`.

    The clan member list carries no preference; it only exists on the player payload, so a member whose
    lookup failed (or whose payload lacks the field) is reported as unknown, never guessed.
    """
    groups = {"in": [], "out": [], "unknown": []}
    for m in members:
        p = players.get(m.get("tag"), {})
        pref = p.get("warPreference") if isinstance(p, dict) and "error" not in p else None
        entry = {"name": m.get("name", "?"), "tag": m.get("tag", ""),
                 "th": m.get("townHallLevel") or (p.get("townHallLevel") if isinstance(p, dict) else None) or 0}
        groups[pref if pref in ("in", "out") else "unknown"].append(entry)
    return groups


def _by_th(entries: list) -> str:
    by_th: dict = {}
    for e in entries:
        by_th.setdefault(e["th"], []).append(escape_markdown(e["name"]))
    lines = []
    for th in sorted(by_th, reverse=True):
        names = ", ".join(sorted(by_th[th], key=str.lower))
        lines.append(f"**TH{th}** ({len(by_th[th])}): {names}" if th else f"**TH?** ({len(by_th[th])}): {names}")
    return "\n".join(lines)


def format_war_preference(clan_name: str, tag: str, groups: dict) -> str:
    total = sum(len(v) for v in groups.values())
    out = [f"⚔️ **War preference — {escape_markdown(clan_name)}** (`{tag}`)",
           f"🟢 in: **{len(groups['in'])}** · 🔴 out: **{len(groups['out'])}** · ⚪ unknown: **{len(groups['unknown'])}** · {total} members", ""]
    for key, title in (("in", "🟢 **Opted IN**"), ("out", "🔴 **Opted OUT**"), ("unknown", "⚪ **Unavailable** (lookup failed)")):
        if groups[key]:
            out += [f"{title}", _by_th(groups[key]), ""]
    return "\n".join(out).rstrip()
