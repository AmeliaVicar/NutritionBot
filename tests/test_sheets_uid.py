import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from sheets import normalize_uid_value


class SheetsUidTests(unittest.TestCase):
    def test_normalize_uid_value_handles_sheet_formats(self):
        self.assertEqual(normalize_uid_value(123456789), "123456789")
        self.assertEqual(normalize_uid_value("123456789"), "123456789")
        self.assertEqual(normalize_uid_value("'123456789"), "123456789")
        self.assertEqual(normalize_uid_value("123456789.0"), "123456789")
        self.assertEqual(normalize_uid_value(" 123456789 "), "123456789")


if __name__ == "__main__":
    unittest.main()
