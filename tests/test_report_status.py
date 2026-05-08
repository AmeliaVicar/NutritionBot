import sys
import unittest

sys.path.insert(0, r"C:\NutritionBot\src")

from report_status import red_report_uids, report_row_status


def make_row(uid, breakfast="", snack1="", lunch="", snack2="", dinner=""):
    row = [""] * 11
    row[3] = breakfast
    row[4] = snack1
    row[5] = lunch
    row[6] = snack2
    row[7] = dinner
    row[9] = str(uid)
    return row


class ReportStatusTests(unittest.TestCase):
    def test_empty_food_row_is_red_unless_excused(self):
        row = make_row(100)

        red_status = report_row_status(row, lambda uid: False)
        self.assertTrue(red_status.red_row)
        self.assertFalse(red_status.red_cells)

        excused_status = report_row_status(row, lambda uid: True)
        self.assertFalse(excused_status.red_row)
        self.assertTrue(excused_status.is_excused)

    def test_missing_main_meal_cells_make_participant_red(self):
        row = make_row(200, breakfast="+", snack1="-", lunch="", dinner="+")
        status = report_row_status(row, lambda uid: True)

        self.assertFalse(status.red_row)
        self.assertEqual(status.red_cells, ("F",))
        self.assertFalse(status.is_excused)

    def test_missing_snacks_only_do_not_make_participant_red(self):
        row = make_row(300, breakfast="+", lunch="-", dinner="+")
        status = report_row_status(row, lambda uid: False)

        self.assertFalse(status.red_row)
        self.assertEqual(status.red_cells, ())

    def test_red_report_uids_are_deduplicated(self):
        rows = [
            make_row(100),
            make_row(100),
            make_row(200, breakfast="+", lunch="", dinner="+"),
            make_row(300, breakfast="+", lunch="+", dinner="+"),
        ]

        self.assertEqual(red_report_uids(rows, lambda uid: False), [100, 200])


if __name__ == "__main__":
    unittest.main()
