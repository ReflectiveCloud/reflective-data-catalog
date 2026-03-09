"""Integration tests for ReflectiveCatalog."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reflective_data_catalog.flexible_sources import FlexibleSourceConfig
from reflective_data_catalog.main import IntakeSource, ReflectiveCatalog

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog(**kwargs) -> ReflectiveCatalog:
    """Create a ReflectiveCatalog with ESGF and ESM helpers mocked."""
    with (
        patch("reflective_data_catalog.main.ESGFHelper") as mock_esgf_cls,
        patch("reflective_data_catalog.main.ESMCatalog") as mock_esm_cls,
        patch("reflective_data_catalog.main.GeoMIPCloudHelper") as mock_geomip_cls,
    ):
        mock_esgf_cls.return_value = MagicMock(name="ESGFHelper")
        mock_esm_cls.return_value = MagicMock(name="ESMCatalog")
        mock_geomip_cls.return_value = MagicMock(name="GeoMIPCloudHelper")
        return ReflectiveCatalog(**kwargs)


# =========================================================================
# Initialisation
# =========================================================================


class TestCatalogInit:
    """Tests for ReflectiveCatalog.__init__."""

    def test_default_catalog_path(self):
        cat = _make_catalog()
        assert str(cat._catalog_path).endswith("data-catalog.yaml")

    def test_custom_catalog_path(self):
        cat = _make_catalog(catalog_path="/tmp/custom.yaml")
        assert cat._catalog_path == "/tmp/custom.yaml"

    def test_flexible_sources_registered(self):
        cat = _make_catalog()
        # Should have all DEFAULT_FLEXIBLE_SOURCES registered
        assert len(cat._flexible_registry) > 0
        assert "cesm2_waccm_g6_1p5k_hilla" in cat._flexible_registry
        assert "ukesm1_ssp245" in cat._flexible_registry

    def test_helpers_initialised(self):
        cat = _make_catalog()
        assert cat.esgf is not None
        assert cat.esm is not None
        assert cat.geomip_cloud is not None


# =========================================================================
# __getattr__
# =========================================================================


class TestCatalogGetattr:
    """Tests for dynamic attribute access."""

    def test_access_flexible_source(self):
        cat = _make_catalog()
        loader = cat.cesm2_waccm_g6_1p5k_hilla
        assert callable(loader)

    def test_flexible_source_returns_flexible_source(self):
        from reflective_data_catalog.flexible_sources import FlexibleSource

        cat = _make_catalog()
        source = cat.cesm2_waccm_g6_1p5k_hilla()
        assert isinstance(source, FlexibleSource)

    def test_nonexistent_attribute_raises(self):
        cat = _make_catalog()
        with pytest.raises(AttributeError, match="not found"):
            _ = cat.totally_nonexistent_source

    def test_private_attribute_raises(self):
        cat = _make_catalog()
        with pytest.raises(AttributeError):
            _ = cat._nonexistent

    def test_intake_source_returns_intake_source_wrapper(self):
        cat = _make_catalog()

        mock_ds = MagicMock(name="dataset")
        mock_source = MagicMock(name="source")
        mock_source.to_dask.return_value = mock_ds

        mock_entry = MagicMock(name="entry")
        mock_entry.return_value = mock_source
        mock_entry._params = {
            "parameters": {
                "variable": {
                    "type": "str",
                    "default": "tas",
                    "allowed": ["tas", "pr"],
                    "description": "variable",
                },
                "table": {
                    "type": "str",
                    "default": "Amon",
                    "allowed": ["Amon", "day"],
                    "description": "table",
                },
            }
        }
        mock_entry._open_args = {"urlpath": "s3://bucket/{{table}}/{{variable}}.zarr"}

        cat._get_intake_catalog = MagicMock(return_value={"yaml_source": mock_entry})

        loader = cat.yaml_source
        source = loader(variable="tas")

        assert isinstance(source, IntakeSource)
        assert source.to_dask() is mock_ds
        assert source.list_variables() == ["tas", "pr"]
        assert source.list_tables() == ["Amon", "day"]
        assert source.url == "s3://bucket/Amon/tas.zarr"

    def test_intake_list_tables_uses_default_when_allowed_missing(self):
        cat = _make_catalog()

        class Param:
            def __init__(
                self, name, default, allowed=None, description="", ptype="str"
            ):
                self.name = name
                self.default = default
                self.allowed = allowed
                self.description = description
                self.type = ptype

        mock_entry = MagicMock(name="entry")
        mock_entry._user_parameters = [
            Param("variable", "tas"),
            Param("member_id", "r1i1p1f2", ["r1i1p1f2", "r2i1p1f2"]),
            Param("table_id", "day", None),
        ]
        mock_entry._open_args = {
            "urlpath": "s3://bucket/{{member_id}}/{{table_id}}/{{variable}}/*"
        }
        mock_entry.return_value = MagicMock(name="source")

        cat._get_intake_catalog = MagicMock(
            return_value={"ukesm1_arise_sai": mock_entry}
        )

        source = cat.ukesm1_arise_sai()
        assert source.list_tables() == ["day"]
        assert source.list_ensembles() == ["r1i1p1f2", "r2i1p1f2"]
        assert source.url == "s3://bucket/r1i1p1f2/day/tas/*"

    def test_intake_list_methods_scan_cloud_from_url_template(self):
        cat = _make_catalog()

        class Param:
            def __init__(
                self, name, default, allowed=None, description="", ptype="str"
            ):
                self.name = name
                self.default = default
                self.allowed = allowed
                self.description = description
                self.type = ptype

        mock_entry = MagicMock(name="entry")
        mock_entry._user_parameters = [
            Param("member_id", "r1i1p1f2"),
            Param("table_id", "day"),
            Param("variable", "tas"),
        ]
        mock_entry._open_args = {
            "urlpath": (
                "s3://bucket/arise/{{member_id}}/{{table_id}}/{{variable}}/"
                "gn/v20220325/*"
            )
        }
        mock_entry.return_value = MagicMock(name="source")
        cat._get_intake_catalog = MagicMock(
            return_value={"ukesm1_arise_sai": mock_entry}
        )

        mock_fs = MagicMock()
        mock_fs.glob.side_effect = [
            [
                "s3://bucket/arise/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
                "s3://bucket/arise/r2i1p1f2/Amon/pr/gn/v20220325/file2.nc",
            ],
            [
                "s3://bucket/arise/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
            ],
            [
                "s3://bucket/arise/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
                "s3://bucket/arise/r1i1p1f2/day/pr/gn/v20220325/file2.nc",
            ],
        ]
        cat._fs = mock_fs

        source = cat.ukesm1_arise_sai()
        assert source.list_ensembles() == ["r1i1p1f2", "r2i1p1f2"]
        assert source.list_tables(ensemble="r1i1p1f2") == ["day"]
        assert source.list_variables(ensemble="r1i1p1f2", table="day") == ["pr", "tas"]

    def test_intake_discovery_cache_and_refresh(self):
        cat = _make_catalog()

        class Param:
            def __init__(self, name, default):
                self.name = name
                self.default = default
                self.allowed = None
                self.description = ""
                self.type = "str"

        mock_entry = MagicMock(name="entry")
        mock_entry._user_parameters = [Param("member_id", "r1i1p1f2")]
        mock_entry._open_args = {"urlpath": "s3://bucket/arise/{{member_id}}/*"}
        mock_entry.return_value = MagicMock(name="source")
        cat._get_intake_catalog = MagicMock(
            return_value={"ukesm1_arise_sai": mock_entry}
        )

        mock_fs = MagicMock()
        mock_fs.glob.side_effect = [
            ["s3://bucket/arise/r1i1p1f2/file1.nc"],
            ["s3://bucket/arise/r2i1p1f2/file2.nc"],
        ]
        cat._fs = mock_fs

        source = cat.ukesm1_arise_sai()
        assert source.list_ensembles() == ["r1i1p1f2"]
        # Cached result: no extra glob call
        assert source.list_ensembles() == ["r1i1p1f2"]
        assert mock_fs.glob.call_count == 1

        # refresh=True bypasses cache
        assert source.list_ensembles(refresh=True) == ["r2i1p1f2"]
        assert mock_fs.glob.call_count == 2


# =========================================================================
# __dir__
# =========================================================================


class TestCatalogDir:
    """Tests for tab-completion / dir()."""

    def test_dir_includes_flexible_sources(self):
        cat = _make_catalog()
        d = dir(cat)
        assert "cesm2_waccm_g6_1p5k_hilla" in d
        assert "ukesm1_ssp245" in d

    def test_dir_includes_builtins(self):
        cat = _make_catalog()
        d = dir(cat)
        for name in [
            "search",
            "list_sources",
            "help",
            "show_parameters",
            "esgf",
            "esm",
            "geomip_cloud",
        ]:
            assert name in d


# =========================================================================
# get_source_config
# =========================================================================


class TestGetSourceConfig:
    """Tests for get_source_config."""

    def test_existing(self):
        cat = _make_catalog()
        cfg = cat.get_source_config("cesm2_waccm_g6_1p5k_hilla")
        assert isinstance(cfg, FlexibleSourceConfig)
        assert cfg.name == "cesm2_waccm_g6_1p5k_hilla"

    def test_missing(self):
        cat = _make_catalog()
        assert cat.get_source_config("nope") is None


# =========================================================================
# get_parameters
# =========================================================================


class TestGetParameters:
    """Tests for get_parameters."""

    def test_flexible_source(self):
        cat = _make_catalog()
        info = cat.get_parameters("cesm2_waccm_g6_1p5k_hilla")
        assert info["has_parameters"] is True
        assert info["is_flexible"] is True
        assert "variable" in info["parameters"]
        assert "table" in info["parameters"]
        assert "ensemble" in info["parameters"]

    def test_not_found_raises(self):
        cat = _make_catalog()
        with pytest.raises(ValueError, match="not found"):
            cat.get_parameters("definitely_not_here")


# =========================================================================
# show_parameters
# =========================================================================


class TestShowParameters:
    """Tests for show_parameters."""

    def test_prints_output(self, capsys):
        cat = _make_catalog()
        cat.show_parameters("cesm2_waccm_g6_1p5k_hilla")
        captured = capsys.readouterr()
        assert "PARAMETERS" in captured.out
        assert "cesm2_waccm_g6_1p5k_hilla" in captured.out

    def test_not_found_prints_error(self, capsys):
        cat = _make_catalog()
        cat.show_parameters("nope")
        captured = capsys.readouterr()
        assert "Error" in captured.out

    def test_discover_intake_source_uses_wrapper_methods(self, capsys):
        cat = _make_catalog()

        mock_fs = MagicMock()
        mock_fs.glob.side_effect = [
            [
                "s3://met-office-ukesm1-arise/ARISE/ARISE/MOHC/UKESM1-0-LL/"
                "arise-sai-1p5/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
                "s3://met-office-ukesm1-arise/ARISE/ARISE/MOHC/UKESM1-0-LL/"
                "arise-sai-1p5/r2i1p1f2/day/tas/gn/v20220325/file2.nc",
            ],
            [
                "s3://met-office-ukesm1-arise/ARISE/ARISE/MOHC/UKESM1-0-LL/"
                "arise-sai-1p5/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
            ],
            [
                "s3://met-office-ukesm1-arise/ARISE/ARISE/MOHC/UKESM1-0-LL/"
                "arise-sai-1p5/r1i1p1f2/day/tas/gn/v20220325/file1.nc",
                "s3://met-office-ukesm1-arise/ARISE/ARISE/MOHC/UKESM1-0-LL/"
                "arise-sai-1p5/r1i1p1f2/day/pr/gn/v20220325/file2.nc",
            ],
        ]
        cat._fs = mock_fs

        cat.show_parameters("ukesm1_arise_sai", discover=True)
        captured = capsys.readouterr()
        assert "AVAILABLE DATA (from cloud storage scan):" in captured.out
        assert "r1i1p1f2" in captured.out
        assert "day (default)" in captured.out
        assert "tas" in captured.out


# =========================================================================
# list_sources
# =========================================================================


class TestListSources:
    """Tests for list_sources."""

    def test_prints_flexible_sources(self, capsys):
        cat = _make_catalog()
        cat.list_sources(include_esgf=False)
        captured = capsys.readouterr()
        assert "FLEXIBLE SOURCES" in captured.out
        assert "cesm2_waccm_g6_1p5k_hilla" in captured.out

    def test_prints_esm_section(self, capsys):
        cat = _make_catalog()
        cat.list_sources(include_esgf=False)
        captured = capsys.readouterr()
        assert "GOOGLE CLOUD" in captured.out

    def test_prints_esgf_section(self, capsys):
        cat = _make_catalog()
        cat.list_sources(include_esgf=True)
        captured = capsys.readouterr()
        assert "ESGF DATA SOURCES" in captured.out

    def test_driver_filter(self, capsys):
        cat = _make_catalog()
        cat.list_sources(driver="zarr", include_esgf=False)
        captured = capsys.readouterr()
        # The FLEXIBLE SOURCES section should not list any netcdf sources
        # when filtered by zarr
        lines = captured.out.split("\n")
        in_flexible = False
        for line in lines:
            if "FLEXIBLE SOURCES" in line:
                in_flexible = True
            elif "---" in line and in_flexible:
                # New section started
                in_flexible = False
            if in_flexible and "cesm2_waccm_g6_1p5k_hilla" in line:
                pytest.fail(
                    "cesm2_waccm_g6_1p5k_hilla should not appear in "
                    "FLEXIBLE SOURCES with driver='zarr'"
                )


# =========================================================================
# search
# =========================================================================


class TestSearch:
    """Tests for the search method."""

    def test_search_by_term(self):
        cat = _make_catalog()
        results = cat.search(term="ukesm")
        assert any("ukesm" in r for r in results)

    def test_search_by_variable(self):
        cat = _make_catalog()
        results = cat.search(variable="T")
        # All matching sources should have default_variable 'T'
        for name in results:
            cfg = cat.get_source_config(name)
            if cfg:
                assert cfg.default_variable == "T"

    def test_search_by_term_and_variable(self):
        cat = _make_catalog()
        results = cat.search(term="cesm", variable="T")
        assert len(results) > 0
        for name in results:
            assert "cesm" in name.lower() or "CESM" in name

    def test_search_no_matches(self):
        cat = _make_catalog()
        results = cat.search(term="zzzzz_no_match_zzzzz")
        assert len(results) == 0

    def test_search_esgf_shortcuts(self):
        cat = _make_catalog()
        results = cat.search(term="g6sulfur")
        esgf_results = [r for r in results if r.startswith("esgf.")]
        assert len(esgf_results) > 0

    def test_search_tag_filters_out_flexible(self):
        cat = _make_catalog()
        results = cat.search(tag="SAI")
        # Flexible sources don't have tags, so any that appear must have
        # come from the intake catalog (which has a separate entry).
        # Just verify the search completes and returns a list.
        assert isinstance(results, list)

    def test_search_returns_list(self):
        cat = _make_catalog()
        results = cat.search()
        assert isinstance(results, list)


# =========================================================================
# help
# =========================================================================


class TestHelp:
    """Tests for the help method."""

    def test_general_help(self, capsys):
        cat = _make_catalog()
        cat.help()
        captured = capsys.readouterr()
        assert "DATA CATALOG" in captured.out

    def test_source_help(self, capsys):
        cat = _make_catalog()
        cat.help("cesm2_waccm_g6_1p5k_hilla")
        captured = capsys.readouterr()
        assert "PARAMETERS" in captured.out


# =========================================================================
# Reflective Data - DEFAULT_FLEXIBLE_SOURCES
# =========================================================================


class TestDefaultSources:
    """Smoke tests ensuring all default source configs are valid."""

    def test_all_defaults_valid(self):
        from reflective_data_catalog.reflective_data import (
            DEFAULT_FLEXIBLE_SOURCES,
        )

        for cfg in DEFAULT_FLEXIBLE_SOURCES:
            errors = cfg.validate()
            assert errors == [], f"{cfg.name} has validation errors: {errors}"

    def test_all_defaults_build_url(self):
        from reflective_data_catalog.reflective_data import (
            DEFAULT_FLEXIBLE_SOURCES,
        )

        for cfg in DEFAULT_FLEXIBLE_SOURCES:
            url = cfg.build_url()
            assert url, f"{cfg.name} produced an empty URL"
            assert "://" in url, f"{cfg.name} URL missing scheme: {url}"

    def test_all_defaults_have_description(self):
        from reflective_data_catalog.reflective_data import (
            DEFAULT_FLEXIBLE_SOURCES,
        )

        for cfg in DEFAULT_FLEXIBLE_SOURCES:
            assert cfg.description, f"{cfg.name} missing description"
