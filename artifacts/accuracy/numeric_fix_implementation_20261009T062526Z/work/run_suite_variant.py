import os, sys, regulus
regulus.__path__.insert(0, os.path.abspath(sys.argv[1]) + "/regulus")
import regulus.accuracy.operators as o
assert o.__file__.startswith(os.path.abspath(sys.argv[1])), o.__file__
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/"] + sys.argv[2:]))
