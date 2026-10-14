import sys, regulus
regulus.__path__.insert(0, sys.argv[1] + "/regulus")
import pytest
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/"]))
