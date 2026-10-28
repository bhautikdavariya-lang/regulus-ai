"""Which FD&C Act sections each 21 CFR part is issued under (switch AU1, 28 Oct 2026).

Every part's <AUTH> line in the eCFR versioner XML lists the U.S. Code sections it implements ("Part 1114:
21 U.S.C. 371, 374, 387a, 387i, 387j"); data/reference/part_fdca_authority.json maps them to the FD&C Act sections held
in the statute store (387j -> 910). A rule's authority is the standard link legal research tools follow from a
regulation to the statute behind it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "part_fdca_authority.json"


@lru_cache(maxsize=1)
def _parts() -> dict[str, list[str]]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))["parts"]
    except (OSError, ValueError, KeyError):
        return {}


def authority(part: str) -> list[str]:
    """The FD&C Act sections the part is issued under, as its Authority line lists them; [] when unknown."""
    return list(_parts().get(str(part), []))
