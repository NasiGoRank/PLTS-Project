import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from scrape_monitoring import kehua_request_sign, prepare_replay_call


class DynamicRequestDateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 2, 30, tzinfo=timezone.utc)

    def test_updates_huawei_month_and_timestamp_in_jakarta_timezone(self):
        original = {
            "site": "huawei",
            "name": "home-station-kpi-chart",
            "headers": {"roarand": "captured"},
            "payload_raw": json.dumps({
                "statDim": "4",
                "statTimeStr": "2026-06-01",
                "statTime": 1780246800000,
            }),
        }

        prepared = prepare_replay_call(original, self.now, sign_timestamp_ms=123)
        payload = json.loads(prepared["payload_raw"])
        expected = datetime(2026, 8, 1, tzinfo=timezone(timedelta(hours=7)))

        self.assertEqual(payload["statTimeStr"], "2026-08-01")
        self.assertEqual(payload["statTime"], int(expected.timestamp() * 1000))
        self.assertIn("2026-06-01", original["payload_raw"])

    def test_updates_huawei_year_and_lifetime_dimensions_to_current_year(self):
        for dimension in ("5", "6"):
            with self.subTest(dimension=dimension):
                prepared = prepare_replay_call({
                    "site": "huawei",
                    "name": "home-station-kpi-chart",
                    "payload_raw": json.dumps({
                        "statDim": dimension,
                        "statTimeStr": "2025-01-01",
                        "statTime": 1735664400000,
                    }),
                }, self.now, sign_timestamp_ms=123)
                payload = json.loads(prepared["payload_raw"])

                self.assertEqual(payload["statTimeStr"], "2026-01-01")

    def test_updates_kehua_target_time_for_each_dimension_and_resigns_payload(self):
        cases = (
            ("5", "2026-06-27", "2026-08-03"),
            ("2", "2026-06", "2026-08"),
            ("3", "2025", "2026"),
            ("4", "", ""),
        )
        for dimension, captured, expected in cases:
            with self.subTest(dimension=dimension):
                original = {
                    "site": "kehua",
                    "name": "getCompanyPowerChartData",
                    "headers": {"sign": "captured-sign"},
                    "payload_raw": f"companyId=1832&dimension={dimension}&targetTime={captured}",
                }
                prepared = prepare_replay_call(original, self.now, sign_timestamp_ms=123)
                payload = {key: values[-1] for key, values in parse_qs(
                    prepared["payload_raw"], keep_blank_values=True
                ).items()}

                self.assertEqual(payload["targetTime"], expected)
                self.assertEqual(prepared["headers"]["sign"], kehua_request_sign(payload, 123))
                self.assertEqual(original["headers"]["sign"], "captured-sign")

    def test_updates_kehua_station_power_trend_without_dimension_as_daily(self):
        prepared = prepare_replay_call({
            "site": "kehua",
            "name": "getPowerTrendChartOfStation",
            "headers": {"sign": "captured-sign"},
            "payload_raw": "stationId=17478&targetTime=2026-06-26&chartType=1",
        }, self.now, sign_timestamp_ms=123)
        payload = parse_qs(prepared["payload_raw"])

        self.assertEqual(payload["targetTime"], ["2026-08-03"])


if __name__ == "__main__":
    unittest.main()
