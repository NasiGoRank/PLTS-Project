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


def _station_rows(payload: dict[str, Any]):
    by_site = payload.get("by_site") if isinstance(payload, dict) else None
    if not isinstance(by_site, dict):
        return

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
            yield str(platform), overview, station, str(station_id)


def _currency(platform: str, overview: dict[str, Any], station: dict[str, Any]) -> Any:
    value = station.get("income_currency") or overview.get("income_currency")
    if not value and platform == "huawei":
        return "IDR"
    return value


def extract_site_daily_rollups(payload: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Build one idempotent daily fact row for every normalized station."""
    timestamp = _timestamp(scraped_at)
    rows: list[dict[str, Any]] = []

    for platform, overview, station, station_id in _station_rows(payload) or []:
        local_date = timestamp.astimezone(_station_timezone(station.get("timezone"))).date()
        rows.append({
            "platform": platform,
            "station_id": station_id,
            "station_name": station.get("name") or station_id,
            "bucket_date": local_date.isoformat(),
            "energy_kwh": _number(station.get("daily_energy_kwh")),
            "revenue_amount": _number(station.get("daily_income")),
            "currency": _currency(platform, overview, station),
            "source_scraped_at": timestamp.astimezone(timezone.utc).isoformat(timespec="seconds"),
        })
    return rows


def extract_site_hourly_rollups(payload: dict[str, Any], scraped_at: str) -> list[dict[str, Any]]:
    """Build one station fact per UTC hour, updated by later scrapes in that hour."""
    timestamp = _timestamp(scraped_at).astimezone(timezone.utc)
    bucket_hour = timestamp.replace(minute=0, second=0, microsecond=0)
    rows: list[dict[str, Any]] = []

    for platform, overview, station, station_id in _station_rows(payload) or []:
        rows.append({
            "platform": platform,
            "station_id": station_id,
            "station_name": station.get("name") or station_id,
            "bucket_hour": bucket_hour.isoformat(timespec="seconds"),
            "status": station.get("status"),
            "current_power_kw": _number(station.get("current_power_kw")),
            "daily_energy_kwh": _number(station.get("daily_energy_kwh")),
            "monthly_energy_kwh": _number(station.get("monthly_energy_kwh")),
            "yearly_energy_kwh": _number(station.get("yearly_energy_kwh")),
            "cumulative_energy_kwh": _number(station.get("cumulative_energy_kwh")),
            "daily_income": _number(station.get("daily_income")),
            "monthly_income": _number(station.get("monthly_income")),
            "yearly_income": _number(station.get("yearly_income")),
            "cumulative_income": _number(station.get("cumulative_income")),
            "currency": _currency(platform, overview, station),
            "station_timezone": station.get("timezone"),
            "source_scraped_at": timestamp.isoformat(timespec="seconds"),
        })
    return rows
