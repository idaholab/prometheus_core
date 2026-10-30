# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Files resource for synchronous operations."""

from pathlib import Path
from typing import Optional
from ..models.file import FileMetadata
from .base import BaseResource


class FilesResource(BaseResource):
    """Handles operations related to file storage and retrieval."""

    def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file to storage.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name (defaults to filename)
            description: Optional file description

        Returns:
            File metadata

        Example:
            ```python
            file_meta = client.files.upload(
                Path("data.csv"),
                description="Experiment results"
            )
            ```
        """
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_name = name or file_path.name

        # Open and upload file
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            data = {}

            if description:
                data["description"] = description

            response = self._client._request(
                "POST", f"{self._base_path}/files", files=files, data=data
            )

        return self._parse_file_metadata(response.json())

    def upload_bytes(
        self, data: bytes, name: str, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload in-memory bytes to storage as one file, without a temporary file.

        Args:
            data: File content
            name: File name
            description: Optional file description

        Returns:
            File metadata
        """
        from ..utils.streaming import ChunkedUploader

        uploader = ChunkedUploader(self._client)
        if len(data) <= uploader.chunk_size:
            form = {"description": description} if description else {}
            response = self._client._request(
                "POST", f"{self._base_path}/files", files={"file": (name, data)}, data=form
            )
            return self._parse_file_metadata(response.json())

        chunks = [
            data[i : i + uploader.chunk_size] for i in range(0, len(data), uploader.chunk_size)
        ]
        upload_id = uploader._start_upload(name, len(data))
        try:
            for chunk_num, chunk_data in enumerate(chunks):
                uploader._upload_chunk(upload_id, chunk_num, chunk_data)
            return uploader._complete_upload(upload_id, name, description, len(chunks))
        except Exception:
            try:
                uploader._cancel_upload(upload_id)
            except Exception:
                pass
            raise

    def upload_chunked(
        self,
        file_path: Path,
        chunk_size: int = 5 * 1024 * 1024,  # 5MB default
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> FileMetadata:
        """Upload a large file in chunks.

        Args:
            file_path: Path to the file to upload
            chunk_size: Size of each chunk in bytes
            name: Optional custom name
            description: Optional file description

        Returns:
            File metadata

        Example:
            ```python
            # Upload large file in 10MB chunks
            file_meta = client.files.upload_chunked(
                Path("large_data.zip"),
                chunk_size=10 * 1024 * 1024
            )
            ```
        """
        from ..utils.streaming import ChunkedUploader

        uploader = ChunkedUploader(self._client, chunk_size)
        return uploader.upload(file_path, name, description)

    def get(self, file_id: int) -> FileMetadata:
        """Get file metadata by ID.

        Args:
            file_id: File identifier

        Returns:
            File metadata

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        # Files are retrieved via records endpoint (they're records with file attachments)
        response = self._client._request("GET", f"{self._base_path}/records/{file_id}")

        return self._parse_file_metadata(response.json())

    def download(self, file_id: int, output_path: Path) -> None:
        """Download a file to local storage.

        Args:
            file_id: File identifier (record ID from upload)
            output_path: Where to save the downloaded file

        Raises:
            ItemNotFoundError: If file doesn't exist

        Example:
            ```python
            client.files.download(123, Path("downloaded.csv"))
            ```
        """
        # Download using the files endpoint with record ID
        response = self._client._request("GET", f"{self._base_path}/files/{file_id}")

        # Write file content
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    def delete(self, file_id: int) -> None:
        """Delete a file.

        Args:
            file_id: File identifier

        Raises:
            ItemNotFoundError: If file doesn't exist
        """
        self._client._request("DELETE", f"{self._base_path}/files/{file_id}")

    def _parse_file_metadata(self, data: dict) -> FileMetadata:
        """Parse API response data into FileMetadata model.

        Args:
            data: Raw API response data

        Returns:
            Parsed FileMetadata object

        Note:
            DeepLynx API returns field names like 'name', 'fileType', 'uri'.
        """
        return FileMetadata(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            file_type=data.get("fileType"),
            size=data.get("fileSize"),
            uri=data.get("uri"),
            created_at=data.get("createdAt"),
            updated_at=data.get("lastUpdatedAt") or data.get("updatedAt"),
        )
