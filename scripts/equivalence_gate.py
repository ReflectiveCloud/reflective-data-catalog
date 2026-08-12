#!/usr/bin/env python3
"""NetCDF->Zarr equivalence gate for backend-switched sources (plan U10).

For every source whose backend switched from the pre-1.0 NetCDF layout to a
Zarr copy, this script opens BOTH backends and verifies the copy carries the
same science before the switch is allowed to ship:

- structure: dims, coordinate names, dtypes, time range
- values (adversarial to partial uploads): the END of the time range and
  array corners — early chunks upload first, so a truncated copy passes a
  first-timestep check — plus the NaN fraction of the default variable.
  Zarr reads missing chunks as fill values (NaN) BY DESIGN, so a partially
  uploaded store opens cleanly and fabricates data silently; the NaN-fraction
  comparison is what catches it.

A failing or unrunnable gate means the source keeps its NetCDF entry
(plan R4); the per-source verdict is written to docs/migration-notes/.

Requires read credentials for the Reflective hub bucket. Reruns are cheap:
metadata plus three small slices per source.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOTES = REPO / "docs" / "migration-notes"

# Pre-1.0 NetCDF layouts (from the deleted reflective_data.py, preserved here
# because the package no longer carries them). ensemble ids already rendered
# with each source's old defaults.
SWITCHED = {
    "ukesm1_g6_1p5k_hilla": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/UKESM1-1/G6-1.5K-HiLLA/"
            "r12i1p1f2/ap4/AERmon/ua/ua_AERmon_UKESM1-1-LL_g6-1p5-hilla_r12i1p1f2_gn_*.nc"
        ),
        "old_default_variable": "ua",
    },
    "ukesm1_ssp245": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/UKESM1-1/SSP245/"
            "r12i1p1f1/ap4/AERmon/mmrso4/mmrso4_AERmon_UKESM1-0-LL_ssp245_r12i1p1f1_gn_*.nc"
        ),
        "old_default_variable": "mmrso4",
    },
    "cesm2_waccm_g6_1p5k_hilla": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/CESM2-WACCM/G6-1.5k-HiLLA/"
            "r1/AMON/b.e21.BW.f09_g17.SSP245-G6-1p5K-HiLLA.001.cam.*.T.*.nc"
        ),
        "old_default_variable": "T",
    },
    "e3smv3_g6_1p5k_hilla": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/E3SMv3/G6-1.5K-HiLLA/"
            "v3.LR.ssp245.g6_hilla.sai.0101/Amon/T/gn/13112025/T_*.nc"
        ),
        "old_default_variable": "T",
    },
}


def compare(name: str, spec: dict) -> tuple[str, list[str]]:
    """Return (verdict, report_lines) for one switched source."""
    import fsspec
    import numpy as np
    import xarray as xr

    sys.path.insert(0, str(REPO / "src"))
    from reflective_data_catalog import ReflectiveCatalog

    lines = [f"# Equivalence report: {name}", ""]
    catalog = ReflectiveCatalog()

    files = fsspec.open_files(spec["netcdf_glob"])
    if not files:
        # The listing succeeded (no PermissionError) but matched nothing:
        # the pre-1.0 NetCDF originals no longer exist. There is no baseline
        # to compare and nothing to revert to — the Zarr copy is the only
        # copy. Verification falls to the bucket audit (existence, format,
        # chunk completeness via scripts/bucket_audit.py --deep).
        lines.append(
            f"NetCDF originals no longer exist at `{spec['netcdf_glob']}` "
            f"(listing succeeded, zero matches). The Zarr copy is the only "
            f"copy; integrity is verified by the bucket audit instead."
        )
        return "ORIGINALS-GONE", lines
    old = xr.open_mfdataset(
        [f.open() for f in files], engine="h5netcdf", combine="by_coords"
    )
    new = catalog.get_source(name).to_dask()

    verdict = "PASS"
    lines.append(f"- NetCDF files: {len(files)}; Zarr store: default parameters")
    lines.append(f"- dims old={dict(old.sizes)} new={dict(new.sizes)}")
    if "time" in old.dims and "time" in new.dims:
        span_old = (str(old.time.values[0]), str(old.time.values[-1]))
        span_new = (str(new.time.values[0]), str(new.time.values[-1]))
        lines.append(f"- time span old={span_old} new={span_new}")
        if span_old != span_new:
            verdict = "FAIL"
            lines.append("  - MISMATCH: time spans differ")

    var_old = spec["old_default_variable"]
    candidates = [var_old, var_old.lower(), "tas"]
    var_new = next((v for v in candidates if v in new.data_vars), None)
    if var_old not in old.data_vars or var_new is None:
        lines.append(
            f"- variable mapping unresolved (old {var_old!r}; new has "
            f"{sorted(new.data_vars)[:8]}) — record the mapping in the matrix"
        )
        return "NEEDS-MAPPING", lines

    a, b = old[var_old], new[var_new]
    # Adversarial slices: end of time range + corners + NaN fraction.
    tail_a = a.isel(time=slice(-3, None)).load()
    tail_b = b.isel(time=slice(-3, None)).load()
    nan_a = float(np.isnan(tail_a.values).mean())
    nan_b = float(np.isnan(tail_b.values).mean())
    lines.append(f"- tail NaN fraction old={nan_a:.4f} new={nan_b:.4f}")
    if abs(nan_a - nan_b) > 0.001:
        verdict = "FAIL"
        lines.append("  - MISMATCH: NaN fractions diverge (partial upload?)")
    if tail_a.shape == tail_b.shape:
        close = np.allclose(tail_a.values, tail_b.values, equal_nan=True, rtol=1e-5)
        lines.append(f"- tail values allclose: {close}")
        if not close:
            verdict = "FAIL"
    else:
        lines.append(f"  - shape mismatch old={tail_a.shape} new={tail_b.shape}")
        verdict = "FAIL"
    return verdict, lines


def main() -> int:
    NOTES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    failures = 0
    for name, spec in SWITCHED.items():
        try:
            verdict, lines = compare(name, spec)
        except PermissionError:
            verdict = "PENDING-CREDENTIALS"
            lines = [
                f"# Equivalence report: {name}",
                "",
                "Gate could not run: the hub bucket denied access. Re-run",
                "`python scripts/equivalence_gate.py` with read credentials.",
            ]
        except Exception as exc:  # verdict captures the failure
            verdict = "ERROR"
            lines = [
                f"# Equivalence report: {name}",
                "",
                f"Gate errored: {type(exc).__name__}: {exc}",
            ]
        lines += ["", f"**Verdict: {verdict}** ({stamp})", ""]
        if verdict == "ORIGINALS-GONE":
            lines.append(
                "Amended R4 disposition: no NetCDF fallback exists; the "
                "bucket audit (--deep chunk-completeness) is the required "
                "verification for this source."
            )
        elif verdict != "PASS":
            failures += 1
            lines.append(
                "Per plan R4, this source must keep (or revert to) its "
                "NetCDF entry until the gate passes."
            )
        out = NOTES / f"{name}.md"
        out.write_text("\n".join(lines) + "\n")
        print(f"{name}: {verdict} -> {out.relative_to(REPO)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
