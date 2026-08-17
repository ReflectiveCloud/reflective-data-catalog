# Equivalence report: e3smv3_g6_1p5k_hilla

Gate errored: DataNotFoundError: e3smv3_g6_1p5k_hilla: could not open s3://reflective-persistent-prod-large/E3SMv3/G6-1.5K-HiLLA/v3.LR.ssp245.g6_hilla.sai.0101/Amon/tas.zarr. Use list_tables()/list_variables() for available groups, or see the migration guide (docs/migration-matrix.md)

**Verdict: ERROR** (2026-08-13T15:47:34+00:00)

Per plan R4, this source must keep (or revert to) its NetCDF entry until the gate passes.

Post-run correction (2026-08-13): the audit showed the store keeps E3SM-native
variable names (T, TREFHT, ...) — `tas` never existed. The entry default was
fixed to `T`; the next gate run compares the real stores.
