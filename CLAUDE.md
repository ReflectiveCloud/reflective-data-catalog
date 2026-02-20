# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this codebase.

## Project Overview

Reflective Data Catalog is a pip-installable Python package that provides a unified interface for accessing SAI (Stratospheric Aerosol Injection) climate model data stored in cloud storage (S3, GCS, Azure, Cloudflare R2). It wraps multiple climate model sources (CESM2-WACCM, MIROC-ES2H, UKESM1, E3SMv3) behind a consistent API.

## Project Structure

- `src/reflective_data_catalog/` — Package source (src layout)
  - `main.py` — `ReflectiveCatalog` class, the main entry point
  - `flexibleSources.py` — `FlexibleSourceConfig`, `FlexibleSource`, `SourceDiscovery`, `FlexibleSourceRegistry` classes
  - `reflective_data.py` — `DEFAULT_FLEXIBLE_SOURCES` list of all source configurations
  - `storage.py` — `CloudFileSystem` class wrapping obstore for multi-cloud access
  - `esgf.py` — `ESGFHelper` for ESGF data access
  - `esm.py` — `ESMCatalog` and `GeoMIPCloudHelper` for Google Cloud CMIP6 catalog via intake-esm
  - `help_text.py` — Help text utilities
- `tests/` — Unit tests (pytest)
  - `conftest.py` — Shared fixtures and mocks
  - `test_flexible_sources.py` — FlexibleSourceConfig, Registry, Discovery
  - `test_storage.py` — CloudFileSystem (including R2)
  - `test_esgf.py` — ESGFHelper (mocked)
  - `test_esm.py` — ESMCatalog, GeoMIPCloudHelper (mocked)
  - `test_catalog.py` — ReflectiveCatalog integration
- `pyproject.toml` — Package metadata, dependencies, and Ruff config
- `.github/workflows/tests.yml` — CI: runs tests and coverage on push/PR

## Key Architecture

- **`FlexibleSourceConfig`** is a frozen dataclass that defines how to build cloud storage paths and filename patterns for each data source. It supports placeholders: `{base}`, `{ensemble}`, `{table_path}`, `{variable}`, `{variant}`, `{time}`, `{ensemble_id}`.
- **`FlexibleSource`** wraps a config and provides `.to_dask()`, `.read()`, `.list_variables()`, `.list_ensembles()`, `.list_tables()`, and `.discover()`.
- **`SourceDiscovery`** handles cloud storage scanning via `obstore` (through `CloudFileSystem`) to discover available data.
- **`CloudFileSystem`** wraps `obstore` to provide a unified API (glob, ls, exists, open) across S3, GCS, Azure, Cloudflare R2, and other cloud providers. It auto-detects the provider from the URL scheme (`s3://`, `gs://`, `az://`, `r2://`). R2 support uses `S3Store` with the Cloudflare endpoint.
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

# Run tests with coverage
pytest --cov=reflective_data_catalog --cov-report=term-missing
```

## Code Style

- Uses Ruff for linting and formatting (configured in `pyproject.toml`)
- Line length: 88 characters
- Double quotes for strings
- All imports use relative paths within the package (e.g., `from .flexibleSources import ...`)

## Important Notes

- Cloud storage access uses `obstore` via the `CloudFileSystem` wrapper — auto-detects provider from URL scheme (`s3://`, `gs://`, `az://`, `r2://`).
- Cloudflare R2 uses `r2://` URLs and requires an account ID via `r2_account_id` kwarg or `CLOUDFLARE_R2_ACCOUNT_ID` / `CLOUDFLARE_ACCOUNT_ID` env var.
- AWS credentials are needed for S3 access; similarly for GCS and Azure.
- Google Cloud CMIP6/GeoMIP data is accessible via `catalog.esm` and `catalog.geomip_cloud` (requires `intake-esm`).
- Some sources use `ensemble_mapping` to convert ensemble names to IDs in filenames (e.g., `r1` → `001` for CESM2).
- MIROC sources use a `variant` parameter to distinguish between file types (e.g., `baseline` vs `G6-1.5K-SAI`).
- UKESM1 and E3SMv3 sources have `{variable}` in the directory pattern, not just the filename.
- All external services are mocked in tests — no network or cloud credentials needed to run `pytest`.