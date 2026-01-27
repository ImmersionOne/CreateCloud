"""macOS Menu Bar application for CrateCloud."""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


def check_rumps_available() -> bool:
    """Check if rumps is available for menu bar app."""
    try:
        import rumps
        return True
    except ImportError:
        return False


class MenuBarApp:
    """
    Simple menu bar application for CrateCloud.

    Provides quick access to:
    - Sync status
    - Last sync time
    - Manual sync trigger
    - Open full app
    - Preferences
    - Quit
    """

    def __init__(self, sync_engine=None, config=None):
        """
        Initialize the menu bar app.

        Args:
            sync_engine: SyncEngine instance.
            config: Configuration instance.
        """
        self.sync_engine = sync_engine
        self.config = config
        self._app = None
        self._status_item = None

    def _create_app(self):
        """Create the rumps application."""
        try:
            import rumps
        except ImportError:
            logger.error("rumps not installed. Install with: pip install 'cratecloud[ui]'")
            raise

        class CrateCloudMenuBar(rumps.App):
            def __init__(app_self, sync_engine, config):
                super().__init__(
                    name="CrateCloud",
                    title="☁️",  # Cloud emoji as icon
                    quit_button=None,  # We'll add our own
                )
                app_self.sync_engine = sync_engine
                app_self.config = config
                app_self._setup_menu()

            def _setup_menu(app_self):
                """Set up the menu items."""
                app_self.menu = [
                    rumps.MenuItem("Status: Ready", callback=None),
                    rumps.MenuItem("Synced: 0 tracks", callback=None),
                    None,  # Separator
                    rumps.MenuItem("Sync Now", callback=app_self.sync_now),
                    rumps.MenuItem("Open CrateCloud", callback=app_self.open_full_app),
                    None,  # Separator
                    rumps.MenuItem("Preferences...", callback=app_self.open_preferences),
                    None,  # Separator
                    rumps.MenuItem("Quit CrateCloud", callback=app_self.quit_app),
                ]

            @rumps.timer(30)  # Update every 30 seconds
            def update_status(app_self, _):
                """Update the status display."""
                if app_self.sync_engine:
                    try:
                        state = app_self.sync_engine.get_sync_state()

                        # Update icon based on state
                        if state.is_syncing:
                            app_self.title = "🔄"  # Syncing
                        elif state.error_tracks > 0:
                            app_self.title = "⚠️"  # Has errors
                        elif state.pending_tracks > 0:
                            app_self.title = "☁️"  # Pending
                        else:
                            app_self.title = "✅"  # All synced

                        # Update menu items
                        if state.is_syncing:
                            app_self.menu["Status: Ready"].title = f"Status: Syncing..."
                        elif state.pending_tracks > 0:
                            app_self.menu["Status: Ready"].title = f"Status: {state.pending_tracks} pending"
                        else:
                            app_self.menu["Status: Ready"].title = "Status: Up to date"

                        app_self.menu["Synced: 0 tracks"].title = f"Synced: {state.synced_tracks}/{state.total_tracks} tracks"

                    except Exception as e:
                        logger.error(f"Error updating status: {e}")

            def sync_now(app_self, _):
                """Trigger a manual sync."""
                if app_self.sync_engine:
                    app_self.title = "🔄"
                    app_self.menu["Status: Ready"].title = "Status: Syncing..."

                    # Run sync in background thread
                    def do_sync():
                        try:
                            app_self.sync_engine.scan_and_index()
                            app_self.sync_engine.queue_pending_uploads()
                            rumps.notification(
                                title="CrateCloud",
                                subtitle="Sync complete",
                                message="Your library is up to date.",
                            )
                        except Exception as e:
                            logger.error(f"Sync failed: {e}")
                            rumps.notification(
                                title="CrateCloud",
                                subtitle="Sync failed",
                                message=str(e),
                            )

                    threading.Thread(target=do_sync, daemon=True).start()
                else:
                    rumps.notification(
                        title="CrateCloud",
                        subtitle="Not configured",
                        message="Please configure CrateCloud first.",
                    )

            def open_full_app(app_self, _):
                """Open the full CrateCloud window."""
                import subprocess
                try:
                    # Try to open the full UI
                    subprocess.Popen(["python", "-m", "cratecloud", "ui", "--mode", "full"])
                except Exception as e:
                    logger.error(f"Failed to open full app: {e}")
                    rumps.notification(
                        title="CrateCloud",
                        subtitle="Error",
                        message="Could not open full application.",
                    )

            def open_preferences(app_self, _):
                """Open preferences."""
                # For now, just show a notification
                rumps.notification(
                    title="CrateCloud",
                    subtitle="Preferences",
                    message="Preferences will be available in a future update.",
                )

            def quit_app(app_self, _):
                """Quit the application."""
                if app_self.sync_engine:
                    app_self.sync_engine.close()
                rumps.quit_application()

        self._app = CrateCloudMenuBar(self.sync_engine, self.config)
        return self._app

    def run(self):
        """Run the menu bar application."""
        if not check_rumps_available():
            logger.error("rumps not available. This app requires macOS.")
            print("Error: Menu bar app requires macOS and rumps package.")
            print("Install with: pip install 'cratecloud[ui]'")
            return

        app = self._create_app()
        logger.info("Starting CrateCloud menu bar app...")
        app.run()

    def stop(self):
        """Stop the menu bar application."""
        if self._app:
            try:
                import rumps
                rumps.quit_application()
            except Exception:
                pass


def run_menubar_app(sync_engine=None, config=None):
    """
    Convenience function to run the menu bar app.

    Args:
        sync_engine: Optional SyncEngine instance.
        config: Optional configuration.
    """
    app = MenuBarApp(sync_engine=sync_engine, config=config)
    app.run()


if __name__ == "__main__":
    run_menubar_app()
