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

"""Async files resource."""

from pathlib import Path
from typing import Optional
from ..models.file import FileMetadata
from .base import AsyncBaseResource


class AsyncFilesResource(AsyncBaseResource):
    """Handles async operations related to file storage and retrieval."""

    async def upload(
        self, file_path: Path, name: Optional[str] = None, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload a file to storage asynchronously."""
        if not file_path.exists():
            raise ValueError(f"File does not exist: {file_path}")

        file_name = name or file_path.name

        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            data = {}

            if description:
                data["description"] = description

            response = await self._client._request(
                "POST", f"{self._base_path}/files", files=files, data=data
            )

        return self._parse_file_metadata(response.json())

    async def upload_bytes(
        self, data: bytes, name: str, description: Optional[str] = None
    ) -> FileMetadata:
        """Upload in-memory bytes as one file asynchronously, without a temporary file."""
        from ..utils.streaming import AsyncChunkedUploader

        uploader = AsyncChunkedUploader(self._client)
        if len(data) <= uploader.chunk_size:
            form = {"description": description} if description else {}
            response = await self._client._request(
                "POST", f"{self._base_path}/files", files={"file": (name, data)}, data=form
            )
            return self._parse_file_metadata(response.json())

        chunks = [
            data[i : i + uploader.chunk_size] for i in range(0, len(data), uploader.chunk_size)
        ]
        upload_id = await uploader._start_upload(name, len(data))
        try:
            for chunk_num, chunk_data in enumerate(chunks):
                await uploader._upload_chunk(upload_id, chunk_num, chunk_data)
            return await uploader._complete_upload(upload_id, name, description, len(chunks))
        except Exception:
            try:
                await uploader._cancel_upload(upload_id)
            except Exception:
                pass
            raise

    async def upload_chunked(
        self,
        file_path: Path,
        chunk_size: int = 5 * 1024 * 1024,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> FileMetadata:
        """Upload a large file in chunks asynchronously."""
        from ..utils.streaming import AsyncChunkedUploader

        uploader = AsyncChunkedUploader(self._client, chunk_size)
        return await uploader.upload(file_path, name, description)

    async def get(self, file_id: int) -> FileMetadata:
        """Get file metadata by ID asynchronously."""
        # Files are retrieved via records endpoint (they're records with file attachments)
        response = await self._client._request("GET", f"{self._base_path}/records/{file_id}")

        return self._parse_file_metadata(response.json())

    async def download(self, file_id: int, output_path: Path) -> None:
        """Download a file to local storage asynchronously."""
        # Download using the files endpoint with record ID
        response = await self._client._request("GET", f"{self._base_path}/files/{file_id}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    async def delete(self, file_id: int) -> None:
        """Delete a file asynchronously."""
        await self._client._request("DELETE", f"{self._base_path}/files/{file_id}")

    def _parse_file_metadata(self, data: dict) -> FileMetadata:
        """Parse API response data into FileMetadata model."""
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
