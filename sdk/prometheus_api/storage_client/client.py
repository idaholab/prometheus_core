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

"""Synchronous storage client."""

from typing import Dict, Optional
import httpx
from .connection import ConnectionConfig
from .auth import AuthHandler
from .exceptions import (
    AuthenticationError,
    ItemNotFoundError,
    ValidationError,
    APIError,
    StorageClientError,
)
from .resources.items import ItemsResource
from .resources.files import FilesResource
from .resources.relationships import RelationshipsResource
from .resources.search import SearchResource
from .resources.tags import TagsResource
from .resources.timeseries import TimeseriesResource


class StorageClient:
    """Synchronous client for storage backend operations.

    This client provides a high-level interface for interacting with the storage
    backend, including CRUD operations for items, file management, relationships,
    and search functionality.

    Example:
        ```python
        config = ConnectionConfig(
            organization_id=123,
            project_id=456,
            api_key="key",
            api_secret="secret"
        )

        with StorageClient(config) as client:
            item = client.items.create(ItemCreate(name="Test"))
            results = client.search.query("test")
        ```
    """

    def __init__(self, config: ConnectionConfig):
        """Initialize the storage client.

        Args:
            config: Connection configuration
        """
        self.config = config
        self._http_client: Optional[httpx.Client] = None
        self._auth_handler: Optional[AuthHandler] = None
        self._default_data_source_id: Optional[int] = None  # Cached default data source

        # Resource handlers (lazy-loaded)
        self._items: Optional[ItemsResource] = None
        self._files: Optional[FilesResource] = None
        self._relationships: Optional[RelationshipsResource] = None
        # Relationship-type name -> project relationship ID (see relationships resource).
        self._relationship_type_ids: Dict[str, int] = {}
        self._search: Optional[SearchResource] = None
        self._tags: Optional[TagsResource] = None
        self._timeseries: Optional[TimeseriesResource] = None

    def __enter__(self) -> "StorageClient":
        """Context manager entry."""
        self._http_client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
        )
        self._auth_handler = AuthHandler(self.config, self._http_client)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._http_client:
            self._http_client.close()

    @property
    def items(self) -> ItemsResource:
        """Access items operations."""
        if not self._items:
            self._items = ItemsResource(self)
        return self._items

    @property
    def files(self) -> FilesResource:
        """Access files operations."""
        if not self._files:
            self._files = FilesResource(self)
        return self._files

    @property
    def relationships(self) -> RelationshipsResource:
        """Access relationships operations."""
        if not self._relationships:
            self._relationships = RelationshipsResource(self)
        return self._relationships

    @property
    def search(self) -> SearchResource:
        """Access search operations."""
        if not self._search:
            self._search = SearchResource(self)
        return self._search

    @property
    def tags(self) -> TagsResource:
        """Access tag operations."""
        if not self._tags:
            self._tags = TagsResource(self)
        return self._tags

    @property
    def timeseries(self) -> TimeseriesResource:
        """Access timeseries operations."""
        if not self._timeseries:
            self._timeseries = TimeseriesResource(self)
        return self._timeseries

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with authentication and error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path
            **kwargs: Additional arguments to pass to httpx

        Returns:
            HTTP response

        Raises:
            StorageClientError: On request failure
        """
        if not self._http_client or not self._auth_handler:
            raise StorageClientError("Client not initialized. Use context manager.")

        # Get authentication headers
        headers = self._auth_handler.get_headers()
        if "headers" in kwargs:
            headers.update(kwargs["headers"])
        kwargs["headers"] = headers

        # Make request with retry logic
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._http_client.request(method, path, **kwargs)
                self._handle_response(response)
                return response

            except AuthenticationError:
                # On auth error, try to refresh token once
                if attempt == 0 and self._auth_handler._managed_token:
                    try:
                        self._auth_handler._refresh_token()
                        continue
                    except Exception:
                        pass
                raise

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < self.config.max_retries:
                    continue
                raise StorageClientError(
                    f"Request failed after {self.config.max_retries} retries: {e}"
                )

            except StorageClientError:
                # Already mapped by _handle_response (ItemNotFoundError, ValidationError,
                # APIError); keep the specific type and the server's message.
                raise

            except Exception as e:
                raise StorageClientError(f"Request failed: {e}")

        raise StorageClientError(f"Request failed: {last_error}")

    def _get_data_source_id(self) -> int:
        """Get the data source ID to use for requests.

        Returns the configured data_source_id if available, otherwise fetches
        the default data source for the project.

        Returns:
            Data source ID

        Raises:
            StorageClientError: If no data source is available
        """
        # Use configured data source if available
        if self.config.data_source_id:
            return self.config.data_source_id

        # Use cached default if we've fetched it before
        if self._default_data_source_id:
            return self._default_data_source_id

        # Fetch default data source from API
        try:
            response = self._request(
                "GET", f"/projects/{self.config.project_id}/datasources/default"
            )
            data = response.json()
            self._default_data_source_id = data.get("id")

            if not self._default_data_source_id:
                raise StorageClientError("No default data source found")

            return self._default_data_source_id

        except Exception as e:
            raise StorageClientError(
                f"Failed to get data source ID. Please set DEEPLYNX_DATA_SOURCE_ID "
                f"in your .env file. Error: {e}"
            )

    def _handle_response(self, response: httpx.Response) -> None:
        """Handle API response and raise appropriate exceptions.

        Args:
            response: HTTP response

        Raises:
            AuthenticationError: On 401
            ItemNotFoundError: On 404
            ValidationError: On 4xx errors
            APIError: On other errors
        """
        if response.is_success:
            return

        status_code = response.status_code
        try:
            data = response.json()
        except Exception:
            data = {"error": response.text}

        error_message = data.get("error", data.get("message", f"HTTP {status_code}"))

        if status_code == 401:
            raise AuthenticationError(error_message)
        elif status_code == 404:
            raise ItemNotFoundError(item_id=data.get("id", "unknown"), message=error_message)
        elif 400 <= status_code < 500:
            raise ValidationError(error_message, details=data)
        else:
            raise APIError(error_message, status_code=status_code, response_data=data)
