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
    catalog.search(term='G6')
    catalog.search(variable='tas')

    # Get parameters for a source
    catalog.show_parameters('source_name')

    # Load data
    ds = catalog.ukesm1_g6_1p5k_hilla(table='ap5', variable='ua').to_dask()

DISCOVERING AVAILABLE DATA:
--------------------------
    # Get a source reference
    source = catalog.cesm2_waccm_g6_1p5k_hilla()

    # List what's available (scans cloud storage)
    source.list_ensembles()    # Available ensemble members
    source.list_tables()       # Available tables/frequencies
    source.list_variables()    # Available variables

    # Full discovery summary
    source.discover()

FLEXIBLE SOURCES (Data in the Reflective Cloud Hub S3 bucket):
----------------
    # These support any valid table/variable combination
    ds = catalog.ukesm1_g6_1p5k_hilla(
        table='ap5',        # Table / frequency
        variable='ua',      # Any variable in the table
        ensemble='r12i1p1f2' # Ensemble member
    ).to_dask()

    # MIROC: HiLLA and SAI are separate storage prefixes — use the matching source
    ds = catalog.miroc_es2h_g6_1p5k_hilla(
        variable='SurfT',
        variant='baseline',
    ).to_dask()
    ds = catalog.miroc_es2h_g6_1p5k_sai(variable='SurfT').to_dask()

CMIP6/GeoMIP (intake-esm):
---------------------------------------
    # Search and load cloud-optimized Zarr data
    datasets = catalog.esm.load(
        experiment_id=['G6sulfur', 'ssp245'],
        variable_id='tas',
        table_id='Amon',
    )

    # GeoMIP convenience helpers
    ds = catalog.geomip_cloud.g6sulfur(variable='tas')
    ds = catalog.geomip_cloud.load_ensemble(
        experiments=['G6sulfur', 'ssp245', 'ssp585'],
        variable='tas',
    )

    # Explore what's available
    catalog.geomip_cloud.list_models()
    catalog.geomip_cloud.list_variables(experiment_id='G6sulfur')
    catalog.geomip_cloud.summary()

ESGF DATA:
---------
    ds = catalog.esgf.geomip.g6sulfur(model='UKESM1-0-LL', variable='tas')
    ds = catalog.esgf.ssp.ssp245(model='UKESM1-0-LL', variable='tas')
    catalog.esgf.search(project='CMIP6', experiment_id='G6sulfur')

CLOUD STORAGE:
-------------
    Data stored across S3, GCS, Azure, and Cloudflare R2 can be accessed using this Data Catalog.
    The CloudFileSystem auto-detects the provider from the URL scheme:
        s3://  -> AWS S3
        gs://  -> Google Cloud Storage
        az://  -> Azure Blob Storage
        r2://  -> Cloudflare R2

For help with a specific source:
    catalog.help('source_name')
    catalog.show_parameters('source_name')
"""
