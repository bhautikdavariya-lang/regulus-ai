"""Validator precision switches (23 Oct 2026, holdout failure analysis, fix A).

Correct drafts were withheld by validator findings that are themselves false (9 of 63 non-PASS holdout answers).
REGULUS_VALIDATOR_PRECISION lists the fixes switched on, e.g. "A1,A2,A3"; empty (the default) keeps the validator
exactly as it was. Each fix ships only after the exact replay of the recorded answers (37 holdout PASS rows
unchanged or re-scored PASS, the named misleading drafts still withheld) and a blind answer A/B.
  A1  a citation whose number the evidence carries is not a figure ("§74.705(a)(1)" read as "74")
  A2  a scoped absence statement ("these provisions set no limit on the amount") is checked against the cited
      text's limiting terms instead of word overlap; unscoped denials stay errors
  A3  whole sentences that carry no citation and fail support (or repeat a supported sentence) are dropped and the
      rest re-validated, before the draft is handed back to the model
"""
from __future__ import annotations

import os

VALIDATOR_PRECISION = frozenset(x.strip().upper() for x in os.environ.get("REGULUS_VALIDATOR_PRECISION", "").split(",") if x.strip())


def enabled(fix: str) -> bool:
    return fix in VALIDATOR_PRECISION
