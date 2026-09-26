import unittest
from datetime import date, datetime, timezone

from history_export_api import _export_filename, _xlsx_response


class HistoryExportTests(unittest.TestCase):
    def test_all_sites_xlsx_filename_is_descriptive(self):
        filename = _export_filename(
            rows=[],
            start=date(2026, 9, 1),
            end=date(2026, 9, 26),
            resolution="daily",
            file_format="xlsx",
            station_id=None,
            platform=None,
            station_name=None,
            generated_at=datetime(2026, 9, 26, 4, 48, tzinfo=timezone.utc),
        )

        self.assertEqual(
            filename,
            "PLTS-History_All-Sites_Daily_2026-09-01_to_2026-09-26_"
            "Exported-2026-09-26_11-48-WIB.xlsx",
        )

    def test_selected_site_filename_uses_platform_and_site_name(self):
        filename = _export_filename(
            rows=[],
            start=date(2026, 9, 1),
            end=date(2026, 9, 26),
            resolution="hourly",
            file_format="csv",
            station_id="17478",
            platform="kehua",
            station_name="SMPN 282 Jakut",
            generated_at=datetime(2026, 9, 26, 4, 48, tzinfo=timezone.utc),
        )

        self.assertEqual(
            filename,
            "PLTS-History_Site-Kehua-SMPN-282-Jakut_Hourly_"
            "2026-09-01_to_2026-09-26_Exported-2026-09-26_11-48-WIB.csv",
        )

    def test_xlsx_response_has_excel_content_type(self):
        response = _xlsx_response(
            rows=[{"station_name": "SMPN 282 Jakut", "energy_kwh": 12.5}],
            columns=[
                ("station_name", "Station Name"),
                ("energy_kwh", "Energy (kWh)"),
            ],
            filename="history.xlsx",
        )

        self.assertEqual(
            response.media_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("history.xlsx", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-export-row-count"], "1")


if __name__ == "__main__":
    unittest.main()
