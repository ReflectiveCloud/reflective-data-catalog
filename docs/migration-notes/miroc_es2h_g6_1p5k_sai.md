# Equivalence report: miroc_es2h_g6_1p5k_sai

- NetCDF files: 1; Zarr store: default parameters
- dims old={'lon': 256, 'bnds': 2, 'lat': 128, 'time': 600} new={'time': 600, 'lat': 128, 'lon': 256}
- time span old=('2035-01-16T12:00:00.000000000', '2084-12-16T12:00:00.000000000') new=('2035-01-16T12:00:00.000000000', '2084-12-16T12:00:00.000000000')
  - time labels shifted within one interval (end-of-interval vs mid-interval stamping) — accepted
- tail NaN fraction old=0.0000 new=0.0000
- tail values allclose (overlap window): True

**Verdict: PASS** (2026-08-13T15:47:34+00:00)
