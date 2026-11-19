"""Clash of Clans season boundaries (a season ends on the last Monday of the month, 05:00 UTC)."""
from datetime import datetime, timedelta, timezone

SEASON_END_HOUR_UTC = 5


def _last_monday_end(year: int, month: int) -> datetime:
    nxt = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
    day = nxt - timedelta(days=1)
    while day.weekday() != 0:
        day -= timedelta(days=1)
    return day.replace(hour=SEASON_END_HOUR_UTC, minute=0, second=0, microsecond=0)


def season_id(now: datetime | None = None) -> str:
    """'YYYY-MM' of the season that is running at `now` (named after the month it ends in)."""
    now = now or datetime.now(timezone.utc)
    if now >= _last_monday_end(now.year, now.month):
        year, month = now.year + (now.month == 12), (now.month % 12) + 1
        return f"{year:04d}-{month:02d}"
    return f"{now.year:04d}-{now.month:02d}"
