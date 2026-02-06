import intake_esgf


class ESGFHelper:
    """Helper for ESGF data access"""
    
    def __init__(self):
        self._esgf_cat = None
        self.geomip = GeoMIPHelper()
        self.ssp = SSPHelper()
    
    def _get_catalog(self):
        """Lazy initialization of ESGF catalog"""
        if self._esgf_cat is None:
            try:
                from intake_esgf import ESGFCatalog
                self._esgf_cat = ESGFCatalog()
            except ImportError:
                raise ImportError(
                    "intake-esgf is required for ESGF data access. "
                    "Install with: pip install intake-esgf"
                )
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
    
    def list_available_experiments(self, activity_id='GeoMIP'):
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
            results = cat.search(
                project='CMIP6',
                activity_id=activity_id
            )
            
            if hasattr(results, 'df') and len(results.df) > 0:
                experiments = sorted(results.df['experiment_id'].unique())
                
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
    
    def list_available_models(self, experiment_id=None, activity_id='GeoMIP'):
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
        
        search_params = {
            'project': 'CMIP6',
            'activity_id': activity_id
        }
        
        if experiment_id:
            search_params['experiment_id'] = experiment_id
            print(f"Searching for models with {activity_id}/{experiment_id}...")
        else:
            print(f"Searching for all {activity_id} models...")
        
        try:
            results = cat.search(**search_params)
            
            if hasattr(results, 'df') and len(results.df) > 0:
                models = sorted(results.df['source_id'].unique())
                
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
    
    def g6sulfur(self, model='UKESM1-0-LL', variable='tas', table='Amon', 
                 member='r1i1p1f2'):
        """Load G6sulfur data from ESGF"""
        return self._load_geomip('G6sulfur', model, variable, table, member)
    
    def g6solar(self, model='UKESM1-0-LL', variable='tas', table='Amon',
                member='r1i1p1f2'):
        """Load G6solar data from ESGF"""
        return self._load_geomip('G6solar', model, variable, table, member)
    
    def _load_geomip(self, experiment, model, variable, table, member):
        """Internal method to load GeoMIP data"""
        try:
            from intake_esgf import ESGFCatalog
        except ImportError:
            raise ImportError("intake-esgf required: pip install intake-esgf")
        
        cat = ESGFCatalog()
        
        print(f"Searching ESGF for {experiment} {model} {variable}...")
        
        results = cat.search(
            project='CMIP6',
            activity_id='GeoMIP',
            experiment_id=experiment,
            source_id=model,
            variable_id=variable,
            table_id=table,
            variant_label=member
        )
        
        ds_dict = results.to_dataset_dict()
        
        if len(ds_dict) == 0:
            raise ValueError(f"No data found for {experiment} {model} {variable}")
        
        first_key = list(ds_dict.keys())[0]
        print(f"✓ Loaded: {first_key}")
        
        return ds_dict[first_key]


class SSPHelper:
    """Helper for CMIP6 SSP scenarios"""
    
    def ssp245(self, model='UKESM1-0-LL', variable='tas', table='Amon',
               member='r1i1p1f2'):
        """Load SSP2-4.5 scenario"""
        return self._load_ssp('ssp245', model, variable, table, member)
    
    def ssp585(self, model='UKESM1-0-LL', variable='tas', table='Amon',
               member='r1i1p1f2'):
        """Load SSP5-8.5 scenario"""
        return self._load_ssp('ssp585', model, variable, table, member)
    
    def ssp126(self, model='UKESM1-0-LL', variable='tas', table='Amon',
               member='r1i1p1f2'):
        """Load SSP1-2.6 scenario"""
        return self._load_ssp('ssp126', model, variable, table, member)
    
    def _load_ssp(self, experiment, model, variable, table, member):
        """Internal method to load SSP data"""
        try:
            from intake_esgf import ESGFCatalog
        except ImportError:
            raise ImportError("intake-esgf required: pip install intake-esgf")
        
        cat = ESGFCatalog()
        
        print(f"Searching ESGF for {experiment.upper()} {model} {variable}...")
        
        results = cat.search(
            project='CMIP6',
            activity_id='ScenarioMIP',
            experiment_id=experiment,
            source_id=model,
            variable_id=variable,
            table_id=table,
            variant_label=member
        )
        
        ds_dict = results.to_dataset_dict()
        
        if len(ds_dict) == 0:
            raise ValueError(f"No data found for {experiment} {model} {variable}")
        
        first_key = list(ds_dict.keys())[0]
        print(f"✓ Loaded: {first_key}")
        
        return ds_dict[first_key]
