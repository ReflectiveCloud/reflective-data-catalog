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
pytest tests/test_flexible_sources.py
pytest tests/test_catalog.py::TestSearch::test_search_by_term
```

All external services (S3, ESGF, intake-esm) are mocked in the test suite — no network access or cloud credentials are needed.

### Writing Tests

- Tests live in `tests/` and use [pytest](https://docs.pytest.org/).
- Shared fixtures and mocks are in `tests/conftest.py`.
- Mock any cloud or network calls; tests must run offline.
- Aim for one test file per source module (e.g. `test_storage.py` for `storage.py`).

## Adding a New Data Source

To add a new flexible data source, create a `FlexibleSourceConfig` entry in `src/reflective_data_catalog/reflective_data.py`:

```python
FlexibleSourceConfig(
    name='model_experiment',                    # Snake-case identifier
    base='s3://bucket/path/to/data',            # Cloud storage base URL (s3://, gs://, az://, r2://)
    pattern='{base}/{ensemble}/{table_path}',   # Directory pattern
    filename_pattern='{variable}.*.nc',         # Filename pattern
    table_mapping={'Amon': 'Amon'},             # Table name mapping
    default_table='Amon',
    default_variable='tas',
    default_ensemble='r1i1p1f1',
    driver='netcdf',
    description='Model experiment description'
)
```

The source will automatically be available as `catalog.model_experiment()`.

### Configuration Fields

| Field | Description |
|-------|-------------|
| `name` | Unique snake_case identifier |
| `base` | Cloud storage base URL (`s3://`, `gs://`, `az://`, `r2://`) |
| `pattern` | Directory path template with `{base}`, `{ensemble}`, `{table_path}`, `{variable}`, `{time}` placeholders |
| `filename_pattern` | Filename template with `{variable}`, `{ensemble}`, `{variant}`, `{ensemble_id}`, `{time}`, and `*` wildcards |
| `table_mapping` | Dict mapping table names to S3 directory names |
| `ensemble_mapping` | Optional dict mapping ensemble names to filename IDs (e.g. `{'r1': '001'}`) |
| `default_table` | Default table when none is specified |
| `default_variable` | Default variable when none is specified |
| `default_ensemble` | Default ensemble member |
| `default_variant` | Optional default variant (e.g. `'baseline'`) |
| `default_time` | Optional default time/frequency (e.g. `'AERmon'`) |
| `driver` | `'netcdf'` or `'zarr'` |
| `combine_files` | How to combine multi-file sources: `'by_coords'`, `'nested'`, or `'first'` |
| `concat_dim` | Dimension to concatenate along (default: `'time'`) |
| `description` | Human-readable description |

## Project Structure

```
src/reflective_data_catalog/
├── __init__.py          # Package exports
├── main.py              # ReflectiveCatalog class
├── flexibleSources.py   # FlexibleSourceConfig, FlexibleSource, SourceDiscovery
├── reflective_data.py   # Default source configurations
├── esgf.py              # ESGF data access helper
├── esm.py               # intake-esm Google Cloud CMIP6/GeoMIP access
├── storage.py           # CloudFileSystem (obstore wrapper)
└── help_text.py         # Help text utilities
tests/
├── conftest.py              # Shared fixtures and mocks
├── test_flexible_sources.py # FlexibleSourceConfig, Registry, Discovery
├── test_storage.py          # CloudFileSystem
├── test_esgf.py             # ESGFHelper (mocked)
├── test_esm.py              # ESMCatalog, GeoMIPCloudHelper (mocked)
└── test_catalog.py          # ReflectiveCatalog integration
```

## Reporting Issues

When reporting a bug, please include:

- Python version
- Package version
- Steps to reproduce the issue
- Full error traceback

## License

By contributing, you agree that your contributions will be licensed under the GPL-3.0 license.
