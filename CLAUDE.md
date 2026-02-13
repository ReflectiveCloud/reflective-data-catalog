# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this codebase.

## Project Overview

Reflective Data Catalog is a pip-installable Python package that provides a unified interface for accessing SAI (Stratospheric Aerosol Injection) climate model data stored in cloud storage (S3, GCS, Azure). It wraps multiple climate model sources (CESM2-WACCM, MIROC-ES2H, UKESM1, E3SMv3) behind a consistent API.

## Project Structure

- `src/reflective_data_catalog/` — Package source (src layout)
  - `main.py` — `ReflectiveCatalog` class, the main entry point
  - `flexibleSoruces.py` — `FlexibleSourceConfig`, `FlexibleSource`, `SourceDiscovery`, `FlexibleSourceRegistry` classes
  - `reflective_data.py` — `DEFAULT_FLEXIBLE_SOURCES` list of all source configurations
  - `storage.py` — `CloudFileSystem` class wrapping obstore for multi-cloud access
  - `esgf.py` — `ESGFHelper` for ESGF data access
  - `esm.py` — `ESMCatalog` and `GeoMIPCloudHelper` for Google Cloud CMIP6 catalog via intake-esm
  - `help_text.py` — Help text utilities
- `pyproject.toml` — Package metadata, dependencies, and Ruff config

## Key Architecture

- **`FlexibleSourceConfig`** is a frozen dataclass that defines how to build cloud storage paths and filename patterns for each data source. It supports placeholders: `{base}`, `{ensemble}`, `{table_path}`, `{variable}`, `{variant}`, `{time}`, `{ensemble_id}`.
- **`FlexibleSource`** wraps a config and provides `.to_dask()`, `.read()`, `.list_variables()`, `.list_ensembles()`, `.list_tables()`, and `.discover()`.
- **`SourceDiscovery`** handles cloud storage scanning via `obstore` (through `CloudFileSystem`) to discover available data.
- **`CloudFileSystem`** wraps `obstore` to provide a unified API (glob, ls, exists, open) across S3, GCS, Azure, and other cloud providers. It auto-detects the provider from the URL scheme.
- **`ESMCatalog`** provides intake-esm access to the Google Cloud CMIP6 catalog (search, load, list experiments/models/variables).
- **`GeoMIPCloudHelper`** wraps ESMCatalog with GeoMIP-specific convenience methods (g6sulfur, g6solar, load_ensemble).
- **`ReflectiveCatalog`** uses `__getattr__` to dynamically expose registered sources (e.g., `catalog.cesm2_waccm_ssp245()`). Also exposes `catalog.esm` and `catalog.geomip_cloud` for cloud-optimized Zarr access.
- Sources are registered from `DEFAULT_FLEXIBLE_SOURCES` in `reflective_data.py`.

## Common Commands

```bash
# Install in development mode
pip install -e ".[dev]"

# Lint
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Format
ruff format .

# Run tests
pytest
```

## Code Style

- Uses Ruff for linting and formatting (configured in `pyproject.toml`)
- Line length: 88 characters
- Double quotes for strings
- All imports use relative paths within the package (e.g., `from .flexibleSoruces import ...`)

## Important Notes

- Cloud storage access uses `obstore` via the `CloudFileSystem` wrapper — auto-detects provider from URL scheme (s3://, gs://, az://).
- AWS credentials are needed for S3 access; similarly for GCS and Azure.
- Some sources use `ensemble_mapping` to convert ensemble names to IDs in filenames (e.g., `r1` → `001` for CESM2).
- MIROC sources use a `variant` parameter to distinguish between file types (e.g., `baseline` vs `G6-1.5K-SAI`).
- UKESM1 and E3SMv3 sources have `{variable}` in the directory pattern, not just the filename.
