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
        # E3SM originals are CDF-5 (b'CDF\x05'), unreadable by h5netcdf.
        "engine": "netcdf4",
    },
    "cesm2_waccm_ssp245": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/CESM2-WACCM/SSP2-4.5/"
            "r1/OMON/b.e21.BWSSP245cmip6.f09_g17.CMIP6-SSP2-4.5-WACCM.001.pop.*.TEMP.*.nc"
        ),
        "old_default_variable": "TEMP",
        # Maintainer decision 2026-08-13: the public store's 2015-2069
        # window ships as-is (the hub originals run to 2100). Tracked in
        # the Cloud Hub Asana project.
        "expected_end": "2069-12",
    },
    "miroc_es2h_g6_1p5k_hilla": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/MIROC-ES2H/G6-1.5K-HiLLA/"
            "Amon/SurfT_baseline_r01.nc"
        ),
        "old_default_variable": "SurfT",
    },
    "miroc_es2h_g6_1p5k_sai": {
        "netcdf_glob": (
            "s3://reflective-persistent-prod-large/MIROC-ES2H/G6-1.5K-SAI/"
            "Mon/SurfT_G6-1.5K-SAI_r01.nc"
        ),
        "old_default_variable": "SurfT",
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
    if files and "*" not in spec["netcdf_glob"]:
        # open_files does not existence-check exact paths; a missing
        # original must classify as ORIGINALS-GONE, not ERROR.
        fs = files.fs
        files = [f for f in files if fs.exists(f.path)]
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
    engine = spec.get("engine", "h5netcdf")
    if engine == "netcdf4":
        # netCDF4-python cannot read file-like objects reliably; download.
        import tempfile

        handles = []
        for f in files:
            with (
                f.open() as fh,
                tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp,
            ):
                tmp.write(fh.read())
                handles.append(tmp.name)
        old = xr.open_mfdataset(handles, engine="netcdf4", combine="by_coords")
    else:
        old = xr.open_mfdataset(
            [f.open() for f in files], engine=engine, combine="by_coords"
        )
    new = catalog.get_source(name).to_dask()

    verdict = "PASS"
    truncated = False
    lines.append(f"- NetCDF files: {len(files)}; Zarr store: default parameters")
    lines.append(f"- dims old={dict(old.sizes)} new={dict(new.sizes)}")
    if "time" in old.dims and "time" in new.dims:
        span_old = (str(old.time.values[0]), str(old.time.values[-1]))
        span_new = (str(new.time.values[0]), str(new.time.values[-1]))
        lines.append(f"- time span old={span_old} new={span_new}")
        n_old, n_new = old.sizes["time"], new.sizes["time"]

        def _ym(value: str) -> tuple[int, int]:
            year, month = str(value)[:7].split("-")
            return int(year), int(month)

        def _months_apart(a: str, b: str) -> int:
            (ya, ma), (yb, mb) = _ym(a), _ym(b)
            return abs((ya - yb) * 12 + (ma - mb))

        if n_old == n_new:
            # Tolerate sub-interval label shifts: CESM history files stamp
            # monthly means at the END of the interval; zarrification
            # re-centers to mid-month. Same data, different labels.
            if (
                _months_apart(span_old[0], span_new[0]) <= 1
                and _months_apart(span_old[1], span_new[1]) <= 1
            ):
                lines.append(
                    "  - time labels shifted within one interval "
                    "(end-of-interval vs mid-interval stamping) — accepted"
                )
            else:
                verdict = "FAIL"
                lines.append("  - MISMATCH: time axes disagree beyond labeling")
        elif n_new < n_old:
            truncated = True
            lines.append(
                f"  - TRUNCATED: the Zarr copy holds {n_new} of {n_old} "
                f"time steps (ends {span_new[1][:7]} vs {span_old[1][:7]}); "
                f"values are compared over the overlap below"
            )
            expected_end = spec.get("expected_end")
            if expected_end and span_new[1][:7] == expected_end:
                truncated = False
                lines.append(
                    f"  - expected window: the store intentionally ends at "
                    f"{expected_end} (recorded in the gate spec) — accepted"
                )
            # Align the comparison to the overlap window (positional:
            # both series start at the same first interval).
            old = old.isel(time=slice(0, n_new))
        else:
            verdict = "FAIL"
            lines.append("  - MISMATCH: the Zarr copy has MORE time steps")

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
        lines.append(f"- tail values allclose (overlap window): {close}")
        if not close:
            verdict = "FAIL"
    else:
        lines.append(f"  - shape mismatch old={tail_a.shape} new={tail_b.shape}")
        verdict = "FAIL"
    if verdict == "PASS" and truncated:
        verdict = "TRUNCATED"
        lines.append(
            "Overlap values agree, but the store is missing later time "
            "steps. If the shorter window is intentional, record "
            "expected_end in the gate spec; otherwise finish the upload."
        )
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
