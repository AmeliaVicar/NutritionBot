import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from sheets import export_range_for_rows, normalize_uid_value


class SheetsUidTests(unittest.TestCase):
    def test_normalize_uid_value_handles_sheet_formats(self):
        self.assertEqual(normalize_uid_value(123456789), "123456789")
        self.assertEqual(normalize_uid_value("123456789"), "123456789")
        self.assertEqual(normalize_uid_value("'123456789"), "123456789")
        self.assertEqual(normalize_uid_value("123456789.0"), "123456789")
        self.assertEqual(normalize_uid_value(" 123456789 "), "123456789")


class SheetsExportRangeTests(unittest.TestCase):
    def test_export_range_includes_header_and_data_rows_only(self):
        rows = [
            ["Ivanova", "", "", "+", "", "", "", "", "", "123"],
            ["", "", "", "", "", "", "", "", "", ""],
            ["Petrova", "", "", "", "", "+", "", "", "", "456"],
        ]

        self.assertEqual(export_range_for_rows(rows), "A1:K4")

    def test_export_range_falls_back_to_header_when_empty(self):
        self.assertEqual(export_range_for_rows([]), "A1:K1")


if __name__ == "__main__":
    unittest.main()
