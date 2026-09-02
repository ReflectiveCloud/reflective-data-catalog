"""Typed exception hierarchy for reflective-data-catalog (plan R13).

This module is a leaf: it imports nothing package-internal, so every other
module can raise from it without creating import cycles.
"""

from __future__ import annotations


class CatalogError(Exception):
    """The catalog file is missing, malformed, or has an unsupported schema."""


class SourceNotFoundError(CatalogError, AttributeError):
    """An unknown source name was requested.

    Subclasses AttributeError so ``hasattr``/``getattr`` semantics and
    notebook tab-completion keep working when raised from ``__getattr__``.
    """


class DataNotFoundError(CatalogError):
    """A rendered URL matched no data, or matched data impurely.

    Raised when a glob matches nothing, when a multi-file match set mixes
    ensemble/stream/variant facets (selection purity, plan R5), or when a
    combined time axis is non-monotonic.
    """


class MissingCredentialsError(CatalogError):
    """A required credential or account identifier is not configured.

    The message names the missing configuration (for example the
    ``CLOUDFLARE_R2_ACCOUNT_ID`` environment variable) instead of leaking a
    provider stack trace.
    """
