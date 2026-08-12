"""Self-parsed loader for the packaged YAML catalog (plan KTD11).

Parses ``data-catalog.yaml`` with ``yaml.safe_load`` only, validates the
schema (plan R21, KTD8), and exposes each entry as a :class:`CatalogSource`
with the shared source surface: ``to_dask``, ``read``, ``url``,
``list_ensembles``, ``list_tables``, ``list_variables``, ``discover``.

Import direction (KTD11): ``exceptions <- storage <- loader <- main``.
``CatalogSource`` is constructor-injected with the shared
:class:`~reflective_data_catalog.storage.CloudFileSystem` — never the
catalog object — so this module has no import back-edge into ``main``.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

import yaml

from .exceptions import (
    CatalogError,
    DataNotFoundError,
    MissingCredentialsError,
)

SUPPORTED_SCHEMA_VERSION = 2

#: Permanent kwarg aliases (plan R11): alias -> canonical.
CANONICAL_ALIASES = {
    "ensemble_member": "ensemble",
    "member_id": "ensemble",
    "table_id": "table",
    "variable_id": "variable",
}

#: Governed args surface (plan KTD8); unknown args keys fail catalog load.
ALLOWED_ARGS = {
    "urlpath",
    "combine",
    "concat_dim",
    "xarray_kwargs",
    "storage_options",
    "consolidated",
}

#: Closed storage-options allowlist (plan KTD7): endpoint selection stays
#: code-owned, derived from the URL scheme — never entry-supplied.
ALLOWED_STORAGE_OPTIONS = {"anon"}

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def load_catalog(path: str | Path) -> dict:
    """Parse and validate the catalog file. Raises CatalogError on any defect."""
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as exc:
        raise CatalogError(f"catalog file not readable: {path}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogError(f"catalog file is not valid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"catalog file has no top-level mapping: {path}")

    meta = data.get("metadata") or {}
    version = meta.get("reflective_schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise CatalogError(
            f"catalog schema version {version!r} is not supported by this "
            f"release (expected {SUPPORTED_SCHEMA_VERSION}); upgrade "
            f"reflective-data-catalog or use a matching catalog file"
        )

    sources = data.get("sources") or {}
    for name, entry in sources.items():
        _validate_entry(name, entry, path)
    return data


def _validate_entry(name: str, entry: dict, path: Path) -> None:
    if not name.isidentifier():
        raise CatalogError(
            f"entry name {name!r} is not a valid Python identifier ({path})"
        )
    driver = entry.get("driver")
    if driver not in ("zarr", "netcdf"):
        raise CatalogError(f"entry {name!r} has unsupported driver {driver!r}")
    args = entry.get("args") or {}
    unknown_args = set(args) - ALLOWED_ARGS
    if unknown_args:
        raise CatalogError(
            f"entry {name!r} has unsupported args keys {sorted(unknown_args)}; "
            f"the governed schema allows {sorted(ALLOWED_ARGS)}"
        )
    if driver == "netcdf" and "consolidated" in args:
        raise CatalogError(f"entry {name!r}: 'consolidated' is a zarr-only argument")
    unknown_opts = set(args.get("storage_options") or {}) - ALLOWED_STORAGE_OPTIONS
    if unknown_opts:
        raise CatalogError(
            f"entry {name!r} has unsupported storage_options {sorted(unknown_opts)}; "
            f"allowed: {sorted(ALLOWED_STORAGE_OPTIONS)} (endpoints are derived "
            f"from the URL scheme, never entry-supplied)"
        )
    if not args.get("urlpath"):
        raise CatalogError(f"entry {name!r} has no urlpath")


class CatalogSource:
    """One catalog entry bound to resolved parameters and a shared filesystem.

    Exposes the pre-1.0 source surface (``to_dask``/``read``/``url``/
    ``list_*``/``discover``) on top of a plain dict entry from
    :func:`load_catalog`.
    """

    def __init__(
        self,
        name: str,
        entry: dict,
        fs,
        *,
        matrix_hints: dict[str, str] | None = None,
        **kwargs: Any,
    ):
        self._name = name
        self._entry = entry
        self._fs = fs
        #: Migration-matrix redirect text for removed kwargs (plan R12/AE2):
        #: {kwarg: guidance}; appended to the unknown-kwarg TypeError.
        self._matrix_hints = matrix_hints or {}
        self._discovery_cache: dict[tuple, list[str]] = {}
        self._params = self._resolve_params(kwargs)

    # -- parameters ---------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> dict:
        """The underlying catalog entry (read-only by convention)."""
        return self._entry

    def _declared_params(self) -> dict:
        return self._entry.get("parameters") or {}

    def _derived_params(self) -> dict:
        return ((self._entry.get("metadata") or {}).get("value_map")) or {}

    def _resolve_params(self, kwargs: dict) -> dict:
        declared = self._declared_params()
        values = {p: spec.get("default") for p, spec in declared.items()}

        normalized: dict[str, Any] = {}
        for key, value in kwargs.items():
            canonical = CANONICAL_ALIASES.get(key, key)
            if canonical in normalized and normalized[canonical] != value:
                raise TypeError(
                    f"{self._name}: conflicting values for parameter "
                    f"{canonical!r} (given via an alias as well)"
                )
            normalized[canonical] = value

        derived = self._derived_params()
        unknown = set(normalized) - set(declared)
        if unknown:
            valid = sorted(set(declared) - set(derived))
            aliases = sorted(a for a, c in CANONICAL_ALIASES.items() if c in declared)
            message = (
                f"{self._name}: unknown parameter(s) {sorted(unknown)}. "
                f"Valid parameters: {valid}"
                + (f" (aliases accepted: {aliases})" if aliases else "")
            )
            hints = [
                f"{key!r}: {self._matrix_hints[key]}"
                for key in sorted(unknown)
                if key in self._matrix_hints
            ]
            if hints:
                message += ". Migration note — " + "; ".join(hints)
            raise TypeError(message)

        for key, value in normalized.items():
            if key in derived:
                raise TypeError(
                    f"{self._name}: parameter {key!r} is derived automatically "
                    f"and cannot be set directly"
                )
            values[key] = value

        # Derive mapped parameters (e.g. ensemble -> ensemble_id, plan R4).
        for target, spec in derived.items():
            source_param = spec.get("from")
            mapping = spec.get("map") or {}
            source_value = values.get(source_param)
            if source_value in mapping:
                values[target] = mapping[source_value]
            elif source_value is not None and values.get(target) is None:
                raise DataNotFoundError(
                    f"{self._name}: no {target!r} mapping for "
                    f"{source_param}={source_value!r}; known values: "
                    f"{sorted(mapping)}"
                )
        return values

    def get_parameters(self) -> dict:
        """Unified parameter description (plan KTD11)."""
        return {
            "name": self._name,
            "driver": self._entry.get("driver"),
            "description": self._entry.get("description", ""),
            "parameters": self._declared_params(),
        }

    # -- URL rendering ------------------------------------------------------

    def _urlpaths(self) -> list[str]:
        up = (self._entry.get("args") or {}).get("urlpath")
        return up if isinstance(up, list) else [up]

    def _render(self, template: str, overrides: dict | None = None) -> str:
        values = dict(self._params)
        if overrides:
            values.update(overrides)

        def sub(match: re.Match) -> str:
            key = match.group(1)
            if key not in values or values[key] is None:
                raise CatalogError(
                    f"{self._name}: urlpath references undeclared or unset "
                    f"parameter {key!r}"
                )
            return str(values[key])

        return _PLACEHOLDER.sub(sub, template)

    @property
    def url(self) -> str | list[str]:
        rendered = [self._render(t) for t in self._urlpaths()]
        return rendered[0] if len(rendered) == 1 else rendered

    @property
    def urlpath(self) -> str | list[str]:
        """Alias for :attr:`url` (matches the pre-1.0 surface)."""
        return self.url

    # -- storage ------------------------------------------------------------

    def _storage_options(self) -> dict:
        opts = (self._entry.get("args") or {}).get("storage_options") or {}
        return {k: v for k, v in opts.items() if k in ALLOWED_STORAGE_OPTIONS}

    def _fsspec_target(self, url: str) -> tuple[str, dict]:
        """Translate a catalog URL to (fsspec_url, storage_options)."""
        try:
            fsspec_url, so = self._fs.fsspec_info(url)
        except ValueError as exc:
            raise MissingCredentialsError(
                f"{self._name}: {exc} — for Cloudflare R2 set the "
                f"CLOUDFLARE_R2_ACCOUNT_ID environment variable"
            ) from exc
        merged = dict(so)
        merged.update(self._storage_options())
        return fsspec_url, merged

    # -- loading ------------------------------------------------------------

    def to_dask(self):
        """Open lazily (dask-backed) without loading data into memory."""
        return self._open()

    def read(self):
        """Open and load into memory (plan R10: never silently lazy)."""
        return self._open().load()

    def _open(self):
        driver = self._entry.get("driver")
        if driver == "zarr":
            return self._open_zarr()
        return self._open_netcdf()

    def _open_zarr(self):
        import xarray as xr

        url = self.url
        if isinstance(url, list):
            raise CatalogError(f"{self._name}: zarr entries take one urlpath")
        fsspec_url, so = self._fsspec_target(url)
        args = self._entry.get("args") or {}
        consolidated = args.get("consolidated")
        kwargs = dict(args.get("xarray_kwargs") or {})
        return xr.open_zarr(
            fsspec_url,
            storage_options=so,
            consolidated=consolidated,
            **kwargs,
        )

    def _open_netcdf(self):
        import fsspec
        import xarray as xr

        args = self._entry.get("args") or {}
        xr_kwargs = dict(args.get("xarray_kwargs") or {})
        engine = xr_kwargs.pop("engine", "h5netcdf")

        urls = self.url
        urls = urls if isinstance(urls, list) else [urls]
        open_files: list = []
        matched: list[str] = []
        for url in urls:
            fsspec_url, so = self._fsspec_target(url)
            if any(ch in fsspec_url for ch in "*?"):
                files = fsspec.open_files(fsspec_url, **so)
                matched.extend(f.path for f in files)
                open_files.extend(files)
            else:
                matched.append(fsspec_url)
                open_files.extend(fsspec.open_files(fsspec_url, **so))
        if not open_files:
            raise DataNotFoundError(
                f"{self._name}: no files match {urls!r}. Check parameter "
                f"values with list_variables()/list_ensembles(), or see the "
                f"migration guide if you are using pre-1.0 vocabulary"
            )
        self._assert_selection_purity(matched)

        handles = [f.open() for f in open_files]
        if len(handles) == 1:
            ds = xr.open_dataset(handles[0], engine=engine, **xr_kwargs)
        else:
            combine = args.get("combine", "by_coords")
            mf_kwargs: dict[str, Any] = {"engine": engine, **xr_kwargs}
            if combine == "nested":
                mf_kwargs["combine"] = "nested"
                mf_kwargs["concat_dim"] = args.get("concat_dim", "time")
            else:
                mf_kwargs["combine"] = "by_coords"
            ds = xr.open_mfdataset(handles, **mf_kwargs)
        self._assert_monotonic_time(ds)
        return ds

    # -- selection purity (plan R5) ------------------------------------------

    def _facet_regex(self) -> re.Pattern | None:
        """Regex over matched basenames capturing each templated facet."""
        template = self._urlpaths()[0].rsplit("/", 1)[-1]
        if not _PLACEHOLDER.search(template) and "*" not in template:
            return None
        pattern = ""
        pos = 0
        for m in _PLACEHOLDER.finditer(template):
            pattern += re.escape(template[pos : m.start()]).replace(r"\*", "[^/]*")
            pattern += f"(?P<{m.group(1)}>[^/_.]+)"
            pos = m.end()
        pattern += re.escape(template[pos:]).replace(r"\*", "[^/]*")
        try:
            return re.compile(pattern + "$")
        except re.error:
            return None

    def _assert_selection_purity(self, matched: list[str]) -> None:
        """A multi-file match set must span exactly one facet selection."""
        if len(matched) < 2:
            return
        regex = self._facet_regex()
        if regex is None:
            return
        facet_values: dict[str, set] = {}
        for path in matched:
            m = regex.search(path.rsplit("/", 1)[-1])
            if m is None:
                continue
            for facet, value in m.groupdict().items():
                facet_values.setdefault(facet, set()).add(value)
        impure = {
            facet: sorted(values)
            for facet, values in facet_values.items()
            if len(values) > 1
        }
        if impure:
            raise DataNotFoundError(
                f"{self._name}: the file glob matched a mixed selection "
                f"{impure}; refusing to combine across facets. This is a "
                f"catalog bug — please report it"
            )

    @staticmethod
    def _assert_monotonic_time(ds) -> None:
        if "time" in ds.dims and ds.sizes.get("time", 0) > 1:
            import numpy as np

            time_values = ds["time"].values
            if not (
                np.all(time_values[:-1] < time_values[1:])
                or np.all(time_values[:-1] > time_values[1:])
            ):
                raise DataNotFoundError(
                    "combined time axis is not monotonic; the file set "
                    "likely mixes selections. This is a catalog bug — "
                    "please report it"
                )

    # -- discovery (delimiter-based; plan KTD6 lands fully in U5) -----------

    def list_ensembles(self, refresh: bool = False) -> list:
        return self._scan("ensemble", refresh=refresh)

    def list_tables(self, ensemble: str | None = None, refresh: bool = False) -> list:
        overrides = {"ensemble": ensemble} if ensemble else None
        return self._scan("table", overrides=overrides, refresh=refresh)

    def list_variables(
        self,
        ensemble: str | None = None,
        table: str | None = None,
        variant: str | None = None,
        refresh: bool = False,
    ) -> list:
        overrides = {}
        if ensemble is not None:
            overrides["ensemble"] = ensemble
        if table is not None:
            overrides["table"] = table
        if variant is not None:
            overrides["variant"] = variant
        return self._scan("variable", overrides=overrides or None, refresh=refresh)

    def _scan(
        self,
        param: str,
        overrides: dict | None = None,
        refresh: bool = False,
    ) -> list:
        """Delimiter-list one level at the template depth of ``param``.

        Returns real observed values; an empty scan returns ``[]`` with a
        warning — never the parameter default (plan R9).
        """
        if param not in self._declared_params():
            return []
        cache_key = (param, tuple(sorted((overrides or {}).items())))
        if not refresh and cache_key in self._discovery_cache:
            return self._discovery_cache[cache_key]

        template = self._urlpaths()[0]
        marker = f"\x00{param}\x00"
        values = dict(self._params)
        if overrides:
            values.update({k: v for k, v in overrides.items() if v is not None})
        values[param] = marker
        try:
            rendered = self._render(template, values)
        except CatalogError:
            return []
        prefix = rendered.split(marker)[0]
        listing_at = prefix.rsplit("/", 1)[0]
        segment = rendered.split("/")[len(listing_at.split("/"))]

        try:
            names = [
                item.rsplit("/", 1)[-1]
                for item in self._fs.ls(
                    listing_at,
                    detail=False,
                    storage_options=self._storage_options(),
                )
            ]
        except Exception:
            names = []

        pre, _, post = segment.partition(marker)
        found = sorted(
            {
                name[len(pre) : len(name) - len(post) if post else None]
                for name in names
                if name.startswith(pre) and name.endswith(post)
            }
        )
        found = [v for v in found if v]
        if not found:
            warnings.warn(
                f"{self._name}: scan for {param!r} found nothing under "
                f"{listing_at}; check credentials and parameter values",
                stacklevel=2,
            )
        self._discovery_cache[cache_key] = found
        return found

    def discover(self, refresh: bool = False) -> dict:
        """Summarize scanned availability. Returns data; printing is main's job."""
        return {
            "name": self._name,
            "url": self.url,
            "ensembles": self.list_ensembles(refresh=refresh),
            "tables": self.list_tables(refresh=refresh),
            "variables": self.list_variables(refresh=refresh),
        }

    def __repr__(self) -> str:
        return (
            f"<CatalogSource {self._name!r} driver={self._entry.get('driver')!r}"
            f" params={self._params!r}>"
        )
