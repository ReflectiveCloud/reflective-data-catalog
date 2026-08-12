#!/usr/bin/env python3
"""Rerunnable bucket audit for data-catalog.yaml (plan U1/U12).

Renders every catalog entry's default URL and verifies it against cloud
storage using delimiter listings only (no data downloads). Writes a
timestamped inventory to tests/fixtures/bucket_inventory.json.

Entries whose buckets the current credentials cannot reach are recorded as
``unverified`` with the reason — the audit never fails outright on a
permission error, so it can run with any subset of credentials and be
re-run when more arrive (U12 re-audit diffs against the committed fixture).

Usage:
    python scripts/bucket_audit.py                 # audit, write inventory
    python scripts/bucket_audit.py --diff          # audit, diff vs fixture
    python scripts/bucket_audit.py --deep          # + chunk-completeness
    python scripts/bucket_audit.py --render        # render docs from matrix

Credentials: AWS via the default credential chain (env or ~/.aws);
Cloudflare R2 via CLOUDFLARE_R2_ACCOUNT_ID (+ R2 keys) when r2:// URLs
appear in the catalog. Least-privilege read/list-only credentials suffice.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "src" / "reflective_data_catalog" / "data-catalog.yaml"
MATRIX = REPO / "src" / "reflective_data_catalog" / "migration_matrix.yaml"
INVENTORY = REPO / "tests" / "fixtures" / "bucket_inventory.json"
MATRIX_DOC = REPO / "docs" / "migration-matrix.md"

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def load_catalog() -> dict:
    with CATALOG.open() as f:
        return yaml.safe_load(f)


def entry_defaults(entry: dict) -> dict:
    return {
        name: spec.get("default")
        for name, spec in (entry.get("parameters") or {}).items()
    }


def render(template: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


def get_fs(storage_options: dict):
    """Build an s3fs filesystem honoring per-entry anon and R2 endpoints."""
    import s3fs

    opts = {}
    if storage_options.get("anon"):
        opts["anon"] = True
    endpoint = storage_options.get("endpoint_url")
    if endpoint:
        opts["client_kwargs"] = {"endpoint_url": endpoint}
    return s3fs.S3FileSystem(**opts)


def r2_endpoint() -> str | None:
    import os

    account = os.environ.get("CLOUDFLARE_R2_ACCOUNT_ID") or os.environ.get(
        "CLOUDFLARE_ACCOUNT_ID"
    )
    return f"https://{account}.r2.cloudflarestorage.com" if account else None


def strip_scheme(url: str) -> tuple[str, str]:
    scheme, _, rest = url.partition("://")
    return scheme, rest


def audit_zarr(fs, path: str, deep: bool) -> dict:
    """Existence + format + consolidated-metadata presence for a Zarr store."""
    result: dict = {}
    parent = path.rstrip("/").rsplit("/", 1)[0]
    name = path.rstrip("/").rsplit("/", 1)[1]
    try:
        listing = fs.ls(parent, detail=False)
    except FileNotFoundError:
        return {"exists": False}
    prefixes = {p.rstrip("/").rsplit("/", 1)[-1] for p in listing}
    result["exists"] = name in prefixes
    if not result["exists"]:
        return result
    children = {c.rsplit("/", 1)[-1] for c in fs.ls(path, detail=False)}
    result["zarr_format"] = (
        3
        if "zarr.json" in children
        else 2
        if ".zgroup" in children or ".zmetadata" in children
        else None
    )
    result["consolidated"] = ".zmetadata" in children or "zarr.json" in children
    if deep:
        keys = fs.find(path)
        result["object_count"] = len(keys)
    return result


def audit_glob(fs, pattern: str) -> dict:
    """Match count + basenames for a NetCDF glob."""
    try:
        matches = fs.glob(pattern)
    except FileNotFoundError:
        return {"exists": False, "match_count": 0}
    return {
        "exists": bool(matches),
        "match_count": len(matches),
        "sample": sorted(matches)[:3],
    }


def observe_facets(fs, template: str, values: dict) -> dict:
    """Delimiter-list one level at each templated segment; record vocabulary.

    ``template`` is a scheme-stripped path that may contain {{placeholders}}.
    """
    facets: dict = {}
    segments = template.split("/")
    built = []
    for seg in segments:
        m = PLACEHOLDER.search(seg)
        if m:
            param = m.group(1)
            listing_path = "/".join(built)
            try:
                listing = fs.ls(listing_path, detail=False)
                names = sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in listing)[:50]
                facets[param] = names
            except Exception as exc:
                facets[param] = f"unlisted: {type(exc).__name__}"
            built.append(render(seg, values))
        else:
            built.append(seg)
        if "*" in seg:
            break
    return facets


def audit_entry(name: str, entry: dict, deep: bool) -> dict:
    args = entry.get("args") or {}
    urlpaths = args.get("urlpath")
    urlpaths = urlpaths if isinstance(urlpaths, list) else [urlpaths]
    storage_options = args.get("storage_options") or {}
    defaults = entry_defaults(entry)
    record: dict = {
        "driver": entry.get("driver"),
        "anon": bool(storage_options.get("anon")),
        "urls": [],
    }
    for template in urlpaths:
        if template is None:
            record["urls"].append({"error": "missing urlpath"})
            continue
        scheme, _ = strip_scheme(template)
        rendered = render(template, defaults)
        url_rec: dict = {"template": template, "rendered_default": rendered}
        opts = dict(storage_options)
        if scheme == "r2":
            endpoint = r2_endpoint()
            if not endpoint:
                url_rec["status"] = "unverified:no_r2_account_id"
                record["urls"].append(url_rec)
                continue
            opts["endpoint_url"] = endpoint
            rendered = rendered.replace("r2://", "s3://", 1)
        try:
            fs = get_fs(opts)
            path = rendered.split("://", 1)[1]
            if entry.get("driver") == "zarr":
                url_rec.update(audit_zarr(fs, path, deep))
            else:
                url_rec.update(audit_glob(fs, path))
            url_rec["facets"] = observe_facets(
                fs, template.split("://", 1)[1], defaults
            )
            url_rec["status"] = "verified"
        except PermissionError:
            url_rec["status"] = "unverified:access_denied"
        except Exception as exc:
            url_rec["status"] = f"unverified:{type(exc).__name__}"
        record["urls"].append(url_rec)
    return record


def run_audit(deep: bool) -> dict:
    catalog = load_catalog()
    inventory = {
        "audited_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "catalog_version": (catalog.get("metadata") or {}).get("version"),
        "entries": {},
    }
    for name, entry in (catalog.get("sources") or {}).items():
        print(f"auditing {name} ...", file=sys.stderr)
        inventory["entries"][name] = audit_entry(name, entry, deep)
    return inventory


def render_docs() -> None:
    with MATRIX.open() as f:
        matrix = yaml.safe_load(f)
    lines = [
        "# Migration matrix (rendered)",
        "",
        f"Rendered from `src/reflective_data_catalog/migration_matrix.yaml` "
        f"(schema v{matrix.get('version')}). Do not edit by hand.",
        "",
        "## Source dispositions",
        "",
        "| Old name | New entry | Backend | Status | Old defaults | New defaults |",
        "|---|---|---|---|---|---|",
    ]
    for old, row in (matrix.get("sources") or {}).items():
        lines.append(
            f"| `{old}` | `{row.get('new_entry')}` | {row.get('backend')} "
            f"| {row.get('status')} | {row.get('old_defaults')} "
            f"| {row.get('new_defaults')} |"
        )
    lines += ["", "## Entry stability", "", "| Entry | Stability |", "|---|---|"]
    for entry, stab in (matrix.get("stability") or {}).items():
        lines.append(f"| `{entry}` | {stab} |")
    lines += ["", "## Kwarg dispositions", "", "| Kwarg | Disposition |", "|---|---|"]
    for kw, row in (matrix.get("kwargs") or {}).items():
        lines.append(f"| `{kw}` | {row} |")
    lines += ["", "## API changes", ""]
    for row in matrix.get("api") or []:
        lines.append(f"- {row}")
    MATRIX_DOC.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_DOC.write_text("\n".join(lines) + "\n")
    print(f"wrote {MATRIX_DOC}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true", help="chunk-count zarr stores")
    parser.add_argument("--diff", action="store_true", help="diff against fixture")
    parser.add_argument("--render", action="store_true", help="render matrix docs")
    args = parser.parse_args()

    if args.render:
        render_docs()
        return 0

    inventory = run_audit(args.deep)
    if args.diff:
        if not INVENTORY.exists():
            print("no committed fixture to diff against", file=sys.stderr)
            return 1
        old = json.loads(INVENTORY.read_text())
        drift = []
        for name, rec in inventory["entries"].items():
            old_rec = old.get("entries", {}).get(name)
            if old_rec is None:
                drift.append(f"new entry: {name}")
                continue
            for new_url, old_url in zip(rec["urls"], old_rec.get("urls", []), strict=False):
                for key in ("status", "exists", "match_count", "zarr_format"):
                    if new_url.get(key) != old_url.get(key):
                        drift.append(
                            f"{name}: {key} {old_url.get(key)!r} -> {new_url.get(key)!r}"
                        )
        for name in old.get("entries", {}):
            if name not in inventory["entries"]:
                drift.append(f"removed entry: {name}")
        if drift:
            print("\n".join(drift))
            return 2
        print("no drift")
        return 0

    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"wrote {INVENTORY}")
    unverified = [
        f"{name} ({url.get('status')})"
        for name, rec in inventory["entries"].items()
        for url in rec["urls"]
        if url.get("status") != "verified"
    ]
    if unverified:
        print("unverified entries (need credentials):", file=sys.stderr)
        for item in unverified:
            print(f"  - {item}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
