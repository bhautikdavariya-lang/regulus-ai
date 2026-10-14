"""Run pytest with regulus.accuracy taken from the pre-change snapshot (production files untouched)."""
import os, sys, regulus
regulus.__path__.insert(0, os.path.abspath(sys.argv[1]) + "/regulus")
import regulus.accuracy.operators as o
assert o.__file__.startswith(os.path.abspath(sys.argv[1])), o.__file__
assert "_permission_over_means" not in open(o.__file__).read()
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider"] + sys.argv[2:]))
