import asyncio
import time
import httpx
import urllib.parse
import coc
from dotenv import load_dotenv

load_dotenv()

CLASHKING_URL = "https://api.clashk.ing"


async def _fetch(base: str, endpoint: str) -> dict:
    headers = {"Accept": "application/json"}
    url = f"{base}{endpoint}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return {"error": "Not Found. Tag might be incorrect."}
            elif response.status_code == 403:
                return {"error": "Forbidden. API Key might be invalid."}
            else:
                return {"error": f"API Error: Status {response.status_code}"}
        except httpx.TimeoutException:
            return {"error": "Request timed out. Try again later."}
        except Exception as e:
            return {"error": str(e)}


async def fetch_stats_data(endpoint: str) -> dict:
    return await _fetch(CLASHKING_URL, endpoint)


def format_tag(tag: str) -> str:
    tag = tag.strip().upper()
    if tag.startswith('#'):
        return urllib.parse.quote_plus(tag)
    return "%23" + tag


def _official_payload(model) -> dict:
    payload = getattr(model, "_raw_data", None)
    if not isinstance(payload, dict):
        raise RuntimeError("Official CoC API response did not include raw player/clan data.")
    return payload


def _api_unavailable() -> dict:
    return {"error": "Official Clash of Clans API is not connected. Configure COC_EMAIL and COC_PASSWORD."}


def _official_tag(tag: str) -> str:
    tag = tag.strip().upper()
    return tag if tag.startswith("#") else f"#{tag}"


async def get_player(tag: str, coc_client=None) -> dict:
    if coc_client is None:
        return _api_unavailable()
    try:
        return _official_payload(await coc_client.get_player(_official_tag(tag)))
    except coc.NotFound:
        return {"error": "Player not found. Check the tag and try again."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}


async def get_player_warhits(tag: str):
    return await fetch_stats_data(f"/player/{format_tag(tag)}/warhits")


async def get_clan(tag: str, coc_client=None, *, lookup_cache: bool = True) -> dict:
    if coc_client is None:
        return _api_unavailable()
    try:
        return _official_payload(
            await coc_client.get_clan(_official_tag(tag), lookup_cache=lookup_cache)
        )
    except coc.NotFound:
        return {"error": "Clan not found. Check the tag and try again."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}


async def get_player_join_leave(tag: str, limit: int = 15):
    # Fetch 250 from API because the API limit returns oldest first; we fetch many and slice locally
    return await fetch_stats_data(f"/player/{format_tag(tag)}/join-leave?timestamp_start=0&time_stamp_end=9999999999&limit=250")

async def get_clan_members(tag: str, coc_client=None):
    clan = await get_clan(tag, coc_client)
    if "error" in clan:
        return clan
    return {"items": clan.get("memberList", [])}


async def get_clan_war(tag: str, coc_client=None, *, lookup_cache: bool = True) -> dict:
    if coc_client is None:
        return _api_unavailable()
    try:
        war = await coc_client.get_clan_war(_official_tag(tag), lookup_cache=lookup_cache)
    except coc.NotFound:
        return {"error": "Clan not found. Check the tag and try again."}
    except coc.PrivateWarLog:
        return {"error": "This clan's war log is private."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}
    if war is None:
        return {"state": "notInWar", "clan": {"tag": _official_tag(tag)}}
    payload = dict(_official_payload(war))
    if war.clan and payload.get("clan", {}).get("tag") != war.clan.tag:
        payload["clan"], payload["opponent"] = payload.get("opponent", {}), payload.get("clan", {})
    return payload

async def get_previous_wars(tag: str, limit: int = 2):
    return await fetch_stats_data(f"/war/{format_tag(tag)}/previous?limit={limit}")


# ── Batch player lookups (shared by /accounts, /waropt, activity, reminders) ──
_PLAYER_CACHE: dict = {}          # official tag -> (fetched_at, payload)
_PLAYER_CACHE_MAX = 2000


async def get_players_batch(tags, coc_client=None, *, batch_size: int = 10, ttl: float = 90) -> dict:
    """Fetch many players concurrently, `batch_size` at a time, to stay inside the API rate limit.

    Returns {official_tag: payload_or_{"error": ...}} for every distinct tag, in input order.
    One failed lookup never fails the others. Successful payloads are cached for `ttl`
    seconds (ttl=0 disables the cache); errors are never cached.
    """
    ordered = list(dict.fromkeys(_official_tag(t) for t in tags if t and t.strip()))
    now = time.monotonic()
    result: dict = {}
    missing = []
    for tag in ordered:
        hit = _PLAYER_CACHE.get(tag)
        if ttl and hit and now - hit[0] < ttl:
            result[tag] = hit[1]
        else:
            missing.append(tag)
    for i in range(0, len(missing), batch_size):
        chunk = missing[i:i + batch_size]
        payloads = await asyncio.gather(*(get_player(t, coc_client) for t in chunk), return_exceptions=True)
        for tag, payload in zip(chunk, payloads):
            if isinstance(payload, Exception):
                payload = {"error": str(payload)}
            result[tag] = payload
            if ttl and "error" not in payload:
                if len(_PLAYER_CACHE) >= _PLAYER_CACHE_MAX:
                    oldest = min(_PLAYER_CACHE, key=lambda k: _PLAYER_CACHE[k][0])
                    _PLAYER_CACHE.pop(oldest, None)
                _PLAYER_CACHE[tag] = (time.monotonic(), payload)
    return {tag: result[tag] for tag in ordered}


# ── Account ownership verification ───────────────────────────────────────────
async def verify_player_token(tag: str, token: str, coc_client=None) -> dict:
    """Check the one-time in-game API token (Settings > More Settings) for a player.

    Returns {"verified": True/False} or {"error": "..."}. The token is never logged or stored.
    """
    if coc_client is None:
        return _api_unavailable()
    token = (token or "").strip()
    if not token:
        return {"error": "No API token provided."}
    try:
        return {"verified": bool(await coc_client.verify_player_token(_official_tag(tag), token))}
    except coc.NotFound:
        return {"error": "Player not found. Check the tag and try again."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}


# ── Current war (regular or CWL) and current raid weekend ───────────────────
async def get_current_war_any(tag: str, coc_client=None) -> dict:
    """The clan's war right now: a regular war, or its CWL war when it is in the league.

    `clan` in the payload is always the requested clan. Adds `isCwl` and `attacksPerMember`
    (CWL wars give each member 1 attack, regular wars 2). {"state": "notInWar"} when there is none.
    """
    if coc_client is None:
        return _api_unavailable()
    try:
        war = await coc_client.get_current_war(_official_tag(tag))
    except coc.NotFound:
        return {"error": "Clan not found. Check the tag and try again."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}
    if war is None:
        return {"state": "notInWar", "clan": {"tag": _official_tag(tag)}}
    payload = dict(_official_payload(war))
    if war.clan and payload.get("clan", {}).get("tag") != war.clan.tag:
        payload["clan"], payload["opponent"] = payload.get("opponent", {}), payload.get("clan", {})
    payload["isCwl"] = bool(getattr(war, "is_cwl", False))
    payload.setdefault("attacksPerMember", 1 if payload["isCwl"] else 2)
    return payload


async def get_current_raid(tag: str, coc_client=None) -> dict:
    """The newest capital raid season entry (raw API shape: state, startTime, endTime, members[...]).

    {"state": "none"} when the clan has no raid history; {"error": "..."} on failure.
    """
    if coc_client is None:
        return _api_unavailable()
    try:
        log = await coc_client.get_raid_log(_official_tag(tag), limit=1)
    except coc.NotFound:
        return {"error": "Clan not found. Check the tag and try again."}
    except coc.Maintenance:
        return {"error": "Clash of Clans is under maintenance. Try again later."}
    except coc.HTTPException as e:
        return {"error": str(e)}
    if not log:
        return {"state": "none"}
    return dict(_official_payload(log[0]))
