# Reflective Data Catalog

[![Reflective](https://img.shields.io/badge/reflective.org-blue?label=🌍)](https://reflective.org)
[![CI](https://img.shields.io/github/actions/workflow/status/ReflectiveCloud/reflective-data-catalog/tests.yml?branch=main)](https://github.com/ReflectiveCloud/reflective-data-catalog/actions)
[![License: Apache-2.0](https://img.shields.io/github/license/ReflectiveCloud/reflective-data-catalog)](https://github.com/ReflectiveCloud/reflective-data-catalog/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/reflective-data-catalog?label=version)](https://pypi.org/project/reflective-data-catalog/)
[![Last Commit](https://img.shields.io/github/last-commit/ReflectiveCloud/reflective-data-catalog)](https://github.com/ReflectiveCloud/reflective-data-catalog/commits/main)


Reflective's unified Python interface for accessing SAI (Stratospheric Aerosol Injection) climate model data across cloud providers (S3, GCS, Azure, Cloudflare R2), for use on the [Reflective Cloud Hub](https://reflective.2i2c.cloud) and anywhere else you run Python.

Every dataset is registered in a single packaged YAML catalog and loaded through one consistent xarray-based interface for browsing, searching, and loading SRM-related datasets. All available datasets [can be seen here](https://docs.google.com/spreadsheets/d/1cjgJQSrDV_IQVN68HoTQpy_xGQQhPy4wz1N0u8E2Pe4/edit?usp=sharing) with more information in [the Reflective Cloud Hub documentation](https://reflectivecloud.github.io/Book/usage_guide/accessing_community_datasets.html). [We've also included an example Jupyter Notebook showing how to use the tool.](./Example.ipynb)

The public ARISE sources work with no credentials at all; sources on the private Reflective hub bucket require AWS credentials (available automatically on the Reflective Cloud Hub). See the [credentials matrix](#credentials) below.

## Installation

```bash
pip install reflective-data-catalog
```

Optional extras add the Google Cloud CMIP6/GeoMIP catalog (via intake-esm) and ESGF access (via intake-esgf) — neither is required for the core catalog:

```bash
pip install "reflective-data-catalog[esm]"    # catalog.esm / catalog.geomip_cloud
pip install "reflective-data-catalog[esgf]"   # catalog.esgf
pip install "reflective-data-catalog[esm,esgf]"
```

For development:

```bash
git clone https://github.com/ReflectiveCloud/reflective-data-catalog.git
cd reflective-data-catalog
pip install -e ".[dev]"
pre-commit install
```

This installs a [pre-commit](https://pre-commit.com/) hook that automatically runs [Ruff](https://docs.astral.sh/ruff/) linting (with auto-fix) and formatting on every commit.

## Quick Start

```python
from reflective_data_catalog import ReflectiveCatalog

rdc = ReflectiveCatalog()

# Public data — works with no credentials at all
ds = rdc.arise_sai_15(variable="TREFHT", time_frequency="month_1").to_dask()

# Public Zarr stores on Cloudflare R2 — also no credentials. Tables and
# realms are Zarr groups; variables are selected from the opened dataset.
ds = rdc.cesm2_waccm_g6_1p5k_hilla(table="Amon", realm="atmos_3d", ensemble="r1").to_dask()
temperature = ds["T"]

# Load into memory instead of lazily
ds = rdc.miroc_es2h_g6_1p5k_sai(table="Mon", ensemble="r01").read()
surface_temp = ds["SurfT"]
```

## Credentials

Three access classes cover every source in the catalog:

| Access class | Credentials needed | Sources |
|---|---|---|
| **Public (anonymous)** | None — works out of the box | The CESM2-WACCM and MIROC-ES2H entries (public Cloudflare R2 Zarr stores: `cesm2_waccm_g6_1p5k_hilla`, `cesm2_waccm_g6_1p5k_sai`, `cesm2_waccm_ssp245`, `miroc_es2h_g6_1p5k_hilla`, `miroc_es2h_g6_1p5k_sai`) and the ARISE entries (`arise_sai_15`, `arise_15_cesm2_waccm_ssp245`, `ukesm1_arise_sai`, `ukesm1_arise_cmip6`) |
| **Reflective hub** (private S3 bucket) | AWS credentials via environment variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) or `~/.aws`; provided automatically on the Reflective Cloud Hub | UKESM1.1, E3SMv3, `cesm2_waccm_historical`, and GAUSS entries |
| **Cloudflare R2 S3 API** (`r2://` URLs) | `CLOUDFLARE_R2_ACCOUNT_ID` (or `CLOUDFLARE_ACCOUNT_ID`) environment variable, plus R2 access keys | No shipped entry needs this — the public R2 stores are served over plain HTTPS; support is built in for future private R2 entries |

Missing credentials raise a `MissingCredentialsError` that names the missing configuration (for example the `CLOUDFLARE_R2_ACCOUNT_ID` environment variable) rather than a provider stack trace.

## Available Sources

All 27 sources come from the packaged catalog file (`src/reflective_data_catalog/data-catalog.yaml`). Entries marked *experimental* are still being populated or verified — see [docs/migration-matrix.md](./docs/migration-matrix.md) for the authoritative stability listing.

| Source | Model | Experiment | Driver | Access | Stability |
|--------|-------|------------|--------|--------|-----------|
| `ukesm1_g6_1p5k_hilla` | UKESM1.1 | G6-1.5K-HiLLA | netcdf | Hub | stable |
| `cesm2_waccm_g6_1p5k_hilla` | CESM2-WACCM | G6-1.5K-HiLLA | zarr | Public | stable |
| `e3smv3_g6_1p5k_hilla` | E3SMv3 | G6-1.5K-HiLLA | netcdf | Hub | stable |
| `miroc_es2h_g6_1p5k_hilla` | MIROC-ES2H | G6-1.5K-HiLLA (`variant=`) | zarr | Public | stable |
| `ukesm1_ssp245` | UKESM1.1 | SSP2-4.5 reference | netcdf | Hub | stable |
| `e3smv3_ssp245` | E3SMv3 | SSP2-4.5 reference | netcdf | Hub | stable |
| `cesm2_waccm_historical` | CESM2-WACCM | Historical (POP ocean) | netcdf | Hub | stable |
| `cesm2_waccm_ssp245` | CESM2-WACCM | SSP2-4.5 (POP ocean) | zarr | Public | stable |
| `miroc_es2h_g6_1p5k_sai` | MIROC-ES2H | G6-1.5K-SAI (`variant=`) | zarr | Public | stable |
| `ukesm1_g6_1p5k_sai` | UKESM1.1 | G6-1.5K-SAI | zarr | Hub | **experimental** |
| `cesm2_waccm_g6_1p5k_sai` | CESM2-WACCM | G6-1.5K-SAI | zarr | Public | stable |
| `e3smv3_g6_1p5k_sai` | E3SMv3 | G6-1.5K-SAI | zarr | Hub | **experimental** |
| `cesm2_waccm6_gauss_historical` | CESM2-WACCM | GAUSS | zarr | Hub | **experimental** |
| `arise_sai_15` | CESM2-WACCM | ARISE-SAI-1.5 | netcdf | Public | stable |
| `arise_15_cesm2_waccm_ssp245` | CESM2-WACCM | SSP2-4.5 (ARISE reference) | netcdf | Public | stable |
| `ukesm1_arise_sai` | UKESM1.0 | ARISE-SAI-1.5 | netcdf | Public | stable |
| `ukesm1_arise_cmip6` | UKESM1.0 | SSP2-4.5 (CMIP6 ScenarioMIP) | netcdf | Public | stable |
| `simulator_cesm2_waccm_ma_0p5k_sai` | CESM2-WACCM-MA | 0.5K-SAI (simulator inputs) | zarr | Public | stable |
| `simulator_cesm2_waccm_ma_1p0k_sai` | CESM2-WACCM-MA | 1.0K-SAI (simulator inputs) | zarr | Public | stable |
| `simulator_cesm2_waccm_ma_1p5k_sai` | CESM2-WACCM-MA | 1.5K-SAI (simulator inputs) | zarr | Public | stable |
| `simulator_cesm2_waccm_ma_baseline` | CESM2-WACCM-MA | baseline (simulator inputs) | zarr | Public | stable |
| `simulator_cesm2_waccm_ma_historical` | CESM2-WACCM-MA | historical (simulator inputs) | zarr | Public | stable |
| `simulator_miroc_es2h_g6_0p5k_sai` | MIROC-ES2H | G6-0.5K-SAI (simulator inputs) | zarr | Public | stable |
| `simulator_miroc_es2h_g6_1p5k_sai` | MIROC-ES2H | G6-1.5K-SAI (simulator inputs) | zarr | Public | stable |
| `simulator_miroc_es2h_baseline` | MIROC-ES2H | baseline (simulator inputs) | zarr | Public | stable |
| `simulator_miroc_es2h_historical` | MIROC-ES2H | historical (simulator inputs) | zarr | Public | stable |
| `simulator_miroc_es2h_ssp245` | MIROC-ES2H | SSP2-4.5 (simulator inputs) | zarr | Public | stable |

The ten `simulator_*` entries are the public simulator-input stores (`simulator-inputs/` on the R2 bucket): grouped Zarr stores of monthly (CESM-MA also daily) 2D atmosphere fields with `table`/`realm` groups (`Mon/atmos_2d` default, plus `atmos_2d_derived` and `atmos_2d_tasminmax`) and a 3-member ensemble selected exactly like the other public CESM/MIROC entries.

## Usage

### Selecting Parameters

Every source takes the canonical keyword arguments `ensemble`, `table`, and `variable`, plus per-source extras such as `variant`, `realm`, `time_frequency`, or `version`. CMIP6-style aliases are accepted permanently: `ensemble_member`/`member_id` → `ensemble`, `table_id` → `table`, `variable_id` → `variable`.

```python
# Canonical kwargs (UKESM HiLLA is NetCDF: UM stream tables + a time segment)
ds = rdc.ukesm1_g6_1p5k_hilla(
    variable="ua", table="ap4", time="AERmon", ensemble="r12i1p1f2"
).to_dask()

# Aliases work identically
ds = rdc.ukesm1_g6_1p5k_hilla(
    variable_id="ua", table_id="ap4", time="AERmon", member_id="r12i1p1f2"
).to_dask()

# Typos raise a TypeError listing the valid parameters — nothing loads silently
rdc.cesm2_waccm_ssp245(varaible="SALT")
# TypeError: cesm2_waccm_ssp245: unknown parameter(s) ['varaible']. ...
```

The CESM2-WACCM and MIROC-ES2H entries open grouped public Zarr stores: `table` and `realm` select the Zarr group, the ensemble is a dataset dimension (`ensemble="all"` keeps every member), and variables are picked from the opened dataset. The MIROC entries additionally take `variant=` — `'baseline'` selects the SSP2-4.5 reference store (the default on the HiLLA entry); the experiment name selects the experiment store:

```python
# SSP2-4.5 reference outputs (the default variant on the HiLLA entry)
ds = rdc.miroc_es2h_g6_1p5k_hilla(table="Mon", ensemble="r01").to_dask()
surface_temp = ds["SurfT"]

# The experiments themselves (the HiLLA experiment store uses
# member-suffixed realm groups — use .discover() to list them)
ds = rdc.miroc_es2h_g6_1p5k_hilla(
    variant="G6-1.5K-HiLLA", table="Amon", realm="atmos_2d_r03"
).to_dask()
ds = rdc.miroc_es2h_g6_1p5k_sai().to_dask()   # variant='G6-1.5K-SAI' default

# The full ten-member ensemble as one dataset
ds = rdc.miroc_es2h_g6_1p5k_sai(ensemble="all").to_dask()
```

### Discovering Available Data

Catalog-level listing and search return structured records; pass `verbose=True` for a printed summary:

```python
records = rdc.list_sources()        # structured records for every source
rdc.list_sources(verbose=True)      # human-readable printout

for rec in rdc.search(term="ukesm"):
    print(rec["name"], rec["kind"])  # every result carries its kind

rdc.list_tags()                      # tags across catalog entries
rdc.get_parameters("arise_sai_15")   # {name, driver, description, parameters}
src = rdc.get_source("arise_sai_15") # string-keyed access to any entry
rdc.help()                           # overview help text
```

Each source scans cloud storage to report what actually exists (an empty scan returns `[]` with a warning — never the parameter defaults):

```python
source = rdc.ukesm1_g6_1p5k_hilla()

source.list_variables()   # observed variables (optionally per ensemble/table)
source.list_ensembles()
source.list_tables()

source.discover()         # dict summary: url + ensembles + tables + variables
```

### Errors

The package raises a typed exception hierarchy: `CatalogError` (bad or unsupported catalog file), `SourceNotFoundError` (unknown source name; subclasses `AttributeError` so `hasattr` and tab-completion keep working), `DataNotFoundError` (a rendered URL matched no data, or matched it impurely), and `MissingCredentialsError` (names the missing credential). Calls that use pre-1.0 parameter vocabulary raise errors that carry the old→new guidance from the migration matrix.

### Google Cloud CMIP6 / GeoMIP (`[esm]` extra)

With `pip install "reflective-data-catalog[esm]"`, access cloud-optimized Zarr data from the Google Cloud CMIP6 catalog:

```python
# Search and load in one step
datasets = rdc.esm.load(
    experiment_id=["G6sulfur", "ssp245", "ssp585"],
    variable_id="tas",
    table_id="Amon",
    require_all_on=["source_id", "institution_id"],
)

# Or use the GeoMIP convenience helper
datasets = rdc.geomip_cloud.load_ensemble(
    experiments=["G6sulfur", "ssp245", "ssp585"],
    variable="tas",
)

# Quick single-experiment load
ds_dict = rdc.geomip_cloud.g6sulfur(variable="tas")

# Explore what's available
rdc.geomip_cloud.list_models()
rdc.geomip_cloud.list_variables(experiment_id="G6sulfur")
rdc.geomip_cloud.summary()

# Advanced: direct search then load
subset = rdc.esm.search(
    experiment_id="G6sulfur",
    variable_id=["tas", "pr"],
    table_id="Amon",
)
datasets = subset.to_dataset_dict()
```

### ESGF Data (`[esgf]` extra)

With `pip install "reflective-data-catalog[esgf]"`, the catalog also provides access to ESGF (Earth System Grid Federation) data:

```python
ds = rdc.esgf.geomip.g6sulfur(model="UKESM1-0-LL", variable="tas")
```

## Migrating from 0.x

**Mid-analysis and need the old behavior right now?** Pin below 1.0:

```bash
pip install "reflective-data-catalog<1"
```

v1.0 replaces the pre-1.0 dual registration system (flexible source configs plus an intake catalog) with a single packaged YAML catalog and a self-parsed loader. The 8 documented source names are unchanged. What did change:

- **One registration mechanism.** All sources live in `data-catalog.yaml`; the flexible-sources system (`FlexibleSourceConfig`, `reflective_data.py`) is gone. `intake` is no longer a runtime dependency — `intake-esm`/`intake-esgf` moved behind the `[esm]`/`[esgf]` extras.
- **Canonical kwargs plus permanent aliases.** `ensemble`/`table`/`variable` are canonical; `ensemble_member`, `member_id`, `table_id`, and `variable_id` are accepted forever.
- **Typos now error.** Unknown keyword arguments raise `TypeError` listing the valid parameters. Previously they were silently ignored and the defaults loaded.
- **MIROC uses `variant=`.** The old separate MIROC SSP2-4.5 sources were absorbed into the two MIROC entries as `variant='baseline'` (the default on the HiLLA entry).
- **Both UKESM hub entries (`ukesm1_ssp245`, `ukesm1_g6_1p5k_hilla`) stay NetCDF** in their pre-1.0 stream/time layouts — UM stream `table=` values (`ap4`..`onm`), the `time=` parameter, and the old defaults all keep working unchanged.
- **Parameter value vocabularies changed with the Zarr switches (CESM/MIROC).** Old table values (e.g. `table='AMON'`) no longer match the Zarr groups (`Amon`), and variables are selected from the opened dataset instead of the path. Old values are never silently translated — they raise an error carrying the old→new mapping. The NetCDF-preserving entries (UKESM, E3SM, `cesm2_waccm_historical`) keep their old vocabularies; E3SM variables stay E3SM-native (`T`, `TREFHT` — there is no `tas`).
- **Structured results and typed errors.** `list_sources()`/`list_tags()`/`search()` return records (printing behind `verbose=True`); `get_source_config()` is replaced by `get_source()` and `get_parameters()`; unknown sources raise `SourceNotFoundError`.

The full old→new table — source by source, kwarg by kwarg, default by default — is in [docs/migration-matrix.md](./docs/migration-matrix.md), rendered from the machine-readable `migration_matrix.yaml` that ships inside the package.

## Running Tests

Run the full test suite:

```bash
pytest
```

Run with coverage report:

```bash
pytest --cov=reflective_data_catalog --cov-report=term-missing
```

Run a specific test file:

```bash
pytest tests/test_catalog.py
pytest tests/test_catalog_entries.py   # instantiates every shipped catalog entry
```

Tests use the real packaged catalog and mock storage I/O only — no network access or cloud credentials are required.

## Requirements

Python >= 3.11. Runtime dependencies (and the `esm`, `esgf`, and `dev` extras) are declared in [`pyproject.toml`](./pyproject.toml) — that file is the single source of truth for versions.

## License

Apache 2.0
