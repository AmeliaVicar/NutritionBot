import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import (
    detect_meal,
    extract_meal_marks,
    is_excuse,
    is_skip,
    looks_like_meal_report,
    looks_like_weight_report,
    parse_absolute_weight,
    split_report_parts,
)


class ParserTests(unittest.TestCase):
    def test_skip_variants_from_chat(self):
        self.assertTrue(is_skip("\u041f\u0435\u0447\u0451\u043d\u043e\u0432\u0430 \u0410\u043b\u0451\u043d\u0430, \u043f\u0435\u0440\u0435\u043a\u0443\u0441 1 \u043d\u0435 \u0431\u044b\u043b\u043e"))
        self.assertTrue(is_skip("\u041a\u0430\u0440\u0430\u0441\u043e\u0432\u0430 \u043e\u0431\u0435\u0434\u0430 \u043d\u0435\u0442"))
        self.assertTrue(is_skip("\u0415\u0440\u043c\u0430\u043a\u043e\u0432\u0430 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 2 \u043f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u043b\u0430"))

    def test_detect_meal_with_declension_and_time(self):
        self.assertEqual(detect_meal("\u041a\u0430\u0440\u0430\u0441\u043e\u0432\u0430 \u043e\u0431\u0435\u0434\u0430 \u043d\u0435\u0442"), "lunch")
        self.assertEqual(detect_meal("\u0427\u0435\u0440\u0435\u043c\u0438\u0441\u0438\u043d\u0430 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 16:30"), "snack2")
        self.assertEqual(detect_meal("\u041c\u0438\u0448\u043a\u0438\u043d\u0430 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 10:30"), "snack1")
        self.assertEqual(detect_meal("\u041a\u0440\u0438\u0432\u0438\u0446\u043a\u0430\u044f \u0431\u0435\u0437 2 \u043f\u0435\u0440\u0435\u043a\u0443\u0441\u0430"), "snack2")

    def test_excuse_no_longer_triggers_on_without_photo(self):
        self.assertFalse(is_excuse("\u041a\u0440\u0430\u0441\u043a\u043e \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0441 \u043d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u044f\u043c\u0438, \u043f\u043e\u044d\u0442\u043e\u043c\u0443 \u0431\u0435\u0437 \u0444\u043e\u0442\u043e"))
        self.assertFalse(is_excuse("\u0413\u0443\u043b\u044f\u0435\u0432\u0430 \u041d\u0430\u0442\u0430\u043b\u044c\u044f \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0431\u0435\u0437 \u0444\u043e\u0442\u043e\u043e\u0442\u0447\u0451\u0442\u0430. \u0424\u043e\u0442\u043e \u043e\u0431\u0435\u0434\u0430 \u0441\u0442\u0440\u0430\u0448\u043d\u043e \u0432\u044b\u043a\u043b\u0430\u0434\u044b\u0432\u0430\u0442\u044c"))

    def test_split_multiline_report(self):
        self.assertEqual(
            split_report_parts("\u0427\u0435\u0440\u0435\u043c\u0438\u0441\u0438\u043d\u0430 \u043e\u0431\u0435\u0434\n\u041f\u0435\u0440\u0435\u043a\u0443\u0441\u0430 1\u043d\u0435 \u0431\u044b\u043b\u043e"),
            ["\u0427\u0435\u0440\u0435\u043c\u0438\u0441\u0438\u043d\u0430 \u043e\u0431\u0435\u0434", "\u041f\u0435\u0440\u0435\u043a\u0443\u0441\u0430 1\u043d\u0435 \u0431\u044b\u043b\u043e"],
        )

    def test_extract_meal_marks_for_multiline_message(self):
        self.assertEqual(
            extract_meal_marks("\u0427\u0435\u0440\u0435\u043c\u0438\u0441\u0438\u043d\u0430 \u043e\u0431\u0435\u0434\n\u041f\u0435\u0440\u0435\u043a\u0443\u0441\u0430 1\u043d\u0435 \u0431\u044b\u043b\u043e", hour=13),
            [("lunch", "+"), ("snack1", "-")],
        )

    def test_extract_meal_marks_for_multiple_meals_in_one_sentence(self):
        self.assertEqual(
            extract_meal_marks("\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u043b\u0430 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 2 \u0438 \u0443\u0436\u0438\u043d", hour=18),
            [("snack2", "-"), ("dinner", "-")],
        )

    def test_skip_before_meal_stays_minus(self):
        self.assertEqual(
            extract_meal_marks("Подсвирова без перекуса 1", hour=10),
            [("snack1", "-")],
        )
        self.assertEqual(
            extract_meal_marks("Ходоренко Олеся без ужина. Температура, не хочу ничего. Водичку пью", hour=19),
            [("dinner", "-")],
        )

    def test_meal_report_filter_ignores_questions(self):
        self.assertFalse(looks_like_meal_report("\u0418 \u0435\u0449\u0451 \u0432\u043e\u043f\u0440\u043e\u0441 \u043f\u043e \u043c\u0435\u043d\u044e 5, \u043d\u0430 \u0437\u0430\u0432\u0442\u0440\u0430\u043a \u043c\u043e\u0436\u043d\u043e \u0441\u044b\u0440 \u0420\u0438\u043a\u043e\u0442\u0442\u0443?"))
        self.assertFalse(looks_like_meal_report("\u041f\u043e\u0434\u0441\u043a\u0430\u0436\u0438\u0442\u0435, \u043f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u043c\u043e\u0436\u043d\u043e \u043b\u0438 \u043f\u0435\u0440\u0435\u043a\u0443\u0441 \u0440\u0430\u0437\u0434\u0435\u043b\u044f\u0442\u044c?"))
        self.assertTrue(looks_like_meal_report("\u041a\u0430\u0440\u0430\u0441\u043e\u0432\u0430, \u043f\u0435\u0440\u0435\u043a\u0443\u0441\u0430 1 \u043d\u0435\u0442"))
        self.assertTrue(looks_like_meal_report("\u041f\u043e\u0434\u0441\u0432\u0438\u0440\u043e\u0432\u0430 \u0431\u0435\u0437 \u043f\u0435\u0440\u0435\u043a\u0443\u0441\u0430 1"))

    def test_weight_report_filter_ignores_complaints(self):
        self.assertFalse(looks_like_weight_report("\u041a\u0430\u0440\u0430\u0441\u043e\u0432\u0430 \u0432\u0435\u0441 \u043d\u0435 \u0432\u0435\u0440\u043d\u044b\u0439, \u0443\u0442\u0440\u043e\u043c \u0431\u044b\u043b 71,4"))
        self.assertIsNone(parse_absolute_weight("\u041f\u0435\u0447\u0451\u043d\u043e\u0432\u0430 \u0410\u043b\u0451\u043d\u0430, \u0432\u0435\u0441 \u0443\u043a\u0430\u0437\u0430\u043d \u043d\u0435 \u0432\u0435\u0440\u043d\u043e, \u0441\u0435\u0433\u043e\u0434\u043d\u044f \u0431\u044b\u043b\u043e 77,3"))
        self.assertTrue(looks_like_weight_report("\u041a\u0443\u0440\u0431\u0430\u0442\u043e\u0432\u0430 \u0412\u0430\u043b\u0435\u043d\u0442\u0438\u043d\u0430 \u0432\u0435\u0441 71"))
        self.assertEqual(parse_absolute_weight("\u041a\u0443\u0440\u0431\u0430\u0442\u043e\u0432\u0430 \u0412\u0430\u043b\u0435\u043d\u0442\u0438\u043d\u0430 \u0432\u0435\u0441 71"), 71.0)


if __name__ == "__main__":
    unittest.main()
