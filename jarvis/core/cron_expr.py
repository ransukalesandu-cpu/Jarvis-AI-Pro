"""Five-field cron expressions (minute hour day-of-month month day-of-week).

Supported per field: ``*``, ``a``, ``a-b``, ``a,b,c``, ``*/n``, ``a-b/n``,
``a/n``; month names (jan..dec) and weekday names (sun..sat); weekday 0 or 7
is Sunday. As in classic cron, when both day-of-month and day-of-week are
restricted a day matches if *either* matches.

``next_after`` walks wall-clock time in the given IANA zone, so schedules keep
their local time across DST changes; a local time that does not exist (spring
forward) is skipped for that day, and one that occurs twice (fall back) fires
once.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_MONTHS = {n: i for i, n in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DAYS = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
_SEARCH_YEARS = 5


class CronError(ValueError):
    """The expression is not a valid five-field cron expression."""


def _value(token: str, names: dict[str, int], lo: int, hi: int, label: str) -> int:
    text = token.strip().lower()
    if text in names:
        return names[text]
    if not text.isdigit():
        raise CronError(f"{label}: '{token}' is not a number or name")
    number = int(text)
    if not lo <= number <= hi:
        raise CronError(f"{label}: {number} is outside {lo}-{hi}")
    return number


def _field(text: str, lo: int, hi: int, label: str, names: dict[str, int] | None = None) -> frozenset[int]:
    names = names or {}
    out: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{label}: empty list item")
        step = 1
        has_step = "/" in part
        if has_step:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{label}: bad step '{step_text}'")
            step = int(step_text)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = _value(a, names, lo, hi, label), _value(b, names, lo, hi, label)
            if start > end:
                raise CronError(f"{label}: range {start}-{end} is backwards")
        else:
            start = _value(part, names, lo, hi, label)
            end = hi if has_step else start
        out.update(range(start, end + 1, step))
    return frozenset(out)


@dataclass(frozen=True)
class CronExpr:
    minutes: frozenset
    hours: frozenset
    days: frozenset
    months: frozenset
    weekdays: frozenset            # 0=Sunday .. 6=Saturday
    days_restricted: bool
    weekdays_restricted: bool
    text: str = ""

    def day_matches(self, when: datetime) -> bool:
        weekday = (when.weekday() + 1) % 7          # Python Monday=0 -> cron Sunday=0
        dom = when.day in self.days
        dow = weekday in self.weekdays
        if self.days_restricted and self.weekdays_restricted:
            return dom or dow
        if self.days_restricted:
            return dom
        if self.weekdays_restricted:
            return dow
        return True


def parse(expression: str) -> CronExpr:
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise CronError("a cron expression has five fields: minute hour day month weekday")
    minutes = _field(parts[0], 0, 59, "minute")
    hours = _field(parts[1], 0, 23, "hour")
    days = _field(parts[2], 1, 31, "day")
    months = _field(parts[3], 1, 12, "month", _MONTHS)
    raw_weekdays = _field(parts[4], 0, 7, "weekday", _DAYS)
    weekdays = frozenset(0 if d == 7 else d for d in raw_weekdays)
    return CronExpr(minutes, hours, days, months, weekdays,
                    days_restricted=not parts[2].startswith("*"),
                    weekdays_restricted=not parts[4].startswith("*"),
                    text=" ".join(parts))


def resolve_zone(name: str | None):
    """A ZoneInfo for ``name``; the local zone when it is empty."""
    if name:
        try:
            return ZoneInfo(name)
        except Exception as exc:
            raise CronError(f"unknown time zone '{name}'") from exc
    return datetime.now().astimezone().tzinfo


def next_after(expr: CronExpr, after: float, tz_name: str | None = None) -> float | None:
    """Epoch seconds of the first match strictly after ``after``; None if none within 5 years."""
    tz = resolve_zone(tz_name)
    start = datetime.fromtimestamp(after, tz).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
    limit = start.replace(year=start.year + _SEARCH_YEARS)
    cursor = start
    while cursor < limit:
        if cursor.month not in expr.months:
            year, month = (cursor.year + 1, 1) if cursor.month == 12 else (cursor.year, cursor.month + 1)
            cursor = datetime(year, month, 1)
            continue
        if not expr.day_matches(cursor):
            cursor = datetime(cursor.year, cursor.month, cursor.day) + timedelta(days=1)
            continue
        if cursor.hour not in expr.hours:
            cursor = cursor.replace(minute=0) + timedelta(hours=1)
            continue
        if cursor.minute not in expr.minutes:
            cursor += timedelta(minutes=1)
            continue
        stamp = cursor.replace(tzinfo=tz).timestamp()
        # A wall-clock time inside a DST gap shifts when converted: skip it.
        back = datetime.fromtimestamp(stamp, tz)
        if (back.hour, back.minute) != (cursor.hour, cursor.minute) or stamp <= after:
            cursor += timedelta(minutes=1)
            continue
        return stamp
    return None
