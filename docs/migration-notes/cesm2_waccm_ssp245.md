# Equivalence report: cesm2_waccm_ssp245

- NetCDF files: 2; Zarr store: default parameters
- dims old={'time': 1032, 'moc_comp': 3, 'transport_comp': 5, 'transport_reg': 2, 'z_t': 60, 'z_w': 60, 'nlat': 384, 'nlon': 320, 'd2': 2, 'z_t_150m': 15, 'z_w_top': 60, 'z_w_bot': 60, 'lat_aux_grid': 395, 'moc_z': 61} new={'nlat': 384, 'nlon': 320, 'z_t': 60, 'z_w': 60, 'moc_comp': 3, 'time': 660, 'bnds': 2, 'transport_comp': 5, 'transport_reg': 2, 'z_w_top': 60, 'lat_aux_grid': 395, 'moc_z': 61, 'z_t_150m': 15, 'z_w_bot': 60}
- time span old=('2015-02-01 00:00:00', '2101-01-01 00:00:00') new=('2015-01-16T12:00:00.000000000', '2069-12-16T12:00:00.000000000')
  - TRUNCATED: the Zarr copy holds 660 of 1032 time steps (ends 2069-12 vs 2101-01); values are compared over the overlap below
  - expected window: the store intentionally ends at 2069-12 (recorded in the gate spec) — accepted
- tail NaN fraction old=0.4239 new=0.4239
- tail values allclose (overlap window): True

**Verdict: PASS** (2026-08-13T15:47:34+00:00)
