# ──────────────────────────────────────────────────────────────────────────────
# IAM — per-user scoped access for the desktop app
#
# The desktop app uses Cognito Identity Pool credentials (not long-lived IAM
# keys). The policy below is attached to the Identity Pool's authenticated
# role. The ${cognito-identity.amazonaws.com:sub} variable is resolved by
# AWS at credential issuance time, so each user can only access their own
# prefix regardless of what user_id value they supply in code.
#
# For the dev environment (before Cognito is set up), a separate
# crat8cloud-dev-user policy is created so the IAM user configured via
# `aws configure` can run upload tests.
# ──────────────────────────────────────────────────────────────────────────────

# ── Cognito Identity Pool authenticated role policy ───────────────────────────
data "aws_iam_policy_document" "user_storage" {
  # Allow read/write only to the user's own prefix.
  statement {
    sid    = "UserOwnPrefixAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [
      "${aws_s3_bucket.main.arn}/users/$${cognito-identity.amazonaws.com:sub}/*",
    ]
  }

  # Allow listing only within the user's own prefix.
  statement {
    sid    = "UserOwnPrefixList"
    effect = "Allow"
    actions = ["s3:ListBucket"]
    resources = [aws_s3_bucket.main.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["users/$${cognito-identity.amazonaws.com:sub}/*"]
    }
  }

  # Allow downloading shared crew tracks (read-only).
  statement {
    sid    = "CrewSharedTracksRead"
    effect = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.main.arn}/shared/crews/*",
    ]
  }
}

resource "aws_iam_policy" "user_storage" {
  name        = "crat8cloud-${var.environment}-user-storage"
  description = "Per-user S3 access for Crat8Cloud desktop app via Cognito Identity Pool."
  policy      = data.aws_iam_policy_document.user_storage.json
}

# ── Dev IAM user policy (for local testing without Cognito) ──────────────────
# Attached to the IAM user created during `aws configure`.
# Grants full access to the dev bucket only — not to any other AWS resources.
data "aws_iam_policy_document" "dev_user" {
  statement {
    sid    = "DevBucketFullAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
      "s3:GetBucketVersioning",
      "s3:GetBucketLocation",
    ]
    resources = [
      aws_s3_bucket.main.arn,
      "${aws_s3_bucket.main.arn}/*",
    ]
  }
}

resource "aws_iam_policy" "dev_user" {
  name        = "crat8cloud-${var.environment}-dev-user"
  description = "Full access to the dev S3 bucket for local testing."
  policy      = data.aws_iam_policy_document.dev_user.json
}

# Attach to the dev IAM user (the user created for local testing).
resource "aws_iam_user_policy_attachment" "dev_user" {
  user       = "crat8cloud-dev"
  policy_arn = aws_iam_policy.dev_user.arn
}
