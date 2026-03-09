"""Tests for FlexibleSourceConfig, FlexibleSourceRegistry, and SourceDiscovery."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from reflective_data_catalog.flexible_sources import (
    FlexibleSource,
    FlexibleSourceConfig,
    FlexibleSourceRegistry,
    SourceDiscovery,
)

# =========================================================================
# FlexibleSourceConfig
# =========================================================================


class TestFlexibleSourceConfig:
    """Tests for FlexibleSourceConfig dataclass."""

    def test_defaults_property(self, simple_config):
        defaults = simple_config.defaults
        assert defaults["table"] == "Amon"
        assert defaults["variable"] == "tas"
        assert defaults["ensemble"] == "r1i1p1f1"
        # No time or variant in simple_config
        assert "time" not in defaults
        assert "variant" not in defaults

    def test_defaults_with_time_and_variant(self, time_config, variant_config):
        td = time_config.defaults
        assert td["time"] == "AERmon"
        assert "variant" not in td

        vd = variant_config.defaults
        assert vd["variant"] == "baseline"

    def test_available_tables(self, simple_config):
        tables = simple_config.available_tables
        assert sorted(tables) == ["Amon", "Omon"]

    def test_available_tables_empty_mapping(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="s3://b/p",
            pattern="{base}/{variable}",
        )
        assert cfg.available_tables == []

    def test_has_filename_pattern(self, simple_config, multi_file_config):
        assert simple_config.has_filename_pattern is True
        cfg = FlexibleSourceConfig(
            name="no_fp",
            base="s3://b/p",
            pattern="{base}/{variable}",
        )
        assert cfg.has_filename_pattern is False

    def test_is_multi_file(self, simple_config, multi_file_config):
        # simple_config has pattern "{variable}.nc" — no wildcards
        assert simple_config.is_multi_file is False
        # multi_file_config has "model.h0.{variable}.*.nc"
        assert multi_file_config.is_multi_file is True

    # --- build_directory_path ---

    def test_build_directory_path_defaults(self, simple_config):
        path = simple_config.build_directory_path()
        assert path == "s3://test-bucket/model/experiment/r1i1p1f1/Amon"

    def test_build_directory_path_overrides(self, simple_config):
        path = simple_config.build_directory_path(
            table="Omon", variable="tos", ensemble="r2i1p1f1"
        )
        assert path == "s3://test-bucket/model/experiment/r2i1p1f1/Omon"

    def test_build_directory_path_table_mapping(self, simple_config):
        path = simple_config.build_directory_path(table="Omon")
        assert "Omon" in path

    def test_build_directory_path_with_ensemble_mapping(self, multi_file_config):
        path = multi_file_config.build_directory_path(ensemble="r2")
        # ensemble in path should still be "r2", not mapped
        assert "/r2/" in path

    def test_build_directory_path_with_time(self, time_config):
        path = time_config.build_directory_path()
        assert "/AERmon/" in path
        assert "/ua" in path

    def test_build_directory_path_with_variant(self, variant_config):
        # variant_config pattern does not include {variant} in directory
        path = variant_config.build_directory_path()
        assert path == "s3://test-bucket/MIROC/G6-HiLLA/Amon"

    # --- build_filename_glob ---

    def test_build_filename_glob_simple(self, simple_config):
        glob = simple_config.build_filename_glob()
        assert glob == "tas.nc"

    def test_build_filename_glob_none_pattern(self):
        cfg = FlexibleSourceConfig(
            name="nofp",
            base="s3://b/p",
            pattern="{base}/{variable}",
        )
        glob = cfg.build_filename_glob(variable="pr")
        assert glob == "pr.nc"

    def test_build_filename_glob_multi_file(self, multi_file_config):
        glob = multi_file_config.build_filename_glob()
        assert glob == "model.001.h0.T.*.nc"

    def test_build_filename_glob_ensemble_mapping(self, multi_file_config):
        glob = multi_file_config.build_filename_glob(ensemble="r2")
        assert "002" in glob

    def test_build_filename_glob_variant(self, variant_config):
        glob = variant_config.build_filename_glob()
        assert "baseline" in glob
        glob2 = variant_config.build_filename_glob(variant="G6-SAI")
        assert "G6-SAI" in glob2

    # --- build_url ---

    def test_build_url_combines_dir_and_filename(self, simple_config):
        url = simple_config.build_url()
        assert url == "s3://test-bucket/model/experiment/r1i1p1f1/Amon/tas.nc"

    def test_build_url_no_double_slash(self, simple_config):
        url = simple_config.build_url()
        # Should not have a double slash between dir and filename
        assert "//" not in url.replace("s3://", "")

    def test_build_url_multi_file(self, multi_file_config):
        url = multi_file_config.build_url(ensemble="r1")
        assert url.endswith("model.001.h0.T.*.nc")
        assert "001" in url

    # --- validate ---

    def test_validate_valid_config(self, simple_config):
        assert simple_config.validate() == []

    def test_validate_missing_name(self):
        cfg = FlexibleSourceConfig(
            name="",
            base="s3://b/p",
            pattern="{base}/{variable}",
        )
        errors = cfg.validate()
        assert any("name" in e for e in errors)

    def test_validate_missing_base(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="",
            pattern="{base}/{variable}",
        )
        errors = cfg.validate()
        assert any("base" in e.lower() for e in errors)

    def test_validate_no_scheme(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="bucket/path",
            pattern="{base}/{variable}",
        )
        errors = cfg.validate()
        assert any("cloud storage URL" in e for e in errors)

    def test_validate_bad_driver(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="s3://b/p",
            pattern="{base}/{variable}",
            driver="parquet",
        )
        errors = cfg.validate()
        assert any("driver" in e for e in errors)

    def test_validate_bad_combine_files(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="s3://b/p",
            pattern="{base}/{variable}",
            combine_files="invalid",
        )
        errors = cfg.validate()
        assert any("combine_files" in e for e in errors)

    def test_validate_no_variable_placeholder(self):
        cfg = FlexibleSourceConfig(
            name="x",
            base="s3://b/p",
            pattern="{base}/{ensemble}",
            filename_pattern="file.nc",
        )
        errors = cfg.validate()
        assert any("variable" in e.lower() for e in errors)

    def test_frozen(self, simple_config):
        with pytest.raises(AttributeError):
            simple_config.name = "changed"


# =========================================================================
# FlexibleSourceRegistry
# =========================================================================


class TestFlexibleSourceRegistry:
    """Tests for FlexibleSourceRegistry."""

    def test_register_and_get(self, simple_config):
        reg = FlexibleSourceRegistry()
        reg.register(simple_config)
        assert reg.get("test_source") is simple_config

    def test_register_duplicate_raises(self, simple_config):
        reg = FlexibleSourceRegistry()
        reg.register(simple_config)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(simple_config)

    def test_register_invalid_raises(self):
        bad_cfg = FlexibleSourceConfig(
            name="",
            base="s3://b/p",
            pattern="{base}/{variable}",
        )
        reg = FlexibleSourceRegistry()
        with pytest.raises(ValueError, match="Invalid configuration"):
            reg.register(bad_cfg)

    def test_unregister(self, simple_config):
        reg = FlexibleSourceRegistry()
        reg.register(simple_config)
        assert reg.unregister("test_source") is True
        assert reg.get("test_source") is None

    def test_unregister_missing(self):
        reg = FlexibleSourceRegistry()
        assert reg.unregister("missing") is False

    def test_contains(self, populated_registry):
        assert "test_source" in populated_registry
        assert "nonexistent" not in populated_registry

    def test_iter(self, populated_registry):
        names = list(populated_registry)
        assert "test_source" in names
        assert "test_multi" in names

    def test_items(self, populated_registry):
        items = dict(populated_registry.items())
        assert "test_source" in items
        assert items["test_source"].default_variable == "tas"

    def test_keys(self, populated_registry):
        assert set(populated_registry.keys()) == {"test_source", "test_multi"}

    def test_len(self, populated_registry):
        assert len(populated_registry) == 2


# =========================================================================
# SourceDiscovery
# =========================================================================


class TestSourceDiscovery:
    """Tests for SourceDiscovery (cloud scanning mocked)."""

    def test_init(self, simple_config):
        sd = SourceDiscovery(simple_config)
        assert sd.config is simple_config
        assert sd._cache == {}

    def test_clear_cache(self, simple_config):
        sd = SourceDiscovery(simple_config)
        sd._cache["key"] = [1, 2, 3]
        sd.clear_cache()
        assert sd._cache == {}

    def test_list_ensembles_no_placeholder(self, variant_config):
        """When pattern has no {ensemble}, return the default."""
        sd = SourceDiscovery(variant_config)
        ensembles = sd.list_ensembles()
        assert ensembles == [variant_config.default_ensemble]

    def test_list_ensembles_cache(self, simple_config):
        sd = SourceDiscovery(simple_config)
        sd._cache["ensembles"] = ["r1", "r2"]
        assert sd.list_ensembles() == ["r1", "r2"]

    def test_list_ensembles_refresh_bypasses_cache(self, simple_config):
        sd = SourceDiscovery(simple_config)
        sd._cache["ensembles"] = ["r1"]

        mock_fs = MagicMock()
        mock_fs.ls.return_value = [
            {"name": "s3://bucket/path/r1i1p1f1", "type": "directory"},
            {"name": "s3://bucket/path/r2i1p1f1", "type": "directory"},
        ]
        sd._fs = mock_fs

        result = sd.list_ensembles(refresh=True)
        assert result == ["r1i1p1f1", "r2i1p1f1"]

    def test_list_tables_with_mapping(self, simple_config):
        sd = SourceDiscovery(simple_config)
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        sd._fs = mock_fs

        tables = sd.list_tables()
        assert set(tables) == {"Amon", "Omon"}

    def test_list_tables_some_missing(self, simple_config):
        sd = SourceDiscovery(simple_config)
        mock_fs = MagicMock()

        def exists_side_effect(path):
            return "Amon" in path

        mock_fs.exists.side_effect = exists_side_effect
        sd._fs = mock_fs

        tables = sd.list_tables()
        assert tables == ["Amon"]

    def test_list_variables_from_glob(self, simple_config):
        sd = SourceDiscovery(simple_config)
        mock_fs = MagicMock()
        mock_fs.glob.return_value = [
            "s3://test-bucket/model/experiment/r1i1p1f1/Amon/tas.nc",
            "s3://test-bucket/model/experiment/r1i1p1f1/Amon/pr.nc",
            "s3://test-bucket/model/experiment/r1i1p1f1/Amon/tos.nc",
        ]
        sd._fs = mock_fs

        variables = sd.list_variables()
        assert variables == ["pr", "tas", "tos"]

    def test_list_variables_cache(self, simple_config):
        sd = SourceDiscovery(simple_config)
        sd._cache["variables_r1i1p1f1_Amon_"] = ["cached_var"]
        assert sd.list_variables() == ["cached_var"]

    def test_extract_variable_simple_nc(self, simple_config):
        sd = SourceDiscovery(simple_config)
        var = sd._extract_variable_from_filename(
            "tas.nc", "Amon", "r1i1p1f1", "", "r1i1p1f1", ""
        )
        assert var == "tas"

    def test_extract_variable_complex_pattern(self, multi_file_config):
        sd = SourceDiscovery(multi_file_config)
        var = sd._extract_variable_from_filename(
            "model.001.h0.T.20150101-20151231.nc",
            "ADAY",
            "r1",
            "",
            "001",
            "",
        )
        assert var == "T"

    def test_extract_variable_with_variant(self, variant_config):
        sd = SourceDiscovery(variant_config)
        var = sd._extract_variable_from_filename(
            "SurfT_baseline_r01.nc",
            "Amon",
            "r01",
            "baseline",
            "r01",
            "",
        )
        assert var == "SurfT"

    def test_extract_variable_no_match(self, simple_config):
        sd = SourceDiscovery(simple_config)
        var = sd._extract_variable_from_filename(
            "random_garbage.txt", "Amon", "r1", "", "r1", ""
        )
        assert var is None


# =========================================================================
# FlexibleSource
# =========================================================================


class TestFlexibleSource:
    """Tests for FlexibleSource wrapper."""

    def test_url_property(self, simple_config):
        mock_catalog = MagicMock()
        source = FlexibleSource(mock_catalog, simple_config)
        assert source.url == simple_config.build_url()
        assert source.urlpath == source.url

    def test_url_with_kwargs(self, simple_config):
        mock_catalog = MagicMock()
        source = FlexibleSource(
            mock_catalog, simple_config, variable="pr", ensemble="r2i1p1f1"
        )
        expected_url = simple_config.build_url(variable="pr", ensemble="r2i1p1f1")
        assert source.url == expected_url

    def test_config_property(self, simple_config):
        mock_catalog = MagicMock()
        source = FlexibleSource(mock_catalog, simple_config)
        assert source.config is simple_config

    def test_repr(self, simple_config):
        mock_catalog = MagicMock()
        source = FlexibleSource(mock_catalog, simple_config, variable="pr")
        r = repr(source)
        assert "test_source" in r
        assert "pr" in r
        assert "to_dask" in r

    def test_to_dask_delegates(self, simple_config):
        mock_catalog = MagicMock()
        mock_catalog._load_flexible.return_value = MagicMock(name="dataset")
        source = FlexibleSource(mock_catalog, simple_config, variable="pr")
        ds = source.to_dask()
        mock_catalog._load_flexible.assert_called_once_with(
            simple_config, lazy=True, variable="pr"
        )
        assert ds is not None

    def test_read_delegates(self, simple_config):
        mock_catalog = MagicMock()
        mock_catalog._load_flexible.return_value = MagicMock(name="dataset")
        source = FlexibleSource(mock_catalog, simple_config, variable="pr")
        source.read()
        mock_catalog._load_flexible.assert_called_once_with(
            simple_config, lazy=False, variable="pr"
        )

    def test_discovery_methods_exist(self, simple_config):
        mock_catalog = MagicMock()
        source = FlexibleSource(mock_catalog, simple_config)
        assert callable(source.list_ensembles)
        assert callable(source.list_tables)
        assert callable(source.list_variables)
        assert callable(source.discover)
        assert callable(source.describe)
