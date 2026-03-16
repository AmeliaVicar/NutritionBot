import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import looks_like_weight_report, parse_explicit_weight, parse_weight_delta


class WeightFreeformMessagesTests(unittest.TestCase):
    def test_absolute_weight_without_weight_word(self):
        cases = [
            ("Сунко 80", 80.0),
            ("Сунко 80.0", 80.0),
            ("Сунко 80,0", 80.0),
            ("Сунко 79.7", 79.7),
            ("Сунко 79,7", 79.7),
            ("Сунко фото не грузится 79,7", 79.7),
            ("Сунко сегодня 79,7", 79.7),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(looks_like_weight_report(text))
                self.assertEqual(parse_explicit_weight(text), expected)
                self.assertIsNone(parse_weight_delta(text))

    def test_weight_delta_without_weight_word(self):
        cases = [
            ("Сунко минус 300", -0.3),
            ("Сунко плюс 200", 0.2),
            ("Сунко -300", -0.3),
            ("Сунко +300", 0.3),
            ("Сунко - 300", -0.3),
            ("Сунко + 200", 0.2),
            ("Сунко -0.3", -0.3),
            ("Сунко +0.2", 0.2),
            ("Сунко минус 0.3", -0.3),
            ("Сунко плюс 0,2", 0.2),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(looks_like_weight_report(text))
                self.assertIsNone(parse_explicit_weight(text))
                self.assertEqual(parse_weight_delta(text), expected)

    def test_explicit_weight_has_priority_over_delta(self):
        text = "Сунко 79,7 минус 300"
        self.assertTrue(looks_like_weight_report(text))
        self.assertEqual(parse_explicit_weight(text), 79.7)
        self.assertEqual(parse_weight_delta(text), -0.3)


if __name__ == "__main__":
    unittest.main()
