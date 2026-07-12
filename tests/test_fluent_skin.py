from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.fluent_skin import (
    apply_qfluent_theme,
    build_fluent_qss,
    contrast_text,
    normalise_accent,
    optional_color,
)


class FluentSkinTests(unittest.TestCase):
    def test_bad_accent_falls_back_to_blue(self):
        self.assertEqual(normalise_accent("not-a-color"), "#2563eb")

    def test_builtin_qss_contains_accent_and_tree_icons(self):
        qss = build_fluent_qss("fluent_dark", "#0f766e", "closed.svg", "open.svg")
        self.assertIn("#0f766e", qss)
        self.assertIn("closed.svg", qss)
        self.assertIn("open.svg", qss)
        self.assertIn("#CanvasPanel", qss)
        self.assertIn("QScrollArea#CardWall", qss)
        self.assertIn("#ResourceCard[selected=\"true\"]", qss)
        self.assertIn("#CardSelectedBadge", qss)
        self.assertIn("QDialog", qss)
        self.assertIn("QCheckBox", qss)
        self.assertIn("#StatusBar", qss)
        self.assertIn("#SummaryText", qss)
        self.assertIn("#CommandBar", qss)
        self.assertIn("#CommandRunButton", qss)
        self.assertIn("#CommandCancelButton", qss)
        self.assertIn("#SidebarLibraryBox", qss)
        self.assertIn("#AnalysisStateBox", qss)
        self.assertIn("QProgressBar#AnalysisProgress", qss)
        self.assertIn("#ToolbarIconButton::menu-indicator", qss)
        self.assertIn("#StatusChip[warning=\"true\"]", qss)
        self.assertIn("QToolTip", qss)

    def test_optional_custom_colors_are_applied(self):
        self.assertEqual(optional_color("#ABCDEF"), "#abcdef")
        self.assertEqual(optional_color("not-a-color"), "")
        qss = build_fluent_qss(
            "fluent_dark",
            "#0f766e",
            "closed.svg",
            "open.svg",
            {"panel": "#202936", "canvas": "#111827", "button": "#273449"},
        )
        self.assertIn("#202936", qss)
        self.assertIn("#111827", qss)
        self.assertIn("#273449", qss)

    def test_semantic_colors_override_independent_roles(self):
        qss = build_fluent_qss(
            "fluent_dark",
            "#0f766e",
            "closed.svg",
            "open.svg",
            {
                "ui_window_color": "#101010",
                "ui_sidebar_color": "#202020",
                "ui_card_color": "#303030",
                "ui_input_color": "#404040",
                "ui_text_color": "#f1f2f3",
                "ui_muted_text_color": "#a1a2a3",
                "ui_border_color": "#505050",
                "ui_icon_color": "#abcdef",
                "ui_button_hover_color": "#606060",
                "ui_button_selected_color": "#f0d000",
            },
        )
        for value in ("#101010", "#202020", "#303030", "#404040", "#f1f2f3", "#a1a2a3", "#505050", "#abcdef", "#606060", "#f0d000"):
            self.assertIn(value, qss)
        self.assertEqual(contrast_text("#ffffff"), "#17202a")
        self.assertEqual(contrast_text("#111111"), "#ffffff")

    def test_claude_light_theme_has_clear_workspace_shell(self):
        qss = build_fluent_qss("claude_light", "#2563eb", "closed.svg", "open.svg")
        self.assertIn("#f2f0eb", qss)
        self.assertIn("#fbfaf7", qss)
        self.assertIn("#9b5a45", qss)
        self.assertIn("#PathTree::item:selected", qss)

    def test_optional_qfluent_missing_or_present_does_not_crash(self):
        result = apply_qfluent_theme({"use_qfluentwidgets": True, "ui_theme": "fluent_dark"})
        self.assertIn(result["backend"], {"builtin", "qfluentwidgets"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
