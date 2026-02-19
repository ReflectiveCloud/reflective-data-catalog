"""Tests for ESMCatalog and GeoMIPCloudHelper (intake-esm mocked)."""

from __future__ import annotations

from reflective_data_catalog.esm import (
    CATALOG_URLS,
    ESMCatalog,
    GeoMIPCloudHelper,
)

# =========================================================================
# ESMCatalog
# =========================================================================


class TestESMCatalog:
    """Tests for ESMCatalog (wraps intake-esm)."""

    def test_default_url(self):
        esm = ESMCatalog()
        assert esm._catalog_url == CATALOG_URLS["default"]

    def test_custom_url(self):
        esm = ESMCatalog(catalog_url="https://custom.catalog.json")
        assert esm._catalog_url == "https://custom.catalog.json"

    def test_catalog_lazy_init(self, mock_esm_catalog):
        esm = ESMCatalog()
        # Access the property — should call open_esm_datastore
        cat = esm.catalog
        assert cat is mock_esm_catalog

    def test_catalog_cached(self, mock_esm_catalog):
        esm = ESMCatalog()
        cat1 = esm.catalog
        cat2 = esm.catalog
        assert cat1 is cat2

    def test_search(self, mock_esm_catalog):
        esm = ESMCatalog()
        _ = esm.catalog  # trigger lazy load

        subset = esm.search(experiment_id="G6sulfur", variable_id="tas")
        assert len(subset.df) > 0
        assert all(subset.df["experiment_id"] == "G6sulfur")
        assert all(subset.df["variable_id"] == "tas")

    def test_search_with_require_all_on(self, mock_esm_catalog):
        esm = ESMCatalog()
        _ = esm.catalog

        subset = esm.search(
            experiment_id="G6sulfur",
            require_all_on=["source_id"],
        )
        # The mock ignores require_all_on but should not raise
        assert len(subset.df) > 0

    def test_load(self, mock_esm_catalog):
        esm = ESMCatalog()
        _ = esm.catalog

        datasets = esm.load(experiment_id="G6sulfur", variable_id="tas")
        assert isinstance(datasets, dict)
        assert len(datasets) > 0

    def test_load_empty(self, mock_esm_catalog):
        esm = ESMCatalog()
        _ = esm.catalog

        datasets = esm.load(experiment_id="nonexistent_experiment")
        assert datasets == {}

    def test_list_experiments(self, mock_esm_catalog, mock_esm_df):
        esm = ESMCatalog()
        _ = esm.catalog

        experiments = esm.list_experiments()
        expected = sorted(mock_esm_df["experiment_id"].unique())
        assert experiments == expected

    def test_list_experiments_filtered(self, mock_esm_catalog, mock_esm_df):
        esm = ESMCatalog()
        _ = esm.catalog

        experiments = esm.list_experiments(activity_id="GeoMIP")
        geomip_df = mock_esm_df[mock_esm_df["activity_id"] == "GeoMIP"]
        expected = sorted(geomip_df["experiment_id"].unique())
        assert experiments == expected

    def test_list_models(self, mock_esm_catalog, mock_esm_df):
        esm = ESMCatalog()
        _ = esm.catalog

        models = esm.list_models(experiment_id="G6sulfur")
        expected = sorted(
            mock_esm_df[mock_esm_df["experiment_id"] == "G6sulfur"][
                "source_id"
            ].unique()
        )
        assert models == expected

    def test_list_variables(self, mock_esm_catalog, mock_esm_df):
        esm = ESMCatalog()
        _ = esm.catalog

        variables = esm.list_variables(experiment_id="G6sulfur")
        expected = sorted(
            mock_esm_df[mock_esm_df["experiment_id"] == "G6sulfur"][
                "variable_id"
            ].unique()
        )
        assert variables == expected

    def test_summary(self, mock_esm_catalog, capsys):
        esm = ESMCatalog()
        _ = esm.catalog

        esm.summary(activity_id="GeoMIP")
        captured = capsys.readouterr()
        assert "ESM Catalog Summary" in captured.out

    def test_repr_loaded(self, mock_esm_catalog, mock_esm_df):
        esm = ESMCatalog()
        _ = esm.catalog

        r = repr(esm)
        assert str(len(mock_esm_df)) in r

    def test_repr_not_loaded(self):
        esm = ESMCatalog()
        r = repr(esm)
        assert "not loaded" in r


# =========================================================================
# GeoMIPCloudHelper
# =========================================================================


class TestGeoMIPCloudHelper:
    """Tests for GeoMIPCloudHelper."""

    def test_catalog_property(self):
        helper = GeoMIPCloudHelper()
        assert isinstance(helper.catalog, ESMCatalog)

    def test_g6sulfur(self, mock_esm_catalog):
        helper = GeoMIPCloudHelper()
        # Force the underlying ESM catalog to use our mock
        helper._esm._catalog = mock_esm_catalog

        result = helper.g6sulfur(variable="tas")
        assert isinstance(result, dict)

    def test_g6solar(self, mock_esm_catalog):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        result = helper.g6solar(variable="pr")
        assert isinstance(result, dict)

    def test_load_ensemble(self, mock_esm_catalog):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        result = helper.load_ensemble(
            experiments=["G6sulfur", "ssp245"],
            variable="tas",
        )
        assert isinstance(result, dict)

    def test_load_ensemble_default_experiments(self, mock_esm_catalog):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        result = helper.load_ensemble()
        assert isinstance(result, dict)

    def test_list_models(self, mock_esm_catalog, mock_esm_df):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        models = helper.list_models()
        assert isinstance(models, list)
        assert len(models) > 0

    def test_list_variables(self, mock_esm_catalog, mock_esm_df):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        variables = helper.list_variables(experiment_id="G6sulfur")
        assert isinstance(variables, list)
        assert "tas" in variables

    def test_summary(self, mock_esm_catalog, capsys):
        helper = GeoMIPCloudHelper()
        helper._esm._catalog = mock_esm_catalog

        helper.summary()
        captured = capsys.readouterr()
        assert "ESM Catalog Summary" in captured.out

    def test_repr(self):
        helper = GeoMIPCloudHelper()
        r = repr(helper)
        assert "GeoMIPCloudHelper" in r
        assert "g6sulfur" in r
