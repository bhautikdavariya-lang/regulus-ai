"""Tests-first baseline on UNCHANGED production: supply only the new operator's NAME (no behaviour), so each row
fails or passes on what production actually decides. Nothing is written to the repository."""
import sys, pytest
from regulus.accuracy import operators as OP
assert not hasattr(OP, "CONFLICT_LIMIT"), "production already changed"
OP.CONFLICT_LIMIT = "limit_direction"
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_accuracy_numeric_limits.py", "-k", "not limit_is_read and not negated_verb and not negation_inside and not within_bounds"]))
