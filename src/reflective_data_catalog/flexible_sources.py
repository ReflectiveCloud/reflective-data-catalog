from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FlexibleSourceConfig:
    """
    Immutable configuration for a flexible data source.

    This dataclass defines the structure for accessing climate data
    stored in cloud storage with flexible table/variable combinations.

    Supports S3, GCS, Azure, Cloudflare R2, and other cloud providers via obstore.

    Attributes:
    -----------
    name : str
        Unique identifier for this source (used as catalog.name())
    base : str
        Base cloud storage URL (e.g., 's3://bucket/model/experiment',
        'gs://bucket/path', 'az://container/path', 'r2://bucket/path')
    pattern : str
        URL pattern with placeholders: {base}, {ensemble}, {table_path}, {variable}
        This constructs the directory path.
    filename_pattern : str, optional
        Pattern for matching files within the directory. Supports:
        - {variable} : Variable name placeholder
        - {table} : Table name placeholder
        - {ensemble} : Ensemble member placeholder
        - * : Wildcard for any characters (e.g., date ranges)
        - ** : Recursive directory wildcard
        If None, assumes single file at the constructed path (e.g., '{variable}.nc')
        Examples:
        - 'b.e21.BW.f09_g17.SSP245-G6-1p5K-HiLLA.001.cam.h0.{variable}.*.nc'
        - '{variable}_Amon_UKESM1-0-LL_*.nc'
    table_mapping : Dict[str, str]
        Mapping from CMIP6 table names to actual path components
    default_table : str
        Default table if not specified
    default_variable : str
        Default variable if not specified
    default_ensemble : str
        Default ensemble member if not specified
    driver : str
        Data format driver ('netcdf' or 'zarr')
    combine_files : str
        How to combine multiple files when filename_pattern matches multiple:
        - 'by_coords' : Combine by coordinates (default, good for time series)
        - 'nested' : Combine as nested dataset
        - 'first' : Use only the first matched file
    concat_dim : str
        Dimension to concatenate along when combining files (default: 'time')
    description : str
        Human-readable description of this data source
    """

    name: str
    base: str
    pattern: str
    filename_pattern: str | None = None
    table_mapping: dict[str, str] = field(default_factory=dict)
    ensemble_mapping: dict[str, str] = field(default_factory=dict)
    default_table: str = "Amon"
    default_variable: str = "tas"
    default_ensemble: str = "r1i1p1f1"
    default_time: str | None = None
    default_variant: str | None = None
    driver: str = "netcdf"
    combine_files: str = "by_coords"
    concat_dim: str = "time"
    description: str = ""

    @property
    def defaults(self) -> dict[str, str]:
        """Get defaults as a dictionary for compatibility"""
        d = {
            "table": self.default_table,
            "variable": self.default_variable,
            "ensemble": self.default_ensemble,
        }
        if self.default_time is not None:
            d["time"] = self.default_time
        if self.default_variant is not None:
            d["variant"] = self.default_variant
        return d

    @property
    def available_tables(self) -> list[str]:
        """Get list of available tables"""
        return list(self.table_mapping.keys()) if self.table_mapping else []

    @property
    def has_filename_pattern(self) -> bool:
        """Check if this config uses a filename pattern (multi-file source)"""
        return self.filename_pattern is not None

    @property
    def is_multi_file(self) -> bool:
        """Check if this config potentially matches multiple files"""
        if self.filename_pattern is None:
            return False
        return "*" in self.filename_pattern or "?" in self.filename_pattern

    def build_directory_path(self, **kwargs) -> str:
        """
        Build the cloud storage directory path for this source

        Parameters:
        -----------
        **kwargs : dict
            Override parameters (table, variable, ensemble)

        Returns:
        --------
        str : Cloud storage directory path
        """
        # Apply defaults, then override with provided kwargs
        table = kwargs.get("table", self.default_table)
        variable = kwargs.get("variable", self.default_variable)
        ensemble = kwargs.get(
            "ensemble", kwargs.get("ensemble_member", self.default_ensemble)
        )

        # Map table to path
        table_path = self.table_mapping.get(table, table)

        time = kwargs.get("time", self.default_time or "")
        variant = kwargs.get("variant", self.default_variant or "")

        # Map ensemble to ID for filenames (e.g. r1 -> 001)
        ensemble_id = self.ensemble_mapping.get(ensemble, ensemble)

        # Build directory path
        return self.pattern.format(
            base=self.base,
            ensemble=ensemble,
            ensemble_id=ensemble_id,
            table_path=table_path,
            variable=variable,
            table=table,
            time=time,
            variant=variant,
        )

    def build_filename_glob(self, **kwargs) -> str:
        """
        Build the filename glob pattern for matching files

        Parameters:
        -----------
        **kwargs : dict
            Override parameters (table, variable, ensemble)

        Returns:
        --------
        str : Filename pattern with placeholders filled in but wildcards preserved
        """
        if self.filename_pattern is None:
            # Default to simple variable.nc pattern
            variable = kwargs.get("variable", self.default_variable)
            return f"{variable}.nc"

        table = kwargs.get("table", self.default_table)
        variable = kwargs.get("variable", self.default_variable)
        ensemble = kwargs.get(
            "ensemble", kwargs.get("ensemble_member", self.default_ensemble)
        )

        time = kwargs.get("time", self.default_time or "")
        variant = kwargs.get("variant", self.default_variant or "")

        # Map ensemble to ID for filenames (e.g. r1 -> 001)
        ensemble_id = self.ensemble_mapping.get(ensemble, ensemble)

        # Replace placeholders but keep wildcards
        return self.filename_pattern.format(
            variable=variable,
            table=table,
            ensemble=ensemble,
            ensemble_id=ensemble_id,
            time=time,
            variant=variant,
        )

    def build_url(self, **kwargs) -> str:
        """
        Build the complete cloud storage URL or glob pattern for this source

        Parameters:
        -----------
        **kwargs : dict
            Override parameters (table, variable, ensemble)

        Returns:
        --------
        str : Complete URL (may include wildcards for multi-file sources)
        """
        directory = self.build_directory_path(**kwargs)
        filename = self.build_filename_glob(**kwargs)

        # Ensure proper path joining
        if directory.endswith("/"):
            return f"{directory}{filename}"
        else:
            return f"{directory}/{filename}"

    def validate(self) -> list[str]:
        """
        Validate the configuration

        Returns:
        --------
        List[str] : List of validation errors (empty if valid)
        """
        errors = []

        if not self.name:
            errors.append("name is required")
        if not self.base:
            errors.append("base cloud storage URL is required")
        if not self.pattern:
            errors.append("URL pattern is required")
        if "://" not in self.base:
            errors.append(
                "base must be a cloud storage URL (e.g., s3://, gs://, az://, r2://)"
            )
        if self.driver not in ("netcdf", "zarr"):
            errors.append(f"driver must be 'netcdf' or 'zarr', got '{self.driver}'")
        if self.combine_files not in ("by_coords", "nested", "first"):
            errors.append("combine_files must be 'by_coords', 'nested', or 'first'")

        # Check filename_pattern has required placeholder
        if self.filename_pattern is not None:
            if (
                "{variable}" not in self.filename_pattern
                and "{variable}" not in self.pattern
            ):
                errors.append(
                    "Either pattern or filename_pattern must contain {variable}"
                )
        elif "{variable}" not in self.pattern:
            errors.append(
                "pattern must contain {variable} when no filename_pattern is set"
            )

        return errors


class SourceDiscovery:
    """
    Discovery utilities for finding available data in cloud storage.

    This class provides methods to scan cloud storage and discover what
    variables, ensembles, and tables are actually available.

    Supports S3, GCS, Azure, Cloudflare R2, and other cloud providers via obstore.
    """

    def __init__(self, config: FlexibleSourceConfig):
        self.config = config
        self._fs = None
        self._cache: dict[str, Any] = {}

    @property
    def fs(self):
        """Lazy initialization of cloud filesystem"""
        if self._fs is None:
            from .storage import CloudFileSystem

            self._fs = CloudFileSystem()
        return self._fs

    def clear_cache(self):
        """Clear the discovery cache"""
        self._cache = {}

    def list_ensembles(self, refresh: bool = False) -> list[str]:
        """
        Discover available ensemble members by scanning cloud storage

        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan

        Returns:
        --------
        List[str] : Available ensemble member identifiers
        """
        cache_key = "ensembles"
        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]

        # Parse the pattern to find where {ensemble} appears
        # Typically: {base}/{ensemble}/...
        pattern = self.config.pattern
        base = self.config.base

        if "{ensemble}" not in pattern:
            # No ensemble dimension in this source
            return [self.config.default_ensemble]

        # Find the path up to {ensemble}
        pattern_parts = pattern.replace("{base}", "").strip("/").split("/")
        ensemble_depth = None
        for i, part in enumerate(pattern_parts):
            if "{ensemble}" in part:
                ensemble_depth = i
                break

        if ensemble_depth is None:
            return [self.config.default_ensemble]

        # List directories at the ensemble level
        search_path = base
        for i in range(ensemble_depth):
            part = pattern_parts[i]
            if "{" not in part:
                search_path = f"{search_path}/{part}"

        try:
            print(f"Scanning for ensembles in: {search_path}/")
            contents = self.fs.ls(search_path, detail=True)

            ensembles = []
            for item in contents:
                if item["type"] == "directory":
                    name = item["name"].split("/")[-1]
                    # Filter out hidden directories
                    if not name.startswith("."):
                        ensembles.append(name)

            ensembles = sorted(ensembles)
            self._cache[cache_key] = ensembles
            return ensembles

        except Exception as e:
            print(f"Warning: Could not list ensembles: {e}")
            return [self.config.default_ensemble]

    def list_tables(
        self, ensemble: str | None = None, refresh: bool = False
    ) -> list[str]:
        """
        Discover available tables by scanning cloud storage

        Parameters:
        -----------
        ensemble : str, optional
            Ensemble to check (uses default if not specified)
        refresh : bool
            If True, bypass cache and rescan

        Returns:
        --------
        List[str] : Available table names
        """
        ensemble = ensemble or self.config.default_ensemble
        cache_key = f"tables_{ensemble}"

        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]

        # If we have explicit table mapping, check which ones exist
        if self.config.table_mapping:
            existing_tables = []
            for table_name, _table_path in self.config.table_mapping.items():
                try:
                    dir_path = self.config.build_directory_path(
                        ensemble=ensemble, table=table_name, variable="PLACEHOLDER"
                    )
                    # Only strip the last component if {variable} is in the pattern
                    # (i.e. PLACEHOLDER appears in the built path)
                    if "PLACEHOLDER" in dir_path:
                        dir_path = (
                            dir_path.rsplit("/", 1)[0] if "/" in dir_path else dir_path
                        )

                    if self.fs.exists(dir_path):
                        existing_tables.append(table_name)
                except Exception:
                    pass

            self._cache[cache_key] = sorted(existing_tables)
            return self._cache[cache_key]

        # Otherwise, try to discover tables from directory structure
        pattern = self.config.pattern
        if "{table_path}" not in pattern and "{table}" not in pattern:
            return [self.config.default_table]

        # Build path up to table level
        try:
            # Replace known values
            ensemble_id = self.config.ensemble_mapping.get(ensemble, ensemble)
            partial_path = pattern.format(
                base=self.config.base,
                ensemble=ensemble,
                ensemble_id=ensemble_id,
                table_path="*",
                table="*",
                variable="*",
                time=self.config.default_time or "*",
                variant=self.config.default_variant or "*",
            )
            # Find parent of table — strip scheme for path parsing
            scheme_prefix = ""
            path_for_split = partial_path
            if "://" in partial_path:
                idx = partial_path.index("://")
                scheme_prefix = partial_path[: idx + 3]
                path_for_split = partial_path[idx + 3 :]

            parts = path_for_split.split("/")
            table_idx = None
            for i, p in enumerate(parts):
                if p == "*":
                    table_idx = i
                    break

            if table_idx is None:
                return [self.config.default_table]

            search_path = scheme_prefix + "/".join(parts[:table_idx])
            print(f"Scanning for tables in: {search_path}/")

            contents = self.fs.ls(search_path, detail=True)
            tables = []
            for item in contents:
                if item["type"] == "directory":
                    name = item["name"].split("/")[-1]
                    if not name.startswith("."):
                        tables.append(name)

            # Reverse map if we have table_mapping
            if self.config.table_mapping:
                reverse_map = {v: k for k, v in self.config.table_mapping.items()}
                tables = [reverse_map.get(t, t) for t in tables]

            tables = sorted(set(tables))
            self._cache[cache_key] = tables
            return tables

        except Exception as e:
            print(f"Warning: Could not list tables: {e}")
            return (
                list(self.config.table_mapping.keys())
                if self.config.table_mapping
                else [self.config.default_table]
            )

    def list_variables(
        self,
        ensemble: str | None = None,
        table: str | None = None,
        variant: str | None = None,
        refresh: bool = False,
    ) -> list[str]:
        """
        Discover available variables by scanning cloud storage

        Parameters:
        -----------
        ensemble : str, optional
            Ensemble to check (uses default if not specified)
        table : str, optional
            Table to check (uses default if not specified)
        variant : str, optional
            Variant to check (uses default if not specified)
        refresh : bool
            If True, bypass cache and rescan

        Returns:
        --------
        List[str] : Available variable names
        """
        ensemble = ensemble or self.config.default_ensemble
        table = table or self.config.default_table
        variant = variant or self.config.default_variant or ""
        time = self.config.default_time or ""
        ensemble_id = self.config.ensemble_mapping.get(ensemble, ensemble)
        cache_key = f"variables_{ensemble}_{table}_{variant}"

        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]

        try:
            # Build full URL pattern with variable='*' to glob all variables
            # This correctly handles {variable} in both directory and filename patterns
            full_url = self.config.build_url(
                ensemble=ensemble, table=table, variant=variant, time=time, variable="*"
            )
            print(f"Scanning for variables with pattern: {full_url}")

            files = self.fs.glob(full_url)
            print(f"Found {len(files)} files")

            if len(files) == 0:
                # Try to help debug: check if the base directory exists
                # Strip back to the first wildcard to check the parent path
                static_prefix = full_url.split("*")[0].rstrip("/")
                # Go up one level from the wildcard
                parent = (
                    static_prefix.rsplit("/", 1)[0]
                    if "/" in static_prefix
                    else static_prefix
                )
                try:
                    contents = self.fs.ls(parent)
                    print(f"Parent directory {parent}/ has {len(contents)} items.")
                    if contents:
                        samples = [c.split("/")[-1] for c in contents[:3]]
                        print(f"Sample items: {samples}")
                except Exception:
                    print(f"Parent directory not accessible: {parent}/")
                return [self.config.default_variable]

            # Extract variable names from filenames
            variables = set()
            unmatched = []
            for f in files:
                filename = f.split("/")[-1]
                var_name = self._extract_variable_from_filename(
                    filename, table, ensemble, variant, ensemble_id, time
                )
                if var_name:
                    variables.add(var_name)
                else:
                    unmatched.append(filename)

            if unmatched and not variables:
                print(
                    f"Warning: Found {len(unmatched)} files but could not extract "
                    f"variable names from any of them."
                )
                print(f"Sample file: {unmatched[0]}")
                print(f"Expected pattern: {self.config.filename_pattern}")
                return [self.config.default_variable]

            variables = sorted(variables)
            self._cache[cache_key] = variables
            return variables

        except Exception as e:
            print(f"Warning: Could not list variables: {e}")
            return [self.config.default_variable]

    def _extract_variable_from_filename(
        self,
        filename: str,
        table: str,
        ensemble: str,
        variant: str,
        ensemble_id: str,
        time: str = "",
    ) -> str | None:
        """
        Extract variable name from a filename based on the pattern

        Parameters:
        -----------
        filename : str
            The filename to parse
        table : str
            Current table name
        ensemble : str
            Current ensemble member
        variant : str
            Current variant
        ensemble_id : str
            Current ensemble ID
        time : str
            Current time/frequency identifier

        Returns:
        --------
        str or None : Extracted variable name
        """
        if self.config.filename_pattern is None:
            # Simple case: variable.nc
            if filename.endswith(".nc"):
                return filename[:-3]
            elif filename.endswith(".zarr"):
                return filename[:-5]
            return None

        # Complex case: parse based on pattern
        # Convert pattern to regex
        import re

        pattern = self.config.filename_pattern
        # Escape special regex chars except our placeholders
        pattern = pattern.replace(".", r"\.")
        pattern = pattern.replace("*", ".*")
        pattern = pattern.replace("?", ".")

        # Replace placeholders with capture groups or literals
        pattern = pattern.replace("{variable}", r"(?P<variable>[^.]+)")
        pattern = pattern.replace("{table}", re.escape(table))
        pattern = pattern.replace("{ensemble}", re.escape(ensemble))
        pattern = pattern.replace("{ensemble_id}", re.escape(ensemble_id))
        pattern = pattern.replace("{variant}", re.escape(variant))
        pattern = pattern.replace("{time}", re.escape(time))

        try:
            match = re.match(pattern, filename)
            if match:
                return match.group("variable")
        except Exception:
            pass

        return None

    def describe(self, refresh: bool = False) -> dict[str, Any]:
        """
        Get a complete description of available data

        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan cloud storage

        Returns:
        --------
        Dict with keys: ensembles, tables, variables (nested by ensemble/table)
        """
        result = {
            "name": self.config.name,
            "description": self.config.description,
            "base": self.config.base,
            "driver": self.config.driver,
            "is_multi_file": self.config.is_multi_file,
            "ensembles": [],
            "tables": {},
            "variables": {},
        }

        # Get ensembles
        ensembles = self.list_ensembles(refresh=refresh)
        result["ensembles"] = ensembles

        # For each ensemble, get tables and variables
        for ensemble in ensembles[:3]:  # Limit to first 3 to avoid too many API calls
            tables = self.list_tables(ensemble=ensemble, refresh=refresh)
            result["tables"][ensemble] = tables
            result["variables"][ensemble] = {}

            for table in tables[:5]:  # Limit to first 5 tables
                variables = self.list_variables(
                    ensemble=ensemble, table=table, refresh=refresh
                )
                result["variables"][ensemble][table] = variables

        return result

    def print_summary(self, refresh: bool = False):
        """
        Print a formatted summary of available data

        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan cloud storage
        """
        print("=" * 80)
        print(f"SOURCE: {self.config.name}")
        print("=" * 80)

        if self.config.description:
            print(f"\n{self.config.description}")

        print(f"\nBase: {self.config.base}")
        print(f"Driver: {self.config.driver}")
        print(f"Multi-file: {self.config.is_multi_file}")

        if self.config.filename_pattern:
            print(f"Filename pattern: {self.config.filename_pattern}")

        # Ensembles
        print("\n" + "-" * 40)
        print("ENSEMBLES:")
        print("-" * 40)
        ensembles = self.list_ensembles(refresh=refresh)
        for ens in ensembles:
            marker = " (default)" if ens == self.config.default_ensemble else ""
            print(f"  • {ens}{marker}")

        # Tables
        print("\n" + "-" * 40)
        print("TABLES:")
        print("-" * 40)
        tables = self.list_tables(refresh=refresh)
        for table in tables:
            marker = " (default)" if table == self.config.default_table else ""
            print(f"  • {table}{marker}")

        # Variables (for default ensemble/table)
        print("\n" + "-" * 40)
        print(
            f"VARIABLES (ensemble={self.config.default_ensemble}, table={self.config.default_table}):"
        )
        print("-" * 40)
        variables = self.list_variables(refresh=refresh)

        # Print in columns
        n_cols = 4
        col_width = 20
        for i in range(0, len(variables), n_cols):
            row = variables[i : i + n_cols]
            print("  " + "".join(v.ljust(col_width) for v in row))

        print("\n" + "=" * 80)


class FlexibleSourceRegistry:
    """
    Protected registry for flexible source configurations.

    This class manages FlexibleSourceConfig instances and provides
    controlled access to prevent accidental modification.
    """

    def __init__(self):
        self._configs: dict[str, FlexibleSourceConfig] = {}

    def register(self, config: FlexibleSourceConfig) -> None:
        """
        Register a new flexible source configuration

        Parameters:
        -----------
        config : FlexibleSourceConfig
            The configuration to register

        Raises:
        -------
        ValueError : If configuration is invalid or name already exists
        """
        # Validate configuration
        errors = config.validate()
        if errors:
            raise ValueError(
                f"Invalid configuration for '{config.name}': {', '.join(errors)}"
            )

        if config.name in self._configs:
            raise ValueError(
                f"Source '{config.name}' already registered. "
                f"Use unregister() first to replace it."
            )

        self._configs[config.name] = config

    def unregister(self, name: str) -> bool:
        """
        Remove a source configuration

        Parameters:
        -----------
        name : str
            Name of the source to remove

        Returns:
        --------
        bool : True if removed, False if not found
        """
        if name in self._configs:
            del self._configs[name]
            return True
        return False

    def get(self, name: str) -> FlexibleSourceConfig | None:
        """
        Get a source configuration by name

        Parameters:
        -----------
        name : str
            Name of the source

        Returns:
        --------
        FlexibleSourceConfig or None
        """
        return self._configs.get(name)

    def __contains__(self, name: str) -> bool:
        """Check if a source is registered"""
        return name in self._configs

    def __iter__(self):
        """Iterate over registered source names"""
        return iter(self._configs)

    def items(self):
        """Iterate over (name, config) pairs"""
        return self._configs.items()

    def keys(self):
        """Get all registered source names"""
        return self._configs.keys()

    def values(self):
        """Get all registered configurations"""
        return self._configs.values()

    def __len__(self) -> int:
        """Get number of registered sources"""
        return len(self._configs)


class FlexibleSource:
    """
    Wrapper that mimics intake source interface for flexible URL templates.

    This allows flexible sources to be used with the same interface as intake:
        ds = catalog.source_name(param='value').to_dask()
        ds = catalog.source_name(param='value').read()

    Also provides discovery methods to explore available data:
        source = catalog.source_name()
        source.list_variables()
        source.list_ensembles()
        source.list_tables()
        source.discover()  # Full summary
    """

    def __init__(
        self,
        catalog: "ReflectiveCatalog",
        config: FlexibleSourceConfig,
        **kwargs,  # noqa: F821
    ):
        """
        Initialize flexible source

        Parameters:
        -----------
        catalog : ReflectiveCatalog
            Reference to parent catalog
        config : FlexibleSourceConfig
            Configuration for this source
        **kwargs : dict
            Parameters for loading (table, variable, ensemble, etc.)
        """
        self._catalog = catalog
        self._config = config
        self._kwargs = kwargs
        self._ds = None
        self._discovery = None

        # Build URL immediately for inspection
        self._url = config.build_url(**kwargs)

    @property
    def _discover(self) -> SourceDiscovery:
        """Lazy initialization of discovery helper"""
        if self._discovery is None:
            self._discovery = SourceDiscovery(self._config)
        return self._discovery

    def to_dask(self):
        """
        Load dataset lazily with dask arrays (matches intake interface)

        Returns:
        --------
        xarray.Dataset with dask arrays
        """
        if self._ds is None:
            self._ds = self._catalog._load_flexible(
                self._config, lazy=True, **self._kwargs
            )
        return self._ds

    def read(self):
        """
        Load dataset into memory (matches intake interface)

        Returns:
        --------
        xarray.Dataset loaded into memory
        """
        return self._catalog._load_flexible(self._config, lazy=False, **self._kwargs)

    @property
    def url(self) -> str:
        """Get the cloud storage URL for this source"""
        return self._url

    @property
    def urlpath(self) -> str:
        """Alias for url (matches intake interface)"""
        return self._url

    @property
    def config(self) -> FlexibleSourceConfig:
        """Get the source configuration"""
        return self._config

    # =========================================================================
    # Discovery methods
    # =========================================================================

    def list_ensembles(self, refresh: bool = False) -> list[str]:
        """
        List available ensemble members

        Parameters:
        -----------
        refresh : bool
            If True, rescan cloud storage (bypass cache)

        Returns:
        --------
        List[str] : Available ensemble identifiers
        """
        return self._discover.list_ensembles(refresh=refresh)

    def list_tables(
        self, ensemble: str | None = None, refresh: bool = False
    ) -> list[str]:
        """
        List available tables

        Parameters:
        -----------
        ensemble : str, optional
            Check for specific ensemble (uses current/default if not specified)
        refresh : bool
            If True, rescan cloud storage (bypass cache)

        Returns:
        --------
        List[str] : Available table names
        """
        ens = ensemble or self._kwargs.get("ensemble", self._config.default_ensemble)
        return self._discover.list_tables(ensemble=ens, refresh=refresh)

    def list_variables(
        self,
        ensemble: str | None = None,
        table: str | None = None,
        variant: str | None = None,
        refresh: bool = False,
    ) -> list[str]:
        """
        List available variables

        Parameters:
        -----------
        ensemble : str, optional
            Check for specific ensemble (uses current/default if not specified)
        table : str, optional
            Check for specific table (uses current/default if not specified)
        variant : str, optional
            Check for specific variant (uses current/default if not specified)
        refresh : bool
            If True, rescan cloud storage (bypass cache)

        Returns:
        --------
        List[str] : Available variable names
        """
        ens = ensemble or self._kwargs.get("ensemble", self._config.default_ensemble)
        tbl = table or self._kwargs.get("table", self._config.default_table)
        var = variant or self._kwargs.get("variant", self._config.default_variant)
        return self._discover.list_variables(
            ensemble=ens, table=tbl, variant=var, refresh=refresh
        )

    def discover(self, refresh: bool = False):
        """
        Print a formatted summary of all available data

        Parameters:
        -----------
        refresh : bool
            If True, rescan cloud storage (bypass cache)
        """
        self._discover.print_summary(refresh=refresh)

    def describe(self):
        """Print detailed description of this source"""
        print(self.__repr__())

    def __repr__(self) -> str:
        params_str = ", ".join(f"{k}={v!r}" for k, v in self._kwargs.items())

        lines = [
            f"<FlexibleSource: {self._config.name}>",
            f"  Description: {self._config.description}",
            f"  Parameters: {params_str}" if params_str else "  Parameters: (defaults)",
            f"  Driver: {self._config.driver}",
            f"  Multi-file: {self._config.is_multi_file}",
            f"  URL: {self._url}",
            "",
            "  Methods:",
            "    .to_dask()         - Load lazily with dask",
            "    .read()            - Load into memory",
            "    .list_variables()  - Show available variables",
            "    .list_ensembles()  - Show available ensembles",
            "    .list_tables()     - Show available tables",
            "    .discover()        - Full data summary",
        ]
        return "\n".join(lines)
