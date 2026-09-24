"""Entry-integrity tests: the real shipped catalog, unmocked, no network.

These tests instantiate every entry in ``data-catalog.yaml`` through the
real loader (plan R16). They need no credentials and no network — rendering
and validation are pure — so they run in CI on every push and gate the
catalog file itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from reflective_data_catalog.exceptions import CatalogError
from reflective_data_catalog.loader import (
    ALLOWED_STORAGE_OPTIONS,
    CANONICAL_ALIASES,
    CatalogSource,
    load_catalog,
)

PACKAGE = Path(__file__).parent.parent / "src" / "reflective_data_catalog"
CATALOG_PATH = PACKAGE / "data-catalog.yaml"
MATRIX_PATH = PACKAGE / "migration_matrix.yaml"
INVENTORY_PATH = Path(__file__).parent / "fixtures" / "bucket_inventory.json"

DOCUMENTED_NAMES = [
    "cesm2_waccm_g6_1p5k_hilla",
    "cesm2_waccm_historical",
    "cesm2_waccm_ssp245",
    "e3smv3_g6_1p5k_hilla",
    "miroc_es2h_g6_1p5k_hilla",
    "miroc_es2h_g6_1p5k_sai",
    "ukesm1_g6_1p5k_hilla",
    "ukesm1_ssp245",
]

# The GAUSS entry is deferred (TODO paths) and excluded from rendering gates.
DEFERRED_ENTRIES = {"cesm2_waccm6_gauss_historical"}


@pytest.fixture(scope="module")
def catalog() -> dict:
    return load_catalog(CATALOG_PATH)


@pytest.fixture(scope="module")
def matrix() -> dict:
    with MATRIX_PATH.open() as f:
        return yaml.safe_load(f)


class FakeFS:
    """Discovery-free stand-in; rendering tests never touch storage."""

    def fsspec_info(self, url):  # pragma: no cover - not exercised here
        return url, {}

    def ls(self, path, detail=False):  # pragma: no cover
        return []


class TestCatalogIntegrity:
    def test_loads_and_validates(self, catalog):
        assert catalog["metadata"]["version"] == 1  # intake format discriminator
        assert catalog["metadata"]["reflective_schema_version"] == 2
        assert len(catalog["sources"]) >= 27

    def test_every_name_is_an_identifier(self, catalog):
        bad = [n for n in catalog["sources"] if not n.isidentifier()]
        assert not bad

    def test_documented_names_present(self, catalog):
        missing = [n for n in DOCUMENTED_NAMES if n not in catalog["sources"]]
        assert not missing

    def test_every_entry_instantiates(self, catalog):
        for name, entry in catalog["sources"].items():
            src = CatalogSource(name, entry, FakeFS())
            assert src.name == name

    def test_every_entry_renders_defaults(self, catalog):
        for name, entry in catalog["sources"].items():
            src = CatalogSource(name, entry, FakeFS())
            urls = src.url
            urls = urls if isinstance(urls, list) else [urls]
            assert all("{{" not in u for u in urls), f"{name}: unrendered"
            group = (entry.get("args") or {}).get("group")
            if group:
                assert "{{" not in src._render(group), f"{name}: group unrendered"

    def test_every_defaults_by_value_renders(self, catalog):
        """Each per-value default set yields a fully rendered url and group."""
        for name, entry in catalog["sources"].items():
            defaults_by = (entry.get("metadata") or {}).get("defaults_by") or {}
            for selector, by_value in defaults_by.items():
                for value, overrides in by_value.items():
                    src = CatalogSource(name, entry, FakeFS(), **{selector: value})
                    for param, default in overrides.items():
                        assert src._params[param] == default, (name, value, param)
                    urls = src.url
                    urls = urls if isinstance(urls, list) else [urls]
                    assert all("{{" not in u for u in urls), (name, value)

    def test_every_entry_renders_one_override(self, catalog):
        for name, entry in catalog["sources"].items():
            if name in DEFERRED_ENTRIES:
                continue
            params = entry.get("parameters") or {}
            derived = ((entry.get("metadata") or {}).get("value_map")) or {}
            derived_sources = {spec.get("from") for spec in derived.values()}
            for param in params:
                if param in derived or param in derived_sources:
                    continue
                src = CatalogSource(name, entry, FakeFS(), **{param: "OVERRIDE"})
                urls = src.url
                urls = urls if isinstance(urls, list) else [urls]
                if any("{{" + param in t for t in _templates(entry)):
                    assert any("OVERRIDE" in u for u in urls), (
                        f"{name}: override of {param} ignored"
                    )

    def test_netcdf_entries_have_no_zarr_args(self, catalog):
        for name, entry in catalog["sources"].items():
            if entry["driver"] == "netcdf":
                assert "consolidated" not in entry["args"], name

    def test_storage_options_are_allowlisted(self, catalog):
        for name, entry in catalog["sources"].items():
            opts = set(entry["args"].get("storage_options") or {})
            assert opts <= ALLOWED_STORAGE_OPTIONS, name

    def test_custom_tags_are_rejected(self, tmp_path):
        evil = tmp_path / "evil.yaml"
        evil.write_text(
            "metadata:\n  reflective_schema_version: 2\n"
            "sources:\n  x: !!python/object/apply:os.system ['echo pwned']\n"
        )
        with pytest.raises(CatalogError):
            load_catalog(evil)

    def test_unknown_args_key_fails_load(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "metadata:\n  reflective_schema_version: 2\n"
            "sources:\n"
            "  x:\n"
            "    driver: zarr\n"
            "    args:\n"
            "      urlpath: s3://b/p.zarr\n"
            "      chunks: {}\n"
        )
        with pytest.raises(CatalogError, match="unsupported args"):
            load_catalog(bad)

    def test_endpoint_smuggling_fails_load(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "metadata:\n  reflective_schema_version: 2\n"
            "sources:\n"
            "  x:\n"
            "    driver: zarr\n"
            "    args:\n"
            "      urlpath: s3://b/p.zarr\n"
            "      storage_options:\n"
            "        endpoint_url: https://evil.example\n"
        )
        with pytest.raises(CatalogError, match="storage_options"):
            load_catalog(bad)

    @pytest.mark.parametrize(
        ("defaults_by", "match"),
        [
            ("{nope: {a: {table: T}}}", "defaults_by selector 'nope'"),
            ("{variant: {a: {nope: T}}}", "undeclared parameter"),
            ("{variant: {a: {variant: b}}}", "cannot set its own selector"),
            ("{variant: [a]}", "mapping"),
        ],
    )
    def test_bad_defaults_by_fails_load(self, tmp_path, defaults_by, match):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "metadata:\n  reflective_schema_version: 2\n"
            "sources:\n"
            "  x:\n"
            "    driver: zarr\n"
            "    args:\n"
            "      urlpath: s3://b/{{variant}}.zarr\n"
            "    parameters:\n"
            "      variant: {type: str, default: a}\n"
            "      table: {type: str, default: T}\n"
            f"    metadata:\n      defaults_by: {defaults_by}\n"
        )
        with pytest.raises(CatalogError, match=match):
            load_catalog(bad)


class TestMatrixCrossCheck:
    """The shipped migration matrix agrees with the catalog it describes."""

    def test_every_source_row_targets_a_real_entry(self, catalog, matrix):
        for old, row in matrix["sources"].items():
            assert row["new_entry"] in catalog["sources"], old

    def test_stability_covers_every_entry(self, catalog, matrix):
        missing = set(catalog["sources"]) - set(matrix["stability"])
        assert not missing, f"entries without a stability disposition: {missing}"
        stale = set(matrix["stability"]) - set(catalog["sources"])
        assert not stale, f"stability rows for absent entries: {stale}"

    def test_new_defaults_render_into_entry_urls(self, catalog, matrix):
        for old, row in matrix["sources"].items():
            entry = catalog["sources"][row["new_entry"]]
            declared = entry.get("parameters") or {}
            new_defaults = {
                k: v
                for k, v in (row.get("new_defaults") or {}).items()
                if v is not None and k in declared
            }
            src = CatalogSource(row["new_entry"], entry, FakeFS(), **new_defaults)
            urls = src.url
            urls = urls if isinstance(urls, list) else [urls]
            assert all("{{" not in u for u in urls), old

    def test_alias_table_matches_loader(self, matrix):
        for alias, canonical in CANONICAL_ALIASES.items():
            assert alias in matrix["kwargs"][canonical], (
                f"matrix kwargs row for {canonical!r} does not document alias {alias!r}"
            )


class TestInventoryCrossCheck:
    """Verified inventory rows agree with what the catalog renders today."""

    def test_verified_urls_still_render_identically(self, catalog):
        inventory = json.loads(INVENTORY_PATH.read_text())
        checked = 0
        for name, record in inventory["entries"].items():
            if name not in catalog["sources"]:
                continue  # renamed since the audit; U12 re-audit re-keys
            entry = catalog["sources"][name]
            src = CatalogSource(name, entry, FakeFS())
            urls = src.url
            urls = urls if isinstance(urls, list) else [urls]
            for url_record, rendered in zip(record["urls"], urls, strict=False):
                if url_record.get("status") == "verified" and url_record.get("exists"):
                    assert url_record["rendered_default"] == rendered, name
                    checked += 1
        assert checked > 0, "no verified inventory rows were cross-checked"


class TestIntakeCompatSmoke:
    """KTD8: the file stays openable as an intake v1 catalog (extras-gated)."""

    def test_intake_can_open_and_enumerate(self):
        intake = pytest.importorskip("intake")
        cat = intake.open_catalog(str(CATALOG_PATH))
        assert len(list(cat)) >= 27


def _templates(entry: dict) -> list[str]:
    up = entry["args"]["urlpath"]
    return up if isinstance(up, list) else [up]


def test_facet_regex_purity_guard():
    """R5: a mixed-stream match set is refused."""
    entry = {
        "driver": "netcdf",
        "args": {
            "urlpath": "s3://b/{{ensemble}}/x.{{ensemble_id}}.cam.*.{{variable}}.*.nc"
        },
        "parameters": {
            "ensemble": {"type": "str", "default": "r1"},
            "ensemble_id": {"type": "str", "default": "001"},
            "variable": {"type": "str", "default": "T"},
        },
    }
    src = CatalogSource("x", entry, FakeFS())
    mixed = [
        "b/r1/x.001.cam.h0.T.2015.nc",
        "b/r1/x.002.cam.h0.T.2015.nc",
    ]
    with pytest.raises(Exception, match="mixed selection"):
        src._assert_selection_purity(mixed)
    pure = [
        "b/r1/x.001.cam.h0.T.2015.nc",
        "b/r1/x.001.cam.h0.T.2016.nc",
    ]
    src._assert_selection_purity(pure)  # does not raise


def test_facet_regex_word_chars():
    """Facet regex tolerates values with dots/hyphens in variant names."""
    entry = {
        "driver": "netcdf",
        "args": {
            "urlpath": "s3://b/{{table}}/{{variable}}_{{variant}}_{{ensemble}}.nc"
        },
        "parameters": {
            "table": {"type": "str", "default": "Amon"},
            "variable": {"type": "str", "default": "SurfT"},
            "variant": {"type": "str", "default": "baseline"},
            "ensemble": {"type": "str", "default": "r01"},
        },
    }
    src = CatalogSource("x", entry, FakeFS())
    mixed_variant = [
        "b/Amon/SurfT_baseline_r01.nc",
        "b/Amon/SurfT_experiment_r01.nc",
    ]
    with pytest.raises(Exception, match="mixed selection"):
        src._assert_selection_purity(mixed_variant)


def test_netcdf4_engine_opens_via_local_copies(tmp_path):
    """CDF-5 sources (E3SM) open via netCDF4 on temporary local copies."""
    pytest.importorskip("netCDF4")
    import numpy as np
    import xarray as xr

    data_dir = tmp_path / "T"
    data_dir.mkdir()
    for i in range(2):
        ds = xr.Dataset(
            {"T": ("time", np.arange(3, dtype="f4"))},
            coords={"time": np.arange(i * 3, i * 3 + 3)},
        )
        ds.to_netcdf(data_dir / f"T_{i}.nc", engine="netcdf4")
    entry = {
        "driver": "netcdf",
        "args": {
            "urlpath": f"file://{tmp_path}/{{{{variable}}}}/*.nc",
            "combine": "by_coords",
            "xarray_kwargs": {"engine": "netcdf4"},
        },
        "parameters": {"variable": {"type": "str", "default": "T"}},
    }
    src = CatalogSource("x", entry, FakeFS())
    opened = src.to_dask()
    assert opened.sizes["time"] == 6
    assert "T" in opened.data_vars


def test_grouped_store_list_variables(monkeypatch):
    """Grouped Zarr entries list variables from the consolidated metadata.

    ``variable`` is not a declared parameter on these entries, so the scan
    reads the store metadata: group segments the caller pins (table/realm)
    filter the groups; unpinned segments aggregate across every group.
    """
    entry = {
        "driver": "zarr",
        "args": {
            "urlpath": "https://example.invalid/store.zarr",
            "group": "{{table}}/{{realm}}",
        },
        "parameters": {
            "table": {"type": "str", "default": "Mon"},
            "realm": {"type": "str", "default": "atmos_2d"},
            "ensemble": {"type": "str", "default": "r01"},
        },
        "metadata": {"select_map": {"member": "ensemble"}},
    }
    meta = {
        "Mon": {"node_type": "group"},
        "Mon/atmos_2d": {"node_type": "group"},
        "Mon/atmos_2d/TREFHT": {
            "node_type": "array",
            "dimension_names": ["member", "time", "lat", "lon"],
        },
        "Mon/atmos_2d/time": {"node_type": "array", "dimension_names": ["time"]},
        "Mon/atmos_2d/member": {"node_type": "array", "dimension_names": ["member"]},
        "day": {"node_type": "group"},
        "day/atmos_2d": {"node_type": "group"},
        "day/atmos_2d/PRECT": {
            "node_type": "array",
            "dimension_names": ["member", "time", "lat", "lon"],
        },
    }
    monkeypatch.setattr(
        CatalogSource, "_store_metadata", lambda self, store_url=None: meta
    )
    src = CatalogSource("x", entry, FakeFS())
    assert src.list_variables() == ["PRECT", "TREFHT"]  # whole store
    assert src.list_variables(table="day") == ["PRECT"]  # day/* aggregate
    assert src.list_variables(table="Mon", realm="atmos_2d") == ["TREFHT"]
    # Non-group parameters do not constrain the group match.
    assert src.list_variables(ensemble="r02", table="day") == ["PRECT"]
    # A pinned value matching no group warns and returns [] (plan R9).
    with pytest.warns(UserWarning, match="no variables"):
        assert src.list_variables(table="Amon", refresh=True) == []


def test_select_map_member_selection():
    """Grouped public stores: the ensemble parameter selects along a dim."""
    import numpy as np
    import xarray as xr

    from reflective_data_catalog.exceptions import DataNotFoundError

    entry = {
        "driver": "zarr",
        "args": {
            "urlpath": "https://example.invalid/store.zarr",
            "group": "{{table}}/{{realm}}",
        },
        "parameters": {
            "table": {"type": "str", "default": "Mon"},
            "realm": {"type": "str", "default": "atmos_2d"},
            "ensemble": {"type": "str", "default": "r01"},
        },
        "metadata": {"select_map": {"member": "ensemble"}},
    }
    ds = xr.Dataset(
        {"SurfT": (("member", "time"), np.zeros((3, 4)))},
        coords={"member": ["r01", "r02", "r03"], "time": range(4)},
    )
    src = CatalogSource("x", entry, FakeFS())
    selected = src._apply_selection(ds)
    assert "member" not in selected.dims  # scalar selection applied

    src_all = CatalogSource("x", entry, FakeFS(), ensemble="all")
    assert "member" in src_all._apply_selection(ds).dims  # sentinel keeps all

    src_bad = CatalogSource("x", entry, FakeFS(), ensemble="r99")
    with pytest.raises(DataNotFoundError, match="r99"):
        src_bad._apply_selection(ds)


def test_value_map_chains_into_selection():
    """CESM: ensemble r2 -> ensemble_id 002 -> member selection."""
    import numpy as np
    import xarray as xr

    entry = {
        "driver": "zarr",
        "args": {
            "urlpath": "https://example.invalid/s.zarr",
            "group": "{{table}}/{{realm}}",
        },
        "parameters": {
            "table": {"type": "str", "default": "Amon"},
            "realm": {"type": "str", "default": "atmos_3d"},
            "ensemble": {"type": "str", "default": "r1"},
            "ensemble_id": {"type": "str", "default": "001"},
        },
        "metadata": {
            "value_map": {
                "ensemble_id": {"from": "ensemble", "map": {"r1": "001", "r2": "002"}}
            },
            "select_map": {"member": "ensemble_id"},
        },
    }
    ds = xr.Dataset(
        {"T": (("member", "time"), np.zeros((2, 3)))},
        coords={"member": ["001", "002"], "time": range(3)},
    )
    src = CatalogSource("x", entry, FakeFS(), ensemble="r2")
    selected = src._apply_selection(ds)
    assert selected["T"].shape == (3,)


def _grouped_open_fixture(monkeypatch):
    """A CESM-shaped grouped store: realm subgroups differ per table."""
    import numpy as np
    import xarray as xr

    entry = {
        "driver": "zarr",
        "args": {
            "urlpath": "https://example.invalid/store.zarr",
            "group": "{{table}}/{{realm}}",
            "consolidated": True,
        },
        "parameters": {
            "table": {"type": "str", "default": "Amon"},
            "realm": {"type": "str", "default": "atmos_3d"},
        },
    }
    groups = [
        "Amon",
        "Amon/atmos_2d",
        "Amon/atmos_3d",
        "day",
        "day/atmos_2d",
        "Omon",
        "Omon/ocean_2d",
        "Omon/ocean_3d",
        "Lday",  # present but empty, as on the real store
    ]
    meta = {g: {"node_type": "group"} for g in groups}
    monkeypatch.setattr(
        CatalogSource, "_store_metadata", lambda self, store_url=None: meta
    )
    opened: list[str] = []

    def fake_open_zarr(url, *, group=None, **kwargs):
        if group not in meta:
            raise KeyError(f"'{group}' not found in consolidated metadata.")
        opened.append(group)
        return xr.Dataset({"TREFHT": ("time", np.zeros(2))})

    monkeypatch.setattr(xr, "open_zarr", fake_open_zarr)
    return entry, opened


def test_defaulted_realm_resolves_to_the_tables_only_subgroup(monkeypatch):
    """table='day' with the atmos_3d default opens day's only realm."""
    entry, opened = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS(), table="day")
    src.to_dask()
    assert opened == ["day/atmos_2d"]
    assert src._params["realm"] == "atmos_2d"


def test_existing_default_group_is_opened_unchanged(monkeypatch):
    entry, opened = _grouped_open_fixture(monkeypatch)
    CatalogSource("x", entry, FakeFS()).to_dask()
    assert opened == ["Amon/atmos_3d"]


def test_ambiguous_defaulted_realm_lists_the_choices(monkeypatch):
    from reflective_data_catalog.exceptions import DataNotFoundError

    entry, _ = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS(), table="Omon")
    with pytest.raises(DataNotFoundError, match=r"realm=.*'ocean_2d', 'ocean_3d'"):
        src.to_dask()


def test_explicit_missing_realm_is_never_substituted(monkeypatch):
    """An explicitly passed realm that does not exist errors with the options."""
    from reflective_data_catalog.exceptions import DataNotFoundError

    entry, opened = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS(), table="day", realm="atmos_3d")
    with pytest.raises(DataNotFoundError, match=r"under 'day'.*\['atmos_2d'\]"):
        src.to_dask()
    assert opened == []


def test_missing_table_lists_the_tables(monkeypatch):
    from reflective_data_catalog.exceptions import DataNotFoundError

    entry, _ = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS(), table="daily")
    with pytest.raises(DataNotFoundError, match=r"table=.*'Amon', 'Lday'"):
        src.to_dask()


def test_empty_table_group_says_so(monkeypatch):
    from reflective_data_catalog.exceptions import DataNotFoundError

    entry, _ = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS(), table="Lday")
    with pytest.raises(DataNotFoundError, match="'Lday' contains no realm groups"):
        src.to_dask()


def test_variant_defaults_select_the_variant_stores_groups(catalog):
    """The HiLLA experiment store has no Mon/atmos_2d; its variant defaults
    point at the ten-member surface group instead."""
    entry = catalog["sources"]["miroc_es2h_g6_1p5k_hilla"]
    baseline = CatalogSource("m", entry, FakeFS())
    assert (baseline._params["table"], baseline._params["realm"]) == (
        "Mon",
        "atmos_2d",
    )
    hilla = CatalogSource("m", entry, FakeFS(), variant="G6-1.5K-HiLLA")
    assert hilla._render("{{table}}/{{realm}}") == "Amon/atmos_2d_r10"
    # Explicit values still win over the variant's defaults.
    explicit = CatalogSource("m", entry, FakeFS(), variant="G6-1.5K-HiLLA", table="day")
    assert explicit._params["table"] == "day"
    assert explicit._params["realm"] == "atmos_2d_r10"
    # Variant defaults are defaults: the missing-group resolver may rebind them.
    assert "realm" not in explicit._explicit_params


def test_cesm_table_descriptions_omit_empty_groups(catalog):
    """Lday/Oyr exist but are empty in the CESM stores; they are not offered."""
    for name, entry in catalog["sources"].items():
        table = (entry.get("parameters") or {}).get("table") or {}
        description = table.get("description", "")
        assert "Lday" not in description and "Oyr" not in description, name


def test_list_realms_lists_a_tables_subgroups(monkeypatch):
    entry, _ = _grouped_open_fixture(monkeypatch)
    src = CatalogSource("x", entry, FakeFS())
    assert src.list_realms() == ["atmos_2d", "atmos_3d"]  # bound table: Amon
    assert src.list_realms(table="Omon") == ["ocean_2d", "ocean_3d"]
    assert src.list_realms(table="day") == ["atmos_2d"]
    with pytest.warns(UserWarning, match="no groups"):
        assert src.list_realms(table="Lday") == []
