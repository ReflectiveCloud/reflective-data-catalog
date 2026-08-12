"""Help text for ReflectiveCatalog.

The SOURCES section is generated from the loaded catalog so it can never
drift from ``data-catalog.yaml``; only the general usage text is static.
"""

from __future__ import annotations

_GENERAL_TEXT = """
Reflective DATA CATALOG
=============================

All sources use the same interface:

    ds = catalog.source_name(param='value').to_dask()  # Lazy loading with dask
    ds = catalog.source_name(param='value').read()     # Load into memory

QUICK START:
-----------
    from reflective_data_catalog import ReflectiveCatalog

    catalog = ReflectiveCatalog()

    # List all sources (returns records; prints unless verbose=False)
    catalog.list_sources()

    # Search for data
    catalog.search(term='G6')
    catalog.search(variable='tas')

    # Get parameters for a source
    catalog.show_parameters('source_name')
    catalog.get_parameters('source_name')   # same information, as a dict

    # String-keyed access
    src = catalog.get_source('ukesm1_g6_1p5k_hilla', variable='tas')

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

CMIP6/GeoMIP (Google Cloud; needs the [esm] extra):
---------------------------------------------------
    # Search and load cloud-optimized Zarr data
    datasets = catalog.esm.load(
        experiment_id=['G6sulfur', 'ssp245'],
        variable_id='tas',
        table_id='Amon',
    )

    # GeoMIP convenience helpers
    ds = catalog.geomip_cloud.g6sulfur(variable='tas')
    catalog.geomip_cloud.list_models()
    catalog.geomip_cloud.summary()

ESGF DATA (needs the [esgf] extra):
-----------------------------------
    ds = catalog.esgf.geomip.g6sulfur(model='UKESM1-0-LL', variable='tas')
    ds = catalog.esgf.ssp.ssp245(model='UKESM1-0-LL', variable='tas')
    catalog.esgf.search(project='CMIP6', experiment_id='G6sulfur')

CLOUD STORAGE:
-------------
    Data stored across S3, GCS, Azure, and Cloudflare R2 can be accessed
    using this Data Catalog. The CloudFileSystem auto-detects the provider
    from the URL scheme:
        s3://  -> AWS S3
        gs://  -> Google Cloud Storage
        az://  -> Azure Blob Storage
        r2://  -> Cloudflare R2

For help with a specific source:
    catalog.help('source_name')
    catalog.show_parameters('source_name')
"""


def render_help(sources: dict) -> str:
    """Render the catalog help text.

    The general usage text is static; the SOURCES section is built from
    the loaded catalog entries (name plus a one-line description).
    """
    lines = [_GENERAL_TEXT.rstrip(), "", "SOURCES:", "--------"]
    for name in sorted(sources):
        entry = sources[name] or {}
        description = (entry.get("description") or "").strip()
        one_line = description.splitlines()[0] if description else ""
        if len(one_line) > 76:
            one_line = one_line[:73] + "..."
        lines.append(f"    {name}")
        if one_line:
            lines.append(f"        {one_line}")
    lines.append("")
    return "\n".join(lines)
