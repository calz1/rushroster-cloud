"""Object storage service for photos and file uploads.

This module provides a unified interface for object storage operations
across different cloud providers (S3, GCS, Azure Blob Storage) and local filesystem.
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
from uuid import UUID
import os
from pathlib import Path
import shutil


class ObjectStorageService:
    """
    Service for managing object storage operations.

    Supports multiple backends:
    - AWS S3
    - Google Cloud Storage (via boto3 compatibility)
    - Azure Blob Storage (via boto3 compatibility)
    """

    def __init__(
        self,
        provider: str = "s3",
        bucket_name: str = "",
        region: str = "us-east-1",
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        endpoint_url: Optional[str] = None
    ):
        """
        Initialize object storage service.

        Args:
            provider: Storage provider ('s3', 'gcs', 'azure')
            bucket_name: Name of the storage bucket
            region: Region for the bucket
            access_key: Access key ID (or None to use environment)
            secret_key: Secret access key (or None to use environment)
            endpoint_url: Custom endpoint URL (for MinIO, LocalStack, etc.)
        """
        self.provider = provider
        self.bucket_name = bucket_name
        self.region = region

        # Initialize boto3 client
        self.s3_client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint_url
        )

    def generate_photo_key(self, device_id: UUID, event_id: UUID, extension: str = "jpg") -> str:
        """
        Generate a unique storage key for a photo.

        Format: photos/{device_id}/{year}/{month}/{event_id}.{extension}

        Args:
            device_id: UUID of the device
            event_id: UUID of the event
            extension: File extension (default: jpg)

        Returns:
            Storage key path
        """
        now = datetime.now()
        return f"photos/{device_id}/{now.year}/{now.month:02d}/{event_id}.{extension}"

    def generate_presigned_upload_url(
        self,
        key: str,
        expires_in: int = 3600,
        content_type: str = "image/jpeg"
    ) -> str:
        """
        Generate a pre-signed URL for uploading a file.

        Args:
            key: Storage key for the file
            expires_in: URL expiration time in seconds (default: 1 hour)
            content_type: MIME type of the file

        Returns:
            Pre-signed upload URL

        Raises:
            Exception: If URL generation fails
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": content_type
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate presigned URL: {str(e)}")

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600
    ) -> str:
        """
        Generate a pre-signed URL for downloading a file.

        Args:
            key: Storage key for the file
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Pre-signed download URL

        Raises:
            Exception: If URL generation fails
        """
        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate presigned URL: {str(e)}")

    def upload_file(
        self,
        file_path: str,
        key: str,
        content_type: str = "image/jpeg",
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Upload a file directly to object storage.

        Args:
            file_path: Local path to the file
            key: Storage key for the file
            content_type: MIME type of the file
            metadata: Optional metadata to attach to the file

        Returns:
            Public URL of the uploaded file

        Raises:
            Exception: If upload fails
        """
        try:
            extra_args = {
                "ContentType": content_type
            }
            if metadata:
                extra_args["Metadata"] = metadata

            self.s3_client.upload_file(
                file_path,
                self.bucket_name,
                key,
                ExtraArgs=extra_args
            )

            # Return the public URL (adjust based on your bucket configuration)
            return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"

        except ClientError as e:
            raise Exception(f"Failed to upload file: {str(e)}")

    def delete_file(self, key: str) -> bool:
        """
        Delete a file from object storage.

        Args:
            key: Storage key for the file

        Returns:
            True if deletion successful

        Raises:
            Exception: If deletion fails
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return True
        except ClientError as e:
            raise Exception(f"Failed to delete file: {str(e)}")

    def file_exists(self, key: str) -> bool:
        """
        Check if a file exists in object storage.

        Args:
            key: Storage key for the file

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return True
        except ClientError:
            return False

    def get_file_metadata(self, key: str) -> Dict[str, Any]:
        """
        Get metadata for a file in object storage.

        Args:
            key: Storage key for the file

        Returns:
            Dictionary containing file metadata

        Raises:
            Exception: If file not found or operation fails
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return {
                "content_type": response.get("ContentType"),
                "content_length": response.get("ContentLength"),
                "last_modified": response.get("LastModified"),
                "metadata": response.get("Metadata", {})
            }
        except ClientError as e:
            raise Exception(f"Failed to get file metadata: {str(e)}")

    def list_files(self, prefix: str = "", max_keys: int = 1000) -> list:
        """
        List files in object storage with a given prefix.

        Args:
            prefix: Key prefix to filter by
            max_keys: Maximum number of keys to return

        Returns:
            List of file keys
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )

            if "Contents" not in response:
                return []

            return [obj["Key"] for obj in response["Contents"]]

        except ClientError as e:
            raise Exception(f"Failed to list files: {str(e)}")

    def get_storage_url(self, key: str) -> str:
        """
        Get the full storage URL for a key.

        This returns a permanent URL (not pre-signed). The file must be
        publicly accessible or the application must use pre-signed URLs
        when serving photos.

        Args:
            key: Storage key for the file

        Returns:
            Full URL to the file
        """
        if self.provider == "s3":
            return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"
        elif self.provider == "gcs":
            return f"https://storage.googleapis.com/{self.bucket_name}/{key}"
        elif self.provider == "azure":
            # Azure Blob Storage URL format
            account_name = os.getenv("AZURE_STORAGE_ACCOUNT", "")
            return f"https://{account_name}.blob.core.windows.net/{self.bucket_name}/{key}"
        else:
            return f"https://{self.bucket_name}/{key}"


class LocalStorageService:
    """
    Local filesystem storage service.

    Provides the same interface as ObjectStorageService but stores files
    on the local filesystem instead of cloud storage. Useful for development
    and self-hosted deployments.
    """

    def __init__(self, base_path: str = "./data/photos"):
        """
        Initialize local storage service.

        Args:
            base_path: Base directory path for storing files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def generate_photo_key(self, device_id: UUID, event_id: UUID, extension: str = "jpg") -> str:
        """
        Generate a unique storage key for a photo.

        Format: photos/{device_id}/{year}/{month}/{event_id}.{extension}

        Args:
            device_id: UUID of the device
            event_id: UUID of the event
            extension: File extension (default: jpg)

        Returns:
            Storage key path
        """
        now = datetime.now()
        return f"photos/{device_id}/{now.year}/{now.month:02d}/{event_id}.{extension}"

    def _get_file_path(self, key: str) -> Path:
        """Get absolute file path for a storage key."""
        return self.base_path / key

    def generate_presigned_upload_url(
        self,
        key: str,
        expires_in: int = 3600,
        content_type: str = "image/jpeg"
    ) -> str:
        """
        Generate a URL for uploading a file.

        For local storage, we return a local API endpoint URL that will handle
        the upload and save to the filesystem.

        Args:
            key: Storage key for the file
            expires_in: URL expiration time in seconds (default: 1 hour)
            content_type: MIME type of the file

        Returns:
            Upload URL (local API endpoint)
        """
        # Ensure directory exists
        file_path = self._get_file_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # For local storage, return the local file path as a pseudo-URL
        # In production, this would be an API endpoint that handles the upload
        return f"/api/storage/upload/{key}"

    def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 3600
    ) -> str:
        """
        Generate a URL for downloading a file.

        Args:
            key: Storage key for the file
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Download URL (local API endpoint)
        """
        return f"/api/storage/download/{key}"

    def upload_file(
        self,
        file_path: str,
        key: str,
        content_type: str = "image/jpeg",
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Upload a file to local storage.

        Args:
            file_path: Local path to the source file
            key: Storage key for the destination
            content_type: MIME type of the file
            metadata: Optional metadata (stored as JSON sidecar file)

        Returns:
            URL to access the file
        """
        dest_path = self._get_file_path(key)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file
        shutil.copy2(file_path, dest_path)

        # Store metadata if provided
        if metadata:
            import json
            metadata_path = dest_path.with_suffix(dest_path.suffix + ".meta")
            with open(metadata_path, 'w') as f:
                json.dump({
                    "content_type": content_type,
                    **metadata
                }, f)

        return self.get_storage_url(key)

    def save_file_content(self, key: str, content: bytes) -> str:
        """
        Save file content directly to storage.

        Args:
            key: Storage key for the file
            content: Binary content to save

        Returns:
            URL to access the file
        """
        file_path = self._get_file_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'wb') as f:
            f.write(content)

        return self.get_storage_url(key)

    def delete_file(self, key: str) -> bool:
        """
        Delete a file from local storage.

        Args:
            key: Storage key for the file

        Returns:
            True if deletion successful
        """
        file_path = self._get_file_path(key)

        if file_path.exists():
            file_path.unlink()

            # Also delete metadata file if it exists
            metadata_path = file_path.with_suffix(file_path.suffix + ".meta")
            if metadata_path.exists():
                metadata_path.unlink()

            return True

        return False

    def file_exists(self, key: str) -> bool:
        """
        Check if a file exists in local storage.

        Args:
            key: Storage key for the file

        Returns:
            True if file exists, False otherwise
        """
        return self._get_file_path(key).exists()

    def get_file_metadata(self, key: str) -> Dict[str, Any]:
        """
        Get metadata for a file in local storage.

        Args:
            key: Storage key for the file

        Returns:
            Dictionary containing file metadata
        """
        file_path = self._get_file_path(key)

        if not file_path.exists():
            raise Exception(f"File not found: {key}")

        stat = file_path.stat()
        metadata = {
            "content_length": stat.st_size,
            "last_modified": datetime.fromtimestamp(stat.st_mtime),
            "metadata": {}
        }

        # Load metadata from sidecar file if it exists
        metadata_path = file_path.with_suffix(file_path.suffix + ".meta")
        if metadata_path.exists():
            import json
            with open(metadata_path, 'r') as f:
                stored_meta = json.load(f)
                metadata["content_type"] = stored_meta.get("content_type", "application/octet-stream")
                metadata["metadata"] = {k: v for k, v in stored_meta.items() if k != "content_type"}

        return metadata

    def list_files(self, prefix: str = "", max_keys: int = 1000) -> list:
        """
        List files in local storage with a given prefix.

        Args:
            prefix: Key prefix to filter by
            max_keys: Maximum number of keys to return

        Returns:
            List of file keys
        """
        search_path = self.base_path / prefix if prefix else self.base_path

        if not search_path.exists():
            return []

        files = []
        for file_path in search_path.rglob("*"):
            if file_path.is_file() and not file_path.suffix == ".meta":
                # Get relative path from base_path
                relative = file_path.relative_to(self.base_path)
                files.append(str(relative))

                if len(files) >= max_keys:
                    break

        return sorted(files)

    def get_storage_url(self, key: str) -> str:
        """
        Get the URL for accessing a file.

        For local storage, this returns an API endpoint URL.

        Args:
            key: Storage key for the file

        Returns:
            URL to access the file
        """
        return f"/api/storage/files/{key}"
