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


async def get_clan(tag: str, coc_client=None) -> dict:
    if coc_client is None:
        return _api_unavailable()
    try:
        return _official_payload(await coc_client.get_clan(_official_tag(tag)))
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


async def get_clan_war(tag: str, coc_client=None) -> dict:
    if coc_client is None:
        return _api_unavailable()
    try:
        war = await coc_client.get_clan_war(_official_tag(tag))
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
