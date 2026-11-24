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

"""Streaming utilities for large file uploads."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid

if TYPE_CHECKING:
    from ..client import StorageClient
    from ..async_client import AsyncStorageClient

from ..models.file import FileMetadata


class ChunkedUploader:
    """Handles chunked file uploads for large files."""

    def __init__(self, client: "StorageClient", chunk_size: int = 5 * 1024 * 1024):
        """Initialize chunked uploader.

        Args:
            client: Storage client instance
            chunk_size: Size of each chunk in bytes (default 5MB)
        """
        self.client = client
        self.chunk_size = chunk_size

    def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file in chunks.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name
            description: Optional description

        Returns:
            File metadata

        Raises:
            ValueError: If file doesn't exist
        """
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_size = file_path.stat().st_size
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
        file_name = name or file_path.name

        # Start upload session
        upload_id = self._start_upload(file_name, file_size)

        # Upload chunks
        try:
            sent = 0
            with open(file_path, "rb") as f:
                for chunk_num in range(total_chunks):
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break
                    self._upload_chunk(upload_id, chunk_num, chunk_data)
                    sent += 1

            # Complete with the number of chunks actually sent. The server's own suggested
            # count (from the start response) can be lower, and completing with a lower count
            # answers 200 but stores only that many chunks.
            return self._complete_upload(upload_id, file_name, description, sent)

        except Exception as e:
            # Attempt to cancel upload on error
            try:
                self._cancel_upload(upload_id)
            except Exception:
                pass
            raise e

    def _start_upload(self, file_name: str, file_size: int) -> str:
        """Start a chunked upload session.

        Args:
            file_name: Name of the file
            file_size: Total file size in bytes

        Returns:
            Upload session ID
        """
        response = self.client._request(
            "POST",
            f"{self.client.files._base_path}/files/upload/start",
            json={
                "fileName": file_name,
                "fileSize": file_size,
                "chunkSize": self.chunk_size,
            },
        )

        data = response.json()
        upload_id = data.get("uploadId") if isinstance(data, dict) else None
        return str(upload_id or uuid.uuid4())

    def _upload_chunk(self, upload_id: str, chunk_num: int, chunk_data: bytes) -> None:
        """Upload a single chunk.

        Args:
            upload_id: Upload session ID
            chunk_num: Chunk number (0-indexed)
            chunk_data: Chunk data bytes
        """
        files = {"chunk": (f"chunk_{chunk_num}", chunk_data)}

        self.client._request(
            "POST",
            f"{self.client.files._base_path}/files/upload/chunk",
            files=files,
            data={
                "uploadId": upload_id,
                "chunkNumber": chunk_num,
            },
        )

    def _complete_upload(
        self, upload_id: str, file_name: str, description: Optional[str], total_chunks: int
    ) -> FileMetadata:
        """Complete the chunked upload.

        Args:
            upload_id: Upload session ID
            file_name: File name
            description: Optional description
            total_chunks: Total number of chunks

        Returns:
            File metadata
        """
        payload: Dict[str, Any] = {
            "uploadId": upload_id,
            "fileName": file_name,
            "totalChunks": total_chunks,
        }

        if description:
            # The server ignores a top-level ``description`` and invents its own; the caller's
            # travels in ``metadata``, whose Name, Description and Properties are all required.
            payload["metadata"] = {
                "Name": file_name,
                "Description": description,
                "Properties": {},
            }

        response = self.client._request(
            "POST", f"{self.client.files._base_path}/files/upload/complete", json=payload
        )

        return self.client.files._parse_file_metadata(response.json())

    def _cancel_upload(self, upload_id: str) -> None:
        """Cancel an upload session.

        Args:
            upload_id: Upload session ID
        """
        self.client._request("DELETE", f"{self.client.files._base_path}/files/upload/{upload_id}")


class AsyncChunkedUploader:
    """Async version of chunked file uploader."""

    def __init__(self, client: "AsyncStorageClient", chunk_size: int = 5 * 1024 * 1024):
        """Initialize async chunked uploader.

        Args:
            client: Async storage client instance
            chunk_size: Size of each chunk in bytes (default 5MB)
        """
        self.client = client
        self.chunk_size = chunk_size

    async def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file in chunks asynchronously.

        Args:
            file_path: Path to the file to upload
            name: Optional custom name
            description: Optional description

        Returns:
            File metadata

        Raises:
            ValueError: If file doesn't exist
        """
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_size = file_path.stat().st_size
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
        file_name = name or file_path.name

        # Start upload session
        upload_id = await self._start_upload(file_name, file_size)

        # Upload chunks
        try:
            sent = 0
            with open(file_path, "rb") as f:
                for chunk_num in range(total_chunks):
                    chunk_data = f.read(self.chunk_size)
                    if not chunk_data:
                        break
                    await self._upload_chunk(upload_id, chunk_num, chunk_data)
                    sent += 1

            # Complete with the number of chunks actually sent. The server's own suggested
            # count (from the start response) can be lower, and completing with a lower count
            # answers 200 but stores only that many chunks.
            return await self._complete_upload(upload_id, file_name, description, sent)

        except Exception as e:
            # Attempt to cancel upload on error
            try:
                await self._cancel_upload(upload_id)
            except Exception:
                pass
            raise e

    async def _start_upload(self, file_name: str, file_size: int) -> str:
        """Start a chunked upload session.

        Args:
            file_name: Name of the file
            file_size: Total file size in bytes

        Returns:
            Upload session ID
        """
        response = await self.client._request(
            "POST",
            f"{self.client.files._base_path}/files/upload/start",
            json={
                "fileName": file_name,
                "fileSize": file_size,
                "chunkSize": self.chunk_size,
            },
        )

        data = response.json()
        upload_id = data.get("uploadId") if isinstance(data, dict) else None
        return str(upload_id or uuid.uuid4())

    async def _upload_chunk(self, upload_id: str, chunk_num: int, chunk_data: bytes) -> None:
        """Upload a single chunk.

        Args:
            upload_id: Upload session ID
            chunk_num: Chunk number (0-indexed)
            chunk_data: Chunk data bytes
        """
        files = {"chunk": (f"chunk_{chunk_num}", chunk_data)}

        await self.client._request(
            "POST",
            f"{self.client.files._base_path}/files/upload/chunk",
            files=files,
            data={
                "uploadId": upload_id,
                "chunkNumber": chunk_num,
            },
        )

    async def _complete_upload(
        self, upload_id: str, file_name: str, description: Optional[str], total_chunks: int
    ) -> FileMetadata:
        """Complete the chunked upload.

        Args:
            upload_id: Upload session ID
            file_name: File name
            description: Optional description
            total_chunks: Total number of chunks

        Returns:
            File metadata
        """
        payload: Dict[str, Any] = {
            "uploadId": upload_id,
            "fileName": file_name,
            "totalChunks": total_chunks,
        }

        if description:
            # The server ignores a top-level ``description`` and invents its own; the caller's
            # travels in ``metadata``, whose Name, Description and Properties are all required.
            payload["metadata"] = {
                "Name": file_name,
                "Description": description,
                "Properties": {},
            }

        response = await self.client._request(
            "POST", f"{self.client.files._base_path}/files/upload/complete", json=payload
        )

        return self.client.files._parse_file_metadata(response.json())

    async def _cancel_upload(self, upload_id: str) -> None:
        """Cancel an upload session.

        Args:
            upload_id: Upload session ID
        """
        await self.client._request(
            "DELETE", f"{self.client.files._base_path}/files/upload/{upload_id}"
        )
