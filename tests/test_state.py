import os
import tempfile
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from src import state
from src.state import parse_until_date


class StateTests(TestCase):
    @patch("src.state.date")
    def test_parse_until_date_with_month_name(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        self.assertEqual(parse_until_date("Уехала до 14 января"), "2026-01-14")
        self.assertEqual(parse_until_date("Уехала до 7 марта"), "2026-03-07")

    @patch("src.state.date")
    def test_parse_until_date_numeric_formats(self, mock_date):
        mock_date.today.return_value = date(2026, 3, 11)
        mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

        self.assertEqual(parse_until_date("До 14.03"), "2026-03-14")
        self.assertEqual(parse_until_date("До 14"), "2026-03-14")

    def test_manual_green_until_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with patch("src.state.STATE_PATH", path):
                state.set_manual_green(1, 100, "2026-05-15")

                self.assertTrue(state.is_manual_green_today(1, 100, date(2026, 5, 15)))
                self.assertEqual(state.cleanup_expired_manual_green(1, date(2026, 5, 15)), [])
                self.assertEqual(state.cleanup_expired_manual_green(1, date(2026, 5, 16)), [100])
                self.assertFalse(state.is_manual_green_today(1, 100, date(2026, 5, 16)))
