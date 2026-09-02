# Equivalence report: cesm2_waccm_g6_1p5k_hilla

- NetCDF files: 2; Zarr store: default parameters
- dims old={'time': 600, 'zlon': 1, 'nbnd': 2, 'lat': 192, 'lev': 70, 'ilev': 71, 'lon': 288} new={'time': 600, 'lev': 70, 'lat': 192, 'lon': 288, 'ilev': 71, 'bnds': 2, 'zlon': 1}
- time span old=('2035-02-01 00:00:00', '2085-01-01 00:00:00') new=('2035-01-16T12:00:00.000000000', '2084-12-16T12:00:00.000000000')
  - time labels shifted within one interval (end-of-interval vs mid-interval stamping) — accepted
- tail NaN fraction old=0.0000 new=0.0000
- tail values allclose (overlap window): True

**Verdict: PASS** (2026-08-13T15:47:34+00:00)
