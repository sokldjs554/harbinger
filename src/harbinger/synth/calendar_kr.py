"""한국 공휴일(고정 + 설·추석 2023~2026 하드코딩)과 재실 지수."""

from __future__ import annotations

from datetime import date, timedelta

_FIXED = [(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)]
_LUNAR = {
    2023: [
        date(2023, 1, 21),
        date(2023, 1, 22),
        date(2023, 1, 23),
        date(2023, 1, 24),
        date(2023, 5, 27),
        date(2023, 9, 28),
        date(2023, 9, 29),
        date(2023, 9, 30),
        date(2023, 10, 2),
    ],
    2024: [
        date(2024, 2, 9),
        date(2024, 2, 10),
        date(2024, 2, 11),
        date(2024, 2, 12),
        date(2024, 5, 15),
        date(2024, 9, 16),
        date(2024, 9, 17),
        date(2024, 9, 18),
    ],
    2025: [
        date(2025, 1, 28),
        date(2025, 1, 29),
        date(2025, 1, 30),
        date(2025, 5, 5),
        date(2025, 10, 5),
        date(2025, 10, 6),
        date(2025, 10, 7),
        date(2025, 10, 8),
    ],
    2026: [
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 5, 24),
        date(2026, 9, 24),
        date(2026, 9, 25),
        date(2026, 9, 26),
    ],
}


def holidays(year: int) -> set[date]:
    out = {date(year, m, d) for m, d in _FIXED}
    out |= set(_LUNAR.get(year, []))
    return out


def is_holiday(d: date, cache: dict[int, set[date]]) -> bool:
    if d.year not in cache:
        cache[d.year] = holidays(d.year)
    return d in cache[d.year]


def occupancy_index(d: date, mode: str, cache: dict[int, set[date]]) -> float:
    """0~1. weekday: 평일 1 / 토 0.35 / 일·공휴일 0.2. always: 0.95 상시. seasonal: 성수기 높음 + 주말 상승."""
    hol = is_holiday(d, cache)
    wd = d.weekday()
    if mode == "always":
        return 0.95 if not hol else 0.9
    if mode == "weekday":
        if hol or wd == 6:
            return 0.2
        if wd == 5:
            return 0.35
        return 1.0
    # seasonal (호텔): 7~8월·12월 성수기, 주말·공휴일 상승
    doy = d.timetuple().tm_yday
    season = 0.65 + 0.3 * (1 if d.month in (7, 8, 12) else 0) + 0.1 * (1 if d.month in (5, 10) else 0)
    weekend = 0.15 if (wd >= 4 or hol) else 0.0
    return min(1.0, season + weekend + 0.03 * ((doy % 7) / 7))


def daterange(start: date, days: int):
    for i in range(days):
        yield start + timedelta(days=i)
