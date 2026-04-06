# ──────────────────────────────────────────────────────────────────────────────
# Primary storage bucket
#
# Key structure (enforced by application, not S3):
#   users/{user_id}/tracks/{hash[:2]}/{sha256_hash}/{filename}
#   users/{user_id}/serato/database_v2
#   users/{user_id}/serato/crates/{crate_name}.crate
#   users/{user_id}/metadata/library.json
#   shared/crews/{crew_id}/{owner_user_id}/{hash[:2]}/{hash}/{filename}
# ──────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "main" {
  # Bucket name includes account ID for global uniqueness.
  # Example: crat8cloud-dev-857812840516
  bucket = "crat8cloud-${var.environment}-${var.aws_account_id}"

  # Prevent accidental destruction in staging/prod.
  # Set to false in dev so `terraform destroy` works cleanly.
  lifecycle {
    prevent_destroy = false
  }
}

# ── Block all public access ───────────────────────────────────────────────────
resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

# ── Versioning ────────────────────────────────────────────────────────────────
# Keeps prior versions of every object so users can roll back to an earlier
# library state (e.g. recover accidentally overwritten cue points).
resource "aws_s3_bucket_versioning" "main" {
  bucket = aws_s3_bucket.main.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ── Server-side encryption (AES-256) ─────────────────────────────────────────
resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    # Enforce encryption on all new objects.
    bucket_key_enabled = true
  }
}

# ── Enforce TLS-only access ───────────────────────────────────────────────────
resource "aws_s3_bucket_policy" "enforce_tls" {
  bucket = aws_s3_bucket.main.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.main.arn,
          "${aws_s3_bucket.main.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })

  # Public access block must be applied before the bucket policy.
  depends_on = [aws_s3_bucket_public_access_block.main]
}

# ── Lifecycle rules ───────────────────────────────────────────────────────────
resource "aws_s3_bucket_lifecycle_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  # Tracks that haven't been accessed in a while move to Infrequent Access
  # (40% cheaper storage). Applies to the full library — a DJ's 2018 tracks
  # that are backed up but rarely restored are ideal candidates.
  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    filter {
      prefix = "users/"
    }

    transition {
      days          = var.ia_transition_days
      storage_class = "STANDARD_IA"
    }
  }

  # Old non-current versions expire after N days to control cost.
  # Current (latest) version is always retained.
  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.versioning_expiry_days
    }

    # Clean up incomplete multipart uploads (can accumulate silently).
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ── CORS (needed for presigned URL uploads from a web dashboard) ──────────────
resource "aws_s3_bucket_cors_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    # Restrict to your own origins in staging/prod.
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}
