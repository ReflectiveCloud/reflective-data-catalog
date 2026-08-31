# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — v1.0.0

The v1.0 migration: one source-registration mechanism, a self-parsed loader,
and a deliberately frozen public API. The full old→new mapping ships in the
package as `migration_matrix.yaml` and is rendered at
[docs/migration-matrix.md](docs/migration-matrix.md). Users mid-analysis can
pin the final pre-migration release: `pip install "reflective-data-catalog<1"`.

### Breaking changes

- The FlexibleSource system is removed (`flexible_sources.py`,
  `reflective_data.py`, `FlexibleSourceConfig`). All sources are registered
  in `data-catalog.yaml` (schema v2) and loaded by a self-parsed loader;
  intake is no longer a runtime dependency.
- The 8 documented source names are unchanged, but the CESM and MIROC
  experiment sources switched backends from NetCDF file sets to public Zarr
  stores; parameter *values* changed with them (e.g. CESM `table='AMON'` →
  `'Amon'`, and variables are selected from the opened dataset instead of
  the path). Old values raise a guidance error carrying the matrix mapping —
  never a silent substitution. UKESM, E3SM, and `cesm2_waccm_historical`
  stay NetCDF with their old vocabularies intact.
- Unknown keyword arguments raise `TypeError` (typos were previously
  silently ignored and loaded default data).
- Both UKESM hub entries (`ukesm1_ssp245`, `ukesm1_g6_1p5k_hilla`) stay
  NetCDF in their pre-1.0 stream/time layouts: UM stream `table=` values
  (ap4..onm), the `time=` kwarg, and the old defaults keep working. MIROC baseline data is `variant='baseline'` on the
  two `miroc_es2h_*` entries; the standalone parenthesized SSP2-4.5 entries
  are absorbed.
- `get_source_config()` and the `is_flexible` key are removed;
  `get_parameters()` unifies on `{name, driver, description, parameters}`.
- `search()`/`list_sources()`/`list_tags()` return structured records;
  printing moved behind `verbose=True` (default on).
- Unknown source names raise `SourceNotFoundError` (an `AttributeError`
  subclass) with close-match suggestions.
- Core dependencies changed: `intake`, `intake-esm`, `intake-esgf` moved out
  of the core install; `catalog.esm` needs
  `pip install "reflective-data-catalog[esm]"`, `catalog.esgf` needs
  `[esgf]`. The load path (`h5netcdf`, `dask`, `zarr`, `s3fs`, `fsspec`,
  `pyyaml`) is now declared — a clean install can actually load data.

### Added

- `catalog.get_source(name)` — string-keyed, typed access to any entry.
- Typed exceptions: `CatalogError`, `SourceNotFoundError`,
  `DataNotFoundError`, `MissingCredentialsError` (names the missing
  `CLOUDFLARE_R2_ACCOUNT_ID` instead of a botocore stack trace).
- Permanent kwarg aliases: `ensemble_member`/`member_id` → `ensemble`,
  `table_id` → `table`, `variable_id` → `variable`.
- Real discovery: `list_variables()`/`list_ensembles()`/`list_tables()` use
  delimiter listings and return what is actually in the bucket; an empty
  scan returns `[]` with a warning — never the parameter default.
- Selection-purity guards: a multi-file open that matches mixed
  ensembles/streams/variants raises instead of silently combining; combined
  time axes are checked for monotonicity.
- Per-entry anonymous access honored end-to-end (public ARISE sources work
  with no credentials); S3 bucket regions resolve automatically.
- CDF-5 NetCDF sources (the E3SM entries) load via the netcdf4 engine with
  a temporary local download — h5netcdf cannot read CDF-5, and netCDF4
  cannot read remote file objects.
- `scripts/bucket_audit.py` (rerunnable bucket inventory) and
  `scripts/equivalence_gate.py` (NetCDF→Zarr equivalence verification with
  partial-upload detection).
- The wheel ships `data-catalog.yaml`, `migration_matrix.yaml`, `py.typed`,
  verified by CI wheel-content checks.

### Fixed

- `read()` on Zarr sources now loads data (previously returned lazy data
  silently).
- `arise_sai_15`: the default parameters could never match a file
  (monthly-stream glob against the 5-daily directory); bucket-verified fix.
- `ukesm1_arise_cmip6`: default version corrected to the only version the
  bucket contains (v20190715).
- Publishing is gated on green tests; TestPyPI publishes only from `main`
  (previously every push to any branch attempted a publish).

## [0.0.5] and earlier

Pre-migration releases carrying the dual flexible-source/intake systems.
