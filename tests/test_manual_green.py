import sys
import unittest
from datetime import date

sys.path.insert(0, r"C:\NutritionBot\src")

from manual_green import parse_manual_green_command


class ManualGreenCommandTests(unittest.TestCase):
    def test_set_green_line_without_date(self):
        command = parse_manual_green_command("зелёная строка", date(2026, 5, 11))

        self.assertIsNotNone(command)
        self.assertEqual(command.action, "set")
        self.assertIsNone(command.until)
        self.assertEqual(command.sheet_value, "")

    def test_set_green_line_with_numeric_date(self):
        command = parse_manual_green_command("зелёная строка до 15.05", date(2026, 5, 11))

        self.assertIsNotNone(command)
        self.assertEqual(command.action, "set")
        self.assertEqual(command.until, date(2026, 5, 15))
        self.assertEqual(command.sheet_value, "15.05")

    def test_set_green_line_with_month_name(self):
        command = parse_manual_green_command("поставь зеленую строку до 3 июня", date(2026, 5, 11))

        self.assertIsNotNone(command)
        self.assertEqual(command.until, date(2026, 6, 3))
        self.assertEqual(command.sheet_value, "03.06")

    def test_remove_green_line(self):
        command = parse_manual_green_command("убрать зелёную строку", date(2026, 5, 11))

        self.assertIsNotNone(command)
        self.assertEqual(command.action, "remove")
        self.assertIsNone(command.until)

    def test_does_not_trigger_on_descriptive_text(self):
        command = parse_manual_green_command("в таблице строка будет зелёной", date(2026, 5, 11))

        self.assertIsNone(command)


if __name__ == "__main__":
    unittest.main()
