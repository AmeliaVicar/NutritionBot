import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import looks_like_weight_report, parse_sheet_weight, parse_weight_delta


class WeightRuntimeSafetyTests(unittest.TestCase):
    def test_parse_sheet_weight_is_strict(self):
        self.assertIsNone(parse_sheet_weight(None))
        self.assertIsNone(parse_sheet_weight(""))
        self.assertIsNone(parse_sheet_weight("   "))
        self.assertIsNone(parse_sheet_weight("=SUM(B2:B3)"))
        self.assertEqual(parse_sheet_weight("108,4"), 108.4)
        self.assertEqual(parse_sheet_weight("108.4"), 108.4)
        self.assertEqual(parse_sheet_weight("'108,4"), 108.4)
        self.assertIsNone(parse_sheet_weight("108.4.1"))
        self.assertIsNone(parse_sheet_weight("вес 108.4"))
        self.assertIsNone(parse_sheet_weight(29.9))
        self.assertIsNone(parse_sheet_weight(200.5))

    def test_integer_weight_delta_is_safe_and_predictable(self):
        self.assertEqual(parse_weight_delta("вес минус 400"), -0.4)
        self.assertEqual(parse_weight_delta("вес плюс 300"), 0.3)
        self.assertEqual(parse_weight_delta("вес минус 400 гр"), -0.4)
        self.assertEqual(parse_weight_delta("вес минус 0.4"), -0.4)
        self.assertEqual(parse_weight_delta("вес плюс 0,2"), 0.2)
        self.assertIsNone(parse_weight_delta("вес минус 1"))
        self.assertIsNone(parse_weight_delta("вес минус 15"))
        self.assertIsNone(parse_weight_delta("вес плюс 5000"))
        self.assertFalse(looks_like_weight_report("вес минус 1"))


if __name__ == "__main__":
    unittest.main()
