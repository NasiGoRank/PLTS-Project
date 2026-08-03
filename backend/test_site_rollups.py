import unittest

from site_rollups import extract_site_daily_rollups


class SiteDailyRollupTests(unittest.TestCase):
    def test_extracts_one_daily_row_per_station_and_preserves_zero_values(self):
        payload = {
            "by_site": {
                "huawei": {
                    "overview": {},
                    "stations": [
                        {
                            "station_id": "NE=1",
                            "name": "Huawei School",
                            "timezone": "Asia/Bangkok",
                            "daily_energy_kwh": 42.5,
                            "daily_income": 12000,
                        }
                    ],
                },
                "kehua": {
                    "overview": {"income_currency": "¥"},
                    "stations": [
                        {
                            "station_id": "17478",
                            "name": "Kehua School",
                            "timezone": "GMT+7",
                            "daily_energy_kwh": 0,
                            "daily_income": 0,
                        }
                    ],
                },
            }
        }

        rows = extract_site_daily_rollups(payload, "2026-08-03T18:30:00+00:00")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["bucket_date"], "2026-08-04")
        self.assertEqual(rows[0]["currency"], "IDR")
        self.assertEqual(rows[0]["energy_kwh"], 42.5)
        self.assertEqual(rows[1]["bucket_date"], "2026-08-04")
        self.assertEqual(rows[1]["currency"], "¥")
        self.assertEqual(rows[1]["energy_kwh"], 0.0)
        self.assertEqual(rows[1]["revenue_amount"], 0.0)

    def test_skips_records_without_a_stable_station_identifier(self):
        payload = {
            "by_site": {
                "huawei": {
                    "stations": [{"name": "Unknown", "daily_energy_kwh": 1}],
                }
            }
        }

        self.assertEqual(extract_site_daily_rollups(payload, "2026-08-03T00:00:00Z"), [])


if __name__ == "__main__":
    unittest.main()
