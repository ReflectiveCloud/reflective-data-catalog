# Runtime spike decision record (plan U3)

Date: 2026-08-12. Both candidates were scored on the pinned six-criterion
rubric from the migration plan, against the schema-v2 catalog, before either
score was compared. Environments: candidate A in a clean venv
(`/tmp/spike-intake`, Python 3.13.11); candidate B in the dev environment
(Python 3.13.11). Python 3.11 was not available on the spike machine — the
CI matrix (3.11/3.12/3.13) covers that gap from U7 onward.

## Decision

**The self-parsed loader (`reflective_data_catalog/loader.py`) is the v1.0
runtime.** intake leaves the load path entirely; it remains only as a
transitive dependency of the optional `[esm]` extra (intake-esm). The YAML
file stays an intake-v1-compatible subset (KTD8), verified by an
extras-gated smoke test.

## Scores

| Criterion | A: intake 2.0.9 + intake-xarray 2.0.0 | B: self-parsed loader |
|---|---|---|
| 1. Enumeration | PASS (17 entries listed) | PASS (17 entries, schema-validated) |
| 2. Golden rendering (default + override) | FAIL — instantiation yields sources whose `urlpath` is `None`; no rendered-URL surface exists to test | PASS 16/17 (the 17th is the deferred GAUSS entry whose urlpath ignores its declared params — a pre-existing catalog TODO, excluded by scope) |
| 3. Real reads (anon public) | FAIL — NetCDF read dies with "None is not a valid NetCDF 3 file": the rendered path never reaches the backend; raw ZarrSource mechanics work against a public store | PASS — multi-file NetCDF `to_dask()` over anon S3 (12,960 daily steps, lazy), public Zarr store opens under zarr-python 3 |
| 4. Error contract | FAIL — unknown kwargs silently accepted; a wrapper layer would be required regardless | PASS — TypeError on unknown kwargs (with valid-parameter listing), alias equivalence, value_map derivation, `MissingCredentialsError` naming `CLOUDFLARE_R2_ACCOUNT_ID` |
| 5. Clean-venv freeze | Recorded: intake 2.0.9, intake-xarray 2.0.0, zarr 3.3.0, xarray 2026.7.0, dask 2026.7.1, s3fs 2026.7.0 — plus **undeclared** jinja2 and scipy needed along the way | Recorded (dev env): zarr 3.1.5, xarray 2025.12.0, dask 2025.12.0, s3fs 2025.12.0, h5netcdf 1.8.1, PyYAML 6.0.3 |
| 6. Footprint | +intake +intake-xarray +jinja2 (+scipy fallback); import 0.05-0.21s | zero deps beyond the load stack (PyYAML already present); import 0.06s |

## Load-bearing observations

- **`metadata.version` is intake's catalog-format discriminator.** Setting
  it to 2 makes `intake.open_catalog` fail with "Not a V2 catalog". Our
  schema version therefore lives in `metadata.reflective_schema_version`
  (the loader asserts it); `metadata.version` stays 1. This amends the
  plan's R21 mechanism.
- intake 2.0.9 requires jinja2 for parameter templating without declaring
  it (clean-install `ModuleNotFoundError`), reconfirming the adoption
  review's finding.
- intake-xarray's NetCDF driver selected the scipy backend for HDF5 files
  (the known NetCDF3 mis-detection) on entries that don't hardcode an
  engine.
- The intake v1-compat entry -> intake-xarray handoff on the current
  resolved stack never delivers the rendered urlpath to the source; fixing
  it means debugging upstream intake — the definition of not "passing
  cleanly".
- Discovery scans against anonymous buckets return empty under both
  candidates because `CloudFileSystem` builds stores without per-entry
  `anon` options — the U4 storage-options plumbing fixes this; it is not a
  candidate differentiator.
- zarr-python 3 (3.1.5 and 3.3.0) opened consolidated v1-format public
  stores without issue in both environments; U8 sets the dependency floor
  from the store formats the (credential-pending) inventory records.

## Reversal trigger (KTD9, unchanged)

If the self-parsed loader grows past ~300 lines to reach parity, or the
YAML schema stops fitting, the fallback is an intake-esm-style asset table
for the model data. The catalog file outlives the runtime either way.
