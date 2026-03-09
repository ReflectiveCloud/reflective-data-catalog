"""Shared fixtures and mocks for reflective-data-catalog tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pandas as pd
import pytest

from reflective_data_catalog.flexibleSources import (
    FlexibleSourceConfig,
    FlexibleSourceRegistry,
)

# ---------------------------------------------------------------------------
# FlexibleSourceConfig fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_config():
    """A minimal single-file flexible source config."""
    return FlexibleSourceConfig(
        name="test_source",
        base="s3://test-bucket/model/experiment",
        pattern="{base}/{ensemble}/{table_path}",
        filename_pattern="{variable}.nc",
        table_mapping={"Amon": "Amon", "Omon": "Omon"},
        default_table="Amon",
        default_variable="tas",
        default_ensemble="r1i1p1f1",
        driver="netcdf",
        description="Test source for unit tests",
    )


@pytest.fixture()
def multi_file_config():
    """A multi-file flexible source config (like CESM2)."""
    return FlexibleSourceConfig(
        name="test_multi",
        base="s3://test-bucket/CESM2/G6-HiLLA",
        pattern="{base}/{ensemble}/{table_path}",
        filename_pattern="model.{ensemble_id}.h0.{variable}.*.nc",
        table_mapping={"ADAY": "ADAY", "AMON": "AMON"},
        ensemble_mapping={"r1": "001", "r2": "002", "r3": "003"},
        default_table="ADAY",
        default_variable="T",
        default_ensemble="r1",
        driver="netcdf",
        combine_files="by_coords",
        concat_dim="time",
        description="Test multi-file source",
    )


@pytest.fixture()
def variant_config():
    """A config with a variant parameter (like MIROC)."""
    return FlexibleSourceConfig(
        name="test_variant",
        base="s3://test-bucket/MIROC/G6-HiLLA",
        pattern="{base}/{table_path}",
        filename_pattern="{variable}_{variant}_{ensemble}.nc",
        table_mapping={"Amon": "Amon", "Omon": "Omon"},
        default_table="Amon",
        default_variable="SurfT",
        default_ensemble="r01",
        default_variant="baseline",
        driver="netcdf",
        description="Test variant source",
    )


@pytest.fixture()
def time_config():
    """A config with {time} and {variable} in pattern (like UKESM1)."""
    return FlexibleSourceConfig(
        name="test_time",
        base="s3://test-bucket/UKESM1/G6-HiLLA",
        pattern="{base}/{ensemble}/{table_path}/{time}/{variable}",
        filename_pattern="{variable}_{time}_UKESM1_g6-hilla_{ensemble}_gn_*.nc",
        table_mapping={"ap5": "ap5", "ap6": "ap6"},
        default_table="ap5",
        default_variable="ua",
        default_ensemble="r12i1p1f2",
        default_time="AERmon",
        driver="netcdf",
        combine_files="by_coords",
        concat_dim="time",
        description="Test time source",
    )


@pytest.fixture()
def populated_registry(simple_config, multi_file_config):
    """A registry with two sources registered."""
    registry = FlexibleSourceRegistry()
    registry.register(simple_config)
    registry.register(multi_file_config)
    return registry


# ---------------------------------------------------------------------------
# Mock intake-esgf fixtures
# ---------------------------------------------------------------------------


@dataclass
class MockESGFResults:
    """Mock for intake-esgf search results."""

    df: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    def to_dataset_dict(self):
        """Return a mock dataset dict."""
        if len(self.df) == 0:
            return {}
        # Create one mock xarray-like object per unique key
        keys = (self.df["experiment_id"] + "." + self.df["source_id"]).unique()
        return {k: MagicMock(name=f"ds_{k}") for k in keys}


@pytest.fixture()
def mock_esgf_catalog(monkeypatch):
    """Patch intake_esgf.ESGFCatalog to return a controllable mock."""
    mock_cat = MagicMock()

    # Build a sample dataframe for search results
    sample_df = pd.DataFrame(
        {
            "experiment_id": [
                "G6sulfur",
                "G6sulfur",
                "G6solar",
                "ssp245",
            ],
            "source_id": [
                "UKESM1-0-LL",
                "CNRM-ESM2-1",
                "UKESM1-0-LL",
                "UKESM1-0-LL",
            ],
            "variable_id": ["tas", "tas", "pr", "tas"],
            "table_id": ["Amon", "Amon", "Amon", "Amon"],
            "activity_id": ["GeoMIP", "GeoMIP", "GeoMIP", "ScenarioMIP"],
        }
    )

    def mock_search(**kwargs):
        filtered = sample_df.copy()
        for key, value in kwargs.items():
            if key in filtered.columns:
                if isinstance(value, list):
                    filtered = filtered[filtered[key].isin(value)]
                else:
                    filtered = filtered[filtered[key] == value]
        return MockESGFResults(df=filtered)

    mock_cat.search = mock_search

    # Patch the import
    mock_module = MagicMock()
    mock_module.ESGFCatalog.return_value = mock_cat
    monkeypatch.setitem(__import__("sys").modules, "intake_esgf", mock_module)

    return mock_cat


# ---------------------------------------------------------------------------
# Mock intake-esm fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_esm_df():
    """Sample DataFrame mimicking a Google Cloud CMIP6 catalog."""
    return pd.DataFrame(
        {
            "activity_id": [
                "GeoMIP",
                "GeoMIP",
                "GeoMIP",
                "ScenarioMIP",
                "ScenarioMIP",
            ],
            "institution_id": [
                "MOHC",
                "CNRM-CERFACS",
                "MOHC",
                "MOHC",
                "CNRM-CERFACS",
            ],
            "source_id": [
                "UKESM1-0-LL",
                "CNRM-ESM2-1",
                "UKESM1-0-LL",
                "UKESM1-0-LL",
                "CNRM-ESM2-1",
            ],
            "experiment_id": [
                "G6sulfur",
                "G6sulfur",
                "G6solar",
                "ssp245",
                "ssp245",
            ],
            "member_id": [
                "r1i1p1f2",
                "r1i1p1f2",
                "r1i1p1f2",
                "r1i1p1f2",
                "r1i1p1f2",
            ],
            "table_id": ["Amon", "Amon", "Amon", "Amon", "Amon"],
            "variable_id": ["tas", "tas", "pr", "tas", "pr"],
            "grid_label": ["gn", "gr", "gn", "gn", "gr"],
            "zstore": [
                "gs://cmip6/CMIP6/GeoMIP/MOHC/UKESM1-0-LL/G6sulfur/...",
                "gs://cmip6/CMIP6/GeoMIP/CNRM/CNRM-ESM2-1/G6sulfur/...",
                "gs://cmip6/CMIP6/GeoMIP/MOHC/UKESM1-0-LL/G6solar/...",
                "gs://cmip6/CMIP6/ScenarioMIP/MOHC/UKESM1-0-LL/ssp245/...",
                "gs://cmip6/CMIP6/ScenarioMIP/CNRM/CNRM-ESM2-1/ssp245/...",
            ],
            "dcpp_init_year": [None, None, None, None, None],
            "version": [
                "20200101",
                "20200101",
                "20200101",
                "20200101",
                "20200101",
            ],
        }
    )


@pytest.fixture()
def mock_esm_catalog(monkeypatch, mock_esm_df):
    """
    Patch intake.open_esm_datastore to return a mock ESM catalog
    with a controllable DataFrame.
    """
    mock_datastore = MagicMock()
    mock_datastore.df = mock_esm_df

    def mock_search(**kwargs):
        filtered = mock_esm_df.copy()
        kwargs.pop("require_all_on", None)
        for key, value in kwargs.items():
            if key in filtered.columns:
                if isinstance(value, list):
                    filtered = filtered[filtered[key].isin(value)]
                else:
                    filtered = filtered[filtered[key] == value]
        subset = MagicMock()
        subset.df = filtered
        subset.to_dataset_dict.return_value = {
            f"mock.{i}": MagicMock() for i in range(len(filtered))
        }
        return subset

    mock_datastore.search = mock_search

    monkeypatch.setattr(
        "intake.open_esm_datastore",
        lambda *args, **kwargs: mock_datastore,
    )

    return mock_datastore
