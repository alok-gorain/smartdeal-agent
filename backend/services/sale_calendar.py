"""Indian e-commerce sale calendar.

Dates are typical windows; stores announce exact dates a few weeks ahead.
`typical_discount` is the usual extra drop on popular electronics (used when a
product has no history for that sale yet).
"""

from dataclasses import dataclass
from datetime import date, timedelta

# Diwali (Lakshmi Puja) dates
DIWALI = {
    2024: date(2024, 11, 1),
    2025: date(2025, 10, 21),
    2026: date(2026, 11, 8),
    2027: date(2027, 10, 29),
    2028: date(2028, 10, 17),
    2029: date(2029, 11, 5),
    2030: date(2030, 10, 26),
}


@dataclass(frozen=True)
class SaleEvent:
    key: str
    name: str
    start: date
    end: date
    platforms: tuple[str, ...]
    typical_discount: float  # 0.15 = 15%

    def to_dict(self, today: date | None = None) -> dict:
        d = {
            "key": self.key,
            "name": self.name,
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            "platforms": list(self.platforms),
            "typical_discount_pct": round(self.typical_discount * 100),
        }
        if today:
            d["days_until"] = max(0, (self.start - today).days)
            d["is_live"] = self.start <= today <= self.end
        return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def events_for_year(year: int) -> list[SaleEvent]:
    diwali = DIWALI.get(year, date(year, 10, 28))
    black_friday = _nth_weekday(year, 11, 4, 4)  # 4th Friday of November
    events = [
        SaleEvent("republic_day", "Republic Day Sale", date(year, 1, 13), date(year, 1, 20),
                  ("amazon", "flipkart", "croma", "reliance_digital"), 0.15),
        SaleEvent("holi", "Holi Sale", date(year, 3, 5), date(year, 3, 10), ("amazon", "flipkart", "myntra"), 0.08),
        SaleEvent("summer", "Summer Sale", date(year, 5, 1), date(year, 5, 7), ("amazon", "flipkart"), 0.10),
        SaleEvent("eors", "End of Reason Sale", date(year, 6, 1), date(year, 6, 8), ("myntra", "ajio"), 0.25),
        SaleEvent("prime_day", "Prime Day", date(year, 7, 12), date(year, 7, 14), ("amazon",), 0.18),
        SaleEvent("independence_day", "Independence Day Sale", date(year, 8, 6), date(year, 8, 12),
                  ("amazon", "flipkart", "croma", "vijay_sales"), 0.12),
        SaleEvent("festive", "Big Billion Days / Great Indian Festival", date(year, 9, 23), date(year, 10, 3),
                  ("amazon", "flipkart", "myntra", "croma", "reliance_digital", "tata_cliq"), 0.25),
        SaleEvent("diwali", "Diwali Sale", diwali - timedelta(days=10), diwali - timedelta(days=1),
                  ("amazon", "flipkart", "myntra", "croma", "reliance_digital", "vijay_sales"), 0.20),
        SaleEvent("black_friday", "Black Friday Sale", black_friday, black_friday + timedelta(days=3),
                  ("amazon", "myntra", "ajio", "croma", "nykaa"), 0.12),
        SaleEvent("year_end", "Year-End Sale", date(year, 12, 20), date(year, 12, 31),
                  ("amazon", "flipkart", "tata_cliq"), 0.10),
    ]
    return sorted(events, key=lambda e: e.start)


def events_between(start: date, end: date) -> list[SaleEvent]:
    out: list[SaleEvent] = []
    for year in range(start.year, end.year + 1):
        out.extend(e for e in events_for_year(year) if e.end >= start and e.start <= end)
    return sorted(out, key=lambda e: e.start)


def upcoming_events(today: date, limit: int = 4, horizon_days: int = 180) -> list[SaleEvent]:
    events = [e for e in events_between(today, today + timedelta(days=horizon_days)) if e.end >= today]
    return events[:limit]


def event_on(day: date) -> SaleEvent | None:
    return next((e for e in events_for_year(day.year) if e.start <= day <= e.end), None)


def previous_occurrence(event: SaleEvent) -> SaleEvent | None:
    """The same sale one year earlier."""
    return next((e for e in events_for_year(event.start.year - 1) if e.key == event.key), None)
