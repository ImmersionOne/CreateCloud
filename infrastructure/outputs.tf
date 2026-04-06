output "bucket_name" {
  description = "Name of the primary S3 storage bucket."
  value       = aws_s3_bucket.main.bucket
}

output "bucket_arn" {
  description = "ARN of the primary S3 storage bucket."
  value       = aws_s3_bucket.main.arn
}

output "bucket_region" {
  description = "AWS region the bucket was created in."
  value       = aws_s3_bucket.main.region
}

output "user_storage_policy_arn" {
  description = "ARN of the per-user storage IAM policy (attach to Cognito Identity Pool authenticated role)."
  value       = aws_iam_policy.user_storage.arn
}

output "dev_user_policy_arn" {
  description = "ARN of the dev IAM user policy (for local testing only)."
  value       = aws_iam_policy.dev_user.arn
}
