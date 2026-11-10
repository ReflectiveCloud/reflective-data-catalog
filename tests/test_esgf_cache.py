"""Tests for the shared S3 cache behind catalog.esgf (storage mocked)."""

from __future__ import annotations

import io
import json
import warnings
from pathlib import Path

import pandas as pd
import pytest

from reflective_data_catalog import esgf_cache
from reflective_data_catalog.esgf_cache import (
    CACHE_ENV_VAR,
    DEFAULT_CACHE_URL,
    MANIFEST_NAME,
    S3DatasetCache,
    dataset_path,
    resolve_cache_url,
)

ROOT = "s3://bucket/esgf-cache"
DATASET_A = "CMIP6.GeoMIP.MOHC.UKESM1-0-LL.G6sulfur.r1i1p1f2.Amon.tas.gn.v20191113"
DATASET_B = "CMIP6.GeoMIP.MOHC.UKESM1-0-LL.G6sulfur.r2i1p1f2.Amon.tas.gn.v20191113"
PATH_A = "CMIP6/GeoMIP/MOHC/UKESM1-0-LL/G6sulfur/r1i1p1f2/Amon/tas/gn/v20191113"
PATH_B = "CMIP6/GeoMIP/MOHC/UKESM1-0-LL/G6sulfur/r2i1p1f2/Amon/tas/gn/v20191113"


class FakeFS:
    """In-memory stand-in for CloudFileSystem (ls/open/put only)."""

    def __init__(self, ls_error=None, put_error=None):
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.ls_calls = 0
        self.ls_error = ls_error
        self.put_error = put_error

    def ls(self, url, **_):
        self.ls_calls += 1
        if self.ls_error is not None:
            raise self.ls_error
        return []

    def open(self, url, **_):
        if url not in self.objects:
            raise FileNotFoundError(url)
        return io.BytesIO(self.objects[url])

    def put(self, url, data, **_):
        if self.put_error is not None:
            raise self.put_error
        self.objects[url] = Path(data).read_bytes() if isinstance(data, Path) else data
        self.puts.append(url)


def _seed_manifest(fs, dataset_path_, names):
    manifest = {"files": [{"name": n, "size": 1} for n in names]}
    fs.objects[f"{ROOT}/{dataset_path_}/{MANIFEST_NAME}"] = json.dumps(
        manifest
    ).encode()


def _local_dataset(root: Path, rel: str, names: list[str]) -> list[Path]:
    d = root / rel
    d.mkdir(parents=True)
    files = []
    for n in names:
        f = d / n
        f.write_bytes(b"netcdf-bytes-" + n.encode())
        files.append(f)
    return files


# =========================================================================
# Configuration
# =========================================================================


class TestResolveCacheURL:
    def test_default_is_hub_bucket(self, monkeypatch):
        monkeypatch.delenv(CACHE_ENV_VAR, raising=False)
        assert resolve_cache_url() == DEFAULT_CACHE_URL.rstrip("/")
        assert DEFAULT_CACHE_URL.startswith(
            "s3://reflective-persistent-prod-large/esgf-cache"
        )

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv(CACHE_ENV_VAR, "s3://other/prefix/")
        assert resolve_cache_url() == "s3://other/prefix"

    @pytest.mark.parametrize("value", ["off", "OFF", "none", "false", "0", ""])
    def test_env_can_disable(self, monkeypatch, value):
        monkeypatch.setenv(CACHE_ENV_VAR, value)
        assert resolve_cache_url() is None

    def test_explicit_wins_over_env(self, monkeypatch):
        monkeypatch.setenv(CACHE_ENV_VAR, "off")
        assert resolve_cache_url("s3://explicit/x") == "s3://explicit/x"

    def test_explicit_false_disables(self, monkeypatch):
        monkeypatch.setenv(CACHE_ENV_VAR, "s3://other/prefix")
        assert resolve_cache_url(False) is None


def test_dataset_path_drops_index_and_uses_drs_layout():
    assert dataset_path(DATASET_A + "|discovery.west.esgf.io") == PATH_A
    assert dataset_path(DATASET_A) == PATH_A


# =========================================================================
# S3DatasetCache
# =========================================================================


class TestS3DatasetCache:
    def test_usable_checks_once(self):
        fs = FakeFS()
        cache = S3DatasetCache(ROOT, fs=fs)
        assert cache.usable() and cache.usable()
        assert fs.ls_calls == 1

    def test_unreachable_bucket_warns_once_and_disables(self):
        fs = FakeFS(ls_error=PermissionError("403 Forbidden"))
        cache = S3DatasetCache(ROOT, fs=fs)
        with pytest.warns(UserWarning, match="local cache"):
            assert cache.usable() is False
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert cache.usable() is False
        assert fs.ls_calls == 1

    def test_lookup_miss(self):
        assert S3DatasetCache(ROOT, fs=FakeFS()).lookup(DATASET_A) is None

    def test_lookup_hit_returns_urls_in_manifest_order(self):
        fs = FakeFS()
        _seed_manifest(fs, PATH_A, ["a_2020.nc", "a_2050.nc"])
        urls = S3DatasetCache(ROOT, fs=fs).lookup(DATASET_A + "|idx")
        assert urls == [f"{ROOT}/{PATH_A}/a_2020.nc", f"{ROOT}/{PATH_A}/a_2050.nc"]

    def test_store_uploads_files_then_manifest(self, tmp_path):
        fs = FakeFS()
        files = _local_dataset(tmp_path, PATH_A, ["a_2050.nc", "a_2020.nc"])
        urls = S3DatasetCache(ROOT, fs=fs).store(DATASET_A, files, [tmp_path])

        assert urls == [f"{ROOT}/{PATH_A}/a_2020.nc", f"{ROOT}/{PATH_A}/a_2050.nc"]
        # the manifest goes up last, so a half-uploaded dataset is never "cached"
        assert fs.puts[-1] == f"{ROOT}/{PATH_A}/{MANIFEST_NAME}"
        assert fs.objects[urls[0]] == b"netcdf-bytes-a_2020.nc"
        manifest = json.loads(fs.objects[fs.puts[-1]])
        assert [f["name"] for f in manifest["files"]] == ["a_2020.nc", "a_2050.nc"]
        assert manifest["dataset_id"] == DATASET_A

    def test_store_deletes_local_copies_and_empty_dirs(self, tmp_path):
        fs = FakeFS()
        cache_root = tmp_path / "cache"
        files = _local_dataset(cache_root, PATH_A, ["a.nc"])
        S3DatasetCache(ROOT, fs=fs).store(DATASET_A, files, [cache_root])

        assert not files[0].exists()
        assert cache_root.exists()  # the cache root itself is kept
        assert list(cache_root.iterdir()) == []

    def test_store_removes_failed_download_temp_files(self, tmp_path):
        fs = FakeFS()
        files = _local_dataset(tmp_path, PATH_A, ["a.nc"])
        d = files[0].parent
        (d / "a.nc.u5jf_3sh").write_bytes(b"")  # intake-esgf mkstemp leftover
        (d / "a.nc.9o20o_c6").write_bytes(b"partial")
        keep = d / "a.nc.notes.txt"  # not a mkstemp name
        keep.write_text("mine")
        S3DatasetCache(ROOT, fs=fs).store(DATASET_A, files, [tmp_path])
        assert sorted(p.name for p in d.iterdir()) == ["a.nc.notes.txt"]

    def test_store_never_deletes_outside_local_cache(self, tmp_path):
        fs = FakeFS()
        dataroot = tmp_path / "dataroot"  # e.g. a read-only esg_dataroot mirror
        files = _local_dataset(dataroot, PATH_A, ["a.nc"])
        S3DatasetCache(ROOT, fs=fs).store(DATASET_A, files, [tmp_path / "cache"])
        assert files[0].exists()

    def test_lookup_after_store_round_trips(self, tmp_path):
        fs = FakeFS()
        cache = S3DatasetCache(ROOT, fs=fs)
        files = _local_dataset(tmp_path, PATH_A, ["a.nc", "b.nc"])
        stored = cache.store(DATASET_A, files, [tmp_path])
        assert cache.lookup(DATASET_A) == stored

    def test_upload_failure_keeps_local_files_and_stops_uploading(self, tmp_path):
        fs = FakeFS(put_error=PermissionError("AccessDenied"))
        cache = S3DatasetCache(ROOT, fs=fs)
        files = _local_dataset(tmp_path, PATH_A, ["a.nc"])
        with pytest.warns(UserWarning, match="kept in the local cache"):
            out = cache.store(DATASET_A, files, [tmp_path])
        assert out == [str(files[0])]
        assert files[0].exists()

        fs.put_error = None  # even if S3 recovers, this session stops trying
        more = _local_dataset(tmp_path, PATH_B, ["b.nc"])
        assert cache.store(DATASET_B, more, [tmp_path]) == [str(more[0])]
        assert fs.puts == []


# =========================================================================
# CachedESGFCatalog (needs intake-esgf)
# =========================================================================


@pytest.fixture
def cached_cls(monkeypatch):
    intake_esgf = pytest.importorskip("intake_esgf")
    cls = esgf_cache.cached_catalog_class()
    # Never touch indices, the network or ~/.esgf: construct bare catalogs.
    monkeypatch.setattr(intake_esgf.ESGFCatalog, "__init__", _bare_init)
    return cls


def _bare_init(self):
    self.indices = []
    self.df = None
    self.project = None
    self.local_cache = []
    self.esg_dataroot = []


def _catalog(cls, tmp_path, fs, rows):
    from intake_esgf.projects import projects

    cat = cls()
    cat.project = projects["cmip6"]
    cat.local_cache = [tmp_path]
    cat.df = pd.DataFrame(rows)
    cat.s3_cache = S3DatasetCache(ROOT, fs=fs)
    return cat


def _row(member, dataset):
    return {
        "mip_era": "CMIP6",
        "activity_id": "GeoMIP",
        "institution_id": "MOHC",
        "source_id": "UKESM1-0-LL",
        "experiment_id": "G6sulfur",
        "member_id": member,
        "table_id": "Amon",
        "variable_id": "tas",
        "grid_label": "gn",
        "version": "20191113",
        "project": "CMIP6",
        "id": [f"{dataset}|discovery.west.esgf.io", f"{dataset}|esgf-node.llnl.gov"],
    }


class TestCachedESGFCatalog:
    def test_serves_hits_from_s3_and_downloads_only_misses(
        self, cached_cls, tmp_path, monkeypatch
    ):
        import intake_esgf

        fs = FakeFS()
        _seed_manifest(fs, PATH_A, ["a.nc"])
        cat = _catalog(
            cached_cls,
            tmp_path,
            fs,
            [_row("r1i1p1f2", DATASET_A), _row("r2i1p1f2", DATASET_B)],
        )
        downloaded = _local_dataset(tmp_path, PATH_B, ["b.nc"])
        seen = {}

        def fake_base(self, **kwargs):
            seen["members"] = list(self.df["member_id"])
            seen["kwargs"] = kwargs
            key = ".".join(self.df.iloc[0][self.project.master_id_facets()])
            return {key: list(downloaded)}

        monkeypatch.setattr(intake_esgf.ESGFCatalog, "to_path_dict", fake_base)

        out = cat.to_path_dict(quiet=True)

        assert seen["members"] == ["r2i1p1f2"]  # the cached dataset is skipped
        assert seen["kwargs"]["minimal_keys"] is False
        assert out == {
            "r1i1p1f2": [f"{ROOT}/{PATH_A}/a.nc"],
            "r2i1p1f2": [f"{ROOT}/{PATH_B}/b.nc"],
        }
        assert not downloaded[0].exists()  # uploaded, then freed locally
        assert f"{ROOT}/{PATH_B}/{MANIFEST_NAME}" in fs.objects

    def test_full_keys_when_minimal_keys_false(self, cached_cls, tmp_path):
        fs = FakeFS()
        _seed_manifest(fs, PATH_A, ["a.nc"])
        cat = _catalog(cached_cls, tmp_path, fs, [_row("r1i1p1f2", DATASET_A)])
        out = cat.to_path_dict(minimal_keys=False, quiet=True)
        assert list(out) == [DATASET_A.rsplit(".v", 1)[0]]
        assert list(cat.df["key"]) == list(out)  # to_dataset_dict reads df["key"]

    @pytest.mark.parametrize(
        "kwargs",
        [{"prefer_streaming": True}, {"globus_endpoint": "uuid"}],
    )
    def test_streaming_and_globus_bypass_the_cache(
        self, cached_cls, tmp_path, monkeypatch, kwargs
    ):
        import intake_esgf

        fs = FakeFS()
        cat = _catalog(cached_cls, tmp_path, fs, [_row("r1i1p1f2", DATASET_A)])
        monkeypatch.setattr(
            intake_esgf.ESGFCatalog, "to_path_dict", lambda self, **kw: {"x": ["y"]}
        )
        assert cat.to_path_dict(**kwargs) == {"x": ["y"]}
        assert fs.ls_calls == 0

    def test_unreachable_cache_falls_back_to_intake_esgf(
        self, cached_cls, tmp_path, monkeypatch
    ):
        import intake_esgf

        fs = FakeFS(ls_error=PermissionError("403"))
        cat = _catalog(cached_cls, tmp_path, fs, [_row("r1i1p1f2", DATASET_A)])
        monkeypatch.setattr(
            intake_esgf.ESGFCatalog, "to_path_dict", lambda self, **kw: {"x": ["y"]}
        )
        with pytest.warns(UserWarning):
            assert cat.to_path_dict() == {"x": ["y"]}

    def test_no_cache_delegates(self, cached_cls, tmp_path, monkeypatch):
        import intake_esgf

        cat = _catalog(cached_cls, tmp_path, FakeFS(), [_row("r1i1p1f2", DATASET_A)])
        cat.s3_cache = None
        monkeypatch.setattr(
            intake_esgf.ESGFCatalog, "to_path_dict", lambda self, **kw: {"x": ["y"]}
        )
        assert cat.to_path_dict() == {"x": ["y"]}

    def test_clone_keeps_class_and_cache(self, cached_cls, tmp_path):
        cat = _catalog(cached_cls, tmp_path, FakeFS(), [_row("r1i1p1f2", DATASET_A)])
        twin = cat.clone()  # intake-esgf clones to look up cell measures
        assert type(twin) is cached_cls
        assert twin.s3_cache is cat.s3_cache

    def test_to_dataset_dict_prefers_h5netcdf_for_s3_urls(
        self, cached_cls, tmp_path, monkeypatch
    ):
        import intake_esgf
        import xarray as xr

        seen = {}

        def fake_base(self, *a, **kw):
            seen["order"] = tuple(xr.get_options()["netcdf_engine_order"])
            return {}

        monkeypatch.setattr(intake_esgf.ESGFCatalog, "to_dataset_dict", fake_base)
        cat = _catalog(cached_cls, tmp_path, FakeFS(), [_row("r1i1p1f2", DATASET_A)])
        cat.to_dataset_dict()
        assert seen["order"][0] == "h5netcdf"
