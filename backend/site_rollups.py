from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _station_timezone(value: Any):
    text = str(value or "").strip()
    try:
        if text:
            return ZoneInfo(text)
    except ZoneInfoNotFoundError:
        pass

    normalized = text.upper().replace("UTC", "GMT")
    if normalized.startswith("GMT") and len(normalized) > 3:
        try:
            hours = int(normalized[3:])
            return timezone(timedelta(hours=hours))
        except ValueError:
            pass
    return timezone.utc


def extract_site_daily_rollups(payload: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Build one idempotent daily fact row for every normalized station."""
    timestamp = _timestamp(scraped_at)
    by_site = payload.get("by_site") if isinstance(payload, dict) else None
    if not isinstance(by_site, dict):
        return []

    rows: list[dict[str, Any]] = []
    for platform, site in by_site.items():
        if not isinstance(site, dict):
            continue
        overview = site.get("overview") if isinstance(site.get("overview"), dict) else {}
        stations = site.get("stations") if isinstance(site.get("stations"), list) else []
        for station in stations:
            if not isinstance(station, dict):
                continue
            station_id = station.get("station_id")
            if station_id in (None, ""):
                continue
            local_date = timestamp.astimezone(_station_timezone(station.get("timezone"))).date()
            currency = station.get("income_currency") or overview.get("income_currency")
            if not currency and platform == "huawei":
                currency = "IDR"
            rows.append({
                "platform": str(platform),
                "station_id": str(station_id),
                "station_name": station.get("name") or str(station_id),
                "bucket_date": local_date.isoformat(),
                "energy_kwh": _number(station.get("daily_energy_kwh")),
                "revenue_amount": _number(station.get("daily_income")),
                "currency": currency,
                "source_scraped_at": timestamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
            })
    return rows
