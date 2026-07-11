from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.settings import DEFAULT_SETTINGS, load_settings, save_settings


class SettingsDefaultsTests(unittest.TestCase):
    def test_default_theme_uses_clear_warm_workbench(self):
        self.assertEqual(DEFAULT_SETTINGS["ui_theme"], "claude_light")
        self.assertGreater(DEFAULT_SETTINGS["preview_cache_max_mb"], 0)
        self.assertGreater(DEFAULT_SETTINGS["move_log_max_records"], 0)
        self.assertGreater(DEFAULT_SETTINGS["staging_max_age_days"], 0)
        self.assertGreater(DEFAULT_SETTINGS["resource_index_max_records"], 0)
        self.assertGreater(DEFAULT_SETTINGS["review_history_max_age_days"], 0)
        self.assertGreater(DEFAULT_SETTINGS["rename_log_max_records"], 0)
        self.assertGreater(DEFAULT_SETTINGS["upload_log_max_records"], 0)
        self.assertGreater(DEFAULT_SETTINGS["sqlite_vacuum_min_reclaim_mb"], 0)

    def test_semantic_theme_roles_are_available_and_persisted(self):
        roles = {
            "ui_window_color",
            "ui_sidebar_color",
            "ui_card_color",
            "ui_input_color",
            "ui_text_color",
            "ui_muted_text_color",
            "ui_border_color",
            "ui_icon_color",
            "ui_button_hover_color",
            "ui_button_selected_color",
        }
        self.assertTrue(roles.issubset(DEFAULT_SETTINGS))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = load_settings(root)
            settings["ui_text_color"] = "#123456"
            settings["ui_card_color"] = "#abcdef"
            save_settings(root, settings)
            loaded = load_settings(root)
            self.assertEqual(loaded["ui_text_color"], "#123456")
            self.assertEqual(loaded["ui_card_color"], "#abcdef")


if __name__ == "__main__":
    unittest.main(verbosity=2)
