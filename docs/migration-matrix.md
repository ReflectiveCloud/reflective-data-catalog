# Migration matrix (rendered)

Rendered from `src/reflective_data_catalog/migration_matrix.yaml` (schema v1). Do not edit by hand.

## Source dispositions

| Old name | New entry | Backend | Status | Old defaults | New defaults |
|---|---|---|---|---|---|
| `cesm2_waccm_g6_1p5k_hilla` | `cesm2_waccm_g6_1p5k_hilla` | netcdf->zarr | pending_verification | {'table': 'AMON', 'variable': 'T', 'ensemble': 'r1'} | {'table': None, 'variable': None, 'ensemble': None} |
| `cesm2_waccm_historical` | `cesm2_waccm_historical` | netcdf->zarr planned; NetCDF fallback preserves today's paths and r1->001 mapping | pending_verification | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} |
| `cesm2_waccm_ssp245` | `cesm2_waccm_ssp245` | netcdf->zarr planned; NetCDF fallback preserves today's paths and r1->001 mapping | pending_verification | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} | {'table': 'OMON', 'variable': 'TEMP', 'ensemble': 'r1'} |
| `e3smv3_g6_1p5k_hilla` | `e3smv3_g6_1p5k_hilla` | netcdf->zarr | pending_verification | {'table': 'Amon', 'variable': 'T', 'ensemble': 'v3.LR.ssp245.g6_hilla.sai.0101'} | {'table': None, 'variable': None, 'ensemble': '0101'} |
| `miroc_es2h_g6_1p5k_hilla` | `miroc_es2h_g6_1p5k_hilla` | netcdf (unchanged) | pending_verification | {'table': 'Amon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'baseline'} | {'table': 'Amon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'baseline'} |
| `miroc_es2h_g6_1p5k_sai` | `miroc_es2h_g6_1p5k_sai` | netcdf (unchanged) | pending_verification | {'table': 'Mon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'G6-1.5K-SAI'} | {'table': 'Mon', 'variable': 'SurfT', 'ensemble': 'r01', 'variant': 'G6-1.5K-SAI'} |
| `ukesm1_g6_1p5k_hilla` | `ukesm1_g6_1p5k_hilla` | netcdf->zarr | pending_verification | {'table': 'ap4', 'variable': 'ua', 'ensemble': 'r12i1p1f2', 'time': 'AERmon'} | {'table': None, 'variable': None, 'ensemble': None} |
| `ukesm1_ssp245` | `ukesm1_ssp245` | netcdf->zarr | pending_verification | {'table': 'ap4', 'variable': 'mmrso4', 'ensemble': 'r12i1p1f1', 'time': 'AERmon'} | {'table': None, 'variable': None, 'ensemble': None} |

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
| `cesm2_waccm_g6_1p5k_sai` | experimental |
| `e3smv3_g6_1p5k_sai` | experimental |
| `miroc_g6_1p5k_sai` | absorbed |
| `cesm2_waccm6_gauss_historical` | experimental |
| `arise_15_cesm2_waccm_ssp245` | stable |
| `arise_sai_15` | stable |
| `ukesm1_arise_sai` | stable |
| `ukesm1_arise_cmip6` | stable |

## Kwarg dispositions

| Kwarg | Disposition |
|---|---|
| `ensemble` | canonical; aliases: ensemble_member, member_id |
| `table` | canonical; aliases: table_id |
| `variable` | canonical; aliases: variable_id |
| `variant` | kept as a per-entry parameter on the MIROC entries |
| `time` | removed with the UKESM Zarr switch; the stream/time split collapses into CMOR tables — error redirects to the migration guide |
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
