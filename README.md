# CrateCloud

Cloud backup and sharing platform for DJs. Automatically backup your Serato library to the cloud and share tracks with your crew.

## Features

- **Automatic Backup**: Watch your music folder and automatically upload new tracks
- **Serato Integration**: Backup crates, cue points, loops, and all metadata
- **Crew Sharing**: Create invite-only groups to share original productions
- **Cross-Device Sync**: Access your library from any Mac
- **Simple & Full UI**: Menu bar app for quick status, full window for management

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/cratecloud.git
cd cratecloud

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[ui,dev]"
```

## Quick Start

```bash
# Run the CLI
cratecloud --help

# Start the menu bar app
cratecloud ui --mode menubar

# Start the full window app
cratecloud ui --mode full

# Manual backup
cratecloud backup --path ~/Music

# Check sync status
cratecloud status
```

## Configuration

CrateCloud stores configuration in `~/.cratecloud/config.json`:

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
cratecloud/
├── src/cratecloud/
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

- [x] Phase 1: Core backup functionality
- [ ] Phase 2: Restore & sync
- [ ] Phase 3: Crew sharing
- [ ] Phase 4: Web dashboard
- [ ] Phase 5: Mobile app

## License

MIT License - see LICENSE file for details.
