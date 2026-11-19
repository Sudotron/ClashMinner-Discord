"""Autocomplete for the `tag` option: the caller's linked accounts, primary first."""
from discord import app_commands

from database import get_linked_accounts

MAX_CHOICES = 25   # Discord limit


def build_choices(accounts: list, current: str) -> list:
    """Filter linked accounts by what the user typed (tag or cached name) and format them."""
    needle = (current or "").strip().lower().lstrip("#")
    choices = []
    for a in accounts:
        tag, label = a["tag"], a.get("label") or ""
        if needle and needle not in tag.lower() and needle not in label.lower():
            continue
        marks = ("★ " if a["is_primary"] else "") + ("✔ " if a["is_verified"] else "")
        text = f"{marks}{label} ({tag})" if label else f"{marks}{tag}"
        choices.append(app_commands.Choice(name=text[:100], value=tag))
    return choices[:MAX_CHOICES]


async def linked_tag_choices(interaction, current: str, entity_type: str) -> list:
    """Never raises: a failed lookup just means no suggestions (typing a tag still works)."""
    try:
        return build_choices(await get_linked_accounts(interaction.user.id, entity_type), current)
    except Exception:
        return []
