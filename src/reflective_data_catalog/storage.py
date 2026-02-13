"""
Cloud-agnostic file system abstraction using obstore.

Supports S3, GCS, Azure, HTTP, and local filesystems via URL scheme detection.
"""

from __future__ import annotations

import fnmatch
import io
from typing import Any
from urllib.parse import urlparse

import obstore
from obstore.store import from_url


class CloudFileSystem:
    """
    Cloud-agnostic filesystem that wraps obstore.

    Automatically detects the cloud provider from the URL scheme:
        - s3://bucket/path   → AWS S3
        - gs://bucket/path   → Google Cloud Storage
        - az://container/... → Azure Blob Storage
        - file:///path       → Local filesystem
        - http(s)://...      → HTTP

    All methods accept and return full URLs (e.g., "s3://bucket/path/file.nc").

    Usage:
    ------
        fs = CloudFileSystem()

        # List directory contents (one level)
        items = fs.ls("s3://bucket/path/")

        # Glob for files matching a pattern
        files = fs.glob("s3://bucket/path/*.nc")

        # Check if a path exists
        fs.exists("s3://bucket/path/file.nc")

        # Open a file for reading
        f = fs.open("s3://bucket/path/file.nc")
        data = f.read()
    """

    def __init__(self, **kwargs: Any):
        """
        Initialize the filesystem.

        Parameters
        ----------
        **kwargs : dict
            Additional arguments passed to obstore store constructors
            (e.g., config, client_options, retry_config).
        """
        self._store_kwargs = kwargs
        self._stores: dict[str, Any] = {}

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

    def _get_store(self, url: str) -> tuple[Any, str, str]:
        """
        Get or create an obstore store for the given URL.

        Parameters
        ----------
        url : str
            Full URL or bare path.

        Returns
        -------
        tuple[ObjectStore, str, str]
            (store, store_key, rel_path)
        """
        store_key, _bucket, rel_path = self._parse_url(url)

        if store_key not in self._stores:
            self._stores[store_key] = from_url(store_key, **self._store_kwargs)

        return self._stores[store_key], store_key, rel_path

    def glob(self, pattern: str) -> list[str]:
        """
        Find all paths matching a glob pattern.

        Parameters
        ----------
        pattern : str
            Glob pattern with wildcards (* and ?).
            Can be a full URL (e.g., "s3://bucket/path/*.nc") or
            a bare path (e.g., "bucket/path/*.nc", assumes S3).

        Returns
        -------
        list[str]
            Matching paths in the same format as s3fs:
            "bucket/path/to/file" (without scheme prefix).
        """
        store, store_key, rel_pattern = self._get_store(pattern)

        # Extract bucket name from store_key for prepending to results
        bucket = store_key.split("://")[1]

        # Find the static prefix (everything before the first wildcard)
        # Truncate at the last '/' to ensure we use a directory-level prefix
        prefix = rel_pattern.split("*")[0].split("?")[0]
        prefix = prefix[: prefix.rfind("/") + 1] if "/" in prefix else ""

        # List all files under the prefix
        all_files = []
        for chunk in obstore.list(store, prefix=prefix):
            all_files.extend(chunk)

        # Filter with fnmatch and prepend bucket name
        matched = [
            f"{bucket}/{f['path']}"
            for f in all_files
            if fnmatch.fnmatch(f["path"], rel_pattern)
        ]

        return sorted(matched)

    def ls(self, path: str, detail: bool = False) -> list[dict | str]:
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
            Directory contents. Paths include the bucket prefix
            (matching s3fs behavior), e.g., "bucket/path/to/dir".
        """
        store, store_key, rel_path = self._get_store(path)
        bucket = store_key.split("://")[1]

        if rel_path and not rel_path.endswith("/"):
            rel_path += "/"

        result = obstore.list_with_delimiter(store, prefix=rel_path)

        items = []
        for obj in result["objects"]:
            full_path = f"{bucket}/{obj['path']}"
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
            name = f"{bucket}/{pfx.rstrip('/')}"
            if detail:
                items.append({"name": name, "type": "directory"})
            else:
                items.append(name)

        return items

    def exists(self, path: str) -> bool:
        """
        Check if a path exists.

        For directories (paths with objects underneath), this checks for
        any objects with the given prefix.

        Parameters
        ----------
        path : str
            Path to check (full URL or bare path).

        Returns
        -------
        bool
        """
        store, _store_key, rel_path = self._get_store(path)

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

    def open(self, path: str, mode: str = "rb") -> io.BytesIO:
        """
        Open a file for reading.

        Downloads the file content and returns a BytesIO object
        compatible with xarray, h5netcdf, scipy, etc.

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

        store, _store_key, rel_path = self._get_store(path)
        result = obstore.get(store, rel_path)
        return io.BytesIO(bytes(result.bytes()))

    def read_bytes(self, path: str) -> bytes:
        """
        Read a file and return its contents as bytes.

        Parameters
        ----------
        path : str
            Path to the file (full URL or bare path).

        Returns
        -------
        bytes
        """
        store, _store_key, rel_path = self._get_store(path)
        result = obstore.get(store, rel_path)
        return bytes(result.bytes())
