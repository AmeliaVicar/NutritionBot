import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import detect_meal, late_message, looks_like_meal_report


class MealParserTimingTests(unittest.TestCase):
    def test_detect_meal_accepts_conversational_forms(self):
        self.assertEqual(detect_meal("Соколова завтракала"), "breakfast")
        self.assertEqual(detect_meal("Соколова позавтракала"), "breakfast")
        self.assertEqual(detect_meal("Соколова обедала"), "lunch")
        self.assertEqual(detect_meal("Соколова пообедала"), "lunch")
        self.assertEqual(detect_meal("Соколова ужинала"), "dinner")
        self.assertEqual(detect_meal("Соколова перекусила", hour=11), "snack1")
        self.assertTrue(looks_like_meal_report("Соколова позавтракала"))
        self.assertTrue(looks_like_meal_report("Соколова пообедала"))

    def test_late_message_warns_only_in_limited_window(self):
        self.assertIsNone(late_message("snack1", 11, 9))
        self.assertEqual(late_message("snack1", 11, 10), "⚠️ Первый перекус — до 11:00.")
        self.assertIsNone(late_message("lunch", 13, 30))
        self.assertIsNone(late_message("lunch", 14, 9))
        self.assertEqual(late_message("lunch", 14, 10), "⚠️ Обед — до 14:00.")
        self.assertEqual(late_message("lunch", 16, 0), "⚠️ Обед — до 14:00.")
        self.assertIsNone(late_message("lunch", 17, 0))
        self.assertIsNone(late_message("snack2", 15, 30))
        self.assertIsNone(late_message("snack2", 16, 9))
        self.assertEqual(late_message("snack2", 16, 10), "⚠️ Второй перекус — до 16:00.")
        self.assertEqual(late_message("snack2", 18, 0), "⚠️ Второй перекус — до 16:00.")
        self.assertIsNone(late_message("snack2", 19, 0))


if __name__ == "__main__":
    unittest.main()
