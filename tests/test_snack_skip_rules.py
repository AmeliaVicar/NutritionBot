import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import extract_meal_marks, looks_like_meal_report


class SnackSkipRulesTests(unittest.TestCase):
    def test_plural_snack_skip_marks_both_snacks(self):
        self.assertTrue(looks_like_meal_report("Соколова перекусов не будет"))
        self.assertEqual(
            extract_meal_marks("Соколова перекусов не будет", hour=10),
            [("snack1", "-"), ("snack2", "-")],
        )
        self.assertEqual(
            extract_meal_marks("Соколова обоих перекусов не будет", hour=17),
            [("snack1", "-"), ("snack2", "-")],
        )


if __name__ == "__main__":
    unittest.main()
