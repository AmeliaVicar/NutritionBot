import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from parser import looks_like_weight_report, parse_explicit_weight, parse_weight_delta


class WeightFreeformMessagesTests(unittest.TestCase):
    def test_absolute_weight_without_weight_word_is_ignored(self):
        cases = [
            "Сунко 80",
            "Сунко 80.0",
            "Сунко 80,0",
            "Сунко 79.7",
            "Сунко 79,7",
            "Сунко фото не грузится 79,7",
            "Сунко сегодня 79,7",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(looks_like_weight_report(text))
                self.assertIsNone(parse_explicit_weight(text))
                self.assertIsNone(parse_weight_delta(text))

    def test_weight_delta_without_weight_word_is_ignored(self):
        cases = [
            "Сунко минус 300",
            "Сунко плюс 200",
            "Сунко -300",
            "Сунко +300",
            "Сунко - 300",
            "Сунко + 200",
            "Сунко -0.3",
            "Сунко +0.2",
            "Сунко минус 0.3",
            "Сунко плюс 0,2",
        ]

        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(looks_like_weight_report(text))
                self.assertIsNone(parse_explicit_weight(text))
                self.assertIsNone(parse_weight_delta(text))

    def test_weight_messages_with_weight_word_still_work(self):
        cases = [
            ("Сунко вес минус 300", -0.3),
            ("Сунко вес плюс 200", 0.2),
            ("Сунко вес -300", -0.3),
            ("Сунко вес +300", 0.3),
            ("Сунко вес - 300", -0.3),
            ("Сунко вес + 200", 0.2),
            ("Сунко вес -0.3", -0.3),
            ("Сунко вес +0.2", 0.2),
            ("Сунко вес минус 0.3", -0.3),
            ("Сунко вес плюс 0,2", 0.2),
        ]

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(looks_like_weight_report(text))
                self.assertIsNone(parse_explicit_weight(text))
                self.assertEqual(parse_weight_delta(text), expected)

    def test_combined_message_without_weight_word_is_ignored(self):
        text = "Сунко 79,7 минус 300"
        self.assertFalse(looks_like_weight_report(text))
        self.assertIsNone(parse_explicit_weight(text))
        self.assertIsNone(parse_weight_delta(text))


if __name__ == "__main__":
    unittest.main()
