"""Tests for ESGFHelper with mocked intake-esgf."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from reflective_data_catalog.esgf import (
    ESGFHelper,
    GeoMIPHelper,
    SSPHelper,
)

# =========================================================================
# ESGFHelper
# =========================================================================


class TestESGFHelper:
    """Tests for the top-level ESGFHelper class."""

    def test_init(self):
        helper = ESGFHelper()
        assert helper._esgf_cat is None
        assert isinstance(helper.geomip, GeoMIPHelper)
        assert isinstance(helper.ssp, SSPHelper)

    def test_get_catalog_lazy(self):
        mock_cat = MagicMock()
        with patch(
            "reflective_data_catalog.esgf._new_catalog", return_value=mock_cat
        ) as new:
            helper = ESGFHelper(cache_url="s3://b/c")
            assert helper._get_catalog() is mock_cat
            assert helper._get_catalog() is mock_cat  # cached
            new.assert_called_once_with("s3://b/c")

    def test_new_catalog_attaches_s3_cache(self, monkeypatch):
        from reflective_data_catalog import esgf as esgf_mod

        class FakeCatalog:
            pass

        monkeypatch.setattr(esgf_mod, "cached_catalog_class", lambda: FakeCatalog)
        monkeypatch.delenv("REFLECTIVE_ESGF_CACHE", raising=False)
        cat = esgf_mod._new_catalog()
        assert cat.s3_cache.url == "s3://reflective-persistent-prod-large/esgf-cache"
        assert esgf_mod._new_catalog("off").s3_cache is None
        monkeypatch.setenv("REFLECTIVE_ESGF_CACHE", "off")
        assert esgf_mod._new_catalog().s3_cache is None

    def test_set_cache_resets_catalog(self, monkeypatch):
        monkeypatch.delenv("REFLECTIVE_ESGF_CACHE", raising=False)
        helper = ESGFHelper()
        assert helper.cache_url.startswith("s3://reflective-persistent-prod-large")
        helper._esgf_cat = MagicMock()
        helper.set_cache("off")
        assert helper._esgf_cat is None
        assert helper.cache_url is None

    def test_get_catalog_import_error(self):
        helper = ESGFHelper()
        with (
            patch.dict(
                "sys.modules",
                {"intake_esgf": None},
            ),
            pytest.raises(ImportError, match="intake-esgf"),
        ):
            helper._get_catalog()

    def test_search_delegates(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        helper._esgf_cat = mock_cat

        helper.search(project="CMIP6", experiment_id="G6sulfur")
        mock_cat.search.assert_called_once_with(
            project="CMIP6", experiment_id="G6sulfur"
        )

    def test_list_experiments_returns_sorted(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame(
            {
                "experiment_id": ["G6solar", "G6sulfur", "G6sulfur"],
            }
        )
        mock_cat.search.return_value = mock_results
        helper._esgf_cat = mock_cat

        experiments = helper.list_experiments(activity_id="GeoMIP")
        assert experiments == ["G6solar", "G6sulfur"]

    def test_list_experiments_empty(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame(columns=["experiment_id"])
        mock_cat.search.return_value = mock_results
        helper._esgf_cat = mock_cat

        result = helper.list_experiments()
        assert result == []

    def test_list_experiments_error(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        mock_cat.search.side_effect = RuntimeError("network")
        helper._esgf_cat = mock_cat

        result = helper.list_experiments()
        assert result == []

    def test_list_variables(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame({"variable_id": ["tas", "pr", "tas"]})
        mock_cat.search.return_value = mock_results
        helper._esgf_cat = mock_cat

        variables = helper.list_variables(
            experiment_id="G6sulfur",
            source_id="UKESM1-0-LL",
        )
        assert variables == ["pr", "tas"]

    def test_list_models(self):
        helper = ESGFHelper()
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame(
            {"source_id": ["UKESM1-0-LL", "CNRM-ESM2-1", "UKESM1-0-LL"]}
        )
        mock_cat.search.return_value = mock_results
        helper._esgf_cat = mock_cat

        models = helper.list_models(experiment_id="G6sulfur")
        assert models == ["CNRM-ESM2-1", "UKESM1-0-LL"]


# =========================================================================
# GeoMIPHelper
# =========================================================================


def _make_mock_esgf_cat(dataset_dict):
    """Create a mock intake_esgf catalog that returns the given dataset dict."""
    mock_cat = MagicMock()
    mock_results = MagicMock()
    mock_results.to_dataset_dict.return_value = dataset_dict
    mock_cat.search.return_value = mock_results
    return mock_cat


class TestGeoMIPHelper:
    """Tests for GeoMIPHelper."""

    def test_g6sulfur(self):
        mock_cat = _make_mock_esgf_cat({"G6sulfur.UKESM": MagicMock()})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = GeoMIPHelper()
            ds = helper.g6sulfur(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_g6solar(self):
        mock_cat = _make_mock_esgf_cat({"G6solar.UKESM": MagicMock()})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = GeoMIPHelper()
            ds = helper.g6solar(model="UKESM1-0-LL", variable="pr")
            assert ds is not None

    def test_g6sulfur_no_data_raises(self):
        mock_cat = _make_mock_esgf_cat({})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = GeoMIPHelper()
            with pytest.raises(ValueError, match="No data found"):
                helper.g6sulfur(model="NOMODEL", variable="tas")

    def test_list_variables(self):
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame({"variable_id": ["tas", "pr", "huss"]})
        mock_cat.search.return_value = mock_results

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = GeoMIPHelper()
            variables = helper.list_variables(experiment="G6sulfur")
            assert variables == ["huss", "pr", "tas"]


# =========================================================================
# SSPHelper
# =========================================================================


class TestSSPHelper:
    """Tests for SSPHelper."""

    def test_ssp245(self):
        mock_cat = _make_mock_esgf_cat({"ssp245.UKESM": MagicMock()})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = SSPHelper()
            ds = helper.ssp245(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_ssp585(self):
        mock_cat = _make_mock_esgf_cat({"ssp585.UKESM": MagicMock()})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = SSPHelper()
            ds = helper.ssp585(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_ssp126(self):
        mock_cat = _make_mock_esgf_cat({"ssp126.UKESM": MagicMock()})

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = SSPHelper()
            ds = helper.ssp126(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_list_variables(self):
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame({"variable_id": ["tas", "pr"]})
        mock_cat.search.return_value = mock_results

        with patch("reflective_data_catalog.esgf._new_catalog", return_value=mock_cat):
            helper = SSPHelper()
            variables = helper.list_variables(experiment="ssp245")
            assert variables == ["pr", "tas"]
