"""Pillow renderers for /progress and /poster. CPU-bound: call through helpers.run_blocking()."""
import io
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

import config

S = 2                                   # draw at 2x, downscale for smooth edges
BG, CARD, TRACK = (24, 26, 32), (38, 41, 50), (58, 62, 74)
TEXT, MUTED, GOLD = (240, 242, 247), (160, 168, 184), (255, 200, 61)
HEROES_SHORT = {"Barbarian King": "BK", "Archer Queen": "AQ", "Grand Warden": "GW", "Royal Champion": "RC",
                "Minion Prince": "MP"}


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False):
    path = os.path.join(config.FONT_DIR, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size * S)
    except OSError:
        return ImageFont.load_default(size * S)


def _fit(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _bar_color(pct: float):
    if pct >= 100: return (88, 214, 141)
    if pct >= 85: return (130, 207, 93)
    if pct >= 65: return (241, 196, 15)
    if pct >= 40: return (243, 156, 18)
    return (231, 90, 76)


def _th_image(path: str | None, size: int):
    if not path or not os.path.isfile(path):
        return None
    with Image.open(path) as src:                     # close the file handle right away
        im = src.convert("RGB").resize((size * S, size * S), Image.LANCZOS)
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *im.size), radius=22 * S, fill=255)
    out = Image.new("RGBA", im.size)
    out.paste(im, (0, 0), mask)
    return out


def _png(img: Image.Image, w: int, h: int) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").resize((w, h), Image.LANCZOS).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _rr(d, box, r, fill):
    d.rounded_rectangle([v * S for v in box], radius=r * S, fill=fill)


def _text(d, xy, text, font, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), text, font=font, fill=fill, anchor=anchor)


def render_progress_card(progress: dict, th_image_path: str | None = None) -> bytes:
    cats = progress["categories"]
    w, row_h, head_h = 1000, 86, 250
    h = head_h + row_h * max(len(cats), 1) + 70
    img = Image.new("RGB", (w * S, h * S), BG)
    d = ImageDraw.Draw(img)
    _rr(d, (16, 16, w - 16, h - 16), 28, CARD)

    th = _th_image(th_image_path, 200)
    if th:
        img.paste(th, (44 * S, 40 * S), th)
    tx = 270
    name_font = _font(44, True)
    _text(d, (tx, 52), _fit(d, progress["name"], name_font, (w - 60 - tx) * S), name_font, TEXT)
    sub = f"TH{progress['th']}  ·  {progress['tag']}" + (f"  ·  {progress['clan']}" if progress.get("clan") else "")
    _text(d, (tx, 112), _fit(d, sub, _font(24), (w - 60 - tx) * S), _font(24), MUTED)
    pct = progress["overall_pct"]
    _text(d, (tx, 160), f"{pct:.1f}%", _font(56, True), _bar_color(pct))
    _text(d, (tx + 250, 190), "overall progress to TH max", _font(22), MUTED)
    bx0, bx1, by = tx, w - 60, 232
    _rr(d, (bx0, by, bx1, by + 14), 7, TRACK)
    if pct > 0:
        _rr(d, (bx0, by, bx0 + max(14, (bx1 - bx0) * min(pct, 100) / 100), by + 14), 7, _bar_color(pct))

    y = head_h
    for c in cats:
        _text(d, (50, y + 6), c["label"], _font(28, True), TEXT)
        stats = f"{c['levels']}/{c['max_levels']} levels  ·  {c['maxed']}/{c['units']} maxed"
        _text(d, (w - 50, y + 12), stats, _font(21), MUTED, "ra")
        _rr(d, (50, y + 48, w - 50, y + 70), 11, TRACK)
        fill = max(22, (w - 100) * min(c["pct"], 100) / 100)
        _rr(d, (50, y + 48, 50 + fill, y + 70), 11, _bar_color(c["pct"]))
        _text(d, (50 + fill - 12, y + 59), f"{c['pct']:.0f}%" if fill > 90 else "", _font(17, True), (20, 22, 28), "rm")
        y += row_h
    if not cats:
        _text(d, (w // 2, head_h + 30), "No home-village units found for this player.", _font(24), MUTED, "ma")
    _text(d, (w // 2, h - 52), "ClashMinner  ·  progress vs Town Hall maximums (home village)", _font(18), MUTED, "ma")
    return _png(img, w, h)


def render_poster_card(data: dict, th_image_path: str | None = None) -> bytes:
    w, h = 1000, 620
    img = Image.new("RGB", (w * S, h * S), BG)
    d = ImageDraw.Draw(img)
    _rr(d, (16, 16, w - 16, h - 16), 28, CARD)
    th = _th_image(th_image_path, 300)
    if th:
        img.paste(th, (44 * S, 44 * S), th)
    clan = data.get("clan") or {}
    role = str(data.get("role", "")).replace("admin", "elder").replace("coLeader", "co-leader").title()
    tx, tw = 380, (w - 380 - 50) * S
    _text(d, (tx, 48), _fit(d, data.get("name", "Unknown"), _font(48, True), tw), _font(48, True), TEXT)
    _text(d, (tx, 112), f"{data.get('tag', '')}  ·  TH{data.get('townHallLevel', '?')}  ·  Level {data.get('expLevel', '?')}",
          _font(24), MUTED)
    if clan.get("name"):
        line = clan["name"] + (f"  ·  {role}" if role else "")
        _text(d, (tx, 150), _fit(d, line, _font(24), tw), _font(24), GOLD)
    stats = [("Trophies", data.get("trophies")), ("Best", data.get("bestTrophies")),
             ("War stars", data.get("warStars")), ("Attack wins", data.get("attackWins")),
             ("Defense wins", data.get("defenseWins")), ("Donated", data.get("donations"))]
    for i, (label, value) in enumerate(stats):
        cx, cy = tx + (i % 3) * 196, 205 + (i // 3) * 100
        _rr(d, (cx, cy, cx + 180, cy + 86), 14, TRACK)
        _text(d, (cx + 90, cy + 14), label, _font(17), MUTED, "ma")
        _text(d, (cx + 90, cy + 40), f"{value:,}" if isinstance(value, int) else "–", _font(28, True), TEXT, "ma")
    heroes = [x for x in data.get("heroes", []) if x.get("village") == "home"][:6]
    _text(d, (50, 380), "Heroes", _font(24, True), TEXT)
    for i, hero in enumerate(heroes):
        cx = 50 + i * 150
        lvl, ml = hero.get("level", 0), hero.get("maxLevel", hero.get("level", 0))
        _rr(d, (cx, 420, cx + 138, 520), 14, TRACK)
        _text(d, (cx + 69, 432), HEROES_SHORT.get(hero.get("name", ""), hero.get("name", "?")[:3].upper()),
              _font(24, True), GOLD, "ma")
        _text(d, (cx + 69, 462), f"{lvl}", _font(34, True), _bar_color(100.0 * lvl / ml if ml else 100), "ma")
        _text(d, (cx + 69, 497), f"/ {ml}", _font(16), MUTED, "ma")
    if not heroes:
        _text(d, (50, 440), "No heroes unlocked yet.", _font(22), MUTED)
    eq = [e for e in data.get("heroEquipment", []) if e.get("village", "home") == "home"]
    if eq:
        maxed = sum(1 for e in eq if e.get("level", 0) >= e.get("maxLevel", 1 << 30))
        _text(d, (50, 548), f"Hero equipment: {len(eq)} owned · {maxed} maxed", _font(22), MUTED)
    _text(d, (w - 50, h - 52), "ClashMinner", _font(18), MUTED, "ra")
    return _png(img, w, h)
