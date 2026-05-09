import sys
import unittest
from datetime import date

sys.path.insert(0, r"C:\NutritionBot\src")

from enrollment import (
    existing_uids_from_rows,
    find_row_by_candidate_name,
    names_match,
    parse_start_candidate,
    start_date_sheet_value,
)


class EnrollmentTests(unittest.TestCase):
    def test_parse_start_candidate_from_chat_message(self):
        candidate = parse_start_candidate("Дежнева Марина начинаю с 10.05.", date(2026, 5, 9))

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.full_name, "Дежнева Марина")
        self.assertEqual(candidate.start_date, date(2026, 5, 10))

    def test_parse_reversed_name_order(self):
        candidate = parse_start_candidate("Марина Дежнева старт 11.05", date(2026, 5, 9))

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.full_name, "Марина Дежнева")
        self.assertEqual(candidate.start_date, date(2026, 5, 11))

    def test_parse_short_name_and_date_without_start_word(self):
        candidate = parse_start_candidate("Самохина Елена 11.05", date(2026, 5, 9))

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.full_name, "Самохина Елена")

    def test_rejects_reports_and_instruction_examples(self):
        self.assertIsNone(parse_start_candidate("Самохина Елена обед 11.05", date(2026, 5, 9)))
        self.assertIsNone(parse_start_candidate("Напишите фамилия имя начинаю с 10.05", date(2026, 5, 9)))

    def test_start_date_sheet_value_is_blank_for_tomorrow(self):
        self.assertEqual(start_date_sheet_value(date(2026, 5, 10), date(2026, 5, 9)), "")
        self.assertEqual(start_date_sheet_value(date(2026, 5, 11), date(2026, 5, 9)), "11.05")

    def test_names_match_in_both_orders(self):
        self.assertTrue(names_match("Дежнева Марина", "Марина Дежнева"))
        self.assertFalse(names_match("Дежнева Марина", "Самохина Елена"))

    def test_find_row_by_candidate_name_and_existing_uids(self):
        rows = [
            ["Дежнева Марина", "", "", "", "", "", "", "", "", "123"],
            ["Самохина Елена"],
        ]

        self.assertEqual(existing_uids_from_rows(rows), {"123"})
        self.assertEqual(find_row_by_candidate_name(rows, "Марина Дежнева"), (2, "123"))
        self.assertEqual(find_row_by_candidate_name(rows, "Елена Самохина"), (3, ""))


if __name__ == "__main__":
    unittest.main()
