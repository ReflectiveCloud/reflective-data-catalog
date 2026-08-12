"""Shared fixtures and mocks for reflective-data-catalog tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pandas as pd
import pytest

from reflective_data_catalog import ReflectiveCatalog

# ---------------------------------------------------------------------------
# Catalog fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_catalog() -> ReflectiveCatalog:
    """A ReflectiveCatalog over the real shipped data-catalog.yaml."""
    return ReflectiveCatalog()


@pytest.fixture()
def mock_fs():
    """A CloudFileSystem stand-in: storage I/O mocked with sensible defaults."""
    fs = MagicMock(name="CloudFileSystem")
    fs.ls.return_value = []
    fs.glob.return_value = []
    fs.exists.return_value = True
    fs.fsspec_info.side_effect = lambda url: (url, {})
    return fs


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

    mock_module = MagicMock()
    mock_module.open_esm_datastore = lambda *args, **kwargs: mock_datastore
    monkeypatch.setitem(sys.modules, "intake", mock_module)

    return mock_datastore
