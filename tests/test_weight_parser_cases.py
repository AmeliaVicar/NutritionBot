import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import (
    looks_like_weight_report,
    parse_absolute_weight,
    parse_explicit_weight,
    parse_weight_delta,
)


class WeightParserCasesTests(unittest.TestCase):
    def test_explicit_weight_accepts_mixed_text_and_comma(self):
        self.assertEqual(parse_explicit_weight("75,6"), 75.6)
        self.assertEqual(parse_explicit_weight("Соколова 75,6"), 75.6)
        self.assertEqual(parse_explicit_weight("фото не грузится, вес 75,6"), 75.6)
        self.assertTrue(looks_like_weight_report("фото не грузится, вес 75,6"))

    def test_explicit_weight_wins_in_combined_message(self):
        text = "Вес 75,6, минус 300 от веса на 14.03"
        self.assertEqual(parse_explicit_weight(text), 75.6)
        self.assertEqual(parse_absolute_weight(text), 75.6)
        self.assertEqual(parse_weight_delta(text), -0.3)
        self.assertTrue(looks_like_weight_report(text))

    def test_weight_delta_variants(self):
        self.assertEqual(parse_weight_delta("-300"), -0.3)
        self.assertEqual(parse_weight_delta("- 300"), -0.3)
        self.assertEqual(parse_weight_delta("минус 300"), -0.3)
        self.assertEqual(parse_weight_delta("минус 0.3"), -0.3)
        self.assertEqual(parse_weight_delta("+200"), 0.2)
        self.assertEqual(parse_weight_delta("плюс 200"), 0.2)
        self.assertEqual(parse_weight_delta("+0,2"), 0.2)
        self.assertEqual(parse_weight_delta("вес тот же"), 0.0)
        self.assertEqual(parse_weight_delta("тот же вес"), 0.0)
        self.assertTrue(looks_like_weight_report("вес тот же"))

    def test_explicit_weight_does_not_take_delta_or_date_as_weight(self):
        self.assertIsNone(parse_explicit_weight("Соколова минус 300"))
        self.assertIsNone(parse_explicit_weight("Вес на 30.03 был неверный"))
        self.assertEqual(parse_explicit_weight("Вес 80.0, плюс 200"), 80.0)


if __name__ == "__main__":
    unittest.main()
