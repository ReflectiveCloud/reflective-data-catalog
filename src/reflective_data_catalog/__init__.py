"""Reflective's Unified SAI Data Catalog."""

from importlib.metadata import PackageNotFoundError, version

from .esm import ESMCatalog, GeoMIPCloudHelper
from .main import ReflectiveCatalog
from .storage import CloudFileSystem

try:
    __version__ = version("reflective-data-catalog")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "CloudFileSystem",
    "ESMCatalog",
    "GeoMIPCloudHelper",
    "ReflectiveCatalog",
    "__version__",
]
