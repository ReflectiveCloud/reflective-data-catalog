from src.reflective_data_catalog.esgf import ESGFHelper
from src.reflective_data_catalog.flexibleSoruces import FlexibleSourceRegistry, FlexibleSourceConfig, FlexibleSource, SourceDiscovery
from src.reflective_data_catalog.reflective_data import DEFAULT_FLEXIBLE_SOURCES

from typing import List, Dict, Optional
import intake


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
    
    Examples:
    ---------
    # Intake catalog sources
    ds = catalog.ukesm1_g6_1p5k_hilla(variable='tas').to_dask()
    
    # Flexible sources (same interface)
    ds = catalog.ukesm1_g6_1p5k_hilla_flex(table='Aday', variable='tasmax').to_dask()
    ds = catalog.cesm2_waccm_g6_1p5k_hilla_flex(table='Lmon', variable='mrso').read()
    
    # ESGF data
    ds = catalog.esgf.geomip.g6sulfur(model='UKESM1-0-LL', variable='tas')
    """
    
    def __init__(self, catalog_path: str = '/shared/catalogs/climate_catalog.yaml'):
        """
        Initialize unified catalog
        
        Parameters:
        -----------
        catalog_path : str
            Path to the main intake YAML catalog
        """
        self._catalog_path = catalog_path
        self._intake_cat = None
        
        # Initialize helpers
        self.esgf = ESGFHelper()
        
        # Initialize flexible source registry with defaults
        self._flexible_registry = FlexibleSourceRegistry()
        for config in DEFAULT_FLEXIBLE_SOURCES:
            self._flexible_registry.register(config)
    
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
                url_pattern=url,
                config=config,
                lazy=lazy
            )
        else:
            if lazy:
                return self._open_dataset_from_s3_lazy(url, driver=config.driver)
            else:
                return self._open_dataset_from_s3(url, driver=config.driver)
    
    def _open_multi_file_dataset(
        self, 
        url_pattern: str, 
        config: FlexibleSourceConfig,
        lazy: bool = True
    ):
        """
        Open multiple files matching a glob pattern and combine them
        
        Parameters:
        -----------
        url_pattern : str
            S3 URL pattern with wildcards (e.g., 's3://bucket/path/*.nc')
        config : FlexibleSourceConfig
            Source configuration with combine settings
        lazy : bool
            If True, load lazily with dask
        
        Returns:
        --------
        xarray.Dataset
        """
        import xarray as xr
        
        try:
            import s3fs
        except ImportError:
            raise ImportError(
                "s3fs is required to read files from S3. "
                "Install with: pip install s3fs"
            )
        
        fs = s3fs.S3FileSystem(anon=False)
        
        # Convert s3:// URL to path for glob
        s3_pattern = url_pattern.replace('s3://', '')
        
        # Find all matching files
        print(f"  Searching for files matching: {url_pattern}")
        matching_files = fs.glob(s3_pattern)
        
        if not matching_files:
            raise FileNotFoundError(
                f"No files found matching pattern: {url_pattern}"
            )
        
        # Sort files (usually by date in filename)
        matching_files = sorted(matching_files)
        
        print(f"  Found {len(matching_files)} files")
        if len(matching_files) <= 5:
            for f in matching_files:
                print(f"    - s3://{f}")
        else:
            print(f"    - s3://{matching_files[0]}")
            print(f"    - s3://{matching_files[1]}")
            print(f"    ... ({len(matching_files) - 4} more)")
            print(f"    - s3://{matching_files[-2]}")
            print(f"    - s3://{matching_files[-1]}")
        
        # Handle single file case
        if len(matching_files) == 1:
            url = f"s3://{matching_files[0]}"
            if lazy:
                return self._open_dataset_from_s3_lazy(url, driver=config.driver)
            else:
                return self._open_dataset_from_s3(url, driver=config.driver)
        
        # Handle combine_files='first'
        if config.combine_files == 'first':
            url = f"s3://{matching_files[0]}"
            print(f"  Using first file only: {url}")
            if lazy:
                return self._open_dataset_from_s3_lazy(url, driver=config.driver)
            else:
                return self._open_dataset_from_s3(url, driver=config.driver)
        
        # Open and combine multiple files
        print(f"  Combining files using: {config.combine_files} along '{config.concat_dim}'")
        
        # Create file objects for xarray
        file_objects = [fs.open(f's3://{f}', 'rb') for f in matching_files]
        
        try:
            if config.driver == 'netcdf':
                # Use open_mfdataset for combining multiple NetCDF files
                if lazy:
                    ds = xr.open_mfdataset(
                        [fs.open(f, 'rb') for f in matching_files],
                        engine='h5netcdf',
                        combine=config.combine_files,
                        concat_dim=config.concat_dim if config.combine_files == 'nested' else None,
                        chunks='auto',
                        parallel=True
                    )
                else:
                    ds = xr.open_mfdataset(
                        [fs.open(f, 'rb') for f in matching_files],
                        engine='h5netcdf',
                        combine=config.combine_files,
                        concat_dim=config.concat_dim if config.combine_files == 'nested' else None,
                    )
                    ds = ds.load()
                
                return ds
            
            elif config.driver == 'zarr':
                # For zarr, load each and combine manually
                datasets = []
                for f in matching_files:
                    url = f"s3://{f}"
                    ds = xr.open_zarr(url, consolidated=True)
                    datasets.append(ds)
                
                combined = xr.concat(datasets, dim=config.concat_dim)
                
                if not lazy:
                    combined = combined.load()
                
                return combined
            
            else:
                raise ValueError(f"Unknown driver: {config.driver}")
        
        except Exception as e:
            # Clean up file objects on error
            for fo in file_objects:
                try:
                    fo.close()
                except:
                    pass
            raise RuntimeError(
                f"Failed to open and combine files from {url_pattern}. "
                f"Error: {e}"
            )
    
    def _open_dataset_from_s3(self, url, driver='netcdf', **kwargs):
        """
        Open a dataset from S3 using the appropriate driver
        
        Parameters:
        -----------
        url : str
            S3 URL to the dataset
        driver : str
            Data format driver ('netcdf' or 'zarr')
        **kwargs : dict
            Additional arguments passed to the open function
        
        Returns:
        --------
        xarray.Dataset
        """
        import xarray as xr
        
        if driver == 'zarr':
            return xr.open_zarr(url, consolidated=True, **kwargs)
        
        elif driver == 'netcdf':
            # For NetCDF files on S3, we need to use s3fs
            try:
                import s3fs
            except ImportError:
                raise ImportError(
                    "s3fs is required to read NetCDF files from S3. "
                    "Install with: pip install s3fs"
                )
            
            # Create S3 filesystem
            fs = s3fs.S3FileSystem(anon=False)
            
            # Open the file and read with xarray
            try:
                with fs.open(url, 'rb') as f:
                    ds = xr.open_dataset(f, engine='h5netcdf', **kwargs)
                    return ds.load()
            except Exception as e:
                # Try scipy engine as fallback (for NetCDF3 files)
                try:
                    with fs.open(url, 'rb') as f:
                        ds = xr.open_dataset(f, engine='scipy', **kwargs)
                        return ds.load()
                except Exception:
                    raise RuntimeError(
                        f"Failed to open NetCDF file from {url}. "
                        f"Original error: {e}"
                    )
        
        else:
            raise ValueError(
                f"Unknown driver: {driver}. "
                f"Supported drivers: 'netcdf', 'zarr'"
            )
    
    def _open_dataset_from_s3_lazy(self, url, driver='netcdf', **kwargs):
        """
        Open a dataset from S3 lazily (using dask) - for large files
        
        Parameters:
        -----------
        url : str
            S3 URL to the dataset
        driver : str
            Data format driver ('netcdf' or 'zarr')
        **kwargs : dict
            Additional arguments passed to the open function
        
        Returns:
        --------
        xarray.Dataset (with dask arrays)
        """
        import xarray as xr
        
        if driver == 'zarr':
            return xr.open_zarr(url, consolidated=True, **kwargs)
        
        elif driver == 'netcdf':
            try:
                import s3fs
            except ImportError:
                raise ImportError(
                    "s3fs is required to read NetCDF files from S3. "
                    "Install with: pip install s3fs"
                )
            
            fs = s3fs.S3FileSystem(anon=False)
            
            try:
                file_obj = fs.open(url, 'rb')
                ds = xr.open_dataset(
                    file_obj,
                    engine='h5netcdf',
                    chunks='auto',
                    **kwargs
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
        if name.startswith('_'):
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
    
    def __dir__(self) -> List[str]:
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
            'esgf', 'timeseries', 'search', 'list_sources',
            'list_tags', 'help', 'add_source', 'get_parameters',
            'show_parameters', 'remove_source', 'get_source_config'
        ]
        
        return sorted(set(builtin + sources))
    
    def add_source(
        self,
        name: str,
        base: str,
        pattern: str,
        filename_pattern: Optional[str] = None,
        table_mapping: Optional[Dict[str, str]] = None,
        default_table: str = 'Amon',
        default_variable: str = 'tas',
        default_ensemble: str = 'r1i1p1f1',
        driver: str = 'netcdf',
        combine_files: str = 'by_coords',
        concat_dim: str = 'time',
        description: str = ''
    ) -> FlexibleSourceConfig:
        """
        Add a new flexible source
        
        Parameters:
        -----------
        name : str
            Source name (will be accessible as catalog.name)
        base : str
            Base S3 path
        pattern : str
            URL pattern for directory path with placeholders:
            {base}, {ensemble}, {table_path}, {variable}
        filename_pattern : str, optional
            Pattern for matching files. Supports wildcards (* and ?).
            Use {variable}, {table}, {ensemble} as placeholders.
            Examples:
            - '{variable}.nc' (single file)
            - 'model.{variable}.*.nc' (multiple files with date ranges)
            - 'b.e21.*.{variable}.??????-??????.nc' (CESM-style dates)
        table_mapping : dict, optional
            Mapping from table names to paths
        default_table : str
            Default table if not specified
        default_variable : str
            Default variable if not specified
        default_ensemble : str
            Default ensemble member if not specified
        driver : str
            Data format ('netcdf' or 'zarr')
        combine_files : str
            How to combine multiple files: 'by_coords', 'nested', or 'first'
        concat_dim : str
            Dimension to concatenate along (default: 'time')
        description : str
            Human-readable description
        
        Returns:
        --------
        FlexibleSourceConfig : The created configuration
        
        Examples:
        ---------
        # Single file per variable
        catalog.add_source(
            name='my_model_simple',
            base='s3://bucket/model/experiment',
            pattern='{base}/{ensemble}/{table_path}',
            filename_pattern='{variable}.nc',
            driver='netcdf'
        )
        
        # Multiple files per variable (time series split across files)
        catalog.add_source(
            name='my_model_timeseries',
            base='s3://bucket/model/experiment',
            pattern='{base}/{ensemble}/atm/hist',
            filename_pattern='model.cam.h0.{variable}.*.nc',
            combine_files='by_coords',
            concat_dim='time',
            driver='netcdf',
            description='Model output with monthly files'
        )
        
        # Then use it:
        ds = catalog.my_model_timeseries(variable='TREFHT').to_dask()
        """
        config = FlexibleSourceConfig(
            name=name,
            base=base,
            pattern=pattern,
            filename_pattern=filename_pattern,
            table_mapping=table_mapping or {},
            default_table=default_table,
            default_variable=default_variable,
            default_ensemble=default_ensemble,
            driver=driver,
            combine_files=combine_files,
            concat_dim=concat_dim,
            description=description
        )
        
        self._flexible_registry.register(config)
        
        print(f"✓ Added source: {name}")
        print(f"  Pattern: {pattern}")
        if filename_pattern:
            print(f"  Filename pattern: {filename_pattern}")
            if '*' in filename_pattern or '?' in filename_pattern:
                print(f"  Multi-file: Yes (combine={combine_files}, dim={concat_dim})")
        print(f"  Usage: catalog.{name}(table='Amon', variable='tas').to_dask()")
        
        return config
    
    def remove_source(self, name: str) -> bool:
        """
        Remove a flexible source
        
        Parameters:
        -----------
        name : str
            Name of the source to remove
        
        Returns:
        --------
        bool : True if removed, False if not found
        """
        if self._flexible_registry.unregister(name):
            print(f"✓ Removed source: {name}")
            return True
        else:
            print(f"Source '{name}' not found")
            return False
    
    def get_source_config(self, name: str) -> Optional[FlexibleSourceConfig]:
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
    
    def list_sources(self, tag: Optional[str] = None, driver: Optional[str] = None, 
                     include_esgf: bool = False):
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
        print("="*80)
        print("AVAILABLE DATA SOURCES")
        print("="*80)
        print("\nAll sources use the same interface:")
        print("  ds = catalog.source_name(param='value').to_dask()  # Lazy load")
        print("  ds = catalog.source_name(param='value').read()     # Load to memory")
        
        # List flexible sources first
        if len(self._flexible_registry) > 0:
            print("\n" + "-"*80)
            print("FLEXIBLE SOURCES (NetCDF/Zarr on S3)")
            print("-"*80)
            
            for name, config in sorted(self._flexible_registry.items()):
                if driver and config.driver != driver:
                    continue
                
                print(f"\n  {name}")
                if config.description:
                    print(f"    {config.description}")
                print(f"    Driver: {config.driver}")
                print(f"    Defaults: table={config.default_table}, "
                      f"variable={config.default_variable}, "
                      f"ensemble={config.default_ensemble}")
                if config.available_tables:
                    print(f"    Tables: {', '.join(config.available_tables)}")
                if config.is_multi_file:
                    print(f"    Multi-file: Yes (combine={config.combine_files}, "
                          f"concat_dim={config.concat_dim})")
                if config.filename_pattern:
                    print(f"    Filename pattern: {config.filename_pattern}")
        
        # List intake catalog sources
        try:
            cat = self._get_intake_catalog()
            
            print("\n" + "-"*80)
            print("INTAKE CATALOG SOURCES")
            print("-"*80)
            
            for name in sorted(cat):
                entry = cat._entries[name]
                
                metadata = entry._metadata if hasattr(entry, '_metadata') else {}
                tags = metadata.get('tags', [])
                drv = entry._driver if hasattr(entry, '_driver') else 'unknown'
                desc = entry._description if hasattr(entry, '_description') else ''
                
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
        
        print("\n" + "="*80)
        
        # Add ESGF sources if requested
        if include_esgf:
            print("\n" + "="*80)
            print("ESGF DATA SOURCES (via catalog.esgf)")
            print("="*80)
            
            print("\nGeoMIP Experiments (catalog.esgf.geomip):")
            print("  - g6sulfur(model='UKESM1-0-LL', variable='tas')")
            print("  - g6solar(model='UKESM1-0-LL', variable='tas')")
            
            print("\nCMIP6 SSP Scenarios (catalog.esgf.ssp):")
            print("  - ssp126/ssp245/ssp585(model='...', variable='...')")
            
            print("\nDirect search:")
            print("  catalog.esgf.search(project='CMIP6', experiment_id='...')")
            
            print("\n" + "="*80)
    
    def list_tags(self):
        """List all unique tags in the intake catalog"""
        cat = self._get_intake_catalog()
        
        all_tags = set()
        for name in cat:
            entry = cat._entries[name]
            metadata = entry._metadata if hasattr(entry, '_metadata') else {}
            tags = metadata.get('tags', [])
            all_tags.update(tags)
        
        print("Available tags:")
        for tag in sorted(all_tags):
            print(f"  - {tag}")
    
    def search(self, term: str) -> List[str]:
        """
        Search catalog by name, description, or tags
        
        Parameters:
        -----------
        term : str
            Search term (case-insensitive)
        
        Returns:
        --------
        list : Matching source names
        """
        term = term.lower()
        matches = []
        
        print("="*80)
        print(f"SEARCH RESULTS: '{term}'")
        print("="*80)
        
        # Search flexible registry
        for name, config in self._flexible_registry.items():
            if term in name.lower():
                matches.append(name)
                print(f"\n{name} [flexible]")
                if config.description:
                    print(f"  {config.description}")
                continue
            
            if config.description and term in config.description.lower():
                matches.append(name)
                print(f"\n{name} [flexible]")
                print(f"  {config.description}")
        
        # Search intake catalog
        try:
            cat = self._get_intake_catalog()
            
            for name in cat:
                if name in matches:
                    continue
                
                entry = cat._entries[name]
                
                if term in name.lower():
                    matches.append(name)
                    desc = entry._description if hasattr(entry, '_description') else ''
                    print(f"\n{name} [intake]")
                    if desc:
                        print(f"  {desc[:70]}...")
                    continue
                
                if hasattr(entry, '_description'):
                    if term in entry._description.lower():
                        matches.append(name)
                        print(f"\n{name} [intake]")
                        print(f"  {entry._description[:70]}...")
                        continue
                
                metadata = entry._metadata if hasattr(entry, '_metadata') else {}
                tags = metadata.get('tags', [])
                if any(term in tag.lower() for tag in tags):
                    matches.append(name)
                    desc = entry._description if hasattr(entry, '_description') else ''
                    print(f"\n{name} [intake]")
                    if desc:
                        print(f"  {desc[:70]}...")
        
        except Exception:
            pass
        
        if not matches:
            print(f"\nNo matches found for '{term}'")
        
        print("\n" + "="*80)
        print(f"Found {len(matches)} matches")
        
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
                'has_parameters': True,
                'is_flexible': True,
                'is_multi_file': config.is_multi_file,
                'parameters': {
                    'table': {
                        'type': 'str',
                        'default': config.default_table,
                        'allowed': config.available_tables or None,
                        'description': 'CMIP6 table / frequency'
                    },
                    'variable': {
                        'type': 'str',
                        'default': config.default_variable,
                        'allowed': None,
                        'description': 'Variable name'
                    },
                    'ensemble': {
                        'type': 'str',
                        'default': config.default_ensemble,
                        'allowed': None,
                        'description': 'Ensemble member'
                    }
                },
                'driver': config.driver,
                'filename_pattern': config.filename_pattern,
                'combine_files': config.combine_files if config.is_multi_file else None,
                'concat_dim': config.concat_dim if config.is_multi_file else None,
                'description': config.description
            }
        
        # Check intake catalog
        try:
            cat = self._get_intake_catalog()
            
            if source_name not in cat:
                raise ValueError(f"Source '{source_name}' not found")
            
            entry = cat._entries[source_name]
            
            params = None
            if hasattr(entry, '_params') and 'parameters' in entry._params:
                params = entry._params['parameters']
            elif hasattr(entry, '_user_parameters'):
                params = entry._user_parameters
            
            if params is None:
                return {
                    'has_parameters': False,
                    'message': f"Source '{source_name}' has no parameters"
                }
            
            param_info = {
                'has_parameters': True,
                'is_flexible': False,
                'parameters': {}
            }
            
            for param_name, param_config in params.items():
                param_info['parameters'][param_name] = {
                    'type': param_config.get('type', 'unknown'),
                    'default': param_config.get('default', None),
                    'allowed': param_config.get('allowed', None),
                    'description': param_config.get('description', '')
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
            If True, scan S3 to show actually available ensembles, tables, 
            and variables (slower but more accurate)
        """
        try:
            param_info = self.get_parameters(source_name)
        except ValueError as e:
            print(f"Error: {e}")
            return
        
        if not param_info.get('has_parameters'):
            print(f"Source '{source_name}' has no parameters")
            return
        
        print("="*80)
        print(f"PARAMETERS: {source_name}")
        print("="*80)
        
        if param_info.get('description'):
            print(f"\n{param_info['description']}")
        
        if param_info.get('is_flexible'):
            print(f"\n[Flexible source - driver: {param_info.get('driver', 'netcdf')}]")
            if param_info.get('is_multi_file'):
                print(f"[Multi-file source - combine: {param_info.get('combine_files')}, "
                      f"concat_dim: {param_info.get('concat_dim')}]")
        
        print("\n" + "-"*40)
        print("PARAMETERS:")
        print("-"*40)
        
        for param_name, info in param_info['parameters'].items():
            print(f"\n  {param_name}:")
            print(f"    Default: {info['default']}")
            if info.get('description'):
                print(f"    Description: {info['description']}")
            if info.get('allowed'):
                allowed = info['allowed']
                if len(allowed) <= 10:
                    print(f"    Allowed: {allowed}")
                else:
                    print(f"    Allowed: {allowed[:5]} ... ({len(allowed)} total)")
        
        # If discover=True and this is a flexible source, scan S3
        if discover and param_info.get('is_flexible'):
            config = self._flexible_registry.get(source_name)
            if config:
                discovery = SourceDiscovery(config)
                
                print("\n" + "-"*40)
                print("AVAILABLE DATA (from S3 scan):")
                print("-"*40)
                
                # Ensembles
                try:
                    ensembles = discovery.list_ensembles()
                    print(f"\n  Ensembles ({len(ensembles)}):")
                    if len(ensembles) <= 10:
                        for ens in ensembles:
                            marker = " (default)" if ens == config.default_ensemble else ""
                            print(f"    • {ens}{marker}")
                    else:
                        for ens in ensembles[:5]:
                            marker = " (default)" if ens == config.default_ensemble else ""
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
                    print(f"\n  Variables in {config.default_table} ({len(variables)}):")
                    if len(variables) <= 20:
                        # Print in columns
                        n_cols = 4
                        col_width = 18
                        for i in range(0, len(variables), n_cols):
                            row = variables[i:i+n_cols]
                            print("    " + "".join(v.ljust(col_width) for v in row))
                    else:
                        # Print first 16 with "and X more"
                        n_cols = 4
                        col_width = 18
                        for i in range(0, 16, n_cols):
                            row = variables[i:i+n_cols]
                            print("    " + "".join(v.ljust(col_width) for v in row))
                        print(f"    ... and {len(variables) - 16} more")
                except Exception as e:
                    print(f"\n  Variables: Could not scan ({e})")
        
        elif param_info.get('is_flexible') and not discover:
            print("\n" + "-"*40)
            print("TIP: Use discover=True to scan S3 for available data:")
            print(f"  catalog.show_parameters('{source_name}', discover=True)")
            print("-"*40)
        
        print("\n" + "="*80)
        print(f"Usage: catalog.{source_name}(param='value').to_dask()")
        print("="*80)
    
    def help(self, source_name=None):
        """
        Show help for the catalog or a specific source
        
        Parameters:
        -----------
        source_name : str, optional
            Name of source to get help for
        """
        if source_name is None:
            print("""
UNIFIED CLIMATE DATA CATALOG
=============================

All sources use the same interface:

    ds = catalog.source_name(param='value').to_dask()  # Lazy loading with dask
    ds = catalog.source_name(param='value').read()     # Load into memory

QUICK START:
-----------
    from climate_catalog import catalog
    
    # List all sources
    catalog.list_sources()
    
    # Search for data
    catalog.search('G6')
    
    # Get parameters for a source
    catalog.show_parameters('source_name')
    
    # Load data
    ds = catalog.ukesm1_g6_1p5k_hilla_flex(table='Amon', variable='tas').to_dask()

DISCOVERING AVAILABLE DATA:
--------------------------
    # Get a source reference
    source = catalog.cesm2_waccm_g6_1p5k_hilla_flex()
    
    # List what's available (scans S3)
    source.list_ensembles()    # Available ensemble members
    source.list_tables()       # Available tables/frequencies
    source.list_variables()    # Available variables
    
    # Full discovery summary
    source.discover()

FLEXIBLE SOURCES:
----------------
    # These support any valid table/variable combination
    ds = catalog.ukesm1_g6_1p5k_hilla_flex(
        table='Amon',       # Amon, Aday, Lmon, Omon, etc.
        variable='tas',     # Any variable in the table
        ensemble='r1i1p1f2' # Ensemble member
    ).to_dask()

ADDING NEW SOURCES:
------------------
    # Single-file per variable
    catalog.add_source(
        name='my_source',
        base='s3://bucket/path',
        pattern='{base}/{ensemble}/{table_path}',
        filename_pattern='{variable}.nc',
        driver='netcdf'
    )
    
    # Multi-file timeseries (e.g., CESM output)
    catalog.add_source(
        name='my_cesm_source',
        base='s3://bucket/cesm',
        pattern='{base}/{ensemble}/atm/hist',
        filename_pattern='model.h0.{variable}.*.nc',
        combine_files='by_coords',
        concat_dim='time'
    )

ESGF DATA:
---------
    ds = catalog.esgf.geomip.g6sulfur(model='UKESM1-0-LL', variable='tas')
    ds = catalog.esgf.ssp.ssp245(model='UKESM1-0-LL', variable='tas')

For help with a specific source:
    catalog.help('source_name')
    catalog.show_parameters('source_name')
            """)
        else:
            self.show_parameters(source_name)
