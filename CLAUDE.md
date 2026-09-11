# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this codebase.

## Project Overview

Reflective Data Catalog is a pip-installable Python package that provides a unified interface for accessing SAI (Stratospheric Aerosol Injection) climate model data stored in cloud storage (S3, GCS, Azure, Cloudflare R2). It wraps multiple climate model sources (CESM2-WACCM, MIROC-ES2H, UKESM1, E3SMv3, ARISE, GAUSS) behind a consistent xarray-based API. All sources are registered in a single packaged YAML catalog and opened by a self-parsed loader — `intake` is not a runtime dependency.

## Project Structure

- `src/reflective_data_catalog/` — Package source (src layout)
  - `main.py` — `ReflectiveCatalog` class, the main entry point
  - `loader.py` — `load_catalog()` (schema validation) and `CatalogSource` (the per-entry runtime: kwargs, URL rendering, open, discovery)
  - `exceptions.py` — Typed exception hierarchy (leaf module; imports nothing package-internal)
  - `storage.py` — `CloudFileSystem` class wrapping obstore for multi-cloud access
  - `esgf.py` — `ESGFHelper` for ESGF data access (`[esgf]` extra)
  - `esm.py` — `ESMCatalog` and `GeoMIPCloudHelper` for Google Cloud CMIP6 catalog via intake-esm (`[esm]` extra)
  - `help_text.py` — Help text, generated from the loaded catalog (not hand-maintained)
  - `data-catalog.yaml` — THE source registry (schema v2, 27 entries); ships in the wheel
  - `migration_matrix.yaml` — Machine-readable old→new dispositions and per-entry stability; ships in the wheel
  - `py.typed` — Ships in the wheel (typed public API)
- `tests/` — Unit tests (pytest)
  - `conftest.py` — Shared fixtures and mocks
  - `test_catalog.py` — ReflectiveCatalog integration
  - `test_catalog_entries.py` — Instantiates every shipped catalog entry unmocked
  - `test_storage.py` — CloudFileSystem (including R2)
  - `test_esgf.py` — ESGFHelper (mocked)
  - `test_esm.py` — ESMCatalog, GeoMIPCloudHelper (mocked)
- `scripts/bucket_audit.py` — Rerunnable audit: renders every entry's default URL and verifies it against the buckets via delimiter listings (read-only credentials suffice); writes `tests/fixtures/bucket_inventory.json`; `--render` regenerates `docs/migration-matrix.md` from the matrix
- `docs/migration-matrix.md` — Rendered from `migration_matrix.yaml`; do not edit by hand
- `pyproject.toml` — Package metadata, dependencies, extras (`esm`, `esgf`, `dev`), and Ruff config
- `.github/workflows/` — CI: tests gate all publishes; TestPyPI from `main` only, PyPI from tags; the release workflow verifies the wheel contains `data-catalog.yaml` and `migration_matrix.yaml`

## Key Architecture

- **`data-catalog.yaml`** is the single registration mechanism. Entries declare `driver: zarr|netcdf`, `args` (allowlist: `urlpath`/`combine`/`concat_dim`/`xarray_kwargs`/`storage_options`/`consolidated`), `parameters` (canonical names `ensemble`/`table`/`variable` plus per-entry extras like `variant`, `realm`, `time_frequency`, `version`), and a `metadata` block for custom fields. `urlpath` templates use `{{param}}` placeholders.
- **`load_catalog()`** (loader.py) parses the file with `yaml.safe_load` only, asserts `metadata.reflective_schema_version` matches `SUPPORTED_SCHEMA_VERSION` (currently 2), and validates every entry — unknown args keys, unknown storage options, or a missing urlpath fail the whole catalog load with `CatalogError`.
- **`CatalogSource`** (loader.py) is one entry bound to resolved parameters and the shared filesystem. It normalizes kwarg aliases (`ensemble_member`/`member_id` → `ensemble`, `table_id` → `table`, `variable_id` → `variable`), raises `TypeError` on unknown kwargs (typos never load defaults silently), derives mapped parameters from `metadata.value_map` (e.g. `ensemble='r1'` → `ensemble_id='001'` on the CESM2 entries; derived params cannot be set directly), and provides `.to_dask()` (lazy), `.read()` (loads), `.url`, `.list_variables()`, `.list_ensembles()`, `.list_tables()`, and `.discover()` (returns a dict; printing is main's job).
- **Opening data**: zarr via `xr.open_zarr` on an fsspec/obstore-translated URL; netcdf via fsspec + h5netcdf, with multi-file glob support (`combine: by_coords|nested`). Multi-file opens are guarded for **selection purity**: a match set that mixes facet values (e.g. two ensembles) or produces a non-monotonic combined time axis raises `DataNotFoundError` instead of silently combining wrong data.
- **Discovery** is delimiter-based: `_scan()` renders the urlpath with a marker at the target parameter, lists one level at that template depth via `CloudFileSystem.ls`, and extracts the observed values. On grouped Zarr entries (where `variable` is not a declared parameter), `list_variables()` enumerates data variables from the store's consolidated metadata: group parameters the caller passes pin their segment, unpinned segments aggregate across groups, and `realm=` pins an exact group. Empty scans return `[]` with a warning — never the parameter defaults. Results are cached per source (pass `refresh=True` to rescan).
- **`CloudFileSystem`** (storage.py) wraps `obstore` (glob, ls, exists, open, `fsspec_info`) across S3, GCS, Azure, Cloudflare R2; auto-detects the provider from the URL scheme (`s3://`, `gs://`, `az://`, `r2://`). Stores are cached keyed on (scheme, bucket, frozen per-entry storage options) so one entry's options can't fix the config for another entry on the same bucket. S3 bucket regions are resolved from the `x-amz-bucket-region` header (obstore doesn't follow cross-region redirects). One named translation point maps fsspec `anon: true` ↔ obstore `skip_signature=True`. `fsspec_info()` is the only fsspec handoff, used at the xarray boundary.
- **`ReflectiveCatalog`** (main.py) loads the catalog **eagerly at construction** — a corrupt catalog fails at `ReflectiveCatalog()` as `CatalogError`. `__getattr__` exposes entries as callables (e.g. `catalog.cesm2_waccm_ssp245(variable=...)`); `get_source(name)` gives string-keyed access; `list_sources()`/`list_tags()`/`search()` return structured records (printing behind `verbose=True`; every search result carries its `kind`); `get_parameters(name)` returns `{name, driver, description, parameters}`. Also exposes `catalog.esm` / `catalog.geomip_cloud` (Google Cloud CMIP6 Zarr) and `catalog.esgf`.
- **Exceptions** (exceptions.py): `CatalogError` (base), `SourceNotFoundError` (subclasses `AttributeError` so `hasattr`/tab-completion keep working), `DataNotFoundError`, `MissingCredentialsError`. Import direction is `exceptions <- storage <- loader <- main` — no back-edges.

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

# Instantiate every shipped catalog entry (offline)
pytest tests/test_catalog_entries.py

# Audit catalog entries against the buckets (needs read-only credentials)
python scripts/bucket_audit.py --diff
```

## Code Style

- Uses Ruff for linting and formatting (configured in `pyproject.toml`)
- Line length: 88 characters
- Double quotes for strings
- All imports use relative paths within the package (e.g., `from .loader import CatalogSource`)

## Important Notes

- The catalog is parsed with `yaml.safe_load` only — never `yaml.load`.
- The loader asserts the catalog schema version (`metadata.reflective_schema_version: 2`); bump `SUPPORTED_SCHEMA_VERSION` deliberately and in step with the file.
- Endpoint smuggling is rejected by design: `storage_options` allows only `anon`; endpoints are always derived in code from the URL scheme, never entry-supplied.
- `intake` is not a runtime dependency. `intake-esm`/`intake-esgf` are reachable only via the `[esm]`/`[esgf]` extras (`catalog.esm`, `catalog.geomip_cloud`, `catalog.esgf`).
- Canonical kwargs are `ensemble`/`table`/`variable` with permanent aliases (`ensemble_member`, `member_id`, `table_id`, `variable_id`). Unknown kwargs raise `TypeError`. Old (pre-1.0) parameter values are never silently translated — they raise guidance errors rendered from `migration_matrix.yaml`, which is the single owner of old→new dispositions.
- MIROC-ES2H registers two entries: `miroc_es2h_g6_1p5k_hilla` and `miroc_es2h_g6_1p5k_sai`, each taking `variant=`. `variant='baseline'` selects the SSP2-4.5 reference outputs under that experiment prefix (the default on the HiLLA entry; the old standalone MIROC ssp245 sources were absorbed as this variant). Do not use `variant='G6-1.5K-SAI'` on the HiLLA entry — the SAI experiment lives under a different prefix; use `miroc_es2h_g6_1p5k_sai`.
- Both UKESM hub entries stay NetCDF in their pre-1.0 stream/time layouts (`ukesm1_ssp245` under `SSP245`, `ukesm1_g6_1p5k_hilla` under `G6-1p5K-HiLLA` — 1p5K spelling); the `time=` kwarg and UM stream `table=` values (ap4..onm) are retained on both. On `ukesm1_ssp245` the filename member label can differ from the directory member (r12i1p1f1 dir, r12i1p1f2 filenames), so the entry globs the filename member. CESM/MIROC `table='AMON'`-style vocabulary changed with the Zarr switches. Both e3smv3 entries are NetCDF-only on the hub (CDF-5 files under `{{variable}}/gn/<version>/`, opened via netCDF4 with a temporary local download) and keep E3SM-native variable names (`T`, `TREFHT` — no `tas`) — see `docs/migration-matrix.md`.
- Entry stability (`stable`/`experimental`) lives in `migration_matrix.yaml`. The three `*_g6_1p5k_sai` entries and `cesm2_waccm6_gauss_historical` (GAUSS) are experimental.
- Credentials: the four ARISE entries are public (`anon: true`); the Reflective hub bucket (`s3://reflective-persistent-prod-large`) needs AWS credentials (env or `~/.aws`); `r2://` URLs need `CLOUDFLARE_R2_ACCOUNT_ID` (or `CLOUDFLARE_ACCOUNT_ID`) — missing credentials raise `MissingCredentialsError` naming the fix.
- CESM2-WACCM historical/ssp245 derive `ensemble_id` filename ids from `ensemble` via `metadata.value_map` (`r1` → `001`); users cannot pass `ensemble_id` directly.
- Tests use the real packaged `data-catalog.yaml` through the real registration path and mock storage I/O only; `pytest` needs no network or cloud credentials.
- The wheel ships `data-catalog.yaml`, `migration_matrix.yaml`, and `py.typed`; publishes are gated on green tests (TestPyPI from `main`, PyPI from tags).
