import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, r"C:\NutritionBot\src")

import state


class StateUsersTests(unittest.TestCase):
    def test_save_user_and_get_users(self):
        state_path = r"C:\NutritionBot\tests\tmp_state_users.json"
        if os.path.exists(state_path):
            os.remove(state_path)

        try:
            with patch.object(state, "STATE_PATH", state_path):
                state.save_user(123, 456789, "tester", "Test User")
                users = state.get_users(123)
        finally:
            if os.path.exists(state_path):
                os.remove(state_path)

        self.assertEqual(users["456789"]["username"], "tester")
        self.assertEqual(users["456789"]["full_name"], "Test User")

    def test_get_users_includes_mentions_fallback(self):
        state_path = r"C:\NutritionBot\tests\tmp_state_users.json"
        if os.path.exists(state_path):
            os.remove(state_path)

        try:
            with patch.object(state, "STATE_PATH", state_path):
                state.save_mention(123, 999888, "@fallback")
                users = state.get_users(123)
        finally:
            if os.path.exists(state_path):
                os.remove(state_path)

        self.assertIn("999888", users)

    def test_start_candidate_storage_marks_imported(self):
        state_path = r"C:\NutritionBot\tests\tmp_state_users.json"
        if os.path.exists(state_path):
            os.remove(state_path)

        try:
            with patch.object(state, "STATE_PATH", state_path):
                state.save_start_candidate(
                    123,
                    456789,
                    "Самохина Елена",
                    "2026-05-11",
                    "Самохина Елена начинаю с 11.05",
                    "2026-05-09T15:58:00+03:00",
                )
                state.mark_start_candidate_imported(123, 456789, "2026-05-09T16:00:00+03:00")
                candidates = state.get_start_candidates(123)
        finally:
            if os.path.exists(state_path):
                os.remove(state_path)

        self.assertEqual(candidates["456789"]["full_name"], "Самохина Елена")
        self.assertEqual(candidates["456789"]["start_date"], "2026-05-11")
        self.assertEqual(candidates["456789"]["imported_at"], "2026-05-09T16:00:00+03:00")



if __name__ == "__main__":
    unittest.main()
