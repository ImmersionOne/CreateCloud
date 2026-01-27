"""AWS S3 integration for file storage."""

import hashlib
import logging
import mimetypes
from pathlib import Path
from typing import BinaryIO, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from cratecloud.core.models import Track

logger = logging.getLogger(__name__)

# Default bucket configuration
DEFAULT_BUCKET_PREFIX = "cratecloud"
DEFAULT_REGION = "us-east-1"


class S3Client:
    """Client for AWS S3 operations."""

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        region: str = DEFAULT_REGION,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
    ):
        """
        Initialize the S3 client.

        Args:
            bucket_name: S3 bucket name.
            region: AWS region.
            aws_access_key_id: AWS access key (uses env/config if not provided).
            aws_secret_access_key: AWS secret key (uses env/config if not provided).
        """
        self.bucket_name = bucket_name
        self.region = region

        # Configure boto3 client
        config = Config(
            region_name=region,
            retries={"max_attempts": 3, "mode": "standard"},
        )

        client_kwargs = {"config": config}
        if aws_access_key_id and aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        self._s3 = boto3.client("s3", **client_kwargs)
        self._s3_resource = boto3.resource("s3", **client_kwargs)

    def set_bucket(self, bucket_name: str):
        """Set the bucket name."""
        self.bucket_name = bucket_name

    def bucket_exists(self) -> bool:
        """Check if the configured bucket exists."""
        if not self.bucket_name:
            return False

        try:
            self._s3.head_bucket(Bucket=self.bucket_name)
            return True
        except ClientError:
            return False

    def create_bucket(self, bucket_name: Optional[str] = None) -> str:
        """
        Create a new S3 bucket.

        Args:
            bucket_name: Bucket name to create.

        Returns:
            The created bucket name.
        """
        bucket_name = bucket_name or self.bucket_name
        if not bucket_name:
            raise ValueError("Bucket name is required")

        try:
            if self.region == "us-east-1":
                self._s3.create_bucket(Bucket=bucket_name)
            else:
                self._s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )

            # Enable versioning for data protection
            self._s3.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )

            # Enable server-side encryption
            self._s3.put_bucket_encryption(
                Bucket=bucket_name,
                ServerSideEncryptionConfiguration={
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "AES256"
                            }
                        }
                    ]
                },
            )

            logger.info(f"Created bucket: {bucket_name}")
            self.bucket_name = bucket_name
            return bucket_name

        except ClientError as e:
            logger.error(f"Failed to create bucket: {e}")
            raise

    def _generate_s3_key(self, user_id: str, track: Track) -> str:
        """
        Generate an S3 key for a track.

        Format: users/{user_id}/tracks/{file_hash[:2]}/{file_hash}/{filename}
        """
        filename = track.file_path.name
        file_hash = track.file_hash

        # Use first 2 chars of hash as prefix for better S3 performance
        return f"users/{user_id}/tracks/{file_hash[:2]}/{file_hash}/{filename}"

    def upload_track(
        self,
        track: Track,
        user_id: str,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """
        Upload a track to S3.

        Args:
            track: Track to upload.
            user_id: User ID for organizing storage.
            progress_callback: Optional callback(bytes_transferred) for progress.

        Returns:
            The S3 key of the uploaded file.
        """
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        s3_key = self._generate_s3_key(user_id, track)

        # Determine content type
        content_type, _ = mimetypes.guess_type(str(track.file_path))
        content_type = content_type or "application/octet-stream"

        # Prepare metadata
        metadata = {
            "file-hash": track.file_hash,
            "original-path": str(track.file_path),
        }

        if track.title:
            metadata["title"] = track.title[:256]  # S3 metadata limit
        if track.artist:
            metadata["artist"] = track.artist[:256]
        if track.bpm:
            metadata["bpm"] = str(track.bpm)
        if track.key:
            metadata["key"] = track.key

        # Upload with progress callback
        extra_args = {
            "ContentType": content_type,
            "Metadata": metadata,
        }

        try:
            if progress_callback:
                self._s3.upload_file(
                    str(track.file_path),
                    self.bucket_name,
                    s3_key,
                    ExtraArgs=extra_args,
                    Callback=progress_callback,
                )
            else:
                self._s3.upload_file(
                    str(track.file_path),
                    self.bucket_name,
                    s3_key,
                    ExtraArgs=extra_args,
                )

            logger.info(f"Uploaded {track.file_path.name} to s3://{self.bucket_name}/{s3_key}")
            return s3_key

        except ClientError as e:
            logger.error(f"Upload failed: {e}")
            raise

    def upload_file(
        self,
        file_path: Path,
        s3_key: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        Upload a generic file to S3.

        Args:
            file_path: Local file path.
            s3_key: S3 key to upload to.
            content_type: MIME type.
            metadata: Optional metadata dict.

        Returns:
            The S3 key.
        """
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(file_path))
            content_type = content_type or "application/octet-stream"

        extra_args = {"ContentType": content_type}
        if metadata:
            extra_args["Metadata"] = metadata

        self._s3.upload_file(str(file_path), self.bucket_name, s3_key, ExtraArgs=extra_args)
        return s3_key

    def download_track(
        self,
        s3_key: str,
        destination: Path,
        progress_callback: Optional[callable] = None,
    ) -> Path:
        """
        Download a track from S3.

        Args:
            s3_key: S3 key of the file.
            destination: Local destination path.
            progress_callback: Optional callback(bytes_transferred) for progress.

        Returns:
            The local file path.
        """
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        # Create parent directories
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            if progress_callback:
                self._s3.download_file(
                    self.bucket_name,
                    s3_key,
                    str(destination),
                    Callback=progress_callback,
                )
            else:
                self._s3.download_file(self.bucket_name, s3_key, str(destination))

            logger.info(f"Downloaded s3://{self.bucket_name}/{s3_key} to {destination}")
            return destination

        except ClientError as e:
            logger.error(f"Download failed: {e}")
            raise

    def delete_track(self, s3_key: str):
        """Delete a track from S3."""
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        try:
            self._s3.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Deleted s3://{self.bucket_name}/{s3_key}")
        except ClientError as e:
            logger.error(f"Delete failed: {e}")
            raise

    def file_exists(self, s3_key: str) -> bool:
        """Check if a file exists in S3."""
        if not self.bucket_name:
            return False

        try:
            self._s3.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError:
            return False

    def get_presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """
        Generate a presigned URL for downloading a file.

        Args:
            s3_key: S3 key of the file.
            expires_in: URL expiration time in seconds.

        Returns:
            Presigned URL.
        """
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    def get_presigned_upload_url(
        self,
        s3_key: str,
        content_type: str,
        expires_in: int = 3600,
    ) -> dict:
        """
        Generate a presigned URL for uploading a file directly.

        Args:
            s3_key: S3 key for the upload.
            content_type: MIME type of the file.
            expires_in: URL expiration time in seconds.

        Returns:
            Dict with 'url' and 'fields' for the upload.
        """
        if not self.bucket_name:
            raise ValueError("Bucket name not configured")

        return self._s3.generate_presigned_post(
            self.bucket_name,
            s3_key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, 500 * 1024 * 1024],  # 500MB max
            ],
            ExpiresIn=expires_in,
        )

    def list_user_tracks(self, user_id: str) -> list[dict]:
        """
        List all tracks for a user.

        Args:
            user_id: User ID.

        Returns:
            List of track info dicts.
        """
        if not self.bucket_name:
            return []

        prefix = f"users/{user_id}/tracks/"
        tracks = []

        try:
            paginator = self._s3.get_paginator("list_objects_v2")

            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get("Contents", []):
                    tracks.append({
                        "s3_key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"],
                    })

        except ClientError as e:
            logger.error(f"Failed to list tracks: {e}")

        return tracks

    def get_storage_used(self, user_id: str) -> int:
        """
        Get total storage used by a user in bytes.

        Args:
            user_id: User ID.

        Returns:
            Total bytes used.
        """
        tracks = self.list_user_tracks(user_id)
        return sum(t["size"] for t in tracks)
