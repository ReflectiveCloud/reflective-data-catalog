# Migration matrix (rendered)

Rendered from `src/reflective_data_catalog/migration_matrix.yaml` (schema v1). Do not edit by hand.

## Source dispositions

| Old name | New entry | Backend | Status | Old defaults | New defaults |
|---|---|---|---|---|---|
| `cesm2_waccm_g6_1p5k_hilla` | `cesm2_waccm_g6_1p5k_hilla` | netcdf->zarr (public Cloudflare R2, one store per experiment) | verified | {'table': 'AMON', 'variable': 'T', 'ensemble': 'r1'} | {'table': 'Amon', 'ensemble': 'r1'} |
| `cesm2_waccm_historical` | `cesm2_waccm_historical` | netcdf (unchanged; NetCDF-only — prefix corrected HISTORICAL -> Historical per maintainer 2026-08-13; filename corrected to b.e21.BWHIST.f09_g17.CMIP6-historical-WACCM.* per the 2026-08-13 hub audit) | verified | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} |
| `cesm2_waccm_ssp245` | `cesm2_waccm_ssp245` | netcdf->zarr (public Cloudflare R2, one store per experiment) | verified | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} | {'table': 'Omon', 'ensemble': 'r1'} |
| `e3smv3_g6_1p5k_hilla` | `e3smv3_g6_1p5k_hilla` | netcdf (unchanged; never zarrified — the hub holds the original CDF-5 tree under variable/gn/<version>/, opened via netCDF4 with a temporary local download; maintainer decision 2026-08-31) | verified | {'table': 'Amon', 'variable': 'T', 'ensemble': 'v3.LR.ssp245.g6_hilla.sai.0101'} | {'table': 'Amon', 'variable': 'T', 'ensemble': '0101'} |
| `miroc_es2h_g6_1p5k_hilla` | `miroc_es2h_g6_1p5k_hilla` | netcdf->zarr (public Cloudflare R2, one store per variant) | verified | {'table': 'Amon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'baseline'} | {'table': 'Mon', 'ensemble': 'r01', 'variant': 'baseline'} |
| `miroc_es2h_g6_1p5k_sai` | `miroc_es2h_g6_1p5k_sai` | netcdf->zarr (public Cloudflare R2, one store per variant) | verified | {'table': 'Mon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'G6-1.5K-SAI'} | {'table': 'Mon', 'ensemble': 'r01', 'variant': 'G6-1.5K-SAI'} |
| `ukesm1_g6_1p5k_hilla` | `ukesm1_g6_1p5k_hilla` | netcdf (unchanged; the source is NetCDF-only — prefix corrected G6-1.5K-HiLLA -> G6-1p5K-HiLLA per maintainer 2026-08-13) | verified | {'table': 'ap4', 'variable': 'ua', 'ensemble': 'r12i1p1f2', 'time': 'AERmon'} | {'table': 'ap4', 'variable': 'ua', 'ensemble': 'r12i1p1f2', 'time': 'AERmon'} |
| `ukesm1_ssp245` | `ukesm1_ssp245` | netcdf (unchanged; the source was never zarrified — the 2026-08-13 hub listing shows the pre-1.0 stream/time NetCDF layout intact) | verified | {'table': 'ap4', 'variable': 'mmrso4', 'ensemble': 'r12i1p1f1', 'time': 'AERmon'} | {'table': 'ap4', 'variable': 'mmrso4', 'ensemble': 'r12i1p1f1', 'time': 'AERmon'} |

## Entry stability

| Entry | Stability |
|---|---|
| `ukesm1_g6_1p5k_hilla` | stable |
| `cesm2_waccm_g6_1p5k_hilla` | stable |
| `e3smv3_g6_1p5k_hilla` | stable |
| `miroc_es2h_g6_1p5k_hilla` | stable |
| `miroc_es2h_g6_1p5k_sai` | stable |
| `cesm2_waccm_historical` | stable |
| `cesm2_waccm_ssp245` | stable |
| `ukesm1_ssp245` | stable |
| `e3smv3_ssp245` | stable |
| `ukesm1_g6_1p5k_sai` | experimental |
| `cesm2_waccm_g6_1p5k_sai` | stable |
| `e3smv3_g6_1p5k_sai` | experimental |
| `cesm2_waccm6_gauss_historical` | experimental |
| `arise_15_cesm2_waccm_ssp245` | stable |
| `arise_sai_15` | stable |
| `ukesm1_arise_sai` | stable |
| `ukesm1_arise_cmip6` | stable |
| `simulator_cesm2_waccm_ma_0p5k_sai` | stable |
| `simulator_cesm2_waccm_ma_1p0k_sai` | stable |
| `simulator_cesm2_waccm_ma_1p5k_sai` | stable |
| `simulator_cesm2_waccm_ma_baseline` | stable |
| `simulator_cesm2_waccm_ma_historical` | stable |
| `simulator_miroc_es2h_g6_0p5k_sai` | stable |
| `simulator_miroc_es2h_g6_1p5k_sai` | stable |
| `simulator_miroc_es2h_baseline` | stable |
| `simulator_miroc_es2h_historical` | stable |
| `simulator_miroc_es2h_ssp245` | stable |

## Kwarg dispositions

| Kwarg | Disposition |
|---|---|
| `ensemble` | canonical; aliases: ensemble_member, member_id |
| `table` | canonical; aliases: table_id |
| `variable` | canonical; aliases: variable_id. On the grouped public-R2 Zarr entries (CESM/MIROC) variables are selected from the opened dataset, not a path parameter |
| `variant` | kept as a per-entry parameter on the MIROC entries |
| `time` | per-entry parameter on both UKESM hub entries (ukesm1_ssp245 and ukesm1_g6_1p5k_hilla), whose stream/time NetCDF layouts are unchanged |
| `realm` | per-entry parameter on ARISE CESM entries |
| `time_frequency` | per-entry parameter on ARISE CESM entries |
| `version` | per-entry parameter on ukesm1_arise_cmip6 |

## API changes

- get_source_config() removed; use get_source(name) and get_parameters(name)
- get_parameters() drops the is_flexible key and unifies on {name, driver, description, parameters}
- search()/list_sources()/list_tags() return structured records; printing moves behind verbose=True
- unknown source names raise SourceNotFoundError (an AttributeError subclass) instead of bare AttributeError/ValueError
- unknown keyword arguments raise TypeError (previously silently ignored)
- old parameter values on renamed backends raise a guidance error carrying rows from this matrix
- get_source(name) added for string-keyed and typed access
