from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTreeWidget, QTreeWidgetItem, QMessageBox, QFrame
)
from PySide6.QtWidgets import QProgressDialog
from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QFont, QColor, QPalette
import sys
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from src.f1_data import get_race_weekends_by_year, get_race_weekends_by_place, get_all_unique_race_names, load_session
from src.gui.settings_dialog import SettingsDialog
from src.lib.season import get_season
from src.lib.f1_theme import F1_RED, F1_BLACK, F1_DARK, F1_GREY, F1_GREY_MID, F1_GREY_LITE, F1_WHITE, F1_OFF_WHITE

# Worker thread to fetch schedule without blocking UI
class FetchScheduleWorker(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, year, parent=None):
        super().__init__(parent)
        self.year = year

    def run(self): #check
        try:
            # enable cache if available in project
            try:
                from src.f1_data import enable_cache
                enable_cache()
            except Exception:
                pass
            events = get_race_weekends_by_year(self.year)
            self.result.emit(events)
        except Exception as e:
            self.error.emit(str(e))

class RaceSelectionWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.loading_session = False
        self.selected_session_title = None
        self.current_year = get_season()
        self.selected_year = self.current_year

        self.setWindowTitle("Formula 1 · Session Selection")
        self._setup_ui()
        self.resize(1080, 720)
        self.setMinimumSize(860, 620)
        self.setWindowState(self.windowState())

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)

        # ── Red accent top bar (racing stripe)
        accent_bar = QFrame()
        accent_bar.setFixedHeight(4)
        accent_bar.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {F1_RED}, stop:0.6 {F1_RED}, stop:1 transparent);"
            f"border:none;"
        )
        main_layout.addWidget(accent_bar)

        # ── Header bar
        header_container = QWidget()
        header_container.setStyleSheet(
            f"background-color: {F1_BLACK};"
            f"border-bottom: 1px solid {F1_GREY_MID};"
        )
        header_container.setFixedHeight(64)
        header_h_layout = QHBoxLayout(header_container)
        header_h_layout.setContentsMargins(24, 0, 24, 0)

        # F1 logo badge
        logo_badge = QLabel("F1")
        logo_badge.setFixedSize(38, 38)
        logo_badge.setAlignment(Qt.AlignCenter)
        logo_badge.setStyleSheet(
            f"background-color: {F1_RED};"
            f"color: {F1_WHITE};"
            f"font-size: 14px; font-weight: 900;"
            f"border-radius: 4px;"
            f"letter-spacing: 1px;"
        )

        # Title
        header_label = QLabel("FORMULA <span style='color:{}'>&nbsp;1</span> · Live Replay".format(F1_RED))
        header_label.setObjectName("header_label")
        header_label.setTextFormat(Qt.RichText)
        header_font = QFont("Inter", 16, QFont.Bold)
        header_label.setFont(header_font)
        header_label.setStyleSheet(f"color: {F1_WHITE}; background: transparent;")

        settings_btn = QPushButton("⚙  Settings")
        settings_btn.setObjectName("settings_btn")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.setFixedHeight(34)
        settings_btn.clicked.connect(self.open_settings)

        header_h_layout.addWidget(logo_badge)
        header_h_layout.addSpacing(12)
        header_h_layout.addWidget(header_label)
        header_h_layout.addStretch()
        header_h_layout.addWidget(settings_btn)
        main_layout.addWidget(header_container)

        # ── Inner content with padding
        inner_widget = QWidget()
        inner_layout = QVBoxLayout(inner_widget)
        inner_layout.setContentsMargins(20, 16, 20, 16)
        inner_layout.setSpacing(12)
        main_layout.addWidget(inner_widget)
        main_layout = inner_layout  # redirect further additions here

        # ── Filter row: Year + Race selectors
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        year_label = QLabel("Year")
        year_label.setStyleSheet(f"color:{F1_GREY_LITE};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;")
        self.year_combo = QComboBox()
        self.year_combo.addItem("All Years")
        for year in range(2018, self.current_year + 1):
            self.year_combo.addItem(str(year))
        self.year_combo.setCurrentText(str(self.current_year))
        self.year_combo.currentTextChanged.connect(self.load_by_year)
        self.year_combo.setFixedWidth(160)

        place_label = QLabel("Grand Prix")
        place_label.setStyleSheet(f"color:{F1_GREY_LITE};font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;")
        self.place_combo = QComboBox()
        self.place_combo.addItem("All Races")
        self.place_combo.addItems(get_all_unique_race_names())
        self.place_combo.currentTextChanged.connect(self.load_by_place)
        self.place_combo.setMinimumWidth(220)

        filter_row.addWidget(year_label)
        filter_row.addWidget(self.year_combo)
        filter_row.addSpacing(16)
        filter_row.addWidget(place_label)
        filter_row.addWidget(self.place_combo)
        filter_row.addStretch()
        main_layout.addLayout(filter_row)

        # ── Main content: left = schedule tree, right = session panel
        content_layout = QHBoxLayout()
        content_layout.setSpacing(16)

        # Schedule tree (left)
        self.schedule_tree = QTreeWidget()
        self.schedule_tree.setHeaderLabels(["Rnd", "Grand Prix", "Country", "Date"])
        self.schedule_tree.setRootIsDecorated(False)
        self.schedule_tree.setAlternatingRowColors(True)
        self.schedule_tree.setSortingEnabled(False)
        self.schedule_tree.setColumnWidth(0, 50)
        self.schedule_tree.setColumnWidth(2, 140)
        content_layout.addWidget(self.schedule_tree, 3)

        # Session panel (right)
        self.session_panel = QWidget()
        self.session_panel.setStyleSheet(
            f"background-color:{F1_DARK};"
            f"border:1px solid {F1_GREY_MID};"
            f"border-radius:8px;"
        )
        self.session_panel_layout = QVBoxLayout()
        self.session_panel_layout.setContentsMargins(16, 16, 16, 16)
        self.session_panel_layout.setSpacing(10)
        self.session_panel.setLayout(self.session_panel_layout)
        self.session_panel_layout.setAlignment(Qt.AlignTop)

        # Session panel header
        header_lbl = QLabel("SESSIONS")
        header_lbl.setStyleSheet(
            f"color:{F1_GREY_LITE};font-size:11px;font-weight:700;"
            f"letter-spacing:1.5px;text-transform:uppercase;"
            f"padding-bottom:8px;border-bottom:1px solid {F1_GREY_MID};"
            f"background:transparent;"
        )
        self.session_panel_layout.addWidget(header_lbl)

        # Container for session buttons
        self.session_list_container = QWidget()
        self.session_list_container.setStyleSheet("background:transparent;")
        self.session_list_layout = QVBoxLayout()
        self.session_list_layout.setSpacing(8)
        self.session_list_layout.setContentsMargins(0, 0, 0, 0)
        self.session_list_container.setLayout(self.session_list_layout)
        self.session_panel_layout.addWidget(self.session_list_container)
        self.session_panel_layout.addStretch()

        content_layout.addWidget(self.session_panel, 1)
        main_layout.addLayout(content_layout)

        # Connect click handler
        self.schedule_tree.itemClicked.connect(self.on_race_clicked)

        # Hide sessions panel until a weekend is selected
        self.session_panel.hide()
        self.load_schedule(year=self.current_year)
        
    def load_schedule(self, year=None, events=None):
        if self.loading_session:
            return
        
        self.schedule_tree.clear()
        # hide sessions panel while loading / when nothing selected
        try:
            self.session_panel.hide()
        except Exception:
            pass
        
        #Race filter
        if events is not None:
            self.populate_schedule(events)
            self.loading_session = False
            return
        
        #Year filter
        if year is not None:
            self.loading_session = True
            self.worker = FetchScheduleWorker(int(year))
            self.worker.result.connect(self.populate_schedule)
            self.worker.error.connect(self.show_error)
            self.worker.start()
            return
        
        self.loading_session=False

    def load_by_year(self, year_text):
        if self.loading_session:
            return
        
        #Reset by_race filter
        if year_text!="All Years":
            self.place_combo.blockSignals(True)
            self.place_combo.setCurrentText("All Races")
            self.place_combo.blockSignals(False)

        if year_text=="All Years":
            self.selected_year=None
            self.schedule_tree.clear()
            return
        
        if not year_text.isdigit():
            return
        
        self.selected_year=int(year_text)
        self.load_schedule(year=self.selected_year)

    def load_by_place(self,race_name):
        if race_name=="All Races":
            if self.selected_year is not None:
                self.load_schedule(year=self.selected_year)
            return
        
        #Reset year filter
        self.year_combo.blockSignals(True)
        self.year_combo.setCurrentText("All Years")
        self.year_combo.blockSignals(False)
        self.selected_year=None

        self.schedule_tree.clear()
        
        events=get_race_weekends_by_place(race_name)
        self.load_schedule(events=events)

    def populate_schedule(self, events):
        for event in events:
            # Ensure all columns are strings (QTreeWidgetItem expects text)
            round_str = str(event.get("round_number", ""))
            name = str(event.get("event_name", ""))
            country = str(event.get("country", ""))
            date = str(event.get("date", ""))

            event_item = QTreeWidgetItem([round_str, name, country, date])
            event_item.setData(0, Qt.UserRole, event)
            self.schedule_tree.addTopLevelItem(event_item)

        # Make sure the round column is wide enough to be visible
        try:
            self.schedule_tree.resizeColumnToContents(0)
            self.schedule_tree.resizeColumnToContents(1)
        except Exception:
            pass

        self.loading_session = False

    def on_race_clicked(self, item, column):
        ev = item.data(0, Qt.UserRole)
        # ensure the sessions panel is visible when a race is selected
        try:
            self.session_panel.show()
        except Exception:
            pass
        # determine sessions to show
        ev_type = (ev.get("type") or "").lower()
        sessions = ["Qualifying", "Race"]
        if "sprint" in ev_type:
            sessions.insert(0, "Sprint Qualifying")
            # show sprint-related session
            sessions.insert(2, "Sprint")

        # clear existing session widgets
        for i in reversed(range(self.session_list_layout.count())):
            w = self.session_list_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        # determine which sessions have already occurred (data available)
        now = datetime.now(timezone.utc)
        session_dates = ev.get("session_dates", {})

        available_sessions = []
        for s in sessions:
            session_date_str = session_dates.get(s)
            if session_date_str:
                try:
                    session_dt = datetime.fromisoformat(session_date_str)
                    if session_dt <= now:
                        available_sessions.append(s)
                except Exception:
                    available_sessions.append(s)
            else:
                # no date info means historical data — assume available
                available_sessions.append(s)

        if not available_sessions:
            label = QLabel("Sessions not available")
            label.setAlignment(Qt.AlignCenter)
            self.session_list_layout.addWidget(label)
        else:
            for s in sessions:
                if s in available_sessions:
                    btn = QPushButton(f"  ▶  {s}")
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.setMinimumHeight(44)
                    btn.setStyleSheet(
                        f"QPushButton {{"
                        f"  background-color: {F1_DARK};"
                        f"  border: 1px solid {F1_GREY_MID};"
                        f"  border-left: 4px solid {F1_RED};"
                        f"  color: {F1_WHITE};"
                        f"  text-align: left;"
                        f"  padding: 10px 16px;"
                        f"  font-size: 13px; font-weight: 600;"
                        f"  border-radius: 4px;"
                        f"}}"
                        f"QPushButton:hover {{"
                        f"  background-color: rgba(225,6,0,0.12);"
                        f"  border-left: 4px solid {F1_RED};"
                        f"  color: {F1_WHITE};"
                        f"}}"
                        f"QPushButton:pressed {{"
                        f"  background-color: rgba(225,6,0,0.22);"
                        f"}}"
                    )
                    btn.clicked.connect(
                        lambda _, sname=s, e=ev: self._on_session_button_clicked(e, sname)
                    )
                    self.session_list_layout.addWidget(btn)

    def _on_session_button_clicked(self, ev, session_label):
        """Launch main.py in a separate process to run the selected session.

        Uses the same CLI flags that `main.py` understands: `--qualifying`,
        `--sprint-qualifying`, `--sprint`. Runs the command detached so the
        Qt UI remains responsive.
        """
        try:
            year = ev.get("year") or self.selected_year
        except Exception:
            year = None

        try:
            round_no = int(ev.get("round_number"))
        except Exception:
            round_no = None

        # map button labels to CLI flags
        flag = None
        if session_label == "Qualifying":
            flag = "--qualifying"
        elif session_label == "Sprint Qualifying":
            flag = "--sprint-qualifying"
        elif session_label == "Sprint":
            flag = "--sprint"

        main_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "main.py")
        )
        cmd = [sys.executable, main_path, "--viewer"]
        if year is not None:
            cmd += ["--year", str(year)]
        if round_no is not None:
            cmd += ["--round", str(round_no)]
        if flag:
            cmd.append(flag)
        if "--verbose" in sys.argv:
            cmd.append("--verbose")
        # Show a modal loading dialog and load the session in a background thread.
        dlg = QProgressDialog("Loading session data...", None, 0, 0, self)
        dlg.setWindowTitle("Loading")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.setRange(0, 0)
        dlg.show()
        QApplication.processEvents()

        # Map label -> fastf1 session type code
        session_code = 'R'
        if session_label == "Qualifying":
            session_code = 'Q'
        elif session_label == "Sprint Qualifying":
            session_code = 'SQ'
        elif session_label == "Sprint":
            session_code = 'S'

        class FetchSessionWorker(QThread):
            result = Signal(object)
            error = Signal(str)

            def __init__(self, year, round_no, session_type, parent=None):
                super().__init__(parent)
                self.year = year
                self.round_no = round_no
                self.session_type = session_type

            def run(self):
                try:
                    # We skip loading the heavy telemetry in the GUI process 
                    # because the child process (main.py) will do it anyway.
                    # This prevents Out-Of-Memory (OOM) crashes by halving the RAM usage.
                    self.result.emit(True)
                except Exception as e:
                    self.error.emit(str(e))

        def _on_loaded(session_obj):
            # create a unique ready-file path and pass it to the child
            ready_path = os.path.join(tempfile.gettempdir(), f"f1_ready_{uuid.uuid4().hex}")
            cmd_with_ready = list(cmd) + ["--ready-file", ready_path]

            try:
                proc = subprocess.Popen(cmd_with_ready)
            except Exception as exc:
                try:
                    dlg.close()
                except Exception:
                    pass
                QMessageBox.critical(self, "Playback error", f"Failed to start playback:\n{exc}")
                return

            # Poll for ready file or child exit
            timer = QTimer(self)

            def _check_ready():
                try:
                    if os.path.exists(ready_path):
                        try:
                            dlg.close()
                        except Exception:
                            pass
                        timer.stop()
                        try:
                            os.remove(ready_path)
                        except Exception:
                            pass
                        return
                    # if process exited early, show error
                    if proc.poll() is not None:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                        timer.stop()
                        QMessageBox.critical(self, "Playback error", "Playback process exited before signaling readiness")
                except Exception:
                    # ignore transient file-system errors
                    pass

            timer.timeout.connect(_check_ready)
            timer.start(200)
            # keep references
            self._play_proc = proc
            self._ready_timer = timer

        def _on_error(msg):
            try:
                dlg.close()
            except Exception:
                pass
            QMessageBox.critical(self, "Load error", f"Failed to load session data:\n{msg}")

        worker = FetchSessionWorker(year, round_no, session_code)
        worker.result.connect(_on_loaded)
        worker.error.connect(_on_error)
        # Keep a reference so it doesn't get GC'd
        self._session_worker = worker
        worker.start()
    def show_error(self, message):
        QMessageBox.critical(self, "Error", f"Failed to load schedule: {message}")
        self.loading_session = False

    def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()
