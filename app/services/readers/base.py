"""Reader protocol for geospatial file formats."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class RawFeature:
    """A single feature as returned by a reader."""

    geometry_json: str
    properties: dict
    geometry_type: str
    src_crs: str | None
    external_id: str | None


class Reader(Protocol):
    """A reader parses a stored file into raw features."""

    def features(self, path: str) -> Iterator[RawFeature]:
        """Yield features for the file at ``path``."""
        ...
