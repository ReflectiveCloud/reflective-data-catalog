"""Tests for CloudFileSystem (obstore mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reflective_data_catalog.exceptions import MissingCredentialsError
from reflective_data_catalog.storage import CloudFileSystem


class TestURLParsing:
    """Tests for URL scheme detection and parsing."""

    def test_s3_url(self):
        fs = CloudFileSystem()
        store_key, bucket, rel = fs._parse_url("s3://my-bucket/path/to/file")
        assert store_key == "s3://my-bucket"
        assert bucket == "my-bucket"
        assert rel == "path/to/file"

    def test_gs_url(self):
        fs = CloudFileSystem()
        store_key, bucket, rel = fs._parse_url("gs://gcs-bucket/data")
        assert store_key == "gs://gcs-bucket"
        assert bucket == "gcs-bucket"
        assert rel == "data"

    def test_az_url(self):
        fs = CloudFileSystem()
        store_key, _bucket, rel = fs._parse_url("az://container/blob")
        assert store_key == "az://container"
        assert rel == "blob"

    def test_r2_url(self):
        fs = CloudFileSystem(r2_account_id="abc123")
        store_key, bucket, rel = fs._parse_url("r2://my-r2-bucket/data/file.nc")
        assert store_key == "r2://my-r2-bucket"
        assert bucket == "my-r2-bucket"
        assert rel == "data/file.nc"

    def test_bare_path_defaults_to_s3(self):
        fs = CloudFileSystem()
        store_key, bucket, rel = fs._parse_url("bucket/path/file")
        assert store_key == "s3://bucket"
        assert bucket == "bucket"
        assert rel == "path/file"

    def test_leading_slash_stripped(self):
        fs = CloudFileSystem()
        _, _, rel = fs._parse_url("s3://bucket/path")
        assert not rel.startswith("/")


class TestCloudFileSystem:
    """Tests for CloudFileSystem methods (obstore calls mocked)."""

    @patch("reflective_data_catalog.storage.from_url")
    def test_get_store_caches(self, mock_from_url):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store

        fs = CloudFileSystem()
        store1, _, _ = fs._get_store("s3://bucket/path1")
        store2, _, _ = fs._get_store("s3://bucket/path2")

        assert store1 is store2
        assert mock_from_url.call_count == 1  # only created once

    @patch("reflective_data_catalog.storage.from_url")
    def test_get_store_different_buckets(self, mock_from_url):
        mock_from_url.side_effect = lambda key, **kw: MagicMock(name=key)

        fs = CloudFileSystem()
        s1, _, _ = fs._get_store("s3://bucket-a/path")
        s2, _, _ = fs._get_store("s3://bucket-b/path")

        assert s1 is not s2
        assert mock_from_url.call_count == 2

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_glob(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store

        mock_obstore.list.return_value = [
            [
                {"path": "data/tas_2020.nc"},
                {"path": "data/tas_2021.nc"},
                {"path": "data/pr_2020.nc"},
            ]
        ]

        fs = CloudFileSystem()
        results = fs.glob("s3://bucket/data/tas_*.nc")

        assert results == [
            "s3://bucket/data/tas_2020.nc",
            "s3://bucket/data/tas_2021.nc",
        ]

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_ls_files_only(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store

        mock_obstore.list_with_delimiter.return_value = {
            "objects": [
                {"path": "data/file1.nc", "size": 100},
                {"path": "data/file2.nc", "size": 200},
            ],
            "common_prefixes": [],
        }

        fs = CloudFileSystem()
        items = fs.ls("s3://bucket/data/")
        assert items == ["s3://bucket/data/file1.nc", "s3://bucket/data/file2.nc"]

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_ls_detail(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store

        mock_obstore.list_with_delimiter.return_value = {
            "objects": [{"path": "data/file.nc", "size": 42}],
            "common_prefixes": ["data/subdir/"],
        }

        fs = CloudFileSystem()
        items = fs.ls("s3://bucket/data/", detail=True)

        assert len(items) == 2
        assert items[0]["type"] == "file"
        assert items[0]["size"] == 42
        assert items[1]["type"] == "directory"

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_exists_file(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store
        mock_obstore.head.return_value = {}  # no error ⇒ exists

        fs = CloudFileSystem()
        assert fs.exists("s3://bucket/data/file.nc") is True

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_exists_directory(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store
        mock_obstore.head.side_effect = FileNotFoundError
        mock_obstore.list_with_delimiter.return_value = {
            "objects": [{"path": "data/dir/file.nc"}],
            "common_prefixes": [],
        }

        fs = CloudFileSystem()
        assert fs.exists("s3://bucket/data/dir") is True

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_exists_false(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store
        mock_obstore.head.side_effect = FileNotFoundError
        mock_obstore.list_with_delimiter.return_value = {
            "objects": [],
            "common_prefixes": [],
        }

        fs = CloudFileSystem()
        assert fs.exists("s3://bucket/data/nope") is False

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.from_url")
    def test_open(self, mock_from_url, mock_obstore):
        mock_store = MagicMock()
        mock_from_url.return_value = mock_store

        mock_result = MagicMock()
        mock_result.bytes.return_value = b"hello netcdf"
        mock_obstore.get.return_value = mock_result

        fs = CloudFileSystem()
        f = fs.open("s3://bucket/data/file.nc")
        assert f.read() == b"hello netcdf"

    def test_open_bad_mode(self):
        fs = CloudFileSystem()
        with pytest.raises(ValueError, match="Only 'rb'"):
            fs.open("s3://bucket/data/file.nc", mode="w")


class TestFsspecInfo:
    """Tests for fsspec_info() URL translation."""

    def test_s3_passthrough(self):
        fs = CloudFileSystem()
        url, opts = fs.fsspec_info("s3://bucket/path/file.nc")
        assert url == "s3://bucket/path/file.nc"
        assert opts == {}

    def test_gs_passthrough(self):
        fs = CloudFileSystem()
        url, opts = fs.fsspec_info("gs://bucket/path/file.nc")
        assert url == "gs://bucket/path/file.nc"
        assert opts == {}

    def test_az_passthrough(self):
        fs = CloudFileSystem()
        url, opts = fs.fsspec_info("az://container/path/file.nc")
        assert url == "az://container/path/file.nc"
        assert opts == {}

    def test_r2_translates_to_s3_with_endpoint(self):
        fs = CloudFileSystem(r2_account_id="abc123")
        url, opts = fs.fsspec_info("r2://my-bucket/data/file.nc")
        assert url == "s3://my-bucket/data/file.nc"
        assert opts == {"endpoint_url": "https://abc123.r2.cloudflarestorage.com"}

    def test_bare_path_defaults_to_s3(self):
        fs = CloudFileSystem()
        url, opts = fs.fsspec_info("bucket/path/file.nc")
        assert url == "s3://bucket/path/file.nc"
        assert opts == {}


class TestCloudflareR2:
    """Tests for Cloudflare R2 support (r2:// scheme)."""

    def test_r2_account_id_from_constructor(self):
        fs = CloudFileSystem(r2_account_id="abc123")
        assert fs._r2_account_id == "abc123"

    def test_r2_account_id_from_env(self, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_R2_ACCOUNT_ID", "env_id")
        fs = CloudFileSystem()
        assert fs._r2_account_id == "env_id"

    def test_r2_account_id_fallback_env(self, monkeypatch):
        monkeypatch.delenv("CLOUDFLARE_R2_ACCOUNT_ID", raising=False)
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fallback_id")
        fs = CloudFileSystem()
        assert fs._r2_account_id == "fallback_id"

    def test_r2_account_id_constructor_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_R2_ACCOUNT_ID", "env_id")
        fs = CloudFileSystem(r2_account_id="explicit_id")
        assert fs._r2_account_id == "explicit_id"

    def test_get_r2_endpoint(self):
        fs = CloudFileSystem(r2_account_id="abc123")
        assert fs._get_r2_endpoint() == ("https://abc123.r2.cloudflarestorage.com")

    def test_get_r2_endpoint_missing_account_id(self):
        fs = CloudFileSystem()
        fs._r2_account_id = None  # ensure unset
        with pytest.raises(
            MissingCredentialsError, match="Cloudflare R2 account ID is required"
        ):
            fs._get_r2_endpoint()

    @patch("reflective_data_catalog.storage.S3Store")
    def test_get_store_creates_s3_store_for_r2(self, mock_s3_store_cls):
        mock_store = MagicMock()
        mock_s3_store_cls.return_value = mock_store

        fs = CloudFileSystem(r2_account_id="abc123")
        store, store_key, rel = fs._get_store("r2://my-bucket/data/file.nc")

        assert store is mock_store
        assert store_key == "r2://my-bucket"
        assert rel == "data/file.nc"
        mock_s3_store_cls.assert_called_once_with(
            bucket="my-bucket",
            endpoint="https://abc123.r2.cloudflarestorage.com",
            region="auto",
        )

    @patch("reflective_data_catalog.storage.S3Store")
    def test_get_store_caches_r2(self, mock_s3_store_cls):
        mock_s3_store_cls.return_value = MagicMock()

        fs = CloudFileSystem(r2_account_id="abc123")
        s1, _, _ = fs._get_store("r2://bucket/path1")
        s2, _, _ = fs._get_store("r2://bucket/path2")

        assert s1 is s2
        assert mock_s3_store_cls.call_count == 1

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.S3Store")
    def test_r2_glob(self, mock_s3_store_cls, mock_obstore):
        mock_store = MagicMock()
        mock_s3_store_cls.return_value = mock_store

        mock_obstore.list.return_value = [
            [
                {"path": "data/tas_2020.nc"},
                {"path": "data/tas_2021.nc"},
                {"path": "data/pr_2020.nc"},
            ]
        ]

        fs = CloudFileSystem(r2_account_id="abc123")
        results = fs.glob("r2://my-bucket/data/tas_*.nc")

        assert results == [
            "r2://my-bucket/data/tas_2020.nc",
            "r2://my-bucket/data/tas_2021.nc",
        ]
        mock_obstore.list.assert_called_once_with(mock_store, prefix="data/")

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.S3Store")
    def test_r2_ls(self, mock_s3_store_cls, mock_obstore):
        mock_store = MagicMock()
        mock_s3_store_cls.return_value = mock_store

        mock_obstore.list_with_delimiter.return_value = {
            "objects": [{"path": "data/file1.nc", "size": 50}],
            "common_prefixes": ["data/subdir/"],
        }

        fs = CloudFileSystem(r2_account_id="abc123")
        items = fs.ls("r2://my-bucket/data/", detail=True)

        assert len(items) == 2
        assert items[0] == {
            "name": "r2://my-bucket/data/file1.nc",
            "type": "file",
            "size": 50,
        }
        assert items[1] == {
            "name": "r2://my-bucket/data/subdir",
            "type": "directory",
        }

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.S3Store")
    def test_r2_exists(self, mock_s3_store_cls, mock_obstore):
        mock_store = MagicMock()
        mock_s3_store_cls.return_value = mock_store
        mock_obstore.head.return_value = {}

        fs = CloudFileSystem(r2_account_id="abc123")
        assert fs.exists("r2://my-bucket/data/file.nc") is True

    @patch("reflective_data_catalog.storage.obstore")
    @patch("reflective_data_catalog.storage.S3Store")
    def test_r2_open(self, mock_s3_store_cls, mock_obstore):
        mock_store = MagicMock()
        mock_s3_store_cls.return_value = mock_store

        mock_result = MagicMock()
        mock_result.bytes.return_value = b"r2 data"
        mock_obstore.get.return_value = mock_result

        fs = CloudFileSystem(r2_account_id="abc123")
        f = fs.open("r2://my-bucket/data/file.nc")
        assert f.read() == b"r2 data"

    @patch("reflective_data_catalog.storage.from_url")
    def test_r2_does_not_call_from_url(self, mock_from_url):
        """R2 stores use S3Store directly, never from_url."""
        with patch("reflective_data_catalog.storage.S3Store") as mock_s3:
            mock_s3.return_value = MagicMock()
            fs = CloudFileSystem(r2_account_id="abc123")
            fs._get_store("r2://bucket/path")

        mock_from_url.assert_not_called()


class TestIcechunkStorage:
    """CloudFileSystem.icechunk_storage: the Icechunk handoff."""

    def test_missing_package_explains(self, monkeypatch):
        import sys

        monkeypatch.setitem(sys.modules, "icechunk", None)
        with pytest.raises(ImportError, match=r"Python >= 3\.12"):
            CloudFileSystem().icechunk_storage("s3://b/repo.icechunk")

    def test_unsupported_scheme(self):
        pytest.importorskip("icechunk")
        with pytest.raises(ValueError, match="s3:// only"):
            CloudFileSystem().icechunk_storage("gs://b/repo.icechunk")

    def test_s3_resolves_region_and_anon(self):
        icechunk = pytest.importorskip("icechunk")
        fs = CloudFileSystem()
        with (
            patch.object(fs, "_resolve_s3_region", return_value="us-west-2") as region,
            patch.object(icechunk, "s3_storage") as s3_storage,
        ):
            fs.icechunk_storage("s3://a.b.c/x/repo.icechunk", {"anon": True})
        region.assert_called_once_with("a.b.c")
        s3_storage.assert_called_once_with(
            bucket="a.b.c",
            prefix="x/repo.icechunk",
            region="us-west-2",
            anonymous=True,
            from_env=None,
        )


class TestS3RegionResolution:
    @pytest.mark.parametrize(
        ("bucket", "url"),
        [
            ("plain-bucket", "https://plain-bucket.s3.amazonaws.com"),
            # Dotted names fail TLS on the virtual-hosted endpoint.
            (
                "us-west-2.opendata.source.coop",
                "https://s3.amazonaws.com/us-west-2.opendata.source.coop",
            ),
        ],
    )
    def test_head_url(self, bucket, url):
        response = MagicMock()
        response.__enter__.return_value.headers = {"x-amz-bucket-region": "r"}
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            assert CloudFileSystem()._resolve_s3_region(bucket) == "r"
        assert urlopen.call_args[0][0].full_url == url
