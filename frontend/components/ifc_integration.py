"""
IFC integration for Chainlit.

Provides utilities to handle IFC file uploads and create viewer components.
"""

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chainlit as cl

from utils.settings import settings


@dataclass
class IFCDataset:
    """
    Represents an IFC file ready for visualization.
    """

    dataset_id: str
    source_path: Path
    output_dir: Path
    filename: str
    file_size: int

    @property
    def file_url(self) -> str:
        """URL path for accessing the IFC file.

        Derived from the actual ``output_dir`` relative to the ``ifc_data_dir``
        so that per-user namespaced paths (e.g.
        ``ifc-data/{user_id}/{dataset_id}``) produce the correct URL without
        hardcoding the directory structure.
        """
        try:
            rel = self.output_dir.relative_to(settings.ifc_data_dir)
            return f"/public/ifc-data/{rel}/{self.filename}"
        except ValueError:
            # Fallback: output_dir is outside ifc_data_dir (shouldn't happen)
            return f"/public/ifc-data/{self.dataset_id}/{self.filename}"

    def to_props(self) -> dict[str, Any]:
        """Convert to props dict for IFCViewer component."""
        return {
            "datasetId": self.dataset_id,
            "fileUrl": self.file_url,
            "filename": self.filename,
            "height": "500px",
        }

    def to_chainlit_element(self) -> cl.CustomElement:
        """Create a Chainlit CustomElement for this dataset."""
        return cl.CustomElement(
            name="IFCViewer",
            props=self.to_props(),
            display="inline",
        )

    def to_result_dict(self) -> dict[str, Any]:
        """
        Create a structured result dict for agent tool returns.

        This format can be recognized by callbacks for special handling.
        """
        return {
            "_type": "ifc_dataset",
            "dataset_id": self.dataset_id,
            "file_url": self.file_url,
            "filename": self.filename,
            "file_size": self.file_size,
        }


async def process_ifc_upload(
    file_path: Path,
    output_dir: Path | None = None,
) -> IFCDataset:
    """
    Process an uploaded IFC file for visualization.

    Copies the file to the public directory for web access.

    Args:
        file_path: Path to the uploaded IFC file.
        output_dir: Optional custom output directory.  Defaults to
            ``public/ifc-data/{dataset_id}``.  Pass a per-user namespaced path
            (e.g. ``public/ifc-data/{user_id}/{dataset_id}``) so that one user
            cannot access another user's dataset by guessing the URL.

    Returns:
        IFCDataset instance ready for visualization.
    """
    if isinstance(file_path, str):
        file_path = Path(file_path)

    # Generate dataset ID
    dataset_id = str(uuid.uuid4())[:8]

    # Create output directory
    if output_dir is None:
        output_dir = settings.ifc_data_dir / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get filename and file size
    filename = file_path.name
    file_size = file_path.stat().st_size

    # Copy file to public directory
    dest_path = output_dir / filename
    shutil.copy2(file_path, dest_path)

    return IFCDataset(
        dataset_id=dataset_id,
        source_path=file_path,
        output_dir=output_dir,
        filename=filename,
        file_size=file_size,
    )


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.1f} GB"
