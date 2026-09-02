"""
intake-esm integration for accessing cloud-hosted CMIP6/GeoMIP data.

Provides access to the Google Cloud CMIP6 catalog via intake-esm,
enabling search and loading of cloud-optimized Zarr datasets for
GeoMIP experiments (G6sulfur, G6solar, etc.) and CMIP6 scenarios.

See: https://reflectivecloud.github.io/Book/Resources/GeoMIP_from_GoogleCloud/
"""

from __future__ import annotations

from typing import Any

# Default Google Cloud CMIP6 catalog URLs
CATALOG_URLS = {
    "default": (
        "https://storage.googleapis.com/cmip6/"
        "cmip6-pgf-ingestion-test/catalog/catalog.json"
    ),
    "noqc": (
        "https://storage.googleapis.com/cmip6/"
        "cmip6-pgf-ingestion-test/catalog/catalog_noqc.json"
    ),
    "retracted": (
        "https://storage.googleapis.com/cmip6/"
        "cmip6-pgf-ingestion-test/catalog/catalog_retracted.json"
    ),
}


class ESMCatalog:
    """
    Wrapper around an intake-esm datastore for searching and loading
    cloud-optimized CMIP6 / GeoMIP Zarr data from Google Cloud Storage.

    Usage:
    ------
        esm = ESMCatalog()

        # Search for data
        subset = esm.search(
            experiment_id=['G6sulfur', 'ssp245', 'ssp585'],
            variable_id='tas',
            table_id='Amon',
        )

        # Load datasets
        datasets = subset.to_dataset_dict()

        # Or with preprocessing (recommended)
        datasets = subset.to_dataset_dict(preprocess=combined_preprocessing)
    """

    def __init__(self, catalog_url: str | None = None):
        """
        Initialize the ESM catalog connection.

        Parameters
        ----------
        catalog_url : str, optional
            URL to an intake-esm catalog JSON file. Defaults to the
            Google Cloud CMIP6 catalog (quality-controlled).
        """
        self._catalog_url = catalog_url or CATALOG_URLS["default"]
        self._catalog = None

    @property
    def catalog(self):
        """Lazy initialization of the intake-esm catalog."""
        if self._catalog is None:
            try:
                import intake
            except ImportError as exc:
                raise ImportError(
                    "intake-esm is required for ESM catalog access. "
                    'Install with: pip install "reflective-data-catalog[esm]"'
                ) from exc
            try:
                self._catalog = intake.open_esm_datastore(self._catalog_url)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to open ESM catalog at {self._catalog_url}: {e}"
                ) from e
        return self._catalog

    def search(
        self,
        require_all_on: list[str] | None = None,
        **query: Any,
    ):
        """
        Search the ESM catalog and return a subset.

        Parameters
        ----------
        require_all_on : list[str], optional
            Column names that must have all queried values present.
            For example, ``['source_id', 'institution_id']`` ensures
            only models that have data for ALL requested experiments
            are returned.
        **query : dict
            Search criteria. Common keys:
            - experiment_id : str or list[str]
            - variable_id : str or list[str]
            - table_id : str
            - source_id : str or list[str]
            - activity_id : str
            - member_id : str

        Returns
        -------
        intake_esm.core.esm_datastore
            Subset catalog matching the query.

        Examples
        --------
        >>> esm = ESMCatalog()
        >>> subset = esm.search(
        ...     experiment_id=['G6sulfur', 'ssp245', 'ssp585'],
        ...     variable_id='tas',
        ...     table_id='Amon',
        ...     require_all_on=['source_id', 'institution_id'],
        ... )
        """
        kwargs = {}
        if require_all_on is not None:
            kwargs["require_all_on"] = require_all_on
        return self.catalog.search(**kwargs, **query)

    def load(
        self,
        preprocess=None,
        require_all_on: list[str] | None = None,
        **query: Any,
    ) -> dict:
        """
        Search and load datasets in one step.

        Parameters
        ----------
        preprocess : callable, optional
            Preprocessing function applied to each dataset.
            Recommended: ``xmip.preprocessing.combined_preprocessing``.
        require_all_on : list[str], optional
            Passed to ``search()``.
        **query : dict
            Search criteria passed to ``search()``.

        Returns
        -------
        dict[str, xarray.Dataset]
            Dictionary of datasets keyed by
            ``activity_id.institution_id.source_id.experiment_id.table_id.grid_label``.

        Examples
        --------
        >>> esm = ESMCatalog()
        >>> datasets = esm.load(
        ...     experiment_id=['G6sulfur', 'ssp245'],
        ...     variable_id='tas',
        ...     table_id='Amon',
        ... )
        """
        subset = self.search(require_all_on=require_all_on, **query)

        if len(subset.df) == 0:
            print("No datasets found matching the query.")
            return {}

        print(f"Loading {len(subset.df)} dataset(s)...")

        kwargs: dict[str, Any] = {}
        if preprocess is not None:
            kwargs["preprocess"] = preprocess

        return subset.to_dataset_dict(**kwargs)

    def list_experiments(
        self,
        activity_id: str | None = None,
    ) -> list[str]:
        """
        List available experiment IDs in the catalog.

        Parameters
        ----------
        activity_id : str, optional
            Filter by activity (e.g., 'GeoMIP', 'ScenarioMIP').

        Returns
        -------
        list[str]
            Sorted list of experiment IDs.
        """
        df = self.catalog.df
        if activity_id:
            df = df[df["activity_id"] == activity_id]
        experiments = sorted(df["experiment_id"].unique())
        print(f"Available experiments ({len(experiments)}):")
        for exp in experiments:
            print(f"  - {exp}")
        return experiments

    def list_models(
        self,
        experiment_id: str | list[str] | None = None,
        activity_id: str | None = None,
    ) -> list[str]:
        """
        List available models (source_id) in the catalog.

        Parameters
        ----------
        experiment_id : str or list[str], optional
            Filter by experiment(s).
        activity_id : str, optional
            Filter by activity.

        Returns
        -------
        list[str]
            Sorted list of model names.
        """
        df = self.catalog.df
        if activity_id:
            df = df[df["activity_id"] == activity_id]
        if experiment_id:
            if isinstance(experiment_id, str):
                experiment_id = [experiment_id]
            df = df[df["experiment_id"].isin(experiment_id)]
        models = sorted(df["source_id"].unique())
        print(f"Available models ({len(models)}):")
        for m in models:
            print(f"  - {m}")
        return models

    def list_variables(
        self,
        experiment_id: str | None = None,
        source_id: str | None = None,
        table_id: str | None = None,
    ) -> list[str]:
        """
        List available variables in the catalog.

        Parameters
        ----------
        experiment_id : str, optional
            Filter by experiment.
        source_id : str, optional
            Filter by model.
        table_id : str, optional
            Filter by table.

        Returns
        -------
        list[str]
            Sorted list of variable IDs.
        """
        df = self.catalog.df
        if experiment_id:
            df = df[df["experiment_id"] == experiment_id]
        if source_id:
            df = df[df["source_id"] == source_id]
        if table_id:
            df = df[df["table_id"] == table_id]
        variables = sorted(df["variable_id"].unique())
        print(f"Available variables ({len(variables)}):")
        for v in variables:
            print(f"  - {v}")
        return variables

    def summary(
        self,
        experiment_id: str | list[str] | None = None,
        activity_id: str | None = None,
    ):
        """
        Print a summary of what's available grouped by model.

        Parameters
        ----------
        experiment_id : str or list[str], optional
            Filter by experiment(s).
        activity_id : str, optional
            Filter by activity.
        """
        df = self.catalog.df
        if activity_id:
            df = df[df["activity_id"] == activity_id]
        if experiment_id:
            if isinstance(experiment_id, str):
                experiment_id = [experiment_id]
            df = df[df["experiment_id"].isin(experiment_id)]

        grouped = df.groupby("source_id")[
            ["experiment_id", "variable_id", "table_id"]
        ].nunique()

        print("=" * 60)
        print("ESM Catalog Summary")
        print("=" * 60)
        print(grouped.to_string())
        print("=" * 60)

    def __repr__(self) -> str:
        if self._catalog is None:
            return f"<ESMCatalog: {self._catalog_url} (not loaded)>"

        try:
            n = len(self._catalog.df)
            return f"<ESMCatalog: {n} entries from {self._catalog_url}>"
        except Exception:
            return f"<ESMCatalog: {self._catalog_url} (loaded)>"


class GeoMIPCloudHelper:
    """
    Convenience helper for loading GeoMIP experiments from the
    Google Cloud CMIP6 catalog.

    Wraps ESMCatalog with GeoMIP-specific defaults and shortcuts.

    Usage:
    ------
        geomip = GeoMIPCloudHelper()

        # Load G6sulfur for all models that also have SSP2-4.5 and SSP5-8.5
        datasets = geomip.load_ensemble(
            experiments=['G6sulfur', 'ssp245', 'ssp585'],
            variable='tas',
        )

        # Quick single-experiment load
        ds_dict = geomip.g6sulfur(variable='tas')

        # List models with GeoMIP data
        geomip.list_models()
    """

    def __init__(
        self,
        catalog_url: str | None = None,
        esm_catalog: ESMCatalog | None = None,
    ):
        """
        Initialize the GeoMIP Cloud helper.

        Parameters
        ----------
        catalog_url : str, optional
            URL to an intake-esm catalog. Defaults to the Google Cloud
            CMIP6 catalog (quality-controlled). Ignored when
            ``esm_catalog`` is provided.
        esm_catalog : ESMCatalog, optional
            An existing :class:`ESMCatalog` to share (avoids opening a
            second connection to the same catalog). When omitted, a new
            one is created.
        """
        if esm_catalog is not None:
            self._esm = esm_catalog
        else:
            self._esm = ESMCatalog(catalog_url=catalog_url)

    @property
    def catalog(self) -> ESMCatalog:
        """Access the underlying ESMCatalog."""
        return self._esm

    def g6sulfur(
        self,
        variable: str = "tas",
        table: str = "Amon",
        source_id: str | list[str] | None = None,
        preprocess=None,
    ) -> dict:
        """
        Load G6sulfur experiment data from the cloud catalog.

        Parameters
        ----------
        variable : str
            Variable ID (e.g., 'tas', 'pr').
        table : str
            Table ID (e.g., 'Amon', 'day').
        source_id : str or list[str], optional
            Filter by model(s). If None, returns all available models.
        preprocess : callable, optional
            Preprocessing function.

        Returns
        -------
        dict[str, xarray.Dataset]
        """
        return self._load_experiment("G6sulfur", variable, table, source_id, preprocess)

    def g6solar(
        self,
        variable: str = "tas",
        table: str = "Amon",
        source_id: str | list[str] | None = None,
        preprocess=None,
    ) -> dict:
        """
        Load G6solar experiment data from the cloud catalog.

        Parameters
        ----------
        variable : str
            Variable ID.
        table : str
            Table ID.
        source_id : str or list[str], optional
            Filter by model(s).
        preprocess : callable, optional
            Preprocessing function.

        Returns
        -------
        dict[str, xarray.Dataset]
        """
        return self._load_experiment("G6solar", variable, table, source_id, preprocess)

    def load_ensemble(
        self,
        experiments: list[str] | None = None,
        variable: str = "tas",
        table: str = "Amon",
        require_all_on: list[str] | None = None,
        preprocess=None,
    ) -> dict:
        """
        Load a multi-experiment ensemble from the cloud catalog.

        This is the recommended way to load GeoMIP data for comparison
        studies. By default, it ensures that only models with data for
        ALL requested experiments are returned.

        Parameters
        ----------
        experiments : list[str], optional
            Experiment IDs to load.
            Default: ['G6sulfur', 'ssp245', 'ssp585'].
        variable : str
            Variable ID.
        table : str
            Table ID.
        require_all_on : list[str], optional
            Ensure each group has all experiments.
            Default: ['source_id', 'institution_id'].
        preprocess : callable, optional
            Preprocessing function (e.g., xmip.preprocessing.combined_preprocessing).

        Returns
        -------
        dict[str, xarray.Dataset]
            Dictionary keyed by
            ``activity_id.institution_id.source_id.experiment_id.table_id.grid_label``.

        Examples
        --------
        >>> geomip = GeoMIPCloudHelper()
        >>> datasets = geomip.load_ensemble(
        ...     experiments=['G6sulfur', 'ssp245', 'ssp585'],
        ...     variable='tas',
        ... )
        >>> # Process each dataset
        >>> for key, ds in datasets.items():
        ...     model = key.split('.')[2]
        ...     experiment = key.split('.')[3]
        ...     print(f"{model} - {experiment}")
        """
        if experiments is None:
            experiments = ["G6sulfur", "ssp245", "ssp585"]
        if require_all_on is None:
            require_all_on = ["source_id", "institution_id"]

        print(f"Loading ensemble: {experiments}")
        print(f"  Variable: {variable}, Table: {table}")

        return self._esm.load(
            experiment_id=experiments,
            variable_id=variable,
            table_id=table,
            require_all_on=require_all_on,
            preprocess=preprocess,
        )

    def list_models(
        self,
        experiment_id: str | None = "G6sulfur",
    ) -> list[str]:
        """
        List models with GeoMIP data.

        Parameters
        ----------
        experiment_id : str, optional
            Filter by experiment. Default: 'G6sulfur'.

        Returns
        -------
        list[str]
        """
        return self._esm.list_models(experiment_id=experiment_id)

    def list_variables(
        self,
        experiment_id: str = "G6sulfur",
        source_id: str | None = None,
        table_id: str | None = None,
    ) -> list[str]:
        """
        List available variables for a GeoMIP experiment.

        Parameters
        ----------
        experiment_id : str
            Experiment to list variables for. Default: 'G6sulfur'.
        source_id : str, optional
            Filter by model.
        table_id : str, optional
            Filter by table.

        Returns
        -------
        list[str]
        """
        return self._esm.list_variables(
            experiment_id=experiment_id,
            source_id=source_id,
            table_id=table_id,
        )

    def summary(self):
        """Print a summary of available GeoMIP data."""
        self._esm.summary(activity_id="GeoMIP")

    def _load_experiment(
        self,
        experiment_id: str,
        variable: str,
        table: str,
        source_id: str | list[str] | None,
        preprocess=None,
    ) -> dict:
        """Internal method to load a single experiment."""
        query: dict[str, Any] = {
            "experiment_id": experiment_id,
            "variable_id": variable,
            "table_id": table,
        }
        if source_id:
            query["source_id"] = source_id

        return self._esm.load(preprocess=preprocess, **query)

    def __repr__(self) -> str:
        return (
            "<GeoMIPCloudHelper>\n"
            "  Methods:\n"
            "    .g6sulfur(variable='tas')     - Load G6sulfur data\n"
            "    .g6solar(variable='tas')      - Load G6solar data\n"
            "    .load_ensemble(...)           - Load multi-experiment ensemble\n"
            "    .list_models()                - List available models\n"
            "    .list_variables()             - List available variables\n"
            "    .summary()                    - Print data summary\n"
            "    .catalog                      - Access underlying ESMCatalog"
        )
