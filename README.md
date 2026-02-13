# Reflective Data Catalog

Reflective's unified Python interface for accessing SAI (Stratospheric Aerosol Injection) climate model data across cloud providers (S3, GCS, Azure).

## Installation

```bash
pip install reflective-data-catalog
```

For development:

```bash
git clone https://github.com/yourusername/reflective-data-catalog.git
cd reflective-data-catalog
pip install -e ".[dev]"
```

## Quick Start

```python
from reflective_data_catalog import ReflectiveCatalog

catalog = ReflectiveCatalog()

# Load a dataset lazily with dask
ds = catalog.cesm2_waccm_g6_1p5k_hilla(variable='T').to_dask()

# Load a dataset into memory
ds = catalog.miroc_es2h_g6_1p5k_sai(variable='SurfT').read()
```

## Available Sources

| Source | Description |
|--------|-------------|
| `cesm2_waccm_g6_1p5k_hilla` | CESM2-WACCM G6-1.5K-HiLLA |
| `cesm2_waccm_historical` | CESM2-WACCM Historical |
| `cesm2_waccm_ssp245` | CESM2-WACCM SSP2-4.5 |
| `cesm2_waccm6_g6_1p5k_hilla` | CESM2-WACCM6 G6-1.5K-HiLLA |
| `e3smv3_g6_1p5k_hilla` | E3SMv3 G6-1.5K-HiLLA |
| `miroc_es2h_g6_1p5k_hilla` | MIROC-ES2H G6-1.5K-HiLLA |
| `miroc_es2h_g6_1p5k_sai` | MIROC-ES2H G6-1.5K-SAI |
| `ukesm1_g6_1p5k_hilla` | UKESM1.1 G6-1.5K-HiLLA |
| `ukesm1_ssp245` | UKESM1.1 SSP2-4.5 |

## Usage

### Selecting Parameters

Each source accepts keyword arguments to select the table, variable, ensemble member, and other parameters:

```python
# Specify variable, table, and ensemble
ds = catalog.cesm2_waccm_g6_1p5k_hilla(
    variable='T',
    table='AMON',
    ensemble='r2'
).to_dask()

# MIROC sources support a variant parameter
ds = catalog.miroc_es2h_g6_1p5k_hilla(
    variable='SurfT',
    variant='G6-1.5K-SAI',
    ensemble='r01'
).to_dask()
```

### Discovering Available Data

Each source provides discovery methods to explore what data is available:

```python
source = catalog.ukesm1_g6_1p5k_hilla()

# List available variables, ensembles, or tables
source.list_variables()
source.list_ensembles()
source.list_tables()

# Print a full summary
source.discover()
```

### Google Cloud CMIP6 / GeoMIP (intake-esm)

Access cloud-optimized Zarr data from the Google Cloud CMIP6 catalog:

```python
# Search and load in one step
datasets = catalog.esm.load(
    experiment_id=['G6sulfur', 'ssp245', 'ssp585'],
    variable_id='tas',
    table_id='Amon',
    require_all_on=['source_id', 'institution_id'],
)

# Or use the GeoMIP convenience helper
datasets = catalog.geomip_cloud.load_ensemble(
    experiments=['G6sulfur', 'ssp245', 'ssp585'],
    variable='tas',
)

# Quick single-experiment load
ds_dict = catalog.geomip_cloud.g6sulfur(variable='tas')

# Explore what's available
catalog.geomip_cloud.list_models()
catalog.geomip_cloud.list_variables(experiment_id='G6sulfur')
catalog.geomip_cloud.summary()

# Advanced: direct search then load
subset = catalog.esm.search(
    experiment_id='G6sulfur',
    variable_id=['tas', 'pr'],
    table_id='Amon',
)
datasets = subset.to_dataset_dict()
```

### ESGF Data

The catalog also provides access to ESGF (Earth System Grid Federation) data:

```python
ds = catalog.esgf.geomip.g6sulfur(model='UKESM1-0-LL', variable='tas')
```

## Requirements

- Python >= 3.11
- intake >= 2.0.0
- intake-esm >= 2025.2.3
- intake-esgf >= 2025.5.9
- xarray >= 2025.01.0
- obstore >= 0.8.0

## License

GPL-3.0
