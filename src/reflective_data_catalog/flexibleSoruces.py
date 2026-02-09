from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass(frozen=True)
class FlexibleSourceConfig:
    """
    Immutable configuration for a flexible data source.
    
    This dataclass defines the structure for accessing climate data
    stored on S3 with flexible table/variable combinations.
    
    Attributes:
    -----------
    name : str
        Unique identifier for this source (used as catalog.name())
    base : str
        Base S3 path (e.g., 's3://bucket/model/experiment')
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
    filename_pattern: Optional[str] = None
    table_mapping: Dict[str, str] = field(default_factory=dict)
    default_table: str = 'Amon'
    default_variable: str = 'tas'
    default_ensemble: str = 'r1i1p1f1'
    default_time: Optional[str] = None
    driver: str = 'netcdf'
    combine_files: str = 'by_coords'
    concat_dim: str = 'time'
    description: str = ''
    
    @property
    def defaults(self) -> Dict[str, str]:
        """Get defaults as a dictionary for compatibility"""
        d = {
            'table': self.default_table,
            'variable': self.default_variable,
            'ensemble': self.default_ensemble,
        }
        if self.default_time is not None:
            d['time'] = self.default_time
        return d
    
    @property
    def available_tables(self) -> List[str]:
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
        return '*' in self.filename_pattern or '?' in self.filename_pattern
    
    def build_directory_path(self, **kwargs) -> str:
        """
        Build the S3 directory path for this source
        
        Parameters:
        -----------
        **kwargs : dict
            Override parameters (table, variable, ensemble)
        
        Returns:
        --------
        str : S3 directory path
        """
        # Apply defaults, then override with provided kwargs
        table = kwargs.get('table', self.default_table)
        variable = kwargs.get('variable', self.default_variable)
        ensemble = kwargs.get('ensemble', kwargs.get('ensemble_member', self.default_ensemble))
        
        # Map table to path
        table_path = self.table_mapping.get(table, table)
        
        time = kwargs.get('time', self.default_time or '')
        
        # Build directory path
        return self.pattern.format(
            base=self.base,
            ensemble=ensemble,
            table_path=table_path,
            variable=variable,
            table=table,
            time=time
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
            variable = kwargs.get('variable', self.default_variable)
            return f"{variable}.nc"
        
        table = kwargs.get('table', self.default_table)
        variable = kwargs.get('variable', self.default_variable)
        ensemble = kwargs.get('ensemble', kwargs.get('ensemble_member', self.default_ensemble))
        
        time = kwargs.get('time', self.default_time or '')
        
        # Replace placeholders but keep wildcards
        return self.filename_pattern.format(
            variable=variable,
            table=table,
            ensemble=ensemble,
            time=time
        )
    
    def build_url(self, **kwargs) -> str:
        """
        Build the complete S3 URL or glob pattern for this source
        
        Parameters:
        -----------
        **kwargs : dict
            Override parameters (table, variable, ensemble)
        
        Returns:
        --------
        str : Complete S3 URL (may include wildcards for multi-file sources)
        """
        directory = self.build_directory_path(**kwargs)
        filename = self.build_filename_glob(**kwargs)
        
        # Ensure proper path joining
        if directory.endswith('/'):
            return f"{directory}{filename}"
        else:
            return f"{directory}/{filename}"
    
    def validate(self) -> List[str]:
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
            errors.append("base S3 path is required")
        if not self.pattern:
            errors.append("URL pattern is required")
        if not self.base.startswith('s3://'):
            errors.append("base must be an S3 path (s3://...)")
        if self.driver not in ('netcdf', 'zarr'):
            errors.append(f"driver must be 'netcdf' or 'zarr', got '{self.driver}'")
        if self.combine_files not in ('by_coords', 'nested', 'first'):
            errors.append(f"combine_files must be 'by_coords', 'nested', or 'first'")
        
        # Check filename_pattern has required placeholder
        if self.filename_pattern is not None:
            if '{variable}' not in self.filename_pattern and '{variable}' not in self.pattern:
                errors.append("Either pattern or filename_pattern must contain {variable}")
        elif '{variable}' not in self.pattern:
            errors.append("pattern must contain {variable} when no filename_pattern is set")
        
        return errors


class SourceDiscovery:
    """
    Discovery utilities for finding available data in S3.
    
    This class provides methods to scan S3 and discover what 
    variables, ensembles, and tables are actually available.
    """
    
    def __init__(self, config: FlexibleSourceConfig):
        self.config = config
        self._fs = None
        self._cache: Dict[str, Any] = {}
    
    @property
    def fs(self):
        """Lazy initialization of S3 filesystem"""
        if self._fs is None:
            try:
                import s3fs
                self._fs = s3fs.S3FileSystem(anon=False)
            except ImportError:
                raise ImportError(
                    "s3fs is required for S3 discovery. "
                    "Install with: pip install s3fs"
                )
        return self._fs
    
    def clear_cache(self):
        """Clear the discovery cache"""
        self._cache = {}
    
    def list_ensembles(self, refresh: bool = False) -> List[str]:
        """
        Discover available ensemble members by scanning S3
        
        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan S3
        
        Returns:
        --------
        List[str] : Available ensemble member identifiers
        """
        cache_key = 'ensembles'
        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]
        
        # Parse the pattern to find where {ensemble} appears
        # Typically: {base}/{ensemble}/...
        pattern = self.config.pattern
        base = self.config.base
        
        if '{ensemble}' not in pattern:
            # No ensemble dimension in this source
            return [self.config.default_ensemble]
        
        # Find the path up to {ensemble}
        pattern_parts = pattern.replace('{base}', '').strip('/').split('/')
        ensemble_depth = None
        for i, part in enumerate(pattern_parts):
            if '{ensemble}' in part:
                ensemble_depth = i
                break
        
        if ensemble_depth is None:
            return [self.config.default_ensemble]
        
        # List directories at the ensemble level
        search_path = base.replace('s3://', '')
        for i in range(ensemble_depth):
            part = pattern_parts[i]
            if '{' not in part:
                search_path = f"{search_path}/{part}"
        
        try:
            print(f"Scanning for ensembles in: s3://{search_path}/")
            contents = self.fs.ls(search_path, detail=True)
            
            ensembles = []
            for item in contents:
                if item['type'] == 'directory':
                    name = item['name'].split('/')[-1]
                    # Filter out hidden directories
                    if not name.startswith('.'):
                        ensembles.append(name)
            
            ensembles = sorted(ensembles)
            self._cache[cache_key] = ensembles
            return ensembles
        
        except Exception as e:
            print(f"Warning: Could not list ensembles: {e}")
            return [self.config.default_ensemble]
    
    def list_tables(self, ensemble: Optional[str] = None, refresh: bool = False) -> List[str]:
        """
        Discover available tables by scanning S3
        
        Parameters:
        -----------
        ensemble : str, optional
            Ensemble to check (uses default if not specified)
        refresh : bool
            If True, bypass cache and rescan S3
        
        Returns:
        --------
        List[str] : Available table names
        """
        ensemble = ensemble or self.config.default_ensemble
        cache_key = f'tables_{ensemble}'
        
        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]
        
        # If we have explicit table mapping, check which ones exist
        if self.config.table_mapping:
            existing_tables = []
            for table_name, table_path in self.config.table_mapping.items():
                try:
                    dir_path = self.config.build_directory_path(
                        ensemble=ensemble,
                        table=table_name,
                        variable='*'  # Placeholder
                    )
                    # Remove variable part to get table directory
                    dir_path = '/'.join(dir_path.replace('s3://', '').split('/')[:-1])
                    
                    if self.fs.exists(dir_path):
                        existing_tables.append(table_name)
                except Exception:
                    pass
            
            self._cache[cache_key] = sorted(existing_tables)
            return self._cache[cache_key]
        
        # Otherwise, try to discover tables from directory structure
        pattern = self.config.pattern
        if '{table_path}' not in pattern and '{table}' not in pattern:
            return [self.config.default_table]
        
        # Build path up to table level
        try:
            # Replace known values
            partial_path = pattern.format(
                base=self.config.base,
                ensemble=ensemble,
                table_path='*',
                table='*',
                variable='*'
            )
            # Find parent of table
            parts = partial_path.replace('s3://', '').split('/')
            table_idx = None
            for i, p in enumerate(parts):
                if p == '*':
                    table_idx = i
                    break
            
            if table_idx is None:
                return [self.config.default_table]
            
            search_path = '/'.join(parts[:table_idx])
            print(f"Scanning for tables in: s3://{search_path}/")
            
            contents = self.fs.ls(search_path, detail=True)
            tables = []
            for item in contents:
                if item['type'] == 'directory':
                    name = item['name'].split('/')[-1]
                    if not name.startswith('.'):
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
            return list(self.config.table_mapping.keys()) if self.config.table_mapping else [self.config.default_table]
    
    def list_variables(
        self, 
        ensemble: Optional[str] = None,
        table: Optional[str] = None,
        refresh: bool = False
    ) -> List[str]:
        """
        Discover available variables by scanning S3
        
        Parameters:
        -----------
        ensemble : str, optional
            Ensemble to check (uses default if not specified)
        table : str, optional
            Table to check (uses default if not specified)
        refresh : bool
            If True, bypass cache and rescan S3
        
        Returns:
        --------
        List[str] : Available variable names
        """
        ensemble = ensemble or self.config.default_ensemble
        table = table or self.config.default_table
        cache_key = f'variables_{ensemble}_{table}'
        
        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]
        
        # Build directory path
        dir_path = self.config.build_directory_path(
            ensemble=ensemble,
            table=table,
            variable='PLACEHOLDER'
        )
        # Remove the placeholder variable from path
        dir_path = dir_path.rsplit('/', 1)[0] if 'PLACEHOLDER' in dir_path else dir_path
        s3_path = dir_path.replace('s3://', '')
        
        print(f"Scanning for variables in: s3://{s3_path}/")
        
        try:
            # List all files in the directory
            if self.config.filename_pattern:
                # Build glob pattern to find all variables
                # Replace {variable} with * to match any variable
                glob_pattern = self.config.filename_pattern
                glob_pattern = glob_pattern.replace('{variable}', '*')
                glob_pattern = glob_pattern.format(
                    table=table,
                    ensemble=ensemble,
                    variable='*'
                )
                
                full_pattern = f"{s3_path}/{glob_pattern}"
                print(f"Using pattern: s3://{full_pattern}")
                
                files = self.fs.glob(full_pattern)
            else:
                # Simple case: each variable is a file like variable.nc
                files = self.fs.glob(f"{s3_path}/*.nc")
            
            # Extract variable names from filenames
            variables = set()
            for f in files:
                filename = f.split('/')[-1]
                var_name = self._extract_variable_from_filename(filename, table, ensemble)
                if var_name:
                    variables.add(var_name)
            
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
        ensemble: str
    ) -> Optional[str]:
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
        
        Returns:
        --------
        str or None : Extracted variable name
        """
        if self.config.filename_pattern is None:
            # Simple case: variable.nc
            if filename.endswith('.nc'):
                return filename[:-3]
            elif filename.endswith('.zarr'):
                return filename[:-5]
            return None
        
        # Complex case: parse based on pattern
        # Convert pattern to regex
        import re
        
        pattern = self.config.filename_pattern
        # Escape special regex chars except our placeholders
        pattern = pattern.replace('.', r'\.')
        pattern = pattern.replace('*', '.*')
        pattern = pattern.replace('?', '.')
        
        # Replace placeholders with capture groups or literals
        pattern = pattern.replace('{variable}', r'(?P<variable>[^.]+)')
        pattern = pattern.replace('{table}', re.escape(table))
        pattern = pattern.replace('{ensemble}', re.escape(ensemble))
        
        try:
            match = re.match(pattern, filename)
            if match:
                return match.group('variable')
        except Exception:
            pass
        
        return None
    
    def describe(self, refresh: bool = False) -> Dict[str, Any]:
        """
        Get a complete description of available data
        
        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan S3
        
        Returns:
        --------
        Dict with keys: ensembles, tables, variables (nested by ensemble/table)
        """
        result = {
            'name': self.config.name,
            'description': self.config.description,
            'base': self.config.base,
            'driver': self.config.driver,
            'is_multi_file': self.config.is_multi_file,
            'ensembles': [],
            'tables': {},
            'variables': {}
        }
        
        # Get ensembles
        ensembles = self.list_ensembles(refresh=refresh)
        result['ensembles'] = ensembles
        
        # For each ensemble, get tables and variables
        for ensemble in ensembles[:3]:  # Limit to first 3 to avoid too many API calls
            tables = self.list_tables(ensemble=ensemble, refresh=refresh)
            result['tables'][ensemble] = tables
            result['variables'][ensemble] = {}
            
            for table in tables[:5]:  # Limit to first 5 tables
                variables = self.list_variables(
                    ensemble=ensemble, 
                    table=table, 
                    refresh=refresh
                )
                result['variables'][ensemble][table] = variables
        
        return result
    
    def print_summary(self, refresh: bool = False):
        """
        Print a formatted summary of available data
        
        Parameters:
        -----------
        refresh : bool
            If True, bypass cache and rescan S3
        """
        print("="*80)
        print(f"SOURCE: {self.config.name}")
        print("="*80)
        
        if self.config.description:
            print(f"\n{self.config.description}")
        
        print(f"\nBase: {self.config.base}")
        print(f"Driver: {self.config.driver}")
        print(f"Multi-file: {self.config.is_multi_file}")
        
        if self.config.filename_pattern:
            print(f"Filename pattern: {self.config.filename_pattern}")
        
        # Ensembles
        print("\n" + "-"*40)
        print("ENSEMBLES:")
        print("-"*40)
        ensembles = self.list_ensembles(refresh=refresh)
        for ens in ensembles:
            marker = " (default)" if ens == self.config.default_ensemble else ""
            print(f"  • {ens}{marker}")
        
        # Tables
        print("\n" + "-"*40)
        print("TABLES:")
        print("-"*40)
        tables = self.list_tables(refresh=refresh)
        for table in tables:
            marker = " (default)" if table == self.config.default_table else ""
            print(f"  • {table}{marker}")
        
        # Variables (for default ensemble/table)
        print("\n" + "-"*40)
        print(f"VARIABLES (ensemble={self.config.default_ensemble}, table={self.config.default_table}):")
        print("-"*40)
        variables = self.list_variables(refresh=refresh)
        
        # Print in columns
        n_cols = 4
        col_width = 20
        for i in range(0, len(variables), n_cols):
            row = variables[i:i+n_cols]
            print("  " + "".join(v.ljust(col_width) for v in row))
        
        print("\n" + "="*80)


class FlexibleSourceRegistry:
    """
    Protected registry for flexible source configurations.
    
    This class manages FlexibleSourceConfig instances and provides
    controlled access to prevent accidental modification.
    """
    
    def __init__(self):
        self._configs: Dict[str, FlexibleSourceConfig] = {}
    
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
            raise ValueError(f"Invalid configuration for '{config.name}': {', '.join(errors)}")
        
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
    
    def get(self, name: str) -> Optional[FlexibleSourceConfig]:
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
    
    def __init__(self, catalog: 'UnifiedCatalog', config: FlexibleSourceConfig, **kwargs):
        """
        Initialize flexible source
        
        Parameters:
        -----------
        catalog : UnifiedCatalog
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
                self._config,
                lazy=True,
                **self._kwargs
            )
        return self._ds
    
    def read(self):
        """
        Load dataset into memory (matches intake interface)
        
        Returns:
        --------
        xarray.Dataset loaded into memory
        """
        return self._catalog._load_flexible(
            self._config,
            lazy=False,
            **self._kwargs
        )
    
    @property
    def url(self) -> str:
        """Get the S3 URL for this source"""
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
    
    def list_ensembles(self, refresh: bool = False) -> List[str]:
        """
        List available ensemble members
        
        Parameters:
        -----------
        refresh : bool
            If True, rescan S3 (bypass cache)
        
        Returns:
        --------
        List[str] : Available ensemble identifiers
        """
        return self._discover.list_ensembles(refresh=refresh)
    
    def list_tables(self, ensemble: Optional[str] = None, refresh: bool = False) -> List[str]:
        """
        List available tables
        
        Parameters:
        -----------
        ensemble : str, optional
            Check for specific ensemble (uses current/default if not specified)
        refresh : bool
            If True, rescan S3 (bypass cache)
        
        Returns:
        --------
        List[str] : Available table names
        """
        ens = ensemble or self._kwargs.get('ensemble', self._config.default_ensemble)
        return self._discover.list_tables(ensemble=ens, refresh=refresh)
    
    def list_variables(
        self, 
        ensemble: Optional[str] = None,
        table: Optional[str] = None,
        refresh: bool = False
    ) -> List[str]:
        """
        List available variables
        
        Parameters:
        -----------
        ensemble : str, optional
            Check for specific ensemble (uses current/default if not specified)
        table : str, optional
            Check for specific table (uses current/default if not specified)
        refresh : bool
            If True, rescan S3 (bypass cache)
        
        Returns:
        --------
        List[str] : Available variable names
        """
        ens = ensemble or self._kwargs.get('ensemble', self._config.default_ensemble)
        tbl = table or self._kwargs.get('table', self._config.default_table)
        return self._discover.list_variables(ensemble=ens, table=tbl, refresh=refresh)
    
    def discover(self, refresh: bool = False):
        """
        Print a formatted summary of all available data
        
        Parameters:
        -----------
        refresh : bool
            If True, rescan S3 (bypass cache)
        """
        self._discover.print_summary(refresh=refresh)
    
    def describe(self):
        """Print detailed description of this source"""
        print(self.__repr__())
    
    def __repr__(self) -> str:
        params_str = ', '.join(f"{k}={v!r}" for k, v in self._kwargs.items())
        
        lines = [
            f"<FlexibleSource: {self._config.name}>",
            f"  Parameters: {params_str}" if params_str else "  Parameters: (defaults)",
            f"  Driver: {self._config.driver}",
            f"  Multi-file: {self._config.is_multi_file}",
            f"  URL: {self._url}",
            f"",
            f"  Methods:",
            f"    .to_dask()         - Load lazily with dask",
            f"    .read()            - Load into memory",
            f"    .list_variables()  - Show available variables",
            f"    .list_ensembles()  - Show available ensembles", 
            f"    .list_tables()     - Show available tables",
            f"    .discover()        - Full data summary",
        ]
        return '\n'.join(lines)
