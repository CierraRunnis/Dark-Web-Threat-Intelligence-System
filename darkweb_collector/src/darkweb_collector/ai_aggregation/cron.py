from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class CronValidationError(ValueError):
    pass


def _expand_part(part: str, minimum: int, maximum: int, *, weekday: bool = False) -> set[int]:
    values: set[int] = set()
    for item in part.split(","):
        item = item.strip()
        if not item:
            raise CronValidationError("cron field contains an empty item")
        base, slash, step_text = item.partition("/")
        if slash:
            try:
                step = int(step_text)
            except ValueError as exc:
                raise CronValidationError("cron step must be an integer") from exc
            if step <= 0:
                raise CronValidationError("cron step must be positive")
        else:
            step = 1

        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            left, right = base.split("-", 1)
            try:
                start, end = int(left), int(right)
            except ValueError as exc:
                raise CronValidationError("cron range must contain integers") from exc
            if start > end:
                raise CronValidationError("cron range start must not exceed its end")
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronValidationError("cron value must be an integer, range, list, or wildcard") from exc

        allowed_maximum = 7 if weekday else maximum
        if start < minimum or end > allowed_maximum:
            raise CronValidationError(
                f"cron value outside allowed range {minimum}-{allowed_maximum}"
            )
        for value in range(start, end + 1, step):
            values.add(0 if weekday and value == 7 else value)
    return values


@dataclass(frozen=True, slots=True)
class CronExpression:
    expression: str
    minutes: set[int]
    hours: set[int]
    days: set[int]
    months: set[int]
    weekdays: set[int]
    day_wildcard: bool
    weekday_wildcard: bool

    @classmethod
    def parse(cls, expression: str) -> "CronExpression":
        parts = expression.strip().split()
        if len(parts) != 5:
            raise CronValidationError("cron must contain exactly five fields")
        minute, hour, day, month, weekday = parts
        return cls(
            expression=" ".join(parts),
            minutes=_expand_part(minute, 0, 59),
            hours=_expand_part(hour, 0, 23),
            days=_expand_part(day, 1, 31),
            months=_expand_part(month, 1, 12),
            weekdays=_expand_part(weekday, 0, 6, weekday=True),
            day_wildcard=day == "*",
            weekday_wildcard=weekday == "*",
        )

    def matches(self, value: datetime) -> bool:
        if value.minute not in self.minutes or value.hour not in self.hours:
            return False
        if value.month not in self.months:
            return False
        day_match = value.day in self.days
        cron_weekday = (value.weekday() + 1) % 7
        weekday_match = cron_weekday in self.weekdays
        if self.day_wildcard and self.weekday_wildcard:
            return True
        if self.day_wildcard:
            return weekday_match
        if self.weekday_wildcard:
            return day_match
        return day_match or weekday_match


def validate_five_field_cron(expression: str) -> str:
    return CronExpression.parse(expression).expression

