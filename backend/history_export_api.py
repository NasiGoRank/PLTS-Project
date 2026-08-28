from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api import STORE, app, require_authenticated_user

PAGE_SIZE = 1000
MAX_DAILY_RANGE_DAYS = 3660
MAX_HOURLY_RANGE_DAYS = 366


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must use YYYY-MM-DD format") from exc


def _validate_range(start_date: str, end_date: str, resolution: str) -> tuple[date, date]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")

    range_days = (end - start).days + 1
    maximum = MAX_HOURLY_RANGE_DAYS if resolution == "hourly" else MAX_DAILY_RANGE_DAYS
    if range_days > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{resolution} exports are limited to {maximum} days per download",
        )
    return start, end


def _fetch_pages(build_query) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = build_query().range(offset, offset + PAGE_SIZE - 1).execute()
        batch = list(response.data or [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _daily_rows(
    *,
    start: date,
    end: date,
    station_id: str | None,
    platform: str | None,
) -> list[dict[str, Any]]:
    client, config = STORE._require()

    def build_query():
        query = (
            client.table(config.daily_table)
            .select(
                "platform,station_id,station_name,bucket_date,energy_kwh,"
                "revenue_amount,currency,source_scraped_at"
            )
            .gte("bucket_date", start.isoformat())
            .lte("bucket_date", end.isoformat())
            .order("bucket_date")
        )
        if station_id:
            query = query.eq("station_id", station_id)
        if platform:
            query = query.eq("platform", platform)
        return query

    with STORE._lock:
        return _fetch_pages(build_query)


def _hourly_rows(
    *,
    start: date,
    end: date,
    station_id: str | None,
    platform: str | None,
) -> list[dict[str, Any]]:
    client, config = STORE._require()
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)

    def build_query():
        query = (
            client.table(config.hourly_table)
            .select(
                "bucket_hour,platform,station_id,station_name,status,current_power_kw,"
                "daily_energy_kwh,monthly_energy_kwh,yearly_energy_kwh,cumulative_energy_kwh,"
                "daily_income,monthly_income,yearly_income,cumulative_income,currency,"
                "station_timezone,source_scraped_at"
            )
            .gte("bucket_hour", start_at.isoformat())
            .lt("bucket_hour", end_exclusive.isoformat())
            .order("bucket_hour")
        )
        if station_id:
            query = query.eq("station_id", station_id)
        if platform:
            query = query.eq("platform", platform)
        return query

    with STORE._lock:
        return _fetch_pages(build_query)


def _csv_response(rows: list[dict[str, Any]], columns: list[tuple[str, str]], filename: str) -> StreamingResponse:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([row.get(key) for key, _ in columns])

    content = "\ufeff" + output.getvalue()
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store, max-age=0",
        "X-Export-Row-Count": str(len(rows)),
    }
    return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8", headers=headers)


@app.get("/api/history/export")
def export_history(
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    resolution: str = Query(default="hourly", pattern="^(daily|hourly)$"),
    station_id: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    _: dict[str, Any] = Depends(require_authenticated_user),
) -> StreamingResponse:
    start, end = _validate_range(start_date, end_date, resolution)

    try:
        if resolution == "daily":
            rows = _daily_rows(start=start, end=end, station_id=station_id, platform=platform)
            columns = [
                ("bucket_date", "Date"),
                ("platform", "Platform"),
                ("station_id", "Station ID"),
                ("station_name", "Station Name"),
                ("energy_kwh", "Energy (kWh)"),
                ("revenue_amount", "Revenue"),
                ("currency", "Currency"),
                ("source_scraped_at", "Source Scraped At"),
            ]
        else:
            rows = _hourly_rows(start=start, end=end, station_id=station_id, platform=platform)
            columns = [
                ("bucket_hour", "Hour (UTC)"),
                ("platform", "Platform"),
                ("station_id", "Station ID"),
                ("station_name", "Station Name"),
                ("status", "Status"),
                ("current_power_kw", "Current Power (kW)"),
                ("daily_energy_kwh", "Daily Energy (kWh)"),
                ("monthly_energy_kwh", "Monthly Energy (kWh)"),
                ("yearly_energy_kwh", "Yearly Energy (kWh)"),
                ("cumulative_energy_kwh", "Cumulative Energy (kWh)"),
                ("daily_income", "Daily Revenue"),
                ("monthly_income", "Monthly Revenue"),
                ("yearly_income", "Yearly Revenue"),
                ("cumulative_income", "Cumulative Revenue"),
                ("currency", "Currency"),
                ("station_timezone", "Station Timezone"),
                ("source_scraped_at", "Latest Reading In Hour"),
            ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"History export is unavailable: {type(exc).__name__}: {exc}",
        ) from exc

    filename = f"plts-history-{resolution}-{start.isoformat()}-to-{end.isoformat()}.csv"
    return _csv_response(rows, columns, filename)
