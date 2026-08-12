"""Integration tests for the ReflectiveCatalog façade.

These tests run the real shipped ``data-catalog.yaml`` through the real
loader — no per-test catalog stubbing. Only storage I/O (CloudFileSystem)
is ever mocked.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from reflective_data_catalog import ReflectiveCatalog
from reflective_data_catalog.exceptions import (
    CatalogError,
    SourceNotFoundError,
)
from reflective_data_catalog.loader import CatalogSource

PACKAGE = Path(__file__).parent.parent / "src" / "reflective_data_catalog"
CATALOG_PATH = PACKAGE / "data-catalog.yaml"

with CATALOG_PATH.open() as _f:
    ALL_ENTRY_NAMES = sorted(yaml.safe_load(_f)["sources"])


# =========================================================================
# Construction
# =========================================================================


class TestConstruction:
    """ReflectiveCatalog.__init__ parses and validates eagerly (R13)."""

    def test_default_packaged_path(self, real_catalog):
        assert str(real_catalog._catalog_path).endswith("data-catalog.yaml")
        assert len(real_catalog._entries) == len(ALL_ENTRY_NAMES)

    def test_custom_catalog_path(self, tmp_path):
        custom = tmp_path / "my-catalog.yaml"
        shutil.copy(CATALOG_PATH, custom)
        cat = ReflectiveCatalog(catalog_path=custom)
        assert cat._catalog_path == custom
        assert len(cat.list_sources(verbose=False)) == len(ALL_ENTRY_NAMES)

    def test_corrupt_yaml_fails_at_construction(self, tmp_path):
        corrupt = tmp_path / "corrupt.yaml"
        corrupt.write_text("sources: [unclosed\n  nonsense: {{{\n")
        with pytest.raises(CatalogError):
            ReflectiveCatalog(catalog_path=corrupt)

    def test_wrong_schema_version_fails_at_construction(self, tmp_path):
        stale = tmp_path / "stale.yaml"
        stale.write_text("metadata:\n  reflective_schema_version: 1\nsources: {}\n")
        with pytest.raises(CatalogError, match="schema version"):
            ReflectiveCatalog(catalog_path=stale)

    def test_missing_file_fails_at_construction(self, tmp_path):
        with pytest.raises(CatalogError, match="not readable"):
            ReflectiveCatalog(catalog_path=tmp_path / "does-not-exist.yaml")

    def test_helpers_initialised(self, real_catalog):
        assert real_catalog.esgf is not None
        assert real_catalog.esm is not None
        assert real_catalog.geomip_cloud is not None

    def test_geomip_cloud_shares_esm_catalog(self, real_catalog):
        # One ESMCatalog per ReflectiveCatalog: geomip_cloud reuses it.
        assert real_catalog.geomip_cloud.catalog is real_catalog.esm


# =========================================================================
# Attribute dispatch
# =========================================================================


class TestGetattr:
    """Dynamic attribute access dispatches to catalog entries."""

    def test_entry_returns_callable(self, real_catalog):
        loader_fn = real_catalog.miroc_es2h_g6_1p5k_hilla
        assert callable(loader_fn)
        source = loader_fn()
        assert isinstance(source, CatalogSource)
        assert source.name == "miroc_es2h_g6_1p5k_hilla"

    @pytest.mark.parametrize("name", ALL_ENTRY_NAMES)
    def test_getattr_works_for_every_entry(self, real_catalog, name):
        source = getattr(real_catalog, name)()
        assert isinstance(source, CatalogSource)
        assert source.name == name

    def test_unknown_name_raises_with_suggestion(self, real_catalog):
        with pytest.raises(SourceNotFoundError, match="cesm2_waccm_ssp245"):
            _ = real_catalog.cesm2_waccm_ssp246

    def test_unknown_name_mentions_list_sources(self, real_catalog):
        with pytest.raises(SourceNotFoundError, match="list_sources"):
            _ = real_catalog.totally_nonexistent_source

    def test_hasattr_is_false_for_unknown(self, real_catalog):
        assert not hasattr(real_catalog, "nope")

    def test_source_not_found_is_attribute_error(self, real_catalog):
        assert issubclass(SourceNotFoundError, AttributeError)
        with pytest.raises(AttributeError):
            _ = real_catalog.nope

    def test_private_attribute_raises_plain_attribute_error(self, real_catalog):
        with pytest.raises(AttributeError):
            _ = real_catalog._nonexistent

    def test_dir_is_exactly_entries_plus_public_surface(self, real_catalog):
        # An exact match proves removed accessors (e.g. the old config
        # getter) are gone from the advertised surface, not just present.
        expected = sorted(
            set(ALL_ENTRY_NAMES)
            | {
                "esm",
                "esgf",
                "geomip_cloud",
                "list_sources",
                "list_tags",
                "search",
                "help",
                "get_parameters",
                "show_parameters",
                "get_source",
            }
        )
        assert dir(real_catalog) == expected


# =========================================================================
# get_source
# =========================================================================


class TestGetSource:
    """String-keyed access mirrors attribute dispatch."""

    def test_round_trip(self, real_catalog):
        source = real_catalog.get_source("ukesm1_ssp245", variable="pr")
        assert isinstance(source, CatalogSource)
        assert source.url.endswith("pr.zarr")

    def test_matches_attribute_dispatch(self, real_catalog):
        via_attr = real_catalog.ukesm1_ssp245(variable="pr").url
        via_name = real_catalog.get_source("ukesm1_ssp245", variable="pr").url
        assert via_attr == via_name

    def test_unknown_raises_source_not_found(self, real_catalog):
        with pytest.raises(SourceNotFoundError, match="ukesm1_ssp245"):
            real_catalog.get_source("ukesm1_ssp254")

    def test_every_search_entry_resolves(self, real_catalog):
        records = real_catalog.search(verbose=False)
        entry_records = [r for r in records if r["kind"] == "entry"]
        assert len(entry_records) == len(ALL_ENTRY_NAMES)
        for record in entry_records:
            source = real_catalog.get_source(record["name"])
            assert isinstance(source, CatalogSource)


# =========================================================================
# Keyword arguments: typos, aliases, removed kwargs
# =========================================================================


class TestKwargs:
    """Unknown kwargs fail loudly (AE1) with migration guidance (R12/AE2)."""

    def test_typo_raises_typeerror_naming_kwarg_and_valid_params(self, real_catalog):
        with pytest.raises(TypeError) as excinfo:
            real_catalog.cesm2_waccm_ssp245(varaible="SALT")
        message = str(excinfo.value)
        assert "varaible" in message
        assert "realm" in message  # valid parameter listing
        assert "ensemble" in message
        assert "table" in message

    def test_alias_ensemble_member_gives_same_url(self, real_catalog):
        canonical = real_catalog.cesm2_waccm_ssp245(ensemble="r2").url
        aliased = real_catalog.cesm2_waccm_ssp245(ensemble_member="r2").url
        assert canonical == aliased

    def test_alias_member_id_gives_same_url(self, real_catalog):
        canonical = real_catalog.ukesm1_g6_1p5k_hilla(ensemble="r2i1p1f2").url
        aliased = real_catalog.ukesm1_g6_1p5k_hilla(member_id="r2i1p1f2").url
        assert canonical == aliased

    def test_removed_time_kwarg_redirects_to_migration_guide(self, real_catalog):
        with pytest.raises(TypeError) as excinfo:
            real_catalog.ukesm1_g6_1p5k_hilla(time="AERmon")
        message = str(excinfo.value)
        assert "time" in message
        assert "migration" in message.lower()

    def test_removed_time_kwarg_on_ukesm_ssp245(self, real_catalog):
        with pytest.raises(TypeError, match=r"[Mm]igration"):
            real_catalog.ukesm1_ssp245(time="AERmon")


# =========================================================================
# value_map derivation
# =========================================================================


class TestValueMap:
    """Derived parameters (R4) render into URLs."""

    def test_cesm_historical_ensemble_r2_maps_to_002(self, real_catalog):
        url = real_catalog.cesm2_waccm_historical(ensemble="r2").url
        assert "/r2/" in url
        assert ".002.pop." in url

    def test_derived_param_cannot_be_set_directly(self, real_catalog):
        with pytest.raises(TypeError, match="derived"):
            real_catalog.cesm2_waccm_historical(ensemble_id="007")


# =========================================================================
# list_sources / list_tags
# =========================================================================


class TestListSources:
    """list_sources returns records and only prints when verbose."""

    def test_returns_one_record_per_entry(self, real_catalog):
        records = real_catalog.list_sources(verbose=False)
        assert len(records) == len(ALL_ENTRY_NAMES)
        for record in records:
            assert set(record) == {
                "name",
                "kind",
                "driver",
                "stability",
                "tags",
                "description",
            }
            assert record["kind"] == "entry"
            assert record["driver"] in {"zarr", "netcdf"}

    def test_stability_comes_from_matrix(self, real_catalog):
        by_name = {r["name"]: r for r in real_catalog.list_sources(verbose=False)}
        assert by_name["ukesm1_g6_1p5k_hilla"]["stability"] == "stable"
        assert by_name["ukesm1_g6_1p5k_sai"]["stability"] == "experimental"

    def test_verbose_false_prints_nothing(self, real_catalog, capsys):
        real_catalog.list_sources(verbose=False)
        assert capsys.readouterr().out == ""

    def test_verbose_true_prints_listing(self, real_catalog, capsys):
        records = real_catalog.list_sources()
        out = capsys.readouterr().out
        assert "AVAILABLE DATA SOURCES" in out
        assert "cesm2_waccm_g6_1p5k_hilla" in out
        assert len(records) == len(ALL_ENTRY_NAMES)  # returned even when printing

    def test_tag_filter(self, real_catalog):
        records = real_catalog.list_sources(tag="ocean", verbose=False)
        names = {r["name"] for r in records}
        assert names == {"cesm2_waccm_historical", "cesm2_waccm_ssp245"}

    def test_driver_filter(self, real_catalog):
        records = real_catalog.list_sources(driver="netcdf", verbose=False)
        assert records
        assert all(r["driver"] == "netcdf" for r in records)


class TestListTags:
    """list_tags returns sorted unique tags."""

    def test_returns_sorted_unique(self, real_catalog):
        tags = real_catalog.list_tags(verbose=False)
        assert tags == sorted(set(tags))
        assert "SAI" in tags
        assert "ocean" in tags

    def test_verbose_false_prints_nothing(self, real_catalog, capsys):
        real_catalog.list_tags(verbose=False)
        assert capsys.readouterr().out == ""


# =========================================================================
# search
# =========================================================================


class TestSearch:
    """search returns records; entries resolve, helper rows are suggestions."""

    def test_search_by_term(self, real_catalog):
        records = real_catalog.search(term="miroc", verbose=False)
        names = {r["name"] for r in records if r["kind"] == "entry"}
        assert names == {"miroc_es2h_g6_1p5k_hilla", "miroc_es2h_g6_1p5k_sai"}

    def test_search_by_variable(self, real_catalog):
        records = real_catalog.search(variable="TEMP", verbose=False)
        entry_names = {r["name"] for r in records if r["kind"] == "entry"}
        # Only the NetCDF fallback still declares variable as a parameter;
        # grouped Zarr stores select variables from the opened dataset.
        assert entry_names == {"cesm2_waccm_historical"}

    def test_search_by_tag(self, real_catalog):
        records = real_catalog.search(tag="ocean", verbose=False)
        # Tag filtering excludes helper suggestions entirely.
        assert all(r["kind"] == "entry" for r in records)
        assert {r["name"] for r in records} == {
            "cesm2_waccm_historical",
            "cesm2_waccm_ssp245",
        }

    def test_search_no_matches(self, real_catalog):
        assert real_catalog.search(term="zzzzz_no_match", verbose=False) == []

    def test_record_shape(self, real_catalog):
        for record in real_catalog.search(verbose=False):
            assert set(record) == {"name", "kind", "driver", "description"}
            assert record["kind"] in {"entry", "esm", "esgf"}

    def test_helper_suggestions_present_but_cheap(self, real_catalog):
        records = real_catalog.search(term="g6sulfur", verbose=False)
        kinds = {r["kind"] for r in records}
        assert "esgf" in kinds  # static suggestion rows survive
        # and none of them claim to be resolvable entries
        for record in records:
            if record["kind"] != "entry":
                assert record["name"] not in ALL_ENTRY_NAMES

    def test_verbose_false_prints_nothing(self, real_catalog, capsys):
        real_catalog.search(term="miroc", verbose=False)
        assert capsys.readouterr().out == ""

    def test_verbose_true_prints_results(self, real_catalog, capsys):
        real_catalog.search(term="miroc")
        out = capsys.readouterr().out
        assert "SEARCH RESULTS" in out
        assert "miroc_es2h_g6_1p5k_sai" in out


# =========================================================================
# get_parameters / show_parameters
# =========================================================================


class TestGetParameters:
    """get_parameters has one unified shape for every entry."""

    def test_unified_shape(self, real_catalog):
        info = real_catalog.get_parameters("miroc_es2h_g6_1p5k_sai")
        assert set(info) == {"name", "driver", "description", "parameters"}
        assert info["name"] == "miroc_es2h_g6_1p5k_sai"
        assert info["driver"] == "zarr"
        assert "variant" in info["parameters"]
        assert "is_flexible" not in info

    @pytest.mark.parametrize("name", ALL_ENTRY_NAMES)
    def test_every_entry_has_parameters(self, real_catalog, name):
        info = real_catalog.get_parameters(name)
        assert info["parameters"], name

    def test_unknown_raises_source_not_found(self, real_catalog):
        with pytest.raises(SourceNotFoundError):
            real_catalog.get_parameters("definitely_not_here")


class TestShowParameters:
    """show_parameters prints the unified parameter dict."""

    def test_prints_parameters(self, real_catalog, capsys):
        real_catalog.show_parameters("cesm2_waccm_g6_1p5k_hilla")
        out = capsys.readouterr().out
        assert "PARAMETERS" in out
        assert "cesm2_waccm_g6_1p5k_hilla" in out
        assert "ensemble" in out

    def test_unknown_raises_source_not_found(self, real_catalog):
        with pytest.raises(SourceNotFoundError):
            real_catalog.show_parameters("nope")

    @pytest.mark.filterwarnings("ignore::UserWarning")  # empty variable scan
    def test_discover_uses_mocked_storage(self, real_catalog, mock_fs, capsys):
        mock_fs.ls.return_value = [
            "reflective-persistent-prod-large/UKESM1-1/SSP245/r1i1p1f2",
            "reflective-persistent-prod-large/UKESM1-1/SSP245/r2i1p1f2",
        ]
        real_catalog._fs = mock_fs
        real_catalog.show_parameters("ukesm1_ssp245", discover=True)
        out = capsys.readouterr().out
        assert "AVAILABLE DATA (from cloud storage scan):" in out
        assert "r2i1p1f2" in out
        assert mock_fs.ls.called  # only storage I/O was mocked


# =========================================================================
# help
# =========================================================================


class TestHelp:
    """help() output is generated from the loaded catalog."""

    def test_general_help_lists_catalog_entries(self, real_catalog, capsys):
        real_catalog.help()
        out = capsys.readouterr().out
        assert "DATA CATALOG" in out
        # Generated from the catalog, not hand-maintained text:
        assert "miroc_es2h_g6_1p5k_hilla" in out
        for name in ALL_ENTRY_NAMES:
            assert name in out

    def test_source_help_prints_parameters(self, real_catalog, capsys):
        real_catalog.help("cesm2_waccm_g6_1p5k_hilla")
        out = capsys.readouterr().out
        assert "PARAMETERS" in out
        assert "cesm2_waccm_g6_1p5k_hilla" in out


class TestValueGuidance:
    """AE2: pre-1.0 parameter values raise guidance naming the new vocabulary."""

    def test_old_table_value_names_new_vocabulary(self, real_catalog):
        from reflective_data_catalog.exceptions import DataNotFoundError

        with pytest.raises(DataNotFoundError) as excinfo:
            real_catalog.cesm2_waccm_g6_1p5k_hilla(table="AMON")
        message = str(excinfo.value)
        assert "cesm2_waccm_g6_1p5k_hilla" in message
        assert "'AMON'" in message
        assert "'Amon'" in message
        assert "migration" in message.lower()

    def test_old_ukesm_stream_table_guided(self, real_catalog):
        from reflective_data_catalog.exceptions import DataNotFoundError

        with pytest.raises(DataNotFoundError, match=r"pre-1\.0 vocabulary"):
            real_catalog.ukesm1_g6_1p5k_hilla(table="ap4")

    def test_preserved_vocabulary_still_accepted(self, real_catalog):
        # NetCDF-preserving entries kept their values: no false guidance.
        src = real_catalog.cesm2_waccm_historical(table="OMON", variable="TEMP")
        assert "/OMON/" in src.url

    def test_new_vocabulary_passes_untouched(self, real_catalog):
        src = real_catalog.cesm2_waccm_g6_1p5k_hilla(table="Amon")
        group = src._render(src.config["args"]["group"])
        assert group.startswith("Amon/")
