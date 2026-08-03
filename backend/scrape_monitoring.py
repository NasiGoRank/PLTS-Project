#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


DROP_REQUEST_HEADERS = {
    "content-length",
    "host",
    "connection",
    "accept-encoding",
    ":authority",
    ":method",
    ":path",
    ":scheme",
}

SENSITIVE_HEADERS = {
    "cookie",
    "authorization",
    "token",
    "x-token",
    "set-cookie",
}

AUTH_ERROR_CODES = {"900", "901", "902", "903", "999", "111005", 900, 901, 902, 903, 999, 111005}

KEHUA_PASSWORD_KEY = "clxslychxyl11988"
KEHUA_SIGN_KEY = "%vSBtRMV4F8mr#dYofsG3lJOBv5vw*fZ"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def safe_filename(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    cleaned = "".join(ch if ch in allowed else "_" for ch in value)
    return cleaned[:180] if cleaned else "unknown"


def try_parse_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def parse_form_payload(text: str) -> dict[str, str]:
    if not text:
        return {}
    try:
        parsed = parse_qs(text, keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}
    except Exception:
        return {}


def extract_cookie_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("cookies"), list):
        return raw["cookies"]
    return []


def cookie_domain_allowed(cookie_domain: str, allowed_domains: list[str]) -> bool:
    normalized = cookie_domain.lstrip(".")
    return any(normalized == item.lstrip(".") or normalized.endswith("." + item.lstrip(".")) for item in allowed_domains)


def load_cookies_into_session(session: requests.Session, cookies_file: Path | None, site: dict[str, Any]) -> dict[str, Any]:
    if not cookies_file or not cookies_file.exists():
        return {"loaded": 0, "token_found": False, "reason": "missing"}

    cookies = extract_cookie_list(load_json(cookies_file))
    allowed_domains = site.get("cookie_domains") or [site["base_domain"]]
    loaded = 0
    token_value = None
    token_cookie_name = None

    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        domain = str(cookie.get("domain") or site["base_domain"])
        if not cookie_domain_allowed(domain, allowed_domains):
            continue
        session.cookies.set(
            name=str(name),
            value=str(value),
            domain=domain,
            path=str(cookie.get("path") or "/"),
            secure=bool(cookie.get("secure", True)),
        )
        loaded += 1
        if str(name).lower() in {"token", "authorization", "auth", "access_token", "access-token"}:
            token_value = str(value)
            token_cookie_name = str(name)

    if token_value:
        session.headers.update({"Authorization": token_value, "token": token_value})

    return {"loaded": loaded, "token_found": bool(token_value), "token_cookie_name": token_cookie_name, "reason": "ok"}


def build_base_headers(site: dict[str, Any]) -> dict[str, str]:
    return {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.8",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "Origin": site["base_url"],
        "Pragma": "no-cache",
        "Referer": site.get("dashboard_url") or site["base_url"],
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    }


def huawei_password_login(session: requests.Session, site: dict[str, Any], username: str, password: str, timeout: int) -> dict[str, Any]:
    base_url = site["base_url"]
    session.get(f"{base_url}/rest/dp/pvms/pvmswebservice/v1/configcenter/oem", timeout=timeout)
    response = session.post(
        f"{base_url}/rest/dp/uidm/unisso/v1/validate-user?service=%2Frest%2Fdp%2Fuidm%2Fauth%2Fv1%2Fon-sso-credential-ready",
        json={"username": username, "password": password, "verifycode": ""},
        timeout=timeout,
    )
    body = response.json()
    redirect_url = (body.get("payload") or {}).get("redirectURL")
    if not redirect_url:
        return {"success": False, "status_code": response.status_code, "body": body, "reason": "missing_redirect"}

    redirection_address = quote(f"{base_url}/rest/pvms/web/login/v1/redirecturl?isFirst=false", safe="")
    final = session.get(f"{base_url}{redirect_url}&redirectionAddress={redirection_address}", timeout=timeout, allow_redirects=True)
    return {"success": response.ok and final.ok, "status_code": final.status_code, "final_url": final.url}


def aes_ecb_base64(value: str, key: str) -> str:
    cipher = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(value.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("ascii")


def kehua_password_cipher(password: str) -> str:
    return aes_ecb_base64(password, KEHUA_PASSWORD_KEY)


def kehua_request_sign(payload: dict[str, str], timestamp_ms: int | None = None) -> str:
    values = [f"{key}={payload[key]}" for key in sorted(payload) if payload[key] != ""]
    timestamp = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    if values:
        digest = hashlib.md5(",".join(values).encode("utf-8")).hexdigest()
        plaintext = f"{digest},{timestamp}"
    else:
        plaintext = str(timestamp)
    return aes_ecb_base64(plaintext, KEHUA_SIGN_KEY)


def kehua_form_headers(site: dict[str, Any], payload: dict[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": site["base_url"],
        "Referer": site.get("login_url") or site["base_url"],
        "clientType": "web",
        "locale": "en",
        "web_version": str(site.get("web_version") or "3.0.4"),
        "sign": kehua_request_sign(payload),
    }


def kehua_check_auth(session: requests.Session, site: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = site.get("auth_check")
    if not url:
        return {"checked": False, "success": None, "reason": "not_configured"}
    response = session.post(
        url,
        data="",
        headers=kehua_form_headers(site, {}),
        timeout=timeout,
        allow_redirects=False,
    )
    body = try_parse_json(response.text)
    app_code = body.get("code") if isinstance(body, dict) else None
    return {
        "checked": True,
        "success": response.ok and app_code in (0, "0"),
        "status_code": response.status_code,
        "app_code": app_code,
    }


def response_authorization(response: requests.Response, body: Any) -> str | None:
    for name, value in response.headers.items():
        if name.lower() == "authorization" and value:
            return str(value)
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict) and data.get("authorization"):
            return str(data["authorization"])
    return None


def kehua_password_login(session: requests.Session, site: dict[str, Any], username: str, password: str, timeout: int) -> dict[str, Any]:
    payload = {"username": username, "password": kehua_password_cipher(password)}
    response = session.post(
        site.get("password_login") or f"{site['base_url']}/necp/server-user/auth/web/login",
        data=urlencode(payload),
        headers=kehua_form_headers(site, payload),
        timeout=timeout,
        allow_redirects=False,
    )
    body = try_parse_json(response.text)
    app_code = body.get("code") if isinstance(body, dict) else None
    authorization = response_authorization(response, body)
    if authorization:
        session.headers.update({"Authorization": authorization})
        session.cookies.set("token", authorization, domain=site["base_domain"], path="/", secure=True)
    return {
        "success": response.ok and app_code in (0, "0") and bool(authorization),
        "status_code": response.status_code,
        "app_code": app_code,
        "authorization_found": bool(authorization),
    }


def refresh_huawei_roarand(session: requests.Session, site: dict[str, Any], timeout: int) -> dict[str, Any]:
    keep_alive = site.get("keep_alive")
    if not keep_alive:
        return {"success": False, "reason": "not_configured"}
    response = session.get(keep_alive, timeout=timeout, allow_redirects=False)
    body = try_parse_json(response.text)
    roarand = None
    if isinstance(body, dict):
        payload = body.get("payload")
        if isinstance(payload, str) and payload:
            roarand = payload
    if roarand:
        session.headers.update({"roarand": roarand})
    return {"success": bool(roarand), "status_code": response.status_code, "roarand_found": bool(roarand), "body": body}


def check_auth(session: requests.Session, site: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = site.get("auth_check")
    if not url:
        return {"checked": False, "success": None}
    response = session.get(url, timeout=timeout, allow_redirects=False)
    body = try_parse_json(response.text)
    success = False
    if isinstance(body, dict):
        success = body.get("code") in (0, "0") and body.get("payload") is True
    return {"checked": True, "success": success, "status_code": response.status_code, "body": body}


def prepare_session(
    site_name: str,
    site: dict[str, Any],
    cookies_file: Path | None,
    timeout: int,
    credentials: dict[str, Any] | None = None,
) -> tuple[requests.Session, dict[str, Any]]:
    session = requests.Session()
    session.headers.update(build_base_headers(site))
    meta: dict[str, Any] = {"cookies": load_cookies_into_session(session, cookies_file, site)}

    if site.get("auth_type") == "huawei_fusionsolar":
        auth = check_auth(session, site, timeout)
        meta["auth_check_before_login"] = auth
        username = os.getenv("HUAWEI_USERNAME")
        password = os.getenv("HUAWEI_PASSWORD")
        if not auth.get("success") and username and password:
            meta["password_login"] = huawei_password_login(session, site, username, password, timeout)
            meta["auth_check_after_login"] = check_auth(session, site, timeout)
        meta["keep_alive"] = refresh_huawei_roarand(session, site, timeout)

    if site.get("auth_type") == "kehua_energy":
        auth = kehua_check_auth(session, site, timeout)
        meta["auth_check_before_login"] = auth
        if not auth.get("success"):
            username = credentials.get("username") if credentials else os.getenv("KEHUA_USERNAME")
            password = credentials.get("password") if credentials else os.getenv("KEHUA_PASSWORD")
            if username and password:
                meta["password_login"] = kehua_password_login(session, site, username, password, timeout)
                meta["auth_check_after_login"] = kehua_check_auth(session, site, timeout)
            else:
                meta["password_login"] = {"success": False, "reason": "credentials_not_configured"}

    return session, meta


def load_kehua_accounts_from_env() -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    legacy_username = os.getenv("KEHUA_USERNAME", "").strip()
    legacy_password = os.getenv("KEHUA_PASSWORD", "").strip()
    if legacy_username and legacy_password:
        accounts.append({
            "name": "primary",
            "username": legacy_username,
            "password": legacy_password,
            "use_shared_cookies": True,
        })

    raw = os.getenv("KEHUA_ACCOUNTS_JSON", "").strip()
    if raw:
        try:
            configured = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"KEHUA_ACCOUNTS_JSON is not valid JSON: {exc.msg}") from exc
        if not isinstance(configured, list):
            raise RuntimeError("KEHUA_ACCOUNTS_JSON must be a JSON list")
        for index, item in enumerate(configured, start=1):
            if not isinstance(item, dict):
                raise RuntimeError(f"KEHUA_ACCOUNTS_JSON item {index} must be an object")
            username = str(item.get("username") or "").strip()
            password = str(item.get("password") or "").strip()
            if not username or not password:
                raise RuntimeError(f"KEHUA_ACCOUNTS_JSON item {index} requires username and password")
            account = {
                "name": str(item.get("name") or f"additional_{index}"),
                "username": username,
                "password": password,
            }
            for key in ("company_id", "station_id", "area_code", "company_name"):
                if item.get(key) not in (None, ""):
                    account[key] = str(item[key])
            accounts.append(account)

    unique: list[dict[str, Any]] = []
    seen_usernames: set[str] = set()
    for account in accounts:
        if account["username"] not in seen_usernames:
            unique.append(account)
            seen_usernames.add(account["username"])
    return unique


def prepare_kehua_account_call(call: dict[str, Any], account: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(call)
    prepared["headers"] = dict(call.get("headers", {}) or {})
    payload = parse_form_payload(str(call.get("payload_raw") or ""))
    replacements = {
        "companyId": account.get("company_id"),
        "stationId": account.get("station_id"),
        "areaCode": account.get("area_code"),
        "companyName": account.get("company_name"),
    }
    for field, value in replacements.items():
        if field in payload and value not in (None, ""):
            payload[field] = str(value)
    prepared["payload_raw"] = urlencode(payload)
    return prepared


def build_request_headers(session: requests.Session, call: dict[str, Any]) -> dict[str, str]:
    headers = dict(call.get("headers", {}) or {})
    for key in list(headers):
        lower = key.lower()
        if lower in DROP_REQUEST_HEADERS or lower in SENSITIVE_HEADERS:
            headers.pop(key, None)
    # Dynamic Huawei session nonce must come from keep-alive, not stale HAR.
    if "roarand" in session.headers:
        headers["roarand"] = session.headers["roarand"]
    return headers


def prepare_replay_call(
    call: dict[str, Any],
    current_time: datetime | None = None,
    *,
    sign_timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Refresh captured period fields and request signatures before replay."""
    prepared = dict(call)
    prepared["headers"] = dict(call.get("headers", {}) or {})
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    jakarta_now = now.astimezone(timezone(timedelta(hours=7)))

    if call.get("site") == "huawei" and call.get("name") == "home-station-kpi-chart":
        payload = try_parse_json(call.get("payload_raw") or "")
        if isinstance(payload, dict):
            stat_dim = str(payload.get("statDim") or "")
            if stat_dim == "4":
                target = jakarta_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif stat_dim in {"5", "6"}:
                target = jakarta_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                target = None
            if target is not None:
                payload["statTimeStr"] = target.strftime("%Y-%m-%d")
                payload["statTime"] = int(target.timestamp() * 1000)
                prepared["payload_raw"] = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    if call.get("site") == "kehua":
        payload = parse_form_payload(str(prepared.get("payload_raw") or ""))
        if "targetTime" in payload:
            dimension = str(payload.get("dimension") or "")
            if dimension == "2":
                payload["targetTime"] = jakarta_now.strftime("%Y-%m")
            elif dimension == "3":
                payload["targetTime"] = jakarta_now.strftime("%Y")
            elif dimension == "4":
                payload["targetTime"] = ""
            else:
                payload["targetTime"] = jakarta_now.strftime("%Y-%m-%d")
        prepared["payload_raw"] = urlencode(payload)
        prepared["headers"]["sign"] = kehua_request_sign(payload, sign_timestamp_ms)

    return prepared


def summarize_response(response_body: Any) -> dict[str, Any]:
    app_code = None
    app_message = None
    data_present = False
    payload_present = False
    auth_error = False

    if isinstance(response_body, dict):
        app_code = response_body.get("code", response_body.get("resultCode"))
        app_message = response_body.get("message", response_body.get("resultMsg"))
        data_present = "data" in response_body
        payload_present = "payload" in response_body
        auth_error = app_code in AUTH_ERROR_CODES or "auth" in str(app_message).lower()

    return {
        "app_code": app_code,
        "app_message": app_message,
        "data_present": data_present,
        "payload_present": payload_present,
        "auth_error": auth_error,
    }


def replay_call(session: requests.Session, call: dict[str, Any], timeout: int) -> dict[str, Any]:
    call = prepare_replay_call(call)
    method = str(call.get("method", "GET")).upper()
    payload_raw = call.get("payload_raw") or ""
    request_kwargs: dict[str, Any] = {
        "url": call["url"],
        "headers": build_request_headers(session, call),
        "timeout": timeout,
        "allow_redirects": False,
    }
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        request_kwargs["data"] = payload_raw.encode("utf-8") if payload_raw else b""

    try:
        response = session.request(method, **request_kwargs)
        if response.status_code in {429, 503}:
            time.sleep(1.0)
            response = session.request(method, **request_kwargs)
        body = try_parse_json(response.text)
        summary = summarize_response(body)
        redirected_to_login = response.status_code in {301, 302, 303, 307, 308} and "login" in response.headers.get("location", "")
        html_login = isinstance(body, str) and "login" in body[:1000].lower() and "<!doctype html" in body[:100].lower()
        success = response.ok and not redirected_to_login and not html_login and not summary["auth_error"]

        return {
            "id": call.get("id"),
            "name": call.get("name"),
            "method": method,
            "url": call.get("url"),
            "path": urlparse(call.get("url", "")).path,
            "payload_raw": payload_raw,
            "success": success,
            "http_status": response.status_code,
            "location": response.headers.get("location"),
            "content_type": response.headers.get("content-type"),
            "auth_error": bool(summary["auth_error"] or redirected_to_login or html_login),
            "app_code": summary["app_code"],
            "app_message": summary["app_message"],
            "data_present": summary["data_present"],
            "payload_present": summary["payload_present"],
            "response_body": body,
            "response_text_preview": response.text[:1000] if not isinstance(body, (dict, list)) else None,
            "error": None,
        }
    except Exception as exc:
        return {
            "id": call.get("id"),
            "name": call.get("name"),
            "method": method,
            "url": call.get("url"),
            "payload_raw": payload_raw,
            "success": False,
            "http_status": None,
            "auth_error": False,
            "response_body": None,
            "error": repr(exc),
        }


def huawei_energy_balance_calls(
    site: dict[str, Any],
    station_list_call: dict[str, Any],
    current_time: datetime | None = None,
) -> list[dict[str, Any]]:
    data = response_data(station_list_call)
    items = data.get("list") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    jakarta = timezone(timedelta(hours=7))
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(jakarta).replace(hour=0, minute=0, second=0, microsecond=0)
    periods = (
        ("daily", "2", today),
        ("monthly", "4", today.replace(day=1)),
        ("yearly", "5", today.replace(month=1, day=1)),
    )

    calls = []
    for item in items:
        if not isinstance(item, dict) or not item.get("dn"):
            continue
        station_dn = str(item["dn"])
        for period_name, time_dim, target in periods:
            station_query = {
                "stationDn": station_dn,
                "timeDim": time_dim,
                "timeZone": "7.0",
                "timeZoneStr": "Asia/Jakarta",
                "queryTime": str(int(target.timestamp() * 1000)),
                "dateStr": target.strftime("%Y-%m-%d 00:00:00"),
                "_": str(int(time.time() * 1000)),
            }
            calls.append({
                "id": f"{period_name}_energy_balance_{station_dn.replace('=', '_')}",
                "site": "huawei",
                "name": f"energy-balance-{period_name}",
                "method": "GET",
                "url": f"{site['base_url']}/rest/pvms/web/station/v3/overview/energy-balance?{urlencode(station_query)}",
                "headers": {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "en-US,en;q=0.8",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "Referer": site.get("dashboard_url") or site["base_url"],
                    "X-Requested-With": "XMLHttpRequest",
                    "x-timezone-offset": "420",
                },
                "payload_raw": "",
            })
    return calls


def normalize_latest(results: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, Any] = {"schema": "monitoring_current.v2", "by_site": {}, "updated_at": now_iso()}
    for site_result in results:
        site_name = site_result["site"]
        account_results = site_result.get("account_results")
        if site_name == "kehua" and isinstance(account_results, list) and account_results:
            normalized_accounts = [build_normalized_site(item) for item in account_results]
            latest["by_site"][site_name] = merge_normalized_sites(normalized_accounts)
        else:
            latest["by_site"][site_name] = build_normalized_site(site_result)
    return latest


def merge_normalized_sites(sites: list[dict[str, Any]]) -> dict[str, Any]:
    if len(sites) == 1:
        site = sites[0]
        for station in site.get("stations", []):
            station.setdefault("charts", site.get("charts", {}))
        return site

    stations_by_id: dict[str, dict[str, Any]] = {}
    for site in sites:
        for station in site.get("stations", []):
            key = str(station.get("station_id") or station.get("name") or "")
            if not key:
                continue
            current = stations_by_id.setdefault(key, {})
            current.update({field: value for field, value in station.items() if value not in (None, "")})
            current.setdefault("charts", site.get("charts", {}))

    sum_fields = {
        "station_count", "connected_station_count", "disconnected_station_count",
        "trouble_station_count", "no_device_station_count", "capacity_kwp",
        "current_power_kw", "daily_energy_kwh", "monthly_energy_kwh",
        "yearly_energy_kwh", "cumulative_energy_kwh", "monthly_income",
        "cumulative_income", "inverter_count", "monthly_alarm_count",
        "today_alarm_count", "last_month_alarm_count",
    }
    overview: dict[str, Any] = {}
    for field in sum_fields:
        values = [site.get("overview", {}).get(field) for site in sites]
        numbers = [value for value in values if isinstance(value, (int, float))]
        if numbers:
            overview[field] = sum(numbers)
    overview["station_count"] = len(stations_by_id)
    for site in sites:
        currency = site.get("overview", {}).get("income_currency")
        if currency:
            overview.setdefault("income_currency", currency)

    scrape_status = {
        field: sum(int(site.get("scrape_status", {}).get(field) or 0) for site in sites)
        for field in ("success_count", "failed_count", "auth_error_count")
    }

    devices: dict[str, Any] = {}
    for list_name, identity_fields in (
        ("devices", ("device_id", "sn")),
        ("collectors", ("collector_id", "sn")),
    ):
        unique_items: dict[str, dict[str, Any]] = {}
        for site in sites:
            for item in site.get("devices", {}).get(list_name, []):
                key = next((str(item.get(field)) for field in identity_fields if item.get(field) not in (None, "")), "")
                if key:
                    unique_items[key] = item
        if unique_items:
            devices[list_name] = list(unique_items.values())
    for field in ("device_count", "normal_count", "abnormal_count", "online_count", "offline_count"):
        values = [site.get("devices", {}).get(field) for site in sites]
        numbers = [value for value in values if isinstance(value, (int, float))]
        if numbers:
            devices[field] = sum(numbers)

    events = [
        event
        for site in sites
        for event in site.get("alarms", {}).get("events", [])
        if isinstance(event, dict)
    ]
    alarms = {
        "unsolved_count": sum(int(site.get("alarms", {}).get("unsolved_count") or 0) for site in sites),
        "event_total": sum(int(site.get("alarms", {}).get("event_total") or 0) for site in sites),
        "events": events,
    }

    return {
        "platform": "kehua",
        "updated_at": max(str(site.get("updated_at") or "") for site in sites),
        "scrape_status": scrape_status,
        "overview": overview,
        "stations": list(stations_by_id.values()),
        "alarms": alarms,
        "devices": devices,
        "charts": sites[0].get("charts", {}),
    }


def response_data(call: dict[str, Any]) -> Any:
    body = call.get("response_body")
    if isinstance(body, dict) and "data" in body:
        return body.get("data")
    return body


def calls_by_name(calls: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        grouped.setdefault(str(call.get("name")), []).append(call)
    return grouped


def first_data(grouped: dict[str, list[dict[str, Any]]], name: str) -> Any:
    calls = grouped.get(name) or []
    return response_data(calls[0]) if calls else None


def to_float(value: Any) -> float | None:
    if value is None or value == "" or value == "null":
        return None
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    number = to_float(value)
    return int(number) if number is not None else None


def energy_to_kwh(value: Any, unit: Any = None) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    unit_text = str(unit or "kWh").lower()
    if unit_text == "mwh":
        return round(number * 1000, 4)
    if unit_text == "gwh":
        return round(number * 1000000, 4)
    return number


def power_to_kw(value: Any, unit: Any = None) -> float | None:
    number = to_float(value)
    if number is None:
        return None
    unit_text = str(unit or "kW").lower()
    if unit_text == "mw":
        return round(number * 1000, 4)
    if unit_text == "w":
        return round(number / 1000, 4)
    return number


def compact_non_null(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def build_normalized_site(site_result: dict[str, Any]) -> dict[str, Any]:
    site_name = site_result["site"]
    calls = site_result["calls"]
    grouped = calls_by_name(calls)
    if site_name == "huawei":
        stations = normalize_huawei_stations(grouped)
        overview = normalize_huawei_overview(grouped, stations)
        alarms = normalize_huawei_alarms(grouped)
        charts = normalize_huawei_charts(grouped)
        devices = normalize_huawei_devices(grouped, stations)
    elif site_name == "kehua":
        stations = normalize_kehua_stations(grouped)
        overview = normalize_kehua_overview(grouped, stations)
        alarms = normalize_kehua_alarms(grouped)
        charts = normalize_kehua_charts(grouped)
        devices = normalize_kehua_devices(grouped)
    else:
        stations = []
        overview = {}
        alarms = {}
        charts = {}
        devices = {}

    return {
        "platform": site_name,
        "updated_at": site_result["scraped_at"],
        "scrape_status": {
            "success_count": site_result["summary"]["success_count"],
            "failed_count": site_result["summary"]["failed_count"],
            "auth_error_count": site_result["summary"]["auth_error_count"],
        },
        "overview": overview,
        "stations": stations,
        "alarms": alarms,
        "devices": devices,
        "charts": charts,
    }


def normalize_huawei_stations(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    station_list = first_data(grouped, "station-list")
    kpi_by_station = huawei_kpi_by_station(grouped)
    energy_balance_by_station = huawei_energy_balance_by_station(grouped)
    items = []
    if isinstance(station_list, dict):
        items = station_list.get("list") or []

    stations = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        station = compact_non_null({
            "platform": "huawei",
            "station_id": str(item.get("dn") or item.get("dnId")),
            "station_dn": item.get("dn"),
            "station_numeric_id": item.get("dnId"),
            "name": item.get("name"),
            "status": normalize_status(item.get("plantStatus")),
            "status_raw": item.get("plantStatus"),
            "capacity_kwp": power_to_kw(item.get("installedCapacity"), "kW"),
            "current_power_kw": power_to_kw(item.get("currentPower"), "kW"),
            "inverter_power_kw": power_to_kw(item.get("inverterPower"), "kW"),
            "daily_energy_kwh": energy_to_kwh(item.get("dailyEnergy"), "kWh"),
            "monthly_energy_kwh": energy_to_kwh(item.get("monthEnergy"), "kWh"),
            "yearly_energy_kwh": energy_to_kwh(item.get("yearEnergy"), "kWh"),
            "cumulative_energy_kwh": energy_to_kwh(item.get("cumulativeEnergy"), "kWh"),
            "full_power_hours": to_float(item.get("eqPowerHours")),
            "self_use_energy_kwh": energy_to_kwh(item.get("dailySelfUseEnergy"), "kWh"),
            "grid_connected_at": item.get("gridConnectedTime"),
            "running_start_at": item.get("runningStartTime"),
            "timezone": item.get("timeZone"),
            "latitude": to_float(item.get("latitude")),
            "longitude": to_float(item.get("longitude")),
            "address": item.get("plantAddress"),
            "has_backup_box": item.get("existBackupBox"),
            "has_meter": None,
            "has_energy_storage": item.get("energyStore") not in (None, "UnAvailable", "null"),
        })
        station.update(kpi_by_station.get(str(item.get("dn") or ""), {}))
        station.update(energy_balance_by_station.get(str(item.get("dn") or ""), {}))
        stations.append(station)
    return stations


def huawei_energy_balance_by_station(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_station: dict[str, dict[str, Any]] = {}
    for call in grouped.get("energy-balance-daily") or []:
        parsed = urlparse(call.get("url") or "")
        query = parse_qs(parsed.query)
        station_dn = (query.get("stationDn") or [None])[0]
        data = response_data(call)
        if not station_dn or not isinstance(data, dict):
            continue
        station = by_station.setdefault(str(station_dn), {"energy_charts": {}})
        station["daily_power_5min"] = compact_non_null({
                "unit": "kW",
                "time_dim": "day_5min",
                "date": (query.get("dateStr") or [None])[0],
                "x": data.get("xAxis"),
                "generation_power_kw": numeric_series(data.get("productPower")),
                "use_power_kw": numeric_series(data.get("usePower")),
                "grid_power_kw": numeric_series(data.get("gridPower")),
                "buy_power_kw": numeric_series(data.get("buyPower")),
                "feed_in_power_kw": numeric_series(data.get("ongridPower") or data.get("onGridPower")),
                "charge_power_kw": numeric_series(data.get("chargePower")),
                "discharge_power_kw": numeric_series(data.get("dischargePower")),
            })

    for call_name, chart_key in (("energy-balance-monthly", "daily"), ("energy-balance-yearly", "monthly")):
        for call in grouped.get(call_name) or []:
            parsed = urlparse(call.get("url") or "")
            query = parse_qs(parsed.query)
            station_dn = (query.get("stationDn") or [None])[0]
            data = response_data(call)
            if not station_dn or not isinstance(data, dict):
                continue
            labels = data.get("xAxis")
            values = numeric_series(data.get("productPower"))
            if not isinstance(labels, list) or not values or len(labels) != len(values):
                continue
            if not any(value is not None for value in values):
                continue
            station = by_station.setdefault(str(station_dn), {"energy_charts": {}})
            station.setdefault("energy_charts", {})[chart_key] = {
                "labels": [str(label) for label in labels],
                "values": values,
            }
    return by_station


def huawei_kpi_by_station(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_station: dict[str, dict[str, Any]] = {}
    current_year = datetime.now().year
    current_month = datetime.now().month

    for call in grouped.get("home-station-kpi-chart") or []:
        payload = try_parse_json(call.get("payload_raw"))
        if not isinstance(payload, dict):
            continue
        mo_list = payload.get("moList")
        station_dn = None
        if isinstance(mo_list, list) and mo_list and isinstance(mo_list[0], dict):
            station_dn = mo_list[0].get("moString")
        if not station_dn:
            continue

        data = response_data(call)
        if not isinstance(data, dict):
            continue

        stat_dim = str(payload.get("statDim") or "")
        stat_time = str(payload.get("statTimeStr") or "")
        year = to_int(stat_time[:4]) if len(stat_time) >= 4 else None
        month = to_int(stat_time[5:7]) if len(stat_time) >= 7 else None
        station = by_station.setdefault(str(station_dn), {"revenue_charts": {}, "energy_charts": {}})

        station["currency_code"] = data.get("currency")
        station["is_price_configured"] = data.get("isPriceConfigured")
        station["has_meter"] = data.get("hasMeter")

        chart = data.get("data") if isinstance(data.get("data"), dict) else None
        revenue_chart = huawei_chart_from_axis(chart, "y2Axis")
        energy_chart = huawei_energy_chart(chart)

        if stat_dim == "4":
            if year == current_year and month == current_month:
                station["monthly_income"] = to_float(data.get("curmonthIncome") or data.get("totalIncome"))
                daily_income = huawei_current_day_value(revenue_chart, stat_time)
                if daily_income is not None:
                    station["daily_income"] = daily_income
                if revenue_chart:
                    station["revenue_charts"]["daily"] = revenue_chart
                if energy_chart:
                    station["energy_charts"]["daily"] = energy_chart
        elif stat_dim == "5":
            if year == current_year or "yearly_income" not in station:
                station["yearly_income"] = to_float(data.get("curyearIncome") or data.get("totalIncome"))
                if revenue_chart:
                    station["revenue_charts"]["monthly"] = revenue_chart
                if energy_chart:
                    station["energy_charts"]["monthly"] = energy_chart
        elif stat_dim == "6":
            cumulative = to_float(data.get("totalIncome"))
            current = station.get("cumulative_income")
            if cumulative is not None and (current is None or cumulative > current):
                station["cumulative_income"] = cumulative
                if revenue_chart:
                    station["revenue_charts"]["yearly"] = revenue_chart
                if energy_chart:
                    station["energy_charts"]["yearly"] = energy_chart

    return {key: compact_non_null(value) for key, value in by_station.items()}


def huawei_chart_from_axis(chart: dict[str, Any] | None, axis_key: str) -> dict[str, Any] | None:
    if not isinstance(chart, dict):
        return None
    labels = chart.get("xAxis")
    values = chart.get(axis_key)
    if not isinstance(labels, list) or not isinstance(values, list):
        return None
    numeric = [to_float(item) for item in values]
    if not any(value is not None for value in numeric):
        return None
    return {"labels": labels, "values": numeric}


def huawei_energy_chart(chart: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(chart, dict):
        return None
    labels = chart.get("xAxis")
    y_axis = chart.get("yAxis")
    if not isinstance(labels, list) or not isinstance(y_axis, list):
        return None
    series = y_axis if y_axis and isinstance(y_axis[0], list) else [y_axis]
    for item in series:
        if not isinstance(item, list):
            continue
        numeric = [to_float(value) for value in item]
        if any(value is not None for value in numeric):
            return {"labels": labels, "values": numeric}
    return None


def huawei_current_day_value(chart: dict[str, Any] | None, stat_time: str) -> float | None:
    if not isinstance(chart, dict):
        return None
    labels = chart.get("labels")
    values = chart.get("values")
    if not isinstance(labels, list) or not isinstance(values, list):
        return None
    today = datetime.now()
    if stat_time.startswith(f"{today.year:04d}-{today.month:02d}"):
        day_label = f"{today.day:02d}"
        if day_label in labels:
            value = values[labels.index(day_label)]
            if value is not None:
                return value
    for value in reversed(values):
        if value is not None:
            return value
    return None


def normalize_huawei_overview(grouped: dict[str, list[dict[str, Any]]], stations: list[dict[str, Any]]) -> dict[str, Any]:
    total = first_data(grouped, "total-real-kpi")
    total_data = total if isinstance(total, dict) else {}
    status = first_data(grouped, "station-status-count")
    status_data = status if isinstance(status, dict) else {}
    return compact_non_null({
        "station_count": len(stations),
        "connected_station_count": to_int(status_data.get("connected") if isinstance(status_data, dict) else None),
        "disconnected_station_count": to_int(status_data.get("disconnected") if isinstance(status_data, dict) else None),
        "trouble_station_count": to_int(status_data.get("trouble") if isinstance(status_data, dict) else None),
        "capacity_kwp": sum_numbers(stations, "capacity_kwp"),
        "inverter_power_kw": power_to_kw(total_data.get("inverterPower"), "kW") if isinstance(total_data, dict) else None,
        "current_power_kw": power_to_kw(total_data.get("currentPower"), "kW") if isinstance(total_data, dict) else None,
        "daily_energy_kwh": energy_to_kwh(total_data.get("dailyEnergy"), "kWh") if isinstance(total_data, dict) else None,
        "monthly_energy_kwh": sum_numbers(stations, "monthly_energy_kwh"),
        "yearly_energy_kwh": sum_numbers(stations, "yearly_energy_kwh"),
        "cumulative_energy_kwh": energy_to_kwh(total_data.get("cumulativeEnergy"), "kWh") if isinstance(total_data, dict) else None,
        "daily_income": to_float(total_data.get("dailyIncome")) if isinstance(total_data, dict) else None,
        "monthly_income": sum_numbers(stations, "monthly_income"),
        "yearly_income": sum_numbers(stations, "yearly_income"),
        "cumulative_income": sum_numbers(stations, "cumulative_income"),
        "currency_code": total_data.get("currency") if isinstance(total_data, dict) else None,
    })


def normalize_huawei_alarms(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    alarm = first_data(grouped, "statistic")
    data = alarm.get("data") if isinstance(alarm, dict) else alarm
    return {"raw_summary": data} if data is not None else {}


def normalize_huawei_devices(grouped: dict[str, list[dict[str, Any]]], stations: list[dict[str, Any]]) -> dict[str, Any]:
    return compact_non_null({
        "inverter_count": None,
        "station_count": len(stations),
        "has_energy_flow": bool(grouped.get("energy-flow")),
        "has_energy_balance": bool(grouped.get("energy-balance")),
    })


def normalize_huawei_charts(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    balance = first_data(grouped, "energy-balance")
    balance_data = balance if isinstance(balance, dict) else None
    chart = first_data(grouped, "home-station-kpi-chart")
    chart_data = chart if isinstance(chart, dict) else None
    return compact_non_null({
        "generation_power_series": extract_huawei_series(balance_data, "productPower"),
        "use_power_series": extract_huawei_series(balance_data, "usePower"),
        "x_axis": balance_data.get("xAxis") if isinstance(balance_data, dict) else None,
        "kpi_chart": chart_data,
    })


def normalize_kehua_stations(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    def merge(station_id: Any, values: dict[str, Any]) -> None:
        key = str(station_id or values.get("station_id") or values.get("name") or "")
        if not key:
            return
        current = by_id.setdefault(key, {"platform": "kehua", "station_id": key})
        for field, value in values.items():
            if value not in (None, ""):
                current[field] = value

    for item in list_from_data(first_data(grouped, "listStationLike")):
        merge(item.get("stationId"), {
            "station_id": str(item.get("stationId")),
            "name": item.get("stationName"),
            "area_code": item.get("areaCode"),
        })

    card = first_data(grouped, "listStationCardInfoByCondition")
    card_result = card.get("result") if isinstance(card, dict) else []
    for item in card_result if isinstance(card_result, list) else []:
        merge(item.get("stationId"), {
            "station_id": str(item.get("stationId")),
            "name": item.get("stationName"),
            "company_id": item.get("companyId"),
            "area_code": item.get("areaCode"),
            "status": normalize_status(item.get("stationStatus"), platform="kehua"),
            "status_raw": item.get("stationStatus"),
            "capacity_kwp": power_to_kw(item.get("capacity"), "kW"),
            "daily_energy_kwh": energy_to_kwh(item.get("dayElec"), "kWh"),
            "monthly_energy_kwh": energy_to_kwh(item.get("monthElec"), "kWh"),
            "yesterday_energy_kwh": energy_to_kwh(item.get("yesterdayElec"), "kWh"),
            "address": item.get("address"),
            "grid_type": item.get("gridType"),
            "station_type": item.get("stationTypeName") or item.get("stationType"),
            "alarm_count": to_int(item.get("alarmNumber")),
            "soc_percent": to_float(item.get("soc")),
            "battery_power_kw": power_to_kw(item.get("batteryPower"), "kW"),
            "has_meter": bool(item.get("haveMeter")),
            "has_pv": item.get("havePv") == 0 or bool(item.get("havePv")),
        })

    info = first_data(grouped, "listStationInfoByCondition")
    result = info.get("result") if isinstance(info, dict) else []
    for item in result if isinstance(result, list) else []:
        merge(item.get("stationId"), {
            "station_id": str(item.get("stationId")),
            "name": item.get("stationName"),
            "company_id": item.get("companyId"),
            "area_code": item.get("areaCode"),
            "status": normalize_status(item.get("stationStatus"), platform="kehua"),
            "status_raw": item.get("stationStatus"),
            "capacity_kwp": power_to_kw(item.get("capacity"), "kW"),
            "current_power_kw": power_to_kw(item.get("activePower"), "kW"),
            "daily_energy_kwh": energy_to_kwh(item.get("dayElec"), "kWh"),
            "monthly_energy_kwh": energy_to_kwh(item.get("monthElec"), "kWh"),
            "yearly_energy_kwh": energy_to_kwh(item.get("yearElec"), "kWh"),
            "full_power_hours": to_float(item.get("fullHours")),
            "station_type": item.get("stationTypeName") or item.get("stationType"),
            "soc_percent": to_float(item.get("soc")),
            "battery_power_kw": power_to_kw(item.get("batteryPower"), "kW"),
            "has_meter": bool(item.get("haveMeter")),
            "has_pv": item.get("havePv") == 0 or bool(item.get("havePv")),
        })

    for item in list_from_data(first_data(grouped, "stationFullCapacityRanking")):
        merge(item.get("stationId"), {
            "station_id": str(item.get("stationId")),
            "name": item.get("stationName"),
            "status": normalize_status(item.get("stationStatus"), platform="kehua"),
            "status_raw": item.get("stationStatus"),
            "avg_daily_full_hours": to_float(item.get("avgDailyFullHours")),
            "total_full_hours": to_float(item.get("totalFullHours")),
        })

    station_info = first_data(grouped, "getStationInfo")
    info = station_info.get("stationInfo") if isinstance(station_info, dict) else None
    if isinstance(info, dict):
        merge(info.get("stationId") or only_station_key(by_id), {
            "name": info.get("stationName"),
            "area_code": info.get("areaCode"),
            "station_type": info.get("stationType"),
            "grid_type": info.get("gridType"),
            "capacity_kwp": power_to_kw(info.get("capacity"), "kW"),
            "latitude": to_float(info.get("latitude")),
            "longitude": to_float(info.get("longitude")),
            "address": info.get("address"),
            "account_name": info.get("accountName"),
            "email": info.get("email"),
            "company_name": info.get("companyName"),
            "timezone": info.get("timeZone") or info.get("offset"),
            "created_at": info.get("createTime"),
        })

    topology = first_data(grouped, "getTopologyInfo")
    if isinstance(topology, dict):
        merge(only_station_key(by_id), {
            "current_power_kw": power_to_kw(topology.get("outputPower"), topology.get("outputPowerUnit")),
            "pv_power_kw": power_to_kw(topology.get("pvPower"), topology.get("pvPowerUnit")),
            "grid_power_kw": power_to_kw(topology.get("gridPower"), topology.get("gridPowerUnit")),
            "load_power_kw": power_to_kw(topology.get("loadPower"), topology.get("loadPowerUnit")),
            "battery_power_kw": power_to_kw(topology.get("batteryPower"), topology.get("batteryPowerUnit")),
            "output_power_kw": power_to_kw(topology.get("outputPower"), topology.get("outputPowerUnit")),
            "soc_percent": to_float(topology.get("soc")),
            "energy_flow": compact_non_null({
                "pv_power_kw": power_to_kw(topology.get("pvPower"), topology.get("pvPowerUnit")),
                "grid_power_kw": power_to_kw(topology.get("gridPower"), topology.get("gridPowerUnit")),
                "load_power_kw": power_to_kw(topology.get("loadPower"), topology.get("loadPowerUnit")),
                "battery_power_kw": power_to_kw(topology.get("batteryPower"), topology.get("batteryPowerUnit")),
                "diesel_generator_power_kw": power_to_kw(topology.get("dieselGeneratorPower"), topology.get("dieselGeneratorPowerUnit")),
                "output_power_kw": power_to_kw(topology.get("outputPower"), topology.get("outputPowerUnit")),
                "soc_percent": to_float(topology.get("soc")),
            }),
        })

    device_status = first_data(grouped, "getDeviceStatus")
    if isinstance(device_status, dict):
        normal_devices = to_int(device_status.get("normal")) or 0
        exception_devices = to_int(device_status.get("exception")) or 0
        offline_devices = to_int(device_status.get("offLine") or device_status.get("offline")) or 0
        status = None
        if normal_devices > 0:
            status = "normal"
        elif exception_devices > 0:
            status = "abnormal"
        elif offline_devices > 0:
            status = "offline"
        if status:
            merge(only_station_key(by_id), {
                "status": status,
                "status_source": "getDeviceStatus",
                "device_status_raw": device_status,
            })

    station_key_data = station_key_data_map(grouped.get("getKeyData") or [])
    if station_key_data:
        merge(only_station_key(by_id), {
            "daily_energy_kwh": energy_to_kwh(get_value_unit(station_key_data, "Daily Generation", "value"), get_value_unit(station_key_data, "Daily Generation", "unit")),
            "cumulative_energy_kwh": energy_to_kwh(get_value_unit(station_key_data, "Cumulative Generation", "value"), get_value_unit(station_key_data, "Cumulative Generation", "unit")),
            "daily_income": to_float(get_value_unit(station_key_data, "Daily Revenue", "value")),
            "cumulative_income": to_float(get_value_unit(station_key_data, "Cumulative Revenue", "value")),
            "full_power_hours": to_float(get_value_unit(station_key_data, "Full-Load Hours (Today)", "value")),
            "capacity_kwp": power_to_kw(get_value_unit(station_key_data, "Installed capacity", "value"), get_value_unit(station_key_data, "Installed capacity", "unit")),
        })

    weather = first_data(grouped, "getWeatherForecast")
    if isinstance(weather, list):
        merge(only_station_key(by_id), {"weather_forecast": [normalize_weather_item(item) for item in weather if isinstance(item, dict)]})

    company_key_data = key_data_map(first_data(grouped, "getKeyData"))
    overview_power = first_data(grouped, "overviewOfPowerGeneration")
    only_key = only_station_key(by_id)
    if only_key:
        merge(only_key, {
            "monthly_energy_kwh": energy_to_kwh(get_value_unit(company_key_data, "Monthly Gen.", "value"), get_value_unit(company_key_data, "Monthly Gen.", "unit")),
            "yearly_energy_kwh": energy_to_kwh(get_value_unit(company_key_data, "Annual Gen.", "value"), get_value_unit(company_key_data, "Annual Gen.", "unit")),
            "cumulative_energy_kwh": energy_to_kwh(get_value_unit(company_key_data, "Cumulative Generation", "value"), get_value_unit(company_key_data, "Cumulative Generation", "unit")),
            "monthly_income": to_float(nested_value(overview_power, ["income", "monthElectricity", "value"])),
            "cumulative_income": to_float(nested_value(overview_power, ["income", "totalElectricity", "value"])),
            "income_currency": nested_value(overview_power, ["income", "monthElectricity", "unit"]) or nested_value(overview_power, ["income", "totalElectricity", "unit"]),
        })

    return list(by_id.values())


def normalize_kehua_overview(grouped: dict[str, list[dict[str, Any]]], stations: list[dict[str, Any]]) -> dict[str, Any]:
    power = first_data(grouped, "overviewOfPowerGeneration")
    key_data = key_data_map(first_data(grouped, "getKeyData"))
    status = first_data(grouped, "getStationStatusCount")
    status_company = first_data(grouped, "ListStationStatusCount")
    return compact_non_null({
        "station_count": to_int(get_value_unit(key_data, "Plants", "value")) or len(stations),
        "connected_station_count": to_int(status.get("normal") if isinstance(status, dict) else None),
        "disconnected_station_count": to_int(status.get("offline") if isinstance(status, dict) else None),
        "trouble_station_count": to_int(status.get("abnormal") if isinstance(status, dict) else None),
        "no_device_station_count": to_int(status.get("nodevice") if isinstance(status, dict) else None),
        "capacity_kwp": power_to_kw(nested_value(power, ["installedCapacity", "value"]), nested_value(power, ["installedCapacity", "unit"])),
        "current_power_kw": sum_numbers(stations, "current_power_kw"),
        "daily_energy_kwh": energy_to_kwh(get_value_unit(key_data, "Daily Generation", "value"), get_value_unit(key_data, "Daily Generation", "unit")),
        "monthly_energy_kwh": energy_to_kwh(get_value_unit(key_data, "Monthly Gen.", "value"), get_value_unit(key_data, "Monthly Gen.", "unit")),
        "yearly_energy_kwh": energy_to_kwh(get_value_unit(key_data, "Annual Gen.", "value"), get_value_unit(key_data, "Annual Gen.", "unit")),
        "cumulative_energy_kwh": energy_to_kwh(get_value_unit(key_data, "Cumulative Generation", "value"), get_value_unit(key_data, "Cumulative Generation", "unit")),
        "monthly_income": to_float(nested_value(power, ["income", "monthElectricity", "value"])),
        "cumulative_income": to_float(nested_value(power, ["income", "totalElectricity", "value"])),
        "income_currency": nested_value(power, ["income", "monthElectricity", "unit"]) or nested_value(power, ["income", "totalElectricity", "unit"]),
        "inverter_count": to_int(get_value_unit(key_data, "Inverters", "value")),
        "monthly_alarm_count": to_int(get_value_unit(key_data, "Monthly Alarms", "value")),
        "today_alarm_count": to_int(get_value_unit(key_data, "Today's Alarms", "value")),
        "last_month_alarm_count": to_int(get_value_unit(key_data, "Last Month Alarms", "value")),
        "station_status_raw": status,
        "company_station_status_raw": status_company,
    })


def normalize_kehua_alarms(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    stats = statistics_map(first_data(grouped, "getStatisticsData"))
    unsolved = first_data(grouped, "getUnsolvedEventNum")
    event_list = first_data(grouped, "listUnsolvedEventLog")
    return compact_non_null({
        "unsolved_count": to_int(unsolved),
        "by_level": stats.get("alarmLevel"),
        "events": event_list.get("result") if isinstance(event_list, dict) else None,
        "event_total": event_list.get("total") if isinstance(event_list, dict) else None,
    })


def normalize_kehua_devices(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    overview = first_data(grouped, "getDeviceOverview")
    device_list = list_from_data(first_data(grouped, "listDeviceBySn"))
    card = first_data(grouped, "listDeviceCardInfoByCondition")
    card_devices = card.get("result") if isinstance(card, dict) and isinstance(card.get("result"), list) else []
    collector_card = first_data(grouped, "listCollectorIconInfoByCondition")
    collectors = collector_card.get("result") if isinstance(collector_card, dict) and isinstance(collector_card.get("result"), list) else []
    device_status = first_data(grouped, "getDeviceStatus")
    collector_status = first_data(grouped, "getCollectorSattus")
    stats = statistics_map(first_data(grouped, "getStatisticsData"))
    return compact_non_null({
        "device_count": len(card_devices) or len(device_list) or to_int(overview.get("total") if isinstance(overview, dict) else None),
        "normal_count": to_int(overview.get("normal") if isinstance(overview, dict) else None),
        "abnormal_count": to_int(overview.get("abnormal") if isinstance(overview, dict) else None),
        "online_count": to_int(overview.get("online") if isinstance(overview, dict) else None),
        "offline_count": to_int(overview.get("offline") if isinstance(overview, dict) else None),
        "station_device_status": device_status,
        "collector_status": collector_status,
        "run_state": stats.get("deviceRunState"),
        "devices": [compact_non_null({
            "device_id": item.get("deviceId"),
            "station_id": item.get("stationId"),
            "company_id": item.get("companyId"),
            "sn": item.get("sn"),
            "device_type": item.get("deviceType"),
            "device_type_name": item.get("devType"),
            "device_model": item.get("deviceModel"),
            "device_state": item.get("deviceState"),
            "collector_id": item.get("collectorId"),
            "collector_sn": item.get("collectorSn"),
            "company_name": item.get("companyName"),
        }) for item in merge_device_lists(device_list, card_devices)],
        "collectors": [compact_non_null({
            "collector_id": item.get("collectorId"),
            "station_id": item.get("stationId"),
            "name": item.get("collectorName"),
            "sn": item.get("sn"),
            "online": bool(item.get("online")),
            "signal_intensity": to_float(item.get("signalIntensity")),
            "collector_type": item.get("collectorType"),
            "collector_model": item.get("collectorModel"),
            "hardware_version": item.get("hardwareVersion"),
            "software_version": item.get("softwareVersion"),
            "communication_type": item.get("communicationType"),
        }) for item in collectors],
    })


def normalize_kehua_charts(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    daily = first_data(grouped, "getCurrentDayElecData")
    monthly = first_data(grouped, "getCurrentMonthElecData")
    power = first_data(grouped, "getCompanyPowerChartData")
    station_energy = first_data(grouped, "getEnergyTrendChartOfStation")
    station_power = first_data(grouped, "getPowerTrendChartOfStation")
    return compact_non_null({
        "daily_generation": normalize_xy_chart(daily, "kWh"),
        "monthly_generation": normalize_xy_chart(monthly, "kWh"),
        "company_power": power.get("data") if isinstance(power, dict) else power,
        "company_power_trends": normalize_kehua_company_power_charts(grouped.get("getCompanyPowerChartData") or []),
        "station_energy_trend": normalize_nested_chart(station_energy),
        "station_power_trend": normalize_nested_chart(station_power),
    })


def normalize_kehua_company_power_charts(calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_dimension: dict[str, Any] = {}
    labels = {"2": "month_daily", "3": "year_monthly", "4": "all_yearly", "5": "week_daily"}
    for call in calls:
        payload = parse_form_payload(call.get("payload_raw") or "")
        dimension = str(payload.get("dimension") or "unknown")
        data = response_data(call)
        chart = normalize_nested_chart(data)
        if chart:
            by_dimension[labels.get(dimension, dimension)] = chart
    return by_dimension or None


def normalize_status(value: Any, platform: str | None = None) -> str | None:
    text = str(value).lower() if value is not None else ""
    if platform == "kehua":
        mapping = {"1": "normal", "2": "abnormal", "3": "vacant", "4": "offline"}
        return mapping.get(str(value), str(value) if value is not None else None)
    if text in {"connected", "normal", "online"}:
        return "normal"
    if text in {"disconnected", "offline"}:
        return "offline"
    if text in {"trouble", "abnormal", "fault"}:
        return "abnormal"
    return str(value) if value is not None else None


def list_from_data(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def key_data_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    return {str(item.get("name")): item.get("val") for item in value if isinstance(item, dict) and item.get("name")}


def statistics_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, list):
        return {}
    return {str(item.get("code") or item.get("name")): item.get("data") for item in value if isinstance(item, dict)}


def get_value_unit(mapping: dict[str, Any], key: str, field: str) -> Any:
    value = mapping.get(key)
    if isinstance(value, dict):
        return value.get(field)
    return None


def nested_value(value: Any, keys: list[str]) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def sum_numbers(items: list[dict[str, Any]], field: str) -> float | None:
    numbers = [to_float(item.get(field)) for item in items]
    numbers = [number for number in numbers if number is not None]
    return round(sum(numbers), 4) if numbers else None


def numeric_series(value: Any) -> list[float | None] | None:
    if not isinstance(value, list):
        return None
    return [to_float(item) for item in value]


def extract_huawei_series(data: Any, key: str) -> list[float] | None:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return None
    values = []
    for item in data[key]:
        number = to_float(item)
        values.append(number if number is not None else 0.0)
    return values


def normalize_xy_chart(data: Any, default_unit: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    x_values = data.get("x_data") or data.get("xAxis")
    y_values = data.get("y_data") or data.get("yAxis")
    unit = data.get("unit") or default_unit
    if not isinstance(y_values, list):
        return compact_non_null({"unit": unit, "x": x_values, "y": y_values})
    return compact_non_null({
        "unit": unit,
        "x": x_values,
        "y": [to_float(item) for item in y_values],
    })


def only_station_key(stations_by_key: dict[str, dict[str, Any]]) -> str | None:
    if len(stations_by_key) == 1:
        return next(iter(stations_by_key))
    return None


def station_key_data_map(calls: list[dict[str, Any]]) -> dict[str, Any]:
    for call in calls:
        data = response_data(call)
        mapping = key_data_map(data)
        if "Installed capacity" in mapping or "Full-Load Hours (Today)" in mapping:
            return mapping
    return {}


def normalize_weather_item(item: dict[str, Any]) -> dict[str, Any]:
    return compact_non_null({
        "date": item.get("time"),
        "day_weather": item.get("dayWeather"),
        "night_weather": item.get("nightWeather"),
        "temp_max_c": to_float(item.get("tempMax")),
        "temp_min_c": to_float(item.get("tempMin")),
        "day_wind": item.get("dayWind"),
        "night_wind": item.get("nightWind"),
        "day_weather_code": item.get("dayWeatherCode"),
    })


def merge_device_lists(simple: list[dict[str, Any]], detailed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in simple + detailed:
        key = str(item.get("deviceId") or item.get("sn") or len(by_key))
        current = by_key.setdefault(key, {})
        for field, value in item.items():
            if value not in (None, ""):
                current[field] = value
    return list(by_key.values())


def normalize_nested_chart(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    unit = None
    unit_data = inner.get("unit") if isinstance(inner, dict) else None
    if isinstance(unit_data, dict) and isinstance(unit_data.get("unit"), list) and unit_data.get("unit"):
        unit = unit_data["unit"][0]
    series = {}
    for key, value in inner.items() if isinstance(inner, dict) else []:
        if key == "unit" or not isinstance(value, dict):
            continue
        series[key] = {
            "x": value.get("x_data"),
            "y": {
                child_key: [to_float(item) for item in child_value]
                for child_key, child_value in value.items()
                if child_key.startswith("y_") and isinstance(child_value, list)
            },
        }
    return compact_non_null({"unit": unit, "series": series})


def extract_station_summary(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stations_by_key: dict[str, dict[str, Any]] = {}

    for call in calls:
        if call.get("name") not in {"station-list", "listStationInfoByCondition", "listStationLike"}:
            continue
        body = call.get("response_body")
        if not isinstance(body, dict):
            continue
        data = body.get("data")
        items = None
        if isinstance(data, dict):
            items = data.get("list") or data.get("result") or data.get("data") or data.get("records")
        elif isinstance(data, list):
            items = data
        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            dn = item.get("dn") or item.get("stationDn") or item.get("plantDn") or item.get("stationCode")
            station_id = item.get("stationId")
            key = str(dn or station_id or item.get("stationName") or item.get("name"))
            if not key:
                continue
            record = {
                "dn": dn,
                "dn_id": item.get("dnId"),
                "station_id": station_id,
                "company_id": item.get("companyId"),
                "name": item.get("name") or item.get("stationName") or item.get("plantName"),
                "status": item.get("plantStatus") or item.get("stationStatus") or item.get("status"),
                "status_text": item.get("plantStatus") or item.get("stationStatusName"),
                "current_power": item.get("currentPower") or item.get("activePower"),
                "installed_capacity": item.get("installedCapacity") or item.get("capacity"),
                "daily_energy": item.get("dailyEnergy") or item.get("dayElec"),
                "month_energy": item.get("monthEnergy") or item.get("monthElec"),
                "year_energy": item.get("yearEnergy"),
                "cumulative_energy": item.get("cumulativeEnergy"),
                "inverter_power": item.get("inverterPower"),
                "full_hours": item.get("fullHours"),
                "station_type": item.get("stationTypeName") or item.get("stationType"),
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "address": item.get("plantAddress"),
                "timezone": item.get("timeZone"),
                "raw": item,
            }
            existing = stations_by_key.get(key)
            if not existing:
                stations_by_key[key] = record
                continue
            for field, value in record.items():
                if field == "raw":
                    existing_raw = existing.get("raw") if isinstance(existing.get("raw"), dict) else {}
                    existing["raw"] = {**existing_raw, **item}
                elif value not in (None, ""):
                    existing[field] = value

    return list(stations_by_key.values())


def extract_site_metrics(calls: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    for call in calls:
        body = call.get("response_body")
        if not isinstance(body, dict):
            continue
        name = call.get("name")
        data = body.get("data")

        if name in {"total-real-kpi", "station-status-count", "station-real-kpi"}:
            metrics[name] = data

        if name == "overviewOfPowerGeneration" and isinstance(data, dict):
            metrics["power_generation"] = data

        if name == "getKeyData" and isinstance(data, list):
            metrics["key_data"] = {
                str(item.get("name")): item.get("val")
                for item in data
                if isinstance(item, dict) and item.get("name")
            }

        if name == "getStatisticsData" and isinstance(data, list):
            metrics["statistics"] = {
                str(item.get("code") or item.get("name")): item.get("data")
                for item in data
                if isinstance(item, dict) and (item.get("code") or item.get("name"))
            }

        if name in {"getStationStatusCount", "ListStationStatusCount", "getUnsolvedEventNum"}:
            metrics[name] = data

    return metrics


def scrape_site(
    site_name: str,
    site: dict[str, Any],
    blueprint_file: Path,
    cookies_file: Path | None,
    timeout: int,
    delay: float,
    account: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blueprint = load_json(blueprint_file)
    session, session_meta = prepare_session(site_name, site, cookies_file, timeout, credentials=account)
    calls = []
    for call in blueprint.get("calls", []):
        prepared_call = prepare_kehua_account_call(call, account) if site_name == "kehua" and account else call
        result = replay_call(session, prepared_call, timeout)
        calls.append(result)
        if site_name == "huawei" and call.get("name") == "station-list" and result.get("success"):
            for extra_call in huawei_energy_balance_calls(site, result):
                extra_result = replay_call(session, extra_call, timeout)
                calls.append(extra_result)
                if delay:
                    time.sleep(delay)
        if delay:
            time.sleep(delay)

    return {
        "site": site_name,
        "scraped_at": now_iso(),
        "blueprint": str(blueprint_file),
        "session": session_meta,
        "summary": {
            "total": len(calls),
            "success_count": sum(1 for item in calls if item["success"]),
            "failed_count": sum(1 for item in calls if not item["success"]),
            "auth_error_count": sum(1 for item in calls if item.get("auth_error")),
        },
        "calls": calls,
    }


def combine_account_results(site_name: str, account_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "site": site_name,
        "scraped_at": max(str(item.get("scraped_at") or "") for item in account_results),
        "blueprint": account_results[0].get("blueprint"),
        "session": {"accounts": [item.get("session", {}) for item in account_results]},
        "summary": {
            field: sum(int(item.get("summary", {}).get(field) or 0) for item in account_results)
            for field in ("total", "success_count", "failed_count", "auth_error_count")
        },
        "calls": [call for item in account_results for call in item.get("calls", [])],
        "account_results": account_results,
    }


def parse_site_args(values: list[str]) -> dict[str, dict[str, Path | None]]:
    parsed: dict[str, dict[str, Path | None]] = {}
    for value in values:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            raise SystemExit(f"Invalid --site value: {value}. Use name:blueprint.json[:Cookies.json]")
        parsed[parts[0]] = {"blueprint": Path(parts[1]), "cookies": Path(parts[2]) if len(parts) == 3 and parts[2] else None}
    return parsed


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    sites_config = load_json(Path(args.sites_config))
    requested_sites = parse_site_args(args.site)
    run_id = now_stamp()
    out_dir = Path(args.out_dir)
    results = []

    for site_name, paths in requested_sites.items():
        if site_name not in sites_config:
            raise SystemExit(f"Unknown site {site_name}. Available: {', '.join(sites_config)}")
        cookies_file = Path(paths["cookies"]) if paths["cookies"] else None
        accounts = load_kehua_accounts_from_env() if site_name == "kehua" else []
        if accounts:
            account_results = [
                scrape_site(
                    site_name,
                    sites_config[site_name],
                    Path(paths["blueprint"]),
                    cookies_file if account.get("use_shared_cookies") else None,
                    args.timeout,
                    args.delay,
                    account=account,
                )
                for account in accounts
            ]
            result = combine_account_results(site_name, account_results)
        else:
            result = scrape_site(
                site_name,
                sites_config[site_name],
                Path(paths["blueprint"]),
                cookies_file,
                args.timeout,
                args.delay,
            )
        results.append(result)

        site_latest = out_dir / "latest" / site_name
        site_history = out_dir / "history" / run_id / site_name
        write_json(site_latest / "all_responses.json", result)
        write_json(site_history / "all_responses.json", result)
        write_json(site_latest / "summary.json", result["summary"])
        write_json(site_history / "summary.json", result["summary"])
        for call in result["calls"]:
            filename = f"{call['id']}_{safe_filename(call['name'])}.json"
            write_json(site_latest / "by_endpoint" / filename, call)
            write_json(site_history / "by_endpoint" / filename, call)
            if args.jsonl:
                append_jsonl(out_dir / "history" / f"{site_name}.jsonl", {"run_id": run_id, **call})

    combined = {"run_id": run_id, "scraped_at": now_iso(), "sites": results}
    current = normalize_latest(results)
    write_json(out_dir / "latest" / "all_sites.json", combined)
    write_json(out_dir / "latest" / "current.json", current)
    write_json(out_dir / "history" / run_id / "all_sites.json", combined)
    write_json(out_dir / "history" / run_id / "current.json", current)
    return {**combined, "current": current}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Huawei and Kehua monitoring APIs from reusable blueprints.")
    parser.add_argument("--sites-config", default="sites.json")
    parser.add_argument(
        "--site",
        action="append",
        required=True,
        help="Site binding: name:blueprint.json[:Cookies.json]. Repeat for huawei and kehua.",
    )
    parser.add_argument("--out-dir", default="monitoring_output")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--watch", type=int, default=0, help="Repeat every N seconds. 0 means run once.")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    while True:
        result = run_once(args)
        for site in result["sites"]:
            summary = site["summary"]
            print(
                f"[{result['run_id']}] {site['site']}: "
                f"success={summary['success_count']} failed={summary['failed_count']} auth_errors={summary['auth_error_count']}"
            )
        print(f"latest: {Path(args.out_dir) / 'latest' / 'current.json'}")
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
