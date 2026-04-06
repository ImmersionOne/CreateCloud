# Crat8Cloud by DJ Roma

Cloud backup and sharing platform for DJs. Automatically backup your Serato library to the cloud and share tracks with your crew.

## Features

- **Automatic Backup**: Monitors your music folder and automatically upload new tracks
- **Serato Integration**: Backup crates, cue points, loops, and all metadata
- **Crew Sharing**: Create invite-only groups to share music with other DJs
- **Cross-Device Sync**: Access your library from any Mac
- **Simple & Full UI**: Menu bar app for quick status, full window for management

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/crat8cloud.git
cd crat8cloud

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[ui,dev]"
```

## Quick Start

```bash
# Run the CLI
crat8cloud --help

# Start the menu bar app
crat8cloud ui --mode menubar

# Start the full window app
crat8cloud ui --mode full

# Manual backup
crat8cloud backup --path ~/Music

# Check sync status
crat8cloud status
```

## Configuration

Crat8Cloud stores configuration in `~/.crat8cloud/config.json`:

```json
{
  "music_paths": ["~/Music"],
  "serato_path": "~/Music/_Serato_",
  "auto_backup": true,
  "backup_schedule": "daily",
  "upload_on_change": true
}
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   File Watcher  │────▶│  Sync Engine    │────▶│    AWS S3       │
│   (watchdog)    │     │                 │     │  (Music Files)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                               │
                               ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Serato Parser   │────▶│   Local DB      │────▶│  AWS DynamoDB   │
│ (serato-tools)  │     │   (SQLite)      │     │  (Metadata)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Project Structure

```
crat8cloud/
├── src/crat8cloud/
│   ├── core/           # Core business logic
│   │   ├── serato.py   # Serato metadata parsing
│   │   ├── watcher.py  # File system monitoring
│   │   ├── sync.py     # Sync engine
│   │   └── models.py   # Data models
│   ├── cloud/          # Cloud integrations
│   │   ├── s3.py       # AWS S3 operations
│   │   ├── dynamo.py   # DynamoDB operations
│   │   └── auth.py     # Cognito authentication
│   ├── ui/             # User interfaces
│   │   ├── menubar.py  # Menu bar app
│   │   └── window.py   # Full window app
│   ├── cli.py          # CLI commands
│   └── config.py       # Configuration management
├── tests/
├── pyproject.toml
└── README.md
```

## Development

```bash
# Run tests
pytest

# Run linter
ruff check src/

# Run type checker
mypy src/
```

## Roadmap

- [x] **Phase 1: Core backup** — upload pipeline, file watcher, Serato parser, SQLite sync engine, auto-backup scheduler
- [ ] **Phase 1.5: Zero-Config Onboarding** — auto-detect Serato installation, auto-discover music folders from the Serato database, guided 3-step first-run flow, no AWS config required from the user. Install → Sign up → You're backed up.
- [ ] **Phase 2: Restore, Sync & Gig Recovery** — `crat8cloud restore` command, cross-device sync, and **Gig Recovery Mode**: sign into a new machine, hit "Recover My Library", and your entire Serato library (tracks, crates, cue points, loops, beatgrids) downloads and reconstructs exactly as it was. Active crates download first so you can play within 30 minutes.
- [ ] **Phase 3: Backend API & Billing** — API Gateway + Lambda backend, Stripe subscription billing, per-user storage quotas, remove direct AWS credential requirement from the desktop app
- [ ] **Phase 4: Crew sharing** — invite-only groups, shared library browsing, presigned track access
- [ ] **Phase 5: Web dashboard** — account management, billing portal, library overview
- [ ] **Phase 6: Mobile app** — iOS/Android companion

## License

MIT License - see LICENSE file for details.
