from datetime import date
from unittest import TestCase
from unittest.mock import patch

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
