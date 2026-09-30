"""Artifact adapters.

Each adapter understands one artifact family and turns it into the canonical
dashboard schemas. Adapters are strictly read-only: they open files, they
never write, and they never load a model or touch the database.

Every adapter exposes the same pair:

    detect(path) -> bool      cheap, tolerant, no exceptions on junk
    load(path, root=None)     the canonical object, with `problems` naming
                              anything the artifact does not record

An artifact that no adapter claims is listed as UNSUPPORTED_SCHEMA by the
registry rather than being silently skipped.
"""

from . import legacy, stage5, training

ADAPTERS = (stage5, legacy, training)

__all__ = ["ADAPTERS", "legacy", "stage5", "training"]
