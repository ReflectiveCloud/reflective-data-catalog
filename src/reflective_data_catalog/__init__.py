"""Reflective's Unified SAI Data Catalog."""

from importlib.metadata import PackageNotFoundError, version

from .esm import ESMCatalog, GeoMIPCloudHelper
from .exceptions import (
    CatalogError,
    DataNotFoundError,
    MissingCredentialsError,
    SourceNotFoundError,
)
from .main import ReflectiveCatalog
from .storage import CloudFileSystem

try:
    __version__ = version("reflective-data-catalog")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

# CatalogSource is intentionally not exported here; import it from
# reflective_data_catalog.loader for typing.
__all__ = [
    "CatalogError",
    "CloudFileSystem",
    "DataNotFoundError",
    "ESMCatalog",
    "GeoMIPCloudHelper",
    "MissingCredentialsError",
    "ReflectiveCatalog",
    "SourceNotFoundError",
    "__version__",
]
