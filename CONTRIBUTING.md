# Contributing to Reflective Data Catalog

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork and clone the repository:

```bash
git clone https://github.com/ReflectiveCloud/reflective-data-catalog.git
cd reflective-data-catalog
```

2. Install in development mode:

```bash
pip install -e ".[dev]"
```

## Development Workflow

1. Create a branch for your work:

```bash
git checkout -b feature/your-feature-name
```

2. Make your changes and ensure they pass linting and tests.

3. Commit your changes with a clear message:

```bash
git commit -m "Add brief description of change"
```

4. Push and open a pull request.

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. Run both before submitting:

```bash
ruff check .
ruff format .
```

Auto-fix lint issues where possible:

```bash
ruff check --fix .
```

Key style rules:

- Line length: 88 characters
- Double quotes for strings
- Space indentation (no tabs)
- Imports sorted with isort rules

## Running Tests

Run the full test suite:

```bash
pytest
```

Run with coverage report:

```bash
pytest --cov=reflective_data_catalog --cov-report=term-missing
```

Run a specific test file or test:

```bash
pytest tests/test_catalog.py
pytest tests/test_catalog_entries.py
pytest tests/test_catalog.py::TestSearch::test_search_by_term
```

Tests use the real packaged `data-catalog.yaml` through the real registration path and mock storage I/O only — no network access or cloud credentials are needed. `tests/test_catalog_entries.py` instantiates every shipped catalog entry unmocked (instantiation renders URLs without opening data, so it runs offline too).

### Writing Tests

- Tests live in `tests/` and use [pytest](https://docs.pytest.org/).
- Shared fixtures and mocks are in `tests/conftest.py`.
- Mock any cloud or network calls; tests must run offline.
- Aim for one test file per source module (e.g. `test_storage.py` for `storage.py`).

## Adding a New Data Source

Sources are registered in one place: `src/reflective_data_catalog/data-catalog.yaml` (entry schema v2). There is no Python configuration to write — add a YAML entry and it is automatically available as `catalog.<entry_name>()`.

### 1. Add the catalog entry

Add an entry under `sources:` following the governed schema:

```yaml
my_model_experiment:
  driver: zarr            # zarr or netcdf — nothing else
  description: "MyModel my-experiment: one-line human description"
  args:
    urlpath: "s3://bucket/path/{{ensemble}}/{{table}}/{{variable}}.zarr"
    consolidated: true    # zarr entries only
    storage_options:
      anon: false         # 'anon' is the ONLY allowed storage_options key
  parameters:
    ensemble:
      description: "Ensemble member identifier"
      type: str
      default: "r1i1p1f1"
    table:
      description: "CMIP6 table (Amon, Lmon, Omon, day, etc.)"
      type: str
      default: "Amon"
    variable:
      description: "Climate variable name"
      type: str
      default: "tas"
  metadata:
    model: "MyModel"
    experiment: "my-experiment"
    tags: ["example"]
```

Schema rules (the loader validates all of these at catalog load and fails fast on violations):

- **`driver`** must be `zarr` or `netcdf`.
- **`args`** allows only: `urlpath`, `combine`, `concat_dim`, `xarray_kwargs`, `storage_options`, and `consolidated` (zarr only). NetCDF entries may use `combine` (`by_coords` or `nested`) with `concat_dim` for multi-file globs, and `xarray_kwargs` (e.g. `engine: h5netcdf`). `urlpath` may be a single template or a list.
- **`storage_options`** allows only `anon`. Endpoints are derived from the URL scheme in code — never entry-supplied, so an entry cannot smuggle in a custom endpoint.
- **Parameter names** use the canonical vocabulary — `ensemble`, `table`, `variable` — plus per-entry extras declared in `parameters` (e.g. `variant`, `realm`, `time_frequency`, `version`). Each parameter takes `type`, `default`, `description`, and optionally an `allowed` list. Users get the aliases (`member_id`, `table_id`, `variable_id`, ...) for free.
- **Custom fields** (`value_map`, `data_access`, `status`, `tags`, papers, buckets, ...) live under the entry's `metadata` block so intake-v1 parsers tolerate the file. `metadata.value_map` declares derived parameters (e.g. `ensemble` → `ensemble_id` filename ids on the CESM2 entries) — derived parameters are set automatically by the loader and cannot be passed by users.

### 2. Verify the entry against the bucket

Run the audit script, which renders every entry's default URL and checks it exists via delimiter listings (read-only credentials suffice; entries your credentials cannot reach are recorded as unverified, not failed):

```bash
python scripts/bucket_audit.py --diff
```

### 3. Add a stability row to the migration matrix

Every catalog entry has a stability disposition (`stable` or `experimental`) in `src/reflective_data_catalog/migration_matrix.yaml` under `stability:`. Add a row for your entry — new or unverified data typically starts `experimental`.

### 4. Run the entry tests

```bash
pytest tests/test_catalog_entries.py
```

This instantiates every catalog entry unmocked through the real registration path, so a schema violation or a broken template fails here before it fails for a user.

## Project Structure

```
src/reflective_data_catalog/
├── __init__.py             # Package exports
├── main.py                 # ReflectiveCatalog class
├── loader.py               # load_catalog() + CatalogSource (self-parsed YAML runtime)
├── exceptions.py           # CatalogError, SourceNotFoundError, DataNotFoundError, MissingCredentialsError
├── storage.py              # CloudFileSystem (obstore wrapper)
├── esgf.py                 # ESGF data access helper ([esgf] extra)
├── esm.py                  # Google Cloud CMIP6/GeoMIP via intake-esm ([esm] extra)
├── help_text.py            # Help text (generated from the loaded catalog)
├── data-catalog.yaml       # THE source registry (schema v2) — ships in the wheel
└── migration_matrix.yaml   # Old→new dispositions + entry stability — ships in the wheel
scripts/
└── bucket_audit.py         # Rerunnable audit of catalog entries against the buckets
tests/
├── conftest.py             # Shared fixtures and mocks
├── test_catalog.py         # ReflectiveCatalog integration
├── test_catalog_entries.py # Instantiates every shipped catalog entry
├── test_storage.py         # CloudFileSystem
├── test_esgf.py            # ESGFHelper (mocked)
└── test_esm.py             # ESMCatalog, GeoMIPCloudHelper (mocked)
```

## Reporting Issues

When reporting a bug, please include:

- Python version
- Package version
- Steps to reproduce the issue
- Full error traceback

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 license.
