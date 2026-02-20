from pathlib import Path

from .esgf import ESGFHelper
from .esm import ESMCatalog, GeoMIPCloudHelper
from .flexibleSources import (
    FlexibleSource,
    FlexibleSourceConfig,
    FlexibleSourceRegistry,
    SourceDiscovery,
)
from .reflective_data import DEFAULT_FLEXIBLE_SOURCES


class ReflectiveCatalog:
    """
    Unified catalog interface for all of Reflective's climate data sources

    All sources use the same interface pattern:
        ds = catalog.source_name(param='value').to_dask()  # Lazy loading
        ds = catalog.source_name(param='value').read()     # Load to memory

    Attributes:
    -----------
    esgf : ESGFHelper
        Access to ESGF data (GeoMIP, SSP scenarios)
    esm : ESMCatalog
        Access to Google Cloud CMIP6 catalog via intake-esm
    geomip_cloud : GeoMIPCloudHelper
        Convenience helper for loading GeoMIP data from Google Cloud
    """

    def __init__(
        self,
        catalog_path: Path = Path(__file__).parent / "data-catalog.yaml",
        *,
        r2_account_id: str | None = None,
    ):
        """
        Initialize unified catalog

        Parameters:
        -----------
        catalog_path : Path
            Path to the intake YAML catalog
        r2_account_id : str, optional
            Cloudflare R2 account ID.  Falls back to the
            ``CLOUDFLARE_R2_ACCOUNT_ID`` / ``CLOUDFLARE_ACCOUNT_ID``
            environment variable when not provided.
        """
        self._catalog_path = catalog_path
        self._intake_cat = None
        self._r2_account_id = r2_account_id
        self._fs = None  # shared CloudFileSystem (lazy)

        # Initialize helpers
        self.esgf = ESGFHelper()
        self.esm = ESMCatalog()
        self.geomip_cloud = GeoMIPCloudHelper()

        # Initialize flexible source registry with defaults
        self._flexible_registry = FlexibleSourceRegistry()
        for config in DEFAULT_FLEXIBLE_SOURCES:
            self._flexible_registry.register(config)

    @property
    def fs(self):
        """Shared :class:`CloudFileSystem` instance (lazy-initialized)."""
        if self._fs is None:
            from .storage import CloudFileSystem

            self._fs = CloudFileSystem(r2_account_id=self._r2_account_id)
        return self._fs

    def _load_flexible(self, config: FlexibleSourceConfig, lazy: bool = True, **kwargs):
        """
        Internal method to load data from a flexible source configuration

        Parameters:
        -----------
        config : FlexibleSourceConfig
            The source configuration
        lazy : bool
            If True, load lazily with dask. If False, load into memory.
        **kwargs : dict
            Parameters for URL construction

        Returns:
        --------
        xarray.Dataset
        """
        url = config.build_url(**kwargs)

        # Merge defaults with kwargs for display
        params = {**config.defaults, **kwargs}

        print(f"Loading {config.name}")
        print(f"  Table: {params.get('table', 'Amon')}")
        print(f"  Variable: {params.get('variable', 'tas')}")
        print(f"  Ensemble: {params.get('ensemble', 'N/A')}")
        print(f"  URL/Pattern: {url}")
        print(f"  Driver: {config.driver}")
        print(f"  Multi-file: {config.is_multi_file}")
        print(f"  Lazy: {lazy}")

        if config.is_multi_file:
            return self._open_multi_file_dataset(
                url_pattern=url, config=config, lazy=lazy
            )
        else:
            if lazy:
                return self._open_dataset_lazy(url, driver=config.driver)
            else:
                return self._open_dataset(url, driver=config.driver)

    def _open_multi_file_dataset(
        self, url_pattern: str, config: FlexibleSourceConfig, lazy: bool = True
    ):
        """
        Open multiple files matching a glob pattern and combine them

        Parameters:
        -----------
        url_pattern : str
            Cloud storage URL pattern with wildcards (e.g., 's3://bucket/path/*.nc')
        config : FlexibleSourceConfig
            Source configuration with combine settings
        lazy : bool
            If True, load lazily with dask

        Returns:
        --------
        xarray.Dataset
        """
        import xarray as xr

        fs = self.fs

        # Find all matching files
        print(f"  Searching for files matching: {url_pattern}")
        matching_files = fs.glob(url_pattern)

        if not matching_files:
            raise FileNotFoundError(f"No files found matching pattern: {url_pattern}")

        # Sort files (usually by date in filename)
        matching_files = sorted(matching_files)

        print(f"  Found {len(matching_files)} files")
        if len(matching_files) <= 5:
            for f in matching_files:
                print(f"    - {f}")
        else:
            print(f"    - {matching_files[0]}")
            print(f"    - {matching_files[1]}")
            print(f"    ... ({len(matching_files) - 4} more)")
            print(f"    - {matching_files[-2]}")
            print(f"    - {matching_files[-1]}")

        # Handle single file case
        if len(matching_files) == 1:
            url = matching_files[0]
            if lazy:
                return self._open_dataset_lazy(url, driver=config.driver)
            else:
                return self._open_dataset(url, driver=config.driver)

        # Handle combine_files='first'
        if config.combine_files == "first":
            url = matching_files[0]
            print(f"  Using first file only: {url}")
            if lazy:
                return self._open_dataset_lazy(url, driver=config.driver)
            else:
                return self._open_dataset(url, driver=config.driver)

        # Open and combine multiple files
        print(
            f"  Combining files using: {config.combine_files} along '{config.concat_dim}'"
        )

        try:
            if config.driver == "netcdf":
                # Use open_mfdataset for combining multiple NetCDF files
                file_objects = [fs.open(f) for f in matching_files]
                if lazy:
                    ds = xr.open_mfdataset(
                        file_objects,
                        engine="h5netcdf",
                        combine=config.combine_files,
                        concat_dim=config.concat_dim
                        if config.combine_files == "nested"
                        else None,
                        chunks="auto",
                        parallel=True,
                    )
                else:
                    ds = xr.open_mfdataset(
                        file_objects,
                        engine="h5netcdf",
                        combine=config.combine_files,
                        concat_dim=config.concat_dim
                        if config.combine_files == "nested"
                        else None,
                    )
                    ds = ds.load()

                return ds

            elif config.driver == "zarr":
                # For zarr, load each and combine manually
                datasets = []
                for f in matching_files:
                    ds = xr.open_zarr(f, consolidated=True)
                    datasets.append(ds)

                combined = xr.concat(datasets, dim=config.concat_dim)

                if not lazy:
                    combined = combined.load()

                return combined

            else:
                raise ValueError(f"Unknown driver: {config.driver}")

        except Exception as e:
            raise RuntimeError(
                f"Failed to open and combine files from {url_pattern}. Error: {e}"
            )

    def _open_dataset(self, url, driver="netcdf", **kwargs):
        """
        Open a dataset from cloud storage using the appropriate driver

        Parameters:
        -----------
        url : str
            Cloud storage URL or path to the dataset
        driver : str
            Data format driver ('netcdf' or 'zarr')
        **kwargs : dict
            Additional arguments passed to the open function

        Returns:
        --------
        xarray.Dataset
        """
        import xarray as xr

        if driver == "zarr":
            # Zarr can open from URL directly via fsspec
            return xr.open_zarr(url, consolidated=True, **kwargs)

        elif driver == "netcdf":
            fs = self.fs

            try:
                f = fs.open(url)
                ds = xr.open_dataset(f, engine="h5netcdf", **kwargs)
                return ds.load()
            except Exception as e:
                # Try scipy engine as fallback (for NetCDF3 files)
                try:
                    f = fs.open(url)
                    ds = xr.open_dataset(f, engine="scipy", **kwargs)
                    return ds.load()
                except Exception:
                    raise RuntimeError(
                        f"Failed to open NetCDF file from {url}. Original error: {e}"
                    )

        else:
            raise ValueError(
                f"Unknown driver: {driver}. Supported drivers: 'netcdf', 'zarr'"
            )

    def _open_dataset_lazy(self, url, driver="netcdf", **kwargs):
        """
        Open a dataset from cloud storage lazily (using dask)

        Parameters:
        -----------
        url : str
            Cloud storage URL or path to the dataset
        driver : str
            Data format driver ('netcdf' or 'zarr')
        **kwargs : dict
            Additional arguments passed to the open function

        Returns:
        --------
        xarray.Dataset (with dask arrays)
        """
        import xarray as xr

        if driver == "zarr":
            # Zarr can open from URL directly via fsspec
            return xr.open_zarr(url, consolidated=True, **kwargs)

        elif driver == "netcdf":
            try:
                # Use fsspec URL so xarray streams bytes via range
                # requests instead of downloading the whole file.
                fsspec_url, storage_opts = self.fs.fsspec_info(url)
                ds = xr.open_dataset(
                    fsspec_url,
                    engine="h5netcdf",
                    chunks="auto",
                    storage_options=storage_opts,
                    **kwargs,
                )
                return ds
            except Exception as e:
                raise RuntimeError(
                    f"Failed to open NetCDF file lazily from {url}. "
                    f"Error: {e}. "
                    f"Try using .read() instead of .to_dask() to load into memory."
                )

        else:
            raise ValueError(f"Unknown driver: {driver}")

    def _get_intake_catalog(self):
        """Lazy load the intake catalog"""
        import intake

        if self._intake_cat is None:
            try:
                self._intake_cat = intake.open_catalog(self._catalog_path)
            except Exception as e:
                raise RuntimeError(
                    f"Could not load catalog from {self._catalog_path}: {e}"
                )
        return self._intake_cat

    def __getattr__(self, name: str):
        """
        Delegate attribute access to intake catalog OR flexible sources

        This allows unified access:
            catalog.intake_source(param='value').to_dask()
            catalog.flexible_source(param='value').to_dask()
        """
        # Don't intercept private attributes or known attributes
        if name.startswith("_"):
            raise AttributeError(f"'{name}' not found")

        # Check flexible registry first
        config = self._flexible_registry.get(name)
        if config is not None:

            def flexible_loader(**kwargs):
                return FlexibleSource(self, config, **kwargs)

            return flexible_loader

        # Fall back to intake catalog
        try:
            cat = self._get_intake_catalog()
            if name in cat:
                return cat[name]
        except Exception:
            pass

        raise AttributeError(
            f"'{name}' not found in catalog. "
            f"Use catalog.list_sources() to see available sources."
        )

    def __dir__(self) -> list[str]:
        """Show available attributes (for autocomplete)"""
        # Start with flexible sources from registry
        sources = list(self._flexible_registry.keys())

        # Add intake catalog sources
        try:
            cat = self._get_intake_catalog()
            sources.extend(list(cat))
        except Exception:
            pass

        # Add built-in attributes
        builtin = [
            "esgf",
            "esm",
            "geomip_cloud",
            "search",
            "list_sources",
            "list_tags",
            "help",
            "get_parameters",
            "show_parameters",
            "get_source_config",
        ]

        return sorted(set(builtin + sources))

    def get_source_config(self, name: str) -> FlexibleSourceConfig | None:
        """
        Get the configuration for a flexible source

        Parameters:
        -----------
        name : str
            Name of the source

        Returns:
        --------
        FlexibleSourceConfig or None
        """
        return self._flexible_registry.get(name)

    def list_sources(
        self,
        tag: str | None = None,
        driver: str | None = None,
        include_esgf: bool = True,
    ):
        """
        List all available data sources

        Parameters:
        -----------
        tag : str, optional
            Filter by tag (intake sources only)
        driver : str, optional
            Filter by driver type
        include_esgf : bool
            If True, also list available ESGF experiments and models
        """
        print("=" * 80)
        print("AVAILABLE DATA SOURCES")
        print("=" * 80)
        print("\nAll sources use the same interface:")
        print("  ds = catalog.source_name(param='value').to_dask()  # Lazy load")
        print("  ds = catalog.source_name(param='value').read()     # Load to memory")

        # List flexible sources first
        if len(self._flexible_registry) > 0:
            print("\n" + "-" * 80)
            print("FLEXIBLE SOURCES (NetCDF/Zarr on cloud storage)")
            print("-" * 80)

            for name, config in sorted(self._flexible_registry.items()):
                if driver and config.driver != driver:
                    continue

                print(f"\n  {name}")
                if config.description:
                    print(f"    {config.description}")
                print(f"    Driver: {config.driver}")
                print(
                    f"    Defaults: table={config.default_table}, "
                      f"variable={config.default_variable}, "
                    f"ensemble={config.default_ensemble}"
                )
                if config.available_tables:
                    print(f"    Tables: {', '.join(config.available_tables)}")
                if config.is_multi_file:
                    print(
                        f"    Multi-file: Yes (combine={config.combine_files}, "
                        f"concat_dim={config.concat_dim})"
                    )
                if config.filename_pattern:
                    print(f"    Filename pattern: {config.filename_pattern}")

        # List intake catalog sources
        try:
            cat = self._get_intake_catalog()

            print("\n" + "-" * 80)
            print("INTAKE CATALOG SOURCES")
            print("-" * 80)

            for name in sorted(cat):
                entry = cat._entries[name]

                metadata = entry._metadata if hasattr(entry, "_metadata") else {}
                tags = metadata.get("tags", [])
                drv = entry._driver if hasattr(entry, "_driver") else "unknown"
                desc = entry._description if hasattr(entry, "_description") else ""

                if tag and tag not in tags:
                    continue
                if driver and drv != driver:
                    continue

                print(f"\n  {name}")
                print(f"    Driver: {drv}")
                if desc:
                    print(f"    {desc[:60]}...")
                if tags:
                    print(f"    Tags: {', '.join(tags[:5])}")

        except Exception as e:
            print(f"\n  (Could not load intake catalog: {e})")

        # ESM Catalog (Google Cloud CMIP6/GeoMIP) — always shown
        print("\n" + "-" * 80)
        print("GOOGLE CLOUD CMIP6/GeoMIP (via catalog.esm / catalog.geomip_cloud)")
        print("-" * 80)

        print("\n  ESM Catalog (catalog.esm):")
        print(
            "    catalog.esm.search(experiment_id=['G6sulfur','ssp245'], "
            "variable_id='tas', table_id='Amon')"
        )
        print("    catalog.esm.load(experiment_id='G6sulfur', variable_id='tas')")
        print("    catalog.esm.list_experiments(activity_id='GeoMIP')")
        print("    catalog.esm.list_models(experiment_id='G6sulfur')")
        print("    catalog.esm.list_variables(experiment_id='G6sulfur')")

        print("\n  GeoMIP Cloud Helper (catalog.geomip_cloud):")
        print("    catalog.geomip_cloud.g6sulfur(variable='tas')")
        print("    catalog.geomip_cloud.g6solar(variable='tas')")
        print(
            "    catalog.geomip_cloud.load_ensemble("
            "experiments=['G6sulfur','ssp245','ssp585'])"
        )
        print("    catalog.geomip_cloud.list_models()")
        print("    catalog.geomip_cloud.summary()")

        print("\n" + "=" * 80)

        # Add ESGF sources if requested
        if include_esgf:
            print("\n" + "=" * 80)
            print("ESGF DATA SOURCES (via catalog.esgf)")
            print("=" * 80)

            print("\nGeoMIP Experiments (catalog.esgf.geomip):")
            print("  - g6sulfur(model='UKESM1-0-LL', variable='tas')")
            print("  - g6solar(model='UKESM1-0-LL', variable='tas')")

            print("\nCMIP6 SSP Scenarios (catalog.esgf.ssp):")
            print("  - ssp126/ssp245/ssp585(model='...', variable='...')")

            print("\nDirect search:")
            print("  catalog.esgf.search(project='CMIP6', experiment_id='...')")

            print("\n" + "=" * 80)

    def list_tags(self):
        """List all unique tags in the intake catalog"""
        cat = self._get_intake_catalog()

        all_tags = set()
        for name in cat:
            entry = cat._entries[name]
            metadata = entry._metadata if hasattr(entry, "_metadata") else {}
            tags = metadata.get("tags", [])
            all_tags.update(tags)

        print("Available tags:")
        for tag in sorted(all_tags):
            print(f"  - {tag}")

    def search(
        self,
        term: str | None = None,
        variable: str | None = None,
        tag: str | None = None,
    ) -> list[str]:
        """
        Search catalog by name/description, variable, or tag.

        All criteria are combined with AND logic — a source must match
        every specified filter to be included.

        Parameters:
        -----------
        term : str, optional
            Free-text search (case-insensitive) matched against source
            name, description, tags, and driver.
        variable : str, optional
            Filter to sources whose default variable matches, or whose
            filename pattern / config could serve this variable name.
            Case-insensitive.
        tag : str, optional
            Filter to intake catalog sources that have this tag.
            Case-insensitive.

        Returns:
        --------
        list[str] : Matching source names

        Examples:
        ---------
        catalog.search(term='ukesm')           # name / description match
        catalog.search(variable='tas')          # sources with 'tas'
        catalog.search(tag='SAI')               # intake sources tagged 'SAI'
        catalog.search(term='cesm', tag='SAI')  # combined filters
        """
        term_lower = term.lower() if term else None
        var_lower = variable.lower() if variable else None
        tag_lower = tag.lower() if tag else None

        matches: list[str] = []
        match_details: list[tuple[str, str, str]] = []  # (name, kind, desc)

        # ---- helper ----
        def _text_match(text: str) -> bool:
            """Check if term matches a piece of text."""
            return term_lower is not None and term_lower in text.lower()

        # -----------------------------------------------------------------
        # Search flexible registry
        # -----------------------------------------------------------------
        for name, config in self._flexible_registry.items():
            # --- term filter ---
            if term_lower is not None:
                haystack = " ".join(
                    filter(
                        None,
                        [
                            name,
                            config.description,
                            config.driver,
                            config.default_variable,
                            config.default_table,
                            config.default_ensemble,
                        ],
                    )
                )
                if term_lower not in haystack.lower():
                    continue

            # --- variable filter ---
            if var_lower is not None and config.default_variable.lower() != var_lower:
                continue

            # --- tag filter (flexible sources don't have tags, skip) ---
            if tag_lower is not None:
                continue

            matches.append(name)
            match_details.append((name, "flexible", config.description or ""))

        # -----------------------------------------------------------------
        # Search intake catalog
        # -----------------------------------------------------------------
        try:
            cat = self._get_intake_catalog()

            for entry_name in cat:
                if entry_name in matches:
                    continue

                entry = cat._entries[entry_name]
                desc = (
                    entry._description
                    if hasattr(entry, "_description")
                    else ""
                )
                metadata = (
                    entry._metadata if hasattr(entry, "_metadata") else {}
                )
                tags = metadata.get("tags", [])
                drv = (
                    entry._driver if hasattr(entry, "_driver") else ""
                )

                # --- term filter ---
                if term_lower is not None:
                    haystack = " ".join(
                        [entry_name, desc, drv, *tags]
                    ).lower()
                    if term_lower not in haystack:
                        continue

                # --- variable filter ---
                if var_lower is not None:
                    # Check the variable parameter default on the entry
                    entry_var = None
                    if hasattr(entry, "_user_parameters"):
                        var_param = entry._user_parameters.get("variable")
                        if var_param and hasattr(var_param, "default"):
                            entry_var = var_param.default
                    if entry_var is None or entry_var.lower() != var_lower:
                        continue

                # --- tag filter ---
                if tag_lower is not None and not any(
                    tag_lower in t.lower() for t in tags
                ):
                    continue

                matches.append(entry_name)
                match_details.append(
                    (entry_name, "intake", desc[:80] if desc else "")
                )

        except Exception:
            pass

        # -----------------------------------------------------------------
        # Search ESM catalog (Google Cloud CMIP6/GeoMIP)
        # -----------------------------------------------------------------
        try:
            esm_df = self.esm.catalog.df

            # Apply filters to the ESM DataFrame
            filtered = esm_df

            if term_lower is not None:
                # Build a combined text column to search against
                text_cols = [
                    c
                    for c in [
                        "experiment_id",
                        "source_id",
                        "variable_id",
                        "table_id",
                        "activity_id",
                        "institution_id",
                    ]
                    if c in filtered.columns
                ]
                mask = filtered[text_cols].apply(
                    lambda row: term_lower
                    in " ".join(str(v) for v in row).lower(),
                    axis=1,
                )
                filtered = filtered[mask]

            if var_lower is not None and "variable_id" in filtered.columns:
                filtered = filtered[
                    filtered["variable_id"].str.lower() == var_lower
                ]

            if len(filtered) > 0:
                # Group matches by experiment+model for readable output
                group_cols = [
                    c
                    for c in ["activity_id", "source_id", "experiment_id"]
                    if c in filtered.columns
                ]
                if group_cols:
                    groups = (
                        filtered.groupby(group_cols)["variable_id"]
                        .nunique()
                        .reset_index()
                    )
                    groups.columns = [*group_cols, "n_variables"]

                    for _, row in groups.iterrows():
                        parts = [str(row[c]) for c in group_cols]
                        esm_key = ".".join(parts)
                        if esm_key not in matches:
                            matches.append(esm_key)
                            desc = (
                                f"{row.get('source_id', '')} "
                                f"{row.get('experiment_id', '')} — "
                                f"{row['n_variables']} variable(s) on "
                                "Google Cloud (Zarr)"
                            )
                            match_details.append((esm_key, "esm", desc))

        except Exception:
            # ESM catalog not loaded or not available (network required)
            pass

        # -----------------------------------------------------------------
        # Search ESGF shortcut methods
        # -----------------------------------------------------------------
        esgf_entries = [
            (
                "esgf.geomip.g6sulfur",
                "Load G6sulfur data from ESGF "
                "(model, variable, table, member)",
            ),
            (
                "esgf.geomip.g6solar",
                "Load G6solar data from ESGF "
                "(model, variable, table, member)",
            ),
            (
                "esgf.ssp.ssp126",
                "Load SSP1-2.6 scenario from ESGF "
                "(model, variable, table, member)",
            ),
            (
                "esgf.ssp.ssp245",
                "Load SSP2-4.5 scenario from ESGF "
                "(model, variable, table, member)",
            ),
            (
                "esgf.ssp.ssp585",
                "Load SSP5-8.5 scenario from ESGF "
                "(model, variable, table, member)",
            ),
            (
                "esgf.search",
                "Direct ESGF search "
                "(project, experiment_id, source_id, variable_id, ...)",
            ),
        ]

        for esgf_name, esgf_desc in esgf_entries:
            # tag filter doesn't apply to ESGF shortcuts
            if tag_lower is not None:
                continue

            # variable filter: ESGF methods accept any variable, so
            # only exclude if searching for a specific variable and the
            # method name gives no indication of that variable
            if var_lower is not None:
                # ESGF methods accept arbitrary variables — include them
                # only when there's no term filter or the term matches
                if term_lower is not None and term_lower not in (
                    esgf_name + " " + esgf_desc
                ).lower():
                    continue
            elif term_lower is not None:
                haystack = (esgf_name + " " + esgf_desc).lower()
                if term_lower not in haystack:
                    continue

            if esgf_name not in matches:
                matches.append(esgf_name)
                match_details.append((esgf_name, "esgf", esgf_desc))

        # -----------------------------------------------------------------
        # Print results
        # -----------------------------------------------------------------
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

        if match_details:
            for src_name, kind, desc in match_details:
                print(f"\n  {src_name}  [{kind}]")
                if desc:
                    print(f"    {desc}")
        else:
            print(f"\n  No matches found for {filter_str}")

        print("\n" + "=" * 80)
        print(f"Found {len(matches)} match(es)")

        return matches

    def get_parameters(self, source_name: str) -> dict:
        """
        Get parameter information for a source

        Parameters:
        -----------
        source_name : str
            Name of the source

        Returns:
        --------
        dict : Parameter information
        """
        # Check flexible registry
        config = self._flexible_registry.get(source_name)
        if config is not None:
            return {
                "has_parameters": True,
                "is_flexible": True,
                "is_multi_file": config.is_multi_file,
                "parameters": {
                    "table": {
                        "type": "str",
                        "default": config.default_table,
                        "allowed": config.available_tables or None,
                        "description": "CMIP6 table / frequency",
                    },
                    "variable": {
                        "type": "str",
                        "default": config.default_variable,
                        "allowed": None,
                        "description": "Variable name",
                    },
                    "ensemble": {
                        "type": "str",
                        "default": config.default_ensemble,
                        "allowed": None,
                        "description": "Ensemble member",
                    },
                },
                "driver": config.driver,
                "filename_pattern": config.filename_pattern,
                "combine_files": config.combine_files if config.is_multi_file else None,
                "concat_dim": config.concat_dim if config.is_multi_file else None,
                "description": config.description,
            }

        # Check intake catalog
        try:
            cat = self._get_intake_catalog()

            if source_name not in cat:
                raise ValueError(f"Source '{source_name}' not found")

            entry = cat._entries[source_name]

            params = None
            if hasattr(entry, "_params") and "parameters" in entry._params:
                params = entry._params["parameters"]
            elif hasattr(entry, "_user_parameters"):
                params = entry._user_parameters

            if params is None:
                return {
                    "has_parameters": False,
                    "message": f"Source '{source_name}' has no parameters",
                }

            param_info = {
                "has_parameters": True,
                "is_flexible": False,
                "parameters": {},
            }

            for param_name, param_config in params.items():
                param_info["parameters"][param_name] = {
                    "type": param_config.get("type", "unknown"),
                    "default": param_config.get("default", None),
                    "allowed": param_config.get("allowed", None),
                    "description": param_config.get("description", ""),
                }

            return param_info

        except Exception as e:
            raise ValueError(f"Could not get parameters for '{source_name}': {e}")

    def show_parameters(self, source_name, discover=False):
        """
        Print formatted parameter information for a source

        Parameters:
        -----------
        source_name : str
            Name of the source
        discover : bool
            If True, scan cloud storage to show actually available ensembles, tables,
            and variables (slower but more accurate)
        """
        try:
            param_info = self.get_parameters(source_name)
        except ValueError as e:
            print(f"Error: {e}")
            return

        if not param_info.get("has_parameters"):
            print(f"Source '{source_name}' has no parameters")
            return

        print("=" * 80)
        print(f"PARAMETERS: {source_name}")
        print("=" * 80)

        if param_info.get("description"):
            print(f"\n{param_info['description']}")

        if param_info.get("is_flexible"):
            print(f"\n[Flexible source - driver: {param_info.get('driver', 'netcdf')}]")
            if param_info.get("is_multi_file"):
                print(
                    f"[Multi-file source - combine: {param_info.get('combine_files')}, "
                    f"concat_dim: {param_info.get('concat_dim')}]"
                )

        print("\n" + "-" * 40)
        print("PARAMETERS:")
        print("-" * 40)

        for param_name, info in param_info["parameters"].items():
            print(f"\n  {param_name}:")
            print(f"    Default: {info['default']}")
            if info.get("description"):
                print(f"    Description: {info['description']}")
            if info.get("allowed"):
                allowed = info["allowed"]
                if len(allowed) <= 10:
                    print(f"    Allowed: {allowed}")
                else:
                    print(f"    Allowed: {allowed[:5]} ... ({len(allowed)} total)")

        # If discover=True and this is a flexible source, scan cloud storage
        if discover and param_info.get("is_flexible"):
            config = self._flexible_registry.get(source_name)
            if config:
                discovery = SourceDiscovery(config)

                print("\n" + "-" * 40)
                print("AVAILABLE DATA (from cloud storage scan):")
                print("-" * 40)

                # Ensembles
                try:
                    ensembles = discovery.list_ensembles()
                    print(f"\n  Ensembles ({len(ensembles)}):")
                    if len(ensembles) <= 10:
                        for ens in ensembles:
                            marker = (
                                " (default)" if ens == config.default_ensemble else ""
                            )
                            print(f"    • {ens}{marker}")
                    else:
                        for ens in ensembles[:5]:
                            marker = (
                                " (default)" if ens == config.default_ensemble else ""
                            )
                            print(f"    • {ens}{marker}")
                        print(f"    ... and {len(ensembles) - 5} more")
                except Exception as e:
                    print(f"\n  Ensembles: Could not scan ({e})")

                # Tables
                try:
                    tables = discovery.list_tables()
                    print(f"\n  Tables ({len(tables)}):")
                    for tbl in tables:
                        marker = " (default)" if tbl == config.default_table else ""
                        print(f"    • {tbl}{marker}")
                except Exception as e:
                    print(f"\n  Tables: Could not scan ({e})")

                # Variables (for default ensemble/table)
                try:
                    variables = discovery.list_variables()
                    print(
                        f"\n  Variables in {config.default_table} ({len(variables)}):"
                    )
                    if len(variables) <= 20:
                        # Print in columns
                        n_cols = 4
                        col_width = 18
                        for i in range(0, len(variables), n_cols):
                            row = variables[i : i + n_cols]
                            print("    " + "".join(v.ljust(col_width) for v in row))
                    else:
                        # Print first 16 with "and X more"
                        n_cols = 4
                        col_width = 18
                        for i in range(0, 16, n_cols):
                            row = variables[i : i + n_cols]
                            print("    " + "".join(v.ljust(col_width) for v in row))
                        print(f"    ... and {len(variables) - 16} more")
                except Exception as e:
                    print(f"\n  Variables: Could not scan ({e})")

        elif param_info.get("is_flexible") and not discover:
            print("\n" + "-" * 40)
            print("TIP: Use discover=True to scan cloud storage for available data:")
            print(f"  catalog.show_parameters('{source_name}', discover=True)")
            print("-" * 40)

        print("\n" + "=" * 80)
        print(f"Usage: catalog.{source_name}(param='value').to_dask()")
        print("=" * 80)

    def help(self, source_name=None):
        """
        Show help for the catalog or a specific source

        Parameters:
        -----------
        source_name : str, optional
            Name of source to get help for
        """
        if source_name is None:
            from .help_text import HELP_TEXT

            print(HELP_TEXT)
        else:
            self.show_parameters(source_name)
