"""Full window application for CrateCloud using PyQt6."""

import logging
import sys
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def check_pyqt_available() -> bool:
    """Check if PyQt6 is available."""
    try:
        from PyQt6 import QtWidgets
        return True
    except ImportError:
        return False


class CrateCloudWindow:
    """
    Full window application for CrateCloud.

    Features:
    - Library browser with track list
    - Sync status and progress
    - Crate management
    - Settings/preferences
    - Group management for sharing
    """

    def __init__(self, sync_engine=None, config=None):
        """
        Initialize the window application.

        Args:
            sync_engine: SyncEngine instance.
            config: Configuration instance.
        """
        self.sync_engine = sync_engine
        self.config = config
        self._app = None
        self._window = None

    def _create_app(self):
        """Create the PyQt application and main window."""
        try:
            from PyQt6.QtCore import Qt, QTimer
            from PyQt6.QtGui import QAction, QFont
            from PyQt6.QtWidgets import (
                QApplication,
                QHBoxLayout,
                QHeaderView,
                QLabel,
                QLineEdit,
                QMainWindow,
                QProgressBar,
                QPushButton,
                QSplitter,
                QStatusBar,
                QTableWidget,
                QTableWidgetItem,
                QTabWidget,
                QTreeWidget,
                QTreeWidgetItem,
                QVBoxLayout,
                QWidget,
            )
        except ImportError:
            logger.error("PyQt6 not installed. Install with: pip install 'cratecloud[ui]'")
            raise

        class MainWindow(QMainWindow):
            def __init__(mw_self, sync_engine, config):
                super().__init__()
                mw_self.sync_engine = sync_engine
                mw_self.config = config
                mw_self._setup_ui()
                mw_self._setup_timer()

            def _setup_ui(mw_self):
                """Set up the main window UI."""
                mw_self.setWindowTitle("CrateCloud")
                mw_self.setMinimumSize(1000, 700)

                # Central widget
                central = QWidget()
                mw_self.setCentralWidget(central)
                layout = QVBoxLayout(central)

                # Top bar with search and sync button
                top_bar = QHBoxLayout()

                search_input = QLineEdit()
                search_input.setPlaceholderText("Search tracks...")
                search_input.setMinimumWidth(300)
                top_bar.addWidget(search_input)

                top_bar.addStretch()

                sync_btn = QPushButton("Sync Now")
                sync_btn.clicked.connect(mw_self._on_sync_clicked)
                top_bar.addWidget(sync_btn)

                layout.addLayout(top_bar)

                # Main content splitter
                splitter = QSplitter(Qt.Orientation.Horizontal)

                # Left sidebar - Crates tree
                sidebar = QWidget()
                sidebar_layout = QVBoxLayout(sidebar)
                sidebar_layout.setContentsMargins(0, 0, 0, 0)

                sidebar_label = QLabel("Library")
                sidebar_label.setFont(QFont("", 12, QFont.Weight.Bold))
                sidebar_layout.addWidget(sidebar_label)

                mw_self.crates_tree = QTreeWidget()
                mw_self.crates_tree.setHeaderHidden(True)
                mw_self.crates_tree.itemClicked.connect(mw_self._on_crate_selected)
                sidebar_layout.addWidget(mw_self.crates_tree)

                # Add default items
                all_tracks = QTreeWidgetItem(["All Tracks"])
                mw_self.crates_tree.addTopLevelItem(all_tracks)

                pending = QTreeWidgetItem(["Pending Upload"])
                mw_self.crates_tree.addTopLevelItem(pending)

                synced = QTreeWidgetItem(["Synced"])
                mw_self.crates_tree.addTopLevelItem(synced)

                crates_header = QTreeWidgetItem(["Crates"])
                mw_self.crates_tree.addTopLevelItem(crates_header)

                sidebar.setMaximumWidth(250)
                splitter.addWidget(sidebar)

                # Right content - Track list and details
                content = QWidget()
                content_layout = QVBoxLayout(content)
                content_layout.setContentsMargins(0, 0, 0, 0)

                # Tabs for different views
                tabs = QTabWidget()

                # Tracks tab
                tracks_widget = QWidget()
                tracks_layout = QVBoxLayout(tracks_widget)

                mw_self.tracks_table = QTableWidget()
                mw_self.tracks_table.setColumnCount(7)
                mw_self.tracks_table.setHorizontalHeaderLabels([
                    "Title", "Artist", "BPM", "Key", "Duration", "Status", "Size"
                ])
                mw_self.tracks_table.horizontalHeader().setSectionResizeMode(
                    0, QHeaderView.ResizeMode.Stretch
                )
                mw_self.tracks_table.horizontalHeader().setSectionResizeMode(
                    1, QHeaderView.ResizeMode.Stretch
                )
                mw_self.tracks_table.setSelectionBehavior(
                    QTableWidget.SelectionBehavior.SelectRows
                )
                tracks_layout.addWidget(mw_self.tracks_table)

                tabs.addTab(tracks_widget, "Tracks")

                # Groups tab (for sharing)
                groups_widget = QWidget()
                groups_layout = QVBoxLayout(groups_widget)
                groups_label = QLabel("Groups feature coming soon...")
                groups_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                groups_layout.addWidget(groups_label)
                tabs.addTab(groups_widget, "Groups")

                # Settings tab
                settings_widget = QWidget()
                settings_layout = QVBoxLayout(settings_widget)
                settings_label = QLabel("Settings feature coming soon...")
                settings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                settings_layout.addWidget(settings_label)
                tabs.addTab(settings_widget, "Settings")

                content_layout.addWidget(tabs)
                splitter.addWidget(content)

                splitter.setSizes([200, 800])
                layout.addWidget(splitter)

                # Progress bar
                mw_self.progress_bar = QProgressBar()
                mw_self.progress_bar.setVisible(False)
                layout.addWidget(mw_self.progress_bar)

                # Status bar
                mw_self.status_bar = QStatusBar()
                mw_self.setStatusBar(mw_self.status_bar)
                mw_self._update_status_bar()

                # Menu bar
                mw_self._setup_menu()

            def _setup_menu(mw_self):
                """Set up the menu bar."""
                menubar = mw_self.menuBar()

                # File menu
                file_menu = menubar.addMenu("File")

                scan_action = QAction("Scan Library", mw_self)
                scan_action.triggered.connect(mw_self._on_scan_library)
                file_menu.addAction(scan_action)

                file_menu.addSeparator()

                quit_action = QAction("Quit", mw_self)
                quit_action.triggered.connect(mw_self.close)
                file_menu.addAction(quit_action)

                # Help menu
                help_menu = menubar.addMenu("Help")

                about_action = QAction("About CrateCloud", mw_self)
                about_action.triggered.connect(mw_self._show_about)
                help_menu.addAction(about_action)

            def _setup_timer(mw_self):
                """Set up a timer to refresh the UI."""
                mw_self.refresh_timer = QTimer()
                mw_self.refresh_timer.timeout.connect(mw_self._refresh_ui)
                mw_self.refresh_timer.start(5000)  # Refresh every 5 seconds

            def _refresh_ui(mw_self):
                """Refresh UI with latest data."""
                mw_self._update_status_bar()

            def _update_status_bar(mw_self):
                """Update the status bar with sync state."""
                if mw_self.sync_engine:
                    try:
                        state = mw_self.sync_engine.get_sync_state()
                        status_text = f"Tracks: {state.synced_tracks}/{state.total_tracks} synced"
                        if state.pending_tracks > 0:
                            status_text += f" | {state.pending_tracks} pending"
                        if state.error_tracks > 0:
                            status_text += f" | {state.error_tracks} errors"
                        mw_self.status_bar.showMessage(status_text)
                    except Exception as e:
                        mw_self.status_bar.showMessage(f"Error: {e}")
                else:
                    mw_self.status_bar.showMessage("Not connected")

            def _on_sync_clicked(mw_self):
                """Handle sync button click."""
                if not mw_self.sync_engine:
                    mw_self.status_bar.showMessage("Sync engine not configured")
                    return

                mw_self.progress_bar.setVisible(True)
                mw_self.progress_bar.setRange(0, 0)  # Indeterminate

                def do_sync():
                    try:
                        mw_self.sync_engine.scan_and_index()
                        mw_self.sync_engine.queue_pending_uploads()
                        mw_self._load_tracks()
                    except Exception as e:
                        logger.error(f"Sync failed: {e}")
                    finally:
                        mw_self.progress_bar.setVisible(False)

                threading.Thread(target=do_sync, daemon=True).start()

            def _on_scan_library(mw_self):
                """Handle scan library menu action."""
                mw_self._on_sync_clicked()

            def _on_crate_selected(mw_self, item, column):
                """Handle crate selection in sidebar."""
                crate_name = item.text(0)
                logger.info(f"Selected crate: {crate_name}")
                mw_self._load_tracks(crate_name)

            def _load_tracks(mw_self, filter_crate: Optional[str] = None):
                """Load tracks into the table."""
                if not mw_self.sync_engine:
                    return

                try:
                    from cratecloud.core.models import SyncStatus

                    tracks = mw_self.sync_engine.db.get_all_tracks()

                    # Apply filters
                    if filter_crate == "Pending Upload":
                        tracks = [t for t in tracks if t.sync_status in (SyncStatus.PENDING, SyncStatus.MODIFIED)]
                    elif filter_crate == "Synced":
                        tracks = [t for t in tracks if t.sync_status == SyncStatus.SYNCED]

                    mw_self.tracks_table.setRowCount(len(tracks))

                    for row, track in enumerate(tracks):
                        mw_self.tracks_table.setItem(row, 0, QTableWidgetItem(track.title or track.file_path.stem))
                        mw_self.tracks_table.setItem(row, 1, QTableWidgetItem(track.artist or ""))
                        mw_self.tracks_table.setItem(row, 2, QTableWidgetItem(f"{track.bpm:.1f}" if track.bpm else ""))
                        mw_self.tracks_table.setItem(row, 3, QTableWidgetItem(track.key or ""))

                        # Duration
                        if track.duration_ms:
                            mins = int(track.duration_ms / 60000)
                            secs = int((track.duration_ms % 60000) / 1000)
                            mw_self.tracks_table.setItem(row, 4, QTableWidgetItem(f"{mins}:{secs:02d}"))
                        else:
                            mw_self.tracks_table.setItem(row, 4, QTableWidgetItem(""))

                        mw_self.tracks_table.setItem(row, 5, QTableWidgetItem(track.sync_status.value))

                        # Size in MB
                        size_mb = track.file_size / (1024 * 1024)
                        mw_self.tracks_table.setItem(row, 6, QTableWidgetItem(f"{size_mb:.1f} MB"))

                except Exception as e:
                    logger.error(f"Error loading tracks: {e}")

            def _show_about(mw_self):
                """Show about dialog."""
                from PyQt6.QtWidgets import QMessageBox

                QMessageBox.about(
                    mw_self,
                    "About CrateCloud",
                    "CrateCloud v0.1.0\n\n"
                    "Cloud backup and sharing platform for DJs.\n\n"
                    "Automatically backup your Serato library to the cloud "
                    "and share tracks with your crew."
                )

            def closeEvent(mw_self, event):
                """Handle window close."""
                if mw_self.sync_engine:
                    mw_self.sync_engine.close()
                event.accept()

        # Create application
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._window = MainWindow(self.sync_engine, self.config)
        return self._app, self._window

    def run(self):
        """Run the window application."""
        if not check_pyqt_available():
            logger.error("PyQt6 not available.")
            print("Error: Window app requires PyQt6 package.")
            print("Install with: pip install 'cratecloud[ui]'")
            return 1

        app, window = self._create_app()
        window.show()

        # Load initial data if sync engine available
        if self.sync_engine:
            window._load_tracks()

        logger.info("Starting CrateCloud window app...")
        return app.exec()

    def stop(self):
        """Stop the application."""
        if self._app:
            self._app.quit()


def run_window_app(sync_engine=None, config=None):
    """
    Convenience function to run the window app.

    Args:
        sync_engine: Optional SyncEngine instance.
        config: Optional configuration.

    Returns:
        Exit code.
    """
    app = CrateCloudWindow(sync_engine=sync_engine, config=config)
    return app.run()


if __name__ == "__main__":
    sys.exit(run_window_app())
