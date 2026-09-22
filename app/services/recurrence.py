"""Calendar recurrence in the selected timezone, with explicit DST behavior."""

import calendar
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.schemas.mailbox import ScheduleRule


def local_to_utc(value: datetime, timezone: str) -> datetime:
    zone = ZoneInfo(timezone)
    # On a repeated autumn hour, use its first occurrence. Never send it twice.
    aware = value.replace(tzinfo=zone, fold=0)
    result = aware.astimezone(UTC)
    if result.astimezone(zone).replace(tzinfo=None) != value:
        raise ValueError(
            "This local time does not exist because clocks change. Choose another time."
        )
    return result


def occurrence(rule: ScheduleRule, index: int) -> datetime | None:
    if index < 0:
        raise ValueError("Occurrence index must be non-negative.")
    if rule.frequency == "once" and index:
        return None
    start = rule.start
    if rule.frequency == "monthly":
        month = start.year * 12 + start.month - 1 + index * rule.interval
        year, month = divmod(month, 12)
        if year > 9999:
            return None
        day = min(start.day, calendar.monthrange(year, month + 1)[1])
        value = start.replace(year=year, month=month + 1, day=day)
    else:
        days = index * rule.interval * (7 if rule.frequency == "weekly" else 1)
        try:
            value = start + timedelta(days=days)
        except OverflowError:
            return None
    if rule.end_date is not None and value.date() > rule.end_date:
        return None
    return local_to_utc(value, rule.timezone)


def next_occurrence(rule: ScheduleRule, index: int, after: datetime):
    """Skip missed occurrences and nonexistent spring-forward times."""
    if rule.frequency == "once":
        return None
    local_after = after.astimezone(ZoneInfo(rule.timezone)).replace(tzinfo=None)
    if rule.frequency == "monthly":
        elapsed = (
            (local_after.year - rule.start.year) * 12
            + local_after.month
            - rule.start.month
        )
    else:
        elapsed = (local_after.date() - rule.start.date()).days
        if rule.frequency == "weekly":
            elapsed //= 7
    index = max(index + 1, elapsed // rule.interval)
    for _ in range(370):
        try:
            due = occurrence(rule, index)
        except ValueError:
            index += 1
            continue
        if due is None:
            return None
        if due > after:
            return index, due
        index += 1
    raise ValueError("Could not determine the next recurrence.")
