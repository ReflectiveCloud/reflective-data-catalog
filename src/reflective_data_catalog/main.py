"""Catalog façade over the self-parsed YAML loader.

``ReflectiveCatalog`` eagerly parses and validates the packaged
``data-catalog.yaml`` (plan R13: a corrupt or missing catalog fails at
construction with :class:`~reflective_data_catalog.exceptions.CatalogError`),
exposes every catalog entry as a dynamically dispatched loader callable, and
keeps the ESM/ESGF/GeoMIP helpers available with lazy optional imports.

Import direction (plan KTD11): ``exceptions <- storage <- loader <- main``.
All data loading lives in :mod:`reflective_data_catalog.loader`; this module
only dispatches, lists, searches, and prints.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, NoReturn

import yaml

from .esgf import ESGFHelper
from .esm import ESMCatalog, GeoMIPCloudHelper
from .exceptions import SourceNotFoundError
from .loader import CatalogSource, load_catalog

_DEFAULT_CATALOG_PATH = Path(__file__).parent / "data-catalog.yaml"
_MATRIX_PATH = Path(__file__).parent / "migration_matrix.yaml"

#: Cheap, static helper-method pointers surfaced by :meth:`search` alongside
#: catalog entries. These are not catalog entries: they are not resolvable
#: through ``get_source()`` and need no intake import or network to list.
_HELPER_SUGGESTIONS: list[tuple[str, str, str]] = [
    (
        "esm.search",
        "esm",
        "Search the Google Cloud CMIP6 catalog "
        "(experiment_id, variable_id, table_id, ...) — needs the [esm] extra",
    ),
    (
        "esm.load",
        "esm",
        "Search and load cloud-optimized Zarr datasets from Google Cloud "
        "— needs the [esm] extra",
    ),
    (
        "geomip_cloud.g6sulfur",
        "esm",
        "Load G6sulfur data from the Google Cloud CMIP6 catalog "
        "— needs the [esm] extra",
    ),
    (
        "geomip_cloud.g6solar",
        "esm",
        "Load G6solar data from the Google Cloud CMIP6 catalog — needs the [esm] extra",
    ),
    (
        "geomip_cloud.load_ensemble",
        "esm",
        "Load a multi-experiment GeoMIP ensemble from Google Cloud "
        "— needs the [esm] extra",
    ),
    (
        "esgf.geomip.g6sulfur",
        "esgf",
        "Load G6sulfur data from ESGF (model, variable, table, member) "
        "— needs the [esgf] extra",
    ),
    (
        "esgf.geomip.g6solar",
        "esgf",
        "Load G6solar data from ESGF (model, variable, table, member) "
        "— needs the [esgf] extra",
    ),
    (
        "esgf.ssp.ssp126",
        "esgf",
        "Load SSP1-2.6 scenario from ESGF (model, variable, table, member) "
        "— needs the [esgf] extra",
    ),
    (
        "esgf.ssp.ssp245",
        "esgf",
        "Load SSP2-4.5 scenario from ESGF (model, variable, table, member) "
        "— needs the [esgf] extra",
    ),
    (
        "esgf.ssp.ssp585",
        "esgf",
        "Load SSP5-8.5 scenario from ESGF (model, variable, table, member) "
        "— needs the [esgf] extra",
    ),
    (
        "esgf.search",
        "esgf",
        "Direct ESGF search (project, experiment_id, source_id, variable_id, "
        "...) — needs the [esgf] extra",
    ),
]

_PUBLIC_METHODS = [
    "esgf",
    "esm",
    "geomip_cloud",
    "get_parameters",
    "get_source",
    "help",
    "list_sources",
    "list_tags",
    "search",
    "show_parameters",
]


class ReflectiveCatalog:
    """Unified catalog interface for all of Reflective's climate data sources.

    All sources use the same interface pattern::

        ds = catalog.source_name(param='value').to_dask()  # Lazy loading
        ds = catalog.source_name(param='value').read()     # Load to memory

    Attributes
    ----------
    esgf : ESGFHelper
        Access to ESGF data (GeoMIP, SSP scenarios); needs the [esgf] extra.
    esm : ESMCatalog
        Access to the Google Cloud CMIP6 catalog via intake-esm; needs the
        [esm] extra.
    geomip_cloud : GeoMIPCloudHelper
        Convenience helper for loading GeoMIP data from Google Cloud;
        shares the ``esm`` catalog instance.
    """

    def __init__(
        self,
        catalog_path: str | Path = _DEFAULT_CATALOG_PATH,
        *,
        r2_account_id: str | None = None,
    ):
        """Initialize the unified catalog.

        Parameters
        ----------
        catalog_path : str or Path
            Path to the YAML catalog. Defaults to the packaged
            ``data-catalog.yaml``. The file is parsed and validated
            eagerly; a corrupt or missing catalog raises
            :class:`CatalogError` here rather than at first access.
        r2_account_id : str, optional
            Cloudflare R2 account ID. Falls back to the
            ``CLOUDFLARE_R2_ACCOUNT_ID`` / ``CLOUDFLARE_ACCOUNT_ID``
            environment variable when not provided.
        """
        self._catalog_path = Path(catalog_path)
        self._catalog = load_catalog(self._catalog_path)
        self._entries: dict[str, dict] = self._catalog.get("sources") or {}
        self._r2_account_id = r2_account_id
        self._fs = None  # shared CloudFileSystem (lazy)
        self._matrix_data: dict | None = None  # migration matrix (lazy)

        # Optional-dependency helpers: construction is import-free; intake
        # imports stay lazy inside each helper.
        self.esgf = ESGFHelper()
        self.esm = ESMCatalog()
        self.geomip_cloud = GeoMIPCloudHelper(esm_catalog=self.esm)

    # -- shared infrastructure ----------------------------------------------

    @property
    def fs(self):
        """Shared :class:`CloudFileSystem` instance (lazy-initialized)."""
        if self._fs is None:
            from .storage import CloudFileSystem

            self._fs = CloudFileSystem(r2_account_id=self._r2_account_id)
        return self._fs

    @property
    def _matrix(self) -> dict:
        """The packaged migration matrix (lazy-loaded on first use)."""
        if self._matrix_data is None:
            with _MATRIX_PATH.open() as f:
                self._matrix_data = yaml.safe_load(f) or {}
        return self._matrix_data

    def _removed_kwargs(self) -> dict[str, str]:
        """Redirect text for kwargs the matrix documents as removed."""
        kwarg_rows = self._matrix.get("kwargs") or {}
        return {
            key: text
            for key, text in kwarg_rows.items()
            if isinstance(text, str) and "removed" in text
        }

    def _value_hints(self, name: str) -> dict[str, tuple[str, str]]:
        """Old->new value pairs for this entry from the migration matrix.

        Only pairs whose value actually changed produce guidance; sources
        that kept their vocabulary (e.g. the NetCDF-preserving entries) get
        no hints and accept their historical values unchanged.
        """
        for row in (self._matrix.get("sources") or {}).values():
            if row.get("new_entry") != name:
                continue
            old = row.get("old_defaults") or {}
            new = row.get("new_defaults") or {}
            return {
                param: (str(old_value), str(new[param]))
                for param, old_value in old.items()
                if new.get(param) is not None and new[param] != old_value
            }
        return {}

    def _make_source(self, name: str, kwargs: dict) -> CatalogSource:
        return CatalogSource(
            name,
            self._entries[name],
            self.fs,
            matrix_hints=self._removed_kwargs(),
            value_hints=self._value_hints(name),
            **kwargs,
        )

    def _raise_unknown_source(self, name: str) -> NoReturn:
        suggestions = difflib.get_close_matches(name, list(self._entries), n=3)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise SourceNotFoundError(
            f"{name!r} not found in catalog.{hint} "
            f"Use catalog.list_sources() to see available sources."
        )

    # -- dynamic dispatch ----------------------------------------------------

    def __getattr__(self, name: str):
        """Expose catalog entries as loader callables.

        ``catalog.entry_name(param='value')`` returns a
        :class:`~reflective_data_catalog.loader.CatalogSource`. Unknown
        names raise :class:`SourceNotFoundError` (an ``AttributeError``
        subclass, so ``hasattr`` and tab-completion keep working).
        """
        if name.startswith("_"):
            raise AttributeError(f"{name!r} not found")

        if name in self._entries:

            def source_loader(**kwargs: Any) -> CatalogSource:
                return self._make_source(name, kwargs)

            source_loader.__name__ = name
            source_loader.__qualname__ = f"ReflectiveCatalog.{name}"
            source_loader.__doc__ = self._entries[name].get("description", "")
            return source_loader

        self._raise_unknown_source(name)

    def get_source(self, name: str, **kwargs: Any) -> CatalogSource:
        """String-keyed access to a catalog entry.

        Equivalent to ``getattr(catalog, name)(**kwargs)``; raises
        :class:`SourceNotFoundError` for unknown names.
        """
        if name not in self._entries:
            self._raise_unknown_source(name)
        return self._make_source(name, kwargs)

    def __dir__(self) -> list[str]:
        """Entry names plus the public surface (for tab-completion)."""
        return sorted(set(_PUBLIC_METHODS) | set(self._entries))

    # -- listing and search ---------------------------------------------------

    def list_sources(
        self,
        tag: str | None = None,
        driver: str | None = None,
        verbose: bool = True,
    ) -> list[dict]:
        """List catalog entries as records; optionally print a listing.

        Parameters
        ----------
        tag : str, optional
            Keep only entries carrying this tag (exact match).
        driver : str, optional
            Keep only entries with this driver ('zarr' or 'netcdf').
        verbose : bool
            Print a human-readable listing. Records are always returned.

        Returns
        -------
        list[dict]
            One record per entry:
            ``{name, kind: "entry", driver, stability, tags, description}``.
        """
        stability = self._matrix.get("stability") or {}
        records = []
        for name in sorted(self._entries):
            entry = self._entries[name]
            meta = entry.get("metadata") or {}
            tags = [str(t) for t in (meta.get("tags") or [])]
            drv = entry.get("driver")
            if tag is not None and tag not in tags:
                continue
            if driver is not None and drv != driver:
                continue
            records.append(
                {
                    "name": name,
                    "kind": "entry",
                    "driver": drv,
                    "stability": stability.get(name, "stable"),
                    "tags": tags,
                    "description": entry.get("description", "") or "",
                }
            )

        if verbose:
            print("=" * 80)
            print("AVAILABLE DATA SOURCES")
            print("=" * 80)
            print("\nAll sources use the same interface:")
            print("  ds = catalog.source_name(param='value').to_dask()  # Lazy load")
            print(
                "  ds = catalog.source_name(param='value').read()     # Load to memory"
            )
            for record in records:
                print(f"\n  {record['name']}")
                print(
                    f"    Driver: {record['driver']}  |  "
                    f"Stability: {record['stability']}"
                )
                if record["description"]:
                    print(f"    {record['description']}")
                if record["tags"]:
                    print(f"    Tags: {', '.join(record['tags'][:6])}")
            print("\n" + "=" * 80)
            print("Also available: catalog.esm / catalog.geomip_cloud (Google Cloud")
            print("CMIP6, needs the [esm] extra) and catalog.esgf ([esgf] extra).")
            print("=" * 80)

        return records

    def list_tags(self, verbose: bool = True) -> list[str]:
        """Sorted unique tags across all catalog entries."""
        tags: set[str] = set()
        for entry in self._entries.values():
            meta = entry.get("metadata") or {}
            tags.update(str(t) for t in (meta.get("tags") or []))
        result = sorted(tags)
        if verbose:
            print("Available tags:")
            for t in result:
                print(f"  - {t}")
        return result

    def search(
        self,
        term: str | None = None,
        variable: str | None = None,
        tag: str | None = None,
        verbose: bool = True,
    ) -> list[dict]:
        """Search the catalog by name/description, default variable, or tag.

        All criteria are combined with AND logic.

        Parameters
        ----------
        term : str, optional
            Free-text search (case-insensitive) against name, description,
            driver, and tags.
        variable : str, optional
            Keep entries whose default ``variable`` parameter matches
            (case-insensitive).
        tag : str, optional
            Keep entries with a matching tag (case-insensitive substring).
        verbose : bool
            Print results. Records are always returned.

        Returns
        -------
        list[dict]
            Records ``{name, kind, driver, description}``. Every record
            with ``kind == "entry"`` resolves via ``get_source(name)``;
            helper suggestions (kind ``"esm"``/``"esgf"``) do not.
        """
        term_l = term.lower() if term else None
        var_l = variable.lower() if variable else None
        tag_l = tag.lower() if tag else None

        records: list[dict] = []
        for name in sorted(self._entries):
            entry = self._entries[name]
            meta = entry.get("metadata") or {}
            tags = [str(t) for t in (meta.get("tags") or [])]
            desc = entry.get("description", "") or ""
            drv = entry.get("driver", "") or ""
            if term_l is not None:
                haystack = " ".join([name, desc, drv, *tags]).lower()
                if term_l not in haystack:
                    continue
            if var_l is not None:
                params = entry.get("parameters") or {}
                default_var = (params.get("variable") or {}).get("default")
                if default_var is None or str(default_var).lower() != var_l:
                    continue
            if tag_l is not None and not any(tag_l in t.lower() for t in tags):
                continue
            records.append(
                {"name": name, "kind": "entry", "driver": drv, "description": desc}
            )

        # Cheap helper-method suggestions: static text, no intake import,
        # no network. Tag filtering never applies to them.
        if tag_l is None:
            for helper_name, kind, desc in _HELPER_SUGGESTIONS:
                haystack = f"{helper_name} {desc}".lower()
                if term_l is not None and term_l not in haystack:
                    continue
                records.append(
                    {
                        "name": helper_name,
                        "kind": kind,
                        "driver": None,
                        "description": desc,
                    }
                )

        if verbose:
            filters = []
            if term:
                filters.append(f"term='{term}'")
            if variable:
                filters.append(f"variable='{variable}'")
            if tag:
                filters.append(f"tag='{tag}'")
            filter_str = ", ".join(filters) if filters else "all"
            print("=" * 80)
            print(f"SEARCH RESULTS ({filter_str})")
            print("=" * 80)
            if records:
                for record in records:
                    print(f"\n  {record['name']}  [{record['kind']}]")
                    if record["description"]:
                        print(f"    {record['description']}")
            else:
                print(f"\n  No matches found for {filter_str}")
            print("\n" + "=" * 80)
            print(f"Found {len(records)} match(es)")

        return records

    # -- parameters and help ---------------------------------------------------

    def get_parameters(self, name: str) -> dict:
        """Unified parameter description for a catalog entry.

        Returns
        -------
        dict
            ``{name, driver, description, parameters}`` — the same shape
            as ``CatalogSource.get_parameters()``.

        Raises
        ------
        SourceNotFoundError
            If ``name`` is not a catalog entry.
        """
        return self.get_source(name).get_parameters()

    def show_parameters(self, name: str, discover: bool = False) -> None:
        """Print formatted parameter information for a catalog entry.

        Parameters
        ----------
        name : str
            Name of the catalog entry.
        discover : bool
            If True, scan cloud storage to show actually available
            ensembles, tables, and variables (slower but accurate).
        """
        info = self.get_parameters(name)

        print("=" * 80)
        print(f"PARAMETERS: {info['name']}")
        print("=" * 80)
        if info.get("description"):
            print(f"\n{info['description']}")
        print(f"\n[driver: {info.get('driver')}]")

        print("\n" + "-" * 40)
        print("PARAMETERS:")
        print("-" * 40)
        for param_name, spec in (info.get("parameters") or {}).items():
            print(f"\n  {param_name}:")
            print(f"    Default: {spec.get('default')}")
            if spec.get("description"):
                print(f"    Description: {spec['description']}")
            if spec.get("allowed"):
                allowed = spec["allowed"]
                if len(allowed) <= 10:
                    print(f"    Allowed: {allowed}")
                else:
                    print(f"    Allowed: {allowed[:5]} ... ({len(allowed)} total)")

        if discover:
            print("\n" + "-" * 40)
            print("AVAILABLE DATA (from cloud storage scan):")
            print("-" * 40)
            summary = self.get_source(name).discover()
            for key in ("ensembles", "tables", "variables"):
                values = summary.get(key) or []
                print(f"\n  {key.capitalize()} ({len(values)}):")
                for value in values[:20]:
                    print(f"    - {value}")
                if len(values) > 20:
                    print(f"    ... and {len(values) - 20} more")
        else:
            print("\n" + "-" * 40)
            print("TIP: Use discover=True to scan cloud storage for available data:")
            print(f"  catalog.show_parameters({name!r}, discover=True)")
            print("-" * 40)

        print("\n" + "=" * 80)
        print(f"Usage: catalog.{name}(param='value').to_dask()")
        print("=" * 80)

    def help(self, source_name: str | None = None) -> None:
        """Show help for the catalog or a specific source.

        The SOURCES section is generated from the loaded catalog, so it
        always matches ``data-catalog.yaml``.
        """
        if source_name is None:
            from .help_text import render_help

            print(render_help(self._entries))
        else:
            self.show_parameters(source_name)
