"""
Cloud-agnostic file system abstraction using obstore.

Supports S3, GCS, Azure, Cloudflare R2, HTTP, and local filesystems
via URL scheme detection.
"""

from __future__ import annotations

import io
import os
import re
from typing import Any
from urllib.parse import urlparse

import obstore
from obstore.store import S3Store, from_url

from .exceptions import MissingCredentialsError

# Cloudflare R2 endpoint template
_R2_ENDPOINT = "https://{account_id}.r2.cloudflarestorage.com"


def _glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a glob to a regex where ``*`` does not cross ``/``.

    ``**`` matches across directories, ``*`` within one segment, ``?`` a
    single non-separator character — matching fsspec's glob semantics.
    """
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + "$")


class CloudFileSystem:
    """
    Cloud-agnostic filesystem that wraps obstore.

    Automatically detects the cloud provider from the URL scheme:
        - s3://bucket/path   → AWS S3
        - gs://bucket/path   → Google Cloud Storage
        - az://container/... → Azure Blob Storage
        - r2://bucket/path   → Cloudflare R2 (S3-compatible)
        - file:///path       → Local filesystem
        - http(s)://...      → HTTP

    All methods accept and return full URLs (e.g., "s3://bucket/path/file.nc").

    For Cloudflare R2, provide your account ID via:
        - The ``r2_account_id`` constructor argument, **or**
        - The ``CLOUDFLARE_R2_ACCOUNT_ID`` (or ``CLOUDFLARE_ACCOUNT_ID``)
          environment variable.

    Usage:
    ------
        fs = CloudFileSystem()

        # List directory contents (one level)
        items = fs.ls("s3://bucket/path/")

        # Glob for files matching a pattern
        files = fs.glob("s3://bucket/path/*.nc")

        # Cloudflare R2
        files = fs.glob("r2://my-r2-bucket/data/*.nc")

        # Check if a path exists
        fs.exists("s3://bucket/path/file.nc")

        # Open a file for reading
        f = fs.open("s3://bucket/path/file.nc")
        data = f.read()
    """

    def __init__(self, *, r2_account_id: str | None = None, **kwargs: Any):
        """
        Initialize the filesystem.

        Parameters
        ----------
        r2_account_id : str, optional
            Cloudflare account ID used to build the R2 endpoint.
            Falls back to the ``CLOUDFLARE_R2_ACCOUNT_ID`` or
            ``CLOUDFLARE_ACCOUNT_ID`` environment variable.
        **kwargs : dict
            Additional arguments passed to obstore store constructors
            (e.g., config, client_options, retry_config).
        """
        self._store_kwargs = kwargs
        self._stores: dict[Any, Any] = {}
        self._s3_regions: dict[str, str | None] = {}
        self._r2_account_id = (
            r2_account_id
            or os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID")
            or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
        )

    # ------------------------------------------------------------------
    # R2 helpers
    # ------------------------------------------------------------------

    def _get_r2_endpoint(self) -> str:
        """
        Build the Cloudflare R2 S3-compatible endpoint URL.

        Returns
        -------
        str
            ``https://<account_id>.r2.cloudflarestorage.com``

        Raises
        ------
        MissingCredentialsError
            If no account ID has been configured.
        """
        if not self._r2_account_id:
            raise MissingCredentialsError(
                "Cloudflare R2 account ID is required for r2:// URLs. "
                "Pass r2_account_id to CloudFileSystem() or set the "
                "CLOUDFLARE_R2_ACCOUNT_ID environment variable."
            )
        return _R2_ENDPOINT.format(account_id=self._r2_account_id)

    # ------------------------------------------------------------------
    # URL parsing / store management
    # ------------------------------------------------------------------

    def _parse_url(self, url: str) -> tuple[str, str, str]:
        """
        Parse a URL into scheme, bucket/host, and relative path.

        Parameters
        ----------
        url : str
            Full URL (e.g., "s3://bucket/path/to/file") or
            bare path (e.g., "bucket/path/to/file", assumes S3).

        Returns
        -------
        tuple[str, str, str]
            (store_key, bucket, rel_path) where:
            - store_key: "scheme://bucket" for store caching
            - bucket: the bucket/container name
            - rel_path: path relative to the bucket root
        """
        if "://" not in url:
            url = f"s3://{url}"

        parsed = urlparse(url)
        scheme = parsed.scheme
        bucket = parsed.netloc
        store_key = f"{scheme}://{bucket}"
        rel_path = parsed.path.lstrip("/")

        return store_key, bucket, rel_path

    def _resolve_s3_region(self, bucket: str) -> str | None:
        """Resolve an S3 bucket's region from the x-amz-bucket-region header.

        obstore does not follow S3's cross-region redirects, so listing a
        bucket outside the default region fails ("Received redirect without
        LOCATION"). One unsigned HEAD per bucket per session resolves it;
        the response carries the header even on 403/404.
        """
        if bucket in self._s3_regions:
            return self._s3_regions[bucket]
        import urllib.error
        import urllib.request

        region: str | None = None
        request = urllib.request.Request(
            f"https://{bucket}.s3.amazonaws.com", method="HEAD"
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                region = response.headers.get("x-amz-bucket-region")
        except urllib.error.HTTPError as exc:
            region = exc.headers.get("x-amz-bucket-region")
        except Exception:
            region = None
        self._s3_regions[bucket] = region
        return region

    @staticmethod
    def _translate_options(scheme: str, storage_options: dict | None) -> dict:
        """Translate catalog storage options into obstore constructor kwargs.

        This is the single translation point between the catalog's
        (fsspec-flavored) option vocabulary and obstore's: ``anon: true``
        becomes ``skip_signature=True`` on S3-compatible stores. Endpoint
        selection is code-owned (derived from the URL scheme) and never
        accepted from options.
        """
        translated: dict[str, Any] = {}
        if (
            storage_options
            and storage_options.get("anon")
            and scheme in ("s3", "r2")
        ):
            translated["skip_signature"] = True
        return translated

    def _get_store(
        self, url: str, storage_options: dict | None = None
    ) -> tuple[Any, str, str]:
        """
        Get or create an obstore store for the given URL.

        For ``r2://`` URLs the store is an ``S3Store`` pointed at the
        Cloudflare R2 endpoint.

        Parameters
        ----------
        url : str
            Full URL or bare path.
        storage_options : dict, optional
            Per-entry options from the catalog (allowlisted upstream).
            Stores are cached per (scheme, bucket, options) so entries
            with different options on the same bucket never share a store.

        Returns
        -------
        tuple[ObjectStore, str, str]
            (store, store_key, rel_path)
        """
        store_key, bucket, rel_path = self._parse_url(url)
        scheme = store_key.split("://")[0]
        translated = self._translate_options(scheme, storage_options)
        cache_key = (store_key, tuple(sorted(translated.items())))

        if cache_key not in self._stores:
            kwargs = {**self._store_kwargs, **translated}
            if scheme == "r2":
                endpoint = self._get_r2_endpoint()
                self._stores[cache_key] = S3Store(
                    bucket=bucket,
                    endpoint=endpoint,
                    region="auto",
                    **kwargs,
                )
            else:
                if scheme == "s3" and "region" not in kwargs:
                    region = self._resolve_s3_region(bucket)
                    if region:
                        kwargs["region"] = region
                self._stores[cache_key] = from_url(store_key, **kwargs)

        return self._stores[cache_key], store_key, rel_path

    def glob(
        self, pattern: str, storage_options: dict | None = None
    ) -> list[str]:
        """
        Find all paths matching a glob pattern.

        ``*`` and ``?`` do not cross ``/`` (use ``**`` for recursive
        matches), matching fsspec's glob semantics.

        Parameters
        ----------
        pattern : str
            Glob pattern with wildcards (*, ** and ?).
            Can be a full URL (e.g., "s3://bucket/path/*.nc") or
            a bare path (e.g., "bucket/path/*.nc", assumes S3).
        storage_options : dict, optional
            Per-entry options (e.g. ``{"anon": True}``).

        Returns
        -------
        list[str]
            Full URLs including the scheme prefix,
            e.g. "s3://bucket/path/to/file".
        """
        store, store_key, rel_pattern = self._get_store(pattern, storage_options)

        # Find the static prefix (everything before the first wildcard)
        # Truncate at the last '/' to ensure we use a directory-level prefix
        prefix = rel_pattern.split("*")[0].split("?")[0]
        prefix = prefix[: prefix.rfind("/") + 1] if "/" in prefix else ""

        # List all files under the prefix
        all_files = []
        for chunk in obstore.list(store, prefix=prefix):
            all_files.extend(chunk)

        # Filter and prepend full scheme://bucket prefix
        regex = _glob_to_regex(rel_pattern)
        matched = [
            f"{store_key}/{f['path']}" for f in all_files if regex.match(f["path"])
        ]

        return sorted(matched)

    def ls(
        self,
        path: str,
        detail: bool = False,
        storage_options: dict | None = None,
    ) -> list[dict | str]:
        """
        List directory contents (one level, not recursive).

        Parameters
        ----------
        path : str
            Directory path to list (full URL or bare path).
        detail : bool
            If True, return dicts with 'name', 'type', 'size'.
            If False, return just path strings.

        Returns
        -------
        list
            Directory contents as full URLs including the scheme
            prefix, e.g., "s3://bucket/path/to/dir".
        """
        store, store_key, rel_path = self._get_store(path, storage_options)

        if rel_path and not rel_path.endswith("/"):
            rel_path += "/"

        result = obstore.list_with_delimiter(store, prefix=rel_path)

        items = []
        for obj in result["objects"]:
            full_path = f"{store_key}/{obj['path']}"
            if detail:
                items.append(
                    {
                        "name": full_path,
                        "type": "file",
                        "size": obj.get("size", 0),
                    }
                )
            else:
                items.append(full_path)

        for pfx in result["common_prefixes"]:
            name = f"{store_key}/{pfx.rstrip('/')}"
            if detail:
                items.append({"name": name, "type": "directory"})
            else:
                items.append(name)

        return items

    def exists(self, path: str, storage_options: dict | None = None) -> bool:
        """
        Check if a path exists.

        For directories (paths with objects underneath), this checks for
        any objects with the given prefix.

        Parameters
        ----------
        path : str
            Path to check (full URL or bare path).
        storage_options : dict, optional
            Per-entry options (e.g. ``{"anon": True}``).

        Returns
        -------
        bool
        """
        store, _store_key, rel_path = self._get_store(path, storage_options)

        # First try as a file
        try:
            obstore.head(store, rel_path)
            return True
        except FileNotFoundError:
            pass

        # Then check if it's a directory (has objects with this prefix)
        prefix = rel_path if rel_path.endswith("/") else rel_path + "/"
        result = obstore.list_with_delimiter(store, prefix=prefix)
        return bool(result["objects"] or result["common_prefixes"])

    def fsspec_info(self, url: str) -> tuple[str, dict[str, Any]]:
        """
        Convert a URL to an fsspec-compatible URL and storage options.

        This is useful for passing URLs directly to libraries like xarray
        that use fsspec for lazy, range-request-based file access — avoiding
        the need to download the entire file into memory.

        ``r2://`` URLs are translated to ``s3://`` with the appropriate
        ``endpoint_url`` so that fsspec's S3 backend can reach R2.

        Parameters
        ----------
        url : str
            Full URL (e.g., "s3://bucket/path", "r2://bucket/path").

        Returns
        -------
        tuple[str, dict[str, Any]]
            (fsspec_url, storage_options) ready for
            ``xr.open_dataset(fsspec_url, storage_options=storage_options)``.
        """
        store_key, bucket, rel_path = self._parse_url(url)
        scheme = store_key.split("://")[0]

        storage_options: dict[str, Any] = {}

        if scheme == "r2":
            # fsspec doesn't know r2://; translate to s3:// with R2 endpoint
            endpoint = self._get_r2_endpoint()
            fsspec_url = f"s3://{bucket}/{rel_path}"
            storage_options["endpoint_url"] = endpoint
        else:
            fsspec_url = f"{scheme}://{bucket}/{rel_path}"

        return fsspec_url, storage_options

    def open(
        self,
        path: str,
        mode: str = "rb",
        storage_options: dict | None = None,
    ) -> io.BytesIO:
        """
        Open a file for reading (downloads entire file into memory).

        .. warning::

            This downloads the **complete** file before returning.
            For lazy / dask-backed access, pass the URL directly to
            ``xr.open_dataset`` with :meth:`fsspec_info` instead::

                url, opts = fs.fsspec_info("s3://bucket/file.nc")
                ds = xr.open_dataset(url, engine="h5netcdf",
                                     chunks="auto", storage_options=opts)

        Parameters
        ----------
        path : str
            Path to the file (full URL or bare path).
        mode : str
            File mode (only 'rb' is supported).

        Returns
        -------
        io.BytesIO
            Seekable file-like object with the file contents.
        """
        if mode != "rb":
            raise ValueError(f"Only 'rb' mode is supported, got '{mode}'")

        store, _store_key, rel_path = self._get_store(path, storage_options)
        result = obstore.get(store, rel_path)
        return io.BytesIO(bytes(result.bytes()))
