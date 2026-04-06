"""
Real S3 upload test — uploads 5-10 tracks from the actual Serato library
to the dev bucket. No mocks, no faking. Uses the same S3Client that the
backup command uses.

Run with:
  .venv312/bin/python s3_upload_test.py
"""

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

BUCKET = "crat8cloud-dev-857812840516"
REGION = "us-east-1"
USER_ID = "dev-test-user"
SERATO_PATH = Path.home() / "Music" / "_Serato_"
MUSIC_PATHS = [
    Path.home() / "Music" / "deemix Music",
    Path.home() / "Music" / "iTunes",
]
MUSIC_PATHS = [p for p in MUSIC_PATHS if p.exists()]
UPLOAD_LIMIT = 8

SEP = "─" * 68

def header(t): print(f"\n{SEP}\n  {t}\n{SEP}")
def ok(m):   print(f"  ✓  {m}")
def info(m): print(f"     {m}")
def fail(m): print(f"  ✗  {m}")

# ── 1. Parse a handful of real tracks ────────────────────────────────────────
header("1. Parsing tracks from real Serato library")

sys.path.insert(0, str(Path(__file__).parent / "src"))
from crat8cloud.core.serato import SeratoParser
from crat8cloud.core.models import SyncStatus

parser = SeratoParser(serato_path=SERATO_PATH, music_paths=MUSIC_PATHS)
all_files = parser.get_all_music_files()
ok(f"Found {len(all_files):,} music files")

# Pick a small sample: prefer mp3s under 10 MB so the test is quick
sample_files = []
for f in all_files:
    if f.suffix.lower() == ".mp3" and f.stat().st_size < 10 * 1024 * 1024:
        sample_files.append(f)
    if len(sample_files) >= UPLOAD_LIMIT:
        break

ok(f"Selected {len(sample_files)} tracks for upload (mp3, <10 MB each)")

tracks = []
for f in sample_files:
    try:
        t = parser.parse_track(f)
        tracks.append(t)
        info(f"{t.file_path.name[:55]:<55}  {t.file_size/1024/1024:.1f} MB")
    except Exception as e:
        fail(f"Parse failed: {f.name}: {e}")

# ── 2. Upload to real S3 ──────────────────────────────────────────────────────
header("2. Uploading to S3")
info(f"Bucket: {BUCKET}  |  Region: {REGION}  |  User prefix: users/{USER_ID}/")

from crat8cloud.cloud.s3 import S3Client

s3 = S3Client(bucket_name=BUCKET, region=REGION)

if not s3.bucket_exists():
    fail(f"Bucket '{BUCKET}' not found or not accessible. Check AWS credentials.")
    sys.exit(1)
ok(f"Bucket accessible: {BUCKET}")

uploaded = []
errors = []

for track in tracks:
    try:
        bytes_so_far = [0]
        def progress(n, _b=bytes_so_far):
            _b[0] += n

        s3_key = s3.upload_track(track, user_id=USER_ID, progress_callback=progress)
        uploaded.append((track, s3_key))
        size_mb = track.file_size / 1024 / 1024
        ok(f"Uploaded ({size_mb:.1f} MB)")
        info(f"  S3 key: {s3_key}")
    except Exception as e:
        fail(f"{track.file_path.name}: {e}")
        errors.append(track)

# ── 3. Verify via S3 list ─────────────────────────────────────────────────────
header("3. Verifying via S3 list")

listed = s3.list_user_tracks(USER_ID)
ok(f"S3 lists {len(listed)} objects under users/{USER_ID}/tracks/")

total_bytes = sum(o["size"] for o in listed)
info(f"Total stored: {total_bytes / 1024 / 1024:.1f} MB")

print()
info("S3 key structure (first 10):")
for obj in listed[:10]:
    info(f"  {obj['s3_key']}")
if len(listed) > 10:
    info(f"  ... and {len(listed)-10} more")

# ── 4. Round-trip integrity check ────────────────────────────────────────────
header("4. Round-trip integrity (re-list and cross-check hashes)")

uploaded_keys = {s3_key for _, s3_key in uploaded}
listed_keys   = {o["s3_key"] for o in listed}
found_in_list = uploaded_keys & listed_keys

ok(f"{len(found_in_list)}/{len(uploaded_keys)} uploaded keys confirmed in S3 list")
if uploaded_keys - listed_keys:
    fail(f"Missing from list: {uploaded_keys - listed_keys}")

# ── Summary ───────────────────────────────────────────────────────────────────
header("SUMMARY")
print(f"""
  Bucket:           {BUCKET}
  Tracks uploaded:  {len(uploaded)}/{len(tracks)}
  Errors:           {len(errors)}
  Total in bucket:  {len(listed)} objects  ({total_bytes/1024/1024:.1f} MB)
  S3 key format:    users/{{user_id}}/tracks/{{hash[:2]}}/{{sha256}}/{{filename}}
""")
print(SEP)
if errors:
    print("  Some uploads failed — check AWS credentials / bucket permissions.")
else:
    print("  All uploads successful. S3 pipeline is working end-to-end.")
print(SEP)
