HELP_TEXT = """
Reflective DATA CATALOG
=============================

All sources use the same interface:

    ds = catalog.source_name(param='value').to_dask()  # Lazy loading with dask
    ds = catalog.source_name(param='value').read()     # Load into memory

QUICK START:
-----------
    from reflective_data_catalog import ReflectiveCatalog
    
    # List all sources
    catalog = ReflectiveCatalog()
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
"""
