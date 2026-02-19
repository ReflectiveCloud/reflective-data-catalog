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
        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}):
            import sys

            mock_mod = sys.modules["intake_esgf"]
            mock_cat = MagicMock()
            mock_mod.ESGFCatalog.return_value = mock_cat

            helper = ESGFHelper()
            cat = helper._get_catalog()
            assert cat is mock_cat
            # Second call should return cached
            cat2 = helper._get_catalog()
            assert cat2 is mock_cat
            assert mock_mod.ESGFCatalog.call_count == 1

    def test_get_catalog_import_error(self):
        helper = ESGFHelper()
        with patch.dict(
            "sys.modules",
            {"intake_esgf": None},
        ), pytest.raises(ImportError, match="intake-esgf"):
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
        mock_results.df = pd.DataFrame(
            {"variable_id": ["tas", "pr", "tas"]}
        )
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

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = GeoMIPHelper()
            ds = helper.g6sulfur(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_g6solar(self):
        mock_cat = _make_mock_esgf_cat({"G6solar.UKESM": MagicMock()})

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = GeoMIPHelper()
            ds = helper.g6solar(model="UKESM1-0-LL", variable="pr")
            assert ds is not None

    def test_g6sulfur_no_data_raises(self):
        mock_cat = _make_mock_esgf_cat({})

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = GeoMIPHelper()
            with pytest.raises(ValueError, match="No data found"):
                helper.g6sulfur(model="NOMODEL", variable="tas")

    def test_list_variables(self):
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame(
            {"variable_id": ["tas", "pr", "huss"]}
        )
        mock_cat.search.return_value = mock_results

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat

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

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = SSPHelper()
            ds = helper.ssp245(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_ssp585(self):
        mock_cat = _make_mock_esgf_cat({"ssp585.UKESM": MagicMock()})

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = SSPHelper()
            ds = helper.ssp585(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_ssp126(self):
        mock_cat = _make_mock_esgf_cat({"ssp126.UKESM": MagicMock()})

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat
            helper = SSPHelper()
            ds = helper.ssp126(model="UKESM1-0-LL", variable="tas")
            assert ds is not None

    def test_list_variables(self):
        mock_cat = MagicMock()
        mock_results = MagicMock()
        mock_results.df = pd.DataFrame(
            {"variable_id": ["tas", "pr"]}
        )
        mock_cat.search.return_value = mock_results

        with patch.dict("sys.modules", {"intake_esgf": MagicMock()}) as _:
            import sys

            sys.modules["intake_esgf"].ESGFCatalog.return_value = mock_cat

            helper = SSPHelper()
            variables = helper.list_variables(experiment="ssp245")
            assert variables == ["pr", "tas"]
