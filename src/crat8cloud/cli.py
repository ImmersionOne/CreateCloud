"""Command-line interface for Crat8Cloud."""

import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from crat8cloud import __version__
from crat8cloud.config import ConfigManager, CredentialsManager, get_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# CLI app
app = typer.Typer(
    name="crat8cloud",
    help="Crat8Cloud - Cloud backup and sharing platform for DJs",
    add_completion=False,
)

console = Console()


class UIMode(str, Enum):
    """UI mode options."""

    MENUBAR = "menubar"
    FULL = "full"


def version_callback(value: bool):
    """Print version and exit."""
    if value:
        console.print(f"Crat8Cloud v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
):
    """Crat8Cloud - Cloud backup and sharing platform for DJs."""
    pass


@app.command()
def status():
    """Show current sync status."""
    from crat8cloud.core.sync import SyncEngine

    config = get_config()

    engine = SyncEngine(
        music_paths=config.music_paths_as_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    try:
        state = engine.get_sync_state()

        table = Table(title="Crat8Cloud Status")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Tracks", str(state.total_tracks))
        table.add_row("Synced", str(state.synced_tracks))
        table.add_row("Pending", str(state.pending_tracks))
        table.add_row("Errors", str(state.error_tracks))

        # Storage
        total_gb = state.total_size_bytes / (1024 ** 3)
        synced_gb = state.synced_size_bytes / (1024 ** 3)
        table.add_row("Total Size", f"{total_gb:.2f} GB")
        table.add_row("Synced Size", f"{synced_gb:.2f} GB")

        # Sync percentage
        table.add_row("Sync Progress", f"{state.sync_percentage:.1f}%")

        if state.last_sync:
            table.add_row("Last Sync", state.last_sync.strftime("%Y-%m-%d %H:%M"))
        else:
            table.add_row("Last Sync", "Never")

        console.print(table)

    finally:
        engine.close()


@app.command()
def scan(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to scan (defaults to configured music paths).",
    ),
):
    """Scan and index your music library."""
    from crat8cloud.core.sync import SyncEngine

    config = get_config()

    music_paths = [path] if path else config.music_paths_as_paths

    engine = SyncEngine(
        music_paths=music_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning library...", total=None)

            def update_progress(current, total, file_path):
                progress.update(task, total=total, completed=current, description=f"Scanning: {Path(file_path).name[:40]}")

            engine.scan_and_index(progress_callback=update_progress)

        state = engine.get_sync_state()
        console.print(f"\n[green]Scan complete![/green] Found {state.total_tracks} tracks.")

    finally:
        engine.close()


@app.command()
def backup(
    path: Optional[Path] = typer.Option(
        None,
        "--path",
        "-p",
        help="Path to backup (defaults to configured music paths).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be uploaded without actually uploading.",
    ),
):
    """Backup music to the cloud."""
    from crat8cloud.core.models import SyncStatus
    from crat8cloud.core.sync import SyncEngine

    config = get_config()

    if not config.aws.bucket_name:
        console.print("[red]Error:[/red] AWS not configured. Run 'crat8cloud config' first.")
        raise typer.Exit(1)

    music_paths = [path] if path else config.music_paths_as_paths

    engine = SyncEngine(
        music_paths=music_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    try:
        # First scan
        console.print("Scanning library...")
        engine.scan_and_index()

        # Get pending tracks
        pending = engine.db.get_tracks_by_status(SyncStatus.PENDING)
        modified = engine.db.get_tracks_by_status(SyncStatus.MODIFIED)
        to_upload = pending + modified

        if not to_upload:
            console.print("[green]Everything is already synced![/green]")
            return

        console.print(f"\nFound {len(to_upload)} tracks to upload:")

        if dry_run:
            table = Table()
            table.add_column("Track", style="cyan")
            table.add_column("Size", style="green")
            table.add_column("Status", style="yellow")

            total_size = 0
            for track in to_upload[:20]:  # Show first 20
                size_mb = track.file_size / (1024 * 1024)
                total_size += track.file_size
                table.add_row(
                    track.title or track.file_path.name,
                    f"{size_mb:.1f} MB",
                    track.sync_status.value,
                )

            if len(to_upload) > 20:
                table.add_row("...", "...", "...")
                table.add_row(f"({len(to_upload) - 20} more)", "", "")

            console.print(table)
            console.print(f"\nTotal: {total_size / (1024**3):.2f} GB")
            console.print("\n[yellow]Dry run - no files uploaded.[/yellow]")

        else:
            # TODO: Actual upload implementation
            console.print("[yellow]Upload functionality requires AWS configuration.[/yellow]")
            console.print("Run 'crat8cloud config' to set up your AWS credentials.")

    finally:
        engine.close()


@app.command()
def watch():
    """Watch for file changes and sync automatically."""
    from crat8cloud.core.sync import SyncEngine
    from crat8cloud.core.watcher import FileChange

    config = get_config()

    console.print("[cyan]Starting Crat8Cloud file watcher...[/cyan]")
    console.print(f"Watching: {', '.join(str(p) for p in config.music_paths_as_paths)}")
    console.print("Press Ctrl+C to stop.\n")

    engine = SyncEngine(
        music_paths=config.music_paths_as_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    def on_change(change: FileChange):
        console.print(f"[yellow]{change.change_type.value}:[/yellow] {change.file_path.name}")

    try:
        engine.watcher = engine.watcher or None
        from crat8cloud.core.watcher import MusicWatcher
        watcher = MusicWatcher(
            music_paths=config.music_paths_as_paths,
            serato_path=config.serato_path_as_path,
            on_change=on_change,
        )
        watcher.start()

        # Keep running until interrupted
        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[cyan]Stopping watcher...[/cyan]")
    finally:
        engine.close()


@app.command(name="config")
def configure(
    show: bool = typer.Option(
        False,
        "--show",
        "-s",
        help="Show current configuration.",
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Reset configuration to defaults.",
    ),
):
    """Configure Crat8Cloud settings."""
    manager = ConfigManager()

    if show:
        config = manager.config
        table = Table(title="Crat8Cloud Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Music Paths", "\n".join(config.music_paths))
        table.add_row("Serato Path", config.serato_path)
        table.add_row("Config Directory", config.config_dir)
        table.add_row("Auto Backup", str(config.sync.auto_backup))
        table.add_row("Backup Schedule", config.sync.backup_schedule)
        table.add_row("AWS Region", config.aws.region)
        table.add_row("AWS Bucket", config.aws.bucket_name or "Not configured")

        console.print(table)
        return

    if reset:
        if typer.confirm("Are you sure you want to reset configuration to defaults?"):
            manager.reset()
            console.print("[green]Configuration reset to defaults.[/green]")
        return

    # Interactive configuration
    console.print("[cyan]Crat8Cloud Configuration[/cyan]\n")

    config = manager.config

    # Music paths
    current_paths = ", ".join(config.music_paths)
    new_paths = typer.prompt("Music paths (comma-separated)", default=current_paths)
    music_paths = [p.strip() for p in new_paths.split(",")]

    # Auto backup
    auto_backup = typer.confirm("Enable auto backup?", default=config.sync.auto_backup)

    # AWS configuration
    console.print("\n[cyan]AWS Configuration[/cyan]")
    console.print("You'll need an AWS account with S3 and Cognito set up.")

    aws_region = typer.prompt("AWS Region", default=config.aws.region)
    aws_bucket = typer.prompt("S3 Bucket Name", default=config.aws.bucket_name or "")

    # Save configuration
    manager.update(
        music_paths=music_paths,
        sync={"auto_backup": auto_backup},
        aws={"region": aws_region, "bucket_name": aws_bucket if aws_bucket else None},
    )

    console.print("\n[green]Configuration saved![/green]")


@app.command()
def login(
    email: str = typer.Option(..., "--email", "-e", prompt=True, help="Your email address."),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        help="Your password.",
    ),
):
    """Log in to Crat8Cloud."""
    config = get_config()

    if not config.aws.user_pool_id or not config.aws.client_id:
        console.print("[red]Error:[/red] AWS Cognito not configured.")
        console.print("Contact your administrator for the user pool details.")
        raise typer.Exit(1)

    from crat8cloud.cloud.auth import AuthClient, AuthError

    try:
        auth = AuthClient(
            user_pool_id=config.aws.user_pool_id,
            client_id=config.aws.client_id,
            region=config.aws.region,
        )

        with console.status("Logging in..."):
            user = auth.sign_in(email, password)

        # Store credentials
        creds_manager = CredentialsManager()
        creds_manager.store_credentials(
            access_token=auth.access_token,
            refresh_token=auth._refresh_token,
            user_id=user.user_id,
        )

        # Update config with user info
        config_manager = ConfigManager()
        config_manager.update(user_id=user.user_id, user_email=user.email)

        console.print(f"\n[green]Welcome, {user.display_name}![/green]")

    except AuthError as e:
        console.print(f"[red]Login failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def logout():
    """Log out of Crat8Cloud."""
    creds_manager = CredentialsManager()
    creds_manager.clear_credentials()

    config_manager = ConfigManager()
    config_manager.update(user_id=None, user_email=None)

    console.print("[green]Logged out successfully.[/green]")


@app.command()
def ui(
    mode: UIMode = typer.Option(
        UIMode.FULL,
        "--mode",
        "-m",
        help="UI mode: 'menubar' for menu bar app, 'full' for window app.",
    ),
):
    """Launch the Crat8Cloud UI."""
    from crat8cloud.core.sync import SyncEngine

    config = get_config()

    engine = SyncEngine(
        music_paths=config.music_paths_as_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    try:
        if mode == UIMode.MENUBAR:
            from crat8cloud.ui.menubar import run_menubar_app
            console.print("[cyan]Starting Crat8Cloud menu bar app...[/cyan]")
            run_menubar_app(sync_engine=engine, config=config)
        else:
            from crat8cloud.ui.window import run_window_app
            console.print("[cyan]Starting Crat8Cloud...[/cyan]")
            sys.exit(run_window_app(sync_engine=engine, config=config))

    finally:
        engine.close()


@app.command()
def tracks(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of tracks to show."),
    status_filter: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: pending, synced, modified, error",
    ),
):
    """List tracks in your library."""
    from crat8cloud.core.models import SyncStatus
    from crat8cloud.core.sync import SyncEngine

    config = get_config()

    engine = SyncEngine(
        music_paths=config.music_paths_as_paths,
        serato_path=config.serato_path_as_path,
        db_path=config.db_path,
    )

    try:
        if status_filter:
            try:
                status = SyncStatus(status_filter)
                tracks = engine.db.get_tracks_by_status(status)
            except ValueError:
                console.print(f"[red]Invalid status:[/red] {status_filter}")
                console.print("Valid options: pending, synced, modified, error")
                raise typer.Exit(1)
        else:
            tracks = engine.db.get_all_tracks()

        if not tracks:
            console.print("No tracks found. Run 'crat8cloud scan' first.")
            return

        table = Table(title=f"Tracks ({len(tracks)} total)")
        table.add_column("Title", style="cyan", max_width=30)
        table.add_column("Artist", style="green", max_width=20)
        table.add_column("BPM", style="yellow", width=6)
        table.add_column("Key", width=4)
        table.add_column("Status", style="magenta", width=10)
        table.add_column("Size", width=10)

        for track in tracks[:limit]:
            size_mb = track.file_size / (1024 * 1024)
            table.add_row(
                track.title or track.file_path.stem[:30],
                track.artist or "",
                f"{track.bpm:.0f}" if track.bpm else "",
                track.key or "",
                track.sync_status.value,
                f"{size_mb:.1f} MB",
            )

        if len(tracks) > limit:
            table.add_row("...", "...", "...", "...", "...", "...")
            console.print(f"\nShowing {limit} of {len(tracks)} tracks. Use --limit to see more.")

        console.print(table)

    finally:
        engine.close()


@app.command()
def crates():
    """List Serato crates."""
    from crat8cloud.core.serato import SeratoParser

    config = get_config()
    parser = SeratoParser(
        serato_path=config.serato_path_as_path,
        music_paths=config.music_paths_as_paths,
    )

    if not parser.is_serato_installed():
        console.print("[yellow]Serato folder not found.[/yellow]")
        console.print(f"Expected location: {parser.serato_path}")
        return

    crates = parser.get_crates()

    if not crates:
        console.print("No crates found.")
        return

    table = Table(title=f"Serato Crates ({len(crates)})")
    table.add_column("Crate", style="cyan")
    table.add_column("Tracks", style="green")
    table.add_column("Parent", style="yellow")

    for crate in sorted(crates, key=lambda c: c.name):
        table.add_row(
            crate.name,
            str(len(crate.track_paths)),
            crate.parent_crate or "",
        )

    console.print(table)


if __name__ == "__main__":
    app()
