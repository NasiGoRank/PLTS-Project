import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from scrape_monitoring import huawei_energy_balance_by_station, huawei_energy_balance_calls


class HuaweiEnergyChartTests(unittest.TestCase):
    def test_builds_day_month_and_year_energy_calls_for_each_station(self):
        station_list_call = {
            "response_body": {
                "data": {"list": [{"dn": "NE=64589850"}]},
            }
        }
        site = {
            "base_url": "https://sg5.fusionsolar.huawei.com",
            "dashboard_url": "https://sg5.fusionsolar.huawei.com/dashboard",
        }

        calls = huawei_energy_balance_calls(
            site,
            station_list_call,
            datetime(2026, 8, 3, 2, 30, tzinfo=timezone.utc),
        )

        self.assertEqual([call["name"] for call in calls], [
            "energy-balance-daily",
            "energy-balance-monthly",
            "energy-balance-yearly",
        ])
        queries = [parse_qs(urlparse(call["url"]).query) for call in calls]
        self.assertEqual([query["timeDim"][0] for query in queries], ["2", "4", "5"])
        self.assertEqual(queries[0]["dateStr"], ["2026-08-03 00:00:00"])
        self.assertEqual(queries[1]["dateStr"], ["2026-08-01 00:00:00"])
        self.assertEqual(queries[2]["dateStr"], ["2026-01-01 00:00:00"])

    def test_normalizes_month_and_year_product_power_as_energy_charts(self):
        grouped = {
            "energy-balance-monthly": [{
                "url": "https://example/energy-balance?stationDn=NE%3D64589850&timeDim=4",
                "response_body": {"data": {
                    "xAxis": ["01", "02", "03", "04"],
                    "productPower": ["64.67", "62.14", "60.40", "--"],
                }},
            }],
            "energy-balance-yearly": [{
                "url": "https://example/energy-balance?stationDn=NE%3D64589850&timeDim=5",
                "response_body": {"data": {
                    "xAxis": ["01", "02", "03", "04"],
                    "productPower": ["2084.12", "1990.17", "2814.79", "2925.45"],
                }},
            }],
        }

        result = huawei_energy_balance_by_station(grouped)["NE=64589850"]

        self.assertEqual(result["energy_charts"]["daily"]["values"], [64.67, 62.14, 60.4, None])
        self.assertEqual(result["energy_charts"]["monthly"]["values"], [2084.12, 1990.17, 2814.79, 2925.45])


if __name__ == "__main__":
    unittest.main()
