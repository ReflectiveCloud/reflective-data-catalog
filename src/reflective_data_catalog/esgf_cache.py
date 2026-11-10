"""Shared S3 cache for the files intake-esgf downloads from ESGF.

intake-esgf caches downloads only in local directories (its ``local_cache``
setting), which quickly fills the small home volumes on the Reflective hub.
This module keeps one shared copy of each downloaded dataset version in S3
instead:

* :class:`S3DatasetCache` stores a dataset version's files under
  ``<cache url>/<DRS path>/`` (e.g. ``.../CMIP6/GeoMIP/MOHC/UKESM1-0-LL/
  G6sulfur/r1i1p1f2/Amon/tas/gn/v20191113/``) and uploads a manifest after
  the last file, so a half-uploaded dataset never counts as cached.
* :func:`cached_catalog_class` returns an ``ESGFCatalog`` subclass whose
  ``to_path_dict`` serves cached datasets from S3, downloads the others
  through intake-esgf as usual, uploads them, and deletes the local copies.
  intake-esgf's own ``to_dataset_dict`` and cell-measure lookup both go
  through ``to_path_dict``, so they use the cache too.

If the bucket can't be reached (off the hub, no AWS credentials) or an
upload fails, a warning is shown and intake-esgf's local cache is used for
the rest of the session.

The subclass relies on intake-esgf internals (``df``, ``project``,
``_set_project()``, ``_minimal_key_format()``, ``clone()``), checked against
the pinned floor (2026.11.28) by ``tests/test_esgf_cache.py``.
"""

from __future__ import annotations

import glob
import json
import os
import re
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import CloudFileSystem

DEFAULT_CACHE_URL = "s3://reflective-persistent-prod-large/esgf-cache/"
CACHE_ENV_VAR = "REFLECTIVE_ESGF_CACHE"
MANIFEST_NAME = ".rdc-manifest.json"
_DISABLED_VALUES = {"", "0", "off", "false", "no", "none"}

# h5netcdf reads s3:// URLs through fsspec; netCDF4 (xarray's default first
# choice) would treat them as OPeNDAP and fail.
_ENGINE_ORDER = ("h5netcdf", "netcdf4", "scipy")


def resolve_cache_url(url: str | bool | None = None) -> str | None:
    """Return the cache URL to use, or ``None`` when the cache is off.

    An explicit ``url`` wins (``False`` turns the cache off); otherwise the
    ``REFLECTIVE_ESGF_CACHE`` environment variable; otherwise
    :data:`DEFAULT_CACHE_URL`. ``off``/``none``/``false``/``0`` disable it.
    """
    if url is False:
        return None
    value = url if url is not None else os.environ.get(CACHE_ENV_VAR)
    if value is None:
        value = DEFAULT_CACHE_URL
    value = str(value).strip()
    if value.lower() in _DISABLED_VALUES:
        return None
    return value.rstrip("/")


def dataset_path(dataset_id: str) -> str:
    """Map an ESGF dataset id to its DRS directory.

    ``CMIP6.GeoMIP.MOHC.UKESM1-0-LL.G6sulfur.r1i1p1f2.Amon.tas.gn.v20191113|host``
    becomes ``CMIP6/GeoMIP/MOHC/UKESM1-0-LL/G6sulfur/r1i1p1f2/Amon/tas/gn/
    v20191113``, the same layout intake-esgf uses locally.
    """
    return dataset_id.split("|", 1)[0].replace(".", "/")


class S3DatasetCache:
    """Dataset-version files kept in S3, one manifest per dataset version."""

    def __init__(self, url: str, fs: Any = None):
        self.url = url.rstrip("/")
        self._fs = fs if fs is not None else CloudFileSystem()
        self._usable: bool | None = None
        self._writable = True

    def __repr__(self) -> str:
        return f"S3DatasetCache({self.url!r})"

    def _prefix(self, dataset_id: str) -> str:
        return f"{self.url}/{dataset_path(dataset_id)}"

    def usable(self) -> bool:
        """Check once per session that the bucket can be listed."""
        if self._usable is None:
            try:
                self._fs.ls(self.url + "/")
            except Exception as exc:
                self._usable = False
                warnings.warn(
                    f"The shared ESGF cache {self.url} can't be reached "
                    f"({type(exc).__name__}: {exc}). ESGF downloads go to "
                    "intake-esgf's local cache instead. Outside the Reflective "
                    f"hub, set {CACHE_ENV_VAR}=off to skip this check.",
                    UserWarning,
                    stacklevel=4,
                )
            else:
                self._usable = True
        return self._usable

    def lookup(self, dataset_id: str) -> list[str] | None:
        """Return the dataset's S3 URLs if it is fully cached, else ``None``."""
        prefix = self._prefix(dataset_id)
        try:
            raw = self._fs.open(f"{prefix}/{MANIFEST_NAME}").read()
        except FileNotFoundError:
            return None
        except Exception as exc:
            # e.g. listing is allowed but reads are not: fall back for good
            self._usable = False
            warnings.warn(
                f"Could not read the shared ESGF cache {self.url} "
                f"({type(exc).__name__}: {exc}). ESGF downloads go to "
                "intake-esgf's local cache instead.",
                UserWarning,
                stacklevel=4,
            )
            return None
        manifest = json.loads(raw)
        return [f"{prefix}/{f['name']}" for f in manifest["files"]]

    def store(
        self,
        dataset_id: str,
        paths: list[str | Path],
        local_roots: list[str | Path],
    ) -> list[str]:
        """Upload one dataset version's files and return their S3 URLs.

        Local copies under ``local_roots`` (intake-esgf's local cache) are
        deleted after the manifest is written; files elsewhere, such as a
        read-only ``esg_dataroot`` mirror, are left alone. If an upload
        fails, the local paths are returned unchanged and uploads stop for
        the rest of the session.
        """
        local = sorted((Path(p) for p in paths), key=lambda p: p.name)
        if not self._writable:
            return [str(p) for p in local]
        prefix = self._prefix(dataset_id)
        try:
            files = []
            for p in local:
                size = p.stat().st_size
                self._fs.put(f"{prefix}/{p.name}", p)
                files.append({"name": p.name, "size": size})
            manifest = {
                "dataset_id": dataset_id.split("|", 1)[0],
                "files": files,
                "created": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._fs.put(
                f"{prefix}/{MANIFEST_NAME}", json.dumps(manifest, indent=1).encode()
            )
        except Exception as exc:
            self._writable = False
            warnings.warn(
                f"Could not upload {dataset_id.split('|', 1)[0]} to the shared "
                f"ESGF cache {self.url} ({type(exc).__name__}: {exc}). The files "
                "are kept in the local cache, and no more uploads will be tried "
                "this session.",
                UserWarning,
                stacklevel=4,
            )
            return [str(p) for p in local]

        roots = [Path(r).expanduser().resolve() for r in local_roots]
        for p in local:
            root = _containing_root(p, roots)
            if root is not None:
                p.unlink(missing_ok=True)
                for leftover in _download_leftovers(p):
                    leftover.unlink(missing_ok=True)
                _prune_empty_dirs(p.parent, root)
        return [f"{prefix}/{f['name']}" for f in files]


def _containing_root(path: Path, roots: list[Path]) -> Path | None:
    resolved = path.expanduser().resolve()
    for root in roots:
        if resolved.is_relative_to(root) and resolved != root:
            return root
    return None


_MKSTEMP_SUFFIX = re.compile(r"[a-z0-9_]{8}")


def _download_leftovers(path: Path) -> list[Path]:
    """Temp files intake-esgf left beside ``path`` from failed attempts.

    intake-esgf downloads into ``tempfile.mkstemp(prefix=f"{name}.")`` and
    renames on success, but a stalled or failed attempt leaves its temp file
    (empty or partial) behind before it retries another server.
    """
    prefix = path.name + "."
    return [
        p
        for p in path.parent.glob(glob.escape(prefix) + "*")
        if p.is_file() and _MKSTEMP_SUFFIX.fullmatch(p.name[len(prefix) :])
    ]


def _prune_empty_dirs(directory: Path, root: Path) -> None:
    """Remove now-empty directories from ``directory`` up to (not incl.) root."""
    directory = directory.resolve()
    while directory != root and directory.is_relative_to(root):
        try:
            directory.rmdir()  # only succeeds when empty
        except OSError:
            return
        directory = directory.parent


def _dataset_id(row) -> str:
    ids = row["id"]
    return ids if isinstance(ids, str) else next(iter(ids))


_CLASSES: dict[type, type] = {}


def cached_catalog_class() -> type:
    """Return the ``ESGFCatalog`` subclass that uses :class:`S3DatasetCache`.

    Raises ``ImportError`` when intake-esgf isn't installed.
    """
    from intake_esgf import ESGFCatalog

    cls = _CLASSES.get(ESGFCatalog)
    if cls is None:
        cls = _build_class(ESGFCatalog)
        _CLASSES[ESGFCatalog] = cls
    return cls


def _build_class(base: type) -> type:
    import xarray as xr

    class CachedESGFCatalog(base):
        """``ESGFCatalog`` that keeps downloaded datasets in a shared S3 cache."""

        s3_cache: S3DatasetCache | None = None

        def clone(self):
            # intake-esgf clones the catalog to look up cell measures; keep
            # the clone on this class so those files are cached too.
            cat = super().clone()
            cat.__class__ = type(self)
            cat.s3_cache = self.s3_cache
            return cat

        def to_dataset_dict(self, *args, **kwargs):
            with xr.set_options(netcdf_engine_order=_ENGINE_ORDER):
                return super().to_dataset_dict(*args, **kwargs)

        def to_path_dict(
            self,
            prefer_streaming: bool = False,
            globus_endpoint: str | None = None,
            globus_path: Path = Path("/"),
            minimal_keys: bool = True,
            ignore_facets: None | str | list[str] = None,
            separator: str = ".",
            quiet: bool = False,
        ) -> dict[str, list[str | Path]]:
            passthrough = {
                "prefer_streaming": prefer_streaming,
                "globus_endpoint": globus_endpoint,
                "globus_path": globus_path,
                "minimal_keys": minimal_keys,
                "ignore_facets": ignore_facets,
                "separator": separator,
                "quiet": quiet,
            }
            cache = self.s3_cache
            if (
                cache is None
                or prefer_streaming
                or globus_endpoint is not None
                or not cache.usable()
            ):
                return super().to_path_dict(**passthrough)
            if self.df is None or len(self.df) == 0:
                raise ValueError("No entries to retrieve.")
            if self.project is None:
                self._set_project()

            # Same keys intake-esgf builds; to_dataset_dict reads df["key"].
            facets = self.project.master_id_facets()
            self.df["key"] = self.df.apply(
                lambda row: separator.join(str(row[f]) for f in facets), axis=1
            )

            dsd: dict[str, list[str | Path]] = {}
            missing = []
            for idx, row in self.df.iterrows():
                urls = cache.lookup(_dataset_id(row))
                if urls:
                    dsd[row["key"]] = urls
                else:
                    missing.append(idx)

            if missing:
                sub = self.clone()
                sub.df = self.df.loc[missing].copy()
                sub.project = self.project
                local = base.to_path_dict(
                    sub,
                    minimal_keys=False,
                    ignore_facets=ignore_facets,
                    separator=separator,
                    quiet=quiet,
                )
                dataset_ids = {
                    row["key"]: _dataset_id(row) for _, row in sub.df.iterrows()
                }
                for key, paths in local.items():
                    dsd[key] = cache.store(dataset_ids[key], paths, self.local_cache)

            if minimal_keys:
                key_format = self._minimal_key_format(ignore_facets)
                key_map = {
                    row["key"]: separator.join(str(v) for v in row[key_format])
                    for _, row in self.df.iterrows()
                }
                dsd = {
                    key_map[old]: paths for old, paths in dsd.items() if old in key_map
                }
            return dsd

    return CachedESGFCatalog
