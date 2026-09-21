"""
F1 Brand Theme — Central QSS Stylesheet
Official F1 colors: Red #E10600, Black #15151E, Dark Grey #2C2C2C
"""

F1_RED       = "#E10600"
F1_RED_DARK  = "#B00000"
F1_BLACK     = "#15151E"
F1_DARK      = "#1E1E2A"
F1_GREY      = "#2C2C3A"
F1_GREY_MID  = "#3D3D50"
F1_GREY_LITE = "#6B6B80"
F1_WHITE     = "#FFFFFF"
F1_OFF_WHITE = "#E8E8F0"
F1_GREEN     = "#00D2BE"
F1_YELLOW    = "#FFD700"

F1_STYLESHEET = f"""
/* ─── Global ─── */
QWidget {{
    background-color: {F1_BLACK};
    color: {F1_OFF_WHITE};
    font-family: "Inter", "Segoe UI", "Arial", sans-serif;
    font-size: 13px;
    selection-background-color: {F1_RED};
    selection-color: {F1_WHITE};
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {F1_BLACK};
}}

/* ─── Scrollbars ─── */
QScrollBar:vertical {{
    background: {F1_DARK};
    width: 8px;
    border: none;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {F1_GREY_MID};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {F1_RED}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: {F1_DARK};
    height: 8px;
    border: none;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {F1_GREY_MID};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {F1_RED}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ─── Labels ─── */
QLabel {{
    background: transparent;
    color: {F1_OFF_WHITE};
    padding: 1px 0;
}}
QLabel#header_label {{
    font-size: 22px;
    font-weight: 900;
    color: {F1_WHITE};
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 8px 0 4px 0;
}}

/* ─── Push Buttons ─── */
QPushButton {{
    background-color: {F1_RED};
    color: {F1_WHITE};
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    min-height: 34px;
}}
QPushButton:hover {{
    background-color: {F1_RED_DARK};
}}
QPushButton:pressed {{
    background-color: #8B0000;
    padding-top: 9px;
    padding-bottom: 7px;
}}
QPushButton:disabled {{
    background-color: {F1_GREY};
    color: {F1_GREY_LITE};
}}

/* Settings / secondary buttons */
QPushButton#settings_btn {{
    background-color: {F1_GREY};
    color: {F1_OFF_WHITE};
    font-size: 11px;
    padding: 6px 14px;
    min-height: 28px;
}}
QPushButton#settings_btn:hover {{
    background-color: {F1_GREY_MID};
    color: {F1_WHITE};
}}

/* Session launch buttons */
QPushButton.session_btn {{
    background-color: {F1_DARK};
    border: 1px solid {F1_GREY_MID};
    border-left: 3px solid {F1_RED};
    color: {F1_WHITE};
    text-align: left;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 40px;
    border-radius: 4px;
}}
QPushButton.session_btn:hover {{
    background-color: {F1_GREY};
    border-left-color: {F1_RED};
    color: {F1_WHITE};
}}

/* ─── ComboBox ─── */
QComboBox {{
    background-color: {F1_DARK};
    border: 1px solid {F1_GREY_MID};
    border-radius: 4px;
    color: {F1_OFF_WHITE};
    padding: 6px 12px;
    font-size: 13px;
    min-height: 32px;
    selection-background-color: {F1_RED};
}}
QComboBox:hover {{
    border-color: {F1_RED};
}}
QComboBox:focus {{
    border-color: {F1_RED};
    border-width: 2px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid {F1_GREY_MID};
    border-radius: 0 4px 4px 0;
    background: {F1_GREY};
}}
QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {F1_OFF_WHITE};
}}
QComboBox QAbstractItemView {{
    background-color: {F1_DARK};
    border: 1px solid {F1_GREY_MID};
    border-radius: 4px;
    color: {F1_OFF_WHITE};
    selection-background-color: {F1_RED};
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    padding: 6px 12px;
    border-radius: 3px;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {F1_GREY};
}}

/* ─── Tree Widget (race schedule) ─── */
QTreeWidget {{
    background-color: {F1_DARK};
    alternate-background-color: {F1_GREY};
    border: 1px solid {F1_GREY_MID};
    border-radius: 8px;
    color: {F1_OFF_WHITE};
    font-size: 13px;
    gridline-color: transparent;
    selection-background-color: rgba(225, 6, 0, 0.25);
    selection-color: {F1_WHITE};
    outline: none;
    padding: 2px;
}}
QTreeWidget::item {{
    padding: 7px 8px;
    border-radius: 4px;
    min-height: 32px;
    border: none;
}}
QTreeWidget::item:hover {{
    background-color: rgba(255, 255, 255, 0.05);
}}
QTreeWidget::item:selected {{
    background-color: rgba(225, 6, 0, 0.2);
    color: {F1_WHITE};
    border-left: 3px solid {F1_RED};
}}
QHeaderView::section {{
    background-color: {F1_BLACK};
    color: {F1_GREY_LITE};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    padding: 8px 8px;
    border: none;
    border-bottom: 2px solid {F1_RED};
}}
QHeaderView::section:hover {{
    background-color: {F1_DARK};
    color: {F1_WHITE};
}}

/* ─── Line Edits / Text Inputs ─── */
QLineEdit {{
    background-color: {F1_DARK};
    border: 1px solid {F1_GREY_MID};
    border-radius: 4px;
    color: {F1_WHITE};
    padding: 7px 12px;
    font-size: 13px;
    selection-background-color: {F1_RED};
}}
QLineEdit:focus {{
    border-color: {F1_RED};
    border-width: 2px;
}}
QLineEdit:hover {{
    border-color: {F1_GREY_LITE};
}}

/* ─── Check Boxes ─── */
QCheckBox {{
    color: {F1_OFF_WHITE};
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {F1_GREY_MID};
    border-radius: 3px;
    background: {F1_DARK};
}}
QCheckBox::indicator:checked {{
    background-color: {F1_RED};
    border-color: {F1_RED};
    image: none;
}}
QCheckBox::indicator:hover {{
    border-color: {F1_RED};
}}

/* ─── Spin Box ─── */
QSpinBox, QDoubleSpinBox {{
    background-color: {F1_DARK};
    border: 1px solid {F1_GREY_MID};
    border-radius: 4px;
    color: {F1_WHITE};
    padding: 6px 10px;
    font-size: 13px;
    min-height: 32px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {F1_RED};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {F1_GREY};
    border: none;
    width: 20px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {F1_RED};
}}

/* ─── Group Box ─── */
QGroupBox {{
    border: 1px solid {F1_GREY_MID};
    border-radius: 8px;
    margin-top: 20px;
    padding-top: 12px;
    font-size: 12px;
    font-weight: 700;
    color: {F1_GREY_LITE};
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    left: 12px;
    color: {F1_RED};
    font-weight: 700;
    letter-spacing: 0.8px;
}}

/* ─── Tab Widget ─── */
QTabWidget::pane {{
    border: 1px solid {F1_GREY_MID};
    border-radius: 0 8px 8px 8px;
    background: {F1_DARK};
}}
QTabBar::tab {{
    background: {F1_GREY};
    color: {F1_GREY_LITE};
    padding: 8px 20px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-radius: 4px 4px 0 0;
    margin-right: 2px;
    min-width: 80px;
}}
QTabBar::tab:selected {{
    background: {F1_RED};
    color: {F1_WHITE};
}}
QTabBar::tab:hover:!selected {{
    background: {F1_GREY_MID};
    color: {F1_WHITE};
}}

/* ─── Progress Dialog ─── */
QProgressDialog {{
    background-color: {F1_BLACK};
    border: 1px solid {F1_GREY_MID};
    border-radius: 8px;
    color: {F1_WHITE};
}}
QProgressDialog QLabel {{
    color: {F1_OFF_WHITE};
    font-size: 14px;
    padding: 12px;
}}
QProgressBar {{
    background: {F1_GREY};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {F1_RED};
    border-radius: 4px;
}}

/* ─── Message Box ─── */
QMessageBox {{
    background-color: {F1_DARK};
    color: {F1_WHITE};
}}
QMessageBox QLabel {{
    color: {F1_OFF_WHITE};
    font-size: 13px;
}}

/* ─── Tool Tip ─── */
QToolTip {{
    background-color: {F1_DARK};
    color: {F1_WHITE};
    border: 1px solid {F1_GREY_MID};
    border-radius: 4px;
    padding: 5px 10px;
    font-size: 12px;
}}

/* ─── Status Bar ─── */
QStatusBar {{
    background-color: {F1_BLACK};
    color: {F1_GREY_LITE};
    border-top: 1px solid {F1_GREY};
    font-size: 11px;
}}

/* ─── Splitter ─── */
QSplitter::handle {{
    background: {F1_GREY_MID};
    width: 2px;
    height: 2px;
}}

/* ─── Frame ─── */
QFrame[frameShape="4"],   /* HLine */
QFrame[frameShape="5"] {{ /* VLine */
    color: {F1_GREY_MID};
    background: {F1_GREY_MID};
    border: none;
    max-height: 1px;
}}
"""


def apply_f1_theme(app) -> None:
    """Apply the F1 brand stylesheet to a QApplication instance."""
    from PySide6.QtGui import QPalette, QColor, QFont
    from PySide6.QtCore import Qt

    # Set dark palette first (prevents white flash before stylesheet loads)
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(F1_BLACK))
    palette.setColor(QPalette.WindowText,      QColor(F1_OFF_WHITE))
    palette.setColor(QPalette.Base,            QColor(F1_DARK))
    palette.setColor(QPalette.AlternateBase,   QColor(F1_GREY))
    palette.setColor(QPalette.ToolTipBase,     QColor(F1_DARK))
    palette.setColor(QPalette.ToolTipText,     QColor(F1_WHITE))
    palette.setColor(QPalette.Text,            QColor(F1_OFF_WHITE))
    palette.setColor(QPalette.Button,          QColor(F1_GREY))
    palette.setColor(QPalette.ButtonText,      QColor(F1_WHITE))
    palette.setColor(QPalette.BrightText,      QColor(F1_RED))
    palette.setColor(QPalette.Link,            QColor(F1_RED))
    palette.setColor(QPalette.Highlight,       QColor(F1_RED))
    palette.setColor(QPalette.HighlightedText, QColor(F1_WHITE))
    app.setPalette(palette)

    # Apply stylesheet
    app.setStyleSheet(F1_STYLESHEET)

    # Set default font
    font = QFont("Inter", 13)
    font.setWeight(QFont.Normal)
    app.setFont(font)
