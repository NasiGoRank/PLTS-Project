import json
import os
import unittest
from unittest.mock import patch

from scrape_monitoring import (
    kehua_request_sign,
    load_kehua_accounts_from_env,
    merge_normalized_sites,
    parse_form_payload,
    prepare_kehua_account_call,
    prepare_replay_call,
)


class KehuaAccountsTests(unittest.TestCase):
    def test_loads_legacy_and_additional_accounts_without_duplicates(self):
        additional = [{
            "name": "school-09",
            "username": "second-user",
            "password": "second-password",
            "company_id": 1831,
            "station_id": 17483,
            "area_code": 2054,
        }]
        with patch.dict(os.environ, {
            "KEHUA_USERNAME": "primary-user",
            "KEHUA_PASSWORD": "primary-password",
            "KEHUA_ACCOUNTS_JSON": json.dumps(additional),
        }, clear=True):
            accounts = load_kehua_accounts_from_env()

        self.assertEqual(len(accounts), 2)
        self.assertTrue(accounts[0]["use_shared_cookies"])
        self.assertEqual(accounts[1]["company_id"], "1831")
        self.assertEqual(accounts[1]["station_id"], "17483")
        self.assertEqual(accounts[1]["area_code"], "2054")

    def test_rewrites_account_identifiers_and_resigns_the_request(self):
        call = {
            "site": "kehua",
            "name": "station",
            "headers": {"sign": "stale"},
            "payload_raw": "companyId=1832&areaCode=2055&stationId=17478",
        }
        account = {
            "company_id": "1831",
            "area_code": "2054",
            "station_id": "17483",
        }

        rewritten = prepare_kehua_account_call(call, account)
        prepared = prepare_replay_call(rewritten, sign_timestamp_ms=123)
        payload = parse_form_payload(prepared["payload_raw"])

        self.assertEqual(payload["companyId"], "1831")
        self.assertEqual(payload["areaCode"], "2054")
        self.assertEqual(payload["stationId"], "17483")
        self.assertEqual(prepared["headers"]["sign"], kehua_request_sign(payload, 123))

    def test_merges_accounts_while_preserving_station_specific_charts(self):
        first = {
            "platform": "kehua",
            "updated_at": "2026-08-03T10:00:00+00:00",
            "scrape_status": {"success_count": 42, "failed_count": 0, "auth_error_count": 0},
            "overview": {"station_count": 1, "capacity_kwp": 15.0, "daily_energy_kwh": 10.0},
            "stations": [{"station_id": "17478", "name": "School 282"}],
            "alarms": {"unsolved_count": 0, "event_total": 0, "events": []},
            "devices": {"device_count": 1, "devices": [{"device_id": 1}]},
            "charts": {"daily_generation": {"x": ["00:00"], "y": [1.0]}},
        }
        second = {
            "platform": "kehua",
            "updated_at": "2026-08-03T10:01:00+00:00",
            "scrape_status": {"success_count": 42, "failed_count": 0, "auth_error_count": 0},
            "overview": {"station_count": 1, "capacity_kwp": 20.0, "daily_energy_kwh": 12.0},
            "stations": [{"station_id": "17483", "name": "School 09"}],
            "alarms": {"unsolved_count": 1, "event_total": 1, "events": [{"id": 2}]},
            "devices": {"device_count": 1, "devices": [{"device_id": 2}]},
            "charts": {"daily_generation": {"x": ["00:00"], "y": [2.0]}},
        }

        merged = merge_normalized_sites([first, second])

        self.assertEqual(merged["overview"]["station_count"], 2)
        self.assertEqual(merged["overview"]["capacity_kwp"], 35.0)
        self.assertEqual(merged["overview"]["daily_energy_kwh"], 22.0)
        self.assertEqual(merged["scrape_status"]["success_count"], 84)
        self.assertEqual(len(merged["stations"]), 2)
        self.assertEqual(merged["stations"][1]["charts"]["daily_generation"]["y"], [2.0])
        self.assertEqual(merged["devices"]["device_count"], 2)


if __name__ == "__main__":
    unittest.main()
