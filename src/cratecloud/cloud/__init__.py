"""Cloud integrations for CrateCloud."""

from cratecloud.cloud.s3 import S3Client
from cratecloud.cloud.auth import AuthClient

__all__ = ["S3Client", "AuthClient"]
