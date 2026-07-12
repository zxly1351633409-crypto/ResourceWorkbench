from __future__ import annotations

import re


def apply_qfluent_theme(settings: dict) -> dict:
    """Apply QFluentWidgets global theme if the optional package is installed."""
    if not bool(settings.get("use_qfluentwidgets", True)):
        return {"ok": False, "backend": "disabled", "error": "disabled"}
    try:
        import qfluentwidgets as qfw  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001 - optional UI dependency
        return {"ok": False, "backend": "builtin", "error": str(exc)}

    theme_value = str(settings.get("ui_theme") or "fluent_dark")
    accent = normalise_accent(str(settings.get("ui_accent_color") or "#2563eb"))
    try:
        theme_enum = getattr(qfw, "Theme", None)
        set_theme = getattr(qfw, "setTheme", None)
        set_theme_color = getattr(qfw, "setThemeColor", None)
        if theme_enum is not None and callable(set_theme):
            set_theme(getattr(theme_enum, "DARK", None) if theme_value == "fluent_dark" else getattr(theme_enum, "LIGHT", None))
        if callable(set_theme_color):
            set_theme_color(accent)
    except Exception as exc:  # noqa: BLE001 - keep UI usable if the optional package changes API
        return {"ok": False, "backend": "builtin", "error": str(exc)}
    return {"ok": True, "backend": "qfluentwidgets", "error": ""}


def normalise_accent(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.lower()
    return "#2563eb"


def optional_color(value: str) -> str:
    value = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.lower()
    return ""


def _mix_hex(color: str, other: str, amount: float) -> str:
    color = optional_color(color) or "#000000"
    other = optional_color(other) or "#ffffff"
    amount = max(0.0, min(1.0, amount))
    left = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    right = tuple(int(other[i : i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(round(l + (r - l) * amount) for l, r in zip(left, right))
    return "#" + "".join(f"{value:02x}" for value in mixed)


def contrast_text(color: str) -> str:
    """Return readable black/white text for a solid semantic color."""
    value = optional_color(color) or "#000000"
    red, green, blue = (int(value[index : index + 2], 16) for index in (1, 3, 5))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#17202a" if luminance > 0.62 else "#ffffff"


def build_fluent_qss(
    theme: str,
    accent: str,
    branch_closed: str,
    branch_open: str,
    custom_colors: dict | None = None,
) -> str:
    accent = normalise_accent(accent)
    if theme in {"claude_light", "warm_light"} and accent == "#2563eb":
        accent = "#9b5a45"
    dark = theme == "fluent_dark"
    if dark:
        palette = {
            "window": "#090d13",
            "canvas": "#0c1118",
            "surface": "#151b24",
            "surface2": "#202936",
            "surface3": "#2a3544",
            "card": "#1b2430",
            "card_selected": "#243757",
            "selected_badge_fg": "#ffffff",
            "border": "#2b3645",
            "border_strong": "#3c4a5d",
            "fg": "#f4f7fb",
            "muted": "#b2bdca",
            "soft": "#e2e8f0",
            "input": "#101722",
            "hover": "#2d3a4a",
            "chip": "#1e5134",
            "chip_fg": "#d5f8df",
            "warn": "#60431b",
            "warn_fg": "#ffe2a3",
            "selection": "#2563eb",
            "selection_fg": "#ffffff",
            "disabled": "#7c8796",
        }
    elif theme == "claude_light":
        palette = {
            "window": "#f6f4ef",
            "canvas": "#fbfaf7",
            "surface": "#fbfaf7",
            "surface2": "#f0eee8",
            "surface3": "#e9e4dc",
            "card": "#fffefd",
            "card_selected": "#fff7f0",
            "selected_badge_fg": "#ffffff",
            "border": "#dfd6cd",
            "border_strong": "#bda99a",
            "fg": "#2d2925",
            "muted": "#756b62",
            "soft": "#3f3832",
            "input": "#fffefd",
            "hover": "#ebe5dd",
            "chip": "#edf3ec",
            "chip_fg": "#3e6a45",
            "warn": "#f2dfc7",
            "warn_fg": "#83543d",
            "selection": accent,
            "selection_fg": "#ffffff",
            "disabled": "#a59a90",
            "sidebar": "#f2f0eb",
            "sidebar_fg": "#3c3630",
            "sidebar_soft": "#5e554d",
            "sidebar_muted": "#8a7e74",
            "sidebar_hover": "#ebe6df",
            "sidebar_selected": "#e4dcd3",
            "sidebar_border": "#ded4ca",
        }
    elif theme == "warm_light":
        palette = {
            "window": "#f5f1ea",
            "canvas": "#ece7de",
            "surface": "#fffdf8",
            "surface2": "#efe7dc",
            "surface3": "#e3d9cb",
            "card": "#fffdf8",
            "card_selected": "#f7ece3",
            "selected_badge_fg": "#ffffff",
            "border": "#d9cfc0",
            "border_strong": "#bda996",
            "fg": "#2f2923",
            "muted": "#76695d",
            "soft": "#42382f",
            "input": "#fffefa",
            "hover": "#e7dccf",
            "chip": "#e4efe4",
            "chip_fg": "#365f40",
            "warn": "#f3e1bf",
            "warn_fg": "#835420",
            "selection": accent,
            "selection_fg": "#ffffff",
            "disabled": "#a69686",
            "sidebar": "#2f2923",
            "sidebar_fg": "#fffaf3",
            "sidebar_soft": "#eadfd2",
            "sidebar_muted": "#b8aa9b",
            "sidebar_hover": "#3c352f",
            "sidebar_selected": "#4a3d35",
            "sidebar_border": "#221d19",
        }
    else:
        palette = {
            "window": "#f5f7fa",
            "canvas": "#eef2f7",
            "surface": "#ffffff",
            "surface2": "#edf1f5",
            "surface3": "#e2e8f0",
            "card": "#ffffff",
            "card_selected": "#eef5ff",
            "selected_badge_fg": "#ffffff",
            "border": "#d7dee7",
            "border_strong": "#aebccc",
            "fg": "#17202a",
            "muted": "#617080",
            "soft": "#334155",
            "input": "#ffffff",
            "hover": "#e7edf4",
            "chip": "#e6f4ec",
            "chip_fg": "#166534",
            "warn": "#fff3d8",
            "warn_fg": "#92400e",
            "selection": "#2563eb",
            "selection_fg": "#ffffff",
            "disabled": "#94a3b8",
        }
    palette.setdefault("sidebar", palette["surface"])
    palette.setdefault("sidebar_fg", palette["fg"])
    palette.setdefault("sidebar_soft", palette["soft"])
    palette.setdefault("sidebar_muted", palette["muted"])
    palette.setdefault("sidebar_hover", palette["surface2"])
    palette.setdefault("sidebar_selected", palette["surface3"])
    palette.setdefault("sidebar_border", palette["border"])
    custom_colors = custom_colors or {}
    def semantic(name: str, legacy: str = "") -> str:
        return optional_color(str(custom_colors.get(name) or (custom_colors.get(legacy) if legacy else "") or ""))

    panel = semantic("ui_panel_color", "panel")
    canvas = semantic("ui_canvas_color", "canvas")
    button = semantic("ui_button_color", "button")
    if panel:
        palette["surface"] = panel
        palette["card"] = panel
        palette["input"] = _mix_hex(panel, "#000000" if dark else "#ffffff", 0.18 if dark else 0.38)
        palette["surface2"] = _mix_hex(panel, "#ffffff" if dark else "#000000", 0.08 if dark else 0.04)
        palette["surface3"] = _mix_hex(panel, "#ffffff" if dark else "#000000", 0.14 if dark else 0.08)
        palette["card_selected"] = _mix_hex(panel, accent, 0.16)
        palette["border"] = _mix_hex(panel, "#ffffff" if dark else "#000000", 0.18 if dark else 0.10)
        palette["border_strong"] = _mix_hex(panel, "#ffffff" if dark else "#000000", 0.28 if dark else 0.18)
        if theme not in {"warm_light", "claude_light"}:
            palette["sidebar"] = panel
            palette["sidebar_hover"] = palette["surface2"]
            palette["sidebar_selected"] = palette["surface3"]
            palette["sidebar_border"] = palette["border"]
    if canvas:
        palette["window"] = _mix_hex(canvas, "#000000" if dark else "#ffffff", 0.12)
        palette["canvas"] = canvas
    if button:
        palette["surface2"] = button
        palette["hover"] = _mix_hex(button, "#ffffff" if dark else "#000000", 0.12 if dark else 0.08)

    # More specific semantic roles deliberately run after the legacy broad
    # panel/canvas/button overrides. This makes each setting independent and
    # keeps old settings.json files working without a migration step.
    window = semantic("ui_window_color", "window")
    sidebar = semantic("ui_sidebar_color", "sidebar")
    card = semantic("ui_card_color", "card")
    input_color = semantic("ui_input_color", "input")
    text_color = semantic("ui_text_color", "text")
    muted_text = semantic("ui_muted_text_color", "muted_text")
    border = semantic("ui_border_color", "border")
    icon = semantic("ui_icon_color", "icon")
    button_hover = semantic("ui_button_hover_color", "button_hover")
    button_selected = semantic("ui_button_selected_color", "button_selected")
    if window:
        palette["window"] = window
    if sidebar:
        palette["sidebar"] = sidebar
        palette["sidebar_hover"] = _mix_hex(sidebar, "#ffffff" if dark else "#000000", 0.10 if dark else 0.06)
        palette["sidebar_selected"] = _mix_hex(sidebar, accent, 0.16)
    if card:
        palette["card"] = card
        palette["card_selected"] = _mix_hex(card, button_selected or accent, 0.14)
    if input_color:
        palette["input"] = input_color
    if text_color:
        palette["fg"] = text_color
        palette["soft"] = text_color
        if not semantic("ui_muted_text_color", "muted_text"):
            palette["muted"] = _mix_hex(text_color, palette["window"], 0.42)
    if muted_text:
        palette["muted"] = muted_text
        palette["disabled"] = _mix_hex(muted_text, palette["window"], 0.30)
    if border:
        palette["border"] = border
        palette["border_strong"] = _mix_hex(border, palette["fg"], 0.24)
        palette["sidebar_border"] = border
    if icon:
        palette["icon"] = icon
    else:
        palette["icon"] = palette["fg"]
    if button_hover:
        palette["hover"] = button_hover
    if button_selected:
        palette["selection"] = button_selected
        palette["selection_fg"] = contrast_text(button_selected)
        palette["card_selected"] = _mix_hex(palette["card"], button_selected, 0.14)
    return f"""
        * {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", Arial, sans-serif; }}
        QMainWindow, QDialog {{ background: {palette["window"]}; color: {palette["fg"]}; }}
        #Sidebar {{
            background: {palette["sidebar"]}; color: {palette["sidebar_fg"]};
            border-right: 1px solid {palette["sidebar_border"]};
        }}
        #SidebarLibraryBox {{
            background: {palette["sidebar_hover"]};
            border: 1px solid {palette["sidebar_border"]}; border-radius: 9px;
        }}
        QWidget {{ color: {palette["fg"]}; }}
        #MutedText, #TinyText, #SummaryText {{ color: {palette["muted"]}; }}
        #SummaryText {{ font-size: 12px; font-weight: 700; }}
        #StatusBar {{
            background: {palette["surface"]}; color: {palette["muted"]};
            border: 1px solid {palette["border"]}; border-radius: 8px;
            padding: 4px 9px; font-size: 11px; font-weight: 600;
        }}
        QLabel, QCheckBox, QRadioButton {{ color: {palette["soft"]}; font-size: 12px; }}
        QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
        #SidebarSectionTitle, #SettingsSectionTitle {{
            color: {palette["muted"]}; font-size: 11px; font-weight: 800; margin-top: 8px;
        }}
        #SidebarSectionTitle {{ color: {palette["sidebar_muted"]}; }}
        #BrandTitle {{ color: {palette["sidebar_fg"]}; font-size: 14px; font-weight: 900; }}
        #BrandSubtitle {{ color: {palette["sidebar_muted"]}; font-size: 10px; font-weight: 700; }}
        QPushButton {{
            border: 1px solid {palette["border"]}; border-radius: 8px; padding: 8px 12px;
            background: {palette["surface2"]}; color: {palette["fg"]}; font-weight: 700;
        }}
        QPushButton:hover {{ background: {palette["hover"]}; border-color: {palette["border_strong"]}; }}
        QPushButton:pressed {{ background: {_mix_hex(accent, palette["surface2"], 0.22)}; }}
        #Sidebar QPushButton {{
            background: transparent; color: {palette["sidebar_fg"]}; text-align: left; padding-left: 14px;
        }}
        #Sidebar QPushButton:hover {{ background: {palette["sidebar_hover"]}; }}
        #SidebarIconButton {{
            background: {palette["sidebar_hover"]}; color: {palette["sidebar_fg"]};
            border: 1px solid {palette["sidebar_selected"]}; border-radius: 8px;
            padding: 0; text-align: center;
        }}
        #SidebarIconButton:hover {{
            background: {palette["sidebar_selected"]}; border-color: {palette["sidebar_muted"]};
        }}
        #SidebarMiniButton {{
            background: transparent; color: {palette["sidebar_fg"]};
            border: 1px solid transparent; border-radius: 7px; padding: 0; text-align: center;
        }}
        #SidebarMiniButton:hover {{
            background: {palette["sidebar_selected"]}; border-color: {palette["sidebar_border"]};
        }}
        #ToolbarIconButton {{
            background: {palette["surface2"]}; color: {palette["icon"]};
            border: 1px solid {palette["border"]}; border-radius: 8px;
            padding: 0; text-align: center;
        }}
        #ToolbarIconButton:hover {{
            background: {palette["hover"]}; border-color: {palette["border_strong"]};
        }}
        #ToolbarIconButton::menu-indicator {{ image: none; width: 0; }}
        #ViewSwitchButton {{
            background: {palette["surface2"]}; color: {palette["soft"]};
            border: 1px solid {palette["border"]}; border-radius: 8px;
            padding: 0 12px; font-size: 12px; font-weight: 800;
        }}
        #ViewSwitchButton:checked {{
            background: {palette["selection"]}; color: {palette["selection_fg"]};
            border-color: {palette["selection"]};
        }}
        #Hero {{ background: transparent; border: none; }}
        #Panel {{
            background: {palette["surface"]}; border: 1px solid {palette["border"]}; border-radius: 8px;
        }}
        #CommandBar {{
            background: {palette["card"]}; border: 1px solid {palette["border"]}; border-radius: 8px;
        }}
        #CommandIconButton {{
            background: {palette["surface2"]}; color: {palette["icon"]};
            border: 1px solid {palette["border"]}; border-radius: 8px; padding: 0;
        }}
        #CommandIconButton:hover {{ background: {palette["hover"]}; border-color: {palette["border_strong"]}; }}
        #CommandRunButton {{
            background: {accent}; color: white; border: 1px solid {accent};
            border-radius: 8px; padding: 0 14px; font-size: 12px; font-weight: 900;
        }}
        #CommandRunButton:hover {{ background: {_mix_hex(accent, "#000000", 0.08)}; border-color: {_mix_hex(accent, "#000000", 0.08)}; }}
        #CommandCancelButton {{
            background: transparent; color: {palette["muted"]};
            border: 1px solid {palette["border"]}; border-radius: 8px;
            padding: 0 12px; font-size: 11px; font-weight: 700;
        }}
        #CommandCancelButton:hover {{
            background: {palette["warn"]}; color: {palette["warn_fg"]};
            border-color: {palette["border_strong"]};
        }}
        #CanvasPanel {{
            background: {palette["canvas"]}; border: 1px solid {palette["border"]}; border-radius: 8px;
        }}
        QScrollArea#CardWall {{
            background: {palette["canvas"]}; border: none;
        }}
        QScrollArea#CardWall > QWidget {{
            background: {palette["canvas"]};
        }}
        QScrollArea#SettingsScroll, QScrollArea#SettingsScroll > QWidget,
        QScrollArea#SettingsScroll > QWidget > QWidget {{
            background: {palette["window"]}; border: none;
        }}
        QScrollArea#ThemeControlsScroll, QScrollArea#ThemeControlsScroll > QWidget,
        QScrollArea#ThemeControlsScroll > QWidget > QWidget {{
            background: transparent; border: none;
        }}
        #ThemeRoleRow, #ThemePreviewPanel {{
            background: {palette["surface"]}; border: 1px solid {palette["border"]}; border-radius: 8px;
        }}
        #ThemeGroupTitle, #ThemeRoleLabel {{ color: {palette["fg"]}; font-weight: 800; }}
        #ThemeGroupTitle {{ font-size: 12px; }}
        #ThemeRoleDescription {{ color: {palette["muted"]}; font-size: 10px; }}
        #ThemeResetButton {{
            background: transparent; color: {palette["muted"]}; border: 1px solid transparent; border-radius: 6px;
        }}
        #ThemeResetButton:hover {{ background: {palette["hover"]}; color: {palette["fg"]}; }}
        #ThemePresetButton {{ padding: 6px 10px; font-size: 11px; }}
        #MasonrySurface {{ background: {palette["canvas"]}; border: none; }}
        #AnalysisStateBox {{
            background: {palette["surface"]}; border: 1px solid {palette["border"]};
            border-radius: 9px;
        }}
        #AnalysisShimmerText {{ color: {palette["muted"]}; font-size: 13px; font-weight: 800; }}
        QProgressBar#AnalysisProgress {{
            background: {palette["surface2"]}; border: none; border-radius: 2px;
        }}
        QProgressBar#AnalysisProgress::chunk {{
            background: {palette["selection"]}; border-radius: 2px;
        }}
        QLineEdit, QComboBox, QSpinBox, QTextEdit {{
            border: 1px solid {palette["border"]}; border-radius: 8px; padding: 8px 11px;
            background: {palette["input"]}; color: {palette["fg"]}; font-size: 12px;
        }}
        QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTextEdit:disabled {{
            background: {palette["surface2"]}; color: {palette["disabled"]}; border-color: {palette["border"]};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus {{
            border: 1px solid {accent};
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView, QListWidget {{
            background: {palette["surface"]}; color: {palette["fg"]};
            border: 1px solid {palette["border"]}; selection-background-color: {palette["selection"]};
            selection-color: {palette["selection_fg"]}; outline: none;
        }}
        QListWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {palette["border"]}; }}
        QListWidget::item:selected {{ background: {palette["selection"]}; color: {palette["selection_fg"]}; }}
        QDialogButtonBox QPushButton {{
            min-width: 72px;
        }}
        #PathTree {{
            background: transparent; border: none; color: {palette["sidebar_soft"]}; outline: none;
        }}
        #PathTree::item {{ min-height: 30px; padding: 5px 7px; border-radius: 7px; }}
        #PathTree::item:hover {{ background: {palette["sidebar_hover"]}; color: {palette["sidebar_fg"]}; }}
        #PathTree::item:selected {{
            background: {palette["sidebar_selected"]}; color: {palette["sidebar_fg"]};
        }}
        #ResourceCard {{
            background: {palette["card"]}; border: 1px solid {palette["border"]}; border-radius: 8px;
        }}
        #ResourceCard:hover {{ border-color: {palette["border_strong"]}; background: {palette["card_selected"]}; }}
        #ResourceCard[selected="true"] {{
            border: 2px solid {palette["selection"]}; background: {palette["card_selected"]};
        }}
        #CardSelectedBadge {{
            background: {palette["selection"]}; color: {palette["selection_fg"]};
            border: 2px solid {palette["card"]}; border-radius: 14px;
            font-size: 16px; font-weight: 900;
        }}
        #CardPreview, #PreviewBox {{
            background: {palette["surface3"]}; border: 1px solid {palette["border"]}; border-radius: 7px;
            color: {palette["muted"]}; font-size: 13px;
        }}
        #CardPreview[empty="true"] {{
            background: {palette["surface2"]}; color: {palette["muted"]};
        }}
        #CardTitle, #PageTitle, #SectionTitle {{ color: {palette["fg"]}; font-weight: 800; }}
        #PageTitle {{ font-size: 15px; }}
        #TypeChip {{ background: {palette["chip"]}; color: {palette["chip_fg"]}; }}
        #ConfidenceChip {{ background: {palette["warn"]}; color: {palette["warn_fg"]}; }}
        #StatusChip {{
            background: {palette["surface2"]}; color: {palette["selection"]};
            border: 1px solid {palette["border"]};
        }}
        #StatusChip[warning="true"] {{ background: {palette["warn"]}; color: {palette["warn_fg"]}; }}
        #TypeChip, #ConfidenceChip, #StatusChip {{
            border-radius: 5px; padding: 2px 6px; font-size: 10px; font-weight: 800;
        }}
        #CardTags, #CardHint {{ color: {palette["muted"]}; font-size: 11px; }}
        #CardTarget, #CardTargetInline {{
            color: {palette["soft"]}; background: {palette["surface2"]};
            border: 1px solid {palette["border"]}; border-radius: 5px; padding: 2px 5px;
            font-size: 10px;
        }}
        #CardHoverOverlay {{ background: rgba(4, 10, 20, 136); border-radius: 7px; }}
        #HoverIconButton {{
            background: {palette["surface"]}; color: {palette["fg"]};
            border-radius: 8px; padding: 0; font-size: 11px; font-weight: 800;
        }}
        #HoverTextButton, #SettingsActionButton {{
            background: {accent}; color: white; border-color: {accent};
            border-radius: 8px; padding: 5px 9px; font-size: 11px; font-weight: 800;
        }}
        QMenu {{
            background: {palette["surface"]}; border: 1px solid {palette["border"]}; padding: 6px;
            color: {palette["fg"]};
        }}
        QMenu::item {{ padding: 7px 28px 7px 12px; color: {palette["fg"]}; }}
        QMenu::item:selected {{ background: {palette["surface2"]}; color: {accent}; }}
        QScrollBar:vertical {{
            background: transparent; width: 8px; margin: 4px 2px 4px 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {palette["border"]}; border-radius: 4px; min-height: 42px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; background: transparent; border: none;
        }}
        QScrollBar:horizontal {{
            background: transparent; height: 8px; margin: 2px 4px 2px 4px;
        }}
        QScrollBar::handle:horizontal {{
            background: {palette["border"]}; border-radius: 4px; min-width: 42px;
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0; background: transparent; border: none;
        }}
        #EmptyWallText {{ color: {palette["muted"]}; font-size: 13px; font-weight: 600; }}
        QToolTip {{
            background: {palette["surface"]}; color: {palette["fg"]};
            border: 1px solid {palette["border"]}; border-radius: 6px; padding: 5px 7px;
        }}
        #PathTree::branch:closed:has-children {{ image: url("{branch_closed}"); }}
        #PathTree::branch:open:has-children {{ image: url("{branch_open}"); }}
        #PathTree::branch:has-children:closed {{ image: url("{branch_closed}"); }}
        #PathTree::branch:has-children:open {{ image: url("{branch_open}"); }}
        #PathTree::branch:!has-children {{ image: none; }}
    """
