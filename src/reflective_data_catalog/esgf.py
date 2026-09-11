class ESGFHelper:
    """Helper for ESGF data access"""

    def __init__(self):
        self._esgf_cat = None
        self.geomip = GeoMIPHelper(parent=self)
        self.ssp = SSPHelper(parent=self)

    def _get_catalog(self):
        """Lazy initialization of ESGF catalog"""
        if self._esgf_cat is None:
            try:
                from intake_esgf import ESGFCatalog

                self._esgf_cat = ESGFCatalog()
            except ImportError as exc:
                raise ImportError(
                    "intake-esgf is required for ESGF data access. "
                    'Install with: pip install "reflective-data-catalog[esgf]" '
                    "(needs Python >= 3.12 — intake-esgf no longer supports "
                    "3.11, so the extra installs nothing there)"
                ) from exc
        return self._esgf_cat

    def search(self, **kwargs):
        """
        Search ESGF directly

        Example:
            results = catalog.esgf.search(
                project='CMIP6',
                experiment_id='G6sulfur',
                source_id='UKESM1-0-LL',
                variable_id='tas'
            )
        """
        cat = self._get_catalog()
        return cat.search(**kwargs)

    def list_experiments(self, activity_id="GeoMIP"):
        """
        List available experiments on ESGF for a given activity

        Parameters:
        -----------
        activity_id : str
            Activity ID (e.g., 'GeoMIP', 'ScenarioMIP')

        Returns:
        --------
        list : Available experiment IDs
        """
        cat = self._get_catalog()

        print(f"Searching ESGF for {activity_id} experiments...")

        try:
            results = cat.search(project="CMIP6", activity_id=activity_id)

            if hasattr(results, "df") and len(results.df) > 0:
                experiments = sorted(results.df["experiment_id"].unique())

                print(f"\nAvailable {activity_id} experiments ({len(experiments)}):")
                for exp in experiments:
                    print(f"  - {exp}")

                return experiments
            else:
                print("No experiments found")
                return []

        except Exception as e:
            print(f"Error searching ESGF: {e}")
            return []

    def list_variables(
        self,
        experiment_id=None,
        source_id=None,
        table_id=None,
        activity_id="GeoMIP",
    ):
        """
        List available variables on ESGF

        Parameters:
        -----------
        experiment_id : str, optional
            Filter by experiment (e.g., 'G6sulfur', 'ssp245')
        source_id : str, optional
            Filter by model (e.g., 'UKESM1-0-LL')
        table_id : str, optional
            Filter by table (e.g., 'Amon', 'day')
        activity_id : str
            Activity ID (e.g., 'GeoMIP', 'ScenarioMIP')

        Returns:
        --------
        list : Available variable IDs

        Examples:
        ---------
        catalog.esgf.list_variables(experiment_id='G6sulfur')
        catalog.esgf.list_variables(
            experiment_id='G6sulfur',
            source_id='UKESM1-0-LL',
            table_id='Amon'
        )
        """
        cat = self._get_catalog()

        search_params = {"project": "CMIP6", "activity_id": activity_id}

        if experiment_id:
            search_params["experiment_id"] = experiment_id
        if source_id:
            search_params["source_id"] = source_id
        if table_id:
            search_params["table_id"] = table_id

        context = " / ".join(
            f"{k}={v}" for k, v in search_params.items() if k != "project"
        )
        print(f"Searching ESGF for variables ({context})...")

        try:
            results = cat.search(**search_params)

            if hasattr(results, "df") and len(results.df) > 0:
                variables = sorted(results.df["variable_id"].unique())

                print(f"\nAvailable variables ({len(variables)}):")
                for var in variables:
                    print(f"  - {var}")

                return variables
            else:
                print("No variables found")
                return []

        except Exception as e:
            print(f"Error searching ESGF: {e}")
            return []

    def list_models(self, experiment_id=None, activity_id="GeoMIP"):
        """
        List available models on ESGF

        Parameters:
        -----------
        experiment_id : str, optional
            Filter by specific experiment
        activity_id : str
            Activity ID

        Returns:
        --------
        list : Available model names
        """
        cat = self._get_catalog()

        search_params = {"project": "CMIP6", "activity_id": activity_id}

        if experiment_id:
            search_params["experiment_id"] = experiment_id
            print(f"Searching for models with {activity_id}/{experiment_id}...")
        else:
            print(f"Searching for all {activity_id} models...")

        try:
            results = cat.search(**search_params)

            if hasattr(results, "df") and len(results.df) > 0:
                models = sorted(results.df["source_id"].unique())

                print(f"\nAvailable models ({len(models)}):")
                for model in models:
                    print(f"  - {model}")

                return models
            else:
                print("No models found")
                return []

        except Exception as e:
            print(f"Error searching ESGF: {e}")
            return []


class GeoMIPHelper:
    """Helper for GeoMIP experiments"""

    def __init__(self, parent: "ESGFHelper | None" = None):
        self._parent = parent

    def _get_catalog(self):
        """Get or create an ESGFCatalog instance."""
        if self._parent is not None:
            return self._parent._get_catalog()
        try:
            from intake_esgf import ESGFCatalog
        except ImportError as exc:
            raise ImportError(
                'intake-esgf required: pip install "reflective-data-catalog[esgf]" '
                "(needs Python >= 3.12)"
            ) from exc
        return ESGFCatalog()

    def g6sulfur(
        self, model="UKESM1-0-LL", variable="tas", table="day", member="r4i1p1f2"
    ):
        """Load G6sulfur data from ESGF"""
        return self._load_geomip("G6sulfur", model, variable, table, member)

    def g6solar(
        self, model="UKESM1-0-LL", variable="tas", table="day", member="r1i1p1f2"
    ):
        """Load G6solar data from ESGF"""
        return self._load_geomip("G6solar", model, variable, table, member)

    def list_variables(
        self,
        experiment="G6sulfur",
        model=None,
        table=None,
    ):
        """
        List available variables for a GeoMIP experiment on ESGF

        Parameters:
        -----------
        experiment : str
            GeoMIP experiment ID (e.g., 'G6sulfur', 'G6solar').
            Default: 'G6sulfur'.
        model : str, optional
            Filter by model (e.g., 'UKESM1-0-LL').
        table : str, optional
            Filter by table (e.g., 'Amon').

        Returns:
        --------
        list : Available variable IDs

        Examples:
        ---------
        catalog.esgf.geomip.list_variables()
        catalog.esgf.geomip.list_variables(experiment='G6solar', model='UKESM1-0-LL')
        """
        cat = self._get_catalog()

        search_params = {
            "project": "CMIP6",
            "activity_id": "GeoMIP",
            "experiment_id": experiment,
        }
        if model:
            search_params["source_id"] = model
        if table:
            search_params["table_id"] = table

        context = f"{experiment}"
        if model:
            context += f" / {model}"
        if table:
            context += f" / {table}"
        print(f"Searching ESGF for GeoMIP variables ({context})...")

        try:
            results = cat.search(**search_params)

            if hasattr(results, "df") and len(results.df) > 0:
                variables = sorted(results.df["variable_id"].unique())

                print(f"\nAvailable variables ({len(variables)}):")
                for var in variables:
                    print(f"  - {var}")

                return variables
            else:
                print("No variables found")
                return []

        except Exception as e:
            print(f"Error searching ESGF: {e}")
            return []

    def _load_geomip(self, experiment, model, variable, table, member):
        """Internal method to load GeoMIP data"""
        cat = self._get_catalog()

        print(f"Searching ESGF for {experiment} {model} {variable}...")

        results = cat.search(
            project="CMIP6",
            activity_id="GeoMIP",
            experiment_id=experiment,
            source_id=model,
            variable_id=variable,
            table_id=table,
            variant_label=member,
        )

        ds_dict = results.to_dataset_dict()

        if len(ds_dict) == 0:
            raise ValueError(f"No data found for {experiment} {model} {variable}")

        first_key = next(iter(ds_dict.keys()))
        print(f"✓ Loaded: {first_key}")

        return ds_dict[first_key]


class SSPHelper:
    """Helper for CMIP6 SSP scenarios"""

    def __init__(self, parent: "ESGFHelper | None" = None):
        self._parent = parent

    def _get_catalog(self):
        """Get or create an ESGFCatalog instance."""
        if self._parent is not None:
            return self._parent._get_catalog()
        try:
            from intake_esgf import ESGFCatalog
        except ImportError as exc:
            raise ImportError(
                'intake-esgf required: pip install "reflective-data-catalog[esgf]" '
                "(needs Python >= 3.12)"
            ) from exc
        return ESGFCatalog()

    def ssp245(
        self, model="UKESM1-0-LL", variable="tas", table="Amon", member="r1i1p1f2"
    ):
        """Load SSP2-4.5 scenario"""
        return self._load_ssp("ssp245", model, variable, table, member)

    def ssp585(
        self, model="UKESM1-0-LL", variable="tas", table="Amon", member="r1i1p1f2"
    ):
        """Load SSP5-8.5 scenario"""
        return self._load_ssp("ssp585", model, variable, table, member)

    def ssp126(
        self, model="UKESM1-0-LL", variable="tas", table="Amon", member="r1i1p1f2"
    ):
        """Load SSP1-2.6 scenario"""
        return self._load_ssp("ssp126", model, variable, table, member)

    def list_variables(
        self,
        experiment="ssp245",
        model=None,
        table=None,
    ):
        """
        List available variables for an SSP experiment on ESGF

        Parameters:
        -----------
        experiment : str
            SSP experiment ID (e.g., 'ssp126', 'ssp245', 'ssp585').
            Default: 'ssp245'.
        model : str, optional
            Filter by model (e.g., 'UKESM1-0-LL').
        table : str, optional
            Filter by table (e.g., 'Amon').

        Returns:
        --------
        list : Available variable IDs

        Examples:
        ---------
        catalog.esgf.ssp.list_variables()
        catalog.esgf.ssp.list_variables(experiment='ssp585', model='UKESM1-0-LL')
        """
        cat = self._get_catalog()

        search_params = {
            "project": "CMIP6",
            "activity_id": "ScenarioMIP",
            "experiment_id": experiment,
        }
        if model:
            search_params["source_id"] = model
        if table:
            search_params["table_id"] = table

        context = f"{experiment}"
        if model:
            context += f" / {model}"
        if table:
            context += f" / {table}"
        print(f"Searching ESGF for SSP variables ({context})...")

        try:
            results = cat.search(**search_params)

            if hasattr(results, "df") and len(results.df) > 0:
                variables = sorted(results.df["variable_id"].unique())

                print(f"\nAvailable variables ({len(variables)}):")
                for var in variables:
                    print(f"  - {var}")

                return variables
            else:
                print("No variables found")
                return []

        except Exception as e:
            print(f"Error searching ESGF: {e}")
            return []

    def _load_ssp(self, experiment, model, variable, table, member):
        """Internal method to load SSP data"""
        cat = self._get_catalog()

        print(f"Searching ESGF for {experiment.upper()} {model} {variable}...")

        results = cat.search(
            project="CMIP6",
            activity_id="ScenarioMIP",
            experiment_id=experiment,
            source_id=model,
            variable_id=variable,
            table_id=table,
            variant_label=member,
        )

        ds_dict = results.to_dataset_dict()

        if len(ds_dict) == 0:
            raise ValueError(f"No data found for {experiment} {model} {variable}")

        first_key = next(iter(ds_dict.keys()))
        print(f"✓ Loaded: {first_key}")

        return ds_dict[first_key]
